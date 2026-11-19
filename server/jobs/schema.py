"""구 큐와 새 계정 DB가 공유하는 작업 열 및 인덱스."""


def jobs_schema(*, registered_users: bool) -> str:
    owner_column = ("user_id TEXT NOT NULL REFERENCES users(user_id)" if registered_users
                    else "owner_hash TEXT NOT NULL")
    return f"""
CREATE TABLE IF NOT EXISTS jobs (
    analysis_id       TEXT PRIMARY KEY,
    {owner_column},
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
