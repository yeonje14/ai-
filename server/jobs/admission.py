"""계정 DB 안의 API 호출량과 신규 분석 접수 원장. 시각은 Unix 초 단위다."""
import math
import sqlite3
from time import time

from server.jobs.queue import JobQueue


class AdmissionDenied(Exception):
    def __init__(self, status: int, reason: str, retry_after: int | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


def prepare(conn: sqlite3.Connection) -> None:
    """API 시작 시 계정 DB의 쓰기 트랜잭션 안에서 한 번 설치한다."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipts'").fetchone():
        return
    conn.execute("""CREATE TABLE receipts (
        user_id TEXT NOT NULL REFERENCES users(user_id), key TEXT NOT NULL,
        video_id TEXT, analysis_id TEXT UNIQUE, accepted_at REAL NOT NULL,
        deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,key))""")
    conn.execute("CREATE INDEX receipts_user_time ON receipts(user_id,accepted_at)")
    conn.execute("CREATE INDEX receipts_expiry ON receipts(accepted_at)")
    conn.execute("CREATE INDEX jobs_user_status ON jobs(user_id,job_status)")
    conn.execute("""CREATE TABLE api_requests (
        user_id TEXT NOT NULL REFERENCES users(user_id), minute INTEGER NOT NULL,
        calls INTEGER NOT NULL, PRIMARY KEY(user_id,minute))""")
    conn.execute("CREATE INDEX requests_expiry ON api_requests(minute)")
    conn.execute("""CREATE TRIGGER tombstone_receipt AFTER DELETE ON jobs BEGIN
        UPDATE receipts SET analysis_id=NULL, video_id=NULL, deleted=1
        WHERE analysis_id=OLD.analysis_id AND user_id=OLD.user_id;
        END""")
    # 전환 직전의 남아 있는 작업도 접수량에 포함한다. 이 내부 키는 UUID와 충돌하지 않는다.
    conn.execute("""INSERT INTO receipts(user_id,key,video_id,analysis_id,accepted_at)
        SELECT user_id,'legacy:' || analysis_id,youtube_video_id,analysis_id,created_at
        FROM jobs WHERE created_at>?""", (time() - 600,))


def count_request(conn: sqlite3.Connection, owner: str) -> int | None:
    """카운트는 거절 응답 때도 커밋한다. 상한 초과면 다음 분까지의 초를 반환한다."""
    now = time()
    minute = math.floor(now / 60)
    conn.execute("DELETE FROM api_requests WHERE rowid IN "
                 "(SELECT rowid FROM api_requests WHERE minute<? LIMIT 32)", (minute,))
    conn.execute("DELETE FROM receipts WHERE rowid IN "
                 "(SELECT rowid FROM receipts WHERE accepted_at<=? LIMIT 32)", (now - 86400,))
    calls, = conn.execute("""INSERT INTO api_requests(user_id,minute,calls) VALUES (?,?,1)
        ON CONFLICT(user_id,minute) DO UPDATE SET calls=calls+1 RETURNING calls""",
                          (owner, minute)).fetchone()
    if calls > 180:
        return math.ceil((minute + 1) * 60 - now)
    return None


def submit(conn: sqlite3.Connection, queue: JobQueue, owner: str, key: str, video: str, max_queued: int) -> str:
    now = time()
    conn.execute("DELETE FROM receipts WHERE user_id=? AND key=? AND accepted_at<=?",
                 (owner, key, now - 86400))
    receipt = conn.execute("SELECT deleted,video_id,analysis_id FROM receipts WHERE user_id=? AND key=?",
                           (owner, key)).fetchone()
    if receipt:
        deleted, original_video, aid = receipt
        if deleted:
            raise AdmissionDenied(410, "analysis_deleted")
        if original_video != video:
            raise AdmissionDenied(409, "idempotency_conflict")
        return aid
    active = conn.execute("SELECT 1 FROM jobs WHERE user_id=? AND job_status IN ('queued','processing') LIMIT 1",
                          (owner,)).fetchone()
    if active:
        raise AdmissionDenied(429, "user_active_limit")
    count, oldest = conn.execute("SELECT COUNT(*),MIN(accepted_at) FROM receipts "
                                 "WHERE user_id=? AND accepted_at>? AND accepted_at<=?",
                                 (owner, now - 600, now)).fetchone()
    if count >= 6:
        raise AdmissionDenied(429, "user_submission_limit", math.ceil(oldest + 600 - now))
    aid = queue.enqueue_in(conn, video, owner, max_queued)
    conn.execute("INSERT INTO receipts(user_id,key,video_id,analysis_id,accepted_at) VALUES (?,?,?,?,?)",
                 (owner, key, video, aid, now))
    return aid
