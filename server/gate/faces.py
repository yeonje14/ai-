"""얼굴 검출(MediaPipe Face Detector, CPU).

프레임과 얼굴 crop을 저장하거나 로그에 남기지 않는다. 숫자(박스, 점수, 선명도)만 돌려준다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.gate.types import Face, FrameFaces, GateConfig, MediaInfo

_SHARPNESS_SIZE = 256


class GateSetupError(RuntimeError):
    """모델 파일이 없거나 해시가 다르다. 미디어의 문제가 아니다."""


def resolve_face_model(model_dir: Path, models_config_path: Path) -> Path:
    """configs/gate_models.json의 해시와 일치하는 모델 파일 경로를 돌려준다."""
    try:
        entry = json.loads(Path(models_config_path).read_text(encoding="utf-8"))["face_detector"]
    except (OSError, ValueError, KeyError) as exc:
        raise GateSetupError("gate 모델 설정을 읽을 수 없다") from exc
    path = Path(model_dir) / entry["file"]
    if not path.is_file():
        raise GateSetupError(f"얼굴 검출 모델 파일이 없다: {path} (docs/gate.md 참고)")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise GateSetupError("얼굴 검출 모델 파일의 sha256이 설정과 다르다")
    return path


def detect_faces(
    path: Path, media: MediaInfo, model_path: Path, config: GateConfig
) -> list[FrameFaces]:
    """face_sample_fps 간격의 표본 프레임에서 얼굴을 검출한다. track_id는 붙이지 않는다."""
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=config.min_detection_confidence,
    )
    stride = max(1, round(media.fps / config.face_sample_fps))
    out: list[FrameFaces] = []
    cap = cv2.VideoCapture(str(path))
    try:
        with vision.FaceDetector.create_from_options(options) as detector:
            index = 0
            while True:
                if index % stride != 0:
                    if not cap.grab():
                        break
                    index += 1
                    continue
                ok, frame = cap.read()
                if not ok:
                    break
                rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                gray = None
                faces = []
                for det in result.detections:
                    box = det.bounding_box
                    if gray is None:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces.append(
                        Face(
                            x=float(box.origin_x),
                            y=float(box.origin_y),
                            w=float(box.width),
                            h=float(box.height),
                            score=float(det.categories[0].score),
                            sharpness=_sharpness(cv2, gray, box),
                        )
                    )
                out.append(FrameFaces(t=round(index / media.fps, 3), faces=tuple(faces)))
                index += 1
    finally:
        cap.release()
    return out


def _sharpness(cv2, gray, box) -> float:
    """얼굴 영역을 고정 크기로 맞춘 뒤의 Laplacian 분산. 값이 작을수록 흐리다."""
    h, w = gray.shape[:2]
    x0, y0 = max(0, box.origin_x), max(0, box.origin_y)
    x1, y1 = min(w, box.origin_x + box.width), min(h, box.origin_y + box.height)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0.0
    roi = cv2.resize(gray[y0:y1, x0:x1], (_SHARPNESS_SIZE, _SHARPNESS_SIZE),
                     interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(roi, cv2.CV_64F).var())
