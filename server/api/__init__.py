"""FastAPI 앱 팩토리와 라우터(analyses / health)."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from server.config import Settings
from server.jobs import admission
from server.jobs.queue import JobQueue


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    from server.api import analyses, health

    settings = settings or Settings.from_env()
    # 사전 초기화된 계정 DB만 허용한다. 스키마 설치도 다른 API 시작과 직렬화한다.
    queue = JobQueue.open_registered(settings.db_path, prepare=admission.prepare)

    app = FastAPI(title="TRINITY", version="0.1.0")
    app.state.settings = settings
    app.state.queue = queue

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/analyses"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    def invalid_request(request: Request, exc: RequestValidationError):
        # FastAPI는 잘못된 JSON/쿼리를 핸들러 진입 전에 거부한다.
        # 이 경우도 같은 인증 오류를 반환하고 입력 원문을 되돌려주지 않는다.
        try:
            key = analyses.bearer_key(request)
            with analyses.authorized(request, key, write=request.method in {"POST", "DELETE"}):
                missing_key = any(error["loc"] == ("header", "idempotency-key") for error in exc.errors())
                reason = "invalid_idempotency_key" if missing_key else "invalid_request"
                return JSONResponse({"detail": {"reason_code": reason}}, status_code=422)
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)

    if settings.cors_origins:
        # 목록에 있는 출처만 허용한다. 와일드카드와 쿠키 인증은 쓰지 않는다.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "Authorization", "If-Match", "Idempotency-Key"],
            expose_headers=["ETag", "Retry-After"],
            allow_credentials=False,
        )
    app.include_router(health.router)
    app.include_router(analyses.router)
    return app
