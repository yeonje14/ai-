"""실행 중인 서버와 worker에 URL-only 수직 슬라이스를 실제로 요청해 본다.

격리 실행: python scripts/smoke_slice.py --isolated (미등록 ID, 임시 계정 DB와 별도 Worker).
기존 서버 모드는 운영자가 발급한 키를 대화형으로 입력한다.
사전 조건: API 서버와 worker가 떠 있어야 한다(docs/DESIGN.md 하단 "서버 실행 방법").
사용: python scripts/smoke_slice.py [http://127.0.0.1:8000] [작업당 최대 대기 초=180]
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import uuid
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"
WAIT_SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0
HEADERS = {"Content-Type": "application/json"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


opener = urllib.request.build_opener(NoRedirect)


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(HEADERS)
    if method == "POST":
        headers["Idempotency-Key"] = str(uuid.uuid4())
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def show(title: str, status: int, payload: dict) -> None:
    print(f"\n== {title} -> HTTP {status}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run(label: str, video_id: str) -> None:
    status, created = call(
        "POST", "/api/v1/analyses", {"url": f"https://www.youtube.com/watch?v={video_id}"}
    )
    show(f"[{label}] POST /analyses", status, created)
    aid = created["analysis_id"]
    seen: list[str] = []
    deadline = time.monotonic() + WAIT_SECONDS  # 실제 WaveRep 추론은 수십 초가 걸릴 수 있다
    while time.monotonic() < deadline:
        _, st = call("GET", f"/api/v1/analyses/{aid}")
        mark = f"{st['job_status']}/{st['stage']}"
        if not seen or seen[-1] != mark:
            seen.append(mark)
        if st["job_status"] not in ("queued", "processing"):
            break
        time.sleep(1)
    print(f"\n== [{label}] 관찰한 상태 전이: {' -> '.join(seen)}")
    show(f"[{label}] GET /analyses/{{id}}", *call("GET", f"/api/v1/analyses/{aid}"))
    show(f"[{label}] GET /analyses/{{id}}/result", *call("GET", f"/api/v1/analyses/{aid}/result"))


def isolated() -> None:
    global BASE
    sys.path.insert(0, str(ROOT))
    from server import accounts

    with tempfile.TemporaryDirectory(prefix="trinity-smoke-") as tmp, socket.socket() as sock:
        root = Path(tmp).resolve()
        db = root / "accounts.sqlite"
        accounts.initialize(db)
        _, key = accounts.issue(db)
        HEADERS["Authorization"] = f"Bearer {key}"
        registry = root / "registry.json"
        registry.write_text('{"authorized_media":[]}')
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRINITY_")}
        env.update(TRINITY_DB_PATH=str(db), TRINITY_RUNTIME_DIR=str(root / "jobs"),
                   TRINITY_AUTHORIZED_MEDIA=str(registry), TRINITY_AUTHORIZED_MEDIA_ROOT=str(root))
        sock.bind(("127.0.0.1", 0))
        BASE = f"http://127.0.0.1:{sock.getsockname()[1]}"
        sock.listen()
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.main:app", "--fd", str(sock.fileno()),
                                   "--no-access-log"], env=env, cwd=ROOT, pass_fds=(sock.fileno(),))
        try:
            sock.close()
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("API 서버 시작 실패")
                try:
                    if call("GET", "/api/v1/health")[0] == 200:
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(.05)
            else:
                raise RuntimeError("서버 대기 시간 초과")
            code, job = call("POST", "/api/v1/analyses", {"url": "https://youtu.be/TRINITYnone"})
            assert code == 202 and job["job_status"] == "queued"
            subprocess.run([sys.executable, "-m", "server.jobs.worker", "--drain"],
                           env=env, cwd=ROOT, timeout=30, check=True)
            code, result = call("GET", f"/api/v1/analyses/{job['analysis_id']}/result")
            assert code == 200 and result["job_status"] == "finished"
            assert result["analysis_status"] == "analysis_unavailable" and result["verdict_status"] == "abstained"
            assert result["overall_score"] is None
            print("POST 202 → Worker --drain 종료 0 → 결과 200, finished / analysis_unavailable / abstained")
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            HEADERS.pop("Authorization", None)


if __name__ == "__main__":
    if sys.argv[1:] == ["--isolated"]:
        isolated()
        sys.exit(0)
    if len(sys.argv) > 1:
        BASE = sys.argv[1].rstrip("/")
    from urllib.parse import urlsplit
    target = urlsplit(BASE)
    if target.scheme != "https" and not (target.scheme == "http" and target.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise SystemExit("루프백 또는 HTTPS 주소가 필요합니다.")
    HEADERS["Authorization"] = "Bearer " + getpass.getpass("개인 Bearer 키: ")
    show("GET /health", *call("GET", "/api/v1/health"))
    run("등록 ID", "TRINITYtest")
    run("미등록 ID", "dQw4w9WgXcQ")
    show(
        "잘못된 URL",
        *call("POST", "/api/v1/analyses", {"url": "https://evil.example/watch?v=dQw4w9WgXcQ"}),
    )
    show(
        "없는 작업",
        *call("GET", "/api/v1/analyses/00000000-0000-4000-8000-000000000000"),
    )
