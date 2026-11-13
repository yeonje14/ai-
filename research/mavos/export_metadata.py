"""MAVOS-DD 분할 메타데이터(arrow)와 파일 크기를 CSV 하나로 내보낸다.

research/mavos/.venv의 Python으로 실행한다(pyarrow, huggingface_hub). 영상은 받지 않는다.
Hugging Face 접근 승인과 로그인이 필요하다.

    research/mavos/.venv/bin/python research/mavos/export_metadata.py

입력: data/research/mavos-dd/data-00000-of-00001.arrow (없으면 받는다)
출력: data/research/mavos-dd/metadata.csv (Git 제외). scripts/mavos_sample.py가 읽는다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ID = "unibuc-cs/MAVOS-DD"
# 2026-11-13에 확인한 저장소 커밋. 표본 목록을 다시 만들 때 같은 파일 목록을 쓰기 위해 고정한다.
REVISION = "3ea7e6dbf0ed7e4f279bb8e6340bf55f0f2e55a5"
ARROW_NAME = "data-00000-of-00001.arrow"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "research" / "mavos-dd"
FIELDS = (
    "video_path", "label", "split", "open_set_model", "open_set_language", "language",
    "generative_method", "audio_generative_method", "audio_fake", "video_fake", "size_bytes",
)


def main() -> int:
    import pyarrow as pa
    from huggingface_hub import HfApi, hf_hub_download

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    arrow_path = DATA_DIR / ARROW_NAME
    if not arrow_path.is_file():
        hf_hub_download(REPO_ID, ARROW_NAME, repo_type="dataset", revision=REVISION, local_dir=DATA_DIR)

    with pa.memory_map(str(arrow_path)) as f:
        try:
            table = pa.ipc.open_stream(f).read_all()
        except pa.ArrowInvalid:
            table = pa.ipc.open_file(f).read_all()
    rows = table.to_pylist()

    sizes = {
        item.path: item.size
        for item in HfApi().list_repo_tree(REPO_ID, repo_type="dataset", revision=REVISION, recursive=True)
        if getattr(item, "size", None) is not None
    }
    missing = [r["video_path"] for r in rows if r["video_path"] not in sizes]
    if missing:
        print(f"크기를 찾지 못한 경로 {len(missing)}개. 예: {missing[:3]}", file=sys.stderr)
        return 1

    rows.sort(key=lambda r: r["video_path"])
    out = DATA_DIR / "metadata.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({**{k: r[k] for k in FIELDS[:-1]}, "size_bytes": sizes[r["video_path"]]})
    total = sum(sizes[r["video_path"]] for r in rows)
    print(f"{out}: {len(rows)}행, 영상 합계 {total} 바이트 ({total / 1e9:.1f} GB), 저장소 커밋 {REVISION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
