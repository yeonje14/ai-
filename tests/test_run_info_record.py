"""jobs.run_info_json: API가 읽지 않는 실행 기록(축별 장치·열 상태). 시도 번호별로 쌓인다."""
import hashlib
import json
import sqlite3

from server.jobs import worker
from server.jobs.queue import JobQueue
from server.schemas import AnalysisResult, dump
from tests.conftest import REGISTERED_ID, TOKEN

OWNER = hashlib.sha256(TOKEN.encode()).hexdigest()
AXES_1 = {"signal": {"device_used": "mps", "thermal_state_start": "nominal", "thermal_state_end": "fair"}}
AXES_2 = {"signal": {"device_used": "cpu", "thermal_state_start": "fair", "thermal_state_end": "fair"}}


def record(queue, aid):
    with sqlite3.connect(queue.db_path) as conn:
        (raw,) = conn.execute("SELECT run_info_json FROM jobs WHERE analysis_id = ?", (aid,)).fetchone()
    return None if raw is None else json.loads(raw)


def expire(queue, aid):
    with sqlite3.connect(queue.db_path) as conn:
        conn.execute("UPDATE jobs SET lease_expires_at = 0 WHERE analysis_id = ?", (aid,))


def test_init_schema_adds_column_to_old_db(tmp_path):
    db = tmp_path / "old.sqlite3"
    with sqlite3.connect(db) as conn:  # 열이 없던 때의 스키마와 행
        conn.execute("CREATE TABLE jobs (analysis_id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL,"
                     " youtube_video_id TEXT NOT NULL, job_status TEXT NOT NULL, stage TEXT,"
                     " completed_stages TEXT NOT NULL DEFAULT '[]', result_json TEXT, failure_reason TEXT,"
                     " attempts INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_expires_at REAL,"
                     " cancel_requested INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,"
                     " started_at REAL, finished_at REAL)")
        conn.execute("INSERT INTO jobs (analysis_id, owner_hash, youtube_video_id, job_status, created_at)"
                     " VALUES ('a', 'o', 'v', 'finished', 1.0)")
    queue = JobQueue(db)
    queue.init_schema()
    queue.init_schema()  # 두 번 불러도 된다
    with sqlite3.connect(db) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(jobs)")]
        row = conn.execute("SELECT analysis_id, owner_hash, job_status, created_at, run_info_json FROM jobs").fetchone()
    assert cols.count("run_info_json") == 1
    assert row == ("a", "o", "finished", 1.0, None)


def test_save_requires_lease_owner(queue):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    job = queue.claim("w1", 30, 2)
    assert queue.save_run_info(aid, "other", job.attempts, AXES_1) is False
    assert record(queue, aid) is None
    assert queue.save_run_info(aid, "w1", job.attempts, AXES_1) is True
    queue.fail(aid, "w1", "timeout")
    assert queue.save_run_info(aid, "w1", job.attempts, AXES_2) is False  # 종료된 작업
    assert record(queue, aid) == {"attempts": [{"attempt": 1, "axes": AXES_1}]}


def test_records_accumulate_per_attempt(queue):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    first = queue.claim("w1", 30, 2)
    assert queue.save_run_info(aid, "w1", first.attempts, AXES_1)
    expire(queue, aid)  # 1차 Worker가 죽어 lease가 만료됐다
    second = queue.claim("w2", 30, 2)
    assert second.analysis_id == aid and second.attempts == 2
    assert record(queue, aid) == {"attempts": [{"attempt": 1, "axes": AXES_1}]}  # 재선점이 지우지 않는다
    assert queue.save_run_info(aid, "w2", second.attempts, AXES_2)
    assert record(queue, aid) == {"attempts": [{"attempt": 1, "axes": AXES_1}, {"attempt": 2, "axes": AXES_2}]}


def test_same_attempt_entry_is_replaced_not_duplicated(queue):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    job = queue.claim("w1", 30, 2)
    queue.save_run_info(aid, "w1", job.attempts, AXES_1)
    both = {**AXES_1, "physics": {"device_used": "cpu", "thermal_state_start": "fair", "thermal_state_end": None}}
    queue.save_run_info(aid, "w1", job.attempts, both)
    assert record(queue, aid) == {"attempts": [{"attempt": 1, "axes": both}]}


def test_unreadable_record_restarts_list(queue):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    job = queue.claim("w1", 30, 2)
    with sqlite3.connect(queue.db_path) as conn:
        conn.execute("UPDATE jobs SET run_info_json = 'not json' WHERE analysis_id = ?", (aid,))
    assert queue.save_run_info(aid, "w1", job.attempts, AXES_1)
    assert record(queue, aid) == {"attempts": [{"attempt": 1, "axes": AXES_1}]}


def _finish(queue, aid, worker_id):
    job = queue.get(aid, OWNER)
    result = dump(AnalysisResult.model_validate(worker.build_unavailable_result(job, worker.ACCESS_NOT_AUTHORIZED)))
    assert queue.finish(aid, worker_id, result, ["validating"])


def test_api_responses_never_include_run_info(client, queue):
    with_record = client.post("/api/v1/analyses", json={"url": f"https://youtu.be/{REGISTERED_ID}"}).json()["analysis_id"]
    queue.claim("w1", 30, 2)
    queue.save_run_info(with_record, "w1", 1, AXES_1)
    _finish(queue, with_record, "w1")
    control = client.post("/api/v1/analyses", json={"url": f"https://youtu.be/{REGISTERED_ID}"}).json()["analysis_id"]
    queue.claim("w2", 30, 2)
    _finish(queue, control, "w2")
    assert record(queue, with_record) is not None and record(queue, control) is None
    for suffix in ("", "/result"):
        a = client.get(f"/api/v1/analyses/{with_record}{suffix}")
        b = client.get(f"/api/v1/analyses/{control}{suffix}")
        assert a.status_code == b.status_code == 200
        assert set(a.json()) == set(b.json())
        for word in ("run_info", "thermal", "device_used"):
            assert word not in a.text
