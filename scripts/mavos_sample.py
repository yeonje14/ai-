"""MAVOS-DD open-set model 분할의 표본 목록(manifest)을 만든다.

규칙과 숫자는 docs/dataset-access.md "표본 추출 규칙"에 고정되어 있다(2026-11-13 승인).
이 스크립트는 메타데이터만 읽는다. 영상을 받지 않고, 모델을 실행하지 않는다.
표준 라이브러리만 쓴다.

입력: research/mavos/export_metadata.py가 만든 CSV (data/research/mavos-dd/metadata.csv)
출력: data/research/mavos-dd/manifest-q<층당 개수>.csv (Git 제외)와 그 sha256

사용 (저장소 루트, conda trinity):
    python scripts/mavos_sample.py                       # 승인된 값(층당 20개)
    python scripts/mavos_sample.py --per-stratum 25      # 나중에 늘릴 때. 20개 목록을 포함한다

같은 시드에서는 층당 개수를 늘려도 이미 뽑힌 영상이 빠지지 않는다. 층마다 순서가
(원본 묶음의 해시, 경로의 해시)로 고정되어 있고 앞에서부터 자르기 때문이다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "research" / "mavos-dd"

# docs/dataset-access.md에 고정한 값 (2026-11-13 승인)
SEED = 20261113
PER_STRATUM = 20        # 가짜: (폴더, 언어) 층마다. 폴더당 상한 = 20 × 언어 6 = 120
MAX_PER_SOURCE = 2      # 한 층에서 같은 원본 묶음의 클립 수 상한
REAL_RATIO = 1.0        # 진짜 : 가짜

MANIFEST_FIELDS = (
    "video_path", "label", "category", "language", "open_set_model",
    "audio_fake", "video_fake", "source_group", "size_bytes",
)

# 진짜 영상의 파일 이름: <11자 ID>_<숫자>_<숫자>[...].mp4
_REAL_NAME = re.compile(r"^([A-Za-z0-9_-]{11})_\d+_\d+(?:_.*)?\.mp4$")
# 다른 폴더의 파일 이름 안에서 ID 후보를 찾는다(겹치는 위치 포함)
_CANDIDATE = re.compile(r"(?=([A-Za-z0-9_-]{11})_\d+(?:_\d+)?)")
_COMMON_VOICE = re.compile(r"(common_voice_[A-Za-z-]+_\d+)")


def category_of(video_path: str) -> str:
    """경로 `<언어>/<폴더>/<파일>`의 폴더. 생성기 이름 또는 real."""
    return video_path.split("/")[1]


def known_source_ids(rows: Iterable[dict]) -> set[str]:
    """데이터셋 전체의 real 폴더 파일 이름에서 얻은 원본 영상 ID 집합."""
    known: set[str] = set()
    for r in rows:
        _, folder, name = r["video_path"].split("/", 2)
        if folder == "real":
            m = _REAL_NAME.match(name)
            if m:
                known.add(m.group(1))
    return known


def source_group(video_path: str, known: set[str]) -> str:
    """같은 원본에서 나온 클립을 묶는 키. 파일 이름에서 추정한다(게시자 문서에 규칙 없음).

    yt:<ID>       이름 안에서 처음 나오는, real 폴더에서 확인된 11자 ID
    cv:<이름>     Common Voice 음성 ID만 있는 경우
    unknown:<경로> 식별자가 없는 경우. 파일 하나가 묶음 하나다
    """
    name = video_path.split("/", 2)[2]
    for m in _CANDIDATE.finditer(name):
        if m.group(1) in known:
            return "yt:" + m.group(1)
    m = _COMMON_VOICE.search(name)
    if m:
        return "cv:" + m.group(1)
    return "unknown:" + video_path


def is_open_set_model_split(row: dict) -> bool:
    """데이터셋 카드의 조건: in-domain 테스트 + 처음 보는 생성기 추가분."""
    return row["split"] == "test" and not _as_bool(row["open_set_language"])


def _as_bool(v) -> bool:
    return v is True or str(v).lower() == "true"


def _rank(seed: int, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()


def draw(
    rows: list[dict],
    seed: int = SEED,
    per_stratum: int = PER_STRATUM,
    max_per_source: int = MAX_PER_SOURCE,
    real_ratio: float = REAL_RATIO,
) -> tuple[list[dict], dict[tuple[str, str], tuple[int, int]]]:
    """표본 행 목록(경로순)과 모자란 층 {(범주, 언어): (뽑은 수, 배정 수)}을 돌려준다.

    층: 가짜는 (폴더, 언어), 진짜는 (real, 언어).
    층 안의 순서: 원본 묶음을 sha256("<시드>:<묶음>") 오름차순으로, 묶음 안의 클립을
    sha256("<시드>:<경로>") 오름차순으로 놓고 묶음마다 앞의 max_per_source개만 남긴다.
    그 순서의 앞에서부터 배정 수만큼 뽑는다. 모자라면 있는 만큼만 쓴다.
    진짜의 층당 배정 수 = per_stratum × 가짜 폴더 수 × real_ratio (반올림).
    """
    if per_stratum < 1 or max_per_source < 1 or real_ratio <= 0:
        raise ValueError("per_stratum, max_per_source는 1 이상, real_ratio는 양수여야 한다")
    known = known_source_ids(rows)
    strata: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not is_open_set_model_split(r):
            continue
        cat = "real" if r["label"] == "real" else category_of(r["video_path"])
        strata[(cat, r["language"])][source_group(r["video_path"], known)].append(r)

    fake_categories = sorted({cat for cat, _ in strata if cat != "real"})
    real_quota = round(per_stratum * len(fake_categories) * real_ratio)

    picked: list[dict] = []
    short: dict[tuple[str, str], tuple[int, int]] = {}
    for key in sorted(strata):
        quota = real_quota if key[0] == "real" else per_stratum
        ordered: list[tuple[str, dict]] = []
        for group in sorted(strata[key], key=lambda g: _rank(seed, g)):
            clips = sorted(strata[key][group], key=lambda r: _rank(seed, r["video_path"]))
            ordered += [(group, r) for r in clips[:max_per_source]]
        chosen = ordered[:quota]
        if len(chosen) < quota:
            short[key] = (len(chosen), quota)
        for group, r in chosen:
            picked.append({
                "video_path": r["video_path"],
                "label": r["label"],
                "category": key[0],
                "language": r["language"],
                "open_set_model": str(_as_bool(r["open_set_model"])).lower(),
                "audio_fake": str(_as_bool(r["audio_fake"])).lower(),
                "video_fake": str(_as_bool(r["video_fake"])).lower(),
                "source_group": group,
                "size_bytes": int(r["size_bytes"]),
            })
    picked.sort(key=lambda r: r["video_path"])
    return picked, short


def manifest_bytes(picked: list[dict]) -> bytes:
    """manifest CSV의 바이트(UTF-8, LF). sha256은 이 바이트로 계산한다."""
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(picked)
    return buf.getvalue().encode("utf-8")


def summarize(picked: list[dict]) -> dict:
    by_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in picked:
        by_cat[r["category"]][0] += 1
        by_cat[r["category"]][1] += r["size_bytes"]
    return {
        "videos": len(picked),
        "real": sum(1 for r in picked if r["label"] == "real"),
        "fake": sum(1 for r in picked if r["label"] == "fake"),
        "bytes": sum(r["size_bytes"] for r in picked),
        "source_groups": len({r["source_group"] for r in picked}),
        "by_category": {k: tuple(v) for k, v in sorted(by_cat.items())},
    }


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--metadata", type=Path, default=DATA_DIR / "metadata.csv")
    p.add_argument("--per-stratum", type=int, default=PER_STRATUM)
    p.add_argument("--out", type=Path, default=None, help="기본: data/research/mavos-dd/manifest-q<N>.csv")
    opt = p.parse_args(argv)

    if not opt.metadata.is_file():
        print(f"파일 없음: {opt.metadata} (research/mavos/export_metadata.py를 먼저 실행)", file=sys.stderr)
        return 2
    rows = load_rows(opt.metadata)
    picked, short = draw(rows, per_stratum=opt.per_stratum)
    data = manifest_bytes(picked)
    out = opt.out or DATA_DIR / f"manifest-q{opt.per_stratum}.csv"
    out.write_bytes(data)

    s = summarize(picked)
    print(f"manifest: {out}")
    print(f"sha256: {hashlib.sha256(data).hexdigest()}")
    print(f"시드 {SEED}, 층당 {opt.per_stratum}, 원본당 {MAX_PER_SOURCE}, 진짜:가짜 {REAL_RATIO}")
    print(f"영상 {s['videos']} (진짜 {s['real']}, 가짜 {s['fake']}), "
          f"{s['bytes']} 바이트 ({s['bytes'] / 1e9:.2f} GB), 원본 묶음 {s['source_groups']}")
    for cat, (n, b) in s["by_category"].items():
        print(f"  {cat}: {n}개, {b / 1e9:.2f} GB")
    print(f"모자란 층: {short if short else '없음'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
