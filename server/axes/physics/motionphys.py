"""MotionPhys 어댑터. 특징 추출 요약만 받는다. 점수도 판정도 없다.

서버 환경은 표준 라이브러리만 쓰고, 추출은 research/motionphys/.venv의 별도 프로세스가 한다.
학습된 분류기가 없으므로 raw_score는 항상 null이다. 축 상태는 후보 A(전체 화면)를 따른다.
HTTP 응답이 아닌 내부 결과를 돌려준다. 정의는 docs/motionphys-spec.md.
"""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from server.jobs.child_process import start_process, stop_process

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / 'research/motionphys'
# 논문 재구현(공개 코드 없음) + 분류기 없음. 추출기 설정이 바뀌면 이름을 바꾼다.
MODEL_VERSION = 'motionphys-reimpl-features-v1'
VARIANTS = ('full', 'face_roi', 'face_motion')
PRIMARY = 'full'
SCALES = ('8', '12', '24')
# 추출기가 내는 "분석할 수 없음" 원인 가운데 그대로 전달하는 것 (docs/DESIGN.md §5.2, §10)
INPUT_REASONS = ('tracking_failed', 'insufficient_motion', 'segment_too_short')


@dataclass(frozen=True)
class MotionPhysConfig:
    python: Path = RESEARCH / '.venv/bin/python'
    script: Path = RESEARCH / 'infer_axis.py'
    timeout_sec: float = 120.0
    # (후보 이름, LightGBM 모델 파일). 검증된 묶음이 있을 때만 서버가 넣는다. 없으면 점수를 내지 않는다.
    margin_model: tuple[str, Path] | None = None


def failure(status: str, reason: str | None) -> dict:
    return {'status': status, 'reason_code': reason, 'raw_score': None,
            'model_version': MODEL_VERSION, 'variants': None, 'margin': None, 'margin_variant': None}


def _finite(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_segments(segments) -> list[list[float]]:
    if not isinstance(segments, (list, tuple)):
        raise ValueError('invalid segments')
    out = []
    for pair in segments:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('invalid segment')
        if not all(_finite(v) for v in pair) or not 0 <= pair[0] < pair[1]:
            raise ValueError('invalid segment bounds')
        out.append([float(pair[0]), float(pair[1])])
    return out


def _counts(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(SCALES):
        raise ValueError('invalid counts')
    for n in value.values():
        if type(n) is not int or n < 0:
            raise ValueError('invalid count')
    return {s: value[s] for s in SCALES}


def _rate(value: Any) -> float | None:
    if value is None:
        return None
    if not _finite(value) or not 0 <= value <= 1:
        raise ValueError('invalid rate')
    return float(value)


def _variant(raw: Any, with_features: bool = False) -> dict:
    """한 후보의 요약. 특징 벡터·오류 문구 등 다른 값은 전달하지 않는다."""
    if not isinstance(raw, dict):
        raise ValueError('invalid variant')
    status = raw.get('status')
    if status == 'completed':
        reason = None
    elif status == 'insufficient_input':
        reason = raw.get('reason_code') if raw.get('reason_code') in INPUT_REASONS else 'tracking_failed'
    elif status == 'error':
        reason = 'inference_error'
    else:
        raise ValueError('unknown status')
    rates = raw.get('tracking_success_rate')
    if rates is not None:
        if not isinstance(rates, dict) or set(rates) != set(SCALES):
            raise ValueError('invalid rates')
        rates = {s: _rate(rates[s]) for s in SCALES}
    out = {'status': status, 'reason_code': reason,
           'valid_trajectories': _counts(raw.get('valid_trajectories')),
           'moving_trajectories': _counts(raw.get('moving_trajectories')),
           'tracking_success_rate': rates,
           'face_detection_rate': _rate(raw.get('face_detection_rate'))}
    if status == 'completed' and out['valid_trajectories'] is None:
        raise ValueError('completed without counts')
    if with_features:
        # 연구용 일괄 추출 전용. 실패한 후보의 특징은 null이다(0으로 채우지 않는다)
        features = raw.get('features') if status == 'completed' else None
        if status == 'completed' and (not isinstance(features, list) or not features
                                      or not all(_finite(x) for x in features)):
            raise ValueError('invalid features')
        out['features'] = None if features is None else [float(x) for x in features]
    return out


def parse_result(raw: Any, with_features: bool = False, margin_variant: str | None = None) -> dict:
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw['schema_version'] != 1:
        raise ValueError('invalid schema')
    variants = raw.get('variants')
    if not isinstance(variants, dict) or set(variants) != set(VARIANTS):
        raise ValueError('invalid variants')
    clean = {name: _variant(variants[name], with_features) for name in VARIANTS}
    primary = clean[PRIMARY]
    result = failure(primary['status'], primary['reason_code'])
    result['variants'] = clean
    if margin_variant is not None:
        # 분류기의 원시 margin(확률 아님). 그 후보의 추출이 실패했거나 값이 이상하면 null이다
        margin = variants[margin_variant].get('margin') if isinstance(variants.get(margin_variant), dict) else None
        if clean[margin_variant]['status'] == 'completed' and _finite(margin):
            result.update(margin=float(margin), margin_variant=margin_variant)
    return result


def _run(cmd: list[str], timeout: float, on_tick, tick_sec: float) -> str | None:
    # stdout/stderr에는 파일 경로가 섞일 수 있어 전달·저장하지 않는다.
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
        # Worker SIGKILL은 supervisor가 감지한다. 정상·취소·timeout도 같은 정리 경로를 쓴다.
        stop_process(proc, parent_fd)


def run_motionphys(video: Path, segments: Sequence[Sequence[float]], work_dir: Path,
                   config: MotionPhysConfig = MotionPhysConfig(),
                   on_tick: Callable[[], bool] | None = None, tick_sec: float = 10.0,
                   include_features: bool = False) -> dict:
    """서버 작업 폴더 안의 허가 미디어와 [(start_sec, end_sec), ...]만 받는다.

    include_features는 연구용 일괄 추출(training/features)만 켠다. 서버 Worker는 켜지 않는다.

    구간이 없으면 실행하지 않는다. on_tick이 False를 돌려주거나 예외를 내면 취소로 보고
    프로세스 그룹을 끝낸다. 실패는 점수 null 결과로 격리하고 예외를 던지지 않는다.
    """
    try:
        bounds = validate_segments(segments)
        if not bounds:
            return failure('insufficient_input', 'no_segments')
        if (not _finite(config.timeout_sec) or config.timeout_sec <= 0
                or not _finite(tick_sec) or tick_sec <= 0):
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
        # 고유 폴더라 이전 실행의 JSON과 섞이지 않는다. 끝나면 폴더째 지운다.
        with tempfile.TemporaryDirectory(prefix='motionphys-', dir=work_dir) as tmp:
            request, output = Path(tmp) / 'request.json', Path(tmp) / 'result.json'
            body = {'video': str(video), 'segments': bounds}
            if include_features:
                body['include_features'] = True
            if config.margin_model is not None:
                if config.margin_model[0] not in VARIANTS or not Path(config.margin_model[1]).is_file():
                    return failure('error', 'model_unavailable')
                body['margin_model'] = {'variant': config.margin_model[0], 'path': str(config.margin_model[1])}
            request.write_text(json.dumps(body))
            cmd = [str(config.python), str(config.script), '--request', str(request), '--output', str(output)]
            try:
                reason = _run(cmd, config.timeout_sec, on_tick, tick_sec)
            except OSError:
                return failure('error', 'model_unavailable')
            if reason:
                return failure('error', reason)
            return parse_result(json.loads(output.read_text()), include_features,
                                config.margin_model[0] if config.margin_model else None)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return failure('error', 'inference_error')
