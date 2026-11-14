"""축2 · 물리 (MotionPhys). 백로그 4번 단계에서는 stub이다. 점수는 null이다."""

from __future__ import annotations

from typing import Any

from server.axes import AxisContext

STUB_REASON = "stub_not_executed"


def run(ctx: AxisContext) -> dict[str, Any]:
    return {
        "status": "insufficient_input",
        "reason_code": STUB_REASON,
        "raw_score": None,
        "model_version": "stub",
    }
