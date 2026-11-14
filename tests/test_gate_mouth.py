"""입 움직임 규칙 단위 테스트. 합성한 입 벌림 시계열만 쓴다(미디어·모델 불필요).

말하는 실제 영상으로는 검증하지 않았다(미검증). 임계값은 임시값이다.
"""

from __future__ import annotations

import hashlib
import json
import math

import pytest

from server.gate import faces, mouth_activity, segments
from server.gate.types import (
    NO_MOUTH_MOVEMENT,
    NO_SPEECH_DETECTED,
    NO_SPEECH_FAMILY,
    SEGMENT_TOO_SHORT,
    SPEAKER_UNCONFIRMED,
    Face,
    FrameFaces,
    GateConfig,
    MediaInfo,
    MouthSample,
)

CONFIG = GateConfig()
MEDIA = MediaInfo(duration_sec=10.0, width=1920, height=1080, fps=30.0, rotation=0, has_audio=True)
BOX = (600.0, 200.0, 400.0, 400.0)
FACE = dict(x=600.0, y=200.0, w=400.0, h=400.0, score=0.9, sharpness=100.0)
OTHER = dict(x=1300.0, y=200.0, w=400.0, h=400.0, score=0.9, sharpness=100.0)
STEP = 1 / 15


def series(opening_at, start=0.0, end=10.0, box=BOX):
    n = int(round((end - start) / STEP))
    return [MouthSample(round(start + i * STEP, 3), opening_at(start + i * STEP), box) for i in range(n + 1)]


def talking(t, lo=2.0, hi=6.0, hz=4.0):
    """lo~hi초 동안 초당 hz번 입을 여닫는다. 그 밖에는 닫혀 있다."""
    if lo <= t <= hi:
        return 0.006 + 0.10 * (0.5 - 0.5 * math.cos(2 * math.pi * hz * (t - lo)))
    return 0.006


def yawn(t):
    """샘플 영상에서 본 모양: 0.3초에 한 번 벌리고 1.0초까지 천천히 닫는다."""
    if t < 0.27:
        return 0.006
    if t < 0.4:
        return 0.006 + 0.12 * (t - 0.27) / 0.13
    if t < 1.0:
        return 0.126 - 0.12 * (t - 0.4) / 0.6
    return 0.006


def one_face_frames(faces_at=lambda t: [FACE]):
    return segments.assign_tracks(
        [FrameFaces(round(i * 0.2, 3), tuple(Face(**f) for f in faces_at(i * 0.2))) for i in range(51)],
        CONFIG,
    )


# ---------- 반전 세기 ----------

def test_closed_mouth_and_jitter_have_no_reversals():
    times = [i * STEP for i in range(150)]
    assert mouth_activity.reversal_times(times, [0.006] * 150, 0.02) == []
    jitter = [0.006 + 0.004 * ((i * 7) % 5 - 2) / 2 for i in range(150)]  # 잡음 수준의 흔들림
    assert mouth_activity.reversal_times(times, jitter, 0.02) == []
    assert mouth_activity.reversal_times([], [], 0.02) == []


def test_single_open_and_close_is_one_reversal():
    s = series(yawn)
    revs = mouth_activity.reversal_times([x.t for x in s], [x.opening for x in s], CONFIG.mouth_min_swing)
    assert len(revs) == 1 and 0.3 <= revs[0] <= 0.5


def test_two_openings_are_three_reversals():
    s = series(lambda t: talking(t, 2.0, 2.5, 4.0))  # 0.5초 동안 두 번 여닫음
    revs = mouth_activity.reversal_times([x.t for x in s], [x.opening for x in s], CONFIG.mouth_min_swing)
    assert len(revs) == 3  # 봉우리, 골, 봉우리. 마지막에 닫힌 채 끝난 골은 세지 않는다


# ---------- 움직인 구간 ----------

def test_single_yawn_is_not_mouth_activity():
    assert mouth_activity.active_intervals(series(yawn), CONFIG) == []


def test_closed_mouth_is_not_mouth_activity():
    assert mouth_activity.active_intervals(series(lambda t: 0.006), CONFIG) == []


def test_repeated_opening_is_mouth_activity_with_padding():
    (a, b), = mouth_activity.active_intervals(series(talking), CONFIG)
    assert a == pytest.approx(2.0, abs=0.15) and b == pytest.approx(6.0, abs=0.3)


def test_long_pause_splits_activity():
    out = mouth_activity.active_intervals(
        series(lambda t: max(talking(t, 1.0, 3.0), talking(t, 6.0, 8.0))), CONFIG
    )
    assert len(out) == 2
    assert out[0][1] < 4.0 and out[1][0] > 5.0


def test_missing_measurement_is_not_bridged():
    # 입을 한 번 벌린 뒤 측정이 끊기고, 다시 한 번 벌린다. 끊긴 곳을 건너 반복으로 세지 않는다.
    def opening(t):
        if 2.0 <= t <= 2.2 or 3.0 <= t <= 3.2:
            return 0.12
        if 2.2 < t < 3.0:
            return None
        return 0.006
    assert mouth_activity.active_intervals(series(opening), CONFIG) == []


def test_face_change_is_not_counted_as_mouth_movement():
    # 닫힌 입의 얼굴과 벌린 입의 다른 얼굴이 번갈아 가장 큰 얼굴로 잡힌 경우
    far = (1300.0, 200.0, 400.0, 400.0)
    s = [MouthSample(round(i * STEP, 3), 0.12 if i % 2 else 0.006, far if i % 2 else BOX) for i in range(60)]
    assert mouth_activity.active_intervals(s, CONFIG) == []


def test_summary_counts_measured_samples_and_uses_none_not_zero():
    out = mouth_activity.summarize([MouthSample(0.0, None, None), MouthSample(0.1, None, None)], CONFIG)
    assert out == {"samples": 2, "measured": 0, "opening_median": None, "opening_max": None, "reversals": 0}
    assert mouth_activity.summarize(series(yawn), CONFIG)["reversals"] == 1


# ---------- 구간 규칙과 결합 ----------

def test_speech_without_mouth_movement_is_excluded():
    result = segments.build_result(MEDIA, [(0.0, 10.0)], one_face_frames(), CONFIG, mouth_active=[])
    assert result.eligible_segments == ()
    assert result.reason_code == NO_MOUTH_MOVEMENT and result.reason_code in NO_SPEECH_FAMILY
    assert [(s.start_sec, s.end_sec, s.reason_code) for s in result.excluded_segments] == [
        (0.0, 10.0, NO_MOUTH_MOVEMENT)
    ]
    assert result.mouth_active_segments == ()


def test_only_speech_with_mouth_movement_is_eligible():
    result = segments.build_result(MEDIA, [(1.0, 9.0)], one_face_frames(), CONFIG, mouth_active=[(2.0, 5.0)])
    assert [(s.start_sec, s.end_sec) for s in result.eligible_segments] == [(2.0, 5.0)]
    assert result.eligible_segments[0].quality.face_frames > 0
    assert result.reason_code is None
    assert [(s.start_sec, s.end_sec, s.reason_code) for s in result.excluded_segments] == [
        (0.0, 1.0, NO_SPEECH_DETECTED),
        (1.0, 2.0, NO_MOUTH_MOVEMENT),
        (5.0, 9.0, NO_MOUTH_MOVEMENT),
        (9.0, 10.0, NO_SPEECH_DETECTED),
    ]


def test_mouth_movement_without_speech_is_not_eligible():
    result = segments.build_result(MEDIA, [], one_face_frames(), CONFIG, mouth_active=[(2.0, 5.0)])
    assert result.eligible_segments == ()
    assert result.reason_code == NO_SPEECH_DETECTED


def test_short_mouth_activity_is_too_short():
    result = segments.build_result(MEDIA, [(0.0, 10.0)], one_face_frames(), CONFIG, mouth_active=[(3.0, 3.5)])
    assert result.eligible_segments == ()
    assert (3.0, 3.5, SEGMENT_TOO_SHORT) in [
        (s.start_sec, s.end_sec, s.reason_code) for s in result.excluded_segments
    ]


def test_two_faces_stay_speaker_unconfirmed_even_if_a_mouth_moves():
    result = segments.build_result(
        MEDIA, [(0.0, 10.0)], one_face_frames(lambda t: [FACE, OTHER]), CONFIG, mouth_active=[(0.0, 10.0)]
    )
    assert result.eligible_segments == ()
    assert result.reason_code == SPEAKER_UNCONFIRMED


def test_without_mouth_measurement_old_rule_applies_and_output_says_so():
    result = segments.build_result(MEDIA, [(0.0, 10.0)], one_face_frames(), CONFIG)
    assert len(result.eligible_segments) == 1
    out = result.to_dict()
    assert out["mouth_active_segments"] is None and out["mouth_summary"] is None
    assert out["speaking_video_validated"] is False


def test_end_to_end_rule_with_synthetic_series():
    active = mouth_activity.active_intervals(series(talking), CONFIG)
    result = segments.build_result(MEDIA, [(0.0, 10.0)], one_face_frames(), CONFIG, mouth_active=active)
    (seg,) = result.eligible_segments
    assert seg.start_sec == pytest.approx(2.0, abs=0.15) and seg.end_sec == pytest.approx(6.0, abs=0.3)

    active = mouth_activity.active_intervals(series(yawn), CONFIG)
    result = segments.build_result(MEDIA, [(0.0, 10.0)], one_face_frames(), CONFIG, mouth_active=active)
    assert result.eligible_segments == () and result.reason_code == NO_MOUTH_MOVEMENT


# ---------- 모델 파일 확인 ----------

def test_landmark_model_must_match_recorded_hash(tmp_path):
    model = tmp_path / "face_landmarker.task"
    model.write_bytes(b"model")
    cfg = tmp_path / "gate_models.json"
    cfg.write_text(json.dumps({"face_landmarker": {
        "file": model.name, "sha256": hashlib.sha256(b"model").hexdigest()}}))
    assert faces.resolve_landmark_model(tmp_path, cfg) == model

    with pytest.raises(faces.GateSetupError):
        faces.resolve_face_model(tmp_path, cfg)  # 설정에 없는 모델
    model.write_bytes(b"tampered")
    with pytest.raises(faces.GateSetupError):
        faces.resolve_landmark_model(tmp_path, cfg)
    model.unlink()
    with pytest.raises(faces.GateSetupError):
        faces.resolve_landmark_model(tmp_path, cfg)
