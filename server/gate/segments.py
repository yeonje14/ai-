"""발화 구간 규칙. 순수 함수이며 표준 라이브러리만 쓴다.

1차 규칙: 음성 구간 동안 주된 얼굴이 정확히 하나일 때만 발화 구간으로 인정한다.
주된 얼굴이 둘 이상이면 speaker_unconfirmed로 보류한다(발화자 선택은 백로그 11번).
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Optional, Sequence

from server.gate.types import (
    AUDIO_MISSING,
    FACE_TOO_SMALL,
    LOW_RESOLUTION,
    NO_FACE_DETECTED,
    NO_SPEECH_DETECTED,
    SEGMENT_TOO_SHORT,
    SPEAKER_UNCONFIRMED,
    TOO_BLURRY,
    Face,
    FrameFaces,
    GateConfig,
    GateResult,
    MediaInfo,
    Segment,
    SegmentQuality,
)

_NONE = "none"
_MULTI = "multi"

Interval = tuple[float, float]


def assign_tracks(frames: Sequence[FrameFaces], config: GateConfig) -> list[FrameFaces]:
    """표본 프레임 사이에서 박스 겹침(IoU)으로 같은 얼굴을 잇고 track_id를 붙인다."""
    out: list[FrameFaces] = []
    last: dict[int, tuple[float, Face]] = {}   # track_id -> (마지막으로 본 시각, 얼굴)
    next_id = 0
    for frame in frames:
        # 오래 안 보인 트랙은 잇지 않는다
        last = {k: v for k, v in last.items() if frame.t - v[0] <= config.max_face_gap_sec + 1e-9}
        used: set[int] = set()
        tracked: list[Face] = []
        for face in sorted(frame.faces, key=lambda f: f.w * f.h, reverse=True):
            best_id, best_iou = None, config.track_iou_threshold
            for tid, (_, prev) in last.items():
                if tid in used:
                    continue
                iou = _iou(face, prev)
                if iou >= best_iou:
                    best_id, best_iou = tid, iou
            if best_id is None:
                best_id = next_id
                next_id += 1
            used.add(best_id)
            tracked.append(Face(face.x, face.y, face.w, face.h, face.score, face.sharpness, best_id))
        for f in tracked:
            last[f.track_id] = (frame.t, f)
        out.append(FrameFaces(frame.t, tuple(tracked)))
    return out


def build_result(
    media: MediaInfo,
    speech: Optional[Sequence[Interval]],
    frames: Sequence[FrameFaces],
    config: GateConfig = GateConfig(),
) -> GateResult:
    """음성 구간과 (track_id가 붙은) 얼굴 표본으로 적합·제외 구간을 만든다.

    speech가 None이면 오디오 스트림이 없다는 뜻이다.
    """
    duration = media.duration_sec
    if speech is None:
        return GateResult(
            media=media,
            reason_code=AUDIO_MISSING,
            excluded_segments=(Segment(0.0, _r(duration), AUDIO_MISSING),),
        )

    speech = [(max(0.0, a), min(duration, b)) for a, b in speech if min(duration, b) > max(0.0, a)]
    excluded: list[Segment] = [
        Segment(_r(a), _r(b), NO_SPEECH_DETECTED) for a, b in _complement(speech, duration)
    ]
    eligible: list[Segment] = []
    short_side = min(media.width, media.height)
    main_min_h = config.main_face_min_height_ratio * short_side

    for a, b in speech:
        for start, end, state, faces in _runs_in_interval(a, b, frames, main_min_h, config):
            seg = _judge(start, end, state, faces, short_side, config)
            (eligible if seg.reason_code is None else excluded).append(seg)

    excluded.sort(key=lambda s: s.start_sec)
    reason = None if eligible else _dominant_reason(excluded)
    return GateResult(
        media=media,
        reason_code=reason,
        eligible_segments=tuple(eligible),
        excluded_segments=tuple(excluded),
        speech_segments=tuple((_r(a), _r(b)) for a, b in speech),
    )


def _runs_in_interval(a, b, frames, main_min_h, config):
    """음성 구간 [a, b] 안의 표본을 상태별 연속 구간으로 묶는다.

    상태: 얼굴 없음 / 주된 얼굴 하나(track_id) / 주된 얼굴 여럿.
    돌려주는 값: (start, end, state, 그 구간의 주된 얼굴 목록)
    """
    samples = []  # (t, state, face 또는 None)
    for frame in frames:
        if frame.t < a or frame.t > b:
            continue
        main = [f for f in frame.faces if f.h >= main_min_h]
        if not main:
            samples.append((frame.t, _NONE, None))
        elif len(main) == 1:
            samples.append((frame.t, main[0].track_id, main[0]))
        else:
            samples.append((frame.t, _MULTI, None))
    if not samples:
        # 표본 간격보다 짧은 음성 구간이다. 얼굴을 확인할 수 없다.
        return [(a, b, _NONE if b - a >= config.min_segment_sec else "short", [])]

    # 같은 얼굴 사이의 짧은 검출 누락은 메운다
    i = 0
    while i < len(samples):
        if samples[i][1] != _NONE:
            i += 1
            continue
        j = i
        while j < len(samples) and samples[j][1] == _NONE:
            j += 1
        before = samples[i - 1][1] if i > 0 else None
        after = samples[j][1] if j < len(samples) else None
        if (
            before is not None and before == after and before not in (_NONE, _MULTI)
            and samples[j][0] - samples[i - 1][0] <= config.max_face_gap_sec + 1e-9
        ):
            for k in range(i, j):
                samples[k] = (samples[k][0], before, None)
        i = j

    runs = []
    start_idx = 0
    for idx in range(1, len(samples) + 1):
        if idx < len(samples) and samples[idx][1] == samples[start_idx][1]:
            continue
        # 구간 경계는 이웃 표본의 중간 시각으로 잡고, 음성 구간 밖으로 나가지 않게 한다
        start = a if start_idx == 0 else (samples[start_idx - 1][0] + samples[start_idx][0]) / 2
        end = b if idx == len(samples) else (samples[idx - 1][0] + samples[idx][0]) / 2
        faces = [s[2] for s in samples[start_idx:idx] if s[2] is not None]
        runs.append((start, end, samples[start_idx][1], faces))
        start_idx = idx
    return runs


def _judge(start, end, state, faces, short_side, config) -> Segment:
    start, end = _r(start), _r(end)
    if state == "short":
        return Segment(start, end, SEGMENT_TOO_SHORT)
    if state == _NONE:
        return Segment(start, end, NO_FACE_DETECTED)
    if state == _MULTI:
        return Segment(start, end, SPEAKER_UNCONFIRMED)

    face_h = median(f.h for f in faces)
    quality = SegmentQuality(
        face_height_px=round(face_h, 1),
        face_height_ratio=round(face_h / short_side, 4),
        sharpness=round(median(f.sharpness for f in faces), 2),
        short_side_px=short_side,
        face_frames=len(faces),
    )
    if short_side < config.min_short_side_px:
        reason = LOW_RESOLUTION
    elif quality.face_height_px < config.min_face_height_px:
        reason = FACE_TOO_SMALL
    elif quality.sharpness < config.min_sharpness:
        reason = TOO_BLURRY
    elif end - start < config.min_segment_sec:
        reason = SEGMENT_TOO_SHORT
    else:
        reason = None
    return Segment(start, end, reason, quality)


def _dominant_reason(excluded: Sequence[Segment]) -> Optional[str]:
    """적합 구간이 없을 때의 대표 원인.

    음성이 아예 없으면 no_speech_detected. 음성이 있으면 음성 구간을 가장 길게
    막은 원인을 고른다(말하지 않는 시간이 길다고 그것이 대표 원인이 되지 않게 한다).
    """
    totals: dict[str, float] = defaultdict(float)
    for s in excluded:
        totals[s.reason_code] += s.duration_sec
    in_speech = {k: v for k, v in totals.items() if k != NO_SPEECH_DETECTED}
    if in_speech:
        return max(in_speech, key=in_speech.get)
    return NO_SPEECH_DETECTED if totals else None


def _complement(intervals: Sequence[Interval], duration: float) -> list[Interval]:
    out, cursor = [], 0.0
    for a, b in sorted(intervals):
        if a > cursor + 1e-6:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if duration > cursor + 1e-6:
        out.append((cursor, duration))
    return out


def _iou(p: Face, q: Face) -> float:
    ix = max(0.0, min(p.x + p.w, q.x + q.w) - max(p.x, q.x))
    iy = max(0.0, min(p.y + p.h, q.y + q.h) - max(p.y, q.y))
    inter = ix * iy
    union = p.w * p.h + q.w * q.h - inter
    return inter / union if union > 0 else 0.0


def _r(x: float) -> float:
    return round(x, 3)
