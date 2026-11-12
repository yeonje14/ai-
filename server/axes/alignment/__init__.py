"""축3 · 정합 (SyncNet). 진위 분류기가 아니라 동기화 보조 지표다.

백로그 4번 단계에서는 stub이다. 지표는 null이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

STUB_REASON = "stub_not_executed"


def run(job_dir: Path) -> dict[str, Any]:
    return {
        "status": "insufficient_input",
        "reason_code": STUB_REASON,
        "lse_c": None,
        "lse_d": None,
        "included_in_fusion": False,
        "model_version": "stub",
    }
