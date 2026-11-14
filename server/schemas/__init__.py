"""결과·상태 Pydantic 모델 (README §9, §10).

작업 종료(job_status) ≠ 분석 완료(analysis_status) ≠ 진위 판정(verdict_status).
실패했거나 실행하지 않은 점수는 null이다. 0을 쓰지 않는다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    finished = "finished"
    failed = "failed"
    cancelled = "cancelled"


class AnalysisStatus(str, Enum):
    completed = "completed"
    partial = "partial"
    out_of_scope = "out_of_scope"
    unsupported = "unsupported"
    insufficient_quality = "insufficient_quality"
    analysis_unavailable = "analysis_unavailable"


class VerdictStatus(str, Enum):
    assessed = "assessed"
    abstained = "abstained"
    not_applicable = "not_applicable"


class VerdictLabel(str, Enum):
    """결과 요약의 라벨. 서버가 고정된 임계값으로 정한다. low_suspicion은 진짜라는 뜻이 아니다."""

    suspicious_signals = "suspicious_signals"
    low_suspicion = "low_suspicion"


class AxisStatus(str, Enum):
    completed = "completed"
    insufficient_input = "insufficient_input"
    unsupported_input = "unsupported_input"
    out_of_distribution = "out_of_distribution"
    error = "error"


class Stage(str, Enum):
    validating = "validating"
    access_check = "access_check"
    preprocessing = "preprocessing"
    waverep = "waverep"
    motionphys = "motionphys"
    syncnet = "syncnet"
    fusion = "fusion"
    finalizing = "finalizing"


STAGE_ORDER = [s.value for s in Stage]


class CreateAnalysisRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class CreateAnalysisResponse(BaseModel):
    analysis_id: str
    youtube_video_id: str
    job_status: JobStatus


class AnalysisStatusResponse(BaseModel):
    analysis_id: str
    job_status: JobStatus
    stage: Optional[Stage] = None
    completed_stages: list[Stage] = []


class PendingResultResponse(BaseModel):
    """작업이 끝나기 전 GET /result의 202 응답. job_status와 stage만 담는다."""

    job_status: JobStatus
    stage: Optional[Stage] = None


class Segment(BaseModel):
    start_sec: float
    end_sec: float


class Coverage(BaseModel):
    """분석한 양. 정확도나 신뢰도가 아니다."""

    video_duration_sec: Optional[float] = None
    eligible_duration_sec: Optional[float] = None
    analyzed_duration_sec: Optional[float] = None
    full_video_coverage: Optional[float] = None
    eligible_coverage: Optional[float] = None
    analyzed_segments: list[Segment] = []


class SignalAxis(BaseModel):
    status: AxisStatus
    reason_code: Optional[str] = None
    raw_score: Optional[float] = None
    model_version: Optional[str] = None


class PhysicsAxis(BaseModel):
    status: AxisStatus
    reason_code: Optional[str] = None
    raw_score: Optional[float] = None
    model_version: Optional[str] = None


class AlignmentAxis(BaseModel):
    """SyncNet은 진위 분류기가 아니라 동기화 보조 지표다."""

    status: AxisStatus
    reason_code: Optional[str] = None
    lse_c: Optional[float] = None
    lse_d: Optional[float] = None
    included_in_fusion: bool = False
    model_version: Optional[str] = None


class Axes(BaseModel):
    signal: SignalAxis
    physics: PhysicsAxis
    alignment: AlignmentAxis


class Explanation(BaseModel):
    template_id: str
    reason_code: str
    message: str


class AnalysisResult(BaseModel):
    """finished 작업의 결과. 실패·취소 작업은 job_status와 reason_code만 채운다.

    미완료(queued·processing) 작업은 이 모델 대신 PendingResultResponse(202)로 답한다.
    """

    analysis_id: str
    youtube_video_id: str
    job_status: JobStatus
    analysis_status: Optional[AnalysisStatus] = None
    verdict_status: Optional[VerdictStatus] = None
    # 검증된 결합 모델이 없으면 null이다. assessed가 아닌 결과에는 붙일 수 없다 (README §9).
    verdict_label: Optional[VerdictLabel] = None
    overall_score: Optional[float] = None
    abstention_reason: Optional[str] = None
    reason_code: Optional[str] = None
    media_provenance: Optional[str] = None
    coverage: Optional[Coverage] = None
    axes: Optional[Axes] = None
    explanations: list[Explanation] = []

    @model_validator(mode="after")
    def _label_only_when_assessed(self) -> "AnalysisResult":
        if self.verdict_label is not None and self.verdict_status != VerdictStatus.assessed:
            raise ValueError("verdict_label은 verdict_status=assessed일 때만 쓸 수 있다")
        return self


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
