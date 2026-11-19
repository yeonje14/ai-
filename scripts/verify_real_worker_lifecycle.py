"""실제 영상 A로 Worker 수명주기를 확인한다: SyncNet 단계 제한, Worker SIGKILL 복구, MPS 실행 중 취소.

    conda activate trinity
    python scripts/verify_real_worker_lifecycle.py                       # 전체 시나리오(된 것은 건너뜀)
    python scripts/verify_real_worker_lifecycle.py --only cancel-syncnet  # 하나만
    python scripts/verify_real_worker_lifecycle.py --report               # 요약 표

시나리오 (제품 코드·기본값 변경 없음, 설정은 환경 변수로만 바꾼다)
  timeout-length     SyncNet 단계 제한을 길이 규칙으로 30초로 낮춤(BASE=30, PER_ELIGIBLE=0) → SyncNet만 error/timeout인지
  timeout-remaining  작업 제한을 150초로 낮춤(JOB BASE=150, PER_ELIGIBLE=0) → SyncNet 제한이 "남은 시간 − 마무리 여유"로 정해지고
                     작업은 finished로 끝나는지(작업 failed/timeout이 아닌지)
  sigkill-syncnet    SyncNet(MPS) 실행 중 Worker를 SIGKILL → 모델·FFmpeg 자식이 정리되는지, 새 Worker가 lease 만료 뒤 복구해 끝내는지
  cancel-syncnet     SyncNet(MPS) 실행 중 API DELETE로 취소 → 자식까지 끝나고 cancelled인지
  cancel-waverep     WaveRep(MPS) 실행 중 API DELETE로 취소(heartbeat 2초) → 자식까지 끝나고 cancelled인지

실제 API 서버(uvicorn)와 별도 Worker 프로세스를 띄운다. 입력은 임시 레지스트리에 등록한 허가 샘플 A(테스트 ID)뿐이다.
결과는 Git 밖 data/research/real-lifecycle/<시나리오>.json. 임시 레지스트리·DB·작업 폴더·로그는 끝나면 지운다.
로그·결과에는 analysis_id, 단계명, 프로세스 이름(실행 파일·스크립트 이름)만 남긴다. URL·영상 내용은 남기지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
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
OUT = ROOT / "data/research/real-lifecycle"
RUNTIME = ROOT / "data/runtime/real-lifecycle"
TEST_ID = "TRINITYtest"
ABCD_SCENARIOS = ("sigkill-gate", "sigkill-waverep", "sigkill-motionphys", "cancel-motionphys")
SCENARIOS = ("timeout-length", "timeout-remaining", "sigkill-syncnet", "cancel-syncnet", "cancel-waverep",
             *ABCD_SCENARIOS)
# 시나리오별 환경 변수(측정용). 나머지는 제품 기본값 그대로다.
SCENARIO_ENV = {
    "timeout-length": {"TRINITY_SYNCNET_TIMEOUT_BASE_SECONDS": "30", "TRINITY_SYNCNET_TIMEOUT_PER_ELIGIBLE_SECOND": "0"},
    "timeout-remaining": {"TRINITY_JOB_TIMEOUT_BASE_SECONDS": "150", "TRINITY_JOB_TIMEOUT_PER_ELIGIBLE_SECOND": "0"},
    "sigkill-syncnet": {},
    "sigkill-gate": {}, "sigkill-waverep": {}, "sigkill-motionphys": {},
    "cancel-motionphys": {"TRINITY_HEARTBEAT_INTERVAL_SECONDS": "2"},
    "cancel-syncnet": {},
    "cancel-waverep": {"TRINITY_HEARTBEAT_INTERVAL_SECONDS": "2"},
}
STAGE_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3}) trinity\.worker job [0-9a-f-]{36} stage (\w+)$")
# 모델 자식 프로세스를 알아보는 스크립트·모듈 이름(명령줄의 이름만 기록한다)
CHILD_MARKERS = {"syncnet": "infer_segments.py", "waverep": "infer_frames.py", "motionphys": "infer_axis.py",
                 "gate": "server.gate.process"}


# ---------------------------------------------------------------- 프로세스

def ps_rows() -> list[dict]:
    text = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,command="], capture_output=True, text=True, check=True).stdout
    rows = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5:
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "pgid": int(parts[2]), "stat": parts[3],
                         "command": parts[4]})
    return rows


def short_name(command: str) -> str:
    """실행 파일 이름과 스크립트·모듈 이름만(경로·인자 값은 버린다)."""
    toks = command.split()
    names = [Path(toks[0]).name] if toks else []
    for i, tok in enumerate(toks[1:], 1):
        if tok.endswith(".py"):
            names.append(Path(tok).name)
            break
        if tok == "-m" and i + 1 < len(toks):
            names.append(toks[i + 1])
            break
    return " ".join(names)


def job_processes(rows: list[dict], job_dir: str, exclude: set[int]) -> list[dict]:
    """명령줄에 작업 폴더가 들어간 프로세스와, 그 프로세스 그룹에 속한 모든 프로세스(FFmpeg 등 후손 포함)."""
    hits = [r for r in rows if job_dir in r["command"] and r["pid"] not in exclude]
    groups = {r["pgid"] for r in hits}
    found = {r["pid"]: r for r in hits}
    for r in rows:
        if r["pgid"] in groups and r["pid"] not in exclude:
            found.setdefault(r["pid"], r)
    return [{"pid": r["pid"], "pgid": r["pgid"], "name": short_name(r["command"])} for r in found.values()]


def alive(pid: int) -> bool:
    return any(row["pid"] == pid and not row["stat"].startswith("Z") for row in ps_rows())


def wait_dead(pids: list[int], limit: float) -> tuple[float | None, list[int]]:
    t = time.monotonic()
    while True:
        left = [p for p in pids if alive(p)]
        if not left:
            return round(time.monotonic() - t, 3), []
        if time.monotonic() - t > limit:
            return None, left
        time.sleep(0.05)


def gpu_evidence(pid: int) -> dict:
    """1초 스택 표본에서 Metal/MPS 프레임 수만 센다(스택 원문은 남기지 않는다)."""
    try:
        text = subprocess.run(["sample", str(pid), "1", "-mayDie", "-file", "/dev/stdout"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return {"sampled": False}
    text = text.partition("Binary Images:")[0]
    return {"sampled": bool(text), "metal_frames": len(re.findall(r"\bMTL|Metal|MPSGraph|\bMPS[A-Z]|AGX", text)),
            "lines": len(text.splitlines())}


def device_state() -> dict:
    run = lambda *a: subprocess.run(list(a), capture_output=True, text=True).stdout.strip()
    return {"unix": round(time.time(), 1), "pmset_batt": run("pmset", "-g", "batt"), "pmset_therm": run("pmset", "-g", "therm"),
            "loadavg": [round(x, 2) for x in os.getloadavg()]}


# ---------------------------------------------------------------- 서버·Worker

class Harness:
    def __init__(self, scenario: str) -> None:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix=f"{scenario}-", dir=RUNTIME)).resolve()
        self.jobs = self.work / "jobs"
        self.db = self.work / "queue.sqlite3"
        (self.work / "registry.json").write_text(json.dumps({"authorized_media": [{
            "youtube_video_id": TEST_ID, "provenance": "registered_authorized_source",
            "local_path": "research/samples/A.MOV", "note": "본인 촬영 샘플(검증용 임시 레지스트리)"}]}))
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRINITY_")}
        env.update(TRINITY_DB_PATH=str(self.db), TRINITY_RUNTIME_DIR=str(self.jobs),
                   TRINITY_AUTHORIZED_MEDIA=str(self.work / "registry.json"),
                   TRINITY_AUTHORIZED_MEDIA_ROOT=str(ROOT / "data"), PYTHONUNBUFFERED="1", **SCENARIO_ENV[scenario])
        self.env = env
        self.token = uuid.uuid4().hex
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}/api/v1"
        self.server_log = (self.work / "server.log").open("w")
        self.server = subprocess.Popen([sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1",
                                        "--port", str(self.port), "--no-access-log"], cwd=ROOT, env=env,
                                       stdout=self.server_log, stderr=subprocess.STDOUT)
        self.workers: list[subprocess.Popen] = []
        self.worker_logs: list[Path] = []
        deadline = time.monotonic() + 20
        while True:
            try:
                if self.call("/health")[0] == 200:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            if time.monotonic() > deadline or self.server.poll() is not None:
                raise RuntimeError("API 서버 시작 실패")
            time.sleep(0.05)

    def call(self, path: str, method: str = "GET", body=None, etag: str | None = None):
        headers = {"Content-Type": "application/json", "X-Client-Token": self.token}
        if etag is not None:
            headers["If-Match"] = etag
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None), response.headers

    def start_worker(self, drain: bool) -> subprocess.Popen:
        log = self.work / f"worker{len(self.workers) + 1}.log"
        cmd = [sys.executable, "-m", "server.jobs.worker"] + (["--drain"] if drain else [])
        with log.open("w") as f:
            proc = subprocess.Popen(cmd, cwd=ROOT, env=self.env, stdout=f, stderr=subprocess.STDOUT)
        self.workers.append(proc)
        self.worker_logs.append(log)
        return proc

    def db_row(self, aid: str) -> dict:
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT job_status, stage, completed_stages, attempts, failure_reason, lease_owner,"
                               " lease_expires_at, cancel_requested, started_at, finished_at FROM jobs WHERE analysis_id = ?",
                               (aid,)).fetchone()
        return dict(row) if row else {}

    def stage_times(self) -> list[list]:
        """Worker 로그의 단계 진입 시각(밀리초). 여러 Worker면 순서대로 잇는다."""
        out = []
        for i, log in enumerate(self.worker_logs, 1):
            for line in log.read_text(errors="replace").splitlines():
                m = STAGE_LINE.match(line)
                if m:
                    t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) + int(m.group(2)) / 1000
                    out.append([i, m.group(3), round(t, 3)])
        return out

    def log_lines(self) -> list[str]:
        """Worker 로그에서 상태 줄만(시각 제외). 경로·URL은 Worker 로그에 원래 없다."""
        keep = []
        for i, log in enumerate(self.worker_logs, 1):
            for line in log.read_text(errors="replace").splitlines():
                body = line.split(" ", 2)[-1]
                if "trinity." in body and "stage" not in body:
                    keep.append(f"w{i}: {body[:200]}")
        return keep[:60]

    def close(self) -> None:
        for proc in [*self.workers, self.server]:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        self.server_log.close()
        shutil.rmtree(self.work)


def stage_durations(times: list[list]) -> dict:
    out = {}
    for (w, name, t0), (w2, _, t1) in zip(times, times[1:]):
        if w == w2:
            out[f"w{w}.{name}"] = round(t1 - t0, 3)
    return out


def wait_for(predicate, limit: float, every: float = 0.25):
    t = time.monotonic()
    while time.monotonic() - t < limit:
        value = predicate()
        if value:
            return value
        time.sleep(every)
    return None


def summarize_result(h: Harness, aid: str) -> dict:
    code, result, _ = h.call(f"/analyses/{aid}/result")
    if code != 200 or not isinstance(result, dict):
        return {"http": code}
    axes = result.get("axes") or {}
    return {"http": code, "job_status": result.get("job_status"), "analysis_status": result.get("analysis_status"),
            "verdict_status": result.get("verdict_status"), "overall_score": result["overall_score"],
            "verdict_label": result["verdict_label"], "abstention_reason": result.get("abstention_reason"),
            "reason_code": result.get("reason_code"),
            "axes": {k: {f: v.get(f) for f in ("status", "reason_code", "raw_score", "lse_c", "lse_d", "included_in_fusion") if f in v}
                     for k, v in axes.items()},
            "eligible_duration_sec": (result.get("coverage") or {}).get("eligible_duration_sec"),
            "analyzed_duration_sec": (result.get("coverage") or {}).get("analyzed_duration_sec"),
            "explanation_templates": [e.get("template_id") for e in result.get("explanations") or []]}


def child_seen(h: Harness, aid: str, marker: str, workers: set[int]) -> list[dict] | None:
    procs = job_processes(ps_rows(), str(h.jobs / aid), workers)
    return procs if any(marker in p["name"] for p in procs) else None


# ---------------------------------------------------------------- 시나리오

def run_timeout(h: Harness, aid: str, scenario: str) -> dict:
    worker = h.start_worker(drain=True)
    seen: dict[int, dict] = {}
    t = time.monotonic()
    while worker.poll() is None and time.monotonic() - t < 1200:
        for p in job_processes(ps_rows(), str(h.jobs / aid), {worker.pid, h.server.pid}):
            seen.setdefault(p["pid"], p)
        time.sleep(1.0)
    worker.wait(timeout=60)
    left = [p["pid"] for p in seen.values() if alive(p["pid"])]
    return {"worker_exit": worker.returncode, "processes_seen": sorted({p["name"] for p in seen.values()}),
            "processes_seen_count": len(seen), "processes_left": left}


def run_cancel(h: Harness, aid: str, scenario: str) -> dict:
    stage = scenario.removeprefix("cancel-")
    marker = CHILD_MARKERS[stage]
    settle = 20 if stage == "syncnet" else 4
    worker = h.start_worker(drain=True)
    procs = wait_for(lambda: child_seen(h, aid, marker, {worker.pid, h.server.pid}), 900, 0.2)
    if procs is None:
        return {"error": f"{stage} 자식을 보지 못함", "db": h.db_row(aid)}
    time.sleep(settle)
    procs = job_processes(ps_rows(), str(h.jobs / aid), {worker.pid, h.server.pid})
    model = next((p for p in procs if marker in p["name"]), None)
    gpu = gpu_evidence(model["pid"]) if model and stage in ("syncnet", "waverep") else {"sampled": False}
    procs = child_seen(h, aid, marker, {h.server.pid, h.workers[-1].pid})
    before = h.db_row(aid)
    if not procs or before.get("stage") != ("preprocessing" if stage == "gate" else stage):
        raise RuntimeError(f"{stage} 실행 확인 실패")
    _, job, headers = h.call(f"/analyses/{aid}")
    t = time.monotonic()
    code, pending, _ = h.call(f"/analyses/{aid}", "DELETE", etag=headers["ETag"])
    done = wait_for(lambda: h.db_row(aid).get("job_status") == "cancelled", 120, 0.05)
    cancel_sec = round(time.monotonic() - t, 3) if done else None
    dead_sec, left = wait_dead([p["pid"] for p in procs], 30)
    worker.wait(timeout=60)
    after = h.db_row(aid)
    return {"stage_at_cancel": before.get("stage"), "completed_before_cancel": json.loads(before.get("completed_stages") or "[]"),
            "delete_http": code, "delete_job_status": (pending or {}).get("job_status"),
            "cancelled_after_sec": cancel_sec, "job_status": after.get("job_status"),
            "completed_stages": json.loads(after.get("completed_stages") or "[]"),
            "processes_at_cancel": [{"pid": p["pid"], "pgid": p["pgid"], "name": p["name"]} for p in procs],
            "all_dead_after_cancelled_sec": dead_sec, "processes_left": left, "gpu_evidence": gpu,
            "job_dir_exists": (h.jobs / aid).exists(), "worker_exit": worker.returncode}


def run_sigkill(h: Harness, aid: str, scenario: str) -> dict:
    stage = scenario.removeprefix("sigkill-")
    marker = CHILD_MARKERS[stage]
    w1 = h.start_worker(drain=False)
    procs = wait_for(lambda: child_seen(h, aid, marker, {w1.pid, h.server.pid}), 900, 0.2)
    if procs is None:
        return {"error": f"{stage} 자식을 보지 못함", "db": h.db_row(aid)}
    time.sleep({"syncnet": 20, "gate": 3}.get(stage, 5))
    procs = job_processes(ps_rows(), str(h.jobs / aid), {w1.pid, h.server.pid})
    model = next((p for p in procs if marker in p["name"]), None)
    gpu = gpu_evidence(model["pid"]) if model and stage in ("syncnet", "waverep") else {"sampled": False}
    procs = child_seen(h, aid, marker, {h.server.pid, h.workers[-1].pid})
    before = h.db_row(aid)
    if not procs or before.get("stage") != ("preprocessing" if stage == "gate" else stage):
        raise RuntimeError(f"{stage} 실행 확인 실패")
    lease_left = None if before.get("lease_expires_at") is None else round(before["lease_expires_at"] - time.time(), 1)
    t_kill = time.monotonic()
    os.kill(w1.pid, signal.SIGKILL)
    w1.wait(timeout=10)
    dead_sec, left = wait_dead([p["pid"] for p in procs], 60)
    right_after = h.db_row(aid)
    dir_after_kill = (h.jobs / aid).exists()
    if left or any(r["pgid"] in {p["pgid"] for p in procs} for r in ps_rows()):
        raise RuntimeError("이전 작업의 프로세스 그룹이 남음")
    sentinel = h.jobs / aid / ".old-attempt"
    sentinel.touch(exist_ok=False)
    w2 = h.start_worker(drain=False)
    t_w2 = time.monotonic()
    requeued = wait_for(lambda: (h.db_row(aid).get("attempts") or 0) >= 2, 300, 0.1)
    reclaim_row = h.db_row(aid)
    old_files_removed = not sentinel.exists()
    reclaim_sec = round(time.monotonic() - t_w2, 3) if requeued else None
    seen2: dict[int, dict] = {}

    def terminal():
        for p in job_processes(ps_rows(), str(h.jobs / aid), {w2.pid, h.server.pid}):
            seen2.setdefault(p["pid"], p)
        return h.db_row(aid).get("job_status") in ("finished", "failed", "cancelled")

    wait_for(terminal, 1500, 1.0)
    final = h.db_row(aid)
    w2.send_signal(signal.SIGTERM)
    try:
        w2.wait(timeout=30)
    except subprocess.TimeoutExpired:
        w2.kill()
        w2.wait(timeout=5)
    left2 = [p["pid"] for p in seen2.values() if alive(p["pid"])]
    return {"stage_at_kill": before.get("stage"), "attempts_at_kill": before.get("attempts"),
            "old_files_removed_on_reclaim": old_files_removed,
            "reclaim_observed_after_lease_sec": round(reclaim_row["started_at"] - right_after["lease_expires_at"], 3) if requeued else None,
            "lease_left_at_kill_sec": lease_left,
            "processes_at_kill": [{"pid": p["pid"], "pgid": p["pgid"], "name": p["name"]} for p in procs],
            "gpu_evidence": gpu, "w1_exit": w1.returncode, "children_dead_after_kill_sec": dead_sec, "children_left": left,
            "db_right_after_kill": {k: right_after.get(k) for k in ("job_status", "stage", "attempts", "lease_owner")},
            "job_dir_exists_after_kill": dir_after_kill, "w2_reclaimed_after_sec": reclaim_sec,
            "final_db": {k: final.get(k) for k in ("job_status", "attempts", "failure_reason", "completed_stages")},
            "attempt2_processes_seen": sorted({p["name"] for p in seen2.values()}), "attempt2_processes_left": left2,
            "job_dir_exists_at_end": (h.jobs / aid).exists(), "w2_exit_after_sigterm": w2.returncode,
            "kill_to_terminal_sec": round(time.monotonic() - t_kill, 1)}


RUNNERS = {"timeout-length": run_timeout, "timeout-remaining": run_timeout, "sigkill-syncnet": run_sigkill,
           "sigkill-gate": run_sigkill, "sigkill-waverep": run_sigkill, "sigkill-motionphys": run_sigkill,
           "cancel-motionphys": run_cancel, "cancel-syncnet": run_cancel, "cancel-waverep": run_cancel}


def run(scenario: str) -> dict:
    before = device_state()
    h = Harness(scenario)
    try:
        code, created, _ = h.call("/analyses", "POST", {"url": f"https://youtu.be/{TEST_ID}"})
        if code != 202:
            return {"scenario": scenario, "error": f"POST {code}"}
        aid = created["analysis_id"]
        t = time.monotonic()
        body = RUNNERS[scenario](h, aid, scenario)
        wall = time.monotonic() - t
        times = h.stage_times()
        row = h.db_row(aid)
        time.sleep(1)
        remaining = job_processes(ps_rows(), str(h.jobs / aid), {h.server.pid, *(w.pid for w in h.workers)})
        result = summarize_result(h, aid) if row.get("job_status") in {"finished", "cancelled"} else None
        return {"scenario": scenario, "attempts": row.get("attempts"), "remaining_processes": remaining, "env": SCENARIO_ENV[scenario], "analysis_id": aid, "wall_sec": round(wall, 1),
                "db_job_sec": None if not row.get("finished_at") or not row.get("started_at")
                else round(row["finished_at"] - row["started_at"], 3),
                "stage_sec": stage_durations(times), "stage_entries": times, "worker_log": h.log_lines(),
                "result": result, "job_dir_exists_after": (h.jobs / aid).exists(),
                "runtime_entries_after": sorted(p.name for p in h.jobs.iterdir()) if h.jobs.is_dir() else [],
                "device_before": before, "device_after": device_state(), **body}
    finally:
        h.close()


def lifecycle_verified(record: dict) -> bool:
    """허가 영상 A에서 기대하는 A~D 완료 조건을 결과 기록과 대조한다."""
    scenario = record["scenario"]
    if scenario not in ABCD_SCENARIOS:
        return False
    action, stage = scenario.split("-", 1)
    observed = {p["name"].split()[-1] for p in record.get(f"processes_at_{'cancel' if action == 'cancel' else 'kill'}", [])}
    if not {"server.jobs.supervisor", CHILD_MARKERS[stage]} <= observed:
        return False
    expected_stage = "preprocessing" if stage == "gate" else stage
    if (record.get("error") or record.get("remaining_processes") != []
            or record.get("job_dir_exists_after") is not False
            or set(record["runtime_entries_after"]) - {".worker.lock"}):
        return False
    result = record.get("result") or {}
    if scenario == "cancel-motionphys":
        return (record.get("stage_at_cancel") == stage and record["delete_http"] == 202
                and record.get("cancelled_after_sec") is not None
                and record["attempts"] == 1 and record["worker_exit"] == 0
                and record["processes_left"] == [] and record["job_status"] == "cancelled"
                and result.get("job_status") == "cancelled" and not result["axes"]
                and result["overall_score"] is None)
    axes = result.get("axes") or {}
    return (record.get("stage_at_kill") == expected_stage and record["w1_exit"] == -signal.SIGKILL
            and record.get("w2_exit_after_sigterm") == 0
            and record["attempts_at_kill"] == 1 and record["attempts"] == 2
            and record["old_files_removed_on_reclaim"] and record["reclaim_observed_after_lease_sec"] > 0
            and record["children_left"] == [] and record["attempt2_processes_left"] == []
            and result.get("job_status") == "finished" and result["analysis_status"] == "completed"
            and result["verdict_status"] == "abstained" and result["overall_score"] is None
            and result["verdict_label"] is None and result["abstention_reason"] == "no_valid_fusion_model"
            and set(axes) == {"signal", "physics", "alignment"}
            and all(axis["status"] == "completed" for axis in axes.values())
            and all(axes[key]["raw_score"] is None for key in ("signal", "physics")))


def report() -> str:
    lines = []
    for scenario in SCENARIOS:
        path = OUT / f"{scenario}.json"
        if not path.is_file():
            lines.append(f"- {scenario}: 미실행")
            continue
        r = json.loads(path.read_text(encoding="utf-8"))
        res = r.get("result") or {}
        axes = ", ".join(f"{k} {v.get('status')}/{v.get('reason_code')}" for k, v in (res.get("axes") or {}).items())
        lines.append(f"- {scenario}: job {res.get('job_status') or r.get('job_status') or (r.get('final_db') or {}).get('job_status')} "
                     f"/ {res.get('analysis_status')} / {res.get('verdict_status')}; {axes}; 단계 {r.get('stage_sec')}; "
                     f"작업 {r.get('db_job_sec')}초; 남은 프로세스 {r.get('processes_left') or r.get('children_left')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", choices=SCENARIOS, action="append")
    p.add_argument("--force", action="store_true")
    p.add_argument("--new-run", action="store_true", help="새 결과 디렉터리에 독립 실행 기록")
    p.add_argument("--report", action="store_true")
    opt = p.parse_args(argv)
    if opt.report:
        print(report())
        return 0
    if not (ROOT / "data/research/samples/A.MOV").is_file():
        print("허가 샘플 A가 없어 실행하지 않았다(미검증).")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=OUT)) if opt.new_run else OUT
    print(output.relative_to(ROOT), flush=True)
    for scenario in opt.only or SCENARIOS:
        path = output / f"{scenario}.json"
        if path.is_file() and not opt.force:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (cached.get("scenario") != scenario or cached.get("error")
                    or (scenario in ABCD_SCENARIOS and not lifecycle_verified(cached))):
                print(f"{scenario}: 저장된 결과가 완료 조건을 충족하지 않음", file=sys.stderr)
                return 1
            print(f"skip {scenario}", flush=True)
            continue
        data = run(scenario)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        if data.get("error") or (scenario in ABCD_SCENARIOS and not lifecycle_verified(data)):
            print(f"{scenario}: 완료 조건 불충족", file=sys.stderr)
            return 1
        print(f"{time.strftime('%H:%M:%S')} {scenario}: done", flush=True)
    if not opt.new_run:
        print(report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
