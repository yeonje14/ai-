"""Worker가 감시하는 프로세스에서 오디오를 읽고 등록 영상의 분석 구간을 자른다."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import astuple
from pathlib import Path

from server.gate import probe, vad
from server.gate.types import GateConfig
from server.ingest.speech_window import CLIP_NAME, WINDOW_SECONDS, WindowError, select_window


def _speech(path, index, duration):
    import webrtcvad

    config = GateConfig()
    detector = webrtcvad.Vad(config.vad_aggressiveness)
    # 원본 시작점 기준으로 오디오 PTS의 공백을 채운다. PCM은 항상 정수 개 프레임씩 읽는다.
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-t", str(duration),
           "-map", f"0:{index}", "-vn", "-af", "aresample=async=1:first_pts=0",
           "-ac", "1", "-ar", str(vad.SAMPLE_RATE), "-f", "s16le", "-"]
    frame_bytes = vad.SAMPLE_RATE * config.vad_frame_ms // 1000 * 2
    flags = bytearray()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        try:
            while data := proc.stdout.read(frame_bytes * 128):
                flags.extend(vad.speech_flags(data, config, detector))
        finally:
            proc.stdout.close()
        if proc.wait() != 0:
            raise WindowError("media_unreadable")
    return vad.flags_to_intervals(flags, config)


def _prepare(path, duration):
    local_video = duration is None
    if local_video:
        media = probe.probe(path)
        if media is None or not media.has_audio:
            return None
        duration = media.duration_sec
    if duration <= WINDOW_SECONDS:
        return select_window(duration, ())
    config = GateConfig()
    index = vad.select_audio_index(path, config.subprocess_timeout_sec)
    window = select_window(duration, _speech(path, index, duration))
    if local_video:
        # 키프레임 앞뒤가 섞이지 않게 디코딩 후 무손실로 저장한다.
        command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", str(window.start_sec),
                   "-i", str(path), "-t", str(WINDOW_SECONDS), "-map", "0:v:0", "-map", f"0:{index}",
                   "-map_metadata", "-1", "-map_chapters", "-1", "-c:v", "libx264", "-qp", "0",
                   "-preset", "veryfast", "-c:a", "flac", str(path.parent / CLIP_NAME)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return window


if __name__ == "__main__":
    try:
        media_path = Path(sys.argv[1])
        duration_sec = float(sys.argv[2]) if len(sys.argv) == 3 else None
        window = _prepare(media_path, duration_sec)
        print(json.dumps(astuple(window) if window is not None else None, allow_nan=False))
    except (WindowError, vad.AudioDecodeError, subprocess.CalledProcessError):
        sys.exit(2)
