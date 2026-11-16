"""본인 촬영 영상의 3축 압축 견고성 실측 (README §14.1 백로그 9·10·11번의 측정).

원본과 범용 압축 프로파일 12개(libx264 CRF 20/28/34 × 원본/1080/720/480)에 대해
Gate, WaveRep, SyncNet, MotionPhys A/B/C를 같은 조건으로 돌리고 결과를 조건별 JSON으로 남긴다.

    conda activate trinity
    python scripts/robustness_selfvideo.py                 # 변환본 생성 + 측정 (된 것은 건너뛴다)
    python scripts/robustness_selfvideo.py --report        # 모아서 summary.json과 표(tables.md)를 쓴다

- 성능 검증이 아니다. 진짜 영상뿐이라 점수·임계값·탐지 성능을 말할 수 없다. "지표가 압축에 얼마나 흔들리는가"만 잰다.
- 하드웨어 인코더를 쓰지 않는다(training.emulator가 libx264만 허용). 실제 YouTube와 같다고 주장하지 않는다.
- Gate는 조건마다 다시 돌려 기록하고, 세 모델은 **원본의 Gate 적합 구간**으로 고정해 돌린다.
- 1080p 프로파일의 출력이 원본 해상도 출력과 sha256이 같으면 다시 재지 않고 duplicate_of로 적는다.
- 시간은 단조 시계(time.monotonic), 최대 메모리는 측정마다 새 프로세스에서 읽은
  RUSAGE_CHILDREN의 ru_maxrss(후손 프로세스 하나의 최대 RSS, 합계 아님)다.
- 변환본·결과는 data/research/robustness-selfvideo/(Git 제외)에 둔다. 외부 평가 데이터는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.axes.alignment.syncnet import SyncNetConfig, run_syncnet  # noqa: E402
from server.axes.physics.motionphys import MotionPhysConfig  # noqa: E402
from server.axes.signal.waverep import WaveRepConfig, run_waverep  # noqa: E402
from server.config import Settings  # noqa: E402
from server.gate.runner import run_gate_process  # noqa: E402
from training.emulator.profiles import PROFILES  # noqa: E402
from training.emulator.video import emulate, ffmpeg_version, probe_video, sha256_file  # noqa: E402

SAMPLES = REPO_ROOT / "data/research/samples"
OUT = REPO_ROOT / "data/research/robustness-selfvideo"
VIDEOS = ("A", "B", "E")
ORIGINAL = "original"
AXES = ("gate", "waverep", "syncnet", "motionphys")
# 측정 스크립트에서만 쓰는 SyncNet 제한(서비스 기본은 600초다)
SYNCNET_TIMEOUT_SEC = 1800.0
# SyncNet이 조건당 10분을 넘을 때 쓰는 축소 집합(사용자 승인, 2026-11-16)
SYNCNET_REDUCED = (ORIGINAL, "x264-crf20-source", "x264-crf20-720p", "x264-crf34-source", "x264-crf34-720p")
SCHEMA_VERSION = 1


def conditions() -> list[str]:
    return [ORIGINAL, *PROFILES]


def result_path(video: str, condition: str, axis: str) -> Path:
    return OUT / "results" / video / condition / f"{axis}.json"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------- 변환본 ----------

def source_path(video: str) -> Path:
    return SAMPLES / f"{video}.MOV"


def prepare_variants(video: str) -> dict:
    """프로파일 12개를 만들고(있으면 그대로) 조건별 파일·해시·중복 관계를 돌려준다."""
    src = source_path(video)
    out_dir = OUT / "variants"
    index_path = OUT / "variants" / f"{video}.index.json"
    index = read_json(index_path) or {"video": video, "conditions": {}}
    conds = index["conditions"]
    if ORIGINAL not in conds:
        conds[ORIGINAL] = {"file": str(src.relative_to(REPO_ROOT)), "sha256": sha256_file(src),
                           "probe": probe_video(src), "duplicate_of": None, "status": "original"}
    for pid in PROFILES:
        if pid in conds:
            continue
        out_file = out_dir / f"{src.stem}__{pid}.mp4"
        meta_file = out_file.with_name(out_file.name + ".json")
        t0 = time.monotonic()
        meta = read_json(meta_file) if out_file.is_file() else None
        if meta is None:
            out_file.unlink(missing_ok=True)
            meta_file.unlink(missing_ok=True)
            meta = emulate(src, pid, out_dir, lineage={"video_id": video, "source_recording_id": video})
        encode_sec = round(time.monotonic() - t0, 2)
        entry = {"status": meta["status"], "reason": meta["reason"], "profile": meta["profile"],
                 "ffmpeg_version": meta["ffmpeg_version"], "ffmpeg_args": meta["ffmpeg_args"],
                 "encode_sec": encode_sec, "file": None, "sha256": None, "probe": None, "duplicate_of": None}
        if meta["status"] == "completed":
            entry.update(file=str(out_file.relative_to(REPO_ROOT)), sha256=meta["output"]["sha256"],
                         probe={k: v for k, v in meta["output"].items() if k not in ("name", "sha256")})
            # 같은 바이트의 출력이 앞 조건에 있으면 다시 재지 않는다
            for other, o in conds.items():
                if other != ORIGINAL and o.get("sha256") == entry["sha256"] and o.get("duplicate_of") is None:
                    entry["duplicate_of"] = other
                    break
        conds[pid] = entry
        write_json(index_path, index)
        print(f"[{video}] variant {pid}: {entry['status']}"
              + (f" (= {entry['duplicate_of']})" if entry["duplicate_of"] else ""), flush=True)
    write_json(index_path, index)
    return index


# ---------- 측정 한 건 (새 프로세스에서 실행) ----------

def _stage(src: Path, work: Path) -> Path:
    """어댑터는 작업 폴더 안의 미디어만 받는다. 원본을 건드리지 않게 복사한다."""
    media = work / f"media{src.suffix.lower()}"
    shutil.copyfile(src, media)
    return media


def _logit_stats(logits: list[float]) -> dict:
    q1, _, q3 = statistics.quantiles(logits, n=4, method="inclusive") if len(logits) > 1 else (logits[0],) * 3
    return {"frames": len(logits), "median": statistics.median(logits), "q25": q1, "q75": q3,
            "iqr": q3 - q1, "min": min(logits), "max": max(logits), "mean": statistics.fmean(logits)}


def measure_gate(media: Path, work: Path, segments, opt) -> dict:
    gate = run_gate_process(media, work, settings=Settings(), timeout_seconds=Settings().gate_timeout_seconds,
                            on_tick=lambda: True)
    return {"reason_code": gate.reason_code, "media": None if gate.media is None else asdict(gate.media),
            "eligible_duration_sec": gate.eligible_duration_sec if gate.media is not None else None,
            "eligible_segments": [[s.start_sec, s.end_sec] for s in gate.eligible_segments],
            "excluded_segments": [{"start_sec": s.start_sec, "end_sec": s.end_sec, "reason_code": s.reason_code}
                                  for s in gate.excluded_segments]}


def measure_waverep(media: Path, work: Path, segments, opt) -> dict:
    s = Settings()
    cfg = WaveRepConfig(device=opt.waverep_device or s.waverep_device, sample_fps=s.waverep_sample_fps,
                        batch_size=s.waverep_batch_size, pretrained=False,
                        timeout_sec=s.waverep_timeout_seconds, measure_peak_footprint=True)
    out = run_waverep(media, segments, work, cfg)
    result = {"status": out["status"], "reason_code": out["reason_code"],
              "config": {"device": cfg.device, "sample_fps": cfg.sample_fps, "batch_size": cfg.batch_size},
              "device_used": (out.get("model") or {}).get("device_used"),
              "timing": out.get("timing"), "memory": out.get("memory"), "frames": None, "frame_logit": None}
    if out["status"] == "completed":
        result["frames"] = [{"index": f["index"], "logit": f["logit"]} for f in out["frames"]]
        result["frame_logit"] = _logit_stats([f["logit"] for f in out["frames"]])
    return result


def measure_syncnet(media: Path, work: Path, segments, opt) -> dict:
    out = run_syncnet(media, segments, work, SyncNetConfig(timeout_sec=SYNCNET_TIMEOUT_SEC))
    return {"status": out["status"], "reason_code": out["reason_code"], "device": "cpu",
            "offset_fps": out["offset_fps"], "timeout_sec": SYNCNET_TIMEOUT_SEC, "segments": out["segments"]}


def _motionphys_once(media: Path, work: Path, segments, tag: str) -> dict:
    """서버 어댑터와 같은 실행기를 부르되 특징 벡터를 받는다(include_features는 측정 전용)."""
    cfg = MotionPhysConfig()
    request, output = work / f"mp_{tag}_request.json", work / f"mp_{tag}_result.json"
    request.write_text(json.dumps({"video": str(media), "segments": segments, "include_features": True}))
    t0 = time.monotonic()
    proc = subprocess.run([str(cfg.python), str(cfg.script), "--request", str(request), "--output", str(output)],
                          cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=900)
    elapsed = round(time.monotonic() - t0, 3)
    raw = read_json(output) if proc.returncode == 0 else None
    return {"returncode": proc.returncode, "elapsed_sec": elapsed, "segments": segments,
            "variants": None if raw is None else raw["variants"]}


def measure_motionphys(media: Path, work: Path, segments, opt) -> dict:
    result = {"device": "cpu", **_motionphys_once(media, work, segments, "main")}
    if opt.condition == ORIGINAL:
        # 대조군: 압축하지 않고 각 구간의 시작만 한 프레임 뒤로 민다(docs/motionphys-spike.md와 같은 정의)
        fps = _fps(media)
        shifted = [[a + 1.0 / fps, b] for a, b in segments]
        result["control_shift1"] = _motionphys_once(media, work, shifted, "shift1")
        result["control_shift1"]["shift_sec"] = 1.0 / fps
    return result


def _fps(media: Path) -> float:
    num, den = probe_video(media)["frame_rate"].split("/")
    return float(num) / float(den)


MEASURES = {"gate": measure_gate, "waverep": measure_waverep, "syncnet": measure_syncnet,
            "motionphys": measure_motionphys}


def measure_one(opt) -> int:
    """한 (영상, 조건, 축)을 재고 JSON을 쓴다. 이 프로세스의 후손만 메모리에 잡히게 따로 띄운다."""
    index = read_json(OUT / "variants" / f"{opt.video}.index.json")
    entry = index["conditions"][opt.condition]
    src = REPO_ROOT / entry["file"]
    segments = None
    if opt.axis != "gate":
        base = read_json(result_path(opt.video, ORIGINAL, "gate"))
        segments = base["result"]["eligible_segments"]
    (OUT / "work").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="job-", dir=OUT / "work") as tmp:
        work = Path(tmp).resolve()
        media = _stage(src, work)
        t0 = time.monotonic()
        result = MEASURES[opt.axis](media, work, segments, opt)
        elapsed = time.monotonic() - t0
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(result_path(opt.video, opt.condition, opt.axis), {
        "schema_version": SCHEMA_VERSION, "video": opt.video, "condition": opt.condition, "axis": opt.axis,
        "input_sha256": entry["sha256"], "segments_from": None if segments is None else "original_gate",
        "segments": segments,
        "elapsed_sec": round(elapsed, 3),                # 단조 시계. 프로세스 시작·모델 로드 포함
        "children_max_rss_bytes": usage.ru_maxrss,       # macOS는 바이트. 후손 프로세스 하나의 최대값
        "machine": {"platform": platform.platform(), "machine": platform.machine()},
        "measured_at_unix": int(time.time()),
        "result": result,
    })
    return 0


# ---------- 전체 실행 ----------

def run_all(opt) -> int:
    missing = [v for v in opt.videos if not source_path(v).is_file()]
    if missing:
        print(f"샘플 없음: {missing}", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "run_config.json", {
        "ffmpeg_version": ffmpeg_version(), "syncnet_set": opt.syncnet_set,
        "syncnet_timeout_sec": SYNCNET_TIMEOUT_SEC, "waverep_device": opt.waverep_device or Settings().waverep_device,
        "profiles": {pid: p.to_dict() for pid, p in PROFILES.items()},
    })
    indexes = {v: prepare_variants(v) for v in opt.videos}
    # 축 순서: 빠른 것부터. SyncNet은 마지막에 몰아서 돌려 중간에 끊겨도 나머지 표가 남는다.
    for axis in opt.axes:
        for video in opt.videos:
            for cond in ([ORIGINAL] + [c for c in opt.conditions if c != ORIGINAL]):
                if cond not in opt.conditions and cond != ORIGINAL:
                    continue
                entry = indexes[video]["conditions"][cond]
                if entry["status"] not in ("original", "completed") or entry["duplicate_of"]:
                    continue
                if axis == "syncnet" and opt.syncnet_set == "reduced" and cond not in SYNCNET_REDUCED:
                    continue
                path = result_path(video, cond, axis)
                if path.is_file() and not opt.force:
                    continue
                if axis != "gate":
                    base = read_json(result_path(video, ORIGINAL, "gate"))
                    if base is None or not base["result"]["eligible_segments"]:
                        print(f"[{video}] 원본 Gate 적합 구간 없음: {axis} 건너뜀", flush=True)
                        break
                cmd = [sys.executable, str(Path(__file__).resolve()), "--measure",
                       "--video", video, "--condition", cond, "--axis", axis]
                if opt.waverep_device:
                    cmd += ["--waverep-device", opt.waverep_device]
                t0 = time.monotonic()
                code = subprocess.run(cmd, cwd=REPO_ROOT).returncode
                done = read_json(path)
                status = "?" if done is None else (done["result"].get("status") or done["result"].get("reason_code") or "ok")
                print(f"[{video}] {axis:10s} {cond:20s} {time.monotonic() - t0:7.1f}s exit={code} {status}", flush=True)
    return 0


# ---------- 보고 ----------

def _rel(base: float, value: float) -> float | None:
    return None if abs(base) <= 1e-9 else (value - base) / abs(base)


def _percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def compare_features(names: list[str], base: list[float], other: list[float]) -> dict:
    """물리량별 |상대 변화|의 중앙값·90번째 백분위와 대표값(궤적별 평균의 궤적 간 중앙값)의 변화."""
    out = {"by_quantity": {}, "selected": {}}
    for quantity in ("curvature", "angular_velocity", "jerk"):
        rels = [r for n, b, o in zip(names, base, other) if f".{quantity}." in n
                for r in [_rel(b, o)] if r is not None]
        mags = [abs(r) for r in rels]
        out["by_quantity"][quantity] = {
            "features_compared": len(mags),
            "median_abs_rel_change": statistics.median(mags) if mags else None,
            "p90_abs_rel_change": _percentile(mags, 0.9) if mags else None,
        }
    for n, b, o in zip(names, base, other):
        if n.endswith(".mean.median"):
            out["selected"][n] = {"base": b, "value": o, "rel_change": _rel(b, o)}
    return out


def _motionphys_summary(run: dict | None, base_run: dict | None) -> dict | None:
    if run is None or run.get("variants") is None:
        return None
    out = {}
    for name, v in run["variants"].items():
        item = {k: v.get(k) for k in ("status", "reason_code", "valid_trajectories", "moving_trajectories",
                                      "tracking_success_rate", "face_detection_rate", "timing_sec")}
        b = None if base_run is None or base_run.get("variants") is None else base_run["variants"].get(name)
        if b is not None and b is not v and v.get("features") and b.get("features"):
            item["vs_original"] = compare_features(v["feature_names"], b["features"], v["features"])
        out[name] = item
    return out


def _waverep_vs(base: dict | None, cur: dict) -> dict | None:
    if base is None or not base.get("frames") or not cur.get("frames"):
        return None
    b = {f["index"]: f["logit"] for f in base["frames"]}
    diffs = [f["logit"] - b[f["index"]] for f in cur["frames"] if f["index"] in b]
    if not diffs:
        return None
    return {"frames_matched": len(diffs), "median_shift": cur["frame_logit"]["median"] - base["frame_logit"]["median"],
            "median_abs_diff": statistics.median(abs(d) for d in diffs), "max_abs_diff": max(abs(d) for d in diffs),
            "mean_diff": statistics.fmean(diffs),
            "sign_changes": sum(1 for f in cur["frames"] if f["index"] in b and (f["logit"] > 0) != (b[f["index"]] > 0))}


def build_summary(videos) -> dict:
    summary = {"schema_version": SCHEMA_VERSION, "run_config": read_json(OUT / "run_config.json"), "videos": {}}
    for video in videos:
        index = read_json(OUT / "variants" / f"{video}.index.json")
        if index is None:
            continue
        base = {axis: (read_json(result_path(video, ORIGINAL, axis)) or {}).get("result") for axis in AXES}
        rows = {}
        for cond in conditions():
            entry = index["conditions"].get(cond)
            if entry is None:
                continue
            row = {"file": {k: entry.get(k) for k in ("status", "sha256", "probe", "duplicate_of", "encode_sec", "reason")}}
            if entry.get("duplicate_of"):
                rows[cond] = row
                continue
            for axis in AXES:
                data = read_json(result_path(video, cond, axis))
                if data is None:
                    row[axis] = None      # 미측정
                    continue
                r = data["result"]
                item = {"elapsed_sec": data["elapsed_sec"], "children_max_rss_bytes": data["children_max_rss_bytes"]}
                if axis == "gate":
                    item.update({k: r[k] for k in ("reason_code", "eligible_duration_sec", "eligible_segments")})
                    item["excluded_reasons"] = sorted({s["reason_code"] for s in r["excluded_segments"]})
                elif axis == "waverep":
                    item.update({k: r[k] for k in ("status", "reason_code", "device_used", "frame_logit", "timing", "memory")})
                    item["vs_original"] = None if cond == ORIGINAL else _waverep_vs(base["waverep"], r)
                elif axis == "syncnet":
                    item.update({k: r[k] for k in ("status", "reason_code", "segments")})
                else:
                    item["variants"] = _motionphys_summary(r, None if cond == ORIGINAL else base["motionphys"])
                    item["process_elapsed_sec"] = r.get("elapsed_sec")
                    if cond == ORIGINAL and r.get("control_shift1"):
                        item["control_shift1"] = _motionphys_summary(r["control_shift1"], r)
                row[axis] = item
            rows[cond] = row
        summary["videos"][video] = rows
    return summary


def report(opt) -> int:
    summary = build_summary(opt.videos)
    write_json(OUT / "summary.json", summary)
    print(OUT / "summary.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--videos", nargs="+", default=list(VIDEOS), choices=VIDEOS)
    p.add_argument("--conditions", nargs="+", default=conditions(), choices=conditions())
    p.add_argument("--axes", nargs="+", default=["gate", "motionphys", "waverep", "syncnet"], choices=AXES)
    p.add_argument("--syncnet-set", choices=("full", "reduced"), default="full",
                   help="reduced: 원본 + CRF 20/34 × 원본/720만 SyncNet을 돌린다")
    p.add_argument("--waverep-device", choices=("cpu", "mps"), default=None, help="기본은 Worker 설정값")
    p.add_argument("--force", action="store_true", help="이미 있는 결과도 다시 잰다")
    p.add_argument("--report", action="store_true", help="측정하지 않고 summary.json만 다시 쓴다")
    p.add_argument("--measure", action="store_true", help="(내부용) 한 건만 잰다")
    p.add_argument("--video")
    p.add_argument("--condition")
    p.add_argument("--axis", choices=AXES)
    opt = p.parse_args(argv)
    if opt.measure:
        return measure_one(opt)
    if opt.report:
        return report(opt)
    code = run_all(opt)
    return code or report(opt)


if __name__ == "__main__":
    sys.exit(main())
