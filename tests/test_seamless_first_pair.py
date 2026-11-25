"""scripts/seamless_first_pair.py의 보조 함수: 시간차 추정, VAD 요약(전사 내용 미보존), 실제 조건 MKV 구성.

실제 Seamless 미디어는 쓰지 않는다. MKV 시험은 FFmpeg가 있을 때만 합성 영상으로 돈다.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from scripts import seamless_first_pair as fp


def test_xcorr_lag_sign_and_size():
    rng = np.random.default_rng(0)
    ref = rng.standard_normal(8000 * 5).astype(np.float32)
    delay = 400  # 50ms
    late = np.concatenate([np.zeros(delay, np.float32), ref[:-delay]])
    out = fp.xcorr_lag(ref, late)
    assert out["lag_sec"] == pytest.approx(0.05, abs=1e-4)
    assert out["peak_ncc"] > 0.9
    early = np.concatenate([ref[delay:], np.zeros(delay, np.float32)])
    assert fp.xcorr_lag(ref, early)["lag_sec"] == pytest.approx(-0.05, abs=1e-4)


def test_xcorr_unrelated_signals_low_peak():
    rng = np.random.default_rng(1)
    a = rng.standard_normal(8000 * 5).astype(np.float32)
    b = rng.standard_normal(8000 * 5).astype(np.float32)
    assert fp.xcorr_lag(a, b)["peak_ncc"] < 0.1


def test_vad_summary_counts_only(tmp_path):
    secret = "이 문장은 결과에 남으면 안 된다"
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"id": "x",
                             "metadata:vad": [{"start": 0.0, "end": 0.5}, {"start": 3.0, "end": 6.0}],
                             "metadata:transcript": [{"start": 3.0, "end": 6.0, "transcript": secret,
                                                      "words": []}]}), encoding="utf-8")
    s = fp.vad_summary(p, 10.0)
    assert s["vad_segments"] == 2 and s["vad_speech_sec"] == 3.5 and s["vad_speech_ratio"] == 0.35
    assert s["vad_segments_ge_2s"] == 1 and s["transcript_entries"] == 1
    assert (s["vad_first_start"], s["vad_last_end"]) == (0.0, 6.0)
    assert secret not in json.dumps(s, ensure_ascii=False)


def test_disk_sampler_tracks_peak(tmp_path):
    d = tmp_path / "job"
    d.mkdir()
    sampler = fp.DiskSampler(d, interval=0.05)
    (d / "a.bin").write_bytes(b"x" * 5000)
    sampler.sample()
    (d / "a.bin").unlink()
    sampler.sample()
    assert sampler.peak_bytes == 5000


def test_disk_sampler_thread_start_stop(tmp_path):
    sampler = fp.DiskSampler(tmp_path, interval=0.01)
    sampler.start()
    (tmp_path / "b.bin").write_bytes(b"x" * 100)
    sampler.stop()
    assert not sampler.is_alive()
    assert sampler.peak_bytes == 100


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")
def test_mux_real_keeps_video_copy_and_single_wav_track(tmp_path):
    mp4, wav = tmp_path / "v.mp4", tmp_path / "a.wav"
    # 자체 오디오가 있는 MP4와 별도 WAV
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x96:rate=30:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
                    "-c:a", "pcm_f32le", str(wav)], check=True)
    out = fp.mux_real(mp4, wav, tmp_path / "media.mkv")
    assert out["video_streams"] == 1 and out["audio_streams"] == 1
    audio = next(s for s in out["streams"] if s["codec_type"] == "audio")
    video = next(s for s in out["streams"] if s["codec_type"] == "video")
    assert audio["codec_name"] == "pcm_f32le"        # WAV 그대로, MP4의 AAC가 아니다
    assert video["codec_name"] == "h264"             # 재인코딩하지 않았다
