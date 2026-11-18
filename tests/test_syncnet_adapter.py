"""모델 대역을 실제 자식 프로세스로 실행하여 격리·취소·JSON 경계를 검증한다."""
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


def adapter():
    name = 'server.axes.alignment.syncnet'
    assert importlib.util.find_spec(name) is not None, 'SyncNet adapter is not implemented'
    return importlib.import_module(name)


@pytest.fixture
def job(tmp_path):
    work = tmp_path / 'job space'
    work.mkdir()
    video = work / 'media.mp4'
    video.write_bytes(b'authorized job copy')
    return work, video


def fake_config(tmp_path, body, timeout=3):
    mod = adapter()
    script = tmp_path / 'fake_model.py'
    script.write_text('''import argparse, json, os, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--request'); p.add_argument('--output')
a = p.parse_args()
r = json.loads(Path(a.request).read_text())
out = {'schema_version': 1, 'segments': [
    {'start_sec': s[0], 'end_sec': s[1], 'status': 'completed', 'reason_code': None,
     'tracks': [{'track_index': 0, 'lse_c': 2.5, 'lse_d': 6.5, 'offset_frames': -2}]}
    for s in r['segments']]}
''' + body)
    return mod.SyncNetConfig(python=Path(sys.executable), script=script, timeout_sec=timeout)


def assert_null(out):
    assert out['lse_c'] is None and out['lse_d'] is None and out['offset_frames'] is None
    assert out['raw_score'] is None and out['included_in_fusion'] is False


def test_success_preserves_segment_track_metrics_and_cleans_job(tmp_path, job):
    work, video = job
    cfg = fake_config(tmp_path, "Path(a.output).write_text(json.dumps(out))")
    out = adapter().run_syncnet(video, [(1, 3), (5, 8)], work, cfg)
    assert out['status'] == 'completed'
    assert out['segments'][1]['start_sec'] == 5
    assert out['segments'][0]['tracks'] == [
        {'track_index': 0, 'lse_c': 2.5, 'lse_d': 6.5, 'offset_frames': -2}]
    assert out['offset_fps'] == 25
    assert_null(out)  # 전체 지표를 임의로 집계하지 않는다
    assert list(work.iterdir()) == [video]
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize('body', [
    "Path(a.output).write_text(json.dumps(out)); sys.exit(7)",
    "Path(a.output).write_text('{broken')",
    "Path(a.output).write_text('[' * 1100 + '0' + ']' * 1100)",
    "pass",
    "out['segments'][0]['tracks'][0]['lse_c'] = float('nan'); Path(a.output).write_text(json.dumps(out))",
    "out['segments'][0]['tracks'][0]['lse_c'] = 10**400; Path(a.output).write_text(json.dumps(out))",
    "out['segments'][0]['tracks'][0]['offset_frames'] = True; Path(a.output).write_text(json.dumps(out))",
    "out['segments'][0]['tracks'][0]['lse_d'] = -1; Path(a.output).write_text(json.dumps(out))",
    "out['segments'][0]['tracks'] = []; Path(a.output).write_text(json.dumps(out))",
    "out['segments'][0]['start_sec'] = 99; Path(a.output).write_text(json.dumps(out))",
    "out['segments'] = []; Path(a.output).write_text(json.dumps(out))",
    "out['schema_version'] = 2; Path(a.output).write_text(json.dumps(out))",
    "out['segments'][0]['status'] = 'finished'; Path(a.output).write_text(json.dumps(out))",
])
def test_bad_or_failed_process_never_returns_metrics(tmp_path, job, body):
    work, video = job
    out = adapter().run_syncnet(video, [(0, 3)], work, fake_config(tmp_path, body))
    assert out['status'] == 'error' and out['reason_code'] == 'inference_error'
    assert out['segments'] is None
    assert_null(out)
    assert list(work.iterdir()) == [video]


def test_failed_segment_cannot_smuggle_scores_and_other_segment_is_preserved(tmp_path, job):
    work, video = job
    body = "out['segments'][0].update(status='error', reason_code='inference_error'); Path(a.output).write_text(json.dumps(out))"
    out = adapter().run_syncnet(video, [(0, 3), (5, 8)], work, fake_config(tmp_path, body))
    assert out['status'] == 'error'
    assert out['segments'][0]['tracks'] is None
    assert out['segments'][1]['tracks'][0]['lse_c'] == 2.5
    assert_null(out)


@pytest.mark.parametrize('segments,reason', [([], 'no_segments'), ([(2, 1)], 'invalid_request'),
    ([(0, float('inf'))], 'invalid_request'), ([(False, 3)], 'invalid_request'),
    ([(0, 10**400)], 'invalid_request'),
    ([None], 'invalid_request'), (['ab'], 'invalid_request')])
def test_no_or_invalid_segments_never_launch(tmp_path, job, segments, reason):
    work, video = job
    cfg = fake_config(tmp_path, "raise AssertionError('must not run')")
    out = adapter().run_syncnet(video, segments, work, cfg)
    assert out['reason_code'] == reason
    assert out['status'] == ('insufficient_input' if not segments else 'error')
    assert_null(out)
    assert list(work.iterdir()) == [video]


def test_rejects_media_outside_job_even_through_symlink(tmp_path, job):
    work, video = job
    outside = tmp_path / 'private.mp4'
    outside.write_bytes(b'outside')
    link = work / 'link.mp4'
    link.symlink_to(outside)
    cfg = fake_config(tmp_path, "raise AssertionError('must not run')")
    for source in (outside, link):
        out = adapter().run_syncnet(source, [(0, 3)], work, cfg)
        assert out['reason_code'] == 'invalid_request'
        assert_null(out)


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), True])
def test_invalid_timeout_never_launch(tmp_path, job, timeout):
    work, video = job
    out = adapter().run_syncnet(video, [(0, 3)], work,
                              fake_config(tmp_path, 'time.sleep(60)', timeout))
    assert out['reason_code'] == 'invalid_request'
    assert_null(out)


def alive(pid):
    result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')


@pytest.mark.parametrize('stop', ['timeout', 'cancel', 'callback_error', 'parent_exit'])
def test_stop_kills_descendant_and_cleans_files(tmp_path, job, stop):
    work, video = job
    pidfile = tmp_path / 'pid.json'
    body = f'''child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path({str(pidfile)!r}).write_text(json.dumps([os.getpid(), child.pid]))
Path(a.output).with_name('private_crop.jpg').write_bytes(b'private')
'''
    body += "Path(a.output).write_text(json.dumps(out))" if stop == 'parent_exit' else 'time.sleep(60)'
    cfg = fake_config(tmp_path, body, timeout=0.6 if stop == 'timeout' else 3)
    def tick():
        if not pidfile.exists():
            return True
        if stop == 'callback_error':
            raise RuntimeError('caller failed')
        return stop != 'cancel'
    pids = []
    try:
        out = adapter().run_syncnet(video, [(0, 3)], work, cfg, on_tick=tick, tick_sec=0.02)
        pids = json.loads(pidfile.read_text())
        if stop == 'parent_exit':
            assert out['status'] == 'completed'
        else:
            assert out['reason_code'] == ('timeout' if stop == 'timeout' else 'aborted')
            assert_null(out)
        deadline = time.monotonic() + 2
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(alive(pid) for pid in pids)
        assert list(work.iterdir()) == [video]
    finally:
        if pidfile.exists():
            for pid in json.loads(pidfile.read_text()):
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass


def test_old_result_is_not_reused_and_empty_worker_input_is_skipped(tmp_path, job):
    from server.axes import AxisContext
    from server.axes import alignment
    work, video = job
    old = work / 'syncnet_result.json'
    old.write_text('old result from another invocation')
    cfg = fake_config(tmp_path, 'pass')
    out = adapter().run_syncnet(video, [(0, 3)], work, cfg)
    assert out['status'] == 'error'
    assert old.read_text() == 'old result from another invocation'
    assert alignment.run(AxisContext(job_dir=work))['reason_code'] == 'no_segments'


def test_device_is_mps_by_default_and_passed_to_runner(tmp_path, job):
    from dataclasses import replace
    work, video = job
    seen = tmp_path / 'seen.json'
    body = f"Path({str(seen)!r}).write_text(json.dumps(r)); out['device_used'] = r['device']; Path(a.output).write_text(json.dumps(out))"
    cfg = fake_config(tmp_path, body)
    assert cfg.device == 'mps'  # docs/DESIGN.md §15.3 2026-11-17. 못 쓰면 실행기가 cpu로 대체한다
    out = adapter().run_syncnet(video, [(0, 3)], work, cfg)
    assert json.loads(seen.read_text())['device'] == 'mps' and out['device_used'] == 'mps'
    out = adapter().run_syncnet(video, [(0, 3)], work, replace(cfg, device='cpu'))
    assert json.loads(seen.read_text())['device'] == 'cpu' and out['device_used'] == 'cpu'
    assert out['status'] == 'completed' and out['raw_score'] is None


@pytest.mark.parametrize('device', ['cuda', 'cuda:0', '', None, 'gpu'])
def test_other_devices_never_launch(tmp_path, job, device):
    from dataclasses import replace
    work, video = job
    cfg = replace(fake_config(tmp_path, "raise AssertionError('must not run')"), device=device)
    out = adapter().run_syncnet(video, [(0, 3)], work, cfg)
    assert (out['status'], out['reason_code']) == ('error', 'invalid_request')



# ---------- 짧은 구간 제외 규칙 (docs/DESIGN.md §15.3 결정 2·8 보완, 2026-11-17) ----------

SHORT = "out['segments'][{i}].update(status='insufficient_input', reason_code='segment_too_short', tracks=None);"
NOTRACK = "out['segments'][{i}].update(status='insufficient_input', reason_code=None, tracks=None);"


@pytest.mark.parametrize('edits,status,reason', [
    ([], 'completed', None),
    ([SHORT.format(i=1)], 'completed', None),                                   # 짧은 구간만 빠지고 나머지는 모두 트랙
    ([SHORT.format(i=0), SHORT.format(i=2)], 'completed', None),
    ([SHORT.format(i=0), SHORT.format(i=1), SHORT.format(i=2)], 'insufficient_input', 'segment_too_short'),
    ([SHORT.format(i=0), NOTRACK.format(i=1)], 'insufficient_input', 'tracking_failed'),  # 남은 구간에 트랙 없음
    ([SHORT.format(i=0), "out['segments'][1].update(status='error', tracks=None);"], 'error', 'inference_error'),
    ([NOTRACK.format(i=2)], 'insufficient_input', 'tracking_failed'),
])
def test_short_segments_are_excluded_from_axis_status(tmp_path, job, edits, status, reason):
    work, video = job
    cfg = fake_config(tmp_path, "".join(edits) + "Path(a.output).write_text(json.dumps(out))")
    out = adapter().run_syncnet(video, [(0, 1.5), (2, 6), (7, 9)], work, cfg)
    assert (out['status'], out['reason_code']) == (status, reason)
    assert_null(out)
    short = [row for row in out['segments'] if row['reason_code'] == 'segment_too_short']
    assert all(row['tracks'] is None and row['status'] == 'insufficient_input' for row in short)


def test_other_failure_reasons_are_not_promoted_to_short(tmp_path, job):
    work, video = job
    body = "out['segments'][0].update(status='insufficient_input', reason_code='anything', tracks=None);"
    out = adapter().run_syncnet(video, [(0, 3)], work, fake_config(tmp_path, body + "Path(a.output).write_text(json.dumps(out))"))
    assert out['reason_code'] == 'tracking_failed'
    body = "out['segments'][0].update(status='error', reason_code='segment_too_short', tracks=None);"
    out = adapter().run_syncnet(video, [(0, 3)], work, fake_config(tmp_path, body + "Path(a.output).write_text(json.dumps(out))"))
    assert out['reason_code'] == 'inference_error'  # 오류는 짧은 구간으로 숨길 수 없다
