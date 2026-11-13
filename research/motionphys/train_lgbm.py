"""MotionPhys 계열 특징으로 LightGBM 분류기를 학습하고 dev·test 점수 파일을 쓴다.

**실제 학습은 DeepSpeak v2 승인 뒤로 미뤘다.** 지금은 합성 데이터로 동작만 확인했다
(tests/test_motionphys_train.py). 이 스크립트가 내는 점수를 진위로 해석하지 않는다.

research/motionphys/.venv의 Python으로 실행한다.

    research/motionphys/.venv/bin/python research/motionphys/train_lgbm.py \
        --manifest <공통 manifest.csv> --features <features.csv> --variant full --out-dir <폴더>

규칙 (README §6.4, §13, docs/evaluation-pipeline.md):
- 누수 검사를 통과하지 못한 manifest로는 학습하지 않는다.
- 학습에는 train 분할만 쓴다. 외부 최종 평가 자료(external)는 학습에도 점수 계산에도 쓰지 않는다.
- 점수는 dev·test에 대해서만 낸다. train의 in-sample 점수는 내지 않는다.
- 점수는 LightGBM의 원시 margin이다. 확률로 바꾸지 않는다. 임계값은 여기서 정하지 않는다
  (training.evaluation.run fit-threshold가 dev에서 정한다).
- 특징이 없는 영상(움직임 부족 등)은 학습에서 빼고, 점수 파일에는 score를 빈칸으로 적는다.

features.csv: dataset_id, video_id, status, reason_code, f0, f1, ... (특징이 없으면 f열은 빈칸)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from training import hygiene  # noqa: E402
from training.datasets.manifest import ManifestError, read_manifest, sha256_file  # noqa: E402
from training.evaluation.lock import DEFAULT_LOCK_PATH, load_lock  # noqa: E402

SCORE_SPLITS = ("dev", "test")
SEED = 20261114
# 우리 선택: LightGBM 기본값에 재현성을 위한 설정만 더했다. 논문은 하이퍼파라미터를 밝히지 않았다.
# 실제 학습 때는 dev 분할에서 정한다.
PARAMS = {
    "objective": "binary",
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
    "verbosity": -1,
}
NUM_BOOST_ROUND = 100


class TrainError(RuntimeError):
    pass


def read_features(path: Path) -> tuple[dict[str, dict], int]:
    """{uid: {"x": [float, ...] 또는 None, "status", "reason_code"}}와 특징 차원."""
    out: dict[str, dict] = {}
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = [c for c in (reader.fieldnames or []) if c.startswith("f") and c[1:].isdigit()]
        cols.sort(key=lambda c: int(c[1:]))
        if not cols or [int(c[1:]) for c in cols] != list(range(len(cols))):
            raise TrainError("특징 열은 f0, f1, ... 이어야 한다")
        for n, row in enumerate(reader, start=2):
            uid = f"{row['dataset_id']}:{row['video_id']}"
            if uid in out:
                raise TrainError(f"특징 파일 {n}행: {uid} 중복")
            cells = [row[c].strip() for c in cols]
            if all(c == "" for c in cells):
                x = None
            elif any(c == "" for c in cells):
                raise TrainError(f"특징 파일 {n}행: 특징이 일부만 비어 있다")
            else:
                x = [float(c) for c in cells]
            out[uid] = {"x": x, "status": row.get("status", ""), "reason_code": row.get("reason_code", "")}
    return out, len(cols)


def train_and_score(manifest: Path, features: Path, variant: str, out_dir: Path, lock_path: Path) -> dict:
    import lightgbm as lgb
    import numpy as np

    records = read_manifest(manifest)
    report = hygiene.check(records, load_lock(lock_path))
    if not report.ok:
        raise TrainError("누수 검사 실패. 학습하지 않는다: " + ", ".join(e["code"] for e in report.errors))
    feats, dim = read_features(features)
    unknown = sorted(set(feats) - {r.uid for r in records})
    if unknown:
        raise TrainError(f"manifest에 없는 영상의 특징 {len(unknown)}건")

    train = [r for r in records if r.split == "train" and (feats.get(r.uid) or {}).get("x") is not None]
    if {r.label for r in train} != {"real", "fake"}:
        raise TrainError("train 분할에 특징이 있는 진짜와 가짜가 모두 있어야 한다")
    x = np.array([feats[r.uid]["x"] for r in train], dtype=np.float64)
    y = np.array([1 if r.label == "fake" else 0 for r in train])
    booster = lgb.train(PARAMS, lgb.Dataset(x, label=y), num_boost_round=NUM_BOOST_ROUND)

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.txt"
    booster.save_model(str(model_path))

    scored = skipped = 0
    scores_path = out_dir / "scores.csv"
    with scores_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["dataset_id", "video_id", "score", "status", "reason_code"])
        for r in sorted(records, key=lambda r: r.uid):
            if r.split not in SCORE_SPLITS:
                continue
            entry = feats.get(r.uid)
            if entry is None or entry["x"] is None:
                # 특징이 없으면 점수도 없다. 0을 쓰지 않는다
                status = entry["status"] if entry else "error"
                reason = (entry["reason_code"] if entry else "") or "missing_features"
                w.writerow([r.dataset_id, r.video_id, "", status or "insufficient_input", reason])
                skipped += 1
            else:
                margin = float(booster.predict(np.array([entry["x"]]), raw_score=True)[0])
                w.writerow([r.dataset_id, r.video_id, repr(margin), "completed", ""])
                scored += 1

    meta = {
        "model_id": f"motionphys-{variant}-lgbm",
        "variant": variant,
        "feature_dim": dim,
        "score": "LightGBM raw margin (확률 아님, 판정 아님)",
        "params": PARAMS,
        "num_boost_round": NUM_BOOST_ROUND,
        "lightgbm_version": lgb.__version__,
        "train_videos": len(train),
        "train_real": int((y == 0).sum()),
        "train_fake": int((y == 1).sum()),
        "train_without_features": sum(1 for r in records if r.split == "train") - len(train),
        "scored_splits": list(SCORE_SPLITS),
        "scored": scored,
        "scored_null": skipped,
        "external_videos_ignored": sum(1 for r in records if r.split == "external"),
        "manifest_sha256": sha256_file(manifest),
        "features_sha256": sha256_file(features),
        "hygiene_warnings": report.warnings,
    }
    (out_dir / "train_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--features", type=Path, required=True)
    p.add_argument("--variant", required=True, choices=["full", "face_roi", "face_motion"])
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    opt = p.parse_args(argv)
    try:
        meta = train_and_score(opt.manifest, opt.features, opt.variant, opt.out_dir, opt.lock)
    except (TrainError, ManifestError, OSError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
