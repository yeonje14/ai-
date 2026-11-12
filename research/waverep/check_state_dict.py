"""WaveRep 체크포인트 키 대조: missing/unexpected keys 확인.

원본 demo/utils.py의 create_model과 같은 방식(같은 아키텍처, 같은 키 걸러내기)으로
state_dict를 만들고, strict=False로 불러 누락·잉여 키를 JSON으로 출력한다.
원본 데모는 strict=True로 불러서 하나라도 어긋나면 예외로 끝난다. 이 스크립트는
그 결과를 명시적으로 기록하기 위한 것이다. 추론은 하지 않는다(CPU, 네트워크 없음).

사용: research/waverep/.venv/bin/python research/waverep/check_state_dict.py [--weights 경로]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_WEIGHTS = Path(__file__).resolve().parent / "upstream" / "demo" / "weights" / "weights_dinov2_G4.ckpt"
# demo/main_avideo.py와 같은 값
ARC = "vit_base_patch14_reg4_dinov2.lvd142m"
CROPPING = 504


def filter_like_demo(dat: dict) -> tuple[dict, list[str]]:
    """demo/utils.py create_model과 같은 규칙. (쓸 키, 버린 키 이름)을 돌려준다."""
    if "state_dict" not in dat:
        return dat, []
    sd = dat["state_dict"]
    kept = {k[6:]: v for k, v in sd.items() if k.startswith("model")}
    dropped = [k for k in sd if not k.startswith("model")]
    return kept, dropped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    opt = p.parse_args(argv)

    import timm
    import torch

    # pretrained=False: 키 이름·모양만 대조하므로 Hub 가중치가 필요 없다.
    model = timm.create_model(ARC, num_classes=1, pretrained=False, img_size=CROPPING)
    dat = torch.load(opt.weights, map_location="cpu")
    top_level = sorted(dat.keys()) if "state_dict" in dat else ["(state_dict 그대로)"]
    kept, dropped = filter_like_demo(dat)

    model_sd = model.state_dict()
    shape_mismatch = [
        f"{k}: ckpt {tuple(v.shape)} != model {tuple(model_sd[k].shape)}"
        for k, v in kept.items()
        if k in model_sd and tuple(v.shape) != tuple(model_sd[k].shape)
    ]
    loadable = {k: v for k, v in kept.items() if not any(m.startswith(k + ":") for m in shape_mismatch)}
    result = model.load_state_dict(loadable, strict=False)

    print(json.dumps({
        "torch": torch.__version__,
        "timm": timm.__version__,
        "arc": ARC,
        "img_size": CROPPING,
        "checkpoint_top_level_keys": top_level,
        "model_keys": len(model_sd),
        "checkpoint_keys_used": len(kept),
        "checkpoint_keys_dropped_by_demo_filter": dropped,
        "missing_keys": list(result.missing_keys),
        "unexpected_keys": list(result.unexpected_keys),
        "shape_mismatch": shape_mismatch,
    }, ensure_ascii=False, indent=2))
    return 0 if not (result.missing_keys or result.unexpected_keys or shape_mismatch) else 1


if __name__ == "__main__":
    raise SystemExit(main())
