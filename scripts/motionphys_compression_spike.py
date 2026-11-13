"""같은 진짜 영상을 다시 압축했을 때 MotionPhys 특징이 얼마나 달라지는지 잰다 (백로그 10번 앞부분).

jerk는 3차 차분이라 좌표의 작은 잡음을 크게 키운다. 압축만으로 jerk 통계가 얼마나
움직이는지 보려는 측정이다. 비교할 가짜 영상이 없으므로 "가짜처럼 보인다"를 판정하지 않는다.
점수를 내지 않고 진위를 해석하지 않는다.

research/motionphys/.venv의 Python으로 실행한다 (저장소 루트에서):
    research/motionphys/.venv/bin/python scripts/motionphys_compression_spike.py \
        --video data/research/samples/<허가 영상>.mp4

FFmpeg의 소프트웨어 인코더 libx264로 CRF 20/28/34를 만든다(하드웨어 인코더를 쓰지 않는다).
실제 YouTube의 재인코딩과 같다고 주장하지 않는다.
변환본과 결과는 data/research/motionphys-spike/ (Git 밖)에 둔다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "research" / "motionphys"))

import numpy as np  # noqa: E402

import extract  # noqa: E402
import kinematics  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "research" / "motionphys-spike"
CRFS = (20, 28, 34)
TIMEOUT_SEC = 600


def encode_command(src: Path, dst: Path, crf: int) -> list[str]:
    """인자 리스트만 만든다. 해상도와 프레임률은 그대로 두고 화질만 바꾼다."""
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-map", "0:v:0", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-an", str(dst),
    ]


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration,size,bit_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    data = json.loads(out.stdout)
    s, f = data["streams"][0], data["format"]
    return {
        "codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
        "fps": s.get("r_frame_rate"), "frames": int(s["nb_frames"]) if s.get("nb_frames") else None,
        "duration_sec": float(f["duration"]), "size_bytes": int(f["size"]),
        "bitrate_kbps": round(int(f["bit_rate"]) / 1000) if f.get("bit_rate") else None,
    }


def relative_change(base: np.ndarray, other: np.ndarray) -> np.ndarray:
    """(other - base) / |base|. 기준값이 0에 가까운 특징은 nan으로 두고 집계에서 뺀다."""
    base, other = np.asarray(base, float), np.asarray(other, float)
    out = np.full(base.shape, np.nan)
    ok = np.abs(base) > 1e-9
    out[ok] = (other[ok] - base[ok]) / np.abs(base[ok])
    return out


def compare(names: list[str], base: list[float], other: list[float]) -> dict:
    """물리량별로 특징의 상대 변화를 요약하고, 대표 특징 몇 개는 값을 그대로 싣는다."""
    rel = relative_change(base, other)
    out: dict = {"by_quantity": {}, "selected": {}}
    for quantity in kinematics.QUANTITIES:
        idx = [i for i, n in enumerate(names) if f".{quantity}." in n]
        r = rel[idx]
        r = r[np.isfinite(r)]
        out["by_quantity"][quantity] = {
            "features": len(idx),
            "features_compared": int(r.size),
            "median_abs_rel_change": float(np.median(np.abs(r))) if r.size else None,
            "p90_abs_rel_change": float(np.percentile(np.abs(r), 90)) if r.size else None,
            "median_signed_rel_change": float(np.median(r)) if r.size else None,
        }
    for i, n in enumerate(names):
        # 궤적별 평균의 궤적 간 중앙값: 그 물리량의 "전형적인 크기"
        if n.endswith(".mean.median"):
            out["selected"][n] = {"base": float(base[i]), "value": float(other[i]),
                                  "rel_change": None if not np.isfinite(rel[i]) else float(rel[i])}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--video", type=Path, required=True, help="허가된 진짜 영상")
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    opt = p.parse_args(argv)
    src = opt.video.resolve()
    if not src.is_file():
        print(f"파일 없음: {src}", file=sys.stderr)
        return 2
    opt.out_dir.mkdir(parents=True, exist_ok=True)

    files = {"original": src}
    for crf in CRFS:
        dst = opt.out_dir / f"crf{crf}.mp4"
        subprocess.run(encode_command(src, dst, crf), check=True, timeout=TIMEOUT_SEC)
        files[f"crf{crf}"] = dst
    media = {name: probe(path) for name, path in files.items()}
    duration = min(m["duration_sec"] for m in media.values())
    num, den = media["original"]["fps"].split("/")
    fps = float(num) / float(den)
    segments = [(0.0, duration)]

    results: dict = {"video_file": src.name, "segments": segments, "media": media, "variants": {}}
    for variant in extract.VARIANTS:
        names = extract.feature_names(variant)
        runs = {name: extract.extract(path, segments, variant) for name, path in files.items()}
        # 대조군: 압축하지 않고 표본 프레임만 한 프레임 뒤로 민 원본. 같은 영상에서 표본 위치만
        # 달라져도 특징이 얼마나 움직이는지 본다. 압축의 영향을 이 값과 견준다.
        runs["original_shift1"] = extract.extract(src, [(1.0 / fps, duration)], variant)
        repeat = extract.extract(src, segments, variant)  # 같은 입력을 한 번 더: 차이가 0이어야 한다
        base = runs["original"]
        entry: dict = {"runs": {}, "repeat_max_abs_diff": None}
        if base["status"] == "completed" and repeat["status"] == "completed":
            entry["repeat_max_abs_diff"] = float(np.max(np.abs(np.array(base["features"]) - np.array(repeat["features"]))))
        for name, r in runs.items():
            item = {k: r.get(k) for k in ("status", "reason_code", "by_scale", "by_region",
                                          "tracking_success_rate", "face_detection_rate", "clips_used")}
            item["frame_step_sec"] = r["segments"][0]["frame_step_sec"] if r.get("segments") else None
            if name != "original" and r["status"] == "completed" and base["status"] == "completed":
                item["vs_original"] = compare(names, base["features"], r["features"])
            entry["runs"][name] = item
        results["variants"][variant] = entry
        print(f"[{variant}] " + ", ".join(f"{n}: {r['status']}" for n, r in runs.items()), flush=True)

    out_path = opt.out_dir / "compression_spike.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
