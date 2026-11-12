from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api import create_app
from server.config import Settings
from server.jobs.queue import JobQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTERED_ID = "TRINITYtest"   # 가짜 ID. 실제 영상이 아니다.
UNREGISTERED_ID = "dQw4w9WgXcQ"  # README §9의 형식 설명용 예시 ID
TOKEN = "test-client-token-0001"
OTHER_TOKEN = "test-client-token-0002"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    registry = tmp_path / "authorized_media.json"
    registry.write_text(
        json.dumps({"authorized_media": [{"youtube_video_id": REGISTERED_ID}]}),
        encoding="utf-8",
    )
    return replace(
        Settings(),
        db_path=tmp_path / "trinity.sqlite3",
        runtime_dir=tmp_path / "jobs",
        authorized_media_path=registry,
    )


@pytest.fixture
def queue(settings: Settings) -> JobQueue:
    q = JobQueue(settings.db_path)
    q.init_schema()
    return q


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), headers={"X-Client-Token": TOKEN})


@pytest.fixture
def run_worker(settings: Settings):
    """Worker를 실제 별도 프로세스로 띄워 대기열을 비운다."""

    def _run() -> subprocess.CompletedProcess:
        env = dict(
            os.environ,
            TRINITY_DB_PATH=str(settings.db_path),
            TRINITY_RUNTIME_DIR=str(settings.runtime_dir),
            TRINITY_AUTHORIZED_MEDIA=str(settings.authorized_media_path),
        )
        return subprocess.run(
            [sys.executable, "-m", "server.jobs.worker", "--drain"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

    return _run
