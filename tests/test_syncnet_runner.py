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
