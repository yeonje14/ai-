"""음성 구간 검출(VAD). webrtcvad를 쓴다. torch가 필요 없다.

오디오는 FFmpeg가 표준 출력으로 넘긴 PCM을 메모리에서만 다루고 파일로 남기지 않는다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Sequence

from server.gate.types import GateConfig

SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 2


class AudioDecodeError(RuntimeError):
    pass


def decode_pcm(path: Path, timeout_sec: float) -> bytes:
    """16kHz 모노 16비트 PCM."""
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error",
        "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "s16le", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_sec, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioDecodeError(type(exc).__name__) from exc
    if proc.returncode != 0:
        raise AudioDecodeError(f"ffmpeg exit {proc.returncode}")
    return proc.stdout


def speech_flags(pcm: bytes, config: GateConfig) -> list[bool]:
    """vad_frame_ms 단위 프레임마다 음성 여부."""
    import webrtcvad

    vad = webrtcvad.Vad(config.vad_aggressiveness)
    frame_bytes = SAMPLE_RATE * config.vad_frame_ms // 1000 * _BYTES_PER_SAMPLE
    return [
        vad.is_speech(pcm[i:i + frame_bytes], SAMPLE_RATE)
        for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes)
    ]


def flags_to_intervals(flags: Sequence[bool], config: GateConfig) -> list[tuple[float, float]]:
    """프레임 단위 판정을 구간으로 묶는다. 짧은 쉼은 잇고, 짧은 조각은 버린다."""
    step = config.vad_frame_ms / 1000
    raw: list[list[float]] = []
    start: Optional[int] = None
    for i, flag in enumerate(list(flags) + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            raw.append([start * step, i * step])
            start = None

    merged: list[list[float]] = []
    for seg in raw:
        if merged and seg[0] - merged[-1][1] <= config.vad_merge_gap_sec + 1e-9:
            merged[-1][1] = seg[1]
        else:
            merged.append(seg)
    return [
        (round(a, 3), round(b, 3))
        for a, b in merged
        if b - a >= config.vad_min_speech_sec - 1e-9
    ]


def detect_speech(path: Path, config: GateConfig) -> list[tuple[float, float]]:
    pcm = decode_pcm(path, config.subprocess_timeout_sec)
    return flags_to_intervals(speech_flags(pcm, config), config)
