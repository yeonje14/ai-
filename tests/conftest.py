from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import accounts
from server.api import create_app
from server.config import Settings
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.jobs.queue import JobQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTERED_ID = "TRINITYtest"   # 가짜 ID. 실제 영상이 아니다.
REGISTERED_MEDIA = "registered.mp4"
REGISTERED_NO_MEDIA_ID = "TRINITYnone"  # 등록됐지만 미디어 파일이 연결되지 않은 가짜 ID
UNREGISTERED_ID = "dQw4w9WgXcQ"  # docs/DESIGN.md §9의 형식 설명용 예시 ID
TOKEN = "A" * 43
OTHER_TOKEN = "B" * 43


@pytest.fixture(autouse=True)
def _no_real_thermal_probe(monkeypatch):
    """Worker 테스트마다 thermalState 프로브 자식 프로세스(축마다 2개)가 뜨지 않게 한다.

    프로브 자체는 tests/test_device_state.py가 server.jobs.device_state를 직접 불러 확인한다.
    값을 보는 Worker 테스트는 이 이름을 다시 바꾼다.
    """
    monkeypatch.setattr("server.jobs.worker.thermal_state", lambda: None)


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
def account_db(settings: Settings):
    accounts.initialize(settings.db_path)
    with accounts.connection(settings.db_path, write=True) as conn:
        for uid, key in (("test-user", TOKEN), ("other-user", OTHER_TOKEN)):
            conn.execute("INSERT INTO users(user_id) VALUES (?)", (uid,))
            conn.execute("INSERT INTO credentials(digest,user_id,expires_at) VALUES (?,?,?)",
                         (hashlib.sha256(key.encode()).digest(), uid, 4102444800))
    return settings.db_path


@pytest.fixture
def client(settings: Settings, account_db) -> TestClient:
    return TestClient(create_app(settings), headers={"Authorization": f"Bearer {TOKEN}"})


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
