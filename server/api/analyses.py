"""분석 작업 등록·조회 (README §9). 핸들러는 큐에 넣고 읽기만 한다. 분석하지 않는다."""

from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from server.ingest.youtube_url import InvalidYouTubeUrl, parse_youtube_url
from server.jobs.queue import Job, JobQueue, QueueFull
from server.schemas import (
    AnalysisResult,
    AnalysisStatusResponse,
    CreateAnalysisRequest,
    CreateAnalysisResponse,
    PendingResultResponse,
    dump,
)

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])

_TOKEN_MIN, _TOKEN_MAX = 16, 256


def owner_hash(x_client_token: Optional[str] = Header(default=None)) -> str:
    """최소한의 작업 소유권 확인. 정식 인증은 백로그 14번에서 바꾼다.

    토큰 원문은 저장하거나 로그에 남기지 않고 해시만 쓴다.
    """
    if x_client_token is None or not (_TOKEN_MIN <= len(x_client_token) <= _TOKEN_MAX):
        raise HTTPException(status_code=401, detail={"reason_code": "client_token_required"})
    return hashlib.sha256(x_client_token.encode("utf-8")).hexdigest()


def _queue(request: Request) -> JobQueue:
    return request.app.state.queue


def _owned_job(analysis_id: str, queue: JobQueue, owner: str) -> Job:
    # 다른 사용자의 작업은 없는 작업과 구별되지 않게 404로 답한다.
    job = queue.get(analysis_id, owner)
    if job is None:
        raise HTTPException(status_code=404, detail={"reason_code": "analysis_not_found"})
    return job


@router.post("", status_code=202, response_model=CreateAnalysisResponse)
def create_analysis(
    body: CreateAnalysisRequest,
    request: Request,
    owner: str = Depends(owner_hash),
) -> CreateAnalysisResponse:
    try:
        parsed = parse_youtube_url(body.url)
    except InvalidYouTubeUrl:
        # 입력 URL을 응답이나 로그에 되돌려 쓰지 않는다.
        raise HTTPException(status_code=422, detail={"reason_code": "invalid_youtube_url"})
    try:
        analysis_id = _queue(request).enqueue(
            parsed.video_id, owner, request.app.state.settings.max_queued
        )
    except QueueFull:
        raise HTTPException(status_code=429, detail={"reason_code": "queue_full"})
    return CreateAnalysisResponse(
        analysis_id=analysis_id, youtube_video_id=parsed.video_id, job_status="queued"
    )


@router.get("/{analysis_id}", response_model=AnalysisStatusResponse)
def get_analysis(
    analysis_id: str, request: Request, owner: str = Depends(owner_hash)
) -> AnalysisStatusResponse:
    job = _owned_job(analysis_id, _queue(request), owner)
    return AnalysisStatusResponse(
        analysis_id=job.analysis_id,
        job_status=job.job_status,
        stage=job.stage,
        completed_stages=job.completed_stages,
    )


@router.get(
    "/{analysis_id}/result",
    response_model=AnalysisResult,
    responses={202: {"model": PendingResultResponse, "description": "작업이 아직 끝나지 않음"}},
)
def get_analysis_result(
    analysis_id: str, request: Request, owner: str = Depends(owner_hash)
):
    job = _owned_job(analysis_id, _queue(request), owner)
    if job.job_status == "finished" and job.result is not None:
        return AnalysisResult.model_validate(job.result)
    if job.job_status in ("queued", "processing"):
        # 미완료: 결과를 꾸며내지 않고 202와 함께 job_status·stage만 돌려준다.
        pending = PendingResultResponse(job_status=job.job_status, stage=job.stage)
        return JSONResponse(status_code=202, content=dump(pending))
    # 실패·취소: 결과 없이 작업 상태와 원인만 돌려준다.
    return AnalysisResult(
        analysis_id=job.analysis_id,
        youtube_video_id=job.youtube_video_id,
        job_status=job.job_status,
        reason_code=job.failure_reason,
    )
