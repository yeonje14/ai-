"""manifest에 적힌 MAVOS-DD 표본 영상만 받는다. 전체(308 GB)를 받지 않는다.

research/mavos/.venv의 Python으로 실행한다. Hugging Face 접근 승인과 로그인이 필요하다.
manifest의 sha256이 docs/dataset-access.md에 적힌 값과 같을 때만 받는다(--sha256 필수).

    research/mavos/.venv/bin/python research/mavos/download_sample.py \
        --manifest data/research/mavos-dd/manifest-q20.csv --sha256 <문서에 적힌 값>

받는 위치: data/research/mavos-dd/<언어>/<폴더>/<파일>.mp4 (Git 제외)
이미 받은 파일은 건너뛴다. 끝나면 파일 수와 크기를 manifest와 대조한다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ID = "unibuc-cs/MAVOS-DD"
REVISION = "3ea7e6dbf0ed7e4f279bb8e6340bf55f0f2e55a5"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "research" / "mavos-dd"
MAX_TOTAL_BYTES = 10 * 10**9      # 저장소 소유자가 정한 한도: 표본 10 GB 이내
MIN_FREE_AFTER_BYTES = 5 * 10**9  # 받은 뒤에도 이만큼은 남아야 시작한다


def verify(rows: list[dict], data_dir: Path) -> tuple[int, int, list[str]]:
    """(있는 파일 수, 그 크기 합, 없거나 크기가 다른 경로 목록)."""
    present = 0
    total = 0
    bad: list[str] = []
    for r in rows:
        path = data_dir / r["video_path"]
        if path.is_file() and path.stat().st_size == int(r["size_bytes"]):
            present += 1
            total += path.stat().st_size
        else:
            bad.append(r["video_path"])
    return present, total, bad


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--sha256", required=True, help="docs/dataset-access.md에 적힌 manifest sha256")
    p.add_argument("--verify-only", action="store_true", help="받지 않고 대조만 한다")
    opt = p.parse_args(argv)

    data = opt.manifest.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != opt.sha256.lower():
        print(f"manifest sha256 불일치: {digest}", file=sys.stderr)
        return 2
    rows = list(csv.DictReader(data.decode("utf-8").splitlines()))
    planned = sum(int(r["size_bytes"]) for r in rows)
    if planned > MAX_TOTAL_BYTES:
        print(f"표본이 한도를 넘는다: {planned} 바이트", file=sys.stderr)
        return 2

    present, have, bad = verify(rows, DATA_DIR)
    if not opt.verify_only and bad:
        need = planned - have
        free = shutil.disk_usage(DATA_DIR).free
        if free - need < MIN_FREE_AFTER_BYTES:
            print(f"디스크 여유 부족: 남은 {free} 바이트, 필요 {need} 바이트", file=sys.stderr)
            return 2
        from huggingface_hub import snapshot_download

        print(f"받을 파일 {len(bad)}개, {need / 1e9:.2f} GB", flush=True)
        snapshot_download(
            REPO_ID, repo_type="dataset", revision=REVISION, local_dir=DATA_DIR,
            allow_patterns=bad,  # manifest의 경로만. 와일드카드 없음
        )
        present, have, bad = verify(rows, DATA_DIR)

    print(f"manifest {len(rows)}개 / {planned} 바이트, 받은 것 {present}개 / {have} 바이트, "
          f"없거나 크기가 다른 것 {len(bad)}개")
    for path in bad[:10]:
        print(f"  누락: {path}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
