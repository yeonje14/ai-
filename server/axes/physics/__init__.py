"""축2 · 물리 (MotionPhys). Worker가 부르는 진입점 (백로그 10번).

- 특징 추출까지만 한다. 학습된 분류기가 없어 raw_score는 null이고 판정하지 않는다.
- 축 상태는 후보 A(전체 화면)를 따른다. B(얼굴 영역)·C(Face Motion)는 설명에만 요약한다.
- 유효 궤적 수·추적 성공률·분석 구간은 기존 explanations에 적는다. API 필드를 늘리지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any

from server.axes import AxisContext
from server.axes.physics import motionphys
from server.axes.physics.motionphys import MODEL_VERSION, MotionPhysConfig

log = logging.getLogger("trinity.axes.physics")

NOT_IN_FUSION = "학습된 분류기가 없어 점수가 없고 종합 판정에 포함하지 않습니다. 진위 판정이 아닙니다."
_LABELS = {"full": "전체 화면(A)", "face_roi": "얼굴 영역(B)", "face_motion": "Face Motion(C)"}
_REASONS = {
    "tracking_failed": "추적 실패",
    "insufficient_motion": "움직임 부족",
    "segment_too_short": "구간이 짧음",
    "inference_error": "실행 오류",
    "timeout": "제한 시간 초과",
    "model_unavailable": "실행 환경 없음",
}


def build_config(ctx: AxisContext) -> MotionPhysConfig:
    timeout = ctx.settings.motionphys_timeout_seconds
    if ctx.timeout_seconds is not None:
        timeout = min(timeout, ctx.timeout_seconds)
    return MotionPhysConfig(timeout_sec=timeout)


def _percent(rate: float | None) -> str:
    return "값 없음" if rate is None else f"{round(rate * 100)}%"


def _variant_text(name: str, v: dict) -> str:
    parts = []
    counts = v["valid_trajectories"]
    if counts is not None:
        parts.append("유효 궤적 " + "/".join(str(counts[s]) for s in motionphys.SCALES) + "개")
    rates = v["tracking_success_rate"]
    if rates is not None:
        parts.append("추적 성공률 " + "/".join(_percent(rates[s]) for s in motionphys.SCALES))
    if v["face_detection_rate"] is not None:
        parts.append("얼굴 검출률 " + _percent(v["face_detection_rate"]))
    if v["status"] != "completed":
        parts.insert(0, "계산하지 못함(" + _REASONS.get(v["reason_code"], "원인 미상") + ")")
    return f"{_LABELS[name]}: " + ", ".join(parts)


def explanation(out: dict, segments) -> dict[str, str]:
    """특징 요약을 기존 explanations 항목 하나로 만든다. 궤적 수는 8·12·24프레임 스케일 순서다."""
    duration = sum(end - start for start, end in segments)
    done = out["status"] == "completed"
    head = (
        f"MotionPhys 특징 추출을 마쳤습니다(분석 구간 {len(segments)}개, {duration:.1f}초)."
        if done else
        f"MotionPhys 특징을 계산하지 못했습니다({_REASONS.get(out['reason_code'], '원인 미상')}; "
        f"구간 {len(segments)}개, {duration:.1f}초)."
    )
    body = ""
    if out["variants"] is not None:
        body = " 궤적 수와 성공률은 8·12·24프레임 스케일 순서입니다. " + ". ".join(
            _variant_text(name, out["variants"][name]) for name in motionphys.VARIANTS) + "."
    return {
        "template_id": "MOTIONPHYS_FEATURES_ONLY" if done else "MOTIONPHYS_NOT_ANALYZED",
        "reason_code": "unvalidated_condition" if done else out["reason_code"],
        "message": f"{head}{body} {NOT_IN_FUSION}",
    }


def run(ctx: AxisContext) -> dict[str, Any]:
    result = {"status": "insufficient_input", "reason_code": "no_segments",
              "raw_score": None, "model_version": MODEL_VERSION}
    if not ctx.segments:
        return result
    if ctx.media_path is None:
        result.update(status="error", reason_code="media_unreadable")
        return result
    out = motionphys.run_motionphys(
        ctx.media_path, ctx.segments, ctx.job_dir, build_config(ctx),
        on_tick=ctx.heartbeat, tick_sec=ctx.settings.heartbeat_interval_seconds,
    )
    # 로그에는 상태와 원인 코드만 남긴다. 영상 내용과 경로는 남기지 않는다.
    log.info("motionphys %s reason=%s", out["status"], out["reason_code"])
    if out["reason_code"] != "aborted":
        ctx.explanations.append(explanation(out, ctx.segments))
    result.update(status=out["status"], reason_code=out["reason_code"])
    return result
