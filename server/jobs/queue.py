"""SQLite 작업 큐 (docs/DESIGN.md §8).

- queued → processing 선점은 BEGIN IMMEDIATE 트랜잭션 하나로 원자적으로 한다.
- 동시 분석은 1건이다. lease가 살아 있는 processing 작업이 있으면 선점하지 않는다.
- 긴 추론 중에는 heartbeat()로 lease를 주기적으로 연장한다.
- lease가 만료된 processing 작업은 재시도 상한 안에서 queued로 되돌린다(재시작 복구).
- 상태를 바꾸는 쓰기는 lease_owner가 일치할 때만 적용한다(중복 실행 방지).
- URL 원문은 저장하지 않는다. video ID와 소유자 토큰의 해시만 저장한다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    analysis_id       TEXT PRIMARY KEY,
    owner_hash        TEXT NOT NULL,
    youtube_video_id  TEXT NOT NULL,
    job_status        TEXT NOT NULL,
    stage             TEXT,
    completed_stages  TEXT NOT NULL DEFAULT '[]',
    result_json       TEXT,
    failure_reason    TEXT,
    attempts          INTEGER NOT NULL DEFAULT 0,
    lease_owner       TEXT,
    lease_expires_at  REAL,
    cancel_requested  INTEGER NOT NULL DEFAULT 0,
    created_at        REAL NOT NULL,
    started_at        REAL,
    finished_at       REAL,
    -- 내부 실행 기록(축별 장치·열 상태, 시도별 누적). API·_to_job은 읽지 않는다
    run_info_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (job_status, created_at);
"""

LEASE_OK = "ok"
LEASE_LOST = "lost"
LEASE_CANCEL = "cancel_requested"


class PreconditionFailed(Exception):
    """If-Match가 현재 작업 수명주기와 다르다."""


def lifecycle_etag(job: Job) -> str:
    phase = "active" if job.job_status in ("queued", "processing") else job.job_status
    return f'"{job.analysis_id}:{phase}"'


class QueueFull(Exception):
    """대기열이 가득 찼다."""


@dataclass(frozen=True)
class Job:
    analysis_id: str
    youtube_video_id: str
    job_status: str
    stage: Optional[str]
    completed_stages: list[str]
    result: Optional[dict[str, Any]]
    failure_reason: Optional[str]
    attempts: int


def _to_job(row: sqlite3.Row) -> Job:
    return Job(
        analysis_id=row["analysis_id"],
        youtube_video_id=row["youtube_video_id"],
        job_status=row["job_status"],
        stage=row["stage"],
        completed_stages=json.loads(row["completed_stages"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        failure_reason=row["failure_reason"],
        attempts=row["attempts"],
    )


class JobQueue:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            # 열이 생기기 전에 만든 DB에는 열만 더한다(기존 행은 그대로)
            if "run_info_json" not in {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}:
                conn.execute("ALTER TABLE jobs ADD COLUMN run_info_json TEXT")
        finally:
            conn.close()

    @contextmanager
    def _tx(self, timeout: float = 5) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # ---- API 쪽 -------------------------------------------------------

    def enqueue(self, youtube_video_id: str, owner_hash: str, max_queued: int) -> str:
        analysis_id = str(uuid.uuid4())
        with self._tx() as conn:
            (queued,) = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE job_status = 'queued'"
            ).fetchone()
            if queued >= max_queued:
                raise QueueFull()
            conn.execute(
                "INSERT INTO jobs (analysis_id, owner_hash, youtube_video_id,"
                " job_status, created_at) VALUES (?, ?, ?, 'queued', ?)",
                (analysis_id, owner_hash, youtube_video_id, time.time()),
            )
        return analysis_id

    def get(self, analysis_id: str, owner_hash: str) -> Optional[Job]:
        """소유자가 다르면 없는 작업과 똑같이 None이다."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE analysis_id = ? AND owner_hash = ?",
                (analysis_id, owner_hash),
            ).fetchone()
        return _to_job(row) if row else None

    def request_cancel(self, analysis_id: str, owner_hash: str) -> bool:
        """접수만 한다. queued도 Worker의 정리가 끝난 뒤 cancelled가 된다."""
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE jobs SET cancel_requested = 1"
                " WHERE analysis_id = ? AND owner_hash = ?"
                " AND job_status IN ('queued', 'processing')",
                (analysis_id, owner_hash),
            )
            return cur.rowcount == 1

    def cancel_or_delete(
        self, analysis_id: str, owner_hash: str, if_match: Optional[str],
        cleanup: Callable[[str], None],
    ) -> tuple[int, Optional[Job]]:
        """권한·조건·상태 분기와 쓰기를 하나의 트랜잭션으로 처리한다.

        폴더 정리가 실패하면 행을 지우지 않는다. 다음 DELETE에서 재시도할 수 있다.
        """
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE analysis_id = ? AND owner_hash = ?",
                (analysis_id, owner_hash),
            ).fetchone()
            if row is None:
                return 404, None
            job = _to_job(row)
            if if_match is not None and if_match.strip() != "*":
                # 생성한 ETag에는 쉼표가 없고 weak tag는 strong 비교에 일치하지 않는다.
                if lifecycle_etag(job) not in [tag.strip() for tag in if_match.split(",")]:
                    raise PreconditionFailed()
            if job.job_status in ("queued", "processing"):
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1 WHERE analysis_id = ? AND cancel_requested = 0",
                    (analysis_id,),
                )
                return 202, job
            cleanup(analysis_id)
            conn.execute("DELETE FROM jobs WHERE analysis_id = ?", (analysis_id,))
            return 204, None

    # ---- Worker 쪽 ----------------------------------------------------

    def claim(
        self, worker_id: str, lease_seconds: float, max_attempts: int,
        cleanup: Optional[Callable[[str], None]] = None,
    ) -> Optional[Job]:
        now = time.time()
        with self._tx() as conn:
            self._recover_expired(conn, now, max_attempts, cleanup)
            busy = conn.execute(
                "SELECT 1 FROM jobs WHERE job_status = 'processing' LIMIT 1"
            ).fetchone()
            if busy:
                return None
            row = conn.execute(
                "SELECT analysis_id FROM jobs WHERE job_status = 'queued'"
                " ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET job_status = 'processing', stage = NULL,"
                " completed_stages = '[]', attempts = attempts + 1,"
                " lease_owner = ?, lease_expires_at = ?, started_at = ?"
                " WHERE analysis_id = ? AND job_status = 'queued'",
                (worker_id, now + lease_seconds, now, row["analysis_id"]),
            )
            claimed = conn.execute(
                "SELECT * FROM jobs WHERE analysis_id = ?", (row["analysis_id"],)
            ).fetchone()
        return _to_job(claimed)

    @staticmethod
    def _recover_expired(
        conn: sqlite3.Connection, now: float, max_attempts: int,
        cleanup: Optional[Callable[[str], None]] = None,
    ) -> None:
        expired = "job_status = 'processing' AND lease_expires_at < ?"
        if cleanup is not None:
            for row in conn.execute(f"SELECT analysis_id FROM jobs WHERE {expired}", (now,)).fetchall():
                cleanup(row["analysis_id"])
        conn.execute(
            "UPDATE jobs SET job_status = 'cancelled', lease_owner = NULL,"
            f" lease_expires_at = NULL, finished_at = ? WHERE {expired}"
            " AND cancel_requested = 1",
            (now, now),
        )
        conn.execute(
            "UPDATE jobs SET job_status = 'failed',"
            " failure_reason = 'max_attempts_exceeded', lease_owner = NULL,"
            f" lease_expires_at = NULL, finished_at = ? WHERE {expired}"
            " AND attempts >= ?",
            (now, now, max_attempts),
        )
        conn.execute(
            "UPDATE jobs SET job_status = 'queued', stage = NULL,"
            " completed_stages = '[]', lease_owner = NULL, lease_expires_at = NULL"
            f" WHERE {expired}",
            (now,),
        )

    def clean_inactive(self, analysis_ids: list[str], cleanup: Callable[[str], None]) -> None:
        """종료 직후 비정상 중단/구버전이 남긴 폴더와 기록 없는 폴더를 정리한다."""
        with self._tx() as conn:
            for aid in analysis_ids:
                row = conn.execute("SELECT job_status FROM jobs WHERE analysis_id = ?", (aid,)).fetchone()
                if row is None or row["job_status"] in ("finished", "failed", "cancelled"):
                    try:
                        cleanup(aid)
                    except OSError:
                        # 다른 종료/고아 폴더의 권한 오류 때문에 새 작업을 막지 않는다.
                        logging.getLogger("trinity.queue").warning("inactive cleanup failed: %s", aid)

    def advance_stage(
        self,
        analysis_id: str,
        worker_id: str,
        stage: str,
        completed_stages: list[str],
        lease_seconds: float,
    ) -> str:
        """단계 기록과 heartbeat(lease 연장)를 함께 한다."""
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE jobs SET stage = ?, completed_stages = ?, lease_expires_at = ?"
                " WHERE analysis_id = ? AND lease_owner = ?"
                " AND job_status = 'processing'",
                (
                    stage,
                    json.dumps(completed_stages),
                    time.time() + lease_seconds,
                    analysis_id,
                    worker_id,
                ),
            )
            if cur.rowcount == 0:
                return LEASE_LOST
            (cancel,) = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        return LEASE_CANCEL if cancel else LEASE_OK

    def save_run_info(
        self, analysis_id: str, worker_id: str, attempt: int,
        axes: dict[str, dict[str, Optional[str]]],
    ) -> bool:
        """이 시도의 축별 실행 기록을 저장한다. 다른 시도의 기록은 그대로 둔다(내부 기록, API는 읽지 않는다).

        lease를 가진 Worker가 처리 중일 때만 쓴다. 기존 값을 읽을 수 없으면 새 목록으로 시작한다.
        진단용 기록이라 DB 잠금은 1초만 기다린다(SyncNet 마무리 여유 10초 안, docs/syncnet-adapter.md).
        """
        with self._tx(timeout=1.0) as conn:
            row = conn.execute(
                "SELECT run_info_json FROM jobs WHERE analysis_id = ? AND lease_owner = ?"
                " AND job_status = 'processing'",
                (analysis_id, worker_id),
            ).fetchone()
            if row is None:
                return False
            try:
                entries = json.loads(row["run_info_json"] or '{"attempts": []}')["attempts"]
                if not isinstance(entries, list) or not all(isinstance(e, dict) and type(e.get("attempt")) is int for e in entries):
                    raise ValueError("invalid run info")
            except (ValueError, TypeError, KeyError):
                entries = []
            entries = [e for e in entries if e["attempt"] != attempt] + [{"attempt": attempt, "axes": axes}]
            entries.sort(key=lambda e: e["attempt"])
            conn.execute(
                "UPDATE jobs SET run_info_json = ? WHERE analysis_id = ?",
                (json.dumps({"attempts": entries}, ensure_ascii=False), analysis_id),
            )
        return True

    def heartbeat(self, analysis_id: str, worker_id: str, lease_seconds: float) -> str:
        """단계를 바꾸지 않고 lease만 연장한다. 긴 추론 중에 주기적으로 부른다."""
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE jobs SET lease_expires_at = ?"
                " WHERE analysis_id = ? AND lease_owner = ?"
                " AND job_status = 'processing'",
                (time.time() + lease_seconds, analysis_id, worker_id),
            )
            if cur.rowcount == 0:
                return LEASE_LOST
            (cancel,) = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        return LEASE_CANCEL if cancel else LEASE_OK

    def _close(
        self,
        analysis_id: str,
        worker_id: str,
        job_status: str,
        *,
        completed_stages: Optional[list[str]] = None,
        result: Optional[dict[str, Any]] = None,
        failure_reason: Optional[str] = None,
    ) -> bool:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE analysis_id = ? AND lease_owner = ?"
                " AND job_status = 'processing'", (analysis_id, worker_id),
            ).fetchone()
            if row is None:
                return False
            if row["cancel_requested"]:
                job_status, result, failure_reason = "cancelled", None, None
            cur = conn.execute(
                "UPDATE jobs SET job_status = ?, stage = NULL,"
                " completed_stages = COALESCE(?, completed_stages),"
                " result_json = ?, failure_reason = ?, lease_owner = NULL,"
                " lease_expires_at = NULL, finished_at = ?"
                " WHERE analysis_id = ? AND lease_owner = ?"
                " AND job_status = 'processing'",
                (
                    job_status,
                    json.dumps(completed_stages) if completed_stages is not None else None,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    failure_reason,
                    time.time(),
                    analysis_id,
                    worker_id,
                ),
            )
            return cur.rowcount == 1

    def finish(
        self,
        analysis_id: str,
        worker_id: str,
        result: dict[str, Any],
        completed_stages: list[str],
    ) -> bool:
        return self._close(
            analysis_id,
            worker_id,
            "finished",
            completed_stages=completed_stages,
            result=result,
        )

    def fail(self, analysis_id: str, worker_id: str, reason: str) -> bool:
        return self._close(analysis_id, worker_id, "failed", failure_reason=reason)

    def mark_cancelled(self, analysis_id: str, worker_id: str) -> bool:
        return self._close(analysis_id, worker_id, "cancelled")
