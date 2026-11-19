"""FastAPI 앱 팩토리와 라우터(analyses / health)."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from server import accounts
from server.config import Settings
from server.jobs.queue import JobQueue


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    from server.api import analyses, health

    settings = settings or Settings.from_env()
    # 구 DB를 열어 마이그레이션하거나 빈 DB를 암묵적으로 생성하지 않는다.
    with accounts.connection(settings.db_path, write=False) as conn:
        conn.execute("SELECT user_id FROM jobs LIMIT 0")
    queue = JobQueue(settings.db_path, registered_users=True)

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
                return JSONResponse({"detail": {"reason_code": "invalid_request"}}, status_code=422)
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)

    if settings.cors_origins:
        # 목록에 있는 출처만 허용한다. 와일드카드와 쿠키 인증은 쓰지 않는다.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "Authorization", "If-Match"],
            expose_headers=["ETag"],
            allow_credentials=False,
        )
    app.include_router(health.router)
    app.include_router(analyses.router)
    return app
