"""축2 · 물리 (MotionPhys). 백로그 4번 단계에서는 stub이다. 점수는 null이다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

STUB_REASON = "stub_not_executed"


def run(job_dir: Path) -> dict[str, Any]:
    return {
        "status": "insufficient_input",
        "reason_code": STUB_REASON,
        "raw_score": None,
        "model_version": "stub",
    }
