"""발화가 가장 많은 연속 60초를 선택하고 결과를 원본 시간으로 표시한다."""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import time
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from server.config import Settings
from server.jobs.child_process import start_process, stop_process

WINDOW_SECONDS = 60
CLIP_NAME = "analysis_window.mkv"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Window:
    duration_sec: float
    start_sec: float
    end_sec: float


class WindowError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def select_window(duration_sec: float, speech: Iterable[tuple[float, float]]) -> Window:
    """Gate가 병합한 오름차순 발화 구간을 사용한다. 동률이면 가장 이른 창을 고른다."""
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        raise WindowError("media_unreadable")
    if duration_sec <= WINDOW_SECONDS:
        return Window(duration_sec, 0, duration_sec)
    # Gate VAD의 밀리초 정밀도를 유지해 동점 비교가 부동소수점 오차에 흔들리지 않게 한다.
    duration = round(duration_sec * 1000)
    width = WINDOW_SECONDS * 1000
    starts, ends, totals = [], [], [0]
    candidates = {0, duration - width}
    for start_sec, end_sec in speech:
        start, end = max(0, round(start_sec * 1000)), min(duration, round(end_sec * 1000))
        if start >= end:
            continue
        starts.append(start)
        ends.append(end)
        totals.append(totals[-1] + end - start)
        # 겹친 길이의 기울기가 감소하는 점만 최대값의 시작이 될 수 있다.
        candidates.update(max(0, min(duration - width, t)) for t in (start, end - width))

    def speech_before(t):
        count = bisect_right(ends, t)
        partial = max(0, t - starts[count]) if count < len(starts) else 0
        return totals[count] + partial

    start = max(candidates, key=lambda t: (speech_before(t + width) - speech_before(t), -t))
    return Window(duration_sec, start / 1000, (start + width) / 1000)


def _run(path: Path, job_dir: Path, settings: Settings, on_tick: Callable[[], bool],
         duration_sec: float | None) -> Window | None:
    path, job_dir = Path(path).resolve(), Path(job_dir).resolve()
    if path.parent != job_dir or not path.is_file():
        raise WindowError("media_unreadable")
    if not on_tick():
        raise WindowError("aborted")
    args = [sys.executable, "-m", "server.ingest.window_process", str(path)]
    if duration_sec is not None:
        args.append(str(duration_sec))
    deadline = time.monotonic() + settings.gate_timeout_seconds
    try:
        proc, fd = start_process(args, cwd=_REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise WindowError("gate_error") from None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WindowError("gate_timeout")
            try:
                data, _ = proc.communicate(timeout=min(remaining, settings.heartbeat_interval_seconds))
            except subprocess.TimeoutExpired:
                if not on_tick():
                    raise WindowError("aborted")
                continue
            if not on_tick():
                raise WindowError("aborted")
            if proc.returncode != 0:
                raise WindowError("media_unreadable" if proc.returncode == 2 else "gate_error")
            values = json.loads(data)
            return None if values is None else Window(*values)
    finally:
        stop_process(proc, fd)
        proc.stdout.close()


def select_audio_window(path: Path, duration_sec: float, job_dir: Path, settings: Settings,
                        on_tick: Callable[[], bool]) -> Window:
    """다운로드 1단계의 오디오를 조사한다. 시간 기준은 원본 영상의 초다."""
    window = _run(path, job_dir, settings, on_tick, duration_sec)
    if window is None:
        raise WindowError("media_unreadable")
    return window


def prepare_window(path: Path, job_dir: Path, settings: Settings,
                   on_tick: Callable[[], bool]) -> tuple[Path, Window | None]:
    """등록 미디어의 짧은 영상은 원본을 쓴다. 판독 불가도 기존 Gate에서 처리한다."""
    window = _run(path, job_dir, settings, on_tick, None)
    if window is None or window.duration_sec <= WINDOW_SECONDS:
        return path, window
    return job_dir / CLIP_NAME, window


def _seconds(value):
    return f"{value:.3f}".rstrip("0").rstrip(".")


def apply_window(result, window: Window | None) -> None:
    if window is None:
        return
    coverage = result["coverage"]
    coverage["video_duration_sec"] = window.duration_sec

    def original(t):
        return round(min(window.end_sec, window.start_sec + max(0, t)), 3)

    segments = coverage["analyzed_segments"]
    shifted = [(original(s["start_sec"]), original(s["end_sec"])) for s in segments]
    coverage["analyzed_segments"] = [{"start_sec": a, "end_sec": b} for a, b in shifted if a < b]
    if coverage["analyzed_duration_sec"] is not None:
        analyzed = round(sum(b - a for a, b in shifted if a < b), 3)
        coverage["analyzed_duration_sec"] = analyzed
        coverage["full_video_coverage"] = round(analyzed / window.duration_sec, 4)
        if coverage["eligible_duration_sec"]:
            coverage["eligible_coverage"] = round(analyzed / coverage["eligible_duration_sec"], 4)

    def source_range(match):
        return "~".join(_seconds(original(float(group))) for group in match.groups()) + "초"

    for entry in result["explanations"]:
        if entry["template_id"] in {"GATE_ELIGIBLE_SEGMENT", "GATE_EXCLUDED_SEGMENT"}:
            entry["message"] = re.sub(r"([\d.]+)~([\d.]+)초", source_range, entry["message"], count=1)
    minutes = int(window.duration_sec // 60)
    seconds = _seconds(window.duration_sec - minutes * 60)
    span = f"{_seconds(window.start_sec)}~{_seconds(window.end_sec)}초"
    result["explanations"].append({"template_id": "ANALYSIS_WINDOW", "reason_code": "unvalidated_condition",
                                   "message": f"전체 {minutes}분 {seconds}초 중 {span}를 분석했습니다."})
