"""Gate의 자료형, 원인 코드, 임시 임계값.

이 파일은 표준 라이브러리만 쓴다(cv2, mediapipe, webrtcvad를 import하지 않는다).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# 원인 코드 (docs/DESIGN.md §10)
MEDIA_UNREADABLE = "media_unreadable"
AUDIO_MISSING = "audio_missing"
NO_SPEECH_DETECTED = "no_speech_detected"
NO_FACE_DETECTED = "no_face_detected"
SPEAKER_UNCONFIRMED = "speaker_unconfirmed"
LOW_RESOLUTION = "low_resolution"
FACE_TOO_SMALL = "face_too_small"
TOO_BLURRY = "too_blurry"
SEGMENT_TOO_SHORT = "segment_too_short"
# 음성으로 판정된 소리는 있지만, 보이는 얼굴에서 입을 여닫는 움직임이 반복되는 것을 확인하지 못했다
NO_MOUTH_MOVEMENT = "no_mouth_movement"

# 적합 구간이 없는 까닭이 "보이는 사람이 말하는 것을 확인하지 못함"인 원인 코드 묶음
NO_SPEECH_FAMILY = (AUDIO_MISSING, NO_SPEECH_DETECTED, NO_MOUTH_MOVEMENT)


@dataclass(frozen=True)
class GateConfig:
    """모든 값은 임시값이다. 검증된 운영 범위가 아니다 (docs/gate.md)."""

    # 얼굴 검출
    face_sample_fps: float = 5.0          # 초당 몇 프레임에서 얼굴을 검출할지
    min_detection_confidence: float = 0.5
    main_face_min_height_ratio: float = 0.10  # 프레임 짧은 변 대비. 이보다 작으면 주된 얼굴로 세지 않는다
    track_iou_threshold: float = 0.3      # 이전 표본의 얼굴과 같은 얼굴로 잇는 최소 겹침
    max_face_gap_sec: float = 0.5         # 같은 얼굴 사이의 짧은 검출 누락은 메운다
    # VAD
    vad_aggressiveness: int = 2           # webrtcvad 0~3
    vad_frame_ms: int = 30
    vad_min_speech_sec: float = 0.25      # 이보다 짧은 음성 조각은 버린다
    vad_merge_gap_sec: float = 0.4        # 이보다 짧은 쉼은 한 구간으로 잇는다
    # 입 움직임 (입 벌림 = 안쪽 입술 거리 / 두 눈 바깥꼬리 거리). 말하는 영상으로 검증하지 않은 임시값이다
    mouth_sample_fps: float = 15.0
    mouth_min_swing: float = 0.02            # 이만큼 되돌아가야 방향이 바뀐 것(반전)으로 센다
    mouth_min_reversals: int = 3             # 한 묶음에 필요한 반전 수. 3이면 입을 두 번 이상 연 것
    mouth_max_reversal_gap_sec: float = 0.75  # 반전 사이가 이보다 길면 다른 묶음이다
    mouth_pad_sec: float = 0.2               # 묶음 앞뒤로 붙이는 여유
    mouth_max_sample_gap_sec: float = 0.3    # 측정이 이보다 오래 끊기면 시계열을 나눈다
    # 구간 품질
    min_short_side_px: int = 360
    min_face_height_px: float = 96.0
    min_sharpness: float = 20.0           # 얼굴 영역을 256px로 맞춘 뒤의 Laplacian 분산
    min_segment_sec: float = 1.0
    # 서브프로세스
    subprocess_timeout_sec: float = 120.0


@dataclass(frozen=True)
class MediaInfo:
    duration_sec: float
    width: int            # 회전을 반영한 표시 기준
    height: int
    fps: float
    rotation: int
    has_audio: bool


@dataclass(frozen=True)
class Face:
    x: float
    y: float
    w: float
    h: float
    score: float
    sharpness: float
    track_id: int = -1


@dataclass(frozen=True)
class FrameFaces:
    t: float                  # 초
    faces: tuple[Face, ...]


@dataclass(frozen=True)
class MouthSample:
    t: float                                   # 초
    opening: Optional[float]                   # 입 벌림 비율. 특징점을 찾지 못했으면 None
    box: Optional[tuple[float, float, float, float]]  # 얼굴 박스 (x, y, w, h), 픽셀


@dataclass(frozen=True)
class SegmentQuality:
    face_height_px: float         # 구간 내 중앙값
    face_height_ratio: float      # 프레임 짧은 변 대비
    sharpness: float              # 구간 내 중앙값
    short_side_px: int
    face_frames: int              # 품질 계산에 쓴 표본 프레임 수


@dataclass(frozen=True)
class Segment:
    start_sec: float
    end_sec: float
    reason_code: Optional[str] = None       # 적합 구간이면 None
    quality: Optional[SegmentQuality] = None

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass(frozen=True)
class GateResult:
    """docs/DESIGN.md §9 coverage 형식에 맞춘 Gate 결과.

    Gate는 추론하지 않는다. analyzed_* 와 coverage 비율은 실제 분석한 양이므로
    여기서는 None이다(백로그 7번에서 채운다). 0으로 채우지 않는다.
    """

    media: Optional[MediaInfo]
    reason_code: Optional[str]              # 적합 구간이 하나도 없을 때의 대표 원인
    eligible_segments: tuple[Segment, ...] = ()
    excluded_segments: tuple[Segment, ...] = ()
    speech_segments: tuple[tuple[float, float], ...] = ()
    # 입을 여닫는 움직임이 반복된 구간. 입 움직임을 재지 않았으면 None이다
    mouth_active_segments: Optional[tuple[tuple[float, float], ...]] = None
    mouth_summary: Optional[dict] = None
    speaking_video_validated: bool = field(default=False)  # 말하는 영상으로는 검증하지 않았다
    multi_speaker_validated: bool = field(default=False)  # 여러 명 영상으로는 검증하지 않았다

    @property
    def eligible_duration_sec(self) -> float:
        return round(float(sum(s.duration_sec for s in self.eligible_segments)), 3)

    def coverage(self) -> dict:
        return {
            "video_duration_sec": None if self.media is None else self.media.duration_sec,
            "eligible_duration_sec": None if self.media is None else self.eligible_duration_sec,
            "analyzed_duration_sec": None,
            "full_video_coverage": None,
            "eligible_coverage": None,
            "analyzed_segments": None,
        }

    def to_dict(self) -> dict:
        def seg(s: Segment) -> dict:
            d = {"start_sec": s.start_sec, "end_sec": s.end_sec}
            if s.reason_code is not None:
                d["reason_code"] = s.reason_code
            if s.quality is not None:
                d["quality"] = asdict(s.quality)
            return d

        return {
            "reason_code": self.reason_code,
            "media": None if self.media is None else asdict(self.media),
            "coverage": self.coverage(),
            "eligible_segments": [seg(s) for s in self.eligible_segments],
            "excluded_segments": [seg(s) for s in self.excluded_segments],
            "speech_segments": [
                {"start_sec": a, "end_sec": b} for a, b in self.speech_segments
            ],
            "mouth_active_segments": None if self.mouth_active_segments is None else [
                {"start_sec": a, "end_sec": b} for a, b in self.mouth_active_segments
            ],
            "mouth_summary": self.mouth_summary,
            "speaking_video_validated": self.speaking_video_validated,
            "multi_speaker_validated": self.multi_speaker_validated,
        }
