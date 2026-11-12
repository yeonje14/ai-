"""Gate 규칙 단위 테스트. 합성한 음성 구간·얼굴 표본만 쓴다(미디어·모델 불필요).

여러 얼굴 경우는 규칙 로직만 확인한다. 실제 다인 영상으로는 검증하지 않았다(미검증).
"""

from __future__ import annotations

import subprocess
import sys

from server.gate import probe, segments, vad
from server.gate.types import (
    AUDIO_MISSING,
    FACE_TOO_SMALL,
    LOW_RESOLUTION,
    NO_FACE_DETECTED,
    NO_SPEECH_DETECTED,
    SEGMENT_TOO_SHORT,
    SPEAKER_UNCONFIRMED,
    TOO_BLURRY,
    Face,
    FrameFaces,
    GateConfig,
    MediaInfo,
)

from tests.conftest import REPO_ROOT

CONFIG = GateConfig()
MEDIA = MediaInfo(duration_sec=10.0, width=1920, height=1080, fps=30.0, rotation=0, has_audio=True)
BIG = dict(x=600.0, y=200.0, w=400.0, h=400.0, score=0.9, sharpness=100.0)
OTHER = dict(x=1300.0, y=200.0, w=400.0, h=400.0, score=0.9, sharpness=100.0)


def frames(faces_at, start=0.0, end=10.0, step=0.2):
    """faces_at(t) -> 그 시각의 얼굴 dict 목록."""
    out, i = [], 0
    while start + i * step <= end + 1e-9:
        t = round(start + i * step, 3)
        out.append(FrameFaces(t, tuple(Face(**f) for f in faces_at(t))))
        i += 1
    return segments.assign_tracks(out, CONFIG)


def build(speech, faces_at, media=MEDIA, config=CONFIG):
    return segments.build_result(media, speech, frames(faces_at), config)


def reasons(result):
    return [s.reason_code for s in result.excluded_segments]


def test_single_speaker_is_eligible():
    result = build([(1.0, 6.0)], lambda t: [BIG])
    assert result.reason_code is None
    assert [(s.start_sec, s.end_sec) for s in result.eligible_segments] == [(1.0, 6.0)]
    assert result.eligible_duration_sec == 5.0
    quality = result.eligible_segments[0].quality
    assert quality.face_height_px == 400.0 and quality.short_side_px == 1080
    # 말하지 않는 앞뒤는 제외 구간으로 남는다
    assert [(s.start_sec, s.end_sec, s.reason_code) for s in result.excluded_segments] == [
        (0.0, 1.0, NO_SPEECH_DETECTED),
        (6.0, 10.0, NO_SPEECH_DETECTED),
    ]


def test_no_audio_stream_is_audio_missing():
    result = segments.build_result(MEDIA, None, [], CONFIG)
    assert result.reason_code == AUDIO_MISSING
    assert reasons(result) == [AUDIO_MISSING]
    assert result.eligible_segments == ()


def test_audio_without_speech_is_no_speech_detected():
    result = build([], lambda t: [BIG])
    assert result.reason_code == NO_SPEECH_DETECTED
    assert reasons(result) == [NO_SPEECH_DETECTED]


def test_speech_without_face_is_no_face_detected():
    result = build([(0.0, 10.0)], lambda t: [])
    assert result.reason_code == NO_FACE_DETECTED
    assert reasons(result) == [NO_FACE_DETECTED]


def test_three_cases_have_distinct_reason_codes():
    codes = {
        build([(0.0, 10.0)], lambda t: [BIG]).reason_code,
        segments.build_result(MEDIA, None, [], CONFIG).reason_code,
        build([(0.0, 10.0)], lambda t: []).reason_code,
    }
    assert codes == {None, AUDIO_MISSING, NO_FACE_DETECTED}


def test_two_main_faces_is_speaker_unconfirmed():
    result = build([(0.0, 10.0)], lambda t: [BIG, OTHER])
    assert result.reason_code == SPEAKER_UNCONFIRMED
    assert result.eligible_segments == ()


def test_second_face_only_part_of_the_time_splits_segment():
    result = build([(0.0, 10.0)], lambda t: [BIG, OTHER] if 4.0 <= t <= 6.0 else [BIG])
    assert result.reason_code is None
    assert [(s.start_sec, s.end_sec) for s in result.eligible_segments] == [(0.0, 3.9), (6.1, 10.0)]
    assert [(s.start_sec, s.end_sec, s.reason_code) for s in result.excluded_segments] == [
        (3.9, 6.1, SPEAKER_UNCONFIRMED)
    ]


def test_small_background_face_is_not_a_main_face():
    tiny = dict(x=50.0, y=50.0, w=60.0, h=60.0, score=0.8, sharpness=100.0)  # 짧은 변의 10% 미만
    result = build([(0.0, 10.0)], lambda t: [BIG, tiny])
    assert result.reason_code is None
    assert len(result.eligible_segments) == 1


def test_short_detection_dropout_is_bridged_but_long_one_is_not():
    # 표본 하나(0.2초 간격)만 빠지면 앞뒤 표본 간격이 0.4초라 max_face_gap_sec(0.5초) 안이다
    short_gap = build([(0.0, 10.0)], lambda t: [] if abs(t - 5.0) < 1e-6 else [BIG])
    assert [(s.start_sec, s.end_sec) for s in short_gap.eligible_segments] == [(0.0, 10.0)]

    long_gap = build([(0.0, 10.0)], lambda t: [] if 4.0 <= t <= 6.0 else [BIG])
    assert len(long_gap.eligible_segments) == 2
    assert reasons(long_gap) == [NO_FACE_DETECTED]


def test_different_face_after_cut_splits_segment():
    result = build([(0.0, 10.0)], lambda t: [BIG] if t < 5.0 else [OTHER])
    assert len(result.eligible_segments) == 2


def test_quality_reasons():
    small = dict(BIG, w=110.0, h=110.0)  # 주된 얼굴이지만 min_face_height_px 미만이 되도록 설정
    config = GateConfig(min_face_height_px=120.0)
    assert build([(0.0, 10.0)], lambda t: [small], config=config).reason_code == FACE_TOO_SMALL

    blurry = dict(BIG, sharpness=1.0)
    assert build([(0.0, 10.0)], lambda t: [blurry]).reason_code == TOO_BLURRY

    low = MediaInfo(duration_sec=10.0, width=320, height=240, fps=30.0, rotation=0, has_audio=True)
    face = dict(x=100.0, y=50.0, w=100.0, h=100.0, score=0.9, sharpness=100.0)
    assert build([(0.0, 10.0)], lambda t: [face], media=low).reason_code == LOW_RESOLUTION

    assert build([(2.0, 2.5)], lambda t: [BIG]).reason_code == SEGMENT_TOO_SHORT


def test_excluded_segment_keeps_quality_numbers():
    result = build([(0.0, 10.0)], lambda t: [dict(BIG, sharpness=1.0)])
    assert result.excluded_segments[0].quality.sharpness == 1.0


def test_coverage_matches_readme_shape_and_leaves_analyzed_null():
    result = build([(1.0, 6.0)], lambda t: [BIG])
    assert result.coverage() == {
        "video_duration_sec": 10.0,
        "eligible_duration_sec": 5.0,
        "analyzed_duration_sec": None,   # Gate는 추론하지 않는다. 0이 아니라 null
        "full_video_coverage": None,
        "eligible_coverage": None,
        "analyzed_segments": None,
    }
    assert result.to_dict()["multi_speaker_validated"] is False


def test_vad_flags_to_intervals_merges_short_pauses_and_drops_blips():
    # 30ms 프레임: 1초 음성, 0.3초 쉼(이어짐), 1초 음성, 1.5초 쉼, 0.09초 잡음(버려짐)
    flags = [True] * 33 + [False] * 10 + [True] * 33 + [False] * 50 + [True] * 3 + [False] * 5
    assert vad.flags_to_intervals(flags, CONFIG) == [(0.0, 2.28)]
    assert vad.flags_to_intervals([False] * 100, CONFIG) == []


def test_parse_probe():
    video = {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30000/1001"}
    info = probe.parse_probe({"format": {"duration": "10.5"}, "streams": [video]})
    assert (info.width, info.height, info.fps, info.has_audio) == (1920, 1080, 29.97, False)

    rotated = dict(video, side_data_list=[{"rotation": -90}])
    info = probe.parse_probe(
        {"format": {"duration": "10.5"}, "streams": [rotated, {"codec_type": "audio"}]}
    )
    assert (info.width, info.height, info.rotation, info.has_audio) == (1080, 1920, 270, True)

    assert probe.parse_probe({"format": {"duration": "3"}, "streams": [{"codec_type": "audio"}]}) is None


def test_api_server_does_not_import_gate_dependencies():
    code = (
        "import sys, server.main; "
        "bad = [m for m in ('cv2', 'mediapipe', 'webrtcvad', 'numpy', 'torch') if m in sys.modules]; "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, check=True, timeout=30)
