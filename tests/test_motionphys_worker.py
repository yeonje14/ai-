"""MotionPhys → Worker: 상태 전달, 설명, lease 연장, 취소, Worker SIGKILL 복구."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from server.axes import physics
from server.gate.types import GateResult, Segment
from server.jobs import worker
from server.schemas import AnalysisResult
from tests.conftest import REGISTERED_ID
from tests.test_gate_worker import MEDIA, run_job
from tests.test_motionphys_adapter import WRITE, alive, fake_config

OWNER = 'gate-owner'
REAL_BUILD_CONFIG = physics.build_config  # conftest가 바꾸기 전의 실제 함수


@pytest.fixture
def others(monkeypatch):
    """Gate는 구간 두 개를 주고 signal·alignment는 완료된 것으로 둔다."""
    monkeypatch.setattr(worker, 'run_gate_process', lambda *a, **k: GateResult(
        MEDIA, None, eligible_segments=(Segment(1, 3), Segment(5, 8))))
    monkeypatch.setattr(worker.signal_axis, 'run', lambda ctx: {'status': 'completed', 'raw_score': None})
    monkeypatch.setattr(worker.alignment, 'run', lambda ctx: {
        'status': 'completed', 'reason_code': None, 'lse_c': None, 'lse_d': None, 'included_in_fusion': False})


def use(monkeypatch, tmp_path, body, timeout=3):
    cfg = fake_config(tmp_path, body, timeout)
    monkeypatch.setattr(physics, 'build_config', lambda ctx: cfg)


def physics_notes(result):
    return [e for e in result['explanations'] if e['template_id'].startswith('MOTIONPHYS')]


def test_completed_axis_has_null_score_and_summary_in_explanations(queue, registry, settings, monkeypatch, tmp_path, others):
    use(monkeypatch, tmp_path, WRITE)
    _, job = run_job(queue, registry, settings)
    r = job.result
    AnalysisResult.model_validate(r)
    assert r['axes']['physics'] == {'status': 'completed', 'reason_code': None, 'raw_score': None,
                                    'model_version': physics.MODEL_VERSION}  # 새 API 필드 없음
    # 세 축이 모두 돌면 기존 규칙대로 completed. 판정 가능 여부는 verdict_status가 맡는다.
    assert (job.job_status, r['analysis_status'], r['verdict_status']) == ('finished', 'completed', 'abstained')
    assert r['abstention_reason'] == 'no_valid_fusion_model'
    assert r['overall_score'] is None and r['verdict_label'] is None
    note, = physics_notes(r)
    assert note['template_id'] == 'MOTIONPHYS_FEATURES_ONLY' and note['reason_code'] == 'unvalidated_condition'
    msg = note['message']
    assert '분석 구간 2개, 5.0초' in msg
    assert '전체 화면(A): 유효 궤적 400/200/100개, 추적 성공률 80%/80%/80%' in msg
    assert '얼굴 영역(B): 유효 궤적 200/100/50개' in msg
    assert 'Face Motion(C): 유효 궤적 120/60/30개, 얼굴 검출률 100%' in msg
    assert '종합 판정에 포함하지 않습니다' in msg
    assert not (settings.runtime_dir / job.analysis_id).exists()


@pytest.mark.parametrize('body,status,reason', [
    ("out['variants']['full'] = bad('insufficient_motion', 30); " + WRITE, 'insufficient_input', 'insufficient_motion'),
    ("out['variants']['full'] = bad('tracking_failed', 3); " + WRITE, 'insufficient_input', 'tracking_failed'),
    ("raise RuntimeError('boom')", 'error', 'inference_error'),
    ("time.sleep(30)", 'error', 'timeout'),
])
def test_failures_are_isolated_with_null_score(queue, registry, settings, monkeypatch, tmp_path, others,
                                               body, status, reason):
    use(monkeypatch, tmp_path, body, timeout=0.5)
    _, job = run_job(queue, registry, settings)
    r = job.result
    assert job.job_status == 'finished'
    assert r['axes']['physics'] == {'status': status, 'reason_code': reason, 'raw_score': None,
                                    'model_version': physics.MODEL_VERSION}
    assert r['axes']['signal']['status'] == 'completed' and r['axes']['alignment']['status'] == 'completed'
    assert (r['analysis_status'], r['verdict_status']) == ('partial', 'abstained')
    assert r['overall_score'] is None and r['verdict_label'] is None
    note, = physics_notes(r)
    assert note['template_id'] == 'MOTIONPHYS_NOT_ANALYZED' and note['reason_code'] == reason
    assert 'boom' not in json.dumps(r)


def test_no_segments_never_launches(queue, registry, settings, monkeypatch, tmp_path):
    use(monkeypatch, tmp_path, "raise AssertionError('must not run')")
    from server.axes import AxisContext
    out = physics.run(AxisContext(job_dir=tmp_path, settings=settings, media_path=tmp_path / 'm.mp4', segments=()))
    assert out == {'status': 'insufficient_input', 'reason_code': 'no_segments', 'raw_score': None,
                   'model_version': physics.MODEL_VERSION}


def test_stage_timeout_is_capped_by_setting_and_job_budget(settings):
    from server.axes import AxisContext
    ctx = AxisContext(job_dir=settings.runtime_dir, settings=replace(settings, motionphys_timeout_seconds=40))
    assert REAL_BUILD_CONFIG(ctx).timeout_sec == 40
    ctx.timeout_seconds = 7.5
    assert REAL_BUILD_CONFIG(ctx).timeout_sec == 7.5


@pytest.mark.parametrize('cancel', [False, True])
def test_heartbeat_extends_lease_and_cancel_stops_job(queue, registry, settings, monkeypatch, tmp_path, others, cancel):
    use(monkeypatch, tmp_path, "time.sleep(0.25); " + WRITE)
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    original = queue.heartbeat
    leases = []

    def heartbeat(*args):
        state = original(*args)
        with sqlite3.connect(settings.db_path) as db:
            stage, lease = db.execute('select stage,lease_expires_at from jobs where analysis_id=?', (aid,)).fetchone()
        if stage == 'motionphys':
            leases.append(lease)
            if cancel and len(leases) == 2:
                queue.request_cancel(aid, OWNER)
        return state

    monkeypatch.setattr(queue, 'heartbeat', heartbeat)
    assert worker.run_once(queue, registry, replace(settings, heartbeat_interval_seconds=0.02), 'mp-worker')
    job = queue.get(aid, OWNER)
    assert job.job_status == ('cancelled' if cancel else 'finished')
    assert len(set(leases)) >= 2
    assert not (settings.runtime_dir / aid).exists()


BOOTSTRAP = '''
import sys
from pathlib import Path
from dataclasses import replace
from server.config import Settings
from server.jobs import worker
from server.axes import physics
from server.axes.physics.motionphys import MotionPhysConfig
from server.gate.types import GateResult, Segment
from tests.test_gate_worker import MEDIA
s = replace(Settings(), db_path=Path(sys.argv[1]), runtime_dir=Path(sys.argv[2]),
    authorized_media_path=Path(sys.argv[3]), authorized_media_root=Path(sys.argv[4]),
    lease_seconds=.6, heartbeat_interval_seconds=.1, max_attempts=int(sys.argv[6]))
worker.run_gate_process = lambda *a, **k: GateResult(MEDIA, None, eligible_segments=(Segment(1,3),))
worker.signal_axis.run = lambda ctx: {'status':'completed', 'raw_score':None}
worker.alignment.run = lambda ctx: {'status':'completed', 'reason_code':None, 'lse_c':None, 'lse_d':None, 'included_in_fusion':False}
physics.build_config = lambda ctx: MotionPhysConfig(python=Path(sys.executable), script=Path(sys.argv[5]), timeout_sec=60)
Settings.from_env = classmethod(lambda cls: s)
worker.main(['--drain'])
'''


@pytest.mark.parametrize('outcome,max_attempts', [('retry', 2), ('exhausted', 1), ('cancel', 2)])
def test_worker_sigkill_stops_group_and_recovers(queue, registry, settings, tmp_path, outcome, max_attempts):
    marker = tmp_path / 'first-attempt'
    pidfile = tmp_path / 'pids.json'
    cfg = fake_config(tmp_path, f'''
marker = Path({str(marker)!r})
if not marker.exists():
    marker.touch()
    descendant = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    pidfile = Path({str(pidfile)!r})
    tmp = pidfile.with_suffix('.tmp')
    tmp.write_text(json.dumps([os.getpid(), descendant.pid]))
    tmp.replace(pidfile)
    while True:
        (Path(a.request).parent / 'orphan').write_text('temporary frames')
        time.sleep(.02)
assert not list(Path(a.request).parent.parent.rglob('orphan')), 'stale temp survived retry'
''' + WRITE)
    aid = queue.enqueue(REGISTERED_ID, 'mp-owner', 3)
    folder = settings.runtime_dir / aid
    command = [sys.executable, '-c', BOOTSTRAP, str(settings.db_path), str(settings.runtime_dir),
               str(settings.authorized_media_path), str(settings.authorized_media_root),
               str(cfg.script), str(max_attempts)]
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
        job = queue.get(aid, 'mp-owner')
        assert job.job_status == 'processing' and job.stage == 'motionphys'
        assert folder.exists()
        if outcome == 'cancel':
            queue.request_cancel(aid, 'mp-owner')
        proc.kill()
        proc.wait(timeout=5)
        deadline = time.monotonic() + 5
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(.02)
        survivors = [pid for pid in pids if alive(pid)]
        assert not survivors, f'MotionPhys group survived Worker SIGKILL: {survivors}'
        time.sleep(.7)  # lease 자연 만료
        replacement = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        processes.append(replacement)
        assert replacement.wait(timeout=10) == 0
        job = queue.get(aid, 'mp-owner')
        assert job.job_status == {'retry': 'finished', 'exhausted': 'failed', 'cancel': 'cancelled'}[outcome]
        if outcome == 'retry':
            assert job.attempts == 2
            assert job.result['axes']['physics']['status'] == 'completed'
            assert job.result['axes']['physics']['raw_score'] is None
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


@pytest.mark.parametrize('variants', [True, False])
@pytest.mark.parametrize('status,reason', [('completed', None), ('insufficient_input', 'insufficient_motion'),
                                           ('error', 'timeout')])
def test_explanation_has_only_the_three_contract_keys(status, reason, variants):
    """explanations 항목은 기존 계약의 세 키뿐이다. 축 결과 필드(status, raw_score 등)가 섞이지 않는다."""
    summary = {'status': 'completed', 'reason_code': None, 'valid_trajectories': {'8': 9, '12': 6, '24': 3},
               'moving_trajectories': None, 'tracking_success_rate': None, 'face_detection_rate': None}
    out = {'status': status, 'reason_code': reason, 'raw_score': None, 'model_version': physics.MODEL_VERSION,
           'variants': {name: summary for name in ('full', 'face_roi', 'face_motion')} if variants else None}
    note = physics.explanation(out, ((1, 3),))
    assert set(note) == {'template_id', 'reason_code', 'message'}
    assert all(isinstance(v, str) and v for v in note.values())
    assert 'stub' not in json.dumps(note, ensure_ascii=False).lower()


def test_axis_result_has_exactly_the_physics_schema_fields(tmp_path, settings, monkeypatch):
    from server.axes import AxisContext
    from server.schemas import PhysicsAxis
    use(monkeypatch, tmp_path, WRITE)
    work = tmp_path / 'job'
    work.mkdir()
    (work / 'media.mp4').write_bytes(b'x')
    ctx = AxisContext(job_dir=work, settings=settings, media_path=work / 'media.mp4', segments=((1, 3),))
    out = physics.run(ctx)
    assert set(out) == set(PhysicsAxis.model_fields) == {'status', 'reason_code', 'raw_score', 'model_version'}
    assert not hasattr(physics, 'STUB_REASON') and out['model_version'] != 'stub'
    assert len(ctx.explanations) == 1
