"""실측 전용 계정과 루프백 API. 발급한 개인 키는 호출 프로세스 메모리에만 둔다."""
from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TextIO

from server import accounts


class WorkerSmokeAPI:
    def __init__(self, db: Path, port: int, timeout: float = 3):
        accounts.initialize(db)
        _, self._key = accounts.issue(db)
        self.port = port
        self.timeout = timeout

    def call(self, path: str, method: str = "GET", body=None, etag: str | None = None):
        headers = {}
        if path != "/health":
            headers["Authorization"] = f"Bearer {self._key}"
        if etag is not None:
            headers["If-Match"] = etag
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()
        if method == "POST":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        # 접수 직후 응답을 잃으면 같은 접수 키로 한 번 더 보낸다.
        attempts = 2 if method == "POST" else 1
        for attempt in range(attempts):
            # 직접 연결하므로 환경 프록시와 HTTP 리디렉션을 따라가지 않는다.
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
            try:
                conn.request(method, "/api/v1" + path, body=payload, headers=headers)
                with conn.getresponse() as response:
                    raw = response.read()
                    data = json.loads(raw) if raw and 200 <= response.status < 300 else None
                    return response.status, data, response.headers
            except (OSError, http.client.IncompleteRead):
                if attempt + 1 == attempts:
                    raise
            finally:
                conn.close()


def start_worker_api(root: Path, env: dict[str, str], log: TextIO, *, timeout: float = 3):
    """선점한 리스너를 API에 넘기고, 준비에 실패하면 서버까지 회수한다."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        api = WorkerSmokeAPI(Path(env["TRINITY_DB_PATH"]), sock.getsockname()[1], timeout)
        sock.listen()
        fd = sock.fileno()
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.main:app", "--fd", str(fd), "--no-access-log"],
            pass_fds=(fd,), cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 20
        while proc.poll() is None and time.monotonic() < deadline:
            try:
                if api.call("/health")[0] == 200:
                    return proc, api
            except OSError:
                pass
            time.sleep(.05)
        raise RuntimeError("API 서버 시작 실패")
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        raise
