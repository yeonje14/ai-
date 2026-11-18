"""무거운 모델 대신 원본 반환 형식의 대역을 써서 실행기 경계를 검사한다."""
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def runner():
    name = 'research.syncnet.infer_segments'
    assert importlib.util.find_spec(name) is not None, 'segment runner is not implemented'
    return importlib.import_module(name)


def output(offsets=None, confs=None, dists=None, has_face=True):
    return (offsets if offsets is not None else [-2, 3],
            confs if confs is not None else [8.0, 2.0],
            dists if dists is not None else [7.0, 4.0], 8.0, 4.0, 'private boxes', has_face)


def test_same_track_metrics_are_paired_not_independent_extrema():
    tracks = runner().tracks_from_output(output())
    assert tracks == [
        {'track_index': 0, 'offset_frames': -2, 'lse_c': 8.0, 'lse_d': 7.0},
        {'track_index': 1, 'offset_frames': 3, 'lse_c': 2.0, 'lse_d': 4.0}]
    assert 'private' not in json.dumps(tracks)


@pytest.mark.parametrize('value', [output([], [], [], False), output([], [], [], True)])
def test_no_track_produces_no_metrics(value):
    assert runner().tracks_from_output(value) == []


@pytest.mark.parametrize('value', [output(confs=[8.0]), output(offsets=[True, 3]),
    output(offsets=[1.5, 3]), output(confs=[float('nan'), 2]), output(dists=[7, float('inf')]),
    output(dists=[7, -1]), output(has_face=False)])
def test_malformed_upstream_metrics_are_rejected(value):
    with pytest.raises(ValueError):
        runner().tracks_from_output(value)


@pytest.fixture
def runner_request(tmp_path):
    video = tmp_path / 'media.mp4'
    video.write_bytes(b'authorized')
    work = tmp_path / 'syncnet-work'
    work.mkdir()
    req = {'video': str(video), 'segments': [[1, 4], [6, 10]], 'weights_dir': str(tmp_path / 'weights')}
    return work, req


def test_segment_failure_does_not_prevent_next_segment_and_cleans(tmp_path, runner_request, monkeypatch):
    mod = runner()
    work, req = runner_request
    calls = []
    def cut(video, start, end, dest):
        calls.append((start, end))
        dest.write_bytes(b'clip')
    monkeypatch.setattr(mod, 'cut_segment', cut)
    class Pipeline:
        count = 0
        def inference(self, video_path, *, cache_dir):
            self.count += 1
            cache = Path(cache_dir)
            cache.mkdir(parents=True)
            (cache / 'face.jpg').write_bytes(b'private')
            if self.count == 1:
                raise RuntimeError('private video details')
            return output()
    result = mod.infer_segments(req, work, Pipeline())
    assert calls == [(1, 4), (6, 10)]
    first, second = result['segments']
    assert first['status'] == 'error' and first['tracks'] is None
    assert all(first[key] is None for key in ('lse_c', 'lse_d', 'offset_frames'))
    assert second['status'] == 'completed' and len(second['tracks']) == 2
    assert list(work.iterdir()) == []
    assert 'private' not in json.dumps(result)


def test_no_tracks_are_insufficient_input(runner_request, monkeypatch):
    mod = runner()
    work, req = runner_request
    monkeypatch.setattr(mod, 'cut_segment', lambda *args: None)
    class Pipeline:
        def inference(self, *args, **kwargs):
            return output([], [], [], False)
    result = mod.infer_segments(req, work, Pipeline())
    assert all(row['status'] == 'insufficient_input' and row['tracks'] is None
               for row in result['segments'])


def test_cut_command_has_shared_av_time_window_and_argument_list(tmp_path, monkeypatch):
    mod = runner()
    calls = []
    monkeypatch.setattr(mod.subprocess, 'run', lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    source, dest = tmp_path / 'a b.mp4', tmp_path / 'clip.avi'
    mod.cut_segment(source, 1.25, 4.75, dest)
    cmd, kwargs = calls[0]
    assert isinstance(cmd, list) and kwargs.get('shell', False) is False
    assert cmd[cmd.index('-i') + 1] == str(source)
    assert cmd[cmd.index('-ss') + 1] == '1.25' and cmd[cmd.index('-t') + 1] == '3.5'
    assert [cmd[i + 1] for i, token in enumerate(cmd) if token == '-map'] == ['0:v:0', '0:a:0']
    assert cmd[cmd.index('-c:a') + 1] == 'pcm_s16le'
    assert 'videotoolbox' not in ' '.join(cmd).lower()
    assert kwargs['check'] is True


def test_hash_mismatch_stops_before_model_import(tmp_path):
    mod = runner()
    weights = tmp_path / 'weights'
    weights.mkdir()
    (weights / 'syncnet_v2.model').write_bytes(b'wrong')
    with pytest.raises(ValueError, match='hash'):
        mod.load_pipeline(weights)


def test_main_writes_internal_json_and_cpu_only_configuration(runner_request, monkeypatch, capsys):
    mod = runner()
    work, req = runner_request
    args = work / 'request.json'
    dest = work / 'result.json'
    args.write_text(json.dumps(req))
    loaded = []
    monkeypatch.setattr(mod, 'load_pipeline', lambda path: loaded.append(path) or object())
    monkeypatch.setattr(mod, 'infer_segments', lambda body, folder, pipeline:
                        {'schema_version': 1, 'segments': []})
    assert mod.main(['--request', str(args), '--output', str(dest)]) == 0
    assert loaded == [Path(req['weights_dir'])]
    assert json.loads(dest.read_text()) == {'schema_version': 1, 'segments': []}
    assert capsys.readouterr().out == ''


def test_model_configuration_explicitly_uses_cpu_and_verified_weights(tmp_path, monkeypatch):
    mod = runner()
    calls = []
    import types
    package = types.ModuleType('syncnet_python')
    package.SyncNetPipeline = lambda **kwargs: calls.append(kwargs) or object()
    monkeypatch.setitem(sys.modules, 'syncnet_python', package)
    monkeypatch.setattr(mod, 'verify_weights', lambda path: calls.append(path))
    mod.load_pipeline(tmp_path)
    assert calls[0] == tmp_path
    assert calls[1] == {'device': 'cpu', 'syncnet_weights': str(tmp_path / 'syncnet_v2.model'),
                        's3fd_weights': str(tmp_path / 'sfd_face.pth')}


def test_main_rejects_work_escape_before_loading_model(runner_request, tmp_path, monkeypatch):
    mod = runner()
    work, req = runner_request
    other = tmp_path.parent / 'not_this_job.mp4'
    req['video'] = str(other)
    args = work / 'request.json'
    args.write_text(json.dumps(req))
    monkeypatch.setattr(mod, 'load_pipeline', lambda path: pytest.fail('model must not load'))
    assert mod.main(['--request', str(args), '--output', str(work / 'result.json')]) == 1


# ---------- 짧은 구간 건너뛰기 (결과는 같고 S3FD만 돌리지 않는다) ----------

class FakeUpstream:
    """upstream inference의 관련 부분만 흉내 낸다: 프레임마다 검출 → 장면 길이가 min_track 이상일 때만 트랙."""

    def __init__(self, frames_by_clip, min_track=50, faces=True):
        import types
        self.cfg = types.SimpleNamespace(min_track=min_track)
        self.real_calls = 0
        self.frames_by_clip, self.faces = frames_by_clip, faces
        self.s3fd = types.SimpleNamespace(detect_faces=self._detect)

    def _detect(self, image, *args, **kwargs):
        self.real_calls += 1
        return [[0, 0, 10, 10, 0.99]] if self.faces else []

    def inference(self, clip, cache_dir=None):
        n = self.frames_by_clip.pop(0)
        self.current = n
        detections = [self.s3fd.detect_faces(object(), conf_th=0.9, scales=[0.25]) for _ in range(n)]
        has_track = n >= self.cfg.min_track and all(len(d) for d in detections)  # 장면 하나 = 구간 전체
        if not has_track:
            return ([], [], [], 0.0, 0.0, '', False)
        return ([4], [5.0], [8.0], 5.0, 8.0, 'boxes', True)


def run_fake(mod, monkeypatch, frames, guard: bool, counter=None, **kw):
    pipeline = FakeUpstream(list(frames), **kw)
    monkeypatch.setattr(mod, 'cut_segment', lambda *a: None)
    monkeypatch.setattr(mod, 'count_frames', counter or (lambda cache: pipeline.current))
    if not guard:
        monkeypatch.setattr(mod, 'install_guard', lambda p: None)
    else:
        monkeypatch.setattr(mod, 'install_guard', lambda p: _install(mod, p))
    segments = [[float(i), float(i) + 3] for i in range(len(frames))]
    import tempfile
    with tempfile.TemporaryDirectory() as work:
        out = mod.infer_segments({'video': 'v', 'segments': segments}, Path(work), pipeline)
    return out, pipeline


def _install(mod, pipeline):
    guard = mod.ShortSegmentGuard(pipeline.s3fd.detect_faces, pipeline.cfg.min_track, lambda cache: mod.count_frames(cache))
    pipeline.s3fd.detect_faces = guard
    return guard


@pytest.mark.parametrize('frames', [[30], [49], [50], [51], [200], [41, 255, 39, 170, 49, 63], [0]])
def test_short_segment_guard_keeps_tracks_identical_and_marks_short_segments(monkeypatch, frames):
    mod = runner()
    plain, p_plain = run_fake(mod, monkeypatch, frames, guard=False)
    guarded, p_guard = run_fake(mod, monkeypatch, frames, guard=True)
    assert p_plain.real_calls == sum(frames)
    assert p_guard.real_calls == sum(n for n in frames if n >= 50)  # min_track 미만 구간은 검출을 돌리지 않는다
    for g, p, n in zip(guarded['segments'], plain['segments'], frames):
        assert (g['tracks'], g['status'], g['start_sec']) == (p['tracks'], p['status'], p['start_sec'])  # 트랙은 같다
        if n >= 50 or n == 0:  # 프레임이 하나도 없으면 셀 기회가 없어 기존대로 둔다(실제 upstream은 오류를 낸다)
            assert g == p
        else:  # 규칙(docs/DESIGN.md §15.3 2026-11-17): 트랙이 없던 이유를 짧은 구간으로 밝힌다
            assert (p['reason_code'], g['reason_code']) == ('tracking_failed', 'segment_too_short')


def test_guard_boundary_is_upstream_min_track_not_duration(monkeypatch):
    mod = runner()
    _, exact = run_fake(mod, monkeypatch, [50], guard=True)
    assert exact.real_calls == 50  # 정확히 min_track이면 건너뛰지 않는다
    _, other = run_fake(mod, monkeypatch, [59], guard=True, min_track=60)
    assert other.real_calls == 0   # 기준은 upstream 설정값을 읽는다(우리가 정하지 않는다)


def test_guard_does_not_skip_when_frames_cannot_be_counted(monkeypatch):
    mod = runner()

    def broken(cache):
        raise OSError('no cache')

    plain, _ = run_fake(mod, monkeypatch, [30], guard=False)
    guarded, pipeline = run_fake(mod, monkeypatch, [30], guard=True, counter=broken)
    assert pipeline.real_calls == 30 and guarded == plain


def test_guard_also_matches_when_detector_finds_no_face(monkeypatch):
    mod = runner()
    plain, _ = run_fake(mod, monkeypatch, [30, 80], guard=False, faces=False)
    guarded, pipeline = run_fake(mod, monkeypatch, [30, 80], guard=True, faces=False)
    assert guarded['segments'][1] == plain['segments'][1] and pipeline.real_calls == 80
    assert guarded['segments'][0]['reason_code'] == 'segment_too_short'


def test_count_frames_uses_the_larger_of_jpeg_and_avi_counts(tmp_path, monkeypatch):
    mod = runner()
    (tmp_path / 'frames').mkdir()
    for i in range(7):
        (tmp_path / 'frames' / f'{i:06d}.jpg').write_bytes(b'x')
    import types
    for avi_frames, expected in ((5, 7), (52, 52)):
        capture = types.SimpleNamespace(get=lambda prop, n=avi_frames: n, release=lambda: None)
        fake_cv2 = types.SimpleNamespace(VideoCapture=lambda path, c=capture: c, CAP_PROP_FRAME_COUNT=7)
        monkeypatch.setitem(sys.modules, 'cv2', fake_cv2)
        assert mod.count_frames(tmp_path) == expected


def test_pipeline_without_detector_is_left_alone():
    assert runner().install_guard(object()) is None


# ---------- 장치 선택 (기본 cpu, mps는 선택지) ----------

def test_device_defaults_to_cpu_and_only_cpu_or_mps_are_accepted(tmp_path, monkeypatch):
    mod = runner()
    assert mod.resolve_device('cpu') == 'cpu'
    for bad in ('cuda', 'cuda:0', '', 'MPS'):
        with pytest.raises(ValueError):
            mod.resolve_device(bad)
    import types
    for available, expected in ((True, 'mps'), (False, 'cpu')):
        torch = types.ModuleType('torch')
        torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda a=available: a))
        monkeypatch.setitem(sys.modules, 'torch', torch)
        monkeypatch.delenv('PYTORCH_ENABLE_MPS_FALLBACK', raising=False)
        assert mod.resolve_device('mps') == expected  # 쓸 수 없으면 cpu로 대체
        import os
        assert os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] == '1'


def test_main_passes_requested_device_and_records_device_used(runner_request, monkeypatch):
    mod = runner()
    work, req = runner_request
    req['device'] = 'mps'
    (work / 'request.json').write_text(json.dumps(req))
    loaded = []
    real_resolve = mod.resolve_device
    monkeypatch.setattr(mod, 'resolve_device', lambda d: 'cpu')  # 이 기기에서 mps를 못 쓰는 경우
    monkeypatch.setattr(mod, 'load_pipeline', lambda path, device: loaded.append(device) or object())
    monkeypatch.setattr(mod, 'infer_segments', lambda body, folder, pipeline: {'schema_version': 1, 'segments': []})
    assert mod.main(['--request', str(work / 'request.json'), '--output', str(work / 'result.json')]) == 0
    assert loaded == ['cpu']
    assert json.loads((work / 'result.json').read_text())['device_used'] == 'cpu'
    monkeypatch.setattr(mod, 'resolve_device', real_resolve)
    req['device'] = 'cuda'
    (work / 'request.json').write_text(json.dumps(req))
    assert mod.main(['--request', str(work / 'request.json'), '--output', str(work / 'result2.json')]) == 1
