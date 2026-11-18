"""Worker 안 SyncNet 대 단독 실행의 시간 차이 측정 (연구용, 제품 코드·설정 기본값 변경 없음).

docs/syncnet-adapter.md "Worker 안 약 400초 대 단독 274~294초 — 측정 방법 제안"의 (a)(b)(c)를 같은 세션에서 번갈아 잰다.

    conda activate trinity
    python scripts/measure_syncnet_worker_gap.py --plan a1,b1,c1,b2,c2,a2,c3,a3,b3   # 된 것은 건너뜀
    python scripts/measure_syncnet_worker_gap.py --report                            # 표(Markdown)를 출력
    python scripts/measure_syncnet_worker_gap.py --plan a1,b1,c1,d1 --dry --cooldown 0 # 하네스 점검(SyncNet 없이)

조건
  a  Worker 전체 경로: 실제 Gate → WaveRep → MotionPhys → SyncNet (별도 Worker 프로세스, 임시 레지스트리·DB)
  b  Worker, 앞 단계 가짜: Gate는 로버스트니스 실측의 A 적합 구간을 바로 돌려주고 WaveRep·MotionPhys는 실행하지 않는다
  c  단독 실행: Worker·supervisor 없이 SyncNet 실행기만 subprocess.run으로
  d  (진단) Worker 없이 실제 Gate·WaveRep·MotionPhys 어댑터를 돌린 직후 c와 같은 단독 SyncNet
  e  (진단) 모델·미디어 없이 모든 코어에 순수 계산 부하를 `--heat-sec`초(기본 68: a·d의 앞 단계 길이) 준 직후 c와 같은 단독 SyncNet.
     앞 단계의 영향이 열(기기 온도) 때문인지, 파일 캐시·메모리·MPS 상태 같은 다른 부작용 때문인지 가른다

네 조건 모두 SyncNet 자식은 같은 실행기(`research/syncnet/profile_adapter_shim.py` → `profile_run.py`)라서
단계별 시간(S3FD, FFmpeg 등)을 같은 표로 비교한다. Worker 조건은 측정 프로세스 안에서만
`alignment.build_config`의 실행기 경로를 바꾼다(`tests/test_job_lifecycle.py` 부트스트랩과 같은 방식). 저장소 코드는 바꾸지 않는다.
SyncNet 장치는 `--device`(기본 cpu: 원래 차이가 관측된 조건). 측정용으로 작업·SyncNet 제한만 환경 변수로 1,800초로 늘린다.

실행마다 시작 전 `--cooldown`초(기본 180) 쉬고 thermalState 0·쉬는 때 CPU 탐침이 세션 최솟값의 5% 안이 될 때까지
더 쉰 뒤(최대 `--cooldown-max`), 전후 기기 상태(pmset -g batt/therm, thermalState, vm_stat, 부하, 충전기)와
실행 중 5초마다 시스템 전력(SystemLoad)·thermalState·다른 프로세스 CPU를 기록한다. 결과는 Git 밖
data/research/syncnet-worker-gap/에 둔다. 임시 레지스트리·DB·작업 폴더는 실행이 끝나면 지운다.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import platform
import re
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

OUT = REPO_ROOT / "data/research/syncnet-worker-gap"
RUNTIME = REPO_ROOT / "data/runtime/syncnet-worker-gap"
SAMPLES = REPO_ROOT / "data/research/samples"
ROBUST_GATE = REPO_ROOT / "data/research/robustness-selfvideo/results/A/original/gate.json"
VENV_PY = REPO_ROOT / "research/syncnet/.venv/bin/python"
SHIM = REPO_ROOT / "research/syncnet/profile_adapter_shim.py"
WEIGHTS = REPO_ROOT / "data/models/syncnet"
TEST_ID = "TRINITYtest"
OWNER = "measure-syncnet-worker-gap"
SCHEMA_VERSION = 1
CONDITIONS = ("a", "b", "c", "d", "e")
HEAT_LOOP = "import sys, time\nend = time.monotonic() + float(sys.argv[1])\nx = 1\nwhile time.monotonic() < end:\n    x = (x * x + 1) % 1000003\n"
THERMAL_SRC = 'import Foundation\nprint(ProcessInfo.processInfo.thermalState.rawValue)\n'


# ---------------------------------------------------------------- 기기 상태

def _cmd(args: list[str], timeout: float = 10.0) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def thermal_probe() -> Path | None:
    """ProcessInfo.thermalState(0 nominal, 1 fair, 2 serious, 3 critical)를 읽는 작은 실행 파일. 없으면 만든다."""
    binary = OUT / "bin" / "thermal_state"
    if binary.is_file():
        return binary
    if not shutil.which("swiftc"):
        return None
    binary.parent.mkdir(parents=True, exist_ok=True)
    src = binary.parent / "thermal_state.swift"
    src.write_text(THERMAL_SRC)
    _cmd(["swiftc", "-O", str(src), "-o", str(binary)], timeout=120)
    return binary if binary.is_file() else None


def thermal_state(probe: Path | None) -> int | None:
    if probe is None:
        return None
    text = _cmd([str(probe)]).strip()
    return int(text) if text.isdigit() else None


def power_telemetry() -> dict:
    """AppleSmartBattery의 전력 값(mW)과 충전기 정보. root 없이 읽힌다. 못 읽으면 빈 값."""
    text = _cmd(["ioreg", "-rn", "AppleSmartBattery"])
    out = {}
    for key in ("SystemLoad", "SystemPowerIn", "BatteryPower"):
        m = re.search(rf'"PowerTelemetryData" = {{[^}}]*"{key}"=(\d+)', text)
        value = int(m.group(1)) if m else None
        # 음수(배터리 방전)는 부호 없는 64비트로 나온다
        out[key] = value - 2 ** 64 if value is not None and value >= 2 ** 63 else value
    m = re.search(r'"AdapterDetails" = {[^}]*"Watts"=(\d+)', text)
    out["adapter_watts"] = int(m.group(1)) if m else None
    for key in ("CurrentCapacity", "IsCharging", "ExternalConnected"):
        m = re.search(rf'^\s*\|?\s*"{key}" = (\S+)', text, re.M)
        out[key] = m.group(1) if m else None
    return out


def vm_stat() -> dict:
    text = _cmd(["vm_stat"])
    keys = {"Pages free": "free", "Pages active": "active", "Pages inactive": "inactive",
            "Pages wired down": "wired", "Pages occupied by compressor": "compressor",
            "Swapins": "swapins", "Swapouts": "swapouts"}
    out = {}
    for line in text.splitlines():
        name, _, value = line.partition(":")
        if name.strip() in keys:
            out[keys[name.strip()]] = int(value.strip().rstrip("."))
    return out


def device_state(probe: Path | None) -> dict:
    load = os.getloadavg()
    return {"unix": round(time.time(), 3), "pmset_batt": _cmd(["pmset", "-g", "batt"]).strip(),
            "pmset_therm": _cmd(["pmset", "-g", "therm"]).strip(), "thermal_state": thermal_state(probe),
            "power": power_telemetry(), "vm_stat": vm_stat(), "swapusage": _cmd(["sysctl", "-n", "vm.swapusage"]).strip(),
            "loadavg": [round(x, 2) for x in load]}


def cpu_probe(repeats: int = 5) -> dict:
    """고정된 한 스레드 계산의 시간(초). 기기가 쉬는 동안 재서 세션·실행 사이의 CPU 속도 차이를 본다."""
    times = []
    for _ in range(repeats):
        t = time.perf_counter()
        s = 0
        for i in range(2_000_000):
            s += i * i
        times.append(time.perf_counter() - t)
    return {"min_sec": round(min(times), 4), "median_sec": round(statistics.median(times), 4)}


def _descendants(rows: list[tuple[int, int, float, str]], root: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for pid, ppid, _, _ in rows:
        children.setdefault(ppid, []).append(pid)
    seen, stack = set(), [root]
    while stack:
        pid = stack.pop()
        for c in children.get(pid, []):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def process_cpu() -> dict:
    """이 측정의 프로세스 트리와 그 밖의 프로세스 CPU 합(ps %CPU, 100 = 코어 하나). 이름은 실행 파일 이름만."""
    rows = []
    for line in _cmd(["ps", "-Ao", "pid=,ppid=,pcpu=,comm="]).splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            try:
                rows.append((int(parts[0]), int(parts[1]), float(parts[2]), Path(parts[3]).name))
            except ValueError:
                continue
    ours = _descendants(rows, os.getpid()) | {os.getpid()}
    mine = sum(c for pid, _, c, _ in rows if pid in ours)
    others = sorted(((c, n) for pid, _, c, n in rows if pid not in ours and c > 0), reverse=True)
    return {"ours_pcpu": round(mine, 1), "others_pcpu": round(sum(c for c, _ in others), 1),
            "top_others": [[n, c] for c, n in others[:4]]}


class Sampler(threading.Thread):
    def __init__(self, probe: Path | None, every: float = 5.0) -> None:
        super().__init__(daemon=True)
        self.probe, self.every, self.samples = probe, every, []
        self.halt = threading.Event()
        self.t0 = time.monotonic()

    def run(self) -> None:
        while not self.halt.is_set():
            p = power_telemetry()
            self.samples.append({"t": round(time.monotonic() - self.t0, 2), "system_load_mw": p["SystemLoad"],
                                 "power_in_mw": p["SystemPowerIn"], "battery_mw": p["BatteryPower"],
                                 "thermal_state": thermal_state(self.probe), **process_cpu()})
            self.halt.wait(self.every)

    def stop(self) -> list[dict]:
        self.halt.set()
        self.join(timeout=15)
        return self.samples


# ---------------------------------------------------------------- 입력

def robust_gate() -> dict:
    return json.loads(ROBUST_GATE.read_text(encoding="utf-8"))["result"]


def robust_segments() -> list[list[float]]:
    return robust_gate()["eligible_segments"]


def leftover_processes() -> list[str]:
    """측정 뒤 남은 모델 프로세스(실행 파일 이름 + 스크립트 이름만)."""
    names = ("infer_segments.py", "profile_run.py", "profile_adapter_shim.py", "infer_axis.py", "server.jobs.supervisor")
    out = []
    for line in _cmd(["ps", "-Ao", "pid=,command="]).splitlines():
        if any(n in line for n in names) and "measure_syncnet_worker_gap" not in line:
            out.append(" ".join(Path(tok).name for tok in line.split()[1:4]))
    return out


# ---------------------------------------------------------------- 조건 a·b: Worker

def worker_env(run_dir: Path, device: str, dry: bool) -> dict:
    env = dict(os.environ)
    env.update({
        "TRINITY_DB_PATH": str(run_dir / "trinity.sqlite3"),
        "TRINITY_RUNTIME_DIR": str(run_dir / "jobs"),
        "TRINITY_AUTHORIZED_MEDIA": str(run_dir / "authorized_media.json"),
        "TRINITY_AUTHORIZED_MEDIA_ROOT": str(REPO_ROOT / "data"),
        "TRINITY_SYNCNET_DEVICE": device,
        # 측정용: 느린 세션에서도 SyncNet이 끝까지 돌게 작업·SyncNet 제한만 늘린다(제품 기본값은 그대로)
        "TRINITY_JOB_TIMEOUT_SECONDS": "1800",
        "TRINITY_JOB_TIMEOUT_BASE_SECONDS": "1800",
        "TRINITY_JOB_TIMEOUT_MAX_SECONDS": "1800",
        "TRINITY_SYNCNET_TIMEOUT_BASE_SECONDS": "1700",
        "SYNCNET_PROFILE_COPY_TO": str(run_dir / "syncnet_profile.json"),
        "GAP_TRACE_PATH": str(run_dir / "worker_trace.json"),
        "PYTHONUNBUFFERED": "1",
    })
    if dry:
        env["SYNCNET_GAP_DRY"] = "1"
    return env


def worker_bootstrap(cond: str) -> int:
    """측정 프로세스 안에서만 Worker를 감싼다(단계 시각·축 시간·SyncNet 어댑터 반환값 기록). 저장소 코드는 그대로다."""
    from server.axes import alignment, physics, signal as signal_axis
    from server.axes.alignment import syncnet as sn
    from server.gate.types import GateResult, MediaInfo, Segment
    from server.jobs import queue as queue_mod, worker

    trace: dict = {"cond": cond, "pid": os.getpid(), "stages": [], "axes": {}, "syncnet_adapter": None}
    path = Path(os.environ["GAP_TRACE_PATH"])

    def save() -> None:
        path.write_text(json.dumps(trace, indent=1, allow_nan=False))

    advance = queue_mod.JobQueue.advance_stage

    def advance_traced(self, analysis_id, worker_id, stage, completed, lease_seconds):
        trace["stages"].append([stage, round(time.monotonic(), 4), round(time.time(), 4)])
        return advance(self, analysis_id, worker_id, stage, completed, lease_seconds)

    queue_mod.JobQueue.advance_stage = advance_traced
    build = alignment.build_config
    alignment.build_config = lambda ctx: dataclasses.replace(build(ctx), script=SHIM)
    run_syncnet = sn.run_syncnet

    def run_syncnet_traced(video, segments, work_dir, config, **kw):
        t = time.monotonic()
        out = run_syncnet(video, segments, work_dir, config, **kw)
        trace["syncnet_adapter"] = {
            "sec": round(time.monotonic() - t, 3), "mono": [round(t, 4), round(time.monotonic(), 4)],
            "timeout_sec": round(config.timeout_sec, 1),
            "device_requested": config.device, "script": Path(config.script).name,
            "status": out.get("status"), "reason_code": out.get("reason_code"), "device_used": out.get("device_used"),
            "segments": [[row["start_sec"], row["end_sec"], row["status"], row["reason_code"],
                          [[t2["offset_frames"], round(t2["lse_c"], 4), round(t2["lse_d"], 4)] for t2 in (row["tracks"] or [])]]
                         for row in (out.get("segments") or [])],
        }
        return out

    sn.run_syncnet = run_syncnet_traced
    if cond == "b":
        g = robust_gate()
        fake = GateResult(
            media=MediaInfo(**g["media"]), reason_code=None,
            eligible_segments=tuple(Segment(s, e) for s, e in g["eligible_segments"]),
            excluded_segments=tuple(Segment(x["start_sec"], x["end_sec"], x["reason_code"]) for x in g["excluded_segments"]))
        worker.run_gate_process = lambda *a, **k: fake
        signal_axis.run = lambda ctx: {"status": "error", "reason_code": "model_unavailable", "raw_score": None}
        physics.run = lambda ctx: {"status": "error", "reason_code": "model_unavailable", "raw_score": None}
    for module, name in ((signal_axis, "signal"), (physics, "physics"), (alignment, "alignment")):
        def timed(ctx, _fn=module.run, _name=name):
            t = time.monotonic()
            try:
                return _fn(ctx)
            finally:
                trace["axes"][_name] = {"sec": round(time.monotonic() - t, 3),
                                        "timeout_sec": None if ctx.timeout_seconds is None else round(ctx.timeout_seconds, 1)}
        module.run = timed
    try:
        return worker.main(["--drain"])
    finally:
        save()


def run_worker(cond: str, device: str, dry: bool, tag: str) -> dict:
    from server.jobs.queue import JobQueue
    import sqlite3

    RUNTIME.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix=f"{tag}-", dir=RUNTIME))
    try:
        (run_dir / "jobs").mkdir()
        (run_dir / "authorized_media.json").write_text(json.dumps({"authorized_media": [{
            "youtube_video_id": TEST_ID, "provenance": "registered_authorized_source",
            "local_path": "research/samples/A.MOV", "note": "본인 촬영 샘플(측정용 임시 레지스트리)"}]}))
        queue = JobQueue(run_dir / "trinity.sqlite3")
        queue.init_schema()
        aid = queue.enqueue(TEST_ID, OWNER, 3)
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker-bootstrap", cond]
        t = time.monotonic()
        with open(run_dir / "worker.log", "wb") as logf:
            code = subprocess.run(cmd, cwd=REPO_ROOT, env=worker_env(run_dir, device, dry), stdin=subprocess.DEVNULL,
                                  stdout=logf, stderr=subprocess.STDOUT).returncode
        wall = time.monotonic() - t
        job = queue.get(aid, OWNER)
        with sqlite3.connect(run_dir / "trinity.sqlite3") as conn:
            started, finished, attempts = conn.execute(
                "SELECT started_at, finished_at, attempts FROM jobs WHERE analysis_id = ?", (aid,)).fetchone()
        trace = json.loads((run_dir / "worker_trace.json").read_text()) if (run_dir / "worker_trace.json").is_file() else None
        prof_path = run_dir / "syncnet_profile.json"
        profile = json.loads(prof_path.read_text()) if prof_path.is_file() else None
        result = job.result or {}
        log_lines = [ln.split(" ", 2)[-1] for ln in (run_dir / "worker.log").read_text(errors="replace").splitlines()
                     if "stage" in ln or "timeout set" in ln or "failed" in ln or "Traceback" in ln][:40]
        jobs_left = sorted(p.name for p in (run_dir / "jobs").iterdir()) if (run_dir / "jobs").is_dir() else []
        stages = trace["stages"] if trace else []
        stage_sec = {}
        for (name, t0, _), (_, t1, _) in zip(stages, stages[1:]):
            stage_sec[name] = round(t1 - t0, 3)
        return {
            "worker_exit": code, "worker_wall_sec": round(wall, 3), "job_status": job.job_status if job else None,
            "failure_reason": job.failure_reason if job else None, "attempts": attempts,
            "db_job_sec": None if started is None or finished is None else round(finished - started, 3),
            "analysis_status": result.get("analysis_status"), "verdict_status": result.get("verdict_status"),
            "overall_score": result.get("overall_score"),
            "axes": {k: {"status": v.get("status"), "reason_code": v.get("reason_code")} for k, v in (result.get("axes") or {}).items()},
            "eligible_duration_sec": (result.get("coverage") or {}).get("eligible_duration_sec"),
            "stage_sec": stage_sec, "trace": trace, "profile": profile, "log": log_lines,
            "job_dirs_left": [n for n in jobs_left if not n.startswith(".")],
        }
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


# ---------------------------------------------------------------- 조건 c·d: Worker 밖

def run_shim(job: Path, media: Path, segments: list[list[float]], device: str, dry: bool) -> dict:
    folder = Path(tempfile.mkdtemp(prefix="syncnet-", dir=job))
    request, output = folder / "request.json", folder / "result.json"
    request.write_text(json.dumps({"video": str(media), "segments": segments, "weights_dir": str(WEIGHTS.resolve()),
                                   "device": device}))
    copy_to = job / "syncnet_profile.json"
    env = dict(os.environ, SYNCNET_PROFILE_COPY_TO=str(copy_to))
    if dry:
        env["SYNCNET_GAP_DRY"] = "1"
    t = time.monotonic()
    code = subprocess.run([str(VENV_PY), str(SHIM), "--request", str(request), "--output", str(output)],
                          cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode
    wall = time.monotonic() - t
    raw = json.loads(output.read_text()) if output.is_file() else None
    profile = json.loads(copy_to.read_text()) if copy_to.is_file() else None
    segs = [[r["start_sec"], r["end_sec"], r["status"], r["reason_code"],
             [[t2["offset_frames"], round(t2["lse_c"], 4), round(t2["lse_d"], 4)] for t2 in (r.get("tracks") or [])]]
            for r in (raw or {}).get("segments", [])]
    return {"exit": code, "sec": round(wall, 3), "mono": [round(t, 4), round(t + wall, 4)],
            "device_used": (raw or {}).get("device_used"), "segments": segs, "profile": profile}


def heat(seconds: float) -> dict:
    """모든 논리 코어에 순수 계산 프로세스를 하나씩 띄워 seconds초 동안 돌린다(모델·미디어·GPU 없음)."""
    n = os.cpu_count() or 8
    t = time.monotonic()
    procs = [subprocess.Popen([sys.executable, "-c", HEAT_LOOP, str(seconds)], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(n)]
    for proc in procs:
        proc.wait()
    return {"heat_sec": round(time.monotonic() - t, 3), "heat_processes": n}


def run_outside(cond: str, device: str, dry: bool, tag: str, heat_sec: float = 68.0) -> dict:
    (OUT / "work").mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix=f"{tag}-", dir=OUT / "work")).resolve()
    try:
        src = SAMPLES / "A.MOV"
        media = job / "media.mov"
        front: dict = {}
        if cond in ("c", "e"):
            if cond == "e":
                front.update(heat(0.0 if dry else heat_sec))
            try:
                os.link(src, media)
            except OSError:
                shutil.copyfile(src, media)
            segments = robust_segments()
        else:
            # Worker와 같은 순서·같은 어댑터로 앞 단계를 실제로 돌린다(큐·heartbeat·작업 제한 없음)
            from server.axes import AxisContext, physics, signal as signal_axis
            from server.config import Settings
            from server.gate.runner import run_gate_process

            shutil.copyfile(src, media)
            settings = Settings(syncnet_device=device)
            t = time.monotonic()
            gate = run_gate_process(media, job, settings=settings, timeout_seconds=600.0, on_tick=lambda: True)
            front["gate_sec"] = round(time.monotonic() - t, 3)
            front["gate_reason"] = gate.reason_code
            segments = [[s.start_sec, s.end_sec] for s in gate.eligible_segments]
            ctx = AxisContext(job_dir=job, settings=settings, media_path=media,
                              segments=tuple(tuple(s) for s in segments), heartbeat=lambda: True)
            for name, module in (("signal", signal_axis), ("physics", physics)):
                t = time.monotonic()
                out = module.run(ctx)
                front[f"{name}_sec"] = round(time.monotonic() - t, 3)
                front[f"{name}_status"] = out.get("status")
        sn = run_shim(job, media, segments, device, dry)
        return {"segments_requested": segments, "front": front, "syncnet": sn}
    finally:
        shutil.rmtree(job, ignore_errors=True)


# ---------------------------------------------------------------- 실행 계획

def run_path(cond: str, rep: int, device: str, dry: bool) -> Path:
    return OUT / ("runs-dry" if dry else "runs") / f"{cond}__{rep}__{device}.json"


def rest(cooldown: float, cooldown_max: float, probe: Path | None, baseline: list[float]) -> dict:
    """최소 cooldown초 쉬고, thermalState가 0이고 쉬는 때 CPU 탐침이 세션 최솟값의 5% 안에 들 때까지 더 쉰다(최대 cooldown_max).

    팬 없는 기기에서 앞 실행의 열이 다음 실행의 시작 상태를 바꾸지 않게 실행마다 시작 상태를 맞춘다.
    """
    t = time.monotonic()
    time.sleep(cooldown)
    trail = []
    while True:
        state, speed = thermal_state(probe), cpu_probe(3)["min_sec"]
        if not baseline or speed < baseline[0]:
            baseline[:] = [speed]
        trail.append([round(time.monotonic() - t, 1), state, speed])
        ok = state in (0, None) and speed <= baseline[0] * 1.05
        if ok or time.monotonic() - t >= cooldown_max:
            return {"rested_sec": round(time.monotonic() - t, 1), "reached": ok, "trail": trail,
                    "probe_baseline_sec": baseline[0]}
        time.sleep(30)


def measure(cond: str, rep: int, device: str, cooldown: float, dry: bool, probe: Path | None,
            cooldown_max: float = 900.0, baseline: list[float] | None = None, heat_sec: float = 68.0) -> Path:
    path = run_path(cond, rep, device, dry)
    tag = f"{cond}{rep}"
    rest_from = time.time()
    rested = rest(cooldown, max(cooldown, cooldown_max), probe, baseline if baseline is not None else [])
    before = device_state(probe)
    probe_before = cpu_probe()
    sampler = Sampler(probe)
    sampler.start()
    t = time.monotonic()
    try:
        body = run_worker(cond, device, dry, tag) if cond in ("a", "b") else run_outside(cond, device, dry, tag, heat_sec)
        error = None
    except Exception as e:  # 측정 실패도 기록으로 남긴다
        body, error = {}, f"{type(e).__name__}: {e}"
    wall = time.monotonic() - t
    samples = sampler.stop()
    after = device_state(probe)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    data = {"schema_version": SCHEMA_VERSION, "cond": cond, "rep": rep, "device": device, "dry": dry,
            "cooldown_sec": cooldown, "rest": rested, "rest_started_unix": round(rest_from, 3), "wall_sec": round(wall, 3),
            "error": error, "before": before, "after": after, "cpu_probe_before": probe_before,
            "samples": samples, "samples_t0_mono": round(sampler.t0, 4), "children_max_rss_bytes": usage.ru_maxrss, "leftover_processes": leftover_processes(),
            "machine": {"platform": platform.platform(), "machine": platform.machine()}, **body}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def parse_plan(text: str) -> list[tuple[str, int]]:
    plan = []
    for item in (p.strip() for p in text.split(",")):
        if not item:
            continue
        m = re.fullmatch(r"([abcde])(\d+)", item)
        if not m:
            raise ValueError(f"계획 항목 형식 오류: {item!r} (예: a1,b1,c1)")
        plan.append((m.group(1), int(m.group(2))))
    return plan


# ---------------------------------------------------------------- 표

def syncnet_view(run: dict) -> dict:
    """조건과 무관하게 같은 기준의 SyncNet 수치를 꺼낸다."""
    if run["cond"] in ("a", "b"):
        sec = ((run.get("trace") or {}).get("syncnet_adapter") or {}).get("sec")
        profile = run.get("profile")
        segs = ((run.get("trace") or {}).get("syncnet_adapter") or {}).get("segments")
        device = ((run.get("trace") or {}).get("syncnet_adapter") or {}).get("device_used")
    else:
        sn = run.get("syncnet") or {}
        sec, profile, segs, device = sn.get("sec"), sn.get("profile"), sn.get("segments"), sn.get("device_used")
    stage = (profile or {}).get("stage_sec", {})
    evals = sum(v for k, v in stage.items() if k.startswith("eval_"))
    return {"sec": sec, "internal": (profile or {}).get("internal_sec"), "s3fd": stage.get("s3fd_detect"),
            "cut": stage.get("cut_ffv1"), "avi": stage.get("avi_convert"), "frames": stage.get("frames_extract"),
            "eval": round(evals, 2) if profile else None, "device": device, "segments": segs,
            "seg_sec": [s.get("inference_sec") for s in (profile or {}).get("segments", [])]}


def syncnet_samples(run: dict) -> list[dict]:
    """SyncNet이 도는 동안의 표본. 표본 시각(측정 시작 기준)과 SyncNet 시각은 같은 기계의 단조 시계다."""
    if run["cond"] in ("a", "b"):
        mono = ((run.get("trace") or {}).get("syncnet_adapter") or {}).get("mono")
    else:
        mono = (run.get("syncnet") or {}).get("mono")
    if not mono:
        return []
    lo, hi = mono[0] - run["samples_t0_mono"], mono[1] - run["samples_t0_mono"]
    return [s for s in run.get("samples", []) if lo <= s["t"] <= hi]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 1) if xs else None


def report(device: str, dry: bool) -> str:
    runs = []
    for path in sorted((OUT / ("runs-dry" if dry else "runs")).glob(f"*__{device}.json")):
        runs.append(json.loads(path.read_text(encoding="utf-8")))
    runs.sort(key=lambda r: r["rest_started_unix"])
    lines = ["| 순서 | 조건 | 시작(현지) | SyncNet 바깥 시간 | 프로세스 안 | S3FD | 구간 절단 | AVI 변환 | 프레임 추출 | 평가 | 앞 단계 | 작업 전체 | 쉬는 때 CPU 탐침 | SyncNet 중 시스템 전력 평균(W) | thermalState 최대 | 다른 프로세스 CPU 평균(%) | 배터리 | 결과 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    by_cond: dict[str, list[dict]] = {}
    for i, run in enumerate(runs, 1):
        v = syncnet_view(run)
        if run["cond"] in ("a", "b"):
            stages = ((run.get("trace") or {}).get("stages")) or []
            names = [s[0] for s in stages]
            front = None
            if "syncnet" in names and "validating" in names:
                front = stages[names.index("syncnet")][1] - stages[names.index("validating")][1]
            total = run.get("db_job_sec")
            status = f"{run.get('job_status')}/{run.get('analysis_status')}, SyncNet {((run.get('axes') or {}).get('alignment') or {}).get('status')}"
        else:
            front_d = run.get("front") or {}
            front = sum(v2 for k, v2 in front_d.items() if k.endswith("_sec")) or None
            total = run.get("wall_sec")
            status = f"exit {(run.get('syncnet') or {}).get('exit')}, " + ",".join(
                s[2][:4] for s in (v["segments"] or []))
        win = syncnet_samples(run)
        loads = [s["system_load_mw"] / 1000 for s in win if s.get("system_load_mw")]
        thermals = [s["thermal_state"] for s in win if s.get("thermal_state") is not None]
        others = [s["others_pcpu"] for s in win]
        batt = re.search(r"(\d+)%; ([^;]+);", run["before"]["pmset_batt"])
        when = time.strftime("%H:%M", time.localtime(run["before"]["unix"]))
        lines.append(
            f"| {i} | {run['cond']}{run['rep']} | {when} | {fmt(v['sec'])} | {fmt(v['internal'])} | {fmt(v['s3fd'])} | {fmt(v['cut'])} | "
            f"{fmt(v['avi'])} | {fmt(v['frames'])} | {fmt(v['eval'])} | {fmt(front)} | {fmt(total)} | {run['cpu_probe_before']['min_sec']:.3f} | "
            f"{fmt(mean(loads))} | {max(thermals) if thermals else '–'} | {fmt(mean(others))} | "
            f"{batt.group(1) + '% ' + batt.group(2) if batt else '?'} | {status} |")
        by_cond.setdefault(run["cond"], []).append({**v, "front": front, "total": total, "load": mean(loads),
                                                    "probe": run["cpu_probe_before"]["min_sec"]})
    lines += ["", "| 조건 | 회수 | SyncNet 바깥 시간 평균 (최소–최대) | 프로세스 안 평균 | S3FD 평균 | 구간 절단 평균 | SyncNet 중 전력 평균(W) |",
              "|---|---|---|---|---|---|---|"]
    for cond in CONDITIONS:
        rs = by_cond.get(cond)
        if not rs:
            continue
        secs = [r["sec"] for r in rs if r["sec"] is not None]
        lines.append(f"| {cond} | {len(rs)} | {fmt(mean(secs))} ({fmt(min(secs) if secs else None)}–{fmt(max(secs) if secs else None)}) | "
                     f"{fmt(mean([r['internal'] for r in rs]))} | {fmt(mean([r['s3fd'] for r in rs]))} | {fmt(mean([r['cut'] for r in rs]))} | "
                     f"{fmt(mean([r['load'] for r in rs]))} |")
    return "\n".join(lines) + "\n"


def fmt(v) -> str:
    return "–" if v is None else f"{v:.1f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--plan", help="쉼표로 이은 실행 목록. 예: a1,b1,c1,b2,c2,a2,c3,a3,b3")
    p.add_argument("--device", default="cpu", choices=("cpu", "mps"))
    p.add_argument("--cooldown", type=float, default=180.0, help="실행 전 최소로 쉬는 시간(초)")
    p.add_argument("--cooldown-max", type=float, default=900.0, help="열 상태·CPU 탐침이 돌아오기를 기다리는 최대 시간(초)")
    p.add_argument("--dry", action="store_true", help="SyncNet을 돌리지 않는 하네스 점검")
    p.add_argument("--heat-sec", type=float, default=68.0, help="조건 e의 순수 계산 부하 시간(초)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--worker-bootstrap", choices=("a", "b"), help=argparse.SUPPRESS)
    opt = p.parse_args(argv)
    if opt.worker_bootstrap:
        return worker_bootstrap(opt.worker_bootstrap)
    if opt.report:
        print(report(opt.device, opt.dry))
        return 0
    if not opt.plan:
        p.error("--plan 또는 --report가 필요하다")
    probe = thermal_probe()
    baseline: list[float] = []
    for cond, rep in parse_plan(opt.plan):
        path = run_path(cond, rep, opt.device, opt.dry)
        if path.is_file() and not opt.force:
            print(f"skip {path.name}", flush=True)
            continue
        t = time.monotonic()
        measure(cond, rep, opt.device, 0.0 if opt.dry else opt.cooldown, opt.dry, probe,
                0.0 if opt.dry else opt.cooldown_max, baseline, opt.heat_sec)
        run = json.loads(path.read_text(encoding="utf-8"))
        v = syncnet_view(run)
        print(f"{time.strftime('%H:%M:%S')} {cond}{rep} total {time.monotonic() - t:7.1f}s syncnet {fmt(v['sec'])}s "
              f"internal {fmt(v['internal'])}s s3fd {fmt(v['s3fd'])}s error={run.get('error')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
