"""임시 계정 DB에서 실제 연결과 트랜잭션을 사용하는 분석 API 계약 테스트."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from server import accounts
from tests.conftest import OTHER_TOKEN, TOKEN, UNREGISTERED_ID

BASE = "/api/v1/analyses"
BODY = {"url": f"https://youtu.be/{UNREGISTERED_ID}"}


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def assert_unauthorized(response):
    assert response.status_code == 401
    assert response.json() == {"detail": {"reason_code": "authentication_required"}}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers
    assert TOKEN not in response.text


@pytest.mark.parametrize("state", ["unknown", "expired", "revoked", "suspended"])
def test_invalid_credential_uses_no_writer(client, account_db, monkeypatch, state):
    headers = bearer("x" * 43 if state == "unknown" else TOKEN)
    with accounts.connection(account_db, write=True) as admin:
        if state == "expired":
            admin.execute("UPDATE credentials SET expires_at=0 WHERE user_id='test-user'")
        elif state == "revoked":
            admin.execute("UPDATE credentials SET revoked_at=0 WHERE user_id='test-user'")
        elif state == "suspended":
            admin.execute("UPDATE users SET disabled_at=0 WHERE user_id='test-user'")

    connect = sqlite3.connect
    write_attempts = []

    def traced(*args, **kwargs):
        kwargs["timeout"] = 0
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(lambda sql: write_attempts.append(sql) if sql == "BEGIN IMMEDIATE" else None)
        return conn

    with accounts.connection(account_db, write=True) as holder:
        monkeypatch.setattr(sqlite3, "connect", traced)
        assert_unauthorized(client.get(BASE, headers=headers))
        assert_unauthorized(client.post(BASE, content=b"{", headers={**headers, "Content-Type": "application/json"}))
        assert write_attempts == []
        assert holder.execute("SELECT COUNT(*) FROM api_requests").fetchone() == (0,)


@pytest.mark.parametrize("mode", ["missing", "malformed", "unknown", "legacy", "mixed", "duplicate",
                                   "expired", "revoked", "suspended"])
def test_credential_rejection_for_every_route(client, account_db, mode):
    path = BASE + "/" + client.post(BASE, json=BODY).json()["analysis_id"]
    client.headers.pop("Authorization")
    headers = {
        "missing": {}, "malformed": {"Authorization": "Basic secret"}, "unknown": bearer("x" * 43),
        "legacy": {"X-Client-Token": TOKEN}, "mixed": {**bearer(TOKEN), "X-Client-Token": TOKEN},
        "duplicate": [("Authorization", f"Bearer {TOKEN}")] * 2,
    }.get(mode, bearer(TOKEN))
    if mode == "expired":
        with accounts.connection(account_db, write=True) as conn:
            conn.execute("UPDATE credentials SET expires_at=0 WHERE user_id='test-user'")
    elif mode in {"revoked", "suspended"}:
        accounts.revoke(account_db, "test-user", suspend=mode == "suspended")
    for method, url in (("POST", BASE), ("GET", BASE), ("GET", path), ("GET", path + "/result"), ("DELETE", path)):
        kwargs = {"json": BODY} if method == "POST" else {}
        assert_unauthorized(client.request(method, url, headers=headers, **kwargs))
    with accounts.connection(account_db, write=False) as conn:
        assert conn.execute("SELECT cancel_requested FROM jobs").fetchall() == [(0,)]


@pytest.mark.parametrize("method,suffix", [("GET", ""), ("GET", "/result"), ("DELETE", "")])
def test_other_and_missing_indistinguishable(client, method, suffix):
    aid = client.post(BASE, json=BODY).json()["analysis_id"]
    headers = {**bearer(OTHER_TOKEN), "If-Match": '"invalid"'}
    responses = [client.request(method, f"{BASE}/{key}{suffix}", headers=headers)
                 for key in (aid, "00000000-0000-4000-8000-000000000000")]
    a, b = responses
    assert a.status_code == b.status_code == 404
    assert a.content == b.content and a.headers == b.headers
    assert a.headers["cache-control"] == "no-store" and "etag" not in a.headers


def test_pagination_and_key_rotation(client, account_db):
    assert client.get(BASE).json() == {"items": [], "next_cursor": None}
    q = client.app.state.queue
    ids = [q.enqueue(UNREGISTERED_ID, "test-user", 40) for _ in range(22)]
    other = q.enqueue(UNREGISTERED_ID, "other-user", 40)
    with accounts.connection(account_db, write=True) as conn:
        conn.execute("UPDATE jobs SET created_at=1, job_status='cancelled'")
        conn.execute("UPDATE jobs SET created_at=2 WHERE analysis_id=?", (ids[0],))
    expected = [ids[0], *sorted(ids[1:], reverse=True)]
    page = client.get(BASE).json()
    assert [item["analysis_id"] for item in page["items"]] == expected[:20]
    cursor = page["next_cursor"]
    foreign_page = client.get(BASE, params={"cursor": cursor}, headers=bearer(OTHER_TOKEN)).json()
    expected_other = [other] if other < expected[19] else []
    assert [item["analysis_id"] for item in foreign_page["items"]] == expected_other

    _, new = accounts.issue(account_db, "test-user")
    assert_unauthorized(client.get(BASE))
    client.headers.update(bearer(new))
    assert client.get(BASE).json() == page
    # 경계가 된 행을 지워도 커서 값으로 다음 페이지를 읽을 수 있다.
    assert client.delete(f"{BASE}/{expected[19]}").status_code == 204
    rest = client.get(BASE, params={"cursor": cursor}).json()
    assert [item["analysis_id"] for item in rest["items"]] == expected[20:]
    assert rest["next_cursor"] is None
    assert expected[19] not in client.get(BASE).text
    for params in ({"limit": 21}, {"limit": 0}, {"cursor": "bad"}):
        assert client.get(BASE, params=params).status_code == 422


@pytest.mark.parametrize("method", ["post", "delete"])
@pytest.mark.parametrize("change", ["expiry", "revoke"])
def test_credential_checked_after_write_lock(client, account_db, monkeypatch, method, change):
    aid = client.post(BASE, json=BODY).json()["analysis_id"]
    now = [100.]
    monkeypatch.setattr(accounts, "time", SimpleNamespace(time=lambda: now[0]))
    with accounts.connection(account_db, write=True) as conn:
        conn.execute("UPDATE credentials SET expires_at=101 WHERE user_id='test-user'")

    waiting = threading.Event()
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(lambda sql: waiting.set() if sql == "BEGIN IMMEDIATE" else None)
        return connection

    with ThreadPoolExecutor(1) as pool:
        with accounts.connection(account_db, write=True) as holder:
            monkeypatch.setattr(sqlite3, "connect", traced)
            if method == "post":
                future = pool.submit(client.post, BASE, json=BODY)
            else:
                future = pool.submit(client.delete, f"{BASE}/{aid}", headers={"If-Match": '"wrong"'})
            assert waiting.wait(3)
            if change == "expiry":
                now[0] = 101.
            else:
                holder.execute("UPDATE credentials SET revoked_at=100 WHERE user_id='test-user'")
        assert_unauthorized(future.result(timeout=5))
    with accounts.connection(account_db, write=False) as conn:
        assert conn.execute("SELECT analysis_id,cancel_requested FROM jobs").fetchall() == [(aid, 0)]
        assert conn.execute("SELECT SUM(calls) FROM api_requests").fetchone() == (1,)


def test_auth_and_status_share_read_snapshot(client, account_db, monkeypatch):
    aid = client.post(BASE, json=BODY).json()["analysis_id"]
    lookup = accounts.identify_in

    def change_after_auth(conn, key):
        owner = lookup(conn, key)
        if conn.row_factory is not sqlite3.Row:  # 호출량 기록은 별도 쓰기 트랜잭션이다.
            return owner
        with accounts.connection(account_db, write=True) as writer:
            writer.execute("UPDATE credentials SET revoked_at=0 WHERE user_id=?", (owner,))
            writer.execute("UPDATE jobs SET job_status='cancelled' WHERE analysis_id=?", (aid,))
        return owner

    with monkeypatch.context() as patch:
        patch.setattr(accounts, "identify_in", change_after_auth)
        response = client.get(f"{BASE}/{aid}")
    assert response.status_code == 200 and response.json()["job_status"] == "queued"
    assert_unauthorized(client.get(f"{BASE}/{aid}"))


def test_issued_key_to_separate_worker_result(client, account_db, run_worker):
    uid, key = accounts.issue(account_db)
    headers = bearer(key)
    created = client.post(BASE, json=BODY, headers=headers)
    assert created.status_code == 202
    aid = created.json()["analysis_id"]
    run_worker()
    result = client.get(f"{BASE}/{aid}/result", headers=headers)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    data = result.json()
    assert (data["job_status"], data["analysis_status"], data["verdict_status"]) == (
        "finished", "analysis_unavailable", "abstained")
    assert data["overall_score"] is None
    with accounts.connection(account_db, write=False) as conn:
        assert conn.execute("SELECT user_id,attempts FROM jobs WHERE analysis_id=?", (aid,)).fetchone() == (uid, 1)


def test_invalid_body_auth_precedence_and_redaction(client, account_db):
    response = client.post(BASE, content='{"url":', headers={"content-type": "application/json"})
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    response = client.get(BASE, params={"limit": TOKEN})
    assert response.status_code == 422 and TOKEN not in response.text
    accounts.revoke(account_db, "test-user")
    assert_unauthorized(client.post(BASE, content='{"url":', headers={"content-type": "application/json"}))
    assert_unauthorized(client.get(BASE, params={"limit": TOKEN}))


def test_api_refuses_legacy_database(settings, queue):
    from server.api import create_app

    original = settings.db_path.read_bytes()
    with pytest.raises(ValueError):
        create_app(settings)
    assert settings.db_path.read_bytes() == original
