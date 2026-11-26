import shutil
import subprocess

import pytest

from server.config import Settings


def test_window_maximizes_summed_speech_and_breaks_ties_by_earliest_start():
    from server.ingest.speech_window import select_window, Window

    assert select_window(33.75, []) == Window(33.75, 0, 33.75)
    assert select_window(120, []) == Window(120, 0, 60)
    assert select_window(150, [(0, 21), (75.25, 100), (122, 135.25)]) == Window(150, 75.25, 135.25)
    assert select_window(150, [(90, 120)]) == Window(150, 60, 120)


def test_result_uses_original_timeline_and_only_counts_analyzed_signal():
    from server.ingest.speech_window import apply_window, Window

    result = {'coverage': {'analyzed_duration_sec': 10, 'analyzed_segments': [{'start_sec': 2, 'end_sec': 12}],
                           'eligible_duration_sec': 20, 'eligible_coverage': 0.5, 'full_video_coverage': 0.1667},
              'explanations': [{'template_id': 'GATE_ELIGIBLE_SEGMENT', 'message': 'Gate 적합 구간: 2~12초.'},
                               {'template_id': 'GATE_EXCLUDED_SEGMENT', 'message': 'Gate 제외 구간: 55~60초.'}]}
    apply_window(result, Window(200, 60, 120))
    assert result['coverage'] == {'video_duration_sec': 200, 'analyzed_duration_sec': 10, 'eligible_duration_sec': 20,
                                  'eligible_coverage': 0.5, 'full_video_coverage': 0.05,
                                  'analyzed_segments': [{'start_sec': 62, 'end_sec': 72}]}
    messages = [entry['message'] for entry in result['explanations']]
    assert 'Gate 적합 구간: 62~72초.' in messages
    assert 'Gate 제외 구간: 115~120초.' in messages
    assert any('전체 3분 20초 중 60~120초를 분석했습니다' in message for message in messages)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg 필요')
def test_prepare_real_silent_video_clips_to_sixty_seconds(tmp_path):
    pytest.importorskip('webrtcvad')
    from server.gate.probe import probe
    from server.ingest.speech_window import prepare_window, Window

    path = tmp_path / 'registered.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=32x32:rate=1', '-f', 'lavfi',
                    '-i', 'anullsrc=r=16000:cl=mono', '-t', '62', '-c:v', 'ffv1', '-c:a', 'pcm_s16le', str(path)], check=True)
    clip, window = prepare_window(path, tmp_path, Settings(), lambda: True)
    assert window == Window(62, 0, 60)
    assert clip != path and clip.parent == tmp_path
    assert probe(clip).duration_sec == pytest.approx(60, abs=0.02)


def test_cancel_preparation_before_probe(tmp_path):
    from server.ingest.speech_window import prepare_window, WindowError

    path = tmp_path / 'media.mkv'
    path.touch()
    with pytest.raises(WindowError, match='aborted'):
        prepare_window(path, tmp_path, Settings(), lambda: False)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg 필요')
def test_audio_only_window_uses_same_voice_frames_as_gate_across_chunk_boundaries(tmp_path):
    pytest.importorskip('webrtcvad')
    from server.gate import vad
    from server.gate.types import GateConfig
    from server.ingest.speech_window import select_audio_window

    path = tmp_path / 'audio.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'anoisesrc=a=0.25:color=pink:sample_rate=16000:duration=12:seed=81', '-af', 'adelay=80000', str(path)], check=True)
    speech = vad.detect_speech(path, GateConfig())
    assert speech and all(start >= 79 for start, end in speech)
    # 이 파일의 발화가 모두 60초 창에 들어가려면 마지막 발화 끝에서 60초를 뺀 곳부터 시작한다.
    window = select_audio_window(path, 92, tmp_path, Settings(), lambda: True)
    assert window.end_sec == pytest.approx(speech[-1][1])
    assert window.start_sec == pytest.approx(speech[-1][1] - 60)


@pytest.mark.parametrize('reason', ['aborted', 'gate_timeout'])
def test_preparation_stops_running_process_on_cancel_or_timeout(tmp_path, monkeypatch, reason):
    import sys
    from dataclasses import replace
    from server.ingest import speech_window
    from server.jobs.child_process import start_process

    child = []

    def start_slow(command, **kwargs):
        proc, fd = start_process([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        child.append(proc)
        return proc, fd

    monkeypatch.setattr(speech_window, 'start_process', start_slow)
    path = tmp_path / 'media.mkv'
    path.touch()
    settings = replace(Settings(), gate_timeout_seconds=0.15, heartbeat_interval_seconds=0.04)
    with pytest.raises(speech_window.WindowError, match=reason):
        speech_window.prepare_window(path, tmp_path, settings, lambda: reason == 'gate_timeout' or not child)
    assert child and child[0].poll() is not None
