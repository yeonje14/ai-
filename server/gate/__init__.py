"""발화 구간 Gate (백로그 6번).

허가 미디어 파일 하나를 받아 "분석할 수 있는 발화 구간"과 원인 코드를 돌려준다.
모델 추론은 하지 않는다. Worker에는 아직 연결하지 않았다(백로그 7번).

무거운 의존성(cv2, mediapipe, webrtcvad)은 run_gate 안에서만 불러온다.
API 서버는 이 패키지를 import하지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from server.gate.types import (
    MEDIA_UNREADABLE,
    GateConfig,
    GateResult,
)

__all__ = ["run_gate", "GateConfig", "GateResult"]


def run_gate(
    media_path: Path,
    *,
    face_model_path: Optional[Path] = None,
    config: GateConfig = GateConfig(),
) -> GateResult:
    """media_path는 서버가 발급한 작업 경로(허가 미디어)여야 한다.

    미디어 문제는 GateResult.reason_code로 돌려준다.
    모델 파일 누락 같은 설정 문제는 GateSetupError로 올린다.
    """
    from server.gate import faces, probe, segments, vad

    path = Path(media_path).resolve()
    if not path.is_file():
        return GateResult(media=None, reason_code=MEDIA_UNREADABLE)

    media = probe.probe(path, config.subprocess_timeout_sec)
    if media is None:
        return GateResult(media=None, reason_code=MEDIA_UNREADABLE)

    if not media.has_audio:
        # 음성 구간이 없으면 얼굴을 볼 필요가 없다
        return segments.build_result(media, None, [], config)

    try:
        speech = vad.detect_speech(path, config)
    except vad.AudioDecodeError:
        return GateResult(media=media, reason_code=MEDIA_UNREADABLE)
    if not speech:
        return segments.build_result(media, [], [], config)

    if face_model_path is None:
        from server.config import Settings

        settings = Settings.from_env()
        face_model_path = faces.resolve_face_model(
            settings.gate_model_dir, settings.gate_models_config_path
        )
    frames = faces.detect_faces(path, media, Path(face_model_path), config)
    frames = segments.assign_tracks(frames, config)
    return segments.build_result(media, speech, frames, config)
