"""scripts/seamless_preprocess.py: 25초 창 선택 규칙과 최종 인코딩 인자.

실제 Seamless 미디어는 쓰지 않는다. 인코딩 시험은 FFmpeg가 있을 때 합성 영상으로만 돈다.
"""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from scripts import seamless_first_pair as fp
from scripts import seamless_preprocess as pp


def brute(vad, allowed, length, step=0.01):
    """0.01초 격자로 찾은 최대 발화량(검산용)."""
    best = -1.0
    for lo, hi in allowed:
        s = lo
        while s <= hi + 1e-9:
            best = max(best, pp.speech_in(vad, s, length))
            s += step
    return best


def test_speech_in_clips_at_window_edges():
    vad = [(0.0, 2.0), (9.0, 12.0)]
    assert pp.speech_in(vad, 1.0, 10.0) == pytest.approx(1.0 + 2.0)
    assert pp.speech_in(vad, 12.0, 10.0) == 0.0


def test_select_maximizes_speech_and_matches_brute_force():
    rng = np.random.default_rng(0)
    for _ in range(30):
        t, vad = 0.0, []
        while t < 100:
            t += float(rng.uniform(0.1, 6.0))
            d = float(rng.uniform(0.1, 5.0))
            vad.append((round(t, 2), round(min(t + d, 100.0), 2)))
            t += d
        w = pp.select_window(vad, [(0.0, 75.0)], 25.0)
        assert w["speech_sec"] == pytest.approx(brute(vad, [(0.0, 75.0)], 25.0), abs=1e-6)
        assert 0.0 <= w["start_sec"] <= 75.0 and w["end_sec"] == pytest.approx(w["start_sec"] + 25.0)


def test_tie_picks_earliest():
    # 발화 5초 두 덩어리가 멀리 떨어져 있다: 어느 쪽을 담아도 5초. 앞쪽 창을 고른다
    vad = [(10.0, 15.0), (60.0, 65.0)]
    w = pp.select_window(vad, [(0.0, 75.0)], 25.0)
    assert w["speech_sec"] == 5.0
    assert w["start_sec"] == 0.0          # [0,25]가 이미 5초를 담고, 가장 앞이다
    # 발화가 전혀 없으면 허용 범위 맨 앞
    assert pp.select_window([], [(3.0, 50.0)], 25.0)["start_sec"] == 3.0


def test_face_window_respects_media_bounds():
    vad = [(0.0, 1.0), (300.0, 320.0)]
    w = pp.face_window(vad, video_start=0.033, video_end=320.019, audio_end=320.0)
    assert w["end_sec"] <= 320.0 and w["start_sec"] >= 0.033
    assert w["start_sec"] == 295.0 and w["speech_sec"] == pytest.approx(20.0)
    assert pp.face_window(vad, 0.0, 20.0, 20.0) is None   # 25초보다 짧다


def test_same_speaker_window_never_overlaps_face():
    vad = [(10.0, 40.0), (100.0, 110.0), (200.0, 203.0)]
    face = pp.face_window(vad, 0.0, 300.0, 300.0)
    assert (face["start_sec"], face["speech_sec"]) == (10.0, 25.0)
    drive = pp.same_speaker_driving_window(vad, 300.0, face)
    assert drive["end_sec"] <= face["start_sec"] or drive["start_sec"] >= face["end_sec"]
    # 얼굴 창 바로 뒤(35초부터)는 남은 5초를 담는다. 100~110의 10초를 담는 창이 더 많다
    assert drive["speech_sec"] == pytest.approx(10.0)
    assert drive["start_sec"] == pytest.approx(85.0)      # 동점 중 가장 앞(85 ≤ s ≤ 100)


def test_same_speaker_touching_boundary_allowed_and_unavailable():
    vad = [(0.0, 50.0)]
    face = {"start_sec": 25.0, "end_sec": 50.0}
    drive = pp.same_speaker_driving_window(vad, 50.0, face)
    assert (drive["start_sec"], drive["end_sec"]) == (0.0, 25.0)   # 경계가 맞닿는다
    assert pp.same_speaker_driving_window(vad, 40.0, {"start_sec": 10.0, "end_sec": 35.0}) is None


def test_encode_args_use_emulator_profile_and_single_wav_track(tmp_path):
    args = pp.build_encode_args("ffmpeg", tmp_path / "v.mp4", tmp_path / "a.wav", 12.5, tmp_path / "o.mp4")
    joined = " ".join(args)
    p = pp.PROFILES[pp.VIDEO_PROFILE_ID]
    assert (p.encoder, p.crf, p.preset, p.short_side) == ("libx264", 20, "medium", 1080)
    assert "-c:v libx264 -preset medium -crf 20" in joined and "videotoolbox" not in joined
    assert "-map 0:v:0 -map 1:a:0" in joined
    assert "-ss 12.500000 -t 25.000000" in joined
    # -ss/-t가 두 입력 뒤(출력 쪽)에 있다
    assert args.index("-ss") > args.index(str(tmp_path / "a.wav"))
    assert "-c:a aac -profile:a aac_low -ar 48000 -ac 1 -b:a 192k" in joined


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")
def test_encode_cuts_both_streams_on_same_timeline(tmp_path):
    mp4, wav = tmp_path / "v.mp4", tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=108x192:rate=30000/1001:duration=8",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=8", "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(mp4)], check=True)
    # WAV: 무작위 잡음(상관으로 위치를 찾을 수 있게)
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(48000 * 8).astype(np.float32) * 0.2
    raw = tmp_path / "n.f32"
    raw.write_bytes(noise.tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", "48000", "-ac", "1", "-i", str(raw),
                    "-c:a", "pcm_f32le", str(wav)], check=True)
    out = tmp_path / "o.mp4"
    enc = pp.encode(mp4, wav, 2.0, out, length=4.0)
    probe = fp.ffprobe(out)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    assert (v["width"], v["height"], v["r_frame_rate"]) == (1080, 1920, "30000/1001")
    assert len(a) == 1 and a[0]["codec_name"] == "aac" and a[0]["channels"] == 1
    assert probe["duration"] == pytest.approx(4.0, abs=0.1)
    lag = fp.xcorr_lag(fp.pcm_window(wav, "0:a:0", 2.0, 3.5), fp.pcm_window(out, "0:a:0", 0.0, 3.5))
    assert abs(lag["lag_sec"]) < 0.002 and lag["peak_ncc"] > 0.8
    assert enc["bytes"] == out.stat().st_size and len(enc["sha256"]) == 64
    assert "v.mp4" in enc["args"] and str(tmp_path) not in " ".join(enc["args"])
