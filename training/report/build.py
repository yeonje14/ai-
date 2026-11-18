"""학습 결과 폴더 → 비교 리포트(JSON + Markdown)와 채택 판단.

    conda activate trinity
    python -m training.report.build --manifest <manifest.csv> --run <학습 결과 폴더> --out <새 폴더>

- 임계값은 학습 때 dev에서 잠근 파일을 그대로 읽는다. 숫자로 받는 옵션이 없고 다시 정하지 않는다.
- dev 지표는 학습 때 지정한 압축 조건의 dev만으로, test 지표는 운영 범위 밖 조건(480p)을 뺀 test로 계산한다
  (압축 조건별로도 나눈다). 운영 범위 밖 조건은 관문에 넣지 않고 판정 제공 비율·보류 사유만 따로 보고한다(감사 A6).
- 학습에 쓴 설정이 커밋된 configs/training.json과 다르면 리포트 맨 위에 적는다. 그런 결과로는 묶음을 만들 수 없다(감사 A2).
- 신뢰구간은 인물·원본 계보 그룹 bootstrap이다. 차이는 같은 재표본으로 짝지어 계산한다.
- 합성 데이터의 리포트는 맨 위에 합성이라고 적힌다. 수치는 성능이 아니다.
- external 분할은 읽지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from training import config as training_config, hygiene
from training.datasets import groups
from training.datasets.manifest import ManifestError, read_manifest, sha256_file
from training.evaluation import metrics, thresholds
from training.evaluation.lock import DEFAULT_LOCK_PATH, load_lock
from training.report import decision as rules

SCHEMA_VERSION = 2  # 2: training_config_matches_committed, test_gate_compression_conditions, test_out_of_range(감사 2026-11-18)


class ReportError(RuntimeError):
    pass


def _scores(path: Path) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return {f"{r['dataset_id']}:{r['video_id']}": r for r in csv.DictReader(f)}


def _media(features_dir: Path | None) -> dict:
    if features_dir is None or not (features_dir / "features.jsonl").is_file():
        return {}
    with (features_dir / "features.jsonl").open(encoding="utf-8") as f:
        return {row["uid"]: row.get("media") for row in map(json.loads, f)}


def _coverage_only(items: list) -> dict:
    """운영 범위 밖 조건의 보고: 판정 제공 비율과 보류 사유만. 탐지 지표(AUC·TPR·FPR)는 계산하지 않는다."""
    def part(members):
        scored = sum(1 for it in members if it.score is not None)
        reasons: dict[str, int] = {}
        for it in members:
            if it.score is None:
                reasons[it.reason_code or metrics.UNKNOWN] = reasons.get(it.reason_code or metrics.UNKNOWN, 0) + 1
        return {"videos": len(members), "real": sum(1 for it in members if it.label == "real"),
                "fake": sum(1 for it in members if it.label == "fake"), "scored": scored,
                "verdict_coverage": scored / len(members) if members else None,
                "abstained_by_reason": dict(sorted(reasons.items()))}

    names = sorted({it.compression or metrics.ORIGINAL for it in items})
    return {**part(items), "by_compression": {n: part([it for it in items if (it.compression or metrics.ORIGINAL) == n])
                                              for n in names}}


def build(manifest: Path, run: Path, lock_path: Path = DEFAULT_LOCK_PATH, n_boot: int | None = None,
          features_dir: Path | None = None, committed_config: dict | None = None) -> dict:
    meta = json.loads((run / "train_meta.json").read_text(encoding="utf-8"))
    config = training_config.validate(meta["config"])
    committed = training_config.validate(committed_config if committed_config is not None else training_config.load())
    config_committed = training_config.without_comment(config) == training_config.without_comment(committed)
    adoption = config["adoption"]
    n_boot = n_boot or adoption["n_boot"]
    seed, confidence = adoption["bootstrap_seed"], adoption["confidence"]
    if sha256_file(manifest) != meta["manifest_sha256"]:
        raise ReportError("학습에 쓴 manifest가 아니다(sha256 불일치)")
    records = read_manifest(manifest)
    report = hygiene.check(records, load_lock(lock_path))
    if not report.ok:
        raise ReportError("누수 검사 실패. 평가하지 않는다: " + ", ".join(e["code"] for e in report.errors))
    gid = groups.group_ids(records)
    dev_conditions = set(meta["dev_compression_conditions"])
    out_of_range = set(config["out_of_range_compression_profiles"])
    split_rows = {
        "dev": [r for r in records if r.split == "dev"
                and (r.compression_profile_id or training_config.ORIGINAL) in dev_conditions],
        "test": [r for r in records if r.split == "test" and r.compression_profile_id not in out_of_range],
        "test_out_of_range": [r for r in records if r.split == "test" and r.compression_profile_id in out_of_range],
    }

    candidates, items, threshold_of, evaluated = [], {}, {}, {}
    for name in meta["candidates"]:
        model = json.loads((run / "models" / f"{name}.json").read_text(encoding="utf-8"))
        scores_path = run / "scores" / f"{name}.csv"
        if sha256_file(scores_path) != model["scores_sha256"]:
            raise ReportError(f"{name}: 점수 파일이 학습 뒤에 바뀌었다")
        threshold = thresholds.load_threshold(run / "thresholds" / f"{name}.json")
        if threshold["digest"] != model["threshold_digest"] or threshold["model_id"] != name:
            raise ReportError(f"{name}: 임계값 파일이 이 모델의 것이 아니다")
        scores = _scores(scores_path)
        candidates.append(model)
        threshold_of[name] = threshold["threshold"]
        items[name], evaluated[name] = {}, {}
        for split, rows in split_rows.items():
            items[name][split] = [metrics.Item(
                uid=r.uid, label=r.label, group=gid[r.uid],
                score=float(scores[r.uid]["score"]) if scores.get(r.uid, {}).get("score") else None,
                generator=r.generator_id, manipulation_type=r.manipulation_type,
                reason_code=(scores.get(r.uid) or {}).get("reason_code", "") or "missing_score",
                compression=r.compression_profile_id) for r in rows]
            if split == "test_out_of_range":
                evaluated[name][split] = _coverage_only(items[name][split])
                continue
            evaluated[name][split] = metrics.evaluate(items[name][split], threshold_of[name], n_boot, seed, confidence)
            evaluated[name][split]["calibration"] = rules.calibration_metrics(items[name][split], model["calibration"])

    selection = rules.select_on_dev({n: evaluated[n]["dev"] for n in evaluated}, candidates)
    own = {n: rules.own_gates(evaluated[n]["test"], adoption) for n in evaluated}
    comparisons, fusion_checks = {}, {}

    def compare(a: str, b: str) -> dict:
        key = rules.comparison_key(a, b)
        if key not in comparisons:
            comparisons[key] = rules.paired_difference(items[a]["test"], items[b]["test"], threshold_of[a],
                                                       threshold_of[b], n_boot, seed, confidence)
        return comparisons[key]

    best_single = selection["best_single"]
    for c in candidates:
        name = c["candidate"]
        if len(c["axes"]) > 1 and rules.BASELINE in evaluated:
            vs_best = compare(name, best_single) if best_single not in (None, rules.BASELINE) else None
            fusion_checks[name] = rules.fusion_gates(compare(name, rules.BASELINE), vs_best, adoption)
    verdict = rules.decide(selection, own, fusion_checks)

    return {
        "schema_version": SCHEMA_VERSION,
        "synthetic": bool(meta.get("synthetic")),
        # False면 사전 고정 설정과 다른 기준으로 학습·판단했다. 묶음을 만들 수 없다(감사 A2)
        "training_config_matches_committed": config_committed,
        "dev_compression_conditions": meta["dev_compression_conditions"],
        # 관문(test 지표)에 들어간 압축 조건. 운영 범위 밖 조건은 빠지고 test_out_of_range에 따로 있다
        "test_gate_compression_conditions": sorted({r.compression_profile_id or training_config.ORIGINAL
                                                    for r in split_rows["test"]}),
        "out_of_range_compression_profiles": sorted(out_of_range),
        "train_compression_conditions": meta["train_compression_conditions"],
        "decision": verdict, "selection": selection,
        "gates": {"adoption_config": adoption, "own": own, "fusion": fusion_checks},
        "comparisons_test": comparisons,
        "candidates": {c["candidate"]: {
            "axes": c["axes"], "inputs": c["inputs"], "motion_variant": c["motion_variant"],
            "threshold": threshold_of[c["candidate"]], "threshold_digest": c["threshold_digest"],
            "dev": evaluated[c["candidate"]]["dev"], "test": evaluated[c["candidate"]]["test"],
            "test_out_of_range": evaluated[c["candidate"]]["test_out_of_range"]} for c in candidates},
        "data": {"manifest_sha256": meta["manifest_sha256"], "features_sha256": meta["features_sha256"],
                 "feature_version": meta["feature_version"], "split_videos": meta["split_videos"],
                 "dev_videos_used": meta["dev_videos_used"], "group_sizes": meta["group_sizes"],
                 "hygiene": report.to_dict(), "motionphys_dev_auc": meta["motionphys_dev_auc"],
                 "waverep_dev_auc_by_aggregation": meta["waverep_dev_auc_by_aggregation"]},
        # train·dev만 본다. test의 라벨 분포를 들여다보지 않는다
        "shortcut_diagnostic": rules.shortcut_diagnostic(
            {r.uid: r.label for r in records if r.split in ("train", "dev")}, _media(features_dir)),
        "bootstrap": {"unit": "group", "n_boot": n_boot, "seed": seed, "confidence": confidence, "paired": True},
        "notes": [
            "후보 선택은 dev에서만 했다. test는 선택 뒤의 확인 관문이며 이 결과로 다시 고르지 않는다.",
            "임계값은 dev에서 FPR 5% 목표로 잠근 값이다. test의 실제 FPR은 5%와 다를 수 있다.",
            "판정 제공 비율(coverage)은 분석한 양이다. 정확도나 신뢰도가 아니다.",
            "TPR·FPR은 점수가 나온 영상만으로 계산한다. 점수가 없는 영상은 보류로 센다.",
            "운영 범위 밖 압축 조건(480p)은 test 관문 지표에 넣지 않고 판정 제공 비율·보류 사유만 따로 적는다.",
        ],
    }


def _pct(v) -> str:
    return "–" if v is None else f"{v * 100:.1f}%"


def _num(v) -> str:
    return "–" if v is None else f"{v:.3f}"


def _ci(m: dict, fmt=_num) -> str:
    return "–" if m["value"] is None else f"{fmt(m['value'])} [{fmt(m['ci_low'])}, {fmt(m['ci_high'])}]"


def to_markdown(r: dict) -> str:
    d = r["decision"]
    lines = ["# 학습 비교 리포트", ""]
    if r["synthetic"]:
        lines += ["> **합성 데이터다. 아래 수치는 파이프라인 동작 확인용이며 어떤 모델의 성능도 아니다.**", ""]
    if not r["training_config_matches_committed"]:
        lines += ["> **학습 설정이 커밋된 configs/training.json과 다르다. 사전 고정 기준의 판단이 아니며 묶음을 만들 수 없다.**", ""]
    lines += [
        f"- **dev 압축 조건(임계값·후보 선택에 쓴 것):** {', '.join(r['dev_compression_conditions'])}",
        f"- test 관문에 들어간 압축 조건: {', '.join(r['test_gate_compression_conditions'])} "
        f"(운영 범위 밖으로 뺀 조건: {', '.join(r['out_of_range_compression_profiles']) or '없음'})",
        f"- train 압축 조건: {', '.join(r['train_compression_conditions'])}",
        f"- **판단: {d['decision_ko']}** (`{d['decision']}`)",
        f"- dev에서 고른 결합 후보: {d['selected_fusion'] or '없음'} / 단일 최강: {d['best_single'] or '없음'}",
        f"- 서버에 쓸 수 있는 후보: {', '.join(d['servable_candidates']) or '없음'}",
        f"- 신뢰구간: 그룹 bootstrap {r['bootstrap']['n_boot']}회, {int(r['bootstrap']['confidence'] * 100)}%. 값 [하한, 상한].",
        "", "## 후보별 지표 (test, dev에서 잠근 임계값)", "",
        "| 후보 | 축 | ROC-AUC | TPR | 실제 FPR | 판정 제공 비율 | Brier | ECE |", "|---|---|---|---|---|---|---|---|",
    ]
    for name, c in r["candidates"].items():
        t = c["test"]
        lines.append(f"| {name} | {'+'.join(c['axes'])} | {_ci(t['overall']['roc_auc'])} | {_ci(t['overall']['tpr'], _pct)} | "
                     f"{_ci(t['overall']['fpr'], _pct)} | {_pct(t['selective']['verdict_coverage'])} | "
                     f"{_num(t['calibration']['brier'])} | {_num(t['calibration']['ece'])} |")
    lines += ["", "## dev (선택에 쓴 값)", "", "| 후보 | ROC-AUC | dev TPR | dev FPR | 판정 제공 비율 |", "|---|---|---|---|---|"]
    for name, c in r["candidates"].items():
        v = c["dev"]
        lines.append(f"| {name} | {_num(v['overall']['roc_auc']['value'])} | {_pct(v['overall']['tpr']['value'])} | "
                     f"{_pct(v['overall']['fpr']['value'])} | {_pct(v['selective']['verdict_coverage'])} |")
    lines += ["", "## 기준 대비 차이 (test, 짝지은 그룹 bootstrap)", "",
              "| 비교 | TPR 차이 | FPR 차이 | AUC 차이 | 판정 제공 비율 차이 |", "|---|---|---|---|---|"]
    for key, c in r["comparisons_test"].items():
        lines.append(f"| {key} | {_ci(c['tpr'], _pct)} | {_ci(c['fpr'], _pct)} | {_ci(c['roc_auc'])} | {_ci(c['coverage'], _pct)} |")
    lines += ["", "## 관문", "", "| 후보 | 확인 | 값 | 기준 | 통과 |", "|---|---|---|---|---|"]
    for group in ("own", "fusion"):
        for name, checks in r["gates"][group].items():
            for c in checks:
                lines.append(f"| {name} | {c['check']} | {_num(c['value'])} | {c['rule']} | {'예' if c['passed'] else '아니오'} |")
    lines += ["", "## 압축 조건별 (test)", "", "| 후보 | 조건 | 영상 | ROC-AUC | TPR | 실제 FPR |", "|---|---|---|---|---|---|"]
    for name, c in r["candidates"].items():
        for cond, v in c["test"]["by_compression"].items():
            lines.append(f"| {name} | {cond} | {v['videos']} | {_ci(v['roc_auc'])} | {_ci(v['tpr'], _pct)} | {_ci(v['fpr'], _pct)} |")
    lines += ["", "## 운영 범위 밖 압축 조건 (test, 관문 제외)", "",
              "탐지 지표는 계산하지 않는다. 판정 제공 비율과 보류 사유만 적는다.", "",
              "| 후보 | 조건 | 영상 | 판정 제공 비율 | 보류 사유별 |", "|---|---|---|---|---|"]
    for name, c in r["candidates"].items():
        for cond, v in c["test_out_of_range"]["by_compression"].items():
            reasons = ", ".join(f"{k} {n}" for k, n in v["abstained_by_reason"].items()) or "–"
            lines.append(f"| {name} | {cond} | {v['videos']} | {_pct(v['verdict_coverage'])} | {reasons} |")
    lines += ["", "## 보류(점수 없음) 현황 (test)", "", "| 후보 | 보류율 | 사유별 |", "|---|---|---|"]
    for name, c in r["candidates"].items():
        s = c["test"]["selective"]
        reasons = ", ".join(f"{k} {v}" for k, v in s["abstained_by_reason"].items()) or "–"
        lines.append(f"| {name} | {_pct(s['abstention_rate'])} | {reasons} |")
    g = r["data"]["group_sizes"]
    lines += ["", "## 데이터", "",
              f"- 영상: {r['data']['split_videos']}, dev에서 쓴 영상 {r['data']['dev_videos_used']}개",
              f"- 그룹 {g['groups']}개, 가장 큰 그룹 {g['largest_group_videos']}개({_pct(g['largest_group_share'])}, 상한 {_pct(g['max_group_share'])}), "
              f"중앙값 {g['median_group_videos']}, 크기별 그룹 수 {g['groups_by_size']}",
              f"- 누수 검사 경고: {r['data']['hygiene']['warnings']}",
              f"- MotionPhys 후보의 dev AUC: {r['data']['motionphys_dev_auc']}",
              f"- WaveRep 집계별 dev AUC(보조, 선택에 쓰지 않음): {r['data']['waverep_dev_auc_by_aggregation']}",
              "", "## shortcut 진단 (경고만, 채택 판단에 쓰지 않음)", "", _shortcut_text(r["shortcut_diagnostic"]),
              "", "## 읽을 때 주의", ""] + [f"- {n}" for n in r["notes"]]
    return "\n".join(lines) + "\n"


def _shortcut_text(d: dict) -> str:
    if not d["available"]:
        return "- 파일 메타데이터가 없어 진단하지 못했다(`--features`를 주지 않았거나 합성 데이터다)."
    fields = ", ".join(f"{k} {_num(v['roc_auc'])}" for k, v in d["fields"].items())
    warn = ", ".join(d["warnings"]) or "없음"
    return (f"- 메타데이터 하나만으로 계산한 라벨 AUC(train·dev {d['videos']}개): {fields}\n"
            f"- 0.5에서 {d['warn_margin']} 넘게 벗어난 항목: **{warn}**. {d['note']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--features", type=Path, default=None, help="특징 폴더(shortcut 진단용, 선택)")
    p.add_argument("--run", type=Path, required=True, help="research/training/train.py의 결과 폴더")
    p.add_argument("--out", type=Path, required=True, help="새 폴더(이미 있으면 거부)")
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    opt = p.parse_args(argv)
    try:
        report = build(opt.manifest, opt.run, opt.lock, features_dir=opt.features)
        opt.out.mkdir(parents=True, exist_ok=False)
    except (ReportError, ManifestError, training_config.ConfigError, thresholds.ThresholdError, OSError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    (opt.out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (opt.out / "report.md").write_text(to_markdown(report), encoding="utf-8")
    print(json.dumps(report["decision"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
