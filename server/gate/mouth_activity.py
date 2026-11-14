"""입 움직임 규칙. 순수 함수이며 표준 라이브러리만 쓴다.

입 벌림 값(안쪽 입술 거리 / 두 눈 바깥꼬리 거리)의 시계열에서 "여닫는 움직임이 반복되는 구간"을 찾는다.
한 번 벌렸다 닫는 동작(하품, 숨)은 발화로 보지 않는다. 방향이 바뀐 횟수(반전)를 센다.

모든 임계값은 임시값이다. 말하는 영상으로 검증하지 않았다 (docs/gate.md).
"""

from __future__ import annotations

from typing import Optional, Sequence

from server.gate.types import GateConfig, MouthSample

Interval = tuple[float, float]


def split_chunks(samples: Sequence[MouthSample], config: GateConfig) -> list[list[MouthSample]]:
    """측정이 끊기거나 다른 얼굴로 바뀐 곳에서 시계열을 나눈다. 끊긴 곳을 건너 움직임을 잇지 않는다."""
    chunks: list[list[MouthSample]] = []
    current: list[MouthSample] = []
    for s in samples:
        if s.opening is None:
            if current:
                chunks.append(current)
            current = []
            continue
        if current and (
            s.t - current[-1].t > config.mouth_max_sample_gap_sec + 1e-9
            or _iou(s.box, current[-1].box) < config.track_iou_threshold
        ):
            chunks.append(current)
            current = []
        current.append(s)
    if current:
        chunks.append(current)
    return chunks


def reversal_times(times: Sequence[float], values: Sequence[float], min_swing: float) -> list[float]:
    """값의 방향이 min_swing 이상 되돌아간 것이 확인된 극점(봉우리·골)의 시각.

    벌렸다(봉우리) 닫으면 반전 1번이다. 닫힌 채 그대로면 골은 확인되지 않아 세지 않는다.
    """
    if not values:
        return []
    out: list[float] = []
    direction = 0                 # +1 오르는 중, -1 내리는 중, 0 아직 모름
    ext_v, ext_t = values[0], times[0]   # 현재 방향의 극값
    lo_v, lo_t = values[0], times[0]
    hi_v, hi_t = values[0], times[0]
    for t, v in zip(times[1:], values[1:]):
        if direction == 0:
            if v < lo_v:
                lo_v, lo_t = v, t
            if v > hi_v:
                hi_v, hi_t = v, t
            if v - lo_v >= min_swing:
                direction, ext_v, ext_t = 1, v, t
            elif hi_v - v >= min_swing:
                direction, ext_v, ext_t = -1, v, t
        elif direction == 1:
            if v > ext_v:
                ext_v, ext_t = v, t
            elif ext_v - v >= min_swing:
                out.append(ext_t)
                direction, ext_v, ext_t = -1, v, t
        else:
            if v < ext_v:
                ext_v, ext_t = v, t
            elif v - ext_v >= min_swing:
                out.append(ext_t)
                direction, ext_v, ext_t = 1, v, t
    return out


def active_intervals(samples: Sequence[MouthSample], config: GateConfig) -> list[Interval]:
    """입을 여닫는 움직임이 반복되는 구간.

    반전이 mouth_max_reversal_gap_sec 안에서 이어지는 묶음 가운데 반전이
    mouth_min_reversals번 이상인 것만 남기고, 앞뒤로 mouth_pad_sec을 붙인다.
    """
    out: list[Interval] = []
    for chunk in split_chunks(samples, config):
        times = [s.t for s in chunk]
        revs = reversal_times(times, [s.opening for s in chunk], config.mouth_min_swing)
        burst: list[float] = []
        for t in revs + [float("inf")]:
            if burst and t - burst[-1] > config.mouth_max_reversal_gap_sec + 1e-9:
                if len(burst) >= config.mouth_min_reversals:
                    out.append((
                        round(max(times[0], burst[0] - config.mouth_pad_sec), 3),
                        round(min(times[-1], burst[-1] + config.mouth_pad_sec), 3),
                    ))
                burst = []
            burst.append(t)
    return _merge(out)


def summarize(samples: Sequence[MouthSample], config: GateConfig) -> dict:
    """진단용 숫자. 영상 내용은 담지 않는다."""
    values = sorted(s.opening for s in samples if s.opening is not None)
    reversals = sum(
        len(reversal_times([s.t for s in c], [s.opening for s in c], config.mouth_min_swing))
        for c in split_chunks(samples, config)
    )
    return {
        "samples": len(samples),
        "measured": len(values),
        "opening_median": round(values[len(values) // 2], 4) if values else None,
        "opening_max": round(values[-1], 4) if values else None,
        "reversals": reversals,
    }


def _merge(intervals: Sequence[Interval]) -> list[Interval]:
    out: list[list[float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], b)
        elif b > a:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _iou(p: Optional[tuple[float, float, float, float]], q: Optional[tuple[float, float, float, float]]) -> float:
    if p is None or q is None:
        return 0.0
    ix = max(0.0, min(p[0] + p[2], q[0] + q[2]) - max(p[0], q[0]))
    iy = max(0.0, min(p[1] + p[3], q[1] + q[3]) - max(p[1], q[1]))
    inter = ix * iy
    union = p[2] * p[3] + q[2] * q[3] - inter
    return inter / union if union > 0 else 0.0
