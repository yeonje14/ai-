"""SyncNet 내부 프로세스 JSON 규약. HTTP API 규약이 아니며 torch를 읽지 않는다."""
from __future__ import annotations

import math
from typing import Any

MODEL_VERSION = 'syncnet-python-0.2.3-ab819ba'
OFFSET_FPS = 25  # 고정 upstream PipelineConfig.frame_rate


def finite_number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_segments(segments) -> list[list[float]]:
    if not isinstance(segments, (list, tuple)):
        raise ValueError('invalid segments')
    result = []
    for pair in segments:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('invalid segment')
        start, end = pair
        if not all(finite_number(v) for v in pair) or not 0 <= start < end:
            raise ValueError('invalid segment bounds')
        result.append([float(start), float(end)])
    return result


def metrics_null() -> dict:
    return {'lse_c': None, 'lse_d': None, 'offset_frames': None}


def failure(status: str, reason: str | None) -> dict:
    return {'status': status, 'reason_code': reason, **metrics_null(), 'raw_score': None,
            'included_in_fusion': False, 'offset_fps': OFFSET_FPS,
            'model_version': MODEL_VERSION, 'segments': None}


def segment_failure(start: float, end: float, status: str, reason: str) -> dict:
    return {'start_sec': start, 'end_sec': end, 'status': status, 'reason_code': reason,
            **metrics_null(), 'tracks': None}


def validate_tracks(tracks) -> list[dict]:
    if not isinstance(tracks, list) or not tracks:
        raise ValueError('empty tracks')
    clean = []
    for index, track in enumerate(tracks):
        if not isinstance(track, dict) or type(track.get('track_index')) is not int or track['track_index'] != index:
            raise ValueError('invalid track index')
        if (not finite_number(track.get('lse_c')) or not finite_number(track.get('lse_d'))
                or track['lse_d'] < 0 or type(track.get('offset_frames')) is not int):
            raise ValueError('invalid track metrics')
        clean.append({key: track[key] for key in ('track_index', 'lse_c', 'lse_d', 'offset_frames')})
    return clean


def parse_result(raw: Any, segments: list[list[float]]) -> dict:
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw['schema_version'] != 1:
        raise ValueError('invalid schema')
    rows = raw.get('segments')
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError('segment count mismatch')
    clean = []
    for row, (start, end) in zip(rows, segments):
        if (not isinstance(row, dict) or not finite_number(row.get('start_sec'))
                or not finite_number(row.get('end_sec'))
                or [row['start_sec'], row['end_sec']] != [start, end]):
            raise ValueError('segment mismatch')
        status = row.get('status')
        if status == 'completed':
            clean.append({'start_sec': start, 'end_sec': end, 'status': status, 'reason_code': None,
                          **metrics_null(), 'tracks': validate_tracks(row.get('tracks'))})
        elif status in ('error', 'insufficient_input', 'unsupported_input'):
            # 실패 응답의 원시 값·임의 오류 메시지는 전파하지 않는다.
            reason = {'error': 'inference_error', 'insufficient_input': 'tracking_failed',
                      'unsupported_input': 'speaker_unconfirmed'}[status]
            clean.append(segment_failure(start, end, status, reason))
        else:
            raise ValueError('unknown status')
    # 부분 성공을 전체 성공으로 표시하지 않고 성공 구간의 지표는 보존한다.
    status = next((s for s in ('error', 'unsupported_input', 'insufficient_input')
                   if any(row['status'] == s for row in clean)), 'completed')
    reason = next((row['reason_code'] for row in clean if row['status'] == status), None)
    result = failure(status, reason)
    result['segments'] = clean
    return result
