"""승인된 상태 대응과 Gate 결과 설명. API 필드를 추가하지 않는다."""
from __future__ import annotations

from server.gate.types import GateResult, Segment

REJECTION_STATES = {
    "audio_missing": ("out_of_scope", "not_applicable"),
    "no_speech_detected": ("out_of_scope", "not_applicable"),
    "no_mouth_movement": ("out_of_scope", "not_applicable"),
    "no_face_detected": ("out_of_scope", "not_applicable"),
    "speaker_unconfirmed": ("unsupported", "abstained"),
    "low_resolution": ("insufficient_quality", "abstained"),
    "face_too_small": ("insufficient_quality", "abstained"),
    "too_blurry": ("insufficient_quality", "abstained"),
    "segment_too_short": ("insufficient_quality", "abstained"),
    "media_unreadable": ("analysis_unavailable", "abstained"),
    "gate_error": ("analysis_unavailable", "abstained"),
    "gate_timeout": ("analysis_unavailable", "abstained"),
}

REASON_MESSAGES = {
    "audio_missing": "영상에 오디오가 없어 발화 구간을 확인하지 못했습니다.",
    "no_speech_detected": "음성으로 감지된 구간이 없습니다.",
    "no_mouth_movement": "음성 구간에서 반복되는 입 움직임을 확인하지 못했습니다.",
    "no_face_detected": "음성 구간에서 분석할 주된 얼굴을 찾지 못했습니다.",
    "speaker_unconfirmed": "말하는 사람을 한 명으로 확인하지 못했습니다.",
    "low_resolution": "영상 해상도가 발화 구간 분석 기준보다 낮습니다.",
    "face_too_small": "얼굴이 작아 분석할 구간을 확보하지 못했습니다.",
    "too_blurry": "얼굴 영역이 흐려 분석할 구간을 확보하지 못했습니다.",
    "segment_too_short": "분석할 발화 구간이 너무 짧습니다.",
    "media_unreadable": "허가된 영상 파일을 읽지 못해 분석하지 못했습니다.",
    "gate_error": "발화 구간을 확인하는 중 오류가 발생해 분석하지 못했습니다.",
    "gate_timeout": "정해진 시간 안에 발화 구간 확인을 마치지 못했습니다.",
}


def _segment_text(segment: Segment) -> str:
    text = f"{segment.start_sec:g}~{segment.end_sec:g}초"
    q = segment.quality
    if q is not None:
        text += (f"; 얼굴 높이 중앙값 {q.face_height_px:g}px, 짧은 변 대비 {q.face_height_ratio:g},"
                 f" 선명도 중앙값 {q.sharpness:g}, 영상 짧은 변 {q.short_side_px}px,"
                 f" 품질 표본 {q.face_frames}프레임")
    return text


def explanations(gate: GateResult) -> list[dict]:
    entries = []
    if gate.reason_code:
        entries.append({"template_id": "GATE_NOT_ANALYZED", "reason_code": gate.reason_code,
                        "message": REASON_MESSAGES[gate.reason_code]})
    if gate.media:
        m = gate.media
        entries.append({"template_id": "GATE_MEDIA", "reason_code": "unvalidated_condition",
                        "message": f"Gate 입력: {m.width}×{m.height}px, {m.fps:g}fps, {m.duration_sec:g}초."})
    for segment in gate.eligible_segments:
        entries.append({"template_id": "GATE_ELIGIBLE_SEGMENT", "reason_code": "unvalidated_condition",
                        "message": "Gate 적합 구간: " + _segment_text(segment) + "."})
    for segment in gate.excluded_segments:
        entries.append({"template_id": "GATE_EXCLUDED_SEGMENT", "reason_code": segment.reason_code,
                        "message": "Gate 제외 구간: " + _segment_text(segment) + ". "
                        + REASON_MESSAGES[segment.reason_code]})
    entries.append({"template_id": "GATE_UNVALIDATED", "reason_code": "unvalidated_condition",
                    "message": "발화 구간 Gate의 임계값은 임시값입니다. 말하는 영상과 다중 발화는 미검증이며, "
                    "구간 품질 수치와 coverage는 진위 판정의 정확도나 신뢰도가 아닙니다."})
    return entries
