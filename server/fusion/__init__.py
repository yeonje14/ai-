"""축별 점수 결합. 검증된 결합 모델이 생기기 전에는 항상 보류한다.

3축 결합을 강제로 채택하지 않는다(README §5.4, 백로그 12번).
"""

from __future__ import annotations

from typing import Any

NO_VALID_FUSION = "no_valid_fusion_model"


def fuse(axes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall_score": None,
        "verdict_status": "abstained",
        "abstention_reason": NO_VALID_FUSION,
    }
