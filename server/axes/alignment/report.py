"""SyncNet 내부 프로세스 JSON 규약. HTTP API 규약이 아니며 torch를 읽지 않는다."""
from __future__ import annotations

import math
import statistics
from typing import Any

MODEL_VERSION = 'syncnet-python-0.2.3-ab819ba'
# upstream min_track보다 프레임이 적어 SyncNet에서 제외한 구간의 원인 코드(README §10, §15.3 2026-11-17)
SEGMENT_TOO_SHORT = 'segment_too_short'
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
            # 실패 응답의 원시 값·임의 오류 메시지는 전파하지 않는다. 짧은 구간 표시만 그대로 받는다.
            reason = {'error': 'inference_error', 'insufficient_input': 'tracking_failed',
                      'unsupported_input': 'speaker_unconfirmed'}[status]
            if status == 'insufficient_input' and row.get('reason_code') == SEGMENT_TOO_SHORT:
                reason = SEGMENT_TOO_SHORT
            clean.append(segment_failure(start, end, status, reason))
        else:
            raise ValueError('unknown status')
    status, reason = aggregate_status(clean)
    result = failure(status, reason)
    result['segments'] = clean
    return result


def aggregate_status(rows: list[dict]) -> tuple[str, str | None]:
    """구간 결과 → 축 상태 (README §15.3 결정 2·8 보완, 2026-11-17).

    min_track 미만이라 제외한 구간(segment_too_short)은 판단에서 뺀다. 남은 구간이 없으면
    insufficient_input/segment_too_short다. 남은 구간이 하나 이상이고 모두 completed여야 completed다.
    부분 성공을 전체 성공으로 표시하지 않고 성공 구간의 지표는 보존한다. 오류가 있으면 error가 우선한다.
    """
    rest = [row for row in rows if row['reason_code'] != SEGMENT_TOO_SHORT]
    if not rest:
        return 'insufficient_input', SEGMENT_TOO_SHORT
    status = next((s for s in ('error', 'unsupported_input', 'insufficient_input')
                   if any(row['status'] == s for row in rest)), 'completed')
    reason = next((row['reason_code'] for row in rest if row['status'] == status), None)
    return status, reason


def excluded_short(result: dict) -> list[dict]:
    """제외한 짧은 구간. 결과가 없거나 실패면 빈 목록."""
    return [row for row in (result.get('segments') or []) if row['reason_code'] == SEGMENT_TOO_SHORT]


def fusion_features(result: dict) -> dict[str, float] | None:
    """결합·학습에 쓰는 SyncNet 값: 전 구간·전 트랙의 LSE-C, LSE-D, |오프셋| 중앙값.

    서버(결합 입력)와 학습(특징 추출)이 **같은 함수**를 쓴다. 축 상태가 completed일 때만 값을 내고
    그 밖에는 None이다(일부 구간의 트랙만으로 값을 만들지 않는다). 진위 판정이 아니다.
    """
    if result.get('status') != 'completed':
        return None
    tracks = [t for row in result.get('segments') or [] if row.get('tracks') for t in row['tracks']]
    if not tracks:
        return None
    return {'lse_c_median': float(statistics.median(t['lse_c'] for t in tracks)),
            'lse_d_median': float(statistics.median(t['lse_d'] for t in tracks)),
            'abs_offset_median': float(statistics.median(abs(t['offset_frames']) for t in tracks))}
