"""단일축 점수 → 그룹 OOF 로지스틱 결합 → OOF 보정 → dev 임계값 잠금 (docs/DESIGN.md §5.4, 백로그 8·12번).

    research/training/.venv/bin/python research/training/train.py \
        --manifest <manifest.csv> --features <특징 폴더> --config configs/training.json --out <새 폴더>

- 입력은 공통 manifest와 training/features/extract.py가 쓴 features.jsonl뿐이다. 영상을 열지 않는다.
- 누수 검사 실패, 최대 그룹 비중 초과, dev 압축 조건 미지정이면 학습하지 않는다.
  최종 평가용 압축 프로파일(또는 그와 같은 출력일 수 있는 1080p 파생본)이 train·dev에 있거나,
  같은 바이트의 영상이 여러 분할에 있어도 학습하지 않는다(감사 A3·A8).
- 학습에는 train 분할만 쓴다. 결합 모델의 입력은 train의 OOF 점수다(in-sample 점수 금지).
- 보정(sigmoid)은 OOF 예측으로만 맞춘다. 임계값은 dev에서만 정해 잠근다. test 점수는 쓰기만 하고 읽지 않는다.
- external 분할은 건드리지 않는다. 계산하지 못한 점수는 빈칸이다(0 아님).
- 축 성공은 서버와 같은 함수(training/serving.py)로 정하고, 성공하지 않은 축의 값은 입력으로 쓰지 않는다.
  영상별 축 성공을 availability.csv에 남긴다(감사 A9).
- 판정이나 성능 주장은 하지 않는다. 채택 판단은 training/report가 한다.

후보(사전 고정): W, M-full, M-face_roi, M-face_motion, W+M(dev AUC가 가장 높은 M), W+M+S.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from training import config as training_config, hygiene, serving  # noqa: E402
from training.datasets import groups  # noqa: E402
from training.datasets.manifest import ManifestError, read_manifest, sha256_file  # noqa: E402
from training.emulator import profiles as emulator_profiles  # noqa: E402
from training.evaluation import thresholds  # noqa: E402
from training.evaluation.lock import DEFAULT_LOCK_PATH, load_lock  # noqa: E402
from training.evaluation.metrics import Item, roc_auc  # noqa: E402

SCHEMA_VERSION = 1
MOTION_VARIANTS = ("full", "face_roi", "face_motion")
SYNC_INPUTS = ("lse_c_median", "lse_d_median", "abs_offset_median")
AXIS_OF = {"W": "signal", "M": "physics", "S": "alignment"}
AVAILABILITY_AXES = ("signal", "physics", "alignment")
LGB_FIXED = {"objective": "binary", "deterministic": True, "force_row_wise": True, "num_threads": 1, "verbosity": -1}


class TrainError(RuntimeError):
    pass


def read_features(folder: Path) -> tuple[dict[str, dict], dict]:
    meta = json.loads((folder / "features.meta.json").read_text(encoding="utf-8"))
    if meta.get("features_sha256") != sha256_file(folder / "features.jsonl"):
        raise TrainError("features.jsonl이 features.meta.json의 해시와 다르다")
    rows = {}
    with (folder / "features.jsonl").open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            rows[row["uid"]] = row
    return rows, meta


def _source_short_side(rec, feats: dict) -> int | None:
    """파생본이면 부모, 아니면 자기 영상의 짧은 변(px). Gate가 읽은 크기가 없으면 None."""
    uid = f"{rec.dataset_id}:{rec.parent_video_id}" if rec.parent_video_id else rec.uid
    media = (feats.get(uid) or {}).get("media") or {}
    w, h = media.get("width"), media.get("height")
    ok = all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (w, h))
    return min(w, h) if ok else None


def _held_out_twins(internal, held_out: set[str], feats: dict) -> list[tuple[str, str]]:
    """train·dev에서 최종 평가용 프로파일과 같은 출력일 수 있는 (파생 프로파일, 최종 평가용 프로파일)."""
    out = set()
    for r in internal:
        p = r.compression_profile_id
        if r.split not in ("train", "dev") or not p or p in held_out or p not in emulator_profiles.PROFILES:
            continue
        for h in held_out:
            if h in emulator_profiles.PROFILES and emulator_profiles.may_equal_output(p, h, _source_short_side(r, feats)):
                out.add((p, h))
    return sorted(out)


def _same_bytes_across_splits(internal, feats: dict) -> list[str]:
    """manifest의 file_hash와 추출기가 계산한 input_sha256을 함께 보고, 여러 분할에 걸친 해시."""
    splits_of: dict[str, set[str]] = {}
    for r in internal:
        for h in {r.file_hash, (feats.get(r.uid) or {}).get("input_sha256")} - {None, ""}:
            splits_of.setdefault(h, set()).add(r.split)
    return sorted(h for h, s in splits_of.items() if len(s) > 1)


def fold_of(group: str, seed: int, k: int) -> int:
    return int(hashlib.sha256(f"{seed}:{group}".encode("utf-8")).hexdigest(), 16) % k


def _platt(np, scores, y) -> dict:
    """sigmoid 보정 p = 1 / (1 + exp(-(a·s + b))). 거의 규제하지 않는 로지스틱 회귀로 맞춘다."""
    from sklearn.linear_model import LogisticRegression
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000).fit(np.asarray(scores).reshape(-1, 1), y)
    return {"a": float(model.coef_[0][0]), "b": float(model.intercept_[0])}


def train(manifest: Path, features_dir: Path, config: dict, out: Path, lock_path: Path = DEFAULT_LOCK_PATH) -> dict:
    import lightgbm as lgb
    import numpy as np
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    config = training_config.validate(config)
    records = read_manifest(manifest)
    report = hygiene.check(records, load_lock(lock_path))
    if not report.ok:
        raise TrainError("누수 검사 실패. 학습하지 않는다: " + ", ".join(e["code"] for e in report.errors))
    sizes = groups.size_summary(records, config["max_group_share"])
    if not sizes["within_limit"]:
        raise TrainError(f"가장 큰 그룹이 내부 영상의 {sizes['largest_group_share']:.1%}다"
                         f"(상한 {config['max_group_share']:.0%}). 학습하지 않는다")
    feats, feat_meta = read_features(features_dir)
    if feat_meta.get("manifest_sha256") != sha256_file(manifest):
        raise TrainError("특징이 이 manifest에서 추출된 것이 아니다(manifest_sha256 불일치)")

    internal = [r for r in sorted(records, key=lambda r: r.uid) if r.split in ("train", "dev", "test")]
    gid = groups.group_ids(records)
    dev_conditions = config["dev_compression_conditions"]
    held_out = set(config["held_out_compression_profiles"])
    leaked = sorted({r.compression_profile_id for r in internal
                     if r.split in ("train", "dev") and r.compression_profile_id in held_out})
    if leaked:
        # 최종 평가용으로 남긴 압축 조건은 학습·증강·선택·임계값에 쓰지 않는다(docs/compression-emulator.md §2)
        raise TrainError(f"최종 평가용 압축 프로파일이 train·dev에 있다: {leaked}")
    twins = _held_out_twins(internal, held_out, feats)
    if twins:
        # 짧은 변 1080px 원본의 x264-crf34-1080p는 최종 평가 전용 x264-crf34-source와 같은 바이트다(감사 A3)
        raise TrainError("최종 평가용 압축 프로파일과 같은 출력일 수 있는 파생본이 train·dev에 있다(원본 크기를 모르면 "
                         "같을 수 있다고 본다): " + ", ".join(f"{p} = {h}" for p, h in twins))
    dup = _same_bytes_across_splits(internal, feats)
    if dup:
        # 어댑터는 영상을 열지 않아 원본 행의 file_hash가 비어 있다. 추출기가 계산한 해시로도 본다(감사 A8)
        raise TrainError(f"같은 바이트의 영상이 여러 분할에 있다: {len(dup)}개 해시, 예 {dup[:3]}")
    present = sorted({r.compression_profile_id or training_config.ORIGINAL for r in internal if r.split == "dev"})
    absent = sorted(set(dev_conditions) - set(present))
    if absent:
        raise TrainError(f"dev에 없는 압축 조건을 지정했다: {absent}. dev에 있는 조건: {present}")
    dev_used = {r.uid for r in internal if r.split == "dev"
                and (r.compression_profile_id or training_config.ORIGINAL) in dev_conditions}
    by_split = {s: [r for r in internal if r.split == s] for s in ("train", "dev", "test")}
    train_rows = by_split["train"]
    k = config["n_folds"]
    fold = {r.uid: fold_of(gid[r.uid], config["fold_seed"], k) for r in train_rows}
    y_of = {r.uid: 1 if r.label == "fake" else 0 for r in internal}
    for f in range(k):
        rest = {y_of[r.uid] for r in train_rows if fold[r.uid] != f}
        if rest != {0, 1} or not any(fold[r.uid] == f for r in train_rows):
            raise TrainError(f"폴드 {f}: 학습 쪽에 진짜와 가짜가 모두 있어야 하고 검증 쪽이 비면 안 된다. "
                             "train 그룹 수가 너무 적다")

    def axis(uid: str, name: str) -> dict:
        return ((feats.get(uid) or {}).get("axes") or {}).get(name) or {}

    # 축 성공은 서버와 같은 함수로 정한다(MotionPhys는 full 변형 기준). 성공하지 않은 축의 값은 입력으로 쓰지 않는다.
    # 그래야 학습·검증한 영상과 서버가 그 후보를 쓰는 영상이 같은 기준으로 갈린다(docs/DESIGN.md §15.3 2026-11-18, 감사 A9)
    ok_axes = {r.uid: serving.successful_axes(serving.feature_statuses((feats.get(r.uid) or {}).get("axes") or {}))
               for r in internal}

    def if_ok(uid: str, server_axis: str, value):
        return value if server_axis in ok_axes[uid] else None

    # column[이름][uid] = 값 또는 None. train의 값은 OOF다(그 영상을 보지 않은 모델의 출력)
    column: dict[str, dict[str, float | None]] = {}
    column["W"] = {r.uid: if_ok(r.uid, "signal", axis(r.uid, "waverep").get(config["waverep_score"])) for r in internal}
    for name in SYNC_INPUTS:
        column[f"S.{name}"] = {r.uid: if_ok(r.uid, "alignment", axis(r.uid, "syncnet").get(name)) for r in internal}

    out.mkdir(parents=True, exist_ok=False)
    (out / "models").mkdir()
    params = {**LGB_FIXED, "seed": config["lightgbm"]["seed"]}
    rounds = config["lightgbm"]["num_boost_round"]
    motion_meta = {}
    for variant in MOTION_VARIANTS:
        x_of = {r.uid: if_ok(r.uid, "physics",
                             ((axis(r.uid, "motionphys").get("variants") or {}).get(variant) or {}).get("features"))
                for r in internal}
        usable = [r for r in train_rows if x_of[r.uid] is not None]
        col: dict[str, float | None] = {r.uid: None for r in internal}
        dims = {len(x_of[r.uid]) for r in internal if x_of[r.uid] is not None}
        if len(dims) > 1:
            raise TrainError(f"MotionPhys {variant}: 특징 차원이 섞여 있다: {sorted(dims)}")
        trainable = {y_of[r.uid] for r in usable} == {0, 1}
        if trainable:
            for f in range(k):
                fit = [r for r in usable if fold[r.uid] != f]
                held = [r for r in usable if fold[r.uid] == f]
                if {y_of[r.uid] for r in fit} != {0, 1} or not held:
                    continue  # 이 폴드의 영상은 점수가 없다(None)
                booster = lgb.train(params, lgb.Dataset(np.array([x_of[r.uid] for r in fit]),
                                                        label=np.array([y_of[r.uid] for r in fit])), rounds)
                for r, s in zip(held, booster.predict(np.array([x_of[r.uid] for r in held]), raw_score=True)):
                    col[r.uid] = float(s)
            final = lgb.train(params, lgb.Dataset(np.array([x_of[r.uid] for r in usable]),
                                                  label=np.array([y_of[r.uid] for r in usable])), rounds)
            final.save_model(str(out / "models" / f"motionphys-{variant}.txt"))
            rest = [r for r in by_split["dev"] + by_split["test"] if x_of[r.uid] is not None]
            if rest:
                for r, s in zip(rest, final.predict(np.array([x_of[r.uid] for r in rest]), raw_score=True)):
                    col[r.uid] = float(s)
        column[f"M-{variant}"] = col
        motion_meta[variant] = {"trained": trainable, "train_videos": len(usable),
                                "feature_dim": next(iter(dims)) if dims else None,
                                "model_file": f"motionphys-{variant}.txt" if trainable else None,
                                "model_sha256": sha256_file(out / "models" / f"motionphys-{variant}.txt") if trainable else None}

    def dev_auc(name: str):
        rows = [r for r in by_split["dev"] if r.uid in dev_used and column[name][r.uid] is not None]
        return roc_auc([column[name][r.uid] for r in rows if r.label == "fake"],
                       [column[name][r.uid] for r in rows if r.label == "real"])

    # 결합에 넣을 MotionPhys 후보는 dev AUC로 고른다(동률이면 A → B → C 순)
    motion_auc = {v: dev_auc(f"M-{v}") for v in MOTION_VARIANTS}
    ranked = [v for v in MOTION_VARIANTS if motion_auc[v] is not None]
    best_motion = max(ranked, key=lambda v: motion_auc[v]) if ranked else None

    specs = [("W", ["W"], ["W"])]
    specs += [(f"M-{v}", [f"M-{v}"], ["M"]) for v in MOTION_VARIANTS if motion_meta[v]["trained"]]
    if best_motion:
        specs.append(("W+M", ["W", f"M-{best_motion}"], ["W", "M"]))
        specs.append(("W+M+S", ["W", f"M-{best_motion}", *[f"S.{n}" for n in SYNC_INPUTS]], ["W", "M", "S"]))

    (out / "scores").mkdir()
    (out / "oof").mkdir()
    (out / "thresholds").mkdir()
    manifest_sha = sha256_file(manifest)
    # 영상별 축 성공. 리포트가 대체 후보를 "서버에서 실제로 쓰일 test 영상"에서 검증할 때 쓴다(감사 A9)
    with (out / "availability.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["dataset_id", "video_id", *AVAILABILITY_AXES])
        for r in internal:
            w.writerow([r.dataset_id, r.video_id, *(int(a in ok_axes[r.uid]) for a in AVAILABILITY_AXES)])
    candidates = []
    for cand, inputs, letters in specs:
        def vector(uid, inputs=inputs):
            values = [column[c][uid] for c in inputs]
            return None if any(v is None for v in values) else values

        fit_rows = [r for r in train_rows if vector(r.uid) is not None]
        if {y_of[r.uid] for r in fit_rows} != {0, 1}:
            continue  # 이 조합으로는 학습할 수 없다. 후보에서 뺀다(리포트에 없는 후보로 남는다)
        score: dict[str, float | None] = {r.uid: None for r in internal}
        if len(inputs) == 1:
            model = {"mean": [0.0], "scale": [1.0], "coef": [1.0], "intercept": 0.0}
            for r in internal:
                score[r.uid] = column[inputs[0]][r.uid]
        else:
            def fit(rows):
                scaler = StandardScaler().fit(np.array([vector(r.uid) for r in rows]))
                lr = LogisticRegression(C=config["logistic"]["C"], solver="lbfgs", max_iter=1000).fit(
                    scaler.transform(np.array([vector(r.uid) for r in rows])), np.array([y_of[r.uid] for r in rows]))
                return scaler, lr

            def apply(scaler, lr, rows):
                if rows:
                    values = lr.decision_function(scaler.transform(np.array([vector(r.uid) for r in rows])))
                    for r, s in zip(rows, values):
                        score[r.uid] = float(s)

            for f in range(k):  # 결합 모델 자체도 교차 적합해 train의 OOF 예측을 얻는다(보정용)
                rest = [r for r in fit_rows if fold[r.uid] != f]
                if {y_of[r.uid] for r in rest} == {0, 1}:
                    apply(*fit(rest), [r for r in fit_rows if fold[r.uid] == f])
            scaler, lr = fit(fit_rows)
            apply(scaler, lr, [r for r in by_split["dev"] + by_split["test"] if vector(r.uid) is not None])
            model = {"mean": [float(v) for v in scaler.mean_], "scale": [float(v) for v in scaler.scale_],
                     "coef": [float(v) for v in lr.coef_[0]], "intercept": float(lr.intercept_[0])}

        oof = [r for r in fit_rows if score[r.uid] is not None]
        if {y_of[r.uid] for r in oof} != {0, 1}:
            continue
        calibration = _platt(np, [score[r.uid] for r in oof], np.array([y_of[r.uid] for r in oof]))

        def write_scores(path: Path, rows) -> None:
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(["dataset_id", "video_id", "score", "status", "reason_code",
                            "video_duration_sec", "eligible_duration_sec", "analyzed_duration_sec"])
                for r in rows:
                    row = feats.get(r.uid) or {}
                    s = score[r.uid]
                    w.writerow([r.dataset_id, r.video_id, "" if s is None else repr(s),
                                "completed" if s is not None else "insufficient_input",
                                "" if s is not None else "missing_axis_input",
                                row.get("video_duration_sec") or "", row.get("eligible_duration_sec") or "",
                                (row.get("eligible_duration_sec") or "") if s is not None else ""])

        scores_path = out / "scores" / f"{cand}.csv"
        write_scores(scores_path, by_split["dev"] + by_split["test"])
        write_scores(out / "oof" / f"{cand}.csv", train_rows)
        dev_items = [Item(uid=r.uid, label=r.label, group=gid[r.uid], score=score[r.uid])
                     for r in by_split["dev"] if r.uid in dev_used]
        # dev에서만 정한다. fit_threshold가 dev가 아닌 분할이 섞이면 거부한다
        threshold = thresholds.fit_threshold(
            dev_items, ["dev"] * len(dev_items), model_id=cand, manifest_sha256=manifest_sha,
            scores_sha256=sha256_file(scores_path), target_fpr=config["target_fpr"])
        thresholds.save_threshold(out / "thresholds" / f"{cand}.json", threshold)
        entry = {
            "candidate": cand, "axes": [AXIS_OF[x] for x in letters], "inputs": inputs,
            "motion_variant": best_motion if "M" in letters and len(inputs) > 1 else
            (inputs[0][2:] if inputs[0].startswith("M-") else None),
            "model": model, "calibration": calibration, "score": "decision value (확률 아님)",
            "threshold_digest": threshold["digest"], "scores_sha256": sha256_file(scores_path),
            "train_videos_fit": len(fit_rows), "train_videos_oof": len(oof), "dev_auc_for_selection": dev_auc_safe(
                roc_auc, dev_items),
        }
        (out / "models" / f"{cand}.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")
        candidates.append(entry)

    if not any(c["candidate"] == "W" for c in candidates):
        raise TrainError("WaveRep 점수로 기준선을 만들 수 없다(train 또는 dev에 점수가 없다)")

    aux = {name: None for name in training_config.WAVEREP_SCORES}
    for name in aux:  # 보조 비교: dev에서만 본다. 선택에 쓰지 않는다(주 지표는 설정에 고정)
        rows = [r for r in by_split["dev"] if r.uid in dev_used and axis(r.uid, "waverep").get(name) is not None]
        aux[name] = roc_auc([axis(r.uid, "waverep")[name] for r in rows if r.label == "fake"],
                            [axis(r.uid, "waverep")[name] for r in rows if r.label == "real"])

    meta = {
        "schema_version": SCHEMA_VERSION, "config": config,
        "manifest_sha256": manifest_sha, "features_sha256": feat_meta["features_sha256"],
        "availability_sha256": sha256_file(out / "availability.csv"), "serving_rule": serving.RULE,
        "feature_version": feat_meta["feature_version"], "synthetic": bool(feat_meta.get("synthetic")),
        "dev_compression_conditions": dev_conditions, "dev_conditions_present": present,
        "train_compression_conditions": sorted({r.compression_profile_id or training_config.ORIGINAL for r in train_rows}),
        "split_videos": {s: len(rows) for s, rows in by_split.items()}, "dev_videos_used": len(dev_used),
        "group_sizes": sizes, "hygiene_warnings": report.warnings,
        "folds": {"k": k, "seed": config["fold_seed"], "videos_per_fold": [sum(1 for u in fold.values() if u == f) for f in range(k)]},
        "motionphys": motion_meta, "motionphys_dev_auc": motion_auc, "motion_variant_for_fusion": best_motion,
        "waverep_dev_auc_by_aggregation": aux,
        "candidates": [c["candidate"] for c in candidates],
        "versions": {"numpy": np.__version__, "scikit-learn": sklearn.__version__, "lightgbm": lgb.__version__},
        "stacking_note": "MotionPhys의 OOF 점수와 결합 모델의 교차 적합은 같은 폴드를 쓴다. 완전한 중첩 교차 검증은 아니다.",
    }
    (out / "train_meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return meta


def dev_auc_safe(roc, items) -> float | None:
    return roc([i.score for i in items if i.label == "fake" and i.score is not None],
               [i.score for i in items if i.label == "real" and i.score is not None])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--features", type=Path, required=True, help="features.jsonl과 features.meta.json이 있는 폴더")
    p.add_argument("--config", type=Path, default=training_config.DEFAULT_PATH)
    p.add_argument("--out", type=Path, required=True, help="새 폴더(이미 있으면 거부)")
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    opt = p.parse_args(argv)
    try:
        config = json.loads(opt.config.read_text(encoding="utf-8"))
        meta = train(opt.manifest, opt.features, config, opt.out, opt.lock)
    except (TrainError, training_config.ConfigError, ManifestError, thresholds.ThresholdError,
            FileExistsError, OSError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    print(json.dumps({k: meta[k] for k in ("candidates", "motion_variant_for_fusion", "dev_compression_conditions",
                                           "split_videos", "dev_videos_used")}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
