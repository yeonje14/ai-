"""고정 평가 파이프라인의 실행 명령 (README §13, 백로그 8번).

    python -m training.evaluation.run fit-threshold \
        --manifest <manifest.csv> --scores <scores.csv> --model-id <이름> --out <threshold.json>
    python -m training.evaluation.run evaluate \
        --manifest <manifest.csv> [--manifest <external.csv>] --scores <scores.csv> \
        --threshold <threshold.json> --split test --out <report.json>

순서가 강제된다.
1. 누수 검사를 통과하지 못한 manifest로는 임계값을 정하지도, 평가하지도 않는다.
2. 임계값은 dev 분할에서만 정해 파일로 고정한다. evaluate는 임계값을 숫자로 받지 않는다.
3. external 분할은 잠금이 풀리고 --final-external을 줘야 평가한다.

점수 파일(CSV): dataset_id, video_id, score, status, reason_code,
  video_duration_sec, eligible_duration_sec, analyzed_duration_sec (뒤 세 열은 없어도 된다).
score가 빈칸이면 판정을 내지 못한 영상이다. 지표에서 조용히 빠지지 않고 보류로 센다.

종료 코드: 0 성공, 1 누수·입력 오류, 3 임계값·잠금 규칙 위반.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Optional

from training import hygiene
from training.datasets.groups import group_ids
from training.datasets.manifest import ManifestError, Record, read_manifest, sha256_file
from training.evaluation import thresholds
from training.evaluation.lock import DEFAULT_LOCK_PATH, ExternalEvalLocked, assert_unlocked, load_lock
from training.evaluation.metrics import Item, evaluate

REPORT_SCHEMA_VERSION = 1
MISSING_SCORE = "missing_score"
EVAL_SPLITS = ("train", "dev", "test", "external")
DURATION_FIELDS = ("video_duration_sec", "eligible_duration_sec", "analyzed_duration_sec")


class InputError(ValueError):
    """manifest·점수 파일이 규칙에 맞지 않는다."""


def read_scores(path: Path) -> dict[str, dict]:
    """{uid: {score, status, reason_code, 길이들}}. score가 빈칸이면 None."""
    out: dict[str, dict] = {}
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        need = {"dataset_id", "video_id", "score"}
        if not need <= set(reader.fieldnames or []):
            raise InputError(f"점수 파일에 필요한 열: {sorted(need)}")
        for n, row in enumerate(reader, start=2):
            uid = f"{row['dataset_id']}:{row['video_id']}"
            if uid in out:
                raise InputError(f"점수 파일 {n}행: {uid} 중복")
            entry: dict = {
                "score": _number(row.get("score"), f"{n}행 score"),
                "status": (row.get("status") or "").strip(),
                "reason_code": (row.get("reason_code") or "").strip(),
            }
            for name in DURATION_FIELDS:
                entry[name] = _number(row.get(name), f"{n}행 {name}")
            out[uid] = entry
    return out


def _number(text: Optional[str], where: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as e:
        raise InputError(f"점수 파일 {where}: 숫자가 아니다") from e
    if not math.isfinite(value):
        raise InputError(f"점수 파일 {where}: 유한한 숫자가 아니다")
    return value


def build_items(records: list[Record], gid: dict[str, str], scores: dict[str, dict]) -> list[Item]:
    """manifest 영상마다 Item 하나. 점수 행이 없는 영상도 보류(missing_score)로 남긴다."""
    items = []
    for r in records:
        s = scores.get(r.uid)
        score = s["score"] if s else None
        reason = "" if score is not None else (s["reason_code"] or s["status"] if s else MISSING_SCORE) or MISSING_SCORE
        items.append(Item(
            uid=r.uid, label=r.label, group=gid[r.uid], score=score,
            generator=r.generator_id, manipulation_type=r.manipulation_type, reason_code=reason,
        ))
    return items


def coverage_summary(records: list[Record], scores: dict[str, dict]) -> dict:
    """분석한 양의 합계. 정확도나 신뢰도가 아니다. 값이 없으면 None."""
    total = {name: 0.0 for name in DURATION_FIELDS}
    have = {name: 0 for name in DURATION_FIELDS}
    for r in records:
        s = scores.get(r.uid) or {}
        for name in DURATION_FIELDS:
            if s.get(name) is not None:
                total[name] += s[name]
                have[name] += 1

    def ratio(num: str, den: str) -> Optional[float]:
        return total[num] / total[den] if have[num] and have[den] and total[den] > 0 else None

    return {
        **{name: (total[name] if have[name] else None) for name in DURATION_FIELDS},
        "videos_with_duration": have["video_duration_sec"],
        "full_video_coverage": ratio("analyzed_duration_sec", "video_duration_sec"),
        "eligible_coverage": ratio("analyzed_duration_sec", "eligible_duration_sec"),
    }


def _load(manifests: list[Path], lock_path: Path) -> tuple[list[Record], dict[str, dict], hygiene.HygieneReport]:
    lock = load_lock(lock_path)
    records = [r for path in manifests for r in read_manifest(path)]
    report = hygiene.check(records, lock)
    return records, lock, report


def cmd_fit_threshold(opt) -> int:
    records, lock, report = _load([opt.manifest], opt.lock)
    if not report.ok:
        raise InputError("누수 검사 실패. 임계값을 정하지 않는다: " + ", ".join(e["code"] for e in report.errors))
    scores = read_scores(opt.scores)
    dev = [r for r in records if r.split == thresholds.SOURCE_SPLIT]
    if not dev:
        raise thresholds.ThresholdError("manifest에 dev 분할 영상이 없다")
    locked = sorted({r.dataset_id for r in dev if r.dataset_id in lock})
    if locked:  # hygiene에서 이미 걸리지만 한 번 더 막는다
        raise ExternalEvalLocked(f"외부 평가 자료로 임계값을 정할 수 없다: {locked}")
    items = build_items(dev, group_ids(records), scores)
    threshold = thresholds.fit_threshold(
        items, [r.split for r in dev],
        model_id=opt.model_id, target_fpr=opt.target_fpr,
        manifest_sha256=sha256_file(opt.manifest), scores_sha256=sha256_file(opt.scores),
    )
    thresholds.save_threshold(opt.out, threshold)
    print(json.dumps(threshold, indent=2, ensure_ascii=False))
    return 0


def cmd_evaluate(opt) -> int:
    threshold = thresholds.load_threshold(opt.threshold)
    manifest_hashes = {str(p): sha256_file(p) for p in opt.manifest}
    if threshold["dev_manifest_sha256"] not in manifest_hashes.values():
        # dev를 함께 넣어야 dev와 평가 분할 사이의 누수를 검사할 수 있다
        raise thresholds.ThresholdError("임계값을 정할 때 쓴 dev manifest가 --manifest에 없다(sha256 불일치)")
    records, lock, report = _load(opt.manifest, opt.lock)
    if not report.ok:
        raise InputError("누수 검사 실패. 평가하지 않는다: " + ", ".join(e["code"] for e in report.errors))

    target = [r for r in records if r.split == opt.split]
    if not target:
        raise InputError(f"manifest에 {opt.split} 분할 영상이 없다")
    if opt.split == "external":
        if not opt.final_external:
            raise ExternalEvalLocked("external 분할은 --final-external을 줘야 평가한다")
        assert_unlocked({r.dataset_id for r in target}, lock)

    scores = read_scores(opt.scores)
    unknown = sorted(set(scores) - {r.uid for r in records})
    if unknown:
        raise InputError(f"manifest에 없는 영상의 점수 {len(unknown)}건. 예: {unknown[:3]}")
    items = build_items(target, group_ids(records), scores)
    result = evaluate(items, threshold["threshold"], n_boot=opt.n_boot, seed=opt.seed)

    out = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "split": opt.split,
        "model_id": threshold["model_id"],
        "threshold": {k: threshold[k] for k in (
            "threshold", "rule", "target_fpr", "source_split", "dev_fpr", "dev_real_scored", "digest")},
        "inputs": {
            "manifests": manifest_hashes,
            "scores_sha256": sha256_file(opt.scores),
            "threshold_file": str(opt.threshold),
        },
        # 누수 검사 결과와 경고 개수는 항상 싣는다
        "hygiene": report.to_dict(),
        "hygiene_warnings_in_split": hygiene.check(target, lock).warnings,
        **result,
        "coverage": coverage_summary(target, scores),
        "notes": [
            "보고의 기본 단위는 생성기별(by_generator)이다. 유형별(by_manipulation_type)은 보조이며, "
            "데이터셋의 생성기를 A1~C2에 대응시킨 것은 잠정이다.",
            "tpr·fpr은 dev에서 고정한 임계값을 적용한 값이다. 이 분할의 ROC에서 다시 고른 값이 아니다.",
            "verdict_coverage와 coverage는 분석한 양이다. 정확도나 신뢰도가 아니다.",
            "신뢰구간은 인물·원본 계보 그룹 단위 bootstrap이다. 원본 식별자가 없는 영상은 서로 독립으로 취급된다.",
        ],
    }
    Path(opt.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    o = result["overall"]
    print(f"{opt.split}: 영상 {result['counts']['videos']}, 판정 제공 비율 {result['selective']['verdict_coverage']}, "
          f"AUC {o['roc_auc']['value']}, TPR {o['tpr']['value']}, FPR {o['fpr']['value']} → {opt.out}")
    print("경고:", json.dumps(out["hygiene_warnings_in_split"], ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="고정 평가 파이프라인")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fit-threshold", help="dev 분할에서 임계값을 정해 파일로 고정한다")
    f.add_argument("--manifest", type=Path, required=True)
    f.add_argument("--scores", type=Path, required=True)
    f.add_argument("--model-id", required=True)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--target-fpr", type=float, default=thresholds.DEFAULT_TARGET_FPR)
    f.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    f.set_defaults(func=cmd_fit_threshold)

    e = sub.add_parser("evaluate", help="고정한 임계값으로 한 분할을 평가한다")
    e.add_argument("--manifest", type=Path, action="append", required=True,
                   help="여러 번 줄 수 있다. 임계값을 정한 dev manifest가 반드시 들어 있어야 한다")
    e.add_argument("--scores", type=Path, required=True)
    e.add_argument("--threshold", type=Path, required=True, help="fit-threshold가 만든 파일. 숫자를 직접 줄 수 없다")
    e.add_argument("--split", choices=EVAL_SPLITS, required=True)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--n-boot", type=int, default=1000)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--final-external", action="store_true", help="external 분할의 최종 평가임을 명시한다")
    e.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    e.set_defaults(func=cmd_evaluate)

    opt = p.parse_args(argv)
    try:
        return opt.func(opt)
    except (thresholds.ThresholdError, ExternalEvalLocked) as err:
        print(f"거부: {err}", file=sys.stderr)
        return 3
    except (InputError, ManifestError, OSError, ValueError) as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
