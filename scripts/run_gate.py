"""허가 미디어 파일 하나에 Gate를 돌리고 결과 JSON을 출력한다 (개발용 확인 도구).

사용자 입력 경로가 아니다. 저장소 소유자가 허가 미디어 경로를 직접 넘긴다.
실행: python scripts/run_gate.py data/research/samples/<파일>.mp4
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.gate import run_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    result = run_gate(args.media)
    out = result.to_dict()
    out["elapsed_sec"] = round(time.perf_counter() - started, 2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
