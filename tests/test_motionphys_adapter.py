"""MotionPhys 어댑터: 추출 대역을 실제 자식 프로세스로 돌려 격리·취소·JSON 경계를 본다.

trinity 환경에는 OpenCV·MediaPipe가 없어도 된다. 실제 영상 실행은 A·B·E 샘플과
research/motionphys/.venv, 모델 파일이 있을 때만 돈다.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from server.axes.physics import motionphys
from server.axes.physics.motionphys import MotionPhysConfig, run_motionphys

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = REPO_ROOT / 'data/research/samples'

FAKE_HEAD = '''import argparse, json, os, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--request'); p.add_argument('--output')
a = p.parse_args()
r = json.loads(Path(a.request).read_text())
def ok(n, rate=0.8, face=None):
    return {'status': 'completed', 'reason_code': None,
            'valid_trajectories': {'8': n, '12': n // 2, '24': n // 4},
            'moving_trajectories': {'8': n, '12': n // 2, '24': n // 4},
            'tracking_success_rate': None if rate is None else {'8': rate, '12': rate, '24': rate},
            'face_detection_rate': face, 'timing_sec': 0.1, 'features': [1.0, 2.0]}
def bad(reason, n=0):
    v = ok(n); v.update(status='insufficient_input', reason_code=reason); return v
out = {'schema_version': 1, 'variants': {'full': ok(400), 'face_roi': ok(200), 'face_motion': ok(120, None, 1.0)}}
'''
WRITE = "Path(a.output).write_text(json.dumps(out))"


@pytest.fixture
def job(tmp_path):
    work = tmp_path / 'job space'
    work.mkdir()
    video = work / 'media.mp4'
    video.write_bytes(b'authorized job copy')
    return work, video


def fake_config(tmp_path, body, timeout=3):
    script = tmp_path / 'fake_motionphys.py'
    script.write_text(FAKE_HEAD + body)
    return MotionPhysConfig(python=Path(sys.executable), script=script, timeout_sec=timeout)


def alive(pid):
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                           capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


def test_success_returns_summaries_without_score_or_features(tmp_path, job):
    work, video = job
    seen = tmp_path / 'seen.json'
    cfg = fake_config(tmp_path, f"Path({str(seen)!r}).write_text(json.dumps(r)); " + WRITE)
    out = run_motionphys(video, [(1, 3), (5, 8)], work, cfg)
    assert (out['status'], out['reason_code']) == ('completed', None)
    assert out['raw_score'] is None
    assert out['variants']['full']['valid_trajectories'] == {'8': 400, '12': 200, '24': 100}
    assert out['variants']['face_motion']['face_detection_rate'] == 1.0
    assert all('features' not in v for v in out['variants'].values())  # 특징 벡터는 서버로 넘어오지 않는다
    request = json.loads(seen.read_text())
    assert request['segments'] == [[1.0, 3.0], [5.0, 8.0]]
    assert Path(request['video']).is_relative_to(work.resolve())
    assert 'include_features' not in request
    assert list(work.iterdir()) == [video]  # 요청·결과 JSON을 남기지 않는다
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize('reason', ['insufficient_motion', 'tracking_failed', 'segment_too_short'])
def test_primary_candidate_decides_axis_status(tmp_path, job, reason):
    work, video = job
    cfg = fake_config(tmp_path, f"out['variants']['full'] = bad({reason!r}, 5); " + WRITE)
    out = run_motionphys(video, [(0, 3)], work, cfg)
    assert (out['status'], out['reason_code']) == ('insufficient_input', reason)
    assert out['raw_score'] is None
    assert out['variants']['face_roi']['status'] == 'completed'  # 다른 후보의 요약은 남는다


def test_secondary_candidate_failure_does_not_change_axis_status(tmp_path, job):
    work, video = job
    body = ("out['variants']['face_roi'] = bad('tracking_failed'); "
            "out['variants']['face_motion'].update(status='error', reason_code='secret detail', "
            "valid_trajectories=None, moving_trajectories=None); " + WRITE)
    out = run_motionphys(video, [(0, 3)], work, fake_config(tmp_path, body))
    assert out['status'] == 'completed'
    assert out['variants']['face_roi']['reason_code'] == 'tracking_failed'
    assert out['variants']['face_motion']['reason_code'] == 'inference_error'
    assert 'secret detail' not in json.dumps(out)


def test_primary_error_is_inference_error(tmp_path, job):
    work, video = job
    body = "out['variants']['full'].update(status='error', reason_code='media_unreadable', valid_trajectories=None); " + WRITE
    out = run_motionphys(video, [(0, 3)], work, fake_config(tmp_path, body))
    assert (out['status'], out['reason_code']) == ('error', 'inference_error')


@pytest.mark.parametrize('body', [
    WRITE + "; sys.exit(7)",
    "Path(a.output).write_text('{broken')",
    "Path(a.output).write_text('[' * 1100 + '0' + ']' * 1100)",
    "pass",
    "raise RuntimeError('boom')",
    "out['schema_version'] = 2; " + WRITE,
    "del out['variants']['face_roi']; " + WRITE,
    "out['variants']['full']['status'] = 'finished'; " + WRITE,
    "out['variants']['full']['valid_trajectories'] = None; " + WRITE,
    "out['variants']['full']['valid_trajectories']['8'] = -1; " + WRITE,
    "out['variants']['full']['valid_trajectories']['8'] = True; " + WRITE,
    "out['variants']['full']['valid_trajectories']['8'] = 1.5; " + WRITE,
    "del out['variants']['full']['valid_trajectories']['24']; " + WRITE,
    "out['variants']['full']['tracking_success_rate']['8'] = float('nan'); " + WRITE,
    "out['variants']['full']['tracking_success_rate']['8'] = 1.5; " + WRITE,
    "out['variants']['face_motion']['face_detection_rate'] = 10**400; " + WRITE,
    "out['variants'] = []; " + WRITE,
])
def test_bad_or_failed_process_is_isolated(tmp_path, job, body):
    work, video = job
    out = run_motionphys(video, [(0, 3)], work, fake_config(tmp_path, body))
    assert (out['status'], out['reason_code']) == ('error', 'inference_error')
    assert out['raw_score'] is None and out['variants'] is None
    assert 'boom' not in json.dumps(out)
    assert list(work.iterdir()) == [video]


@pytest.mark.parametrize('segments,reason', [([], 'no_segments'), ([(2, 1)], 'invalid_request'),
    ([(0, float('inf'))], 'invalid_request'), ([(False, 3)], 'invalid_request'),
    ([(0, 10**400)], 'invalid_request'), ([None], 'invalid_request'), (['ab'], 'invalid_request')])
def test_no_or_invalid_segments_never_launch(tmp_path, job, segments, reason):
    work, video = job
    cfg = fake_config(tmp_path, "raise AssertionError('must not run')")
    out = run_motionphys(video, segments, work, cfg)
    assert out['reason_code'] == reason
    assert out['status'] == ('insufficient_input' if not segments else 'error')
    assert out['raw_score'] is None
    assert list(work.iterdir()) == [video]


def test_media_outside_job_folder_or_missing_is_rejected(tmp_path, job):
    work, video = job
    cfg = fake_config(tmp_path, "raise AssertionError('must not run')")
    outside = tmp_path / 'outside.mp4'
    outside.write_bytes(b'x')
    assert run_motionphys(outside, [(0, 3)], work, cfg)['reason_code'] == 'invalid_request'
    link = work / 'link.mp4'
    link.symlink_to(outside)
    assert run_motionphys(link, [(0, 3)], work, cfg)['reason_code'] == 'invalid_request'
    assert run_motionphys(work / 'none.mp4', [(0, 3)], work, cfg)['reason_code'] == 'media_unreadable'


def test_missing_environment_is_model_unavailable(tmp_path, job):
    work, video = job
    cfg = MotionPhysConfig(python=tmp_path / 'no-python', script=tmp_path / 'no-script')
    out = run_motionphys(video, [(0, 3)], work, cfg)
    assert (out['status'], out['reason_code']) == ('error', 'model_unavailable')


def test_command_is_argument_list_with_two_job_paths(tmp_path, job, monkeypatch):
    work, video = job
    seen = []
    monkeypatch.setattr(motionphys, '_run', lambda cmd, *a: seen.append(cmd) or 'inference_error')
    run_motionphys(video, [(0, 3)], work, fake_config(tmp_path, "pass"))
    cmd = seen[0]
    assert isinstance(cmd, list) and all(isinstance(c, str) for c in cmd)
    assert cmd[2] == '--request' and cmd[4] == '--output' and len(cmd) == 6
    assert all(Path(cmd[i]).is_relative_to(work.resolve()) for i in (3, 5))


def _spawn_descendant(pidfile):
    return f'''
d = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
tmp = Path({str(pidfile)!r} + '.tmp'); tmp.write_text(json.dumps([os.getpid(), d.pid])); tmp.replace({str(pidfile)!r})
time.sleep(60)
'''


def _wait_dead(pids):
    deadline = time.monotonic() + 5
    while any(alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(.02)
    return [p for p in pids if alive(p)]


def test_timeout_kills_process_group(tmp_path, job):
    work, video = job
    pidfile = tmp_path / 'pids.json'
    cfg = fake_config(tmp_path, _spawn_descendant(pidfile), timeout=1.0)
    started = time.monotonic()
    out = run_motionphys(video, [(0, 3)], work, cfg)
    assert (out['status'], out['reason_code']) == ('error', 'timeout')
    assert time.monotonic() - started < 10
    assert _wait_dead(json.loads(pidfile.read_text())) == []
    assert list(work.iterdir()) == [video]


@pytest.mark.parametrize('how', ['false', 'raise'])
def test_cancel_callback_kills_process_group(tmp_path, job, how):
    work, video = job
    pidfile = tmp_path / 'pids.json'
    cfg = fake_config(tmp_path, _spawn_descendant(pidfile), timeout=30)
    calls = []

    def tick():
        calls.append(1)
        if len(calls) == 1:
            return True  # 시작 전 확인
        if not pidfile.exists():
            return True
        if how == 'raise':
            raise RuntimeError('lease lost')
        return False

    out = run_motionphys(video, [(0, 3)], work, cfg, on_tick=tick, tick_sec=0.05)
    assert (out['status'], out['reason_code']) == ('error', 'aborted')
    assert _wait_dead(json.loads(pidfile.read_text())) == []
    assert list(work.iterdir()) == [video]


def test_cancel_before_start_never_launches(tmp_path, job):
    work, video = job
    cfg = fake_config(tmp_path, "raise AssertionError('must not run')")
    out = run_motionphys(video, [(0, 3)], work, cfg, on_tick=lambda: False)
    assert out['reason_code'] == 'aborted'


def test_tick_is_called_while_waiting(tmp_path, job):
    work, video = job
    cfg = fake_config(tmp_path, "time.sleep(0.4); " + WRITE)
    ticks = []
    out = run_motionphys(video, [(0, 3)], work, cfg, on_tick=lambda: ticks.append(1) or True, tick_sec=0.05)
    assert out['status'] == 'completed' and len(ticks) >= 3


# ---------- 실제 영상 (샘플·venv·모델 파일이 있을 때만) ----------

REAL = MotionPhysConfig()
real_ready = REAL.python.is_file() and (REPO_ROOT / 'data/models/motionphys/face_landmarker.task').is_file()


@pytest.mark.parametrize('name', ['A.MOV', 'B.MOV', 'E.MOV'])
def test_real_sample_extracts_three_candidates(tmp_path, name):
    source = SAMPLES / name
    if not source.is_file() or not real_ready:
        pytest.skip('A·B·E 샘플 또는 research/motionphys/.venv·모델 파일 없음')
    work = tmp_path / 'job'
    work.mkdir()
    video = work / 'media.mov'
    os.link(source, video) if os.stat(source).st_dev == os.stat(work).st_dev else video.write_bytes(source.read_bytes())
    out = run_motionphys(video, [(2.0, 6.0)], work, REAL)
    assert out['status'] in ('completed', 'insufficient_input')
    assert out['raw_score'] is None
    for v in out['variants'].values():
        assert v['status'] in ('completed', 'insufficient_input')
    if out['status'] == 'completed':
        assert all(n >= 20 for n in out['variants']['full']['valid_trajectories'].values())
    assert list(work.iterdir()) == [video]
