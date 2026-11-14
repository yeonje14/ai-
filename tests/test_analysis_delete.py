"""DELETE의 권한·수명주기·조건부 취소 계약. 실제 SQLite와 API를 함께 사용한다."""
import hashlib

import pytest

from tests.conftest import TOKEN, OTHER_TOKEN, REGISTERED_ID

OWNER = hashlib.sha256(TOKEN.encode()).hexdigest()


def submit(client):
    response = client.post('/api/v1/analyses', json={'url': f'https://youtu.be/{REGISTERED_ID}'})
    assert response.status_code == 202
    return '/api/v1/analyses/' + response.json()['analysis_id']


def test_delete_requires_token_and_hides_other_owner(client):
    path = submit(client)
    assert client.delete(path, headers={'X-Client-Token': OTHER_TOKEN, 'If-Match': '"wrong"'}).status_code == 404
    client.headers.pop('X-Client-Token')
    assert client.delete(path).status_code == 401


@pytest.mark.parametrize('processing', [False, True])
def test_cancel_is_pending_and_repeatable_until_worker_cleanup(client, processing):
    path = submit(client)
    q = client.app.state.queue
    if processing:
        q.claim('w', 30, 2)
    first = client.delete(path)
    again = client.delete(path)
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()
    assert first.json() == client.get(path).json()
    assert first.json()['job_status'] == ('processing' if processing else 'queued')
    assert client.get(path + '/result').status_code == 202


@pytest.mark.parametrize('terminal', ['finished', 'failed', 'cancelled'])
def test_terminal_delete_removes_result_record_and_folder(client, settings, terminal):
    path = submit(client)
    aid = path.rsplit('/', 1)[1]
    q = client.app.state.queue
    q.claim('w', 30, 2)
    if terminal == 'finished':
        q.finish(aid, 'w', {'private_result': True}, [])
    elif terminal == 'failed':
        q.fail(aid, 'w', 'worker_error')
    else:
        q.mark_cancelled(aid, 'w')
    folder = settings.runtime_dir / aid
    folder.mkdir(parents=True)
    (folder / 'media').write_bytes(b'private')
    response = client.delete(path)
    assert response.status_code == 204 and response.content == b''
    assert not folder.exists()
    assert q.get(aid, OWNER) is None
    assert client.get(path).status_code == 404
    assert client.get(path + '/result').status_code == 404
    assert client.delete(path).status_code == 404


def test_active_etag_survives_claim_stages_heartbeat_and_retry(client):
    path = submit(client)
    aid = path.rsplit('/', 1)[1]
    q = client.app.state.queue
    initial = client.get(path)
    etag = initial.headers.get('etag')
    assert etag and not etag.startswith('W/')
    assert initial.headers['cache-control'] == 'no-store'
    q.claim('w', 30, 2)
    for stage in ['validating', 'preprocessing', 'waverep', 'finalizing']:
        q.advance_stage(aid, 'w', stage, [], 30)
        q.heartbeat(aid, 'w', 30)
        assert client.get(path).headers['etag'] == etag
    with q._tx() as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE analysis_id=?', (aid,))
    assert q.claim('w2', 30, 2).attempts == 2
    assert client.get(path).headers['etag'] == etag
    response = client.delete(path, headers={'If-Match': etag})
    assert response.status_code == 202
    assert client.delete(path, headers={'If-Match': etag}).status_code == 202
    assert client.get(path).headers['etag'] == etag


@pytest.mark.parametrize('terminal', ['finished', 'failed', 'cancelled'])
def test_stale_active_etag_cannot_delete_terminal_job(client, settings, terminal):
    path = submit(client)
    aid = path.rsplit('/', 1)[1]
    etag = client.get(path).headers.get('etag')
    assert etag
    q = client.app.state.queue
    q.claim('w', 30, 2)
    if terminal == 'finished':
        q.finish(aid, 'w', {'private_result': True}, [])
    elif terminal == 'failed':
        q.fail(aid, 'w', 'worker_error')
    else:
        q.mark_cancelled(aid, 'w')
    folder = settings.runtime_dir / aid
    folder.mkdir(parents=True)
    terminal_etag = client.get(path).headers['etag']
    assert terminal_etag != etag
    response = client.delete(path, headers={'If-Match': etag})
    assert response.status_code == 412 and response.content == b''
    assert q.get(aid, OWNER).job_status == terminal
    assert folder.exists()
    # 일반 DELETE 계약은 바뀌지 않는다.
    assert client.delete(path).status_code == 204


def test_mismatched_or_weak_etag_does_not_request_cancel(client):
    path = submit(client)
    etag = client.get(path).headers.get('etag')
    assert etag
    for value in ['"other"', 'W/' + etag, '']:
        assert client.delete(path, headers={'If-Match': value}).status_code == 412
    q = client.app.state.queue
    aid = path.rsplit('/', 1)[1]
    q.claim('w', 30, 2)
    assert q.heartbeat(aid, 'w', 30) == 'ok'
    assert client.delete(path, headers={'If-Match': '"other", ' + etag}).status_code == 202


def test_accepted_cancel_wins_race_with_finish(client):
    path = submit(client)
    aid = path.rsplit('/', 1)[1]
    q = client.app.state.queue
    q.claim('w', 30, 2)
    assert client.delete(path).status_code == 202
    q.finish(aid, 'w', {'must_not_publish': True}, ['finalizing'])
    job = q.get(aid, OWNER)
    assert job.job_status == 'cancelled' and job.result is None


def test_browser_can_read_etag_and_send_conditional_delete(client):
    path = submit(client)
    origin = 'http://localhost:8080'
    response = client.get(path, headers={'Origin': origin})
    assert 'etag' in response.headers.get('access-control-expose-headers', '').lower()
    preflight = client.options(path, headers={
        'Origin': origin, 'Access-Control-Request-Method': 'DELETE',
        'Access-Control-Request-Headers': 'X-Client-Token,If-Match',
    })
    assert preflight.status_code == 200
    assert 'DELETE' in preflight.headers['access-control-allow-methods']
    assert client.options(path, headers={
        'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'DELETE',
    }).status_code == 400
