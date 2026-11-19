"""등록된 임시 DB를 공유하는 독립 API 인스턴스로 접수·시간 경계를 검증한다."""
from contextlib import contextmanager
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from server import accounts
from server.api import create_app
from server.jobs import admission
from tests.conftest import REGISTERED_ID, TOKEN, OTHER_TOKEN

BASE = "/api/v1/analyses"


def submit(client, key, video=REGISTERED_ID, token=TOKEN):
    return client.post(BASE, headers={"Idempotency-Key": key, "Authorization": f"Bearer {token}"},
                       json={"url": f"https://youtu.be/{video}"})


def denied(response, reason, retry=None, status=429):
    assert response.status_code == status and response.json()["detail"]["reason_code"] == reason
    assert response.headers.get("retry-after") == retry


def totals(db):
    with accounts.connection(db, write=False) as conn:
        return conn.execute("SELECT (SELECT COUNT(*) FROM jobs), (SELECT COUNT(*) FROM receipts), "
                            "(SELECT SUM(calls) FROM api_requests)").fetchone()


@pytest.mark.parametrize("shared", [True, False])
def test_concurrent_admissions(client, account_db, settings, shared):
    other = TestClient(create_app(settings))
    first = str(uuid.uuid4())
    keys = [first, first if shared else str(uuid.uuid4())]
    start = threading.Barrier(2)

    def send(pair):
        api, key = pair
        start.wait(timeout=5)
        return submit(api, key)

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(send, zip((client, other), keys)))
    assert totals(account_db) == (1, 1, 2)
    if shared:
        assert [r.status_code for r in responses] == [202, 202]
        assert responses[0].json() == responses[1].json()
    else:
        assert sorted(r.status_code for r in responses) == [202, 429]
        denied(next(r for r in responses if r.status_code == 429), "user_active_limit")


def test_lost_response_restart_scope_and_delete(client, account_db, settings):
    key = str(uuid.uuid4())
    accepted = submit(client, key)
    aid = accepted.json()["analysis_id"]
    assert submit(client, key, token=OTHER_TOKEN).json()["analysis_id"] != aid
    q = client.app.state.queue
    assert q.claim("w", 30, 2).analysis_id == aid
    with q._tx() as conn:
        conn.execute("UPDATE jobs SET lease_expires_at=0 WHERE analysis_id=?", (aid,))
    assert q.claim("w2", 30, 2).attempts == 2
    _, new_key = accounts.issue(account_db, "test-user")
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {new_key}"}) as restarted:
        response = restarted.post(BASE, headers={"Idempotency-Key": key},
                                  json={"url": f"https://www.youtube.com/watch?v={REGISTERED_ID}"})
        assert response.status_code == 202 and response.json() == accepted.json()
        denied(submit(restarted, key, "abcdefghijk", new_key), "idempotency_conflict", status=409)
        path = f"{BASE}/{aid}"
        assert restarted.delete(path).status_code == 202
        denied(submit(restarted, str(uuid.uuid4()), token=new_key), "user_active_limit")
        q.mark_cancelled(aid, "w2")
        assert restarted.delete(path).status_code == 204
        denied(submit(restarted, key, token=new_key), "analysis_deleted", status=410)
    with accounts.connection(account_db, write=False) as conn:
        assert conn.execute("SELECT deleted,analysis_id,video_id FROM receipts WHERE user_id='test-user'").fetchone() == (1, None, None)
    assert totals(account_db) == (1, 2, 8)


def test_time_windows_survive_delete_rotation_and_restart(client, account_db, settings, monkeypatch):
    now = [1200.]
    monkeypatch.setattr(admission, "time", lambda: now[0])
    key = str(uuid.uuid4())
    for index in range(6):
        response = submit(client, key if index == 0 else str(uuid.uuid4()))
        assert response.status_code == 202
        aid = response.json()["analysis_id"]
        q = client.app.state.queue
        q.claim("w", 30, 2)
        q.mark_cancelled(aid, "w")
        assert client.delete(f"{BASE}/{aid}").status_code == 204
    _, token = accounts.issue(account_db, "test-user")
    with TestClient(create_app(settings)) as restarted:
        now[0] += 599.9
        denied(submit(restarted, str(uuid.uuid4()), token=token), "user_submission_limit", "1")
        now[0] = 1800.
        assert submit(restarted, str(uuid.uuid4()), token=token).status_code == 202
        now[0] = 1200 + 86400 - .1
        denied(submit(restarted, key, token=token), "analysis_deleted", status=410)
        now[0] = 1200 + 86400
        denied(submit(restarted, key, token=token), "user_active_limit")
        job = q.claim("w2", 30, 2)
        q.mark_cancelled(job.analysis_id, "w2")
        assert submit(restarted, key, token=token).status_code == 202


def test_minute_counts_all_authenticated_calls(client, account_db, settings, monkeypatch):
    now = [1259.8]
    monkeypatch.setattr(admission, "time", lambda: now[0])
    key = str(uuid.uuid4())
    path = BASE + "/" + submit(client, key).json()["analysis_id"]
    assert submit(client, key).status_code == 202
    assert client.delete(path, headers={"If-Match": '"wrong"'}).status_code == 412
    assert client.get(BASE + "/missing/result").status_code == 404
    assert client.get(BASE, params={"limit": 0}).status_code == 422
    assert client.post(BASE, content=b"bad", headers={"Content-Type": "application/json"}).status_code == 422
    denied(submit(client, str(uuid.uuid4())), "user_active_limit")
    assert client.get("/api/v1/health").status_code == 200
    assert client.options(BASE, headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "POST",
                                         "Access-Control-Request-Headers": "Idempotency-Key,Authorization"}).status_code == 200
    assert totals(account_db) == (1, 1, 7)
    for _ in range(180 - 7):
        assert client.get(path).status_code == 200
    _, token = accounts.issue(account_db, "test-user")
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {token}"}) as restarted:
        denied(restarted.get(path), "request_rate_limited", "1")
        assert totals(account_db) == (1, 1, 181)
        assert restarted.get(BASE, headers={"Authorization": f"Bearer {OTHER_TOKEN}"}).status_code == 200
        now[0] = 1260.
        assert restarted.get(path).status_code == 200


def test_receipt_failure_rolls_back_job_but_commits_call(client, account_db):
    key = str(uuid.uuid4())
    with accounts.connection(account_db, write=True) as conn:
        conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON receipts BEGIN SELECT RAISE(ABORT,'fail'); END")
    assert submit(client, key).status_code == 500
    assert totals(account_db) == (0, 0, 1)
    with accounts.connection(account_db, write=True) as conn:
        conn.execute("DROP TRIGGER fail_receipt")
    assert submit(client, key).status_code == 202
    assert totals(account_db) == (1, 1, 2)


def test_required_key_and_existing_db_prepare(account_db, settings):
    # 2단계 계정 DB에 남아 있는 최근 접수의 소유권과 비용을 보존한다.
    with accounts.connection(account_db, write=True) as conn:
        conn.execute("INSERT INTO jobs(analysis_id,user_id,youtube_video_id,job_status,created_at) "
                     "VALUES ('old','test-user',?,'finished',?)", (REGISTERED_ID, admission.time()))
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {TOKEN}"}) as api:
        for headers in ({}, {"Idempotency-Key": "bad"}, [("Idempotency-Key", str(uuid.uuid4()))] * 2):
            denied(api.post(BASE, headers=headers, json={"url": f"https://youtu.be/{REGISTERED_ID}"}),
                   "invalid_idempotency_key", status=422)
    assert totals(account_db) == (1, 1, 3)


def test_revoked_between_count_and_enqueue(client, account_db, monkeypatch):
    original = accounts.connection
    transactions = []

    @contextmanager
    def revoke_after_first_commit(path, *, write):
        with original(path, write=write) as conn:
            transactions.append(write)
            yield conn
        if len(transactions) == 1:
            with original(path, write=True) as admin:
                admin.execute("UPDATE credentials SET revoked_at=0 WHERE user_id='test-user'")

    with monkeypatch.context() as patch:
        patch.setattr(accounts, "connection", revoke_after_first_commit)
        response = submit(client, str(uuid.uuid4()))
    assert transactions == [True, True]
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert totals(account_db) == (0, 0, 1)
