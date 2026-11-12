"""FastAPI 앱 팩토리와 라우터(analyses / health)."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

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
    app.include_router(health.router)
    app.include_router(analyses.router)
    return app
