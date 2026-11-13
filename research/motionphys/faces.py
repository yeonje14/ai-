"""MediaPipe 얼굴 박스와 얼굴 특징점. 후보 B(얼굴 영역)와 C(Face Motion)가 쓴다.

MediaPipe는 얼굴 위치와 특징점을 주는 도구다. 딥페이크 탐지기가 아니다(README §5.2).
모델 파일은 Git 밖(data/models/)에 두고, configs/motionphys_models.json의 sha256과 다르면 실행을 거부한다.
얼굴 이미지를 디스크에 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_CONFIG = REPO_ROOT / "configs" / "motionphys_models.json"

FACE_BOX_MARGIN = 0.10          # 얼굴 박스를 사방으로 이만큼 넓힌다 (우리 선택)
MIN_DETECTION_CONFIDENCE = 0.5
# 눈 사이 거리의 기준이 되는 특징점: 양쪽 눈의 바깥 꼬리
EYE_OUTER = (33, 263)


class ModelFileError(RuntimeError):
    pass


def model_path(key: str, config_path: Path = MODELS_CONFIG) -> Path:
    """설정에 적힌 모델 파일의 경로. 파일이 없거나 sha256이 다르면 ModelFileError."""
    entry = json.loads(config_path.read_text(encoding="utf-8"))[key]
    path = REPO_ROOT / entry["path"]
    if not path.is_file():
        raise ModelFileError(f"모델 파일 없음: {entry['path']}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise ModelFileError(f"모델 파일의 sha256이 설정과 다르다: {entry['path']}")
    return path


def _mp_image(frame_bgr: np.ndarray):
    import mediapipe as mp

    return mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))


class FaceBoxDetector:
    """프레임에서 가장 큰 얼굴의 박스. 얼굴이 없으면 None."""

    def __init__(self) -> None:
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision

        self._detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(model_path("face_detector"))),
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        ))

    def largest_box(self, frame_bgr: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        """(x0, y0, x1, y1). 여백을 더하고 프레임 안으로 자른다."""
        result = self._detector.detect(_mp_image(frame_bgr))
        if not result.detections:
            return None
        box = max((d.bounding_box for d in result.detections), key=lambda b: b.width * b.height)
        h, w = frame_bgr.shape[:2]
        mx, my = box.width * FACE_BOX_MARGIN, box.height * FACE_BOX_MARGIN
        x0, y0 = max(int(box.origin_x - mx), 0), max(int(box.origin_y - my), 0)
        x1, y1 = min(int(box.origin_x + box.width + mx), w), min(int(box.origin_y + box.height + my), h)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return x0, y0, x1, y1

    def mask(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        box = self.largest_box(frame_bgr)
        if box is None:
            return None
        m = np.zeros(frame_bgr.shape[:2], np.uint8)
        m[box[1]:box[3], box[0]:box[2]] = 255
        return m

    def close(self) -> None:
        self._detector.close()


def landmark_regions() -> dict[str, list[int]]:
    """Face Motion의 세 영역에 쓰는 특징점 번호. MediaPipe가 제공하는 연결 목록에서 얻는다."""
    from mediapipe.tasks.python import vision

    c = vision.FaceLandmarksConnections

    def indices(*groups) -> list[int]:
        return sorted({i for g in groups for conn in g for i in (conn.start, conn.end)})

    return {
        "head": indices(c.FACE_LANDMARKS_FACE_OVAL),
        "eyebrows": indices(c.FACE_LANDMARKS_LEFT_EYEBROW, c.FACE_LANDMARKS_RIGHT_EYEBROW),
        "lips": indices(c.FACE_LANDMARKS_LIPS),
    }


class FaceLandmarkTracker:
    """프레임마다 얼굴 특징점의 픽셀 좌표 (478, 2). 얼굴이 없으면 None."""

    def __init__(self) -> None:
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision

        self._landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(model_path("face_landmarker"))),
            num_faces=1,
        ))

    def landmarks(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        result = self._landmarker.detect(_mp_image(frame_bgr))
        if not result.face_landmarks:
            return None
        h, w = frame_bgr.shape[:2]
        return np.array([[p.x * w, p.y * h] for p in result.face_landmarks[0]], dtype=np.float64)

    def close(self) -> None:
        self._landmarker.close()


def region_trajectories(landmarks: np.ndarray, regions: dict[str, list[int]]) -> dict[str, np.ndarray]:
    """(T, 478, 2) 특징점 열 → 영역별 궤적 (점 수, T, 2).

    head: 얼굴 윤곽 점의 화면 좌표 그대로(머리 전체의 움직임).
    eyebrows, lips: 프레임마다 얼굴 윤곽의 중심을 빼고, 눈 사이 거리를 이 클립의 중앙값에
    맞춰 크기를 보정한 좌표(머리의 이동과 거리 변화를 뺀 얼굴 안의 움직임). 회전은 빼지 않는다.
    단위는 모두 처리 해상도의 픽셀이다.
    """
    lm = np.asarray(landmarks, dtype=np.float64)
    head = lm[:, regions["head"]]                                   # (T, n, 2)
    center = head.mean(axis=1, keepdims=True)                       # (T, 1, 2)
    iod = np.linalg.norm(lm[:, EYE_OUTER[0]] - lm[:, EYE_OUTER[1]], axis=1)   # (T,)
    ref = float(np.median(iod))
    factor = (ref / np.maximum(iod, 1e-6))[:, None, None]
    out = {"head": head.transpose(1, 0, 2)}
    for name in ("eyebrows", "lips"):
        out[name] = ((lm[:, regions[name]] - center) * factor).transpose(1, 0, 2)
    return out
