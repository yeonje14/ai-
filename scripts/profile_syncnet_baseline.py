"""SyncNet 성능 기준선 측정 (개선 시도 없음). 이어서 돌릴 수 있다.

    conda activate trinity
    python scripts/profile_syncnet_baseline.py                 # 전체 계획 실행(된 것은 건너뜀)
    python scripts/profile_syncnet_baseline.py --report        # 표(Markdown)를 data/research/syncnet-perf/tables.md에 쓴다

실행 한 건 = 새 프로세스 하나(`--one`). 모드:
- standalone: 전용 venv의 research/syncnet/profile_run.py를 직접 실행한다.
- supervised: 서버와 같은 server.jobs.child_process.start_process(supervisor 경유)로 같은 명령을 실행한다.
- adapter: 서버의 실제 어댑터 run_syncnet(타이머 없음)을 호출한다. 타이머 때문에 시간이 늘지 않았는지 보는 대조용이다.
시간은 time.monotonic. 최대 메모리는 이 측정 프로세스가 기다린 후손 프로세스 중 하나의 최대 RSS(ru_maxrss, 합계 아님).
구간은 로버스트니스 실측과 같은 원본 Gate 적합 구간이다. 입력은 허가된 본인 촬영 샘플과 그 변환본이다.
결과는 data/research/syncnet-perf/(Git 제외)에 둔다.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.axes.alignment.syncnet import SyncNetConfig, run_syncnet  # noqa: E402
from server.jobs.child_process import start_process, stop_process  # noqa: E402

ROBUST = REPO_ROOT / "data/research/robustness-selfvideo"
OUT = REPO_ROOT / "data/research/syncnet-perf"
SAMPLES = REPO_ROOT / "data/research/samples"
VENV_PY = REPO_ROOT / "research/syncnet/.venv/bin/python"
PROFILE = REPO_ROOT / "research/syncnet/profile_run.py"
WEIGHTS = REPO_ROOT / "data/models/syncnet"
MODES = ("standalone", "supervised", "adapter")
SCHEMA_VERSION = 1
# E의 해상도 비교: 같은 CRF 28, 코덱을 H.264로 맞춘 1080/720/480 변환본(로버스트니스 실측의 변환본)
RESOLUTION_CONDITIONS = ("x264-crf28-source", "x264-crf28-720p", "x264-crf28-480p")


def plan() -> list[tuple[str, str, str, int]]:
    """(영상, 조건, 모드, 반복). 앞쪽이 먼저. 같은 영상의 모드를 번갈아 돌려 시간 흐름의 영향을 나눈다."""
    runs = []
    for video in "ABE":
        for rep in (1, 2):
            for mode in ("standalone", "supervised"):
                runs.append((video, "original", mode, rep))
        runs.append((video, "original", "adapter", 1))
    for cond in RESOLUTION_CONDITIONS:
        runs.append(("E", cond, "standalone", 1))
    return runs


def run_path(video: str, cond: str, mode: str, rep: int) -> Path:
    return OUT / "runs" / f"{video}__{cond}__{mode}__{rep}.json"


def media_of(video: str, cond: str) -> Path:
    if cond == "original":
        return SAMPLES / f"{video}.MOV"
    index = json.loads((ROBUST / "variants" / f"{video}.index.json").read_text(encoding="utf-8"))
    return REPO_ROOT / index["conditions"][cond]["file"]


def segments_of(video: str) -> list[list[float]]:
    gate = json.loads((ROBUST / "results" / video / "original" / "gate.json").read_text(encoding="utf-8"))
    return gate["result"]["eligible_segments"]


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def measure_one(video: str, cond: str, mode: str, rep: int) -> int:
    segments = segments_of(video)
    src = media_of(video, cond)
    (OUT / "work").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="job-", dir=OUT / "work") as tmp:
        job = Path(tmp).resolve()
        media = job / f"media{src.suffix.lower()}"
        try:
            os.link(src, media)
        except OSError:
            shutil.copyfile(src, media)
        prof_dir = job / "syncnet-perf"
        prof_dir.mkdir()
        request, output = prof_dir / "request.json", prof_dir / "profile.json"
        request.write_text(json.dumps({"video": str(media), "segments": segments, "weights_dir": str(WEIGHTS)}))
        cmd = [str(VENV_PY), str(PROFILE), "--request", str(request), "--output", str(output)]
        t0 = time.monotonic()
        profile = result = None
        if mode == "standalone":
            code = subprocess.run(cmd, cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode
        elif mode == "supervised":
            proc, fd = start_process(cmd, cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
            try:
                code = proc.wait()
            finally:
                stop_process(proc, fd)
        else:
            result = run_syncnet(media, segments, job, SyncNetConfig(timeout_sec=1800.0))
            code = 0 if result["status"] in ("completed", "insufficient_input") else 1
        wall = time.monotonic() - t0
        if mode != "adapter" and output.is_file():
            profile = json.loads(output.read_text(encoding="utf-8"))
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    write(run_path(video, cond, mode, rep), {
        "schema_version": SCHEMA_VERSION, "video": video, "condition": cond, "mode": mode, "rep": rep,
        "input": {"name": src.name, "size_bytes": src.stat().st_size},
        "segments_requested": segments, "wall_sec": round(wall, 3), "exit_code": code,
        "children_max_rss_bytes": usage.ru_maxrss, "machine": {"platform": platform.platform(), "machine": platform.machine()},
        "measured_at_unix": int(time.time()), "profile": profile, "adapter_result": result})
    return 0


def run_all(force: bool) -> int:
    for video, cond, mode, rep in plan():
        path = run_path(video, cond, mode, rep)
        if path.is_file() and not force:
            continue
        t0 = time.monotonic()
        code = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--one", video, cond, mode, str(rep)],
                              cwd=REPO_ROOT).returncode
        done = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        print(f"[{video}] {cond:18s} {mode:10s} #{rep} {time.monotonic() - t0:7.1f}s driver_exit={code} "
              f"child_exit={None if done is None else done['exit_code']}", flush=True)
    return 0


# ---------- 표 ----------

STAGES = (  # (이름, 설명). 위에서 아래로 upstream/래퍼의 실행 순서
    ("import_sec", "torch·SyncNet import"), ("weights_verify", "가중치 해시 확인"), ("model_load", "모델 로드"),
    ("cut_ffv1", "구간 절단(FFmpeg, FFV1+PCM, 원본 해상도)"), ("avi_convert", "25fps MJPEG AVI 변환(원본 해상도)"),
    ("audio_extract", "입력 오디오 추출(FFmpeg)"), ("frames_extract", "프레임 JPEG 추출(원본 해상도)"), ("audio_resample", "오디오 16kHz 변환"),
    ("detect_imread", "S3FD 입력 JPEG 읽기"), ("s3fd_detect", "S3FD 얼굴 검출(0.25배 축소)"),
    ("infer_loop_other", "검출 루프의 나머지(색 변환 등)"), ("scene_detect", "장면 검출(AVI 디코딩)"), ("track", "트래킹"),
    ("crop_imread", "크롭: JPEG 읽기"), ("crop_other", "크롭: 패딩·리사이즈·쓰기"), ("crop_audio_slice", "크롭: 오디오 자르기(FFmpeg)"),
    ("crop_mux", "크롭: 합치기(FFmpeg)"), ("crop_frames_extract", "크롭 프레임 JPEG 추출(224px)"),
    ("crop_audio_extract", "크롭 오디오 추출"), ("eval_imread", "SyncNet 입력 JPEG 읽기(224px)"), ("eval_mfcc", "MFCC"),
    ("eval_forward_lip", "영상 임베딩"), ("eval_forward_aud", "오디오 임베딩"), ("eval_pdist", "오프셋 탐색(거리 계산)"),
    ("eval_other", "SyncNet 평가의 나머지(텐서 변환 등)"), ("tmpdir_cleanup", "임시 폴더 삭제"),
    ("wrapper_other_sec", "래퍼의 나머지(구간 반복·JSON)"),
)


def stage_value(profile: dict, name: str) -> float:
    if name in ("import_sec", "wrapper_other_sec"):
        return profile[name]
    return profile["stage_sec"].get(name, 0.0)


def load_runs() -> dict:
    runs = {}
    for video, cond, mode, rep in plan():
        path = run_path(video, cond, mode, rep)
        if path.is_file():
            runs[(video, cond, mode, rep)] = json.loads(path.read_text(encoding="utf-8"))
    return runs


def f1(v) -> str:
    return "–" if v is None else f"{v:.1f}"


def tables() -> str:
    runs = load_runs()
    lines = []
    # 1) 총 시간
    lines += ["### 처리 시간 (초, 실행 한 건 전체 = 프로세스 시작부터 종료까지)", "",
              "| 영상 | 모드 | 1회 | 2회 | 평균 | 프로세스 안 시간(평균) | 시작·종료 오버헤드(평균) | 최대 RSS(GiB) |", "|---|---|---|---|---|---|---|---|"]
    for video in "ABE":
        for mode in MODES:
            rs = [runs.get((video, "original", mode, r)) for r in (1, 2)]
            rs = [r for r in rs if r]
            if not rs:
                continue
            walls = [r["wall_sec"] for r in rs]
            profs = [r["profile"] for r in rs if r.get("profile")]
            inside = [p["internal_sec"] for p in profs]
            over = [r["wall_sec"] - r["profile"]["internal_sec"] for r in rs if r.get("profile")]
            lines.append(f"| {video} | {mode} | {f1(walls[0])} | {f1(walls[1]) if len(walls) > 1 else '–'} | {f1(statistics.fmean(walls))} | "
                         f"{f1(statistics.fmean(inside)) if inside else '–'} | {f1(statistics.fmean(over)) if over else '–'} | "
                         f"{max(r['children_max_rss_bytes'] for r in rs) / 2 ** 30:.2f} |")
    # 2) 단계별 (standalone 평균)
    lines += ["", "### 단계별 시간 (초, standalone 2회 평균 / 괄호는 두 회의 차이)", "",
              "| 단계 | A | B | E |", "|---|---|---|---|"]
    cells = {}
    for video in "ABE":
        rs = [runs.get((video, "original", "standalone", r)) for r in (1, 2)]
        cells[video] = [r["profile"] for r in rs if r and r.get("profile")]
    for key, label in STAGES:
        row = [f"{label} (`{key}`)"]
        for video in "ABE":
            vals = [stage_value(p, key) for p in cells[video]]
            row.append("–" if not vals else f"{statistics.fmean(vals):.1f} (±{abs(vals[0] - vals[-1]) / 2:.1f})" if len(vals) > 1 else f"{vals[0]:.1f}")
        lines.append("| " + " | ".join(row) + " |")
    totals = ["**프로세스 안 합계**"] + [(f"{statistics.fmean(p['internal_sec'] for p in cells[v]):.1f}" if cells[v] else "–") for v in "ABE"]
    lines.append("| " + " | ".join(totals) + " |")
    # 3) 모드 비교
    lines += ["", "### 단계별 시간: standalone 대 supervised (초, 2회 평균)", "", "| 단계 | A 단독 | A supervisor | B 단독 | B supervisor | E 단독 | E supervisor |", "|---|---|---|---|---|---|---|"]
    for key, label in STAGES:
        row = [f"`{key}`"]
        for video in "ABE":
            for mode in ("standalone", "supervised"):
                rs = [runs.get((video, "original", mode, r)) for r in (1, 2)]
                vals = [stage_value(r["profile"], key) for r in rs if r and r.get("profile")]
                row.append("–" if not vals else f"{statistics.fmean(vals):.1f}")
        lines.append("| " + " | ".join(row) + " |")
    # 4) E 해상도
    lines += ["", "### E의 해상도별 단계 시간 (초, standalone 1회)", "",
              "| 단계 | 원본 HEVC 1080p (2회 평균) | CRF28 H.264 1080p | CRF28 720p | CRF28 480p |", "|---|---|---|---|---|"]
    cols = [cells["E"]] + [[runs[("E", c, "standalone", 1)]["profile"]] if ("E", c, "standalone", 1) in runs and runs[("E", c, "standalone", 1)].get("profile") else [] for c in RESOLUTION_CONDITIONS]
    for key, label in STAGES:
        row = [f"{label} (`{key}`)"]
        for col in cols:
            vals = [stage_value(p, key) for p in col]
            row.append("–" if not vals else f"{statistics.fmean(vals):.1f}")
        lines.append("| " + " | ".join(row) + " |")
    row = ["**프로세스 안 합계**"] + [("–" if not col else f"{statistics.fmean(p['internal_sec'] for p in col):.1f}") for col in cols]
    lines.append("| " + " | ".join(row) + " |")
    probes = []
    for col in cols:
        p = col[0] if col else None
        probes.append("–" if not p else "×".join(map(str, p["segments"][0].get("frame_wh") or ["?"])))
    lines.append("| 추출한 프레임 크기(첫 구간) | " + " | ".join(probes) + " |")
    # 5) 구간별 (B, E, A)
    for video in "ABE":
        r = runs.get((video, "original", "standalone", 1))
        if not r or not r.get("profile"):
            continue
        lines += ["", f"### {video}: 구간별 검출·트랙·결과 (standalone 1회)", "",
                  "| # | 구간(초) | 프레임 | 검출된 프레임 | 상자 합계 | 장면(프레임 범위) | 후보 트랙 길이(상위) | min_track(50) 초과 후보 | 트랙 | 결과 | 구간 시간(초) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in r["profile"]["segments"]:
            calls = s.get("track_calls", [])
            cand = "; ".join(str(c["candidate_track_lengths"][:3]) for c in calls) or "–"
            over = sum(c["longer_than_min_track"] for c in calls)
            trk = sum(c["tracks"] for c in calls)
            scenes = ", ".join(f"{a}–{b}" for a, b in s.get("scenes", [])) or "–"
            result = s["status"] + (f"/{s['reason_code']}" if s.get("reason_code") else "") + (f" ({s['error_type']})" if s.get("error_type") else "")
            lines.append(f"| {s['index']} | {s['start_sec']:.2f}–{s['end_sec']:.2f} | {s.get('frames', 0)} | {s.get('frames_with_box', 0)} | {s.get('boxes', 0)} | {scenes} | {cand} | {over} | {trk} | {result} | {s['inference_sec']:.1f} |")
    # 6) 재현성: 같은 입력의 두 회·모드가 같은 트랙 지표를 냈는지, 로버스트니스 실측과 같은지
    lines += ["", "### 결과 일치 확인", "", "| 영상 | 비교 | 구간 | 트랙 지표(오프셋·LSE-C·LSE-D) 일치 |", "|---|---|---|---|"]
    for video in "ABE":
        base = json.loads((ROBUST / "results" / video / "original" / "syncnet.json").read_text(encoding="utf-8"))["result"]["segments"]
        for mode in MODES:
            for rep in (1, 2):
                r = runs.get((video, "original", mode, rep))
                if not r:
                    continue
                rows = (r["profile"]["result"]["segments"] if r.get("profile") else r["adapter_result"]["segments"])
                same = [a["tracks"] == b["tracks"] and a["status"] == b["status"] for a, b in zip(rows, base)]
                lines.append(f"| {video} | {mode} #{rep} 대 로버스트니스 실측 | {len(same)} | {sum(same)}/{len(same)} 구간 동일 |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--one", nargs=4, metavar=("VIDEO", "CONDITION", "MODE", "REP"), help="(내부용) 한 건만 잰다")
    p.add_argument("--report", action="store_true")
    p.add_argument("--force", action="store_true")
    opt = p.parse_args(argv)
    if opt.one:
        return measure_one(opt.one[0], opt.one[1], opt.one[2], int(opt.one[3]))
    if opt.report:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "tables.md").write_text(tables(), encoding="utf-8")
        print(OUT / "tables.md")
        return 0
    return run_all(opt.force)


if __name__ == "__main__":
    sys.exit(main())
