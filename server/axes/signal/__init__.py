"""축1 · 신호 (WaveRep). Worker가 부르는 진입점 (백로그 7번).

- 구간이 없으면 모델을 실행하지 않는다. 점수는 null이다.
- 결과에는 프레임 logit 요약만 둔다. raw_score는 null이고 판정하지 않는다
  (집계 방법과 임계값은 백로그 8번 이후에 정한다).
- 프레임별 점수, 실행 시간, stderr 같은 내부 값은 결과에 넣지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any

from server.axes import AxisContext
from server.axes.signal import waverep
from server.axes.signal.waverep import WaveRepConfig, run_waverep

log = logging.getLogger("trinity.axes.signal")

def build_config(ctx: AxisContext) -> WaveRepConfig:
    s = ctx.settings
    timeout = s.waverep_timeout_seconds
    if ctx.timeout_seconds is not None:
        timeout = min(timeout, ctx.timeout_seconds)
    return WaveRepConfig(
        device=s.waverep_device,
        sample_fps=s.waverep_sample_fps,
        batch_size=s.waverep_batch_size,
        pretrained=False,
        timeout_sec=max(timeout, 0.0),
    )


def run(ctx: AxisContext) -> dict[str, Any]:
    if not ctx.segments:
        return {
            "status": waverep.INSUFFICIENT_INPUT,
            "reason_code": "no_segments",
            "raw_score": None,
            "raw_metrics": None,
            "model_version": waverep.MODEL_VERSION,
        }
    if ctx.media_path is None:
        return {
            "status": waverep.ERROR,
            "reason_code": "media_unreadable",
            "raw_score": None,
            "raw_metrics": None,
            "model_version": waverep.MODEL_VERSION,
        }

    out = run_waverep(
        ctx.media_path,
        ctx.segments,
        ctx.job_dir,
        build_config(ctx),
        on_tick=ctx.heartbeat,
        tick_sec=ctx.settings.heartbeat_interval_seconds,
    )
    if isinstance(out.get("video"), dict):
        ctx.media_info.update(out["video"])

    # 로그에는 상태·원인 코드·수치만 남긴다. 영상 내용과 경로는 남기지 않는다.
    if out["status"] == waverep.COMPLETED:
        log.info(
            "waverep completed frames=%s device=%s total_sec=%s",
            out["raw_metrics"]["frame_logit"]["frames"],
            (out.get("model") or {}).get("device_used"),
            (out.get("timing") or {}).get("total_sec"),
        )
    else:
        log.warning(
            "waverep %s reason=%s returncode=%s",
            out["status"], out["reason_code"], out.get("returncode"),
        )

    return {
        "status": out["status"],
        "reason_code": out["reason_code"],
        "raw_score": None,
        "raw_metrics": out["raw_metrics"],
        "model_version": out["model_version"],
    }
