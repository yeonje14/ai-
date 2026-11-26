"""Seamless 파일럿 첫 쌍(예약 파일럿 0번)의 파일·시간축·얼굴 높이·Gate·축별 결과를 기록한다.

계획: docs/seamless-pilot-plan.md §3. 결과 정리: docs/seamless-first-pair.md.
research/seamless/fetch_pilot.py로 받은 두 파일 ID만 읽는다. MuseTalk 합성은 하지 않는다.

    conda activate trinity
    python scripts/seamless_first_pair.py files            # 해시·ffprobe·디코딩·VAD·시간축 (A, B)
    python scripts/seamless_first_pair.py run --who A      # 실제 조건 입력(MKV) → Gate → 세 축 (Worker와 같은 순서·제한)
    python scripts/seamless_first_pair.py run --who B
    python scripts/seamless_first_pair.py run --who A --input pre   # 전처리 입력(docs/seamless-preprocess.md)

- 실제 조건 입력은 **첫 쌍 확인용**이다. 원본 MP4의 영상 스트림을 복사하고, 같은 참가자의 WAV 하나만
  오디오 트랙으로 넣은 MKV다(손실 재인코딩 없음). MP4 자체 오디오는 넣지 않는다.
  10쌍 단계에서는 실제·합성을 같은 최종 인코딩으로 맞춘다(docs/seamless-first-pair.md).
- Gate와 축은 Worker(server/jobs/worker.py)와 같은 함수·순서·제한으로 돈다. Gate는 작업 제한
  (job_timeout_seconds) 안에서, 축은 Gate 뒤 다시 정한 작업 제한 안에서 돈다. 실패 점수는 null이다.
- 결과 JSON에는 수치와 상태만 남긴다. 전사 내용, 얼굴 이미지, 프레임을 남기지 않는다.
- 작업 폴더(MKV 포함)는 끝나면 지운다. 디스크 사용량은 2초 간격 표본으로 최대값을 잰다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SEAMLESS = REPO_ROOT / "data/research/seamless"
PILOT_DIR = SEAMLESS / "pilot/pilot-00"
SCHEMA_VERSION = 1
XCORR_SECONDS = 120     # MP4 자체 오디오와 WAV의 시간 차를 잴 앞부분 길이
XCORR_RATE = 8000
XCORR_MAX_LAG_SEC = 2.0


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pilot_dir(order: int = 0) -> Path:
    return SEAMLESS / f"pilot/pilot-{order:02d}"


def pick(order: int = 0) -> dict:
    """파일럿 order번의 fetch.json에서 A·B 파일 경로를 읽는다. 받은 파일 외에는 읽지 않는다."""
    rec = json.loads((pilot_dir(order) / "fetch.json").read_text(encoding="utf-8"))
    out = {}
    for who, key in (("A", "file_id_a"), ("B", "file_id_b")):
        fid = rec["pilot"][key]
        d = rec["downloads"][fid]
        if d["status"] != "ok":
            raise SystemExit(f"{who}: 다운로드가 완전하지 않다")
        files = {ext: REPO_ROOT / d["files"][ext]["path"] for ext in ("mp4", "wav", "json", "npz")}
        out[who] = {"file_id": fid, "files": files,
                    "sha256": {ext: d["files"][ext].get("sha256") for ext in files}}
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ffprobe(path: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=120, check=True)
    raw = json.loads(proc.stdout)
    streams = []
    for s in raw.get("streams", []):
        streams.append({k: s.get(k) for k in (
            "index", "codec_type", "codec_name", "profile", "width", "height", "pix_fmt", "r_frame_rate",
            "avg_frame_rate", "nb_frames", "sample_rate", "channels", "channel_layout", "sample_fmt")}
            | {"start_time": _num(s.get("start_time")), "duration": _num(s.get("duration")),
               "default": (s.get("disposition") or {}).get("default"),
               "rotation": next((sd.get("rotation") for sd in s.get("side_data_list", []) or []
                                 if "rotation" in sd), None)})
    fmt = raw.get("format", {})
    return {"format_name": fmt.get("format_name"), "duration": _num(fmt.get("duration")),
            "start_time": _num(fmt.get("start_time")), "bit_rate": _num(fmt.get("bit_rate")),
            "size": _num(fmt.get("size")), "streams": streams}


def decode_check(path: Path, stream: str) -> dict:
    """스트림 하나를 끝까지 디코딩한다. 오류 줄 수만 남긴다."""
    t0 = time.monotonic()
    proc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", stream, "-f", "null", "-"],
                          capture_output=True, text=True, timeout=1800)
    errors = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    return {"stream": stream, "returncode": proc.returncode, "error_lines": len(errors),
            "elapsed_sec": round(time.monotonic() - t0, 2)}


def pcm_window(path: Path, stream: str, start: float, seconds: float):
    """[start, start+seconds] 오디오를 8kHz 모노 float로 디코딩한다(입력 쪽 -ss, 오디오는 정확히 잘린다)."""
    import numpy as np
    proc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.6f}", "-i", str(path),
                           "-map", stream, "-t", str(seconds),
                           "-ac", "1", "-ar", str(XCORR_RATE), "-f", "f32le", "-"],
                          capture_output=True, timeout=600, check=True)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def pcm(path: Path, stream: str, seconds: float):
    return pcm_window(path, stream, 0.0, seconds)


def xcorr_lag(ref, other, rate: int = XCORR_RATE, max_lag_sec: float = XCORR_MAX_LAG_SEC) -> dict:
    """other가 ref보다 늦으면 양수(초). 정규화 상관 최댓값도 돌려준다."""
    import numpy as np
    n = min(len(ref), len(other))
    a = ref[:n] - ref[:n].mean()
    b = other[:n] - other[:n].mean()
    size = 1 << (2 * n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    max_lag = int(max_lag_sec * rate)
    lags = np.concatenate([np.arange(0, max_lag + 1), np.arange(-max_lag, 0)])
    vals = np.concatenate([corr[:max_lag + 1], corr[-max_lag:]])
    i = int(np.argmax(vals))
    denom = float(np.sqrt((a * a).sum() * (b * b).sum())) or 1.0
    return {"lag_sec": round(float(lags[i]) / rate, 4), "peak_ncc": round(float(vals[i]) / denom, 4),
            "window_sec": round(n / rate, 2), "rate_hz": rate}


def vad_summary(json_path: Path, duration: float | None) -> dict:
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    vad = meta.get("metadata:vad") or []
    segs = [(float(v["start"]), float(v["end"])) for v in vad]
    speech = sum(max(e - s, 0.0) for s, e in segs)
    tr = meta.get("metadata:transcript") or []
    return {"vad_segments": len(segs), "vad_speech_sec": round(speech, 2),
            "vad_speech_ratio": None if not duration else round(speech / duration, 4),
            "vad_first_start": min((s for s, _ in segs), default=None),
            "vad_last_end": max((e for _, e in segs), default=None),
            "vad_segments_ge_2s": sum(1 for s, e in segs if e - s >= 2.0),
            "transcript_entries": len(tr),   # 내용은 남기지 않는다
            "json_keys": sorted(meta.keys())}


def files_report() -> dict:
    p = pick()
    report = {"schema_version": SCHEMA_VERSION, "participants": {}}
    for who, info in p.items():
        f = info["files"]
        sha_now = {ext: sha256_file(path) for ext, path in f.items()}
        mp4, wav = ffprobe(f["mp4"]), ffprobe(f["wav"])
        v = next(s for s in mp4["streams"] if s["codec_type"] == "video")
        mp4_audio = [s for s in mp4["streams"] if s["codec_type"] == "audio"]
        w = wav["streams"][0]
        decodes = [decode_check(f["mp4"], "0:v:0"), decode_check(f["wav"], "0:a:0")]
        decodes += [decode_check(f["mp4"], f"0:{s['index']}") for s in mp4_audio]
        timeline = {
            "video_start_sec": v["start_time"], "video_duration_sec": v["duration"],
            "mp4_audio_start_sec": mp4_audio[0]["start_time"] if mp4_audio else None,
            "mp4_audio_duration_sec": mp4_audio[0]["duration"] if mp4_audio else None,
            "wav_start_sec": w["start_time"],  # WAV에는 시작 시각 필드가 없다(None). 0초에서 시작하는 것으로 읽힌다
            "wav_duration_sec": w["duration"],
            "wav_minus_video_duration_sec": None if None in (w["duration"], v["duration"])
            else round(w["duration"] - v["duration"], 4),
            "wav_minus_mp4_audio_duration_sec": None if not mp4_audio or None in (w["duration"],
                                                                                  mp4_audio[0]["duration"])
            else round(w["duration"] - mp4_audio[0]["duration"], 4),
        }
        if mp4_audio:
            timeline["wav_vs_mp4_audio_xcorr"] = xcorr_lag(pcm(f["mp4"], f"0:{mp4_audio[0]['index']}", XCORR_SECONDS),
                                                           pcm(f["wav"], "0:a:0", XCORR_SECONDS))
        report["participants"][who] = {
            "file_id": info["file_id"],
            "sha256": sha_now, "sha256_matches_fetch": sha_now == info["sha256"],
            "bytes": {ext: path.stat().st_size for ext, path in f.items()},
            "mp4": mp4, "wav": wav, "mp4_has_audio": bool(mp4_audio), "decode": decodes,
            "timeline": timeline, "vad": vad_summary(f["json"], w["duration"]),
        }
    a, b = report["participants"]["A"], report["participants"]["B"]
    # 상대방 WAV와 A의 MP4 자체 오디오의 상관(혼선·공용 마이크 여부 참고)
    if a["mp4_has_audio"]:
        pa = pick()
        idx = next(s["index"] for s in a["mp4"]["streams"] if s["codec_type"] == "audio")
        report["cross"] = {"B_wav_vs_A_mp4_audio_xcorr": xcorr_lag(
            pcm(pa["A"]["files"]["mp4"], f"0:{idx}", XCORR_SECONDS), pcm(pa["B"]["files"]["wav"], "0:a:0",
                                                                           XCORR_SECONDS))}
    report["pair"] = {
        "video_duration_diff_sec": round(a["timeline"]["video_duration_sec"] - b["timeline"]["video_duration_sec"], 4),
        "wav_duration_diff_sec": round(a["timeline"]["wav_duration_sec"] - b["timeline"]["wav_duration_sec"], 4),
    }
    write_json(PILOT_DIR / "inspect/files.json", report)
    return report


# ---------- 실제 조건 입력과 Gate·축 ----------

def mux_real(mp4: Path, wav: Path, out: Path) -> dict:
    """원본 영상 스트림 복사 + 같은 참가자 WAV 하나. MP4 자체 오디오는 넣지 않는다."""
    t0 = time.monotonic()
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(mp4), "-i", str(wav),
                    "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-f", "matroska", str(out)],
                   check=True, timeout=1800)
    info = ffprobe(out)
    return {"elapsed_sec": round(time.monotonic() - t0, 2), "bytes": out.stat().st_size,
            "audio_streams": sum(1 for s in info["streams"] if s["codec_type"] == "audio"),
            "video_streams": sum(1 for s in info["streams"] if s["codec_type"] == "video"),
            "streams": info["streams"], "duration": info["duration"], "sha256": sha256_file(out)}


def dir_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


class DiskSampler(threading.Thread):
    def __init__(self, path: Path, interval: float = 2.0):
        super().__init__(daemon=True)
        self.path, self.interval = path, interval
        self.peak_bytes = 0
        self.min_free = shutil.disk_usage(path).free
        self._halt = threading.Event()  # Thread._stop과 이름이 겹치지 않게 한다

    def run(self):
        while not self._halt.is_set():
            self.sample()
            self._halt.wait(self.interval)

    def sample(self):
        self.peak_bytes = max(self.peak_bytes, dir_bytes(self.path))
        self.min_free = min(self.min_free, shutil.disk_usage(self.path).free)

    def stop(self):
        self._halt.set()
        self.join()
        self.sample()


def _summ_waverep(out: dict) -> dict:
    keep = {k: out.get(k) for k in ("status", "reason_code", "video", "timing", "memory")}
    keep["device_used"] = (out.get("model") or {}).get("device_used")
    keep["frame_logit"] = (out.get("raw_metrics") or {}).get("frame_logit")
    # 구간별 통계용: 프레임 번호와 logit 숫자만 남긴다(영상 내용 없음)
    keep["frames"] = [{"index": f.get("index"), "logit": f.get("logit")} for f in out.get("frames") or []]
    keep["sampling"] = out.get("sampling")
    return keep


def _summ_syncnet(out: dict) -> dict:
    return {k: out.get(k) for k in ("status", "reason_code", "offset_fps", "device_used", "segments")}


def _summ_motionphys(out: dict) -> dict:
    return {k: out.get(k) for k in ("status", "reason_code", "device_used", "variants")}


def run_real(who: str, source: str = "original") -> dict:
    """source: original(원본 MP4 영상 + WAV MKV) 또는 pre(docs/seamless-preprocess.md 전처리 MP4)."""
    p = pick()[who]
    result: dict = {"schema_version": SCHEMA_VERSION, "who": who, "file_id": p["file_id"],
                    "condition": "real_mkv_first_pair_check" if source == "original" else "real_preprocessed"}

    def prepare(job_dir: Path, stages: dict) -> Path:
        if source == "original":
            media = job_dir / "media.mkv"
            result["mux"] = mux_real(p["files"]["mp4"], p["files"]["wav"], media)
            stages["preprocessing_mux_sec"] = result["mux"]["elapsed_sec"]
            return media
        return stage_copy(PILOT_DIR / "pre" / f"{who}.mp4", job_dir, result, stages)

    try:
        return run_job(prepare, result)
    finally:
        name = "real" if source == "original" else "pre"
        write_json(PILOT_DIR / f"inspect/{who}.{name}.json", result)


def stage_copy(src: Path, job_dir: Path, result: dict, stages: dict) -> Path:
    """Worker처럼 허가 미디어를 작업 폴더로 복사한다."""
    media = job_dir / f"media{src.suffix}"
    t0 = time.monotonic()
    shutil.copyfile(src, media)
    result["staged"] = {"bytes": media.stat().st_size, "sha256": sha256_file(media)}
    stages["preprocessing_copy_sec"] = round(time.monotonic() - t0, 2)
    return media


def run_file(src: Path, work_root: Path | None = None, *, gate_only: bool = False) -> dict:
    """파일 하나를 Worker와 같은 Gate → 세 축으로 돌린 결과(수치·상태만). 기록은 호출자가 한다.

    gate_only: Gate까지만 돈다(job_status_equivalent = "finished/gate_only").
    """
    result: dict = {"schema_version": SCHEMA_VERSION}
    return run_job(lambda job_dir, stages: stage_copy(Path(src), job_dir, result, stages), result, work_root,
                   gate_only=gate_only)


def run_job(prepare, result: dict, work_root: Path | None = None, *, gate_only: bool = False) -> dict:
    """prepare(job_dir, stages) -> 미디어 경로. Gate와 세 축을 Worker와 같은 함수·순서·제한으로 돌린다."""
    from server.axes import AxisContext
    from server.axes import alignment, physics
    from server.axes import signal as signal_axis
    from server.axes.alignment import syncnet as syncnet_mod
    from server.axes.physics import motionphys as motionphys_mod
    from server.config import Settings
    from server.gate.runner import run_gate_process
    from server.jobs import worker
    from server.fusion import load_active

    settings = Settings.from_env()
    raw: dict[str, dict] = {}

    # Worker가 부르는 축 모듈은 그대로 두고, 실행기 반환값만 기록용으로 받아 둔다
    orig_w, orig_s, orig_m = signal_axis.run_waverep, syncnet_mod.run_syncnet, motionphys_mod.run_motionphys

    def rec(name, fn, summ):
        def wrapped(*a, **k):
            out = fn(*a, **k)
            raw[name] = summ(out)
            return out
        return wrapped

    signal_axis.run_waverep = rec("waverep", orig_w, _summ_waverep)
    syncnet_mod.run_syncnet = rec("syncnet", orig_s, _summ_syncnet)
    motionphys_mod.run_motionphys = rec("motionphys", orig_m, _summ_motionphys)

    work_root = work_root or SEAMLESS / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    result.update({"settings": {k: v for k, v in asdict(settings).items()
                                if "timeout" in k or "device" in k or k.startswith("job_")},
                   "disk_free_before": shutil.disk_usage(work_root).free})
    job_dir = Path(tempfile.mkdtemp(prefix="job-", dir=work_root)).resolve()
    sampler = DiskSampler(job_dir)
    sampler.start()
    stages = {}
    try:
        started = time.monotonic()
        deadline = [started + settings.job_timeout_seconds]
        timed_out = []

        def heartbeat() -> bool:
            if time.monotonic() > deadline[0]:
                timed_out.append(True)
                return False
            return True

        media = prepare(job_dir, stages)

        t0 = time.monotonic()
        try:
            gate = run_gate_process(media, job_dir, settings=settings,
                                    timeout_seconds=max(deadline[0] - time.monotonic(), 0.0), on_tick=heartbeat)
        except Exception as e:
            from server.gate.types import GateResult
            gate = GateResult(None, "gate_error")
            result["gate_exception"] = type(e).__name__
        stages["gate_sec"] = round(time.monotonic() - t0, 2)
        segments = tuple((s.start_sec, s.end_sec) for s in gate.eligible_segments)
        result["gate"] = gate.to_dict()
        if gate.reason_code not in worker.GATE_FAILURES:
            eligible = sum(e - s for s, e in segments)
            limit = settings.job_timeout_after_gate(eligible)
            deadline[0] = started + limit
            result["job_timeout_after_gate_sec"] = limit
        if timed_out:
            result["job_status_equivalent"] = "failed/timeout (gate)"
        elif not segments:
            result["job_status_equivalent"] = "finished/gate_rejection"
        elif gate_only:
            result["job_status_equivalent"] = "finished/gate_only"
        else:
            ctx = AxisContext(job_dir=job_dir, settings=settings, media_path=media, segments=segments,
                              heartbeat=heartbeat, bundle=load_active(settings))
            result["bundle_active"] = ctx.bundle is not None
            axes = {}
            for stage, axis_name, module in worker.AXES:
                ctx.device_used = None
                ctx.timeout_seconds = max(deadline[0] - time.monotonic(), 0.0)
                t0 = time.monotonic()
                axes[axis_name] = worker.run_axis(axis_name, module.run, ctx)
                stages[f"{stage}_sec"] = round(time.monotonic() - t0, 2)
                axes[axis_name]["device_used"] = ctx.device_used
                axes[axis_name]["stage_timeout_given_sec"] = round(ctx.timeout_seconds, 1)
                if timed_out:
                    result["job_status_equivalent"] = f"failed/timeout ({stage})"
                    break
            else:
                result["job_status_equivalent"] = "finished"
            result["axes"] = axes
            result["explanations"] = ctx.explanations
            result["axis_raw"] = raw
        stages["total_sec"] = round(time.monotonic() - started, 2)
    finally:
        signal_axis.run_waverep, syncnet_mod.run_syncnet, motionphys_mod.run_motionphys = orig_w, orig_s, orig_m
        try:
            sampler.stop()
        except Exception as e:  # 표본 실패가 결과 기록과 작업 폴더 삭제를 막지 않는다
            result["disk_sampler_error"] = type(e).__name__
        result["stages"] = stages
        result["disk"] = {"job_dir_peak_bytes": sampler.peak_bytes, "min_free_bytes": sampler.min_free,
                          "sample_interval_sec": sampler.interval}
        shutil.rmtree(job_dir, ignore_errors=True)
        result["disk"]["job_dir_removed"] = not job_dir.exists()
        result["disk_free_after"] = shutil.disk_usage(work_root).free
    return result


def summarize(res: dict | None) -> dict:
    """run 결과 JSON 하나를 비교표 한 열로 줄인다. 없는 값은 None(표에서 '—')."""
    if res is None:
        return {}
    g = res.get("gate") or {}
    el = g.get("eligible_segments") or []
    media = g.get("media") or {}
    qs = [s["quality"] for s in el if s.get("quality")]
    excl: dict[str, float] = {}
    for x in g.get("excluded_segments") or []:
        excl[x.get("reason_code")] = excl.get(x.get("reason_code"), 0.0) + x["end_sec"] - x["start_sec"]
    axes = res.get("axes") or {}
    raw = res.get("axis_raw") or {}
    st = res.get("stages") or {}
    sync = raw.get("syncnet") or {}
    segs = sync.get("segments") or []
    tracked = [t for sg in segs for t in (sg.get("tracks") or [])]

    def ax(name):
        a = axes.get(name)
        return None if a is None else f"{a['status']}" + (f" / {a['reason_code']}" if a.get("reason_code") else "")

    dur = media.get("duration_sec")
    eligible = sum(x["end_sec"] - x["start_sec"] for x in el)
    return {
        "job": res.get("job_status_equivalent"),
        "media": None if not media else f"{media['width']}×{media['height']}, {dur:.1f}s",
        "gate": g.get("reason_code") or ("완료" if media else None),
        "gate_sec": st.get("gate_sec"),
        "eligible": None if not media else f"{len(el)}개, {eligible:.1f}s ({eligible / dur:.1%})",
        "excluded": None if not excl else ", ".join(f"{k} {v:.1f}" for k, v in sorted(excl.items(), key=lambda kv: -kv[1])),
        "face_h": None if not qs else f"{min(q['face_height_px'] for q in qs):g}–{max(q['face_height_px'] for q in qs):g}px",
        "face_ratio": None if not qs else f"{min(q['face_height_ratio'] for q in qs):g}–{max(q['face_height_ratio'] for q in qs):g}",
        "sharpness": None if not qs else f"{min(q['sharpness'] for q in qs):g}–{max(q['sharpness'] for q in qs):g}",
        "waverep": ax("signal"),
        "waverep_frames": ((raw.get("waverep") or {}).get("frame_logit") or {}).get("frames"),
        "waverep_sec": st.get("waverep_sec"),
        "motionphys": ax("physics"),
        "motionphys_sec": st.get("motionphys_sec"),
        "syncnet": ax("alignment"),
        "syncnet_segments": None if not segs else (
            f"{len(segs)}개 중 짧음 {sum(1 for x in segs if x['reason_code'] == 'segment_too_short')}, "
            f"트랙 있음 {sum(1 for x in segs if x.get('tracks'))}, 트랙 없음 "
            f"{sum(1 for x in segs if x['reason_code'] == 'tracking_failed')}"),
        "syncnet_offsets": None if not tracked else sorted({t["offset_frames"] for t in tracked}),
        "syncnet_sec": st.get("syncnet_sec"),
        "total_sec": st.get("total_sec"),
        "job_limit_sec": res.get("job_timeout_after_gate_sec"),
        "job_dir_peak_mb": round(res["disk"]["job_dir_peak_bytes"] / 1e6, 1) if res.get("disk") else None,
    }


ROWS = (("job", "Worker 기준 작업 상태"), ("media", "Gate가 읽은 입력"), ("gate", "Gate"), ("gate_sec", "Gate 시간(s)"),
        ("eligible", "적합 구간"), ("excluded", "제외 구간(사유별 초)"), ("face_h", "얼굴 높이(구간 중앙값 범위)"),
        ("face_ratio", "짧은 변 대비"), ("sharpness", "선명도"), ("waverep", "WaveRep"),
        ("waverep_frames", "WaveRep 프레임"), ("waverep_sec", "WaveRep 시간(s)"), ("motionphys", "MotionPhys"),
        ("motionphys_sec", "MotionPhys 시간(s)"), ("syncnet", "SyncNet"), ("syncnet_segments", "SyncNet 구간"),
        ("syncnet_offsets", "SyncNet 오프셋(25fps 프레임)"), ("syncnet_sec", "SyncNet 시간(s)"),
        ("total_sec", "합계(s)"), ("job_limit_sec", "Gate 뒤 작업 제한(s)"), ("job_dir_peak_mb", "작업 폴더 최대(MB)"))


def compare_table() -> str:
    cols = {}
    for who in ("A", "B"):
        for name in ("real", "pre"):
            path = PILOT_DIR / f"inspect/{who}.{name}.json"
            cols[(who, name)] = summarize(json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)
    head = "| 항목 | A 원본 | A 전처리 | B 원본 | B 전처리 |\n|---|---|---|---|---|"
    lines = [head]
    for key, label in ROWS:
        vals = [cols[(w, n)].get(key) for w in ("A", "B") for n in ("real", "pre")]
        lines.append(f"| {label} | " + " | ".join("—" if v is None else str(v) for v in vals) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("files")
    sub.add_parser("compare")
    r = sub.add_parser("run")
    r.add_argument("--who", choices=("A", "B"), required=True)
    r.add_argument("--input", choices=("original", "pre"), default="original",
                   help="original: 원본 영상 + WAV MKV, pre: docs/seamless-preprocess.md 전처리 MP4")
    opt = ap.parse_args(argv)
    if opt.cmd == "compare":
        print(compare_table())
        return 0
    if opt.cmd == "files":
        rep = files_report()
        print(json.dumps({w: {"timeline": d["timeline"], "mp4_has_audio": d["mp4_has_audio"],
                              "vad": {k: v for k, v in d["vad"].items() if k != "json_keys"},
                              "decode": d["decode"], "sha256_matches_fetch": d["sha256_matches_fetch"]}
                          for w, d in rep["participants"].items()} | {"cross": rep.get("cross"),
                                                                     "pair": rep["pair"]},
                         ensure_ascii=False, indent=2))
    else:
        res = run_real(opt.who, opt.input)
        print(json.dumps({k: res.get(k) for k in ("job_status_equivalent", "stages", "disk",
                                                   "job_timeout_after_gate_sec")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
