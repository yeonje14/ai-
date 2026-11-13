"""MAVOS-DD 표본을 공통 manifest로 바꾸고 메타데이터만 검사한다 (추론하지 않는다).

MAVOS-DD open-set model 분할의 표본은 최종 외부 평가 전용이다(README §15.3 결정 6,
configs/external_eval_lock.json). 여기서는 영상을 열지 않는다. 경로, 크기, 목록의 sha256,
층별 개수만 본다.

    python -m training.datasets.mavos check
    python -m training.datasets.mavos check --write-common data/research/mavos-dd/common-manifest.csv

종료 코드: 0 통과, 1 검사 실패, 2 파일 없음.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from scripts import mavos_sample
from training.datasets.manifest import Record, write_manifest
from training.evaluation.lock import DEFAULT_LOCK_PATH, load_lock

DATASET_ID = "mavos-dd"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "research" / "mavos-dd"
MAX_TOTAL_BYTES = 10 * 10**9

# 잠정 대응이다(2026-11-13). MAVOS-DD의 폴더(생성기)를 README §6.1의 A1~C2에 맞춘 판단이며
# 게시자의 분류가 아니다. 결과 보고는 생성기별을 기본으로 하고 유형별은 보조로만 쓴다.
MANIPULATION_TYPE_PROVISIONAL = True
MANIPULATION_TYPE_BY_GENERATOR = {
    "echomimic": "A1",     # 초상 이미지 + 음성 → 토킹헤드
    "memo": "A1",
    "sonic": "A1",
    "liveportrait": "A1",  # 초상 애니메이션
    "hififace": "C1",      # 얼굴 교체
    "roop": "C1",
    "inswapper": "C2",     # 얼굴 교체 + GFPGAN 보정 (논문)
    "freevc": "B1",        # 음성만 변환. 화면은 진짜
    "knnvc": "B1",
}


def read_sample_manifest(path: Path) -> tuple[list[dict], str]:
    data = Path(path).read_bytes()
    rows = list(csv.DictReader(data.decode("utf-8").splitlines()))
    return rows, hashlib.sha256(data).hexdigest()


def to_records(rows: list[dict]) -> list[Record]:
    """표본 목록의 행을 공통 레코드로. 인물 ID는 MAVOS-DD에 없어 비워 둔다."""
    records = []
    for row in rows:
        fake = row["label"] == "fake"
        generator = row["category"] if fake else ""
        records.append(Record(
            dataset_id=DATASET_ID,
            video_id=row["video_path"],
            video_path=row["video_path"],
            label=row["label"],
            manipulation_type=MANIPULATION_TYPE_BY_GENERATOR.get(generator, "") if fake else "",
            generator_id=generator,
            identity_ids=(),
            # 파일 이름에서 추정한 원본 묶음. 식별자가 없으면 "unknown:<경로>"
            source_recording_id=row["source_group"],
            split="external",
            file_hash="",  # 영상을 읽지 않으므로 계산하지 않는다
        ))
    return records


def check_sample(rows: list[dict], sha256: str, lock: dict[str, dict], data_dir: Path = DATA_DIR) -> dict:
    """표본이 고정한 규칙·잠금과 맞는지 본다. problems가 비어 있으면 통과."""
    problems: list[str] = []
    entry = lock.get(DATASET_ID)
    if entry is None:
        problems.append("lock 파일에 mavos-dd가 없다")
    elif entry.get("manifest_sha256") != sha256:
        problems.append("표본 목록의 sha256이 lock 파일에 적힌 값과 다르다")

    paths = [r["video_path"] for r in rows]
    if len(paths) != len(set(paths)):
        problems.append("표본 목록에 같은 경로가 두 번 있다")

    per_stratum: dict[tuple[str, str], int] = defaultdict(int)
    per_source: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in rows:
        per_stratum[(r["category"], r["language"])] += 1
        per_source[(r["category"], r["language"], r["source_group"])] += 1
        if (r["label"] == "real") != (r["category"] == "real"):
            problems.append(f"라벨과 범주가 어긋난다: {r['video_path']}")
    fake_categories = sorted({c for c, _ in per_stratum if c != "real"})
    real_quota = round(mavos_sample.PER_STRATUM * len(fake_categories) * mavos_sample.REAL_RATIO)
    over = {f"{c}/{lang}": n for (c, lang), n in per_stratum.items()
            if n > (real_quota if c == "real" else mavos_sample.PER_STRATUM)}
    if over:
        problems.append(f"층당 개수를 넘는 층: {over}")
    if per_source and max(per_source.values()) > mavos_sample.MAX_PER_SOURCE:
        problems.append("한 층에서 같은 원본 묶음이 상한보다 많이 뽑혔다")

    total = sum(int(r["size_bytes"]) for r in rows)
    if total > MAX_TOTAL_BYTES:
        problems.append(f"표본이 10 GB를 넘는다: {total}")

    present = sum(1 for r in rows if (data_dir / r["video_path"]).is_file())
    wrong_size = sum(
        1 for r in rows
        if (data_dir / r["video_path"]).is_file()
        and (data_dir / r["video_path"]).stat().st_size != int(r["size_bytes"])
    )
    if wrong_size:
        problems.append(f"크기가 목록과 다른 파일 {wrong_size}개")

    return {
        "ok": not problems,
        "problems": problems,
        "manifest_sha256": sha256,
        "lock_status": entry.get("status") if entry else None,
        "videos": len(rows),
        "real": sum(1 for r in rows if r["label"] == "real"),
        "fake": sum(1 for r in rows if r["label"] == "fake"),
        "bytes": total,
        "strata": len(per_stratum),
        "source_groups": len({r["source_group"] for r in rows}),
        "source_unverified": sum(1 for r in rows if r["source_group"].startswith("unknown:")),
        "files_present": present,
        "files_missing": len(rows) - present,
        "manipulation_type_provisional": MANIPULATION_TYPE_PROVISIONAL,
        "inference_run": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MAVOS-DD 표본의 메타데이터 검사 (추론 없음)")
    p.add_argument("command", choices=["check"])
    p.add_argument("--manifest", type=Path, default=DATA_DIR / f"manifest-q{mavos_sample.PER_STRATUM}.csv")
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    p.add_argument("--write-common", type=Path, default=None, help="공통 manifest CSV로도 쓴다 (Git 밖 경로)")
    opt = p.parse_args(argv)
    if not opt.manifest.is_file():
        print(f"파일 없음: {opt.manifest}", file=sys.stderr)
        return 2
    rows, sha256 = read_sample_manifest(opt.manifest)
    result = check_sample(rows, sha256, load_lock(opt.lock))
    if opt.write_common:
        write_manifest(opt.write_common, to_records(rows))
        result["common_manifest"] = str(opt.write_common)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
