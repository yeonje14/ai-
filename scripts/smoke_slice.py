"""실행 중인 서버와 worker에 URL-only 수직 슬라이스를 실제로 요청해 본다.

사전 조건: API 서버와 worker가 떠 있어야 한다(README 하단 "서버 실행 방법").
사용: python scripts/smoke_slice.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
HEADERS = {"Content-Type": "application/json", "X-Client-Token": "local-smoke-token-0001"}


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
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
    for _ in range(100):
        _, st = call("GET", f"/api/v1/analyses/{aid}")
        mark = f"{st['job_status']}/{st['stage']}"
        if not seen or seen[-1] != mark:
            seen.append(mark)
        if st["job_status"] not in ("queued", "processing"):
            break
        time.sleep(0.1)
    print(f"\n== [{label}] 관찰한 상태 전이: {' -> '.join(seen)}")
    show(f"[{label}] GET /analyses/{{id}}", *call("GET", f"/api/v1/analyses/{aid}"))
    show(f"[{label}] GET /analyses/{{id}}/result", *call("GET", f"/api/v1/analyses/{aid}/result"))


if __name__ == "__main__":
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
