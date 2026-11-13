"""공통 manifest: 데이터셋마다 다른 필드를 TRINITY 내부 공통 레코드로 맞춘다 (README §6.4).

CSV 한 줄이 영상 하나다. 표준 라이브러리만 쓴다. 영상 파일을 열지 않는다.
모르는 값은 빈칸이다. 0이나 추측값을 넣지 않는다.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

SPLITS = ("train", "dev", "test", "external")
INTERNAL_SPLITS = ("train", "dev", "test")
LABELS = ("real", "fake")
# README §6.1 위조 유형 관리. 평가용 메타데이터이며 다중분류 클래스가 아니다.
MANIPULATION_TYPES = ("A1", "A2", "A3", "B1", "B2", "C1", "C2")
IDENTITY_SEPARATOR = "|"

FIELDS = (
    "dataset_id", "video_id", "video_path", "label", "manipulation_type", "generator_id",
    "identity_ids", "source_recording_id", "parent_video_id", "derivation_group_id",
    "split", "file_hash",
)
# 원본 계보 ID(source_recording_id)는 필수다. 인물 ID는 없을 수 있다(경고로 센다).
REQUIRED = ("dataset_id", "video_id", "video_path", "label", "source_recording_id")
# 원본을 알 수 없어 파일 하나를 묶음 하나로 둔 경우의 접두사 (scripts/mavos_sample.py와 같은 규칙)
UNVERIFIED_SOURCE_PREFIX = "unknown:"


class ManifestError(ValueError):
    """manifest 형식 오류. problems에 줄 번호와 이유가 들어 있다."""

    def __init__(self, problems: list[str]):
        super().__init__(f"manifest 오류 {len(problems)}건: " + "; ".join(problems[:5]))
        self.problems = problems


@dataclass(frozen=True)
class Record:
    dataset_id: str
    video_id: str
    video_path: str
    label: str
    source_recording_id: str
    manipulation_type: str = ""
    generator_id: str = ""
    identity_ids: tuple[str, ...] = ()
    parent_video_id: str = ""
    derivation_group_id: str = ""
    split: str = ""
    file_hash: str = ""

    @property
    def uid(self) -> str:
        """데이터셋을 넘어 유일한 키."""
        return f"{self.dataset_id}:{self.video_id}"

    @property
    def source_unverified(self) -> bool:
        return self.source_recording_id.startswith(UNVERIFIED_SOURCE_PREFIX)

    def with_split(self, split: str) -> "Record":
        return replace(self, split=split)

    def to_row(self) -> dict[str, str]:
        row = {f: getattr(self, f) for f in FIELDS if f != "identity_ids"}
        row["identity_ids"] = IDENTITY_SEPARATOR.join(self.identity_ids)
        return row


def _problems_of(rec: Record) -> list[str]:
    out = []
    for f in REQUIRED:
        if not getattr(rec, f):
            out.append(f"{f} 비어 있음")
    if rec.label and rec.label not in LABELS:
        out.append(f"label은 {LABELS} 중 하나: {rec.label!r}")
    if rec.split and rec.split not in SPLITS:
        out.append(f"split은 {SPLITS} 중 하나 또는 빈칸: {rec.split!r}")
    if rec.manipulation_type and rec.manipulation_type not in MANIPULATION_TYPES:
        out.append(f"manipulation_type은 {MANIPULATION_TYPES} 중 하나 또는 빈칸: {rec.manipulation_type!r}")
    if rec.label == "real" and (rec.manipulation_type or rec.generator_id):
        out.append("real에는 manipulation_type·generator_id를 쓰지 않는다")
    return out


def validate(records: Iterable[Record]) -> list[Record]:
    """형식을 검사하고 목록으로 돌려준다. 문제가 있으면 ManifestError."""
    records = list(records)
    problems: list[str] = []
    seen: dict[str, int] = {}
    for i, rec in enumerate(records, start=2):  # CSV 기준 줄 번호(머리글이 1)
        for msg in _problems_of(rec):
            problems.append(f"{i}행: {msg}")
        if rec.uid in seen:
            problems.append(f"{i}행: {rec.uid}가 {seen[rec.uid]}행과 중복")
        seen.setdefault(rec.uid, i)
    if problems:
        raise ManifestError(problems)
    return records


def read_manifest(path: Path) -> list[Record]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in FIELDS if c not in (reader.fieldnames or [])]
        if missing:
            raise ManifestError([f"머리글에 없는 열: {missing}"])
        records = []
        for row in reader:
            ids = tuple(s for s in (row["identity_ids"] or "").split(IDENTITY_SEPARATOR) if s)
            records.append(Record(
                identity_ids=ids,
                **{f: (row[f] or "").strip() for f in FIELDS if f != "identity_ids"},
            ))
    return validate(records)


def write_manifest(path: Path, records: Iterable[Record]) -> None:
    records = validate(records)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for rec in sorted(records, key=lambda r: r.uid):
            w.writerow(rec.to_row())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
