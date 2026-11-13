"""MotionPhys 궤적 추출: 프레임 표본 → 점 초기화 → 피라미드 Lucas–Kanade 추적.

He et al., arXiv:2608.20770v1 "Video Input and Trajectory Extraction"의 재구현이다.
논문은 숫자(코너 수, 격자 간격, 창 크기 등)를 밝히지 않았다. 아래 TrackingConfig의 값은
모두 우리 선택이며 임시값이다(docs/motionphys-spec.md).
OpenCV와 NumPy를 쓴다. 프레임을 디스크에 쓰지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import cv2
import numpy as np

from kinematics import SCALES

N_FRAMES = 48  # 논문: N = 48 프레임을 균등하게 뽑는다


@dataclass(frozen=True)
class TrackingConfig:
    """논문에 없는 값들. 전부 우리 선택(임시값)이다."""

    long_side: int = 640            # 처리 해상도(긴 변). 좌표와 jerk의 단위가 이 해상도의 픽셀이다
    max_corners: int = 200          # Shi–Tomasi 코너 수 상한
    corner_quality: float = 0.01
    corner_min_distance: int = 7
    grid_step: int = 32             # 격자점 간격(px)
    lk_window: int = 21
    lk_levels: int = 3
    fb_max_error: float = 1.0       # 역방향 재추적 오차(px)가 이보다 크면 탈락
    moving_min_mean_step: float = 0.5   # 한 걸음 평균 이동(px)이 이 이상이면 "움직인 궤적"


@dataclass
class SegmentFrames:
    frames: list[np.ndarray]        # 처리 해상도의 BGR 프레임
    indices: list[int]              # 원본 프레임 번호
    fps: float
    scale: float                    # 처리 해상도 / 원본 해상도

    @property
    def step_sec(self) -> Optional[float]:
        """표본 프레임 사이의 평균 시간 간격. jerk의 크기는 이 간격에 따라 달라진다."""
        if len(self.indices) < 2 or self.fps <= 0:
            return None
        return (self.indices[-1] - self.indices[0]) / (len(self.indices) - 1) / self.fps


class MediaError(RuntimeError):
    pass


def sample_indices(first: int, stop: int, n: int = N_FRAMES) -> list[int]:
    """[first, stop) 프레임에서 n개를 균등하게. 프레임이 n보다 적으면 있는 것을 모두 쓴다."""
    count = stop - first
    if count <= 0:
        return []
    if count <= n:
        return list(range(first, stop))
    return sorted({int(round(x)) for x in np.linspace(first, stop - 1, n)})


def read_segment_frames(
    video: Path, start_sec: float, end_sec: float, config: TrackingConfig = TrackingConfig()
) -> SegmentFrames:
    """구간 [start_sec, end_sec)에서 최대 48프레임을 균등하게 읽어 처리 해상도로 줄인다."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise MediaError("영상을 열 수 없음")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if fps <= 0 or total <= 0 or width <= 0 or height <= 0:
            raise MediaError("영상 정보(fps·프레임 수·크기)를 읽을 수 없음")
        first = max(int(np.ceil(start_sec * fps - 1e-6)), 0)
        stop = min(int(np.ceil(end_sec * fps - 1e-6)), total)
        wanted = sample_indices(first, stop)
        scale = min(1.0, config.long_side / max(width, height))
        size = (max(int(round(width * scale)), 1), max(int(round(height * scale)), 1))

        frames: list[np.ndarray] = []
        got: list[int] = []
        target = set(wanted)
        idx = 0
        while wanted and idx <= wanted[-1]:
            if not cap.grab():
                break
            if idx in target:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                if scale < 1.0:
                    frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                frames.append(frame)
                got.append(idx)
            idx += 1
    finally:
        cap.release()
    return SegmentFrames(frames=frames, indices=got, fps=fps, scale=scale)


def clip_ranges(n_frames: int, length: int) -> list[tuple[int, int]]:
    """n_frames를 겹치지 않는 길이 length의 클립으로 나눈다. 남는 프레임은 버린다."""
    return [(s, s + length) for s in range(0, n_frames - length + 1, length)]


def init_points(gray: np.ndarray, config: TrackingConfig, mask: Optional[np.ndarray] = None) -> np.ndarray:
    """Shi–Tomasi 코너와 격자점을 합친다. mask(uint8, 0이 아닌 곳만 허용)가 있으면 그 안에서만."""
    corners = cv2.goodFeaturesToTrack(
        gray, maxCorners=config.max_corners, qualityLevel=config.corner_quality,
        minDistance=config.corner_min_distance, mask=mask,
    )
    corners = corners.reshape(-1, 2) if corners is not None else np.empty((0, 2), np.float32)
    h, w = gray.shape[:2]
    half = config.grid_step // 2
    ys, xs = np.mgrid[half:h:config.grid_step, half:w:config.grid_step]
    grid = np.stack([xs.ravel(), ys.ravel()], axis=1).astype(np.float32)
    if mask is not None and len(grid):
        grid = grid[mask[grid[:, 1].astype(int), grid[:, 0].astype(int)] > 0]
    return np.concatenate([corners.astype(np.float32), grid], axis=0)


def track_clip(grays: Sequence[np.ndarray], points: np.ndarray, config: TrackingConfig) -> np.ndarray:
    """클립의 첫 프레임에서 잡은 점을 끝까지 추적한다. 끝까지 살아남은 궤적만 (M, L, 2)로 돌려준다."""
    if len(points) == 0:
        return np.empty((0, len(grays), 2), np.float32)
    lk = dict(
        winSize=(config.lk_window, config.lk_window), maxLevel=config.lk_levels,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    h, w = grays[0].shape[:2]
    alive = np.ones(len(points), dtype=bool)
    path = [points.astype(np.float32)]
    for prev, nxt in zip(grays[:-1], grays[1:]):
        cur = path[-1].reshape(-1, 1, 2)
        fwd, st_f, _ = cv2.calcOpticalFlowPyrLK(prev, nxt, cur, None, **lk)
        back, st_b, _ = cv2.calcOpticalFlowPyrLK(nxt, prev, fwd, None, **lk)
        fwd2 = fwd.reshape(-1, 2)
        fb_error = np.linalg.norm(back.reshape(-1, 2) - cur.reshape(-1, 2), axis=1)
        inside = (fwd2[:, 0] >= 0) & (fwd2[:, 0] < w) & (fwd2[:, 1] >= 0) & (fwd2[:, 1] < h)
        alive &= (st_f.ravel() == 1) & (st_b.ravel() == 1) & (fb_error <= config.fb_max_error) & inside
        path.append(fwd2)
    return np.stack(path, axis=1)[alive]


MaskFn = Callable[[int, np.ndarray], Optional[np.ndarray]]


def extract_trajectories(
    frames: Sequence[np.ndarray],
    config: TrackingConfig = TrackingConfig(),
    mask_for_clip: Optional[MaskFn] = None,
) -> tuple[dict[int, np.ndarray], dict[int, dict]]:
    """스케일마다 클립을 나눠 추적한다. {L: (M_L, L, 2)}와 스케일별 집계를 돌려준다.

    클립마다 첫 프레임에서 점을 다시 초기화한다(우리 선택).
    mask_for_clip(첫 프레임의 번호, 첫 프레임) → 마스크 또는 None. None을 돌려주면
    그 클립은 건너뛴다(얼굴 영역 후보에서 얼굴이 없는 클립).
    """
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    out: dict[int, np.ndarray] = {}
    info: dict[int, dict] = {}
    for length in SCALES:
        parts = []
        clips = clip_ranges(len(grays), length)
        initialized = used = 0
        for start, stop in clips:
            mask = None
            if mask_for_clip is not None:
                mask = mask_for_clip(start, frames[start])
                if mask is None:
                    continue
            points = init_points(grays[start], config, mask)
            initialized += len(points)
            used += 1
            parts.append(track_clip(grays[start:stop], points, config))
        out[length] = np.concatenate(parts, axis=0) if parts else np.empty((0, length, 2), np.float32)
        info[length] = {"clips": len(clips), "clips_used": used, "initialized": initialized}
    return out, info
