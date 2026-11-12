"""WaveRep 어댑터 비교 측정 (README §14.1 백로그 7번의 앞부분).

같은 영상으로 "모든 프레임"과 샘플링 설정별 실행 시간·메모리·점수 요약을 기록하고,
배치·pretrained·기존 스파이크 결과와의 프레임 점수 차이를 계산한다.
속도·재현성 확인이다. 성능 검증이 아니며 점수를 판정에 쓰지 않는다.

사용 (저장소 루트, conda trinity):
    python scripts/bench_waverep_adapter.py --video data/research/samples/<파일>.mp4
    python scripts/bench_waverep_adapter.py --video ... --only mps-all-b8 --force
    python scripts/bench_waverep_adapter.py --video ... --compare-only

실행은 하나씩 순차로 한다. 결과는 data/research/waverep-adapter/ (Git 밖)에 쓴다.
이미 결과 파일이 있는 실행은 --force가 없으면 건너뛴다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.axes.signal.waverep import WaveRepConfig, run_waverep  # noqa: E402

DEFAULT_OUT_DIR = REPO_ROOT / "data" / "research" / "waverep-adapter"
SPIKE_CSV = REPO_ROOT / "data" / "research" / "waverep-spike" / "cpu-1.csv"

# (tag, device, sample_fps, batch_size, pretrained)
RUNS: list[tuple[str, str, float | None, int, bool]] = [
    ("cpu-all-b1-pretrained", "cpu", None, 1, True),
    ("cpu-all-b1", "cpu", None, 1, False),
    ("cpu-all-b8", "cpu", None, 8, False),
    ("cpu-all-b8-r2", "cpu", None, 8, False),
    ("mps-all-b1", "mps", None, 1, False),
    ("mps-all-b8", "mps", None, 8, False),
    ("mps-all-b8-r2", "mps", None, 8, False),
    ("mps-all-b16", "mps", None, 16, False),
    ("cpu-fps1-b8", "cpu", 1, 8, False),
    ("cpu-fps2-b8", "cpu", 2, 8, False),
    ("cpu-fps4-b8", "cpu", 4, 8, False),
    ("mps-fps1-b8", "mps", 1, 8, False),
    ("mps-fps2-b8", "mps", 2, 8, False),
    ("mps-fps4-b8", "mps", 4, 8, False),
]
# (비교할 실행, 기준 실행). 같은 프레임 번호끼리 logit 차이를 본다.
PAIRS: list[tuple[str, str]] = [
    ("cpu-all-b1-pretrained", "spike:cpu-1"),
    ("cpu-all-b1", "cpu-all-b1-pretrained"),
    ("cpu-all-b8", "cpu-all-b1"),
    ("cpu-all-b8-r2", "cpu-all-b8"),
    ("mps-all-b1", "cpu-all-b1"),
    ("mps-all-b8", "mps-all-b1"),
    ("mps-all-b8-r2", "mps-all-b8"),
    ("mps-all-b16", "mps-all-b1"),
    ("cpu-fps1-b8", "cpu-all-b8"),
    ("cpu-fps2-b8", "cpu-all-b8"),
    ("cpu-fps4-b8", "cpu-all-b8"),
    ("mps-fps1-b8", "mps-all-b8"),
    ("mps-fps2-b8", "mps-all-b8"),
    ("mps-fps4-b8", "mps-all-b8"),
]


def load_logits(out_dir: Path, name: str) -> dict[int, float] | None:
    """실행 결과(또는 스파이크 CSV)에서 {프레임 번호: logit}. 없거나 실패한 실행이면 None."""
    if name.startswith("spike:"):
        if not SPIKE_CSV.is_file():
            return None
        with SPIKE_CSV.open(newline="") as f:
            return {int(r["index"]): float(r["logit"]) for r in csv.DictReader(f)}
    path = out_dir / f"{name}.json"
    if not path.is_file():
        return None
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") != "completed":
        return None
    return {f["index"]: f["logit"] for f in result["frames"]}


def compare(a: dict[int, float], b: dict[int, float]) -> dict:
    """a의 프레임이 모두 b에 있어야 비교한다. 빠진 프레임이 있으면 차이는 None."""
    missing = sorted(set(a) - set(b))
    if missing or not a:
        return {"frames": len(a), "missing_in_reference": len(missing),
                "max_abs_diff": None, "mean_abs_diff": None, "sign_changes": None}
    diffs = [abs(a[i] - b[i]) for i in a]
    return {
        "frames": len(a),
        "missing_in_reference": 0,
        "max_abs_diff": max(diffs),
        "mean_abs_diff": sum(diffs) / len(diffs),
        "sign_changes": sum(1 for i in a if (a[i] > 0) != (b[i] > 0)),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--video", type=Path, required=True, help="허가된 테스트 영상")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--only", action="append", help="이 tag만 실행 (여러 번 줄 수 있다)")
    p.add_argument("--force", action="store_true", help="결과가 있어도 다시 실행")
    p.add_argument("--compare-only", action="store_true", help="실행하지 않고 비교만 다시 계산")
    p.add_argument("--timeout", type=float, default=1800.0)
    opt = p.parse_args(argv)

    video = opt.video.resolve()
    if not video.is_file():
        print(f"파일 없음: {video}", file=sys.stderr)
        return 2
    opt.out_dir.mkdir(parents=True, exist_ok=True)

    if not opt.compare_only:
        for tag, device, sample_fps, batch_size, pretrained in RUNS:
            if opt.only and tag not in opt.only:
                continue
            out_path = opt.out_dir / f"{tag}.json"
            if out_path.is_file() and not opt.force:
                print(f"[건너뜀] {tag} (결과 있음)", flush=True)
                continue
            cfg = WaveRepConfig(
                device=device, sample_fps=sample_fps, batch_size=batch_size,
                pretrained=pretrained, timeout_sec=opt.timeout, measure_peak_footprint=True,
            )
            t0 = time.perf_counter()
            with tempfile.TemporaryDirectory(prefix="waverep-bench-") as work:
                # 구간은 영상 전체를 덮도록 넉넉히 준다. 영상 길이를 넘는 부분은 버려진다.
                result = run_waverep(video, [(0.0, 86400.0)], Path(work), cfg)
            result["tag"] = tag
            result["wall_sec"] = round(time.perf_counter() - t0, 3)
            result["video_file"] = video.name
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            s = (result.get("raw_metrics") or {}).get("frame_logit") or {}
            print(f"[{result['status']}] {tag}: {result['wall_sec']}초, 프레임 {s.get('frames')}", flush=True)

    comparisons = []
    for name, ref in PAIRS:
        a, b = load_logits(opt.out_dir, name), load_logits(opt.out_dir, ref)
        row = {"run": name, "reference": ref}
        row.update(compare(a, b) if a is not None and b is not None else {"skipped": "결과 없음"})
        comparisons.append(row)
    (opt.out_dir / "comparisons.json").write_text(
        json.dumps(comparisons, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(comparisons, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
