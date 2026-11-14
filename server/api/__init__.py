"""FastAPI 앱 팩토리와 라우터(analyses / health)."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import Settings
from server.jobs.queue import JobQueue


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    from server.api import analyses, health

    settings = settings or Settings.from_env()
    queue = JobQueue(settings.db_path)
    queue.init_schema()

    app = FastAPI(title="TRINITY", version="0.1.0")
    app.state.settings = settings
    app.state.queue = queue
    if settings.cors_origins:
        # 목록에 있는 출처만 허용한다. 와일드카드와 쿠키 인증은 쓰지 않는다.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Client-Token"],
            allow_credentials=False,
        )
    app.include_router(health.router)
    app.include_router(analyses.router)
    return app
