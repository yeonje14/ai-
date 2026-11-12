"""ffprobe로 길이·해상도·fps·회전·오디오 유무를 읽는다."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Optional

from server.gate.types import MediaInfo


def probe(path: Path, timeout_sec: float = 120.0) -> Optional[MediaInfo]:
    """읽을 수 없거나 영상 스트림이 없으면 None."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,avg_frame_rate,r_frame_rate,duration"
        ":stream_side_data=rotation",
        "-of", "json",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_sec, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return parse_probe(json.loads(proc.stdout))
    except (ValueError, KeyError, TypeError, ZeroDivisionError):
        return None


def parse_probe(data: dict) -> Optional[MediaInfo]:
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        return None
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
    width, height = int(video["width"]), int(video["height"])
    if duration <= 0 or fps <= 0 or width <= 0 or height <= 0:
        return None

    rotation = 0
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = int(round(float(side["rotation"]))) % 360
    if rotation in (90, 270):
        width, height = height, width
    return MediaInfo(
        duration_sec=round(duration, 3),
        width=width,
        height=height,
        fps=round(fps, 3),
        rotation=rotation,
        has_audio=has_audio,
    )


def _rate(value: Optional[str]) -> float:
    if not value or value in ("0/0", "0"):
        return 0.0
    return float(Fraction(value))
