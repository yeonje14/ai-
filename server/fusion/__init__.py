"""축별 점수 결합. 검증된 모델 묶음이 있을 때만 판정하고, 그 밖에는 항상 보류한다.

3축 결합을 강제로 채택하지 않는다(docs/DESIGN.md §5.4, 백로그 12번). 규칙은 docs/DESIGN.md §15.3 결정 5·8 보완(2026-11-16):
묶음의 digest가 저장소에 커밋된 값과 같고, 검증 리포트가 채택 조건을 통과했고(판단을 리포트 지표로 다시 계산해
확인하고, 학습 설정이 커밋된 configs/training.json과 같아야 한다), 특징 버전이 서버와 같고,
이번 요청에 쓸 후보가 있을 때만 overall_score와 verdict_label을 낸다. 후보는 training/serving.py의 규칙으로 고른다:
선택 후보는 그 축이 모두 성공하고 입력이 모두 있으면 쓰고, 아니면 성공한 축 집합과 정확히 같은 대체 후보를 쓴다
(docs/DESIGN.md §15.3 2026-11-18).
하나라도 어긋나면 null / abstained / no_valid_fusion_model이다. 결측을 0이나 평균으로 채우지 않는다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from server.config import Settings

log = logging.getLogger("trinity.fusion")

NO_VALID_FUSION = "no_valid_fusion_model"
ABSTAINED = {"overall_score": None, "verdict_status": "abstained", "abstention_reason": NO_VALID_FUSION}


def load_active(settings: Settings) -> Optional[Any]:
    """쓸 수 있는 묶음 또는 None. 실패 이유는 코드만 로그에 남긴다. 예외를 던지지 않는다."""
    try:
        pinned = json.loads(settings.fusion_bundle_config_path.read_text(encoding="utf-8"))
        bundle_id, digest = pinned.get("bundle_id"), pinned.get("digest")
    except (OSError, ValueError, AttributeError):
        return None
    if not bundle_id or not digest:
        return None  # 묶음을 고정하지 않았다(기본 상태)
    try:
        from training import bundle as bundles, config as training_config
        from training.features.extract import default_settings, feature_version

        if not isinstance(bundle_id, str) or "/" in bundle_id or bundle_id.startswith("."):
            raise bundles.BundleError("bundle_id_invalid")
        # 묶음의 학습 설정·채택 기준이 커밋된 설정과 같아야 한다(감사 A2)
        committed = training_config.load(settings.training_config_path)
        loaded = bundles.load(settings.fusion_bundle_dir / bundle_id, digest, settings.allow_synthetic_bundle,
                              expected_config=committed)
        if loaded.feature_version != feature_version(default_settings(settings)):
            # 학습 때의 추출 설정·모델 버전과 서버가 다르다. 그 점수에 그 임계값을 적용할 수 없다
            raise bundles.BundleError("feature_version_mismatch")
        return loaded
    except Exception as e:
        log.warning("fusion bundle rejected: %s", getattr(e, "code", type(e).__name__))
        return None


def fuse(axes: dict[str, dict[str, Any]], bundle: Optional[Any] = None,
         inputs: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """bundle이 없으면 지금까지와 같이 보류한다. 있으면 성공한 축 집합에 맞는 후보로만 판정한다."""
    if bundle is None:
        return dict(ABSTAINED)
    from training import serving

    # 축 성공은 학습과 같은 함수로 정하고, 후보는 학습·리포트와 같은 규칙으로 고른다(docs/DESIGN.md §15.3 2026-11-18, 감사 A9)
    available = serving.successful_axes({name: a.get("status") for name, a in axes.items()})
    candidate = bundle.choose(available, inputs or {})
    score = candidate.score(inputs or {}) if candidate is not None else None
    if score is None:
        return dict(ABSTAINED)
    values = inputs or {}
    updates: dict[str, dict[str, Any]] = {}
    if "signal" in candidate.axes:
        updates["signal"] = {"raw_score": values["W"]}
    if "physics" in candidate.axes:
        updates["physics"] = {"raw_score": values[f"M-{candidate.motion_variant}"]}
    if "alignment" in candidate.axes:
        updates["alignment"] = {"lse_c": values["S.lse_c_median"], "lse_d": values["S.lse_d_median"],
                                "included_in_fusion": True}
    return {
        "overall_score": candidate.calibrated(score),  # 보정된 값. 진짜/가짜 확률이라고 표시하지 않는다
        "verdict_status": "assessed",
        "abstention_reason": None,
        # 서버가 고정 임계값으로 정한다(결정 8). 임계값은 보정 전 결합 점수에 적용한다
        "verdict_label": "suspicious_signals" if score >= candidate.threshold else "low_suspicion",
        "candidate": candidate.name,
        "axis_updates": updates,
    }
