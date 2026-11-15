"""SyncNet 스모크는 빈 결과/CLI 오류를 성공으로 보고하거나 숫자를 노출하면 안 된다."""
import json

import pytest

from research.syncnet import run_spike


@pytest.mark.parametrize('body,valid', [
    ([{'status': 'success', 'has_face': True, 'offset': 1, 'confidence': 2.0, 'min_distance': 3.0}], True),
    ([{'status': 'error', 'error': 'private input'}], False),
    ([{'status': 'success', 'has_face': False, 'offset': None, 'confidence': 0, 'min_distance': 0}], False),
    ([{'status': 'success', 'has_face': True, 'offset': 1, 'confidence': float('nan'), 'min_distance': 3}], False),
    ([], False),
    ({}, False),
])
def test_cli_result_requires_real_track_and_finite_outputs(body, valid):
    assert run_spike.result_succeeded(body) is valid


def test_unregistered_media_never_starts_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_spike, 'execute', lambda *args: pytest.fail('unregistered media executed'))
    code = run_spike.main(['--registry', str(tmp_path / 'absent.json'), '--media-root', str(tmp_path),
                          '--video-id', 'TRINITYtest'])
    assert code == 1
    assert capsys.readouterr().out.strip() == '실행 실패'


@pytest.mark.parametrize('successful', [True, False])
def test_smoke_prints_only_outcome_and_cleans_every_temporary_file(tmp_path, monkeypatch, capsys, successful):
    media = tmp_path / 'media'
    media.mkdir()
    (media / 'clip.mp4').write_bytes(b'authorized fixture')
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'authorized_media': [
        {'youtube_video_id': 'TRINITYtest', 'local_path': 'clip.mp4'},
    ]}))
    monkeypatch.setattr(run_spike, 'verify_weights', lambda: None)
    runtime = tmp_path / 'runtime'
    monkeypatch.setattr(run_spike, 'RUNTIME', runtime)
    def execute(work):
        assert (work / 'media.mp4').read_bytes() == b'authorized fixture'
        (work / 'crop.jpg').write_bytes(b'private face')
        (work / 'result.json').write_text('private numeric output')
        if not successful:
            raise RuntimeError('private media and score 123.456')
        return True
    monkeypatch.setattr(run_spike, 'execute', execute)
    code = run_spike.main(['--registry', str(registry), '--media-root', str(media), '--video-id', 'TRINITYtest'])
    assert code == (0 if successful else 1)
    captured = capsys.readouterr()
    assert captured.out.strip() == ('실행 성공' if successful else '실행 실패')
    assert captured.err == ''
    assert list(runtime.iterdir()) == []
    assert (media / 'clip.mp4').read_bytes() == b'authorized fixture'


def test_weight_hash_mismatch_is_rejected_before_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(run_spike, 'WEIGHTS', tmp_path)
    monkeypatch.setattr(run_spike, 'MANIFEST', {'weights': {'wrong.model': {'sha256': '0' * 64}}})
    (tmp_path / 'wrong.model').write_bytes(b'changed')
    with pytest.raises(ValueError):
        run_spike.verify_weights()
