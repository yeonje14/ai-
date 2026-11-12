"""WaveRep 단독 추론 스파이크 실행기 (README §14.1 백로그 5번).

원본 저장소의 demo/main_avideo.py를 수정 없이 서브프로세스로 실행하고,
실행 시간·최대 메모리·프레임 점수 요약을 JSON으로 남긴다.
실행 가능성 확인용이다. 점수(logit)를 진위로 해석하지 않는다.

사용 (저장소 루트에서):
    research/waverep/.venv/bin/python research/waverep/run_spike.py \
        --video data/research/samples/<파일>.mp4 --device cpu --tag cpu-1 [--limit 8]

출력은 data/research/waverep-spike/ (Git 밖)에 쓴다.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DEMO_DIR = HERE / "upstream" / "demo"
DEFAULT_WEIGHTS = DEMO_DIR / "weights" / "weights_dinov2_G4.ckpt"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "research" / "waverep-spike"
ALLOWED_DEVICES = ("cpu", "mps")
TIME_BIN = "/usr/bin/time"


def build_command(
    python: str, video: Path, csv_out: Path, weights: Path, device: str, limit: int | None
) -> list[str]:
    """인자 리스트만 만든다(셸 문자열 없음). CUDA는 받지 않는다."""
    if device not in ALLOWED_DEVICES:
        raise ValueError(f"device는 {ALLOWED_DEVICES} 중 하나여야 한다: {device!r}")
    cmd = [
        TIME_BIN, "-l", python, "main_avideo.py",
        "--video_input", str(video),
        "--csv_output", str(csv_out),
        "--weights", str(weights),
        "--device", device,
    ]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    return cmd


def parse_time_l(stderr: str) -> dict[str, int | None]:
    """macOS `/usr/bin/time -l` 출력에서 바이트 단위 메모리 값을 읽는다. 없으면 None."""
    def grab(label: str) -> int | None:
        m = re.search(rf"^\s*(\d+)\s+{re.escape(label)}\s*$", stderr, re.MULTILINE)
        return int(m.group(1)) if m else None

    return {
        "max_rss_bytes": grab("maximum resident set size"),
        "peak_footprint_bytes": grab("peak memory footprint"),
    }


def read_logits(csv_path: Path) -> list[float]:
    with open(csv_path, newline="") as f:
        return [float(row["logit"]) for row in csv.DictReader(f)]


def summarize_logits(logits: list[float]) -> dict[str, float | int | None]:
    """원시 logit 요약. 값이 없으면 0이 아니라 None이다."""
    if not logits:
        return {"frames": 0, "mean": None, "median": None, "min": None, "max": None, "stdev": None}
    return {
        "frames": len(logits),
        "mean": statistics.fmean(logits),
        "median": statistics.median(logits),
        "min": min(logits),
        "max": max(logits),
        "stdev": statistics.pstdev(logits),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--video", required=True, type=Path)
    p.add_argument("--device", required=True, choices=ALLOWED_DEVICES)
    p.add_argument("--tag", required=True, help="출력 파일 이름에 쓸 실행 이름 (예: cpu-1)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    opt = p.parse_args(argv)

    if not re.fullmatch(r"[A-Za-z0-9_-]+", opt.tag):
        p.error("--tag는 영문·숫자·-·_만 쓴다")
    video = opt.video.resolve()
    weights = opt.weights.resolve()
    for path in (video, weights, DEMO_DIR / "main_avideo.py"):
        if not path.is_file():
            print(f"파일 없음: {path}", file=sys.stderr)
            return 2
    out_dir = opt.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_out = out_dir / f"{opt.tag}.csv"
    csv_out.unlink(missing_ok=True)

    env = dict(os.environ)
    if opt.device == "mps":
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    cmd = build_command(sys.executable, video, csv_out, weights, opt.device, opt.limit)

    started = time.perf_counter()
    done = subprocess.run(cmd, cwd=DEMO_DIR, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - started

    logits = read_logits(csv_out) if done.returncode == 0 and csv_out.is_file() else []
    summary = {
        "tag": opt.tag,
        "device": opt.device,
        "limit": opt.limit,
        "returncode": done.returncode,
        "wall_seconds": round(wall, 2),
        **parse_time_l(done.stderr),
        "mps_fallback_env": env.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        "logit_summary": summarize_logits(logits),
        "stdout_tail": done.stdout.strip().splitlines()[-3:],
        # tqdm 진행 줄(\r)은 버리고 마지막 줄들만 남긴다.
        "stderr_tail": [ln.split("\r")[-1] for ln in done.stderr.strip().splitlines()[-25:]],
    }
    (out_dir / f"{opt.tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
