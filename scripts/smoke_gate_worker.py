"""실제 서버·Worker와 기존 발화 없는 허가 샘플로 Gate 차단을 검증한다.

conda trinity에서 실행: python scripts/smoke_gate_worker.py
네트워크 다운로드 없이 검증용 ID를 임시 레지스트리에 연결한다. API 입력은 YouTube URL뿐이다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4"


def main() -> int:
    if not SAMPLE.is_file():
        raise SystemExit("기존 발화 없는 허가 샘플이 없습니다. 미검증.")
    if importlib.util.find_spec("torch") is not None:
        raise SystemExit("torch 없는 trinity 환경에서 실행하세요.")
    runtime = ROOT / "data/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gate-smoke-", dir=runtime) as directory:
        work = Path(directory)
        registry = work / "registry.json"
        registry.write_text(json.dumps({"authorized_media": [{
            "youtube_video_id": "TRINITYtest", "local_path": SAMPLE.name,
        }]}), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRINITY_")}
        env.update(
            TRINITY_DB_PATH=str(work / "queue.sqlite3"), TRINITY_RUNTIME_DIR=str(work / "jobs"),
            TRINITY_AUTHORIZED_MEDIA=str(registry), TRINITY_AUTHORIZED_MEDIA_ROOT=str(SAMPLE.parent),
            TRINITY_HEARTBEAT_INTERVAL_SECONDS="0.2", TRINITY_LEASE_SECONDS="2",
            TRINITY_GATE_TIMEOUT_SECONDS="30", TRINITY_JOB_TIMEOUT_SECONDS="60",
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}/api/v1"
        token = uuid.uuid4().hex

        def call(path, body=None):
            req = urllib.request.Request(
                base + path, data=None if body is None else json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "X-Client-Token": token},
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)

        with (work / "server.log").open("w") as server_log, (work / "worker.log").open("w") as worker_log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT,
            )
            worker = None
            try:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        assert call("/health")[0] == 200
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() > deadline or server.poll() is not None:
                            raise RuntimeError("API 서버 시작 실패") from None
                        time.sleep(.1)
                status, created = call("/analyses", {"url": "https://www.youtube.com/watch?v=TRINITYtest"})
                assert status == 202
                aid = created["analysis_id"]
                worker = subprocess.Popen(
                    [sys.executable, "-m", "server.jobs.worker", "--drain"],
                    cwd=ROOT, env=env, stdout=worker_log, stderr=subprocess.STDOUT,
                )
                leases = set()
                started = time.monotonic()
                while worker.poll() is None:
                    if time.monotonic() - started > 90:
                        raise RuntimeError("Worker 제한시간 초과")
                    with sqlite3.connect(work / "queue.sqlite3") as db:
                        stage, expiry = db.execute(
                            "SELECT stage, lease_expires_at FROM jobs WHERE analysis_id=?", (aid,),
                        ).fetchone()
                        if stage == "preprocessing":
                            leases.add(expiry)
                    time.sleep(.05)
                assert worker.returncode == 0
                _, job = call(f"/analyses/{aid}")
                _, result = call(f"/analyses/{aid}/result")
                assert (result["job_status"], result["analysis_status"], result["verdict_status"]) == (
                    "finished", "out_of_scope", "not_applicable",
                )
                assert result["reason_code"] == "no_mouth_movement"
                assert result["gate_bypassed"] is False
                assert result["axes"]["signal"]["raw_score"] is None
                assert result["axes"]["signal"]["raw_metrics"] is None
                assert result["overall_score"] is None
                assert result["coverage"]["eligible_duration_sec"] == 0
                assert job["completed_stages"] == ["validating", "access_check", "preprocessing", "finalizing"]
                assert len(leases) >= 2, "실제 Gate 실행 중 lease 연장을 관찰하지 못함"
                assert not (work / "jobs" / aid).exists()
                assert "waverep" not in (work / "worker.log").read_text()
                print(json.dumps({
                    "python": sys.executable, "torch_present": False,
                    "job_status": result["job_status"], "analysis_status": result["analysis_status"],
                    "verdict_status": result["verdict_status"], "reason_code": result["reason_code"],
                    "gate_bypassed": result["gate_bypassed"], "coverage": result["coverage"],
                    "signal": result["axes"]["signal"], "overall_score": result["overall_score"],
                    "completed_stages": job["completed_stages"],
                    "preprocessing_lease_values_observed": len(leases),
                    "elapsed_sec": round(time.monotonic() - started, 2),
                    "temporary_job_removed": True, "speaking_video": "미검증",
                }, ensure_ascii=False, indent=2))
            finally:
                for process in (worker, server):
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=65)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
