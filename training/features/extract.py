"""manifest의 영상마다 Gate → WaveRep·MotionPhys·SyncNet을 돌려 특징을 캐시에 쌓는다 (연구용).

    conda activate trinity
    python -m training.features.extract --manifest <m.csv> --media-root <영상 폴더> --out <특징 폴더>

- 서버와 같은 경로를 쓴다: 서버의 Gate 실행기와 세 축 어댑터를 그대로 부르고(각 .venv 서브프로세스),
  Gate 적합 구간만 모델에 넘긴다. 추론 코드를 다시 구현하지 않는다.
- 이어서 돌리기: 결과는 (입력 파일 sha256, 축 버전, 설정, 구간)으로 만든 키의 JSON 파일이다. 있으면 건너뛴다.
- 항목별 실패 격리: 한 영상·한 축의 실패는 status와 reason_code로 남고 특징은 null이다. 0을 쓰지 않는다.
  실행 오류(error)는 캐시에 남기지 않아 다음 실행에서 다시 시도한다.
- 진행 기록: <out>/progress.jsonl에 한 줄씩 덧붙인다(시각, 영상, 축, 상태, 걸린 시간). 영상 내용은 적지 않는다.
- 외부 평가 자료(split=external)는 이 명령으로 추출하지 않는다. 누수 검사에 실패한 manifest도 거부한다.
- 마지막에 영상 단위 요약 <out>/features.jsonl을 쓴다. 학습(research/training)은 이 파일만 읽는다.

프레임 logit의 집계(중앙값 등)와 SyncNet 트랙 지표의 집계는 연구 내부 특징이며 API 결과가 아니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional

from server.axes.alignment import report as syncnet_report
from server.axes.alignment.syncnet import SyncNetConfig, run_syncnet
from server.axes.physics import motionphys
from server.axes.physics.motionphys import MotionPhysConfig, run_motionphys
from server.axes.signal import waverep
from server.axes.signal.waverep import WaveRepConfig, run_waverep
from server.config import Settings
from server.gate.runner import run_gate_process
from training import hygiene
from training.datasets.manifest import ManifestError, Record, read_manifest, sha256_file
from training.evaluation.lock import DEFAULT_LOCK_PATH, load_lock

SCHEMA_VERSION = 1
AXES = ("gate", "waverep", "motionphys", "syncnet")
MODEL_AXES = AXES[1:]
GATE_VERSION = "gate-v1"  # Gate 설정(임시 임계값)이 바뀌면 올린다. 캐시 키에 들어간다
CACHEABLE = ("completed", "insufficient_input", "unsupported_input", "out_of_distribution")


class ExtractError(RuntimeError):
    pass


def default_settings() -> dict:
    """추출 설정. 서버 기본값과 같게 둔다. 캐시 키와 묶음의 특징 버전에 들어간다."""
    s = Settings()
    return {
        "gate": {"version": GATE_VERSION, "timeout_sec": s.gate_timeout_seconds},
        "waverep": {"version": waverep.MODEL_VERSION, "device": s.waverep_device,
                    "sample_fps": s.waverep_sample_fps, "batch_size": s.waverep_batch_size,
                    "timeout_sec": s.waverep_timeout_seconds},
        "motionphys": {"version": motionphys.MODEL_VERSION, "timeout_sec": s.motionphys_timeout_seconds},
        "syncnet": {"version": syncnet_report.MODEL_VERSION, "timeout_sec": 600.0},
    }


def feature_version(settings: dict) -> dict:
    """결과에 영향을 주는 설정만(제한 시간 제외). 학습 묶음과 서버가 이 값으로 서로를 확인한다."""
    return {axis: {k: v for k, v in cfg.items() if k != "timeout_sec"} for axis, cfg in settings.items()}


def cache_key(file_hash: str, axis: str, settings: dict, segments) -> str:
    body = json.dumps({"file": file_hash, "axis": axis, "config": feature_version(settings)[axis],
                       "segments": segments, "schema": SCHEMA_VERSION}, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------- 축 한 건 ----------

def run_gate(media: Path, work: Path, segments, settings: dict) -> dict:
    s = Settings()
    gate = run_gate_process(media, work, settings=s, timeout_seconds=settings["gate"]["timeout_sec"],
                            on_tick=lambda: True)
    eligible = [[seg.start_sec, seg.end_sec] for seg in gate.eligible_segments]
    failed = gate.reason_code in ("gate_error", "gate_timeout")
    return {
        "status": "error" if failed else "completed" if eligible else "insufficient_input",
        "reason_code": gate.reason_code,
        "video_duration_sec": None if gate.media is None else gate.media.duration_sec,
        "eligible_duration_sec": None if gate.media is None else gate.eligible_duration_sec,
        "eligible_segments": eligible,
        "media": None if gate.media is None else asdict(gate.media),
    }


def run_waverep_axis(media: Path, work: Path, segments, settings: dict) -> dict:
    c = settings["waverep"]
    out = run_waverep(media, segments, work, WaveRepConfig(
        device=c["device"], sample_fps=c["sample_fps"], batch_size=c["batch_size"],
        pretrained=False, timeout_sec=c["timeout_sec"]))
    logits = [f["logit"] for f in out["frames"]] if out["status"] == "completed" else None
    return {"status": out["status"], "reason_code": out["reason_code"], "frame_logits": logits,
            "device_used": (out.get("model") or {}).get("device_used")}


def run_motionphys_axis(media: Path, work: Path, segments, settings: dict) -> dict:
    out = run_motionphys(media, segments, work, MotionPhysConfig(timeout_sec=settings["motionphys"]["timeout_sec"]),
                         include_features=True)
    return {"status": out["status"], "reason_code": out["reason_code"], "variants": out["variants"]}


def run_syncnet_axis(media: Path, work: Path, segments, settings: dict) -> dict:
    out = run_syncnet(media, segments, work, SyncNetConfig(timeout_sec=settings["syncnet"]["timeout_sec"]))
    return {"status": out["status"], "reason_code": out["reason_code"], "segments": out["segments"]}


RUNNERS: dict[str, Callable] = {"gate": run_gate, "waverep": run_waverep_axis,
                                "motionphys": run_motionphys_axis, "syncnet": run_syncnet_axis}


# ---------- 일괄 실행 ----------

def _stage(src: Path, work: Path) -> Path:
    """어댑터는 작업 폴더 안의 파일만 받는다. 원본은 읽기만 한다."""
    media = work / f"media{src.suffix.lower()}"
    try:
        os.link(src, media)
    except OSError:
        shutil.copyfile(src, media)
    return media


def _read(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _progress(out: Path, **entry) -> None:
    with (out / "progress.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": int(time.time()), **entry}, ensure_ascii=False) + "\n")


def extract_video(rec: Record, media_root: Path, out: Path, settings: dict, axes=MODEL_AXES) -> dict:
    """한 영상의 축별 결과 {axis: result}. 예외를 던지지 않는다."""
    src = (media_root / rec.video_path).resolve()
    results: dict[str, dict] = {}

    def fail_all(reason: str) -> dict:
        return {axis: {"status": "error", "reason_code": reason} for axis in ("gate", *axes)}

    if not src.is_file() or not src.is_relative_to(media_root.resolve()):
        _progress(out, video=rec.uid, axis="*", status="error", reason_code="media_unreadable")
        return fail_all("media_unreadable")
    file_hash = sha256_file(src)
    if rec.file_hash and rec.file_hash != file_hash:
        # manifest가 가리키는 파일이 아니다. 다른 영상의 특징을 이 행에 붙이지 않는다
        _progress(out, video=rec.uid, axis="*", status="error", reason_code="file_hash_mismatch")
        return fail_all("file_hash_mismatch")

    segments = None
    (out / "work").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="job-", dir=out / "work") as tmp:
        work, media = Path(tmp).resolve(), None
        for axis in ("gate", *axes):
            if axis != "gate" and not segments:
                # Gate가 거른 영상은 모델을 돌리지 않는다(서버와 같다)
                gate = results["gate"]
                results[axis] = {"status": "error" if gate["status"] == "error" else "insufficient_input",
                                 "reason_code": gate["reason_code"] or "no_segments"}
                continue
            path = out / "cache" / axis / f"{cache_key(file_hash, axis, settings, segments)}.json"
            cached = _read(path)
            if cached is None:
                media = media or _stage(src, work)
                t0 = time.monotonic()
                try:
                    result = RUNNERS[axis](media, work, segments, settings)
                except Exception as e:  # 한 축의 실패가 나머지 영상까지 막지 않게 한다
                    result = {"status": "error", "reason_code": "extraction_error", "detail": type(e).__name__}
                elapsed = round(time.monotonic() - t0, 3)
                cached = {"schema_version": SCHEMA_VERSION, "axis": axis, "input_sha256": file_hash,
                          "config": feature_version(settings)[axis], "segments": segments, "result": result}
                if result["status"] in CACHEABLE:
                    _write(path, cached)
                _progress(out, video=rec.uid, axis=axis, status=result["status"],
                          reason_code=result.get("reason_code"), elapsed_sec=elapsed, cached=False)
            else:
                _progress(out, video=rec.uid, axis=axis, status=cached["result"]["status"],
                          reason_code=cached["result"].get("reason_code"), cached=True)
            results[axis] = cached["result"]
            if axis == "gate":
                segments = results["gate"].get("eligible_segments") or None
    return results


# ---------- 영상 단위 요약 ----------

def _median(values: list[float]) -> Optional[float]:
    return statistics.median(values) if values else None


def summarize_video(rec: Record, results: dict[str, dict]) -> dict:
    """학습이 읽는 한 줄. 계산하지 못한 값은 null이고 이유를 함께 적는다."""
    gate = results.get("gate") or {}
    row = {"uid": rec.uid, "dataset_id": rec.dataset_id, "video_id": rec.video_id,
           "video_duration_sec": gate.get("video_duration_sec"),
           "eligible_duration_sec": gate.get("eligible_duration_sec"),
           "gate_reason": gate.get("reason_code"),
           # 해상도·fps·길이·오디오 유무. 라벨이 이것만으로 예측되는지(shortcut) 진단할 때만 쓴다. 모델 입력이 아니다
           "media": gate.get("media"), "axes": {}}
    axes = row["axes"]

    w = results.get("waverep")
    if w is not None:
        logits = w.get("frame_logits")
        axes["waverep"] = {"status": w["status"], "reason_code": w.get("reason_code"),
                           "frames": len(logits) if logits else 0,
                           # 주 지표는 중앙값이다(사전 고정). 평균과 q75는 dev에서만 견주는 보조다
                           "logit_median": _median(logits or []),
                           "logit_mean": statistics.fmean(logits) if logits else None,
                           "logit_q75": (statistics.quantiles(logits, n=4, method="inclusive")[2]
                                         if logits and len(logits) > 1 else (logits[0] if logits else None))}
    m = results.get("motionphys")
    if m is not None:
        variants = m.get("variants") or {}
        axes["motionphys"] = {"status": m["status"], "reason_code": m.get("reason_code"), "variants": {
            name: {"status": (variants.get(name) or {}).get("status", m["status"]),
                   "reason_code": (variants.get(name) or {}).get("reason_code", m.get("reason_code")),
                   "features": (variants.get(name) or {}).get("features")}
            for name in motionphys.VARIANTS}}
    s = results.get("syncnet")
    if s is not None:
        tracks = [t for seg in (s.get("segments") or []) if seg.get("tracks") for t in seg["tracks"]]
        # 전 구간·전 트랙의 중앙값(연구 내부 집계, 2026-11-16 승인). 트랙이 없으면 null
        axes["syncnet"] = {"status": s["status"], "reason_code": s.get("reason_code"), "tracks": len(tracks),
                           "lse_c_median": _median([t["lse_c"] for t in tracks]),
                           "lse_d_median": _median([t["lse_d"] for t in tracks]),
                           "abs_offset_median": _median([abs(t["offset_frames"]) for t in tracks])}
    return row


def run(manifest: Path, media_root: Path, out: Path, axes=MODEL_AXES, lock_path: Path = DEFAULT_LOCK_PATH,
        settings: Optional[dict] = None, limit: Optional[int] = None) -> dict:
    records = read_manifest(manifest)
    report = hygiene.check(records, load_lock(lock_path))
    if not report.ok:
        raise ExtractError("누수 검사 실패. 추출하지 않는다: " + ", ".join(e["code"] for e in report.errors))
    settings = settings or default_settings()
    out.mkdir(parents=True, exist_ok=True)
    todo = [r for r in sorted(records, key=lambda r: r.uid) if r.split != "external"]
    skipped_external = len(records) - len(todo)
    if limit is not None:
        todo = todo[:limit]
    rows, counts = [], {}
    for rec in todo:
        results = extract_video(rec, media_root, out, settings, axes)
        rows.append(summarize_video(rec, results))
        for axis, r in results.items():
            counts.setdefault(axis, {}).setdefault(r["status"], 0)
            counts[axis][r["status"]] += 1
    tmp = out / "features.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    os.replace(tmp, out / "features.jsonl")
    meta = {"schema_version": SCHEMA_VERSION, "manifest_sha256": sha256_file(manifest),
            "feature_version": feature_version(settings), "axes": list(axes), "videos": len(rows),
            "external_videos_skipped": skipped_external, "status_counts": counts,
            "features_sha256": sha256_file(out / "features.jsonl")}
    _write(out / "features.meta.json", meta)
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--media-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--axes", nargs="+", default=list(MODEL_AXES), choices=MODEL_AXES)
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    p.add_argument("--limit", type=int, default=None, help="앞에서부터 이 개수만(스모크용)")
    opt = p.parse_args(argv)
    try:
        meta = run(opt.manifest, opt.media_root, opt.out, tuple(opt.axes), opt.lock, limit=opt.limit)
    except (ExtractError, ManifestError, OSError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
