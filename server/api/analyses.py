"""분석 작업 등록·조회 (docs/DESIGN.md §9). 핸들러는 큐에 넣고 읽기만 한다. 분석하지 않는다."""

import math
import re
import sqlite3
from contextlib import contextmanager
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPBearer
from fastapi.responses import JSONResponse

from server import accounts
from server.ingest.youtube_url import InvalidYouTubeUrl, parse_youtube_url
from server.jobs.queue import Job, QueueFull, PreconditionFailed, lifecycle_etag
from server.jobs.runtime import remove_job_dir
from server.schemas import (
    AnalysisListResponse,
    AnalysisResult,
    AnalysisStatusResponse,
    CreateAnalysisRequest,
    CreateAnalysisResponse,
    PendingResultResponse,
    dump,
)


def unauthorized() -> HTTPException:
    return HTTPException(401, detail={"reason_code": "authentication_required"},
                         headers={"WWW-Authenticate": "Bearer"})


class AccountBearer(HTTPBearer):
    def __call__(self, request: Request) -> str:
        values = request.headers.getlist("authorization")
        if "x-client-token" in request.headers or len(values) != 1:
            raise unauthorized()
        match = re.fullmatch(r"Bearer +([A-Za-z0-9_-]{43})", values[0], re.IGNORECASE | re.ASCII)
        if not match:
            raise unauthorized()
        return match[1]


bearer_key = AccountBearer()
router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])


@contextmanager
def authorized(request: Request, key: str, *, write: bool = False):
    try:
        with accounts.connection(request.app.state.settings.db_path, write=write) as conn:
            conn.row_factory = sqlite3.Row
            owner = accounts.identify_in(conn, key)
            if owner is None:
                raise unauthorized()
            yield conn, owner
    except sqlite3.OperationalError as exc:
        primary_code = getattr(exc, "sqlite_errorcode", 0) & 0xff
        if primary_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise HTTPException(503, detail={"reason_code": "temporarily_unavailable"}) from None
        raise


def _owned_job(request: Request, analysis_id: str, key: str) -> Job:
    with authorized(request, key) as (conn, owner):
        job = request.app.state.queue.get_in(conn, analysis_id, owner)
    if job is None:
        raise HTTPException(status_code=404, detail={"reason_code": "analysis_not_found"})
    return job


@router.post("", status_code=202, response_model=CreateAnalysisResponse)
def create_analysis(
    body: CreateAnalysisRequest,
    request: Request,
    key: str = Depends(bearer_key),
) -> CreateAnalysisResponse:
    with authorized(request, key, write=True) as (conn, owner):
        try:
            parsed = parse_youtube_url(body.url)
        except InvalidYouTubeUrl:
            raise HTTPException(422, detail={"reason_code": "invalid_youtube_url"}) from None
        try:
            analysis_id = request.app.state.queue.enqueue_in(
                conn, parsed.video_id, owner, request.app.state.settings.max_queued
            )
        except QueueFull:
            raise HTTPException(429, detail={"reason_code": "queue_full"}) from None
    return CreateAnalysisResponse(
        analysis_id=analysis_id, youtube_video_id=parsed.video_id, job_status="queued"
    )


@router.get("", response_model=AnalysisListResponse)
def list_analyses(request: Request, limit: int = Query(20, ge=1, le=20),
                  cursor: Optional[str] = None, key: str = Depends(bearer_key)):
    with authorized(request, key) as (conn, owner):
        params = [owner]
        boundary = ""
        if cursor is not None:
            try:
                stamp, aid = cursor.split("~")
                created = float(stamp)
                if not math.isfinite(created) or str(UUID(aid)) != aid:
                    raise ValueError
            except ValueError:
                raise HTTPException(422, detail={"reason_code": "invalid_cursor"}) from None
            boundary = " AND (created_at, analysis_id) < (?, ?)"
            params.extend((created, aid))
        rows = conn.execute(
            "SELECT analysis_id, created_at, job_status FROM jobs WHERE user_id=?" + boundary
            + " ORDER BY created_at DESC, analysis_id DESC LIMIT ?", (*params, limit + 1)
        ).fetchall()
    items = [dict(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = f"{last['created_at']}~{last['analysis_id']}"
    return {"items": items, "next_cursor": next_cursor}


@router.get("/{analysis_id}", response_model=AnalysisStatusResponse)
def get_analysis(
    analysis_id: str, request: Request, response: Response, key: str = Depends(bearer_key)
) -> AnalysisStatusResponse:
    job = _owned_job(request, analysis_id, key)
    response.headers["ETag"] = lifecycle_etag(job)
    response.headers["Cache-Control"] = "no-store"
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
    analysis_id: str, request: Request, key: str = Depends(bearer_key)
):
    job = _owned_job(request, analysis_id, key)
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


@router.delete(
    "/{analysis_id}", status_code=202, response_model=AnalysisStatusResponse,
    responses={204: {"description": "종료 작업 삭제"}, 412: {"description": "수명주기 조건 불일치"}},
)
def delete_analysis(
    analysis_id: str, request: Request,
    if_match: Optional[str] = Header(default=None), key: str = Depends(bearer_key),
):
    try:
        with authorized(request, key, write=True) as (conn, owner):
            code, job = request.app.state.queue.cancel_or_delete(
                conn, analysis_id, owner, if_match,
                lambda aid: remove_job_dir(request.app.state.settings.runtime_dir, aid),
            )
    except PreconditionFailed:
        return Response(status_code=412, headers={"Cache-Control": "no-store"})
    except OSError:
        # 경로·영상·토큰 정보를 응답에 싣지 않는다. 삭제 성공으로 보고하지 않는다.
        raise HTTPException(status_code=500) from None
    if code == 404:
        raise HTTPException(status_code=404, detail={"reason_code": "analysis_not_found"})
    if code == 204:
        return Response(status_code=204)
    body = AnalysisStatusResponse(
        analysis_id=job.analysis_id, job_status=job.job_status,
        stage=job.stage, completed_stages=job.completed_stages,
    )
    return JSONResponse(status_code=202, content=dump(body), headers={
        "ETag": lifecycle_etag(job), "Cache-Control": "no-store",
    })
