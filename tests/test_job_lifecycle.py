"""종료 상태는 자식 종료·임시 폴더 정리가 완료됐다는 뜻이어야 한다."""
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import replace

import pytest

from server.jobs import worker, runtime
from tests.conftest import REGISTERED_ID

OWNER = "test-user"


def seed_folder(settings, aid):
    folder = settings.runtime_dir / aid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'leftover').write_bytes(b'private')
    return folder


def expire(queue, aid):
    with sqlite3.connect(queue.db_path) as conn:
        conn.execute('UPDATE jobs SET lease_expires_at=0 WHERE analysis_id=?', (aid,))


@pytest.mark.parametrize('outcome', ['finished', 'failed', 'cancelled', 'timeout'])
def test_cleanup_precedes_terminal_state(queue, registry, settings, monkeypatch, outcome):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    folder = seed_folder(settings, aid)
    close = queue._close
    closed = []
    def checked_close(*args, **kwargs):
        assert not folder.exists(), 'terminal state must not precede cleanup'
        closed.append(True)
        return close(*args, **kwargs)
    monkeypatch.setattr(queue, '_close', checked_close)
    if outcome == 'failed':
        monkeypatch.setattr(registry, 'resolve', lambda _: (_ for _ in ()).throw(RuntimeError('failure')))
    elif outcome == 'cancelled':
        queue.request_cancel(aid, OWNER)
    elif outcome == 'timeout':
        settings = replace(settings, job_timeout_seconds=-1)
    worker.run_once(queue, registry, settings, 'w')
    assert closed
    assert queue.get(aid, OWNER).job_status == ('failed' if outcome == 'timeout' else outcome)
    assert not folder.exists()


@pytest.mark.parametrize('cancel,attempts', [(False, 1), (False, 2), (True, 1)])
def test_recovery_removes_old_files_before_retry_or_terminal(queue, registry, settings, monkeypatch, cancel, attempts):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    for _ in range(attempts):
        queue.claim('dead', 30, 2)
        expire(queue, aid)
    folder = seed_folder(settings, aid)
    if cancel:
        queue.request_cancel(aid, OWNER)
    real_process = worker.process
    def checked_process(*args):
        assert not folder.exists(), 'old attempt files must not be reused'
        return real_process(*args)
    monkeypatch.setattr(worker, 'process', checked_process)
    worker.run_once(queue, registry, settings, 'replacement')
    job = queue.get(aid, OWNER)
    assert job.job_status == ('cancelled' if cancel else 'failed' if attempts == 2 else 'finished')
    if attempts == 2:
        assert job.failure_reason == 'max_attempts_exceeded'
    assert not folder.exists()


def test_cleanup_failure_keeps_processing_for_recovery(queue, registry, settings, monkeypatch):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    folder = seed_folder(settings, aid)
    with monkeypatch.context() as patch:
        patch.setattr(runtime.shutil, 'rmtree', lambda _: (_ for _ in ()).throw(PermissionError()))
        worker.run_once(queue, registry, settings, 'w')
    assert queue.get(aid, OWNER).job_status == 'processing'
    assert folder.exists()
    expire(queue, aid)
    worker.run_once(queue, registry, settings, 'w2')
    assert queue.get(aid, OWNER).job_status == 'finished'
    assert not folder.exists()


def test_delete_cleanup_failure_keeps_record_for_retry(client, settings, monkeypatch):
    q = client.app.state.queue
    aid = q.enqueue(REGISTERED_ID, OWNER, 3)
    q.claim('w', 30, 2)
    q.fail(aid, 'w', 'worker_error')
    folder = seed_folder(settings, aid)
    with monkeypatch.context() as patch:
        patch.setattr(runtime.shutil, 'rmtree', lambda _: (_ for _ in ()).throw(PermissionError()))
        assert client.delete(f'/api/v1/analyses/{aid}').status_code == 500
    assert folder.exists() and q.get(aid, OWNER) is not None
    assert client.delete(f'/api/v1/analyses/{aid}').status_code == 204


def test_cleanup_does_not_follow_job_directory_symlink(queue, settings, tmp_path):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    original = tmp_path / 'source'
    original.mkdir()
    (original / 'keep').write_bytes(b'original')
    settings.runtime_dir.mkdir(parents=True)
    link = settings.runtime_dir / aid
    link.symlink_to(original, target_is_directory=True)
    runtime.remove_job_dir(settings.runtime_dir, aid)
    assert not link.is_symlink()
    assert (original / 'keep').read_bytes() == b'original'


def test_alive_old_worker_blocks_recovery_until_it_releases_runtime(queue, registry, settings, monkeypatch):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    entered, release = threading.Event(), threading.Event()
    real_process = worker.process
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return real_process(*args)
    monkeypatch.setattr(worker, 'process', blocked)
    thread = threading.Thread(target=worker.run_once, args=(queue, registry, settings, 'old'))
    thread.start()
    try:
        assert entered.wait(3)
        expire(queue, aid)
        assert worker.run_once(queue, registry, settings, 'new') is False
        assert queue.get(aid, OWNER).attempts == 1
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()


@pytest.mark.parametrize('max_attempts', [1, 2])
def test_actual_worker_restart_after_kill(account_queue, registry, settings, max_attempts):
    aid = account_queue.enqueue(REGISTERED_ID, OWNER, 3)
    folder = seed_folder(settings, aid)
    # 실제 Worker main을 별도 프로세스로 실행한다. validating의 긴 지연 중 강제 종료한다.
    script = '''
import sys
from pathlib import Path
from dataclasses import replace
from server.config import Settings
from server.jobs.worker import main
s = replace(Settings(), db_path=Path(sys.argv[1]), runtime_dir=Path(sys.argv[2]),
    authorized_media_path=Path(sys.argv[3]), authorized_media_root=Path(sys.argv[4]),
    lease_seconds=.6, heartbeat_interval_seconds=.1, stub_stage_delay_seconds=60)
Settings.from_env = classmethod(lambda cls: s)
main([])
'''
    proc = subprocess.Popen([sys.executable, '-c', script, str(settings.db_path), str(settings.runtime_dir),
                             str(settings.authorized_media_path), str(settings.authorized_media_root)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 5
        while account_queue.get(aid, OWNER).stage != 'validating':
            assert proc.poll() is None and time.monotonic() < deadline
            time.sleep(.02)
        proc.kill()
        proc.wait(timeout=5)
        # lease가 살아 있을 때는 선점하지 않는다. 만료 후 새 Worker가 처리한다.
        assert worker.run_once(account_queue, registry, replace(settings, max_attempts=max_attempts), 'new') is False
        time.sleep(.7)
        worker.run_once(account_queue, registry, replace(settings, max_attempts=max_attempts), 'new')
        job = account_queue.get(aid, OWNER)
        assert job.job_status == ('failed' if max_attempts == 1 else 'finished')
        assert job.attempts == max_attempts
        if max_attempts == 1:
            assert job.failure_reason == 'max_attempts_exceeded'
        assert not folder.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


@pytest.mark.parametrize('engine', ['gate', 'model'])
def test_api_cancel_stops_child_and_descendant_before_cancelled(
    client, registry, settings, monkeypatch, tmp_path, engine,
):
    queue = client.app.state.queue
    import json
    from server.gate import runner
    from server.axes.signal import waverep
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    path = f'/api/v1/analyses/{aid}'
    pidfile = tmp_path / 'pids.json'
    script = tmp_path / 'slow_child.py'
    script.write_text(
        'import os, sys, time, json, subprocess\nfrom pathlib import Path\n'
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f'Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n'
        'time.sleep(60)\n'
    )
    cmd = [sys.executable, str(script)]
    if engine == 'gate':
        monkeypatch.setattr(runner, 'build_command', lambda _: cmd)
    else:
        def slow_model(ctx):
            waverep._run_process(cmd, 30, ctx.heartbeat, .1)
            return {'status': 'error', 'reason_code': 'inference_error', 'raw_score': None}
        monkeypatch.setattr(worker.signal_axis, 'run', slow_model)
        settings = replace(settings, dev_manual_segments=((0, 2),))
    settings = replace(settings, heartbeat_interval_seconds=.1)
    release = threading.Event()
    beat = queue.heartbeat
    def controlled_beat(*args):
        if pidfile.exists():
            assert release.wait(5)
        return beat(*args)
    monkeypatch.setattr(queue, 'heartbeat', controlled_beat)
    errors = []
    def run():
        try:
            worker.run_once(queue, registry, settings, 'w')
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists():
            assert time.monotonic() < deadline and thread.is_alive()
            time.sleep(.01)
        response = client.delete(path)
        assert response.status_code == 202
        assert response.json()['job_status'] == 'processing'
        assert client.delete(path).status_code == 202
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert client.get(path).json()['job_status'] == 'cancelled'
    assert client.get(path + '/result').json()['overall_score'] is None
    assert not (settings.runtime_dir / aid).exists()
    for pid in json.loads(pidfile.read_text()):
        # macOS가 reparent된 좀비를 거두기 전에는 Z가 잠시 보일 수 있다.
        state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                               capture_output=True, text=True, check=False).stdout.strip()
        assert not state or state.startswith('Z')
    assert client.delete(path).status_code == 204


def test_unrelated_cleanup_failure_does_not_block_new_jobs(queue, registry, settings, monkeypatch):
    import uuid
    orphan = str(uuid.uuid4())
    stale = seed_folder(settings, orphan)
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    original = runtime.shutil.rmtree
    def cleanup(path):
        if path == stale:
            raise PermissionError('unrelated stale folder')
        return original(path)
    monkeypatch.setattr(runtime.shutil, 'rmtree', cleanup)
    assert worker.run_once(queue, registry, settings, 'w') is True
    assert queue.get(aid, OWNER).job_status == 'finished'
    assert stale.exists()


@pytest.mark.parametrize('engine', ['gate', 'model'])
def test_worker_death_stops_children_before_recovery(account_queue, registry, settings, tmp_path, engine):
    import json
    pidfile = tmp_path / 'orphan_pids.json'
    aid = account_queue.enqueue(REGISTERED_ID, OWNER, 3)
    folder = settings.runtime_dir / aid
    child = tmp_path / 'orphan_writer.py'
    child.write_text(
        'import os, sys, time, json, subprocess\nfrom pathlib import Path\n'
        "descendant = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f'Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(), descendant.pid]))\n'
        f'folder = Path({str(folder)!r})\n'
        'while True:\n'
        '    folder.mkdir(parents=True, exist_ok=True)\n'
        "    (folder / 'orphan').write_bytes(b'private')\n"
        '    time.sleep(.02)\n'
    )
    bootstrap = '''
import sys
from pathlib import Path
from dataclasses import replace
from server.config import Settings
from server.jobs.worker import main
from server.gate import runner
from server.axes import signal
from server.axes.signal.waverep import _run_process
s = replace(Settings(), db_path=Path(sys.argv[1]), runtime_dir=Path(sys.argv[2]),
    authorized_media_path=Path(sys.argv[3]), authorized_media_root=Path(sys.argv[4]),
    lease_seconds=.6, heartbeat_interval_seconds=.1,
    dev_manual_segments=((0,2),) if sys.argv[6] == 'model' else ())
cmd = [sys.executable, sys.argv[5]]
runner.build_command = lambda _: cmd
def model(ctx):
    _run_process(cmd, 60, ctx.heartbeat, .1)
    return {'status':'error', 'raw_score':None}
signal.run = model
Settings.from_env = classmethod(lambda cls: s)
main([])
'''
    proc = subprocess.Popen([sys.executable, '-c', bootstrap, str(settings.db_path), str(settings.runtime_dir),
                             str(settings.authorized_media_path), str(settings.authorized_media_root), str(child), engine],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pids = []
    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists():
            assert time.monotonic() < deadline and proc.poll() is None
            time.sleep(.01)
        pids = json.loads(pidfile.read_text())
        account_queue.request_cancel(aid, OWNER)
        expire(account_queue, aid)  # 이미 만료된 lease라도 guardian 종료 전 복구가 선행하면 안 된다.
        proc.kill()
        proc.wait(timeout=5)
        deadline = time.monotonic() + 5
        while account_queue.get(aid, OWNER).job_status != 'cancelled':
            worker.run_once(account_queue, registry, settings, 'replacement')
            assert time.monotonic() < deadline
            time.sleep(.01)
        for pid in pids:
            state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                   capture_output=True, text=True).stdout.strip()
            assert not state or state.startswith('Z'), 'orphan child survived recovery'
        time.sleep(.1)
        assert not folder.exists(), 'orphan must not recreate private files after recovery'
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        # RED 실행에서 살아남은 가짜 프로세스도 테스트 후 남기지 않는다.
        import os, signal
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
