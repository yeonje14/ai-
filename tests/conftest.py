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
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.jobs.queue import JobQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTERED_ID = "TRINITYtest"   # 가짜 ID. 실제 영상이 아니다.
REGISTERED_MEDIA = "registered.mp4"
REGISTERED_NO_MEDIA_ID = "TRINITYnone"  # 등록됐지만 미디어 파일이 연결되지 않은 가짜 ID
UNREGISTERED_ID = "dQw4w9WgXcQ"  # README §9의 형식 설명용 예시 ID
TOKEN = "test-client-token-0001"
OTHER_TOKEN = "test-client-token-0002"


@pytest.fixture(autouse=True)
def _no_real_motionphys(tmp_path: Path, monkeypatch):
    """테스트가 이 기기의 research/motionphys/.venv를 몰래 실행하지 않게 한다.

    physics 축을 보는 테스트는 build_config를 가짜 프로세스로 다시 바꾼다. 실제 영상 테스트는
    어댑터를 MotionPhysConfig()로 직접 부른다. 바꾸지 않은 테스트에서는 실행 환경이 없는 것과 같다.
    """
    from server.axes import physics
    from server.axes.physics.motionphys import MotionPhysConfig

    missing = MotionPhysConfig(python=tmp_path / "no-motionphys-python")
    monkeypatch.setattr(physics, "build_config", lambda ctx: missing)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # 가짜 허가 미디어 파일. 실제 영상이 아니다(모델을 실행하는 테스트는 가짜 추론 프로세스를 쓴다).
    media_root = tmp_path / "media"
    media_root.mkdir()
    (media_root / REGISTERED_MEDIA).write_bytes(b"not a real video")
    registry = tmp_path / "authorized_media.json"
    registry.write_text(
        json.dumps({"authorized_media": [
            {"youtube_video_id": REGISTERED_ID, "local_path": REGISTERED_MEDIA},
            {"youtube_video_id": REGISTERED_NO_MEDIA_ID},
        ]}),
        encoding="utf-8",
    )
    return replace(
        Settings(),
        db_path=tmp_path / "trinity.sqlite3",
        runtime_dir=tmp_path / "jobs",
        authorized_media_path=registry,
        authorized_media_root=media_root,
    )


@pytest.fixture
def registry(settings: Settings) -> AuthorizedMediaRegistry:
    return AuthorizedMediaRegistry.from_file(
        settings.authorized_media_path, settings.authorized_media_root
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
            TRINITY_AUTHORIZED_MEDIA_ROOT=str(settings.authorized_media_root),
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
