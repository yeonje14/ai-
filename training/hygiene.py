"""데이터 위생: 분할 누수 검사 (README §6.4, 백로그 8번).

같은 인물·원본 계보 그룹이 여러 분할에 걸치면 실패다. 실패한 manifest로는 평가하지 않는다.
이 모듈은 manifest만 본다. 영상 파일을 열지 않는다.

    python -m training.hygiene <manifest.csv> [<manifest2.csv> ...] [--lock configs/external_eval_lock.json]

종료 코드: 0 통과, 1 누수·오류 있음, 2 manifest를 읽지 못함.

이번 단계에서 하지 않는 것: 영상 유사도, 무음 편향, 코덱·해상도·FPS shortcut 진단
(실제 파일이 필요하다).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from training.datasets.groups import group_ids
from training.datasets.manifest import INTERNAL_SPLITS, ManifestError, Record, read_manifest, validate
from training.evaluation.lock import DEFAULT_LOCK_PATH, load_lock

MAX_EXAMPLES = 5  # 리포트에 싣는 예시 수. 전체 개수는 따로 센다


@dataclass
class HygieneReport:
    records: int
    groups: int
    split_counts: dict[str, int]
    errors: list[dict] = field(default_factory=list)
    # 경고는 평가 리포트에 항상 그대로 싣는다
    warnings: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "records": self.records,
            "groups": self.groups,
            "split_counts": self.split_counts,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _error(code: str, count: int, examples: list) -> dict:
    return {"code": code, "count": count, "examples": examples[:MAX_EXAMPLES]}


def check(records: Iterable[Record], lock: dict[str, dict]) -> HygieneReport:
    """누수 검사. 예외를 던지지 않고 리포트로 돌려준다(형식 오류는 ManifestError)."""
    records = validate(records)
    gid = group_ids(records)
    split_counts: dict[str, int] = defaultdict(int)
    for r in records:
        split_counts[r.split or "(미배정)"] += 1
    report = HygieneReport(
        records=len(records), groups=len(set(gid.values())), split_counts=dict(sorted(split_counts.items())),
    )

    # 1) 분할이 비어 있는 영상
    unassigned = [r.uid for r in records if not r.split]
    if unassigned:
        report.errors.append(_error("split_missing", len(unassigned), sorted(unassigned)))

    # 2) 같은 그룹이 여러 분할에 걸침 (external 포함)
    splits_of_group: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r.split:
            splits_of_group[gid[r.uid]].add(r.split)
    spanning = {g: sorted(s) for g, s in splits_of_group.items() if len(s) > 1}
    if spanning:
        examples = []
        for g in sorted(spanning)[:MAX_EXAMPLES]:
            members = sorted(r.uid for r in records if gid[r.uid] == g)
            examples.append({"group": g, "splits": spanning[g], "videos": members[:MAX_EXAMPLES]})
        report.errors.append(_error("group_spans_splits", len(spanning), examples))

    # 3) external과 내부 분할 사이의 겹침을 종류별로 따로 보고한다
    def overlap(values_of) -> list[str]:
        ext: set[str] = set()
        internal: set[str] = set()
        for r in records:
            target = ext if r.split == "external" else internal if r.split in INTERNAL_SPLITS else None
            if target is not None:
                target.update(v for v in values_of(r) if v)
        return sorted(ext & internal)

    for code, values_of in (
        ("source_overlap_external_internal", lambda r: [r.source_recording_id]),
        ("identity_overlap_external_internal", lambda r: r.identity_ids),
        ("file_hash_overlap_external_internal", lambda r: [r.file_hash]),
    ):
        shared = overlap(values_of)
        if shared:
            report.errors.append(_error(code, len(shared), shared))

    # 4) 같은 파일 해시가 서로 다른 분할에 있음
    splits_of_hash: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r.file_hash and r.split:
            splits_of_hash[r.file_hash].add(r.split)
    dup = sorted(h for h, s in splits_of_hash.items() if len(s) > 1)
    if dup:
        report.errors.append(_error("file_hash_spans_splits", len(dup), dup))

    # 5) 잠금 대상 데이터셋이 내부 분할에 있거나, external인데 등록되지 않음
    misplaced = sorted(r.uid for r in records if r.dataset_id in lock and r.split in INTERNAL_SPLITS)
    if misplaced:
        report.errors.append(_error("external_dataset_in_internal_split", len(misplaced), misplaced))
    unregistered = sorted({r.dataset_id for r in records if r.split == "external" and r.dataset_id not in lock})
    if unregistered:
        report.errors.append(_error("external_dataset_not_registered", len(unregistered), unregistered))

    # 경고: 실패는 아니지만 검증할 수 없었던 것. 0이어도 항목을 남긴다
    report.warnings = {
        "identity_missing": sum(1 for r in records if not r.identity_ids),
        "source_unverified": sum(1 for r in records if r.source_unverified),
        "fake_generator_missing": sum(1 for r in records if r.label == "fake" and not r.generator_id),
        "fake_manipulation_type_missing": sum(1 for r in records if r.label == "fake" and not r.manipulation_type),
        "file_hash_missing": sum(1 for r in records if not r.file_hash),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="manifest의 분할 누수를 검사한다")
    p.add_argument("manifest", type=Path, nargs="+")
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    opt = p.parse_args(argv)
    try:
        records = [r for path in opt.manifest for r in read_manifest(path)]
        report = check(records, load_lock(opt.lock))
    except (OSError, ManifestError, ValueError) as e:
        print(f"manifest를 읽지 못함: {e}", file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
