"""기존 서버 Python에서 Gate를 격리 실행한다. torch/미디어 패키지는 여기서 import하지 않는다."""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from pydantic import TypeAdapter

from server.config import Settings
from server.gate.types import GateResult

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_ERROR = "gate_error"
GATE_TIMEOUT = "gate_timeout"
GATE_REASONS = frozenset({
    "media_unreadable", "audio_missing", "no_speech_detected", "no_mouth_movement",
    "no_face_detected", "speaker_unconfirmed", "low_resolution", "face_too_small",
    "too_blurry", "segment_too_short", GATE_ERROR, GATE_TIMEOUT,
})


def build_command(request: Path) -> list[str]:
    return [sys.executable, "-m", "server.gate.process", str(request)]


def parse_result(text: str) -> GateResult:
    """깨진 출력을 적합 구간으로 쓰지 않는다. 프로세스 경계에서 형식·범위를 검사한다."""
    result = TypeAdapter(GateResult).validate_json(text, strict=True)
    if result.reason_code is not None and result.reason_code not in GATE_REASONS:
        raise ValueError("unknown gate reason")
    if result.eligible_segments:
        if result.reason_code is not None or result.media is None:
            raise ValueError("inconsistent eligible result")
    elif result.reason_code is None:
        raise ValueError("missing rejection reason")
    if result.media is None:
        if result.eligible_segments or result.excluded_segments or result.reason_code not in {
            "media_unreadable", GATE_ERROR, GATE_TIMEOUT,
        }:
            raise ValueError("missing media")
        return result
    media = result.media
    if not all(math.isfinite(v) and v > 0 for v in (media.duration_sec, media.fps, media.width, media.height)):
        raise ValueError("invalid media bounds")
    previous_end = 0.0
    for segment in sorted((*result.eligible_segments, *result.excluded_segments), key=lambda s: s.start_sec):
        if not (math.isfinite(segment.start_sec) and math.isfinite(segment.end_sec)
                and previous_end <= segment.start_sec < segment.end_sec <= media.duration_sec):
            raise ValueError("invalid or overlapping segment")
        previous_end = segment.end_sec
        quality = segment.quality
        if quality and not all(math.isfinite(v) and v >= 0 for v in (
            quality.face_height_px, quality.face_height_ratio, quality.sharpness,
            quality.short_side_px, quality.face_frames,
        )):
            raise ValueError("invalid quality")
    if any(s.reason_code is not None for s in result.eligible_segments):
        raise ValueError("excluded segment marked eligible")
    if any(s.reason_code not in GATE_REASONS for s in result.excluded_segments):
        raise ValueError("missing exclusion reason")
    return result


def run_gate_process(
    media_path: Path,
    work_dir: Path,
    *,
    settings: Settings,
    timeout_seconds: float,
    on_tick: Callable[[], bool],
) -> GateResult:
    """작업 폴더 경로만 전달한다. 실패·제한시간 초과는 점수 없는 GateResult다.

    중단 시 FFmpeg를 포함한 프로세스 그룹을 종료한다. Worker가 on_tick에서 기록한
    취소/lease 상실/전체 제한시간 초과는 호출자에서 처리한다. stderr는 저장하지 않는다.
    """
    work_dir = work_dir.resolve()
    media_path = media_path.resolve()
    request = work_dir / "gate_request.json"
    output = work_dir / "gate_result.json"
    proc = None
    try:
        if media_path.parent != work_dir or not media_path.is_file():
            return GateResult(None, GATE_ERROR)
        output.unlink(missing_ok=True)
        request.write_text(json.dumps({
            "media": str(media_path),
            "model_dir": str(settings.gate_model_dir.resolve()),
            "models_config": str(settings.gate_models_config_path.resolve()),
        }), encoding="utf-8")
        if not on_tick():
            return GateResult(None, GATE_ERROR)
        deadline = time.monotonic() + min(settings.gate_timeout_seconds, timeout_seconds)
        proc = subprocess.Popen(
            build_command(request), cwd=REPO_ROOT, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return GateResult(None, GATE_TIMEOUT)
            try:
                code = proc.wait(timeout=min(remaining, settings.heartbeat_interval_seconds))
                if not on_tick():
                    return GateResult(None, GATE_ERROR)
                if code != 0:
                    return GateResult(None, GATE_ERROR)
                return parse_result(output.read_text(encoding="utf-8"))
            except subprocess.TimeoutExpired:
                if not on_tick():
                    return GateResult(None, GATE_ERROR)
    except Exception:
        # 패키지/모델 누락, 잘못된 JSON, 프로세스 오류를 원문이나 경로 없이 격리한다.
        return GateResult(None, GATE_ERROR)
    finally:
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        request.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
