"""SQLite 작업 큐 (README §8).

- queued → processing 선점은 BEGIN IMMEDIATE 트랜잭션 하나로 원자적으로 한다.
- 동시 분석은 1건이다. lease가 살아 있는 processing 작업이 있으면 선점하지 않는다.
- lease가 만료된 processing 작업은 재시도 상한 안에서 queued로 되돌린다(재시작 복구).
- 상태를 바꾸는 쓰기는 lease_owner가 일치할 때만 적용한다(중복 실행 방지).
- URL 원문은 저장하지 않는다. video ID와 소유자 토큰의 해시만 저장한다.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

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
    finished_at       REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (job_status, created_at);
"""

LEASE_OK = "ok"
LEASE_LOST = "lost"
LEASE_CANCEL = "cancel_requested"


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
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
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
        """queued는 바로 cancelled로, processing은 worker가 다음 단계 경계에서 멈춘다."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT job_status FROM jobs WHERE analysis_id = ? AND owner_hash = ?",
                (analysis_id, owner_hash),
            ).fetchone()
            if row is None:
                return False
            if row["job_status"] == "queued":
                conn.execute(
                    "UPDATE jobs SET job_status = 'cancelled', finished_at = ?"
                    " WHERE analysis_id = ?",
                    (time.time(), analysis_id),
                )
                return True
            if row["job_status"] == "processing":
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1 WHERE analysis_id = ?",
                    (analysis_id,),
                )
                return True
            return False

    # ---- Worker 쪽 ----------------------------------------------------

    def claim(
        self, worker_id: str, lease_seconds: float, max_attempts: int
    ) -> Optional[Job]:
        now = time.time()
        with self._tx() as conn:
            self._recover_expired(conn, now, max_attempts)
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
    def _recover_expired(conn: sqlite3.Connection, now: float, max_attempts: int) -> None:
        expired = "job_status = 'processing' AND lease_expires_at < ?"
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
