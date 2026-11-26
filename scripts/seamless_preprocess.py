"""Seamless 파일럿 입력 전처리: 25초 창 선택과 최종 인코딩 (docs/seamless-preprocess.md, 커밋 6bc3493).

    conda activate trinity
    python scripts/seamless_preprocess.py            # pilot#0: 창 4개 계산·기록, A·B 실제 조건 인코딩

- 창은 공식 Meta VAD 발화량이 가장 많은 25초 창이다(동점이면 앞쪽). A 얼굴 창, B 얼굴 창,
  A 구동 음성 창(A 얼굴 창과 겹치지 않음), B 구동 음성 창(= B 얼굴 창)을 계산한다.
  구동 음성 창은 기록만 한다. 합성은 하지 않는다.
- 최종 인코딩: 영상은 training.emulator의 x264-crf20-1080p 프로파일 설정, 오디오는 WAV → AAC-LC
  48kHz 모노 192kbps, MP4. 원본 MP4 영상과 같은 참가자 WAV를 한 명령에서 출력 쪽 -ss/-t로 함께 자른다.
- 결과: data/research/seamless/pilot/pilot-00/pre/ (Git 제외). 내용(전사·프레임)은 기록하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from training.emulator.profiles import PROFILES  # noqa: E402
from training.emulator.video import scale_filter  # noqa: E402

WINDOW_SEC = 25.0
VIDEO_PROFILE_ID = "x264-crf20-1080p"
AUDIO_ARGS = ("-c:a", "aac", "-profile:a", "aac_low", "-ar", "48000", "-ac", "1", "-b:a", "192k")
ROUND = 6   # 마이크로초

FACE_UNAVAILABLE = "window_unavailable"
SAME_SPEAKER_UNAVAILABLE = "same_speaker_unavailable"


# ---------- 창 선택 (순수 함수) ----------

def speech_in(vad: Sequence[tuple[float, float]], start: float, length: float = WINDOW_SEC) -> float:
    end = start + length
    return sum(max(0.0, min(e, end) - max(b, start)) for b, e in vad)


def select_window(vad: Sequence[tuple[float, float]], allowed: Sequence[tuple[float, float]],
                  length: float = WINDOW_SEC) -> Optional[dict]:
    """allowed: 시작점 s의 허용 구간 [lo, hi] 목록. 발화량 최대, 동점이면 작은 s. 없으면 None.

    발화량은 s에 대해 구간마다 선형이라 최댓값은 VAD 경계(b, e - length)나 허용 구간 끝에서 나온다.
    """
    candidates: set[float] = set()
    for lo, hi in allowed:
        lo, hi = round(lo, ROUND), round(hi, ROUND)
        if hi < lo:
            continue
        candidates.update((lo, hi))
        for b, e in vad:
            for x in (round(b, ROUND), round(e - length, ROUND)):
                if lo <= x <= hi:
                    candidates.add(x)
    if not candidates:
        return None
    best = min(candidates, key=lambda s: (-round(speech_in(vad, s, length), ROUND), s))
    return {"start_sec": best, "end_sec": round(best + length, ROUND),
            "speech_sec": round(speech_in(vad, best, length), ROUND), "candidates": len(candidates)}


def face_window(vad, video_start: float, video_end: float, audio_end: float,
                length: float = WINDOW_SEC) -> Optional[dict]:
    lo = max(video_start, 0.0)
    hi = min(video_end, audio_end) - length
    return select_window(vad, [(lo, hi)], length)


def same_speaker_driving_window(vad, audio_end: float, face: dict,
                                length: float = WINDOW_SEC) -> Optional[dict]:
    """얼굴 창과 겹치지 않는 창(경계가 맞닿는 것은 허용)."""
    allowed = [(0.0, face["start_sec"] - length), (face["end_sec"], audio_end - length)]
    return select_window(vad, allowed, length)


def load_vad(json_path: Path) -> list[tuple[float, float]]:
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    return [(float(v["start"]), float(v["end"])) for v in meta.get("metadata:vad") or []]


# ---------- 인코딩 ----------

def build_encode_args(ffmpeg: str, mp4: Path, wav: Path, start: float, out: Path,
                      length: float = WINDOW_SEC) -> list[str]:
    p = PROFILES[VIDEO_PROFILE_ID]
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
        "-i", str(mp4), "-i", str(wav),
        "-map", "0:v:0", "-map", "1:a:0", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
        # 출력 쪽 -ss/-t: 두 입력을 같은 시간축에서 함께 자른다
        "-ss", f"{start:.6f}", "-t", f"{length:.6f}",
        "-vf", scale_filter(p), "-filter_threads", "1",
        "-c:v", p.encoder, "-preset", p.preset, "-crf", str(p.crf), "-pix_fmt", p.pix_fmt,
        "-threads", str(p.threads),
        *AUDIO_ARGS,
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-movflags", "+faststart", "-f", "mp4", str(out),
    ]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffmpeg_version(ffmpeg: str = "ffmpeg") -> str:
    out = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=True).stdout
    return out.splitlines()[0]


def encode(mp4: Path, wav: Path, start: float, out: Path, ffmpeg: str = "ffmpeg",
           length: float = WINDOW_SEC) -> dict:
    out.unlink(missing_ok=True)
    args = build_encode_args(ffmpeg, mp4, wav, start, out, length)
    t0 = time.monotonic()
    subprocess.run(args, check=True, timeout=3600)
    return {"elapsed_sec": round(time.monotonic() - t0, 2), "bytes": out.stat().st_size,
            "sha256": sha256_file(out), "args": [Path(a).name if a in (str(mp4), str(wav), str(out)) else a
                                                 for a in args[1:]]}


def _gray_frames(path: Path, sel_range: Optional[tuple[float, float]] = None, dur: Optional[float] = None,
                 size: tuple[int, int] = (54, 96)):
    import re

    import numpy as np
    w, h = size
    sel = "" if sel_range is None else f"select='between(t,{sel_range[0]:.6f},{sel_range[1]:.6f})',"
    cmd = ["ffmpeg", "-nostdin", "-v", "info", "-i", str(path)]
    if dur is not None:
        cmd += ["-t", f"{dur}"]
    cmd += ["-map", "0:v:0", "-vf", f"{sel}scale={w}:{h},format=gray,showinfo", "-fps_mode", "passthrough",
            "-f", "rawvideo", "-"]
    proc = subprocess.run(cmd, capture_output=True, check=True, timeout=1800)
    pts = [float(m) for m in re.findall(rb"pts_time:([-\d.]+)", proc.stderr)]
    frames = np.frombuffer(proc.stdout, np.uint8).reshape(-1, h, w).astype(np.float32)
    return pts, frames


def frame_alignment(src_mp4: Path, out_mp4: Path, start: float, n: int = 3) -> dict:
    """출력 앞 n프레임을 원본 [start-0.15, start+0.2] 프레임과 맞춰 영상의 시간 어긋남을 잰다.

    오디오는 원본 WAV의 start부터 그대로 잘리므로(상관 시간차 0), 어긋남 = 출력 pts − (원본 pts − start).
    양수면 출력에서 영상이 오디오보다 늦다.
    """
    opts, oa = _gray_frames(out_mp4, dur=0.2)
    ipts, ia = _gray_frames(src_mp4, sel_range=(start - 0.15, start + 0.2))
    rows = []
    for k in range(min(n, len(oa))):
        mse = [float(((oa[k] - x) ** 2).mean()) for x in ia]
        order = sorted(range(len(mse)), key=mse.__getitem__)
        j = order[0]
        rows.append({"out_pts": opts[k], "src_pts": ipts[j], "offset_ms": round((opts[k] - (ipts[j] - start)) * 1000, 1),
                     "mse": round(mse[j], 3), "second_mse": round(mse[order[1]], 3) if len(order) > 1 else None})
    offsets = {r["offset_ms"] for r in rows}
    return {"frames": rows, "video_minus_audio_ms": rows[0]["offset_ms"] if len(offsets) == 1 else None,
            "consistent": len(offsets) == 1}


# ---------- pilot#0 실행 ----------

def run_pilot0() -> dict:
    from scripts import seamless_first_pair as fp

    p = fp.pick()
    files = json.loads((fp.PILOT_DIR / "inspect/files.json").read_text(encoding="utf-8"))["participants"]
    out_dir = fp.PILOT_DIR / "pre"
    out_dir.mkdir(parents=True, exist_ok=True)
    rec: dict = {"rule_commit": "6bc3493", "window_sec": WINDOW_SEC, "video_profile": PROFILES[VIDEO_PROFILE_ID].to_dict(),
                 "audio_args": list(AUDIO_ARGS), "ffmpeg_version": ffmpeg_version(), "windows": {}, "encodes": {}}
    vad = {w: load_vad(p[w]["files"]["json"]) for w in ("A", "B")}
    tl = {w: files[w]["timeline"] for w in ("A", "B")}

    t0 = time.monotonic()
    faces = {}
    for w in ("A", "B"):
        t = tl[w]
        faces[w] = face_window(vad[w], t["video_start_sec"], t["video_start_sec"] + t["video_duration_sec"],
                               t["wav_duration_sec"])
        rec["windows"][f"{w}_face"] = faces[w] or {"status": FACE_UNAVAILABLE}
    a_drive = None if faces["A"] is None else same_speaker_driving_window(vad["A"], tl["A"]["wav_duration_sec"],
                                                                          faces["A"])
    rec["windows"]["A_driving_same_speaker"] = a_drive or {"status": SAME_SPEAKER_UNAVAILABLE}
    rec["windows"]["B_driving_partner"] = (dict(faces["B"], source="B_face") if faces["B"]
                                           else {"status": FACE_UNAVAILABLE})
    rec["window_select_sec"] = round(time.monotonic() - t0, 4)
    for w in ("A", "B"):
        d = rec["windows"][f"{w}_face"]
        d["file_speech_sec"] = round(sum(e - b for b, e in vad[w]), 3)

    for w in ("A", "B"):
        if faces[w] is None:
            continue
        out = out_dir / f"{w}.mp4"
        enc = encode(p[w]["files"]["mp4"], p[w]["files"]["wav"], faces[w]["start_sec"], out)
        probe = fp.ffprobe(out)
        # 자른 오디오가 원본 WAV의 같은 구간과 맞는지: 출력 오디오 vs WAV[s, s+25]
        ref = fp.pcm_window(p[w]["files"]["wav"], "0:a:0", faces[w]["start_sec"], WINDOW_SEC)
        got = fp.pcm_window(out, "0:a:0", 0.0, WINDOW_SEC)
        enc.update({"probe": probe, "audio_vs_source_wav_window": fp.xcorr_lag(ref, got),
                    "video_alignment": frame_alignment(p[w]["files"]["mp4"], out, faces[w]["start_sec"])})
        rec["encodes"][w] = enc
    fp.write_json(out_dir / "preprocess.json", rec)
    return rec


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    rec = run_pilot0()
    show = {"windows": rec["windows"], "window_select_sec": rec["window_select_sec"],
            "encodes": {w: {k: e[k] for k in ("elapsed_sec", "bytes", "sha256", "audio_vs_source_wav_window",
                                              "video_alignment")}
                        | {"video": next(s for s in e["probe"]["streams"] if s["codec_type"] == "video"),
                           "duration": e["probe"]["duration"]}
                        for w, e in rec["encodes"].items()}}
    print(json.dumps(show, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
