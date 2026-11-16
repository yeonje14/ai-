"""physics 축 실행기: 한 영상의 구간에서 후보 A·B·C의 특징 추출 요약을 낸다.

서버 어댑터(server/axes/physics/motionphys.py)가 별도 프로세스로 부른다.
입력과 출력은 JSON 파일 경로 두 개뿐이다. 기본 출력에는 특징 벡터가 없다(요약만).
학습된 분류기가 없으므로 점수를 내지 않는다. 한 후보의 실패는 다른 후보를 막지 않는다.

    research/motionphys/.venv/bin/python research/motionphys/infer_axis.py --request req.json --output out.json

요청: {"video": 경로, "segments": [[시작, 끝], ...], "variants": [...](선택), "include_features": bool(선택)}
include_features는 연구용 측정 스크립트만 켠다. 서버 어댑터는 켜지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import extract

SCHEMA_VERSION = 1
SCALES = ("8", "12", "24")


def _per_scale(summary: dict | None, key: str) -> dict | None:
    if not isinstance(summary, dict):
        return None
    return {s: summary[s][key] for s in SCALES}


def summarize(result: dict, variant: str, include_features: bool = False) -> dict:
    """extract.extract()의 결과에서 유효 궤적 수·추적 성공률만 남긴다."""
    out = {
        "status": result["status"],
        "reason_code": result.get("reason_code"),
        "valid_trajectories": None,
        "moving_trajectories": None,
        "tracking_success_rate": None,
        "face_detection_rate": None,
        "timing_sec": (result.get("timing") or {}).get("total_sec"),
    }
    if variant == "face_motion":
        regions = result.get("by_region")
        if isinstance(regions, dict):
            # 영역(머리·눈썹·입술)의 궤적 수를 스케일별로 더한다. 움직임 기준은 머리에만 적용한다.
            out["valid_trajectories"] = {
                s: sum(regions[r][s]["valid_trajectories"] for r in regions) for s in SCALES
            }
            out["moving_trajectories"] = _per_scale(regions.get("head"), "moving_trajectories")
        out["face_detection_rate"] = result.get("face_detection_rate")
    else:
        out["valid_trajectories"] = _per_scale(result.get("by_scale"), "valid_trajectories")
        out["moving_trajectories"] = _per_scale(result.get("by_scale"), "moving_trajectories")
        rate = result.get("tracking_success_rate")
        out["tracking_success_rate"] = {s: rate[s] for s in SCALES} if isinstance(rate, dict) else None
    if include_features:
        out["features"] = result.get("features")
        out["feature_names"] = extract.feature_names(variant)
        out["detail"] = {k: result.get(k) for k in ("by_scale", "by_region", "segments", "processing_scale", "clips", "clips_used")}
    return out


def _margin(model_path: str, features: list) -> float | None:
    """LightGBM 원시 margin(확률 아님). 모델과 특징 차원이 맞지 않으면 None."""
    try:
        import lightgbm as lgb
        import numpy as np
        booster = lgb.Booster(model_file=model_path)
        if booster.num_feature() != len(features):
            return None
        return float(booster.predict(np.array([features]), raw_score=True)[0])
    except Exception:
        return None


def run(req: dict) -> dict:
    video = Path(req["video"])
    segments = req["segments"]
    variants = req.get("variants") or list(extract.VARIANTS)
    include = bool(req.get("include_features", False))
    out = {"schema_version": SCHEMA_VERSION, "variants": {}}
    margin_model = req.get("margin_model")  # {"variant", "path"}: 검증된 묶음의 분류기. 서버만 넘긴다
    for variant in variants:
        try:
            result = extract.extract(video, segments, variant)
            out["variants"][variant] = summarize(result, variant, include)
            if margin_model and margin_model["variant"] == variant and result.get("features") is not None:
                out["variants"][variant]["margin"] = _margin(margin_model["path"], result["features"])
        except Exception:  # 한 후보의 실패가 다른 후보를 막지 않는다
            out["variants"][variant] = summarize(
                {"status": extract.ERROR, "reason_code": "extraction_error"}, variant)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    opt = p.parse_args(argv)
    result = run(json.loads(opt.request.read_text(encoding="utf-8")))
    tmp = opt.output.with_suffix(opt.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    os.replace(tmp, opt.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
