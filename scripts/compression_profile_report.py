"""허가된 영상 하나에 범용 압축 프로파일 전부를 적용하고 출력을 비교한다 (백로그 9번).

    python scripts/compression_profile_report.py --video data/research/samples/<허가 영상>.mp4

프로파일마다 두 번 인코딩해 해시가 같은지 확인하고, 해상도·비트레이트·크기를 표로 낸다.
결과는 <out-dir>/report.json에 쓴다. 변환본은 Git에 넣지 않는다(data/ 아래).
실제 YouTube의 재인코딩과 같다고 주장하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.emulator.profiles import PROFILES  # noqa: E402
from training.emulator.video import emulate  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", type=Path, required=True, help="권한이 확인된 영상")
    p.add_argument("--out-dir", type=Path, default=ROOT / "data/research/emulator/profile-report")
    opt = p.parse_args()
    if opt.out_dir.exists():
        print(f"오류: 출력 폴더가 이미 있다. 덮어쓰지 않는다: {opt.out_dir}", file=sys.stderr)
        return 1

    rows = []
    for pid in PROFILES:
        t0 = time.perf_counter()
        first = emulate(opt.video, pid, opt.out_dir / "run1")
        seconds = time.perf_counter() - t0
        second = emulate(opt.video, pid, opt.out_dir / "run2")
        out = first["output"]
        rows.append({
            "profile_id": pid, "status": first["status"], "reason": first["reason"],
            "output": out, "encode_seconds": round(seconds, 2),
            "identical_on_rerun": (first == second) if out else None,
            "ffmpeg_args": first["ffmpeg_args"],
        })
        if second["output"]:  # 두 번째 출력은 비교가 끝나면 지운다
            (opt.out_dir / "run2" / second["output"]["name"]).unlink()
    report = {
        "note": "범용 압축 프로파일의 출력 비교다. 성능 결과가 아니며 실제 YouTube 재인코딩과 같다고 주장하지 않는다.",
        "ffmpeg_version": first["ffmpeg_version"], "input": first["input"], "profiles": rows,
    }
    (opt.out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    src = report["input"]
    print(f"입력: {src['codec']} {src['width']}×{src['height']}, {src['size_bytes']:,}바이트, sha256 {src['sha256'][:12]}…")
    print("| 프로파일 | 상태 | 해상도 | 영상 비트레이트 | 크기 | sha256 | 재실행 동일 | 인코딩 시간 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        o = r["output"]
        if o:
            print(f"| `{r['profile_id']}` | {r['status']} | {o['width']}×{o['height']} | "
                  f"{o['video_bit_rate'] / 1000:,.0f} kbps | {o['size_bytes']:,}바이트 | `{o['sha256'][:12]}…` | "
                  f"{'예' if r['identical_on_rerun'] else '아니오'} | {r['encode_seconds']}초 |")
        else:
            print(f"| `{r['profile_id']}` | {r['status']} | – | – | – | – | – | – |")
    return 0 if all(r["identical_on_rerun"] is not False and r["status"] != "error" for r in rows) else 2


if __name__ == "__main__":
    sys.exit(main())
