"""데이터셋 메타데이터 → 공통 manifest (README §6.4). 표준 라이브러리만 쓴다.

데이터셋마다 다른 필드 이름은 configs/datasets/<이름>.json에 둔다. 코드에는 필드 이름을 적지 않는다.
설정의 evidence가 "card"인 필드는 공개 데이터셋 카드에 적힌 것이고, "unconfirmed"는 확인하지 못한 자리다.
status가 "unconfirmed"인 설정(필드를 확인하지 못한 데이터셋)은 변환을 거부한다.

입력 행은 JSON Lines(한 줄에 영상 하나의 메타데이터)다. 영상 파일을 열지 않는다.
실제 데이터로 돌린 적이 없다. 접근 승인 후 첫 행을 열어 설정을 확인한다(docs/training-pipeline.md).

    python -m training.datasets.adapters --config configs/datasets/deepspeak_v2.json \
        --rows data/research/deepspeak_v2/metadata.jsonl --out data/research/deepspeak_v2/manifest.csv
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

from training import hygiene
from training.datasets import groups
from training.datasets.manifest import (
    IDENTITY_SEPARATOR, MANIPULATION_TYPES, UNVERIFIED_SOURCE_PREFIX, ManifestError, Record, write_manifest,
)
from training.evaluation.lock import DEFAULT_LOCK_PATH, load_lock

CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs" / "datasets"
USABLE_STATUSES = ("card_only", "verified")  # verified: 실제 행으로 확인한 뒤에 쓴다


class AdapterError(ValueError):
    """설정이 불완전하거나 행을 공통 레코드로 바꿀 수 없다."""


def load_config(path: Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("status") not in USABLE_STATUSES:
        raise AdapterError(
            f"{config.get('dataset_id')!r}: 필드를 확인하지 않은 데이터셋이다(status={config.get('status')!r}). "
            "공개 정보를 확인해 설정을 채우기 전에는 변환하지 않는다")
    for key in ("dataset_id", "fields", "split"):
        if not config.get(key):
            raise AdapterError(f"설정에 {key}가 없다")
    for name in ("video_path", "label"):
        if not (config["fields"].get(name) or {}).get("paths"):
            raise AdapterError(f"설정의 fields.{name}.paths가 비어 있다")
    return config


def unconfirmed_fields(config: dict) -> list[str]:
    return sorted(k for k, v in config["fields"].items() if v.get("evidence") != "card")


def _get(row: dict, spec: Optional[dict]) -> Any:
    """설정의 paths 가운데 처음 찾은 값. 없으면 None."""
    for path in (spec or {}).get("paths", []):
        cur: Any = row
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur is not None and cur != "":
            return cur
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _id_text(value: Any) -> str:
    """인물·녹화 ID. 결측이 섞인 정수 열은 JSON Lines로 내보낼 때 12.0이 되므로 12로 맞추고,
    NaN·무한대는 값이 아닌 것으로 본다(같은 인물이 다른 그룹이 되거나 결측끼리 한 그룹이 되지 않게, 감사 A12)."""
    if isinstance(value, float) and not isinstance(value, bool):
        if not math.isfinite(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return _text(value)


def to_record(row: dict, config: dict, line: int) -> tuple[Record, str]:
    """(분할이 빈 레코드, 공식 분할 이름). 필수 값이 없으면 AdapterError."""
    f = config["fields"]
    ns = config.get("identity_namespace") or config["dataset_id"]
    path = _text(_get(row, f["video_path"]))
    raw_label = _text(_get(row, f["label"]))
    label = (f["label"].get("values") or {}).get(raw_label)
    if not path or label is None:
        raise AdapterError(f"{line}행: 영상 경로 또는 라벨을 읽지 못했다(label={raw_label!r})")
    video_id = _text(_get(row, f.get("video_id"))) or path
    official = _text(_get(row, f.get("official_split")))

    def ident(value: Any) -> str:
        return f"{ns}:id:{_id_text(value)}" if _id_text(value) else ""

    def recording(value: Any) -> str:
        return f"{ns}:rec:{_id_text(value)}" if _id_text(value) else ""

    if label == "real":
        ids = [ident(_get(row, f.get("real_identity")))]
        source = recording(_get(row, f.get("real_recording")))
        manipulation = generator = ""
    else:
        ids = [ident(_get(row, f.get("fake_identity_source"))), ident(_get(row, f.get("fake_identity_target")))]
        source = recording(_get(row, f.get(config.get("fake_source_recording") or "")))
        generator = _text(_get(row, f.get("fake_engine")))
        gen_config = _text(_get(row, f.get("fake_gen_config")))
        if gen_config and generator:
            generator = f"{generator}/{gen_config}"
        manipulation = _manipulation_type(_text(_get(row, f.get("fake_kind"))), gen_config, config)
    ids = tuple(dict.fromkeys(i for i in ids if i))
    return Record(
        dataset_id=config["dataset_id"], video_id=video_id, video_path=path, label=label,
        # 원본을 알 수 없으면 추측하지 않고 "묶을 수 없는 영상"으로 드러낸다
        source_recording_id=source or f"{UNVERIFIED_SOURCE_PREFIX}{path}",
        manipulation_type=manipulation, generator_id=generator, identity_ids=ids,
    ), official


def _manipulation_type(kind: str, gen_config: str, config: dict) -> str:
    mapping = config.get("manipulation_type") or {}
    value = (mapping.get("by_kind") or {}).get(kind, "")
    if kind == "face-swap" and any(m in gen_config for m in mapping.get("face_swap_restored_markers", [])):
        value = mapping.get("face_swap_restored_type", value)
    if value and value not in MANIPULATION_TYPES:
        raise AdapterError(f"설정의 manipulation_type 대응이 잘못됐다: {value!r}")
    return value


def convert(rows: Iterable[dict], config: dict) -> list[Record]:
    """행 → 분할이 정해진 공통 레코드. 공식 test는 test, 공식 train은 그룹 단위로 train/dev."""
    split_cfg = config["split"]
    records, official = [], {}
    for line, row in enumerate(rows, start=1):
        rec, off = to_record(row, config, line)
        if off not in (split_cfg["official_test_value"], split_cfg["official_train_value"]):
            raise AdapterError(f"{line}행: 공식 분할을 읽지 못했다({off!r}). 내보낼 때 분할 열을 붙인다")
        records.append(rec)
        official[rec.uid] = off
    if len(official) != len(records):
        raise AdapterError("video_id가 겹친다. 설정의 fields.video_id를 확인한다")
    train = [r for r in records if official[r.uid] == split_cfg["official_train_value"]]
    test = [r.with_split("test") for r in records if official[r.uid] == split_cfg["official_test_value"]]
    assigned = groups.assign_splits(train, split_cfg["train_fractions"], split_cfg["seed"]) if train else []
    return assigned + test


def summarize(records: list[Record], config: dict, lock: dict) -> dict:
    report = hygiene.check(records, lock)
    return {
        "dataset_id": config["dataset_id"], "config_status": config["status"],
        "unconfirmed_fields": unconfirmed_fields(config),
        "manipulation_type_provisional": bool((config.get("manipulation_type") or {}).get("provisional")),
        "videos": len(records),
        "by_split_label": dict(sorted(Counter(f"{r.split}/{r.label}" for r in records).items())),
        "hygiene": report.to_dict(),
        "group_sizes": groups.size_summary(records),
    }


def read_rows(path: Path) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise AdapterError(f"{n}행: JSON 객체가 아니다")
                rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--rows", type=Path, required=True, help="메타데이터 JSON Lines")
    p.add_argument("--out", type=Path, required=True, help="공통 manifest CSV")
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    opt = p.parse_args(argv)
    try:
        config = load_config(opt.config)
        records = convert(read_rows(opt.rows), config)
        summary = summarize(records, config, load_lock(opt.lock))
    except (AdapterError, ManifestError, OSError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not summary["hygiene"]["ok"]:
        # 공식 분할이 그룹을 쪼갠다. 조용히 다시 나누지 않는다
        print("누수 검사 실패. manifest를 쓰지 않는다", file=sys.stderr)
        return 1
    write_manifest(opt.out, records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
