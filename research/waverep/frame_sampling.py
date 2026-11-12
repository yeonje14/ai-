"""시간 구간 목록에서 분석할 프레임 번호를 고른다 (README §14.1 백로그 7번).

표준 라이브러리만 쓴다(torch, cv2를 import하지 않는다). trinity 환경의 pytest와
research/waverep/.venv의 infer_frames.py가 같은 함수를 쓴다.

프레임 i의 시각은 i / video_fps로 본다(고정 프레임률 가정). 가변 프레임률 영상에서
이 시각이 실제 표시 시각과 맞는지는 확인하지 않았다.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

# 부동소수점 오차로 경계 프레임이 빠지거나 더 들어가지 않게 하는 여유
_EPS = 1e-6


def validate_segments(segments: Iterable[Sequence[float]]) -> list[tuple[float, float]]:
    """[start_sec, end_sec) 목록을 검사해 (float, float) 목록으로 돌려준다. 잘못되면 ValueError."""
    out: list[tuple[float, float]] = []
    for seg in segments:
        if isinstance(seg, (str, bytes)) or len(seg) != 2:
            raise ValueError(f"구간은 [start_sec, end_sec] 두 값이어야 한다: {seg!r}")
        start, end = seg
        for v in (start, end):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"구간 값은 유한한 숫자여야 한다: {seg!r}")
        if start < 0 or end <= start:
            raise ValueError(f"구간은 0 <= start < end 여야 한다: {seg!r}")
        out.append((float(start), float(end)))
    return out


def validate_sample_fps(sample_fps: Optional[float]) -> Optional[float]:
    """None은 '구간 안 모든 프레임'이다. 숫자면 양수여야 한다."""
    if sample_fps is None:
        return None
    if isinstance(sample_fps, bool) or not isinstance(sample_fps, (int, float)):
        raise ValueError(f"sample_fps는 숫자 또는 None이어야 한다: {sample_fps!r}")
    if not math.isfinite(sample_fps) or sample_fps <= 0:
        raise ValueError(f"sample_fps는 양수여야 한다: {sample_fps!r}")
    return float(sample_fps)


def select_frame_indices(
    segments: Iterable[Sequence[float]],
    video_fps: float,
    frame_count: int,
    sample_fps: Optional[float] = None,
) -> list[int]:
    """구간들에서 고른 프레임 번호를 오름차순, 중복 없이 돌려준다.

    - sample_fps=None: start <= i/video_fps < end 인 모든 프레임.
    - sample_fps=f: 구간마다 start, start+1/f, start+2/f, ... (end 미만) 시각에
      화면에 나와 있는 프레임(floor(t * video_fps)).
    구간이 겹치면 같은 프레임은 한 번만 고른다. 영상 길이를 넘는 부분은 버린다.
    """
    segs = validate_segments(segments)
    sample_fps = validate_sample_fps(sample_fps)
    if not math.isfinite(video_fps) or video_fps <= 0:
        raise ValueError(f"video_fps는 양수여야 한다: {video_fps!r}")
    if frame_count < 0:
        raise ValueError(f"frame_count는 0 이상이어야 한다: {frame_count!r}")

    chosen: set[int] = set()
    for start, end in segs:
        # 구간에 들어가는 프레임 번호 범위 [first, stop)
        first = math.ceil(start * video_fps - _EPS)
        stop = min(math.ceil(end * video_fps - _EPS), frame_count)
        if sample_fps is None:
            chosen.update(range(first, stop))
            continue
        k = 0
        while True:
            t = start + k / sample_fps
            if t >= end - _EPS:
                break
            idx = max(math.floor(t * video_fps + _EPS), first)
            if idx >= stop:
                break
            chosen.add(idx)
            k += 1
    return sorted(chosen)
