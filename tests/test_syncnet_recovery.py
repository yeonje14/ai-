"""실제 Worker SIGKILL 뒤 SyncNet/FFmpeg 대역 그룹과 lease 복구를 확인한다."""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from tests.conftest import REGISTERED_ID
from tests.test_syncnet_adapter import fake_config


def alive(pid):
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                           capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


BOOTSTRAP = '''
import sys
from pathlib import Path
from dataclasses import replace
from server.config import Settings
from server.jobs import worker
from server.axes import alignment
from server.axes.alignment.syncnet import SyncNetConfig
from server.gate.types import GateResult, Segment
from tests.test_gate_worker import MEDIA
s = replace(Settings(), db_path=Path(sys.argv[1]), runtime_dir=Path(sys.argv[2]),
    authorized_media_path=Path(sys.argv[3]), authorized_media_root=Path(sys.argv[4]),
    lease_seconds=.6, heartbeat_interval_seconds=.1, max_attempts=int(sys.argv[7]))
worker.run_gate_process = lambda *a, **k: GateResult(MEDIA, None, eligible_segments=(Segment(1,3),))
worker.signal_axis.run = lambda ctx: {'status':'completed', 'raw_score':None}
alignment.build_config = lambda ctx: SyncNetConfig(python=Path(sys.executable),
    script=Path(sys.argv[5]), weights_dir=Path(sys.argv[6]), timeout_sec=60)
Settings.from_env = classmethod(lambda cls: s)
worker.main(['--drain'])
'''


@pytest.mark.parametrize('outcome,max_attempts', [('retry', 2), ('exhausted', 1), ('cancel', 2)])
def test_syncnet_worker_death_stops_group_and_recovers(queue, registry, settings, tmp_path,
                                                       outcome, max_attempts):
    marker = tmp_path / 'first-attempt'
    pidfile = tmp_path / 'pids.json'
    cfg = fake_config(tmp_path, f'''
import os, subprocess
marker = Path({str(marker)!r})
if not marker.exists():
    marker.touch()
    descendant = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    pidfile = Path({str(pidfile)!r})
    tmp = pidfile.with_suffix('.tmp')
    tmp.write_text(json.dumps([os.getpid(), descendant.pid]))
    tmp.replace(pidfile)
    while True:
        Path(a.request).parent.mkdir(parents=True, exist_ok=True)
        (Path(a.request).parent / 'orphan').write_text('temporary crop')
        time.sleep(.02)
assert not list(Path(a.request).parent.parent.rglob('orphan')), 'stale crop survived retry'
Path(a.output).write_text(json.dumps(out))
''')
    aid = queue.enqueue(REGISTERED_ID, 'sync-owner', 3)
    folder = settings.runtime_dir / aid
    command = [sys.executable, '-c', BOOTSTRAP, str(settings.db_path), str(settings.runtime_dir),
               str(settings.authorized_media_path), str(settings.authorized_media_root),
               str(cfg.script), str(cfg.weights_dir), str(max_attempts)]
    pids, processes = [], []
    log = (tmp_path / 'worker.log').open('w')
    try:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        processes.append(proc)
        deadline = time.monotonic() + 10
        while not pidfile.exists():
            assert proc.poll() is None and time.monotonic() < deadline
            time.sleep(.02)
        pids = json.loads(pidfile.read_text())
        assert all(alive(pid) for pid in pids)
        job = queue.get(aid, 'sync-owner')
        assert job.job_status == 'processing' and job.stage == 'syncnet'
        assert folder.exists()
        if outcome == 'cancel':
            queue.request_cancel(aid, 'sync-owner')
        proc.kill()
        proc.wait(timeout=5)
        deadline = time.monotonic() + 5
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(.02)
        survivors = [pid for pid in pids if alive(pid)]
        assert not survivors, f'SyncNet/FFmpeg survived Worker SIGKILL: {survivors}'
        # lease가 자연 만료된 뒤 별도 Worker 프로세스를 시작한다.
        time.sleep(.7)
        replacement = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        processes.append(replacement)
        assert replacement.wait(timeout=10) == 0
        job = queue.get(aid, 'sync-owner')
        assert job.job_status == {'retry':'finished', 'exhausted':'failed', 'cancel':'cancelled'}[outcome]
        if outcome == 'retry':
            assert job.attempts == 2
            assert job.result['axes']['alignment']['status'] == 'completed'
        elif outcome == 'exhausted':
            assert job.failure_reason == 'max_attempts_exceeded'
        assert not folder.exists()
        time.sleep(.1)
        assert not folder.exists() and not any(alive(pid) for pid in pids)
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()
