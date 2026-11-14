"""입 벌림 측정(MediaPipe Face Landmarker, CPU).

프레임과 얼굴 crop, 특징점 좌표를 저장하거나 로그에 남기지 않는다.
표본마다 입 벌림 비율 하나와 얼굴 박스만 돌려준다.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Sequence

from server.gate.types import GateConfig, MediaInfo, MouthSample

# MediaPipe Face Mesh 특징점 번호
_UPPER_INNER_LIP, _LOWER_INNER_LIP = 13, 14
_RIGHT_EYE_OUTER, _LEFT_EYE_OUTER = 33, 263
_MAX_FACES = 4


def measure_mouth(
    path: Path,
    media: MediaInfo,
    model_path: Path,
    config: GateConfig,
    within: Optional[Sequence[tuple[float, float]]] = None,
) -> list[MouthSample]:
    """mouth_sample_fps 간격의 표본 프레임에서 가장 큰 얼굴의 입 벌림을 잰다.

    within이 있으면 그 구간(앞뒤 여유 포함) 안의 프레임만 본다. 음성이 없는 곳은 잴 필요가 없다.
    얼굴 특징점을 찾지 못한 표본의 opening은 None이다(0이 아니다).
    """
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=_MAX_FACES,
    )
    margin = config.mouth_max_reversal_gap_sec
    stride = max(1, round(media.fps / config.mouth_sample_fps))
    out: list[MouthSample] = []
    cap = cv2.VideoCapture(str(path))
    try:
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            index = 0
            while True:
                t = index / media.fps
                wanted = index % stride == 0 and (
                    within is None or any(a - margin <= t <= b + margin for a, b in within)
                )
                if not wanted:
                    if not cap.grab():
                        break
                    index += 1
                    continue
                ok, frame = cap.read()
                if not ok:
                    break
                rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                h, w = frame.shape[:2]
                out.append(_sample(round(t, 3), result.face_landmarks, w, h))
                index += 1
    finally:
        cap.release()
    return out


def _sample(t: float, faces, width: int, height: int) -> MouthSample:
    best = None
    for lm in faces:
        xs = [p.x * width for p in lm]
        ys = [p.y * height for p in lm]
        box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        if best is None or box[3] > best[1][3]:
            best = (lm, box)
    if best is None:
        return MouthSample(t, None, None)
    lm, box = best

    def dist(i: int, j: int) -> float:
        return math.hypot((lm[i].x - lm[j].x) * width, (lm[i].y - lm[j].y) * height)

    eye = dist(_RIGHT_EYE_OUTER, _LEFT_EYE_OUTER)
    if eye < 1.0:
        return MouthSample(t, None, box)
    return MouthSample(t, dist(_UPPER_INNER_LIP, _LOWER_INNER_LIP) / eye, box)
