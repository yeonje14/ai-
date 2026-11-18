"""SyncNet 독립 어댑터. Gate 적합 구간만 받으며 Worker 연결은 조각 3에서 한다.

HTTP 응답이 아닌 내부 JSON을 반환한다. 트랙별 지표를 합치거나 판정하지 않는다.
서버 환경은 표준 라이브러리만 사용하고 모델은 전용 venv 프로세스에서 실행한다.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from server.jobs.child_process import start_process, stop_process

from .report import failure, finite_number, parse_result, validate_segments

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / 'research/syncnet'


@dataclass(frozen=True)
class SyncNetConfig:
    python: Path = RESEARCH / '.venv/bin/python'
    script: Path = RESEARCH / 'infer_segments.py'
    weights_dir: Path = ROOT / 'data/models/syncnet'
    timeout_sec: float = 600.0
    # cpu 또는 mps. 기본은 mps이고 쓸 수 없으면 실행기가 cpu로 대체한다(docs/DESIGN.md §15.3 2026-11-17, docs/syncnet-adapter.md)
    device: str = 'mps'


def _run(cmd: list[str], timeout: float, on_tick, tick_sec: float) -> str | None:
    # 원본의 stdout/stderr에는 파일 경로와 지표가 있으므로 전달/저장하지 않는다.
    proc, parent_fd = start_process(cmd, cwd=ROOT, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 'timeout'
            try:
                code = proc.wait(timeout=min(remaining, tick_sec) if on_tick else remaining)
                return None if code == 0 else 'inference_error'
            except subprocess.TimeoutExpired:
                if on_tick:
                    try:
                        if not on_tick():
                            return 'aborted'
                    except Exception:
                        return 'aborted'
    finally:
        # Worker SIGKILL은 supervisor가 감지하고, 정상/취소/timeout도 같은 정리 경로를 쓴다.
        stop_process(proc, parent_fd)


def run_syncnet(video: Path, segments: Sequence[Sequence[float]], work_dir: Path,
                config: SyncNetConfig = SyncNetConfig(),
                on_tick: Callable[[], bool] | None = None, tick_sec: float = 10.0) -> dict:
    """서버 작업 폴더 내 허가 미디어와 [(start_sec, end_sec), ...]만 받는다.

    호출자가 Gate 적합 구간을 선택한다. 구간이 없으면 추론하지 않는다.
    on_tick=False 또는 예외는 취소로 처리하며 모델/FFmpeg 프로세스 그룹을 종료한다.
    실패는 점수 null 결과로 격리한다. 원본 작업 파일은 호출자가 소유한다.
    """
    try:
        bounds = validate_segments(segments)
        if not bounds:
            return failure('insufficient_input', 'no_segments')
        if (not finite_number(config.timeout_sec) or config.timeout_sec <= 0
                or not finite_number(tick_sec) or tick_sec <= 0 or config.device not in ('cpu', 'mps')):
            return failure('error', 'invalid_request')
        work_dir, video = Path(work_dir).resolve(), Path(video).resolve()
        if not work_dir.is_dir() or not video.is_relative_to(work_dir):
            return failure('error', 'invalid_request')
        if not video.is_file():
            return failure('error', 'media_unreadable')
    except (ValueError, TypeError, OSError):
        return failure('error', 'invalid_request')
    if on_tick:
        try:
            if not on_tick():
                return failure('error', 'aborted')
        except Exception:
            return failure('error', 'aborted')
    if not Path(config.python).is_file() or not Path(config.script).is_file():
        return failure('error', 'model_unavailable')
    try:
        # 고유 폴더로 이전/다른 실행의 JSON과 충돌하지 않는다.
        with tempfile.TemporaryDirectory(prefix='syncnet-', dir=work_dir) as tmp:
            folder = Path(tmp)
            request, output = folder / 'request.json', folder / 'result.json'
            request.write_text(json.dumps({'video': str(video), 'segments': bounds,
                                           'weights_dir': str(Path(config.weights_dir).resolve()),
                                           'device': config.device}))
            cmd = [str(config.python), str(config.script), '--request', str(request), '--output', str(output)]
            try:
                reason = _run(cmd, config.timeout_sec, on_tick, tick_sec)
            except OSError:
                return failure('error', 'model_unavailable')
            if reason:
                return failure('error', reason)
            raw = json.loads(output.read_text())
            result = parse_result(raw, bounds)
            used = raw.get('device_used') if isinstance(raw, dict) else None
            result['device_used'] = used if used in ('cpu', 'mps') else None  # 내부 기록(API 결과 아님)
            return result
    except (OSError, ValueError, TypeError, RecursionError):
        return failure('error', 'inference_error')
