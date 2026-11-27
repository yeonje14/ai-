"""기준 범위 예약 v2 실행기 (사용자가 터미널에서 오래 돌린다). 계획: docs/superpowers/plans/2026-11-27-evidence-range.md

    conda activate trinity                     # 저장소 루트
    caffeinate -i python scripts/evidence_range_run.py fetch
    caffeinate -i python scripts/evidence_range_run.py fetch --retry-incomplete   # v2 보완 45+4세션
    caffeinate -i python scripts/evidence_range_run.py analyze --gate-version gate-v2   # 12-03 Gate 결정 뒤
    python scripts/evidence_range_run.py status

fetch   두 역할을 5:3(F F C F F C F C 반복)으로 번갈아, 역할 안 order 순서로 한 세션씩
        공식 S3 방법(research/seamless/fetch_pilot.py, 별도 venv)으로 두 사람을 받는다
        → 전처리 규칙(6bc3493, scripts/seamless_preprocess.py)으로 필수 입력을 갖춘 사람마다 25초본을 만든다
        → 길이·스트림·오디오 일치·해시를 확인하고 즉시 원본(mp4·wav·json·npz)을 지운다.
        디스크에 두는 원본은 한 번에 1세션이다. 여유 공간이 --min-free-gb(기본 10) 아래면 멈춘다.
        Gate 결과를 모르는 단계라 정지 규칙을 적용하지 않고 예약 전체를 받는다(--max-sessions로 줄일 수 있다).
analyze 확정된 Gate 버전에서만 돈다. 사람마다 원본 25초본과 재압축본(training.emulator x264-crf28-720p)
        두 조건에서 Gate를 돌리고, 원본 Gate 통과자만 해당 조건에서 통과할 때 세 축을 돈다.
        역할별 고정 순서로 처리하며, 한 사람 이상 원본 Gate를 통과한 세션이 100개(range_fit)·60개(range_check)가
        되면 그 역할을 멈춘다. 측정 뒤 그 세션의 25초본과 파생본을 지우고 수치·상태·해시만 남긴다.

- 세션마다 state.json에 기록한다. 멈추거나 전원이 꺼져도 같은 명령으로 이어서 한다(끝나지 않은 세션은
  부분 파일을 지우고 처음부터 다시 한다).
- 실패하면 원인 코드를 기록하고 다음 세션으로 넘어간다. 네트워크·DNS 실패는 다음 실행에서 다시 시도하고
  (세션당 3회까지), 연속 3세션이면 멈춘다.
- 진행 로그는 한 줄(처리 수, 통과 수, 남은 디스크, 경과 시간)이다. 영상 내용·전사·URL은 남기지 않는다.
- 결과는 data/research/seamless/range_v2/ (Git 제외).
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SEAMLESS = REPO_ROOT / "data/research/seamless"
FETCH_SCRIPT = REPO_ROOT / "research/seamless/fetch_pilot.py"
VENV_PYTHON = SEAMLESS / ".venv/bin/python"
FILELIST = SEAMLESS / "src/seamless_interaction/assets/filelist.csv"

_spec = importlib.util.spec_from_file_location("fetch_pilot", FETCH_SCRIPT)
fetch_pilot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_pilot)

RANGE_DIR = fetch_pilot.RANGE_DIR
RANGE_LISTS = fetch_pilot.RANGE_LISTS
ROLES = ("range_fit", "range_check")
TARGETS = {"range_fit": 100, "range_check": 60}   # 한 사람 이상 원본 Gate 통과 세션 수
WHO = ("A", "B")
RECOMPRESS_PROFILE = "x264-crf28-720p"
CONDITIONS = ("original", RECOMPRESS_PROFILE)
PREPROCESS_RULE = "6bc3493"
DURATION_TOL_SEC = 0.1          # 25초 창 길이 허용 오차(파일럿 8개: 25.000~25.025)
MIN_AUDIO_NCC = 0.99            # 출력 오디오와 원본 WAV 같은 창의 정규화 상관(파일럿 8개: 0.9999~1.0)
NETWORK_KINDS = {"dns_error", "network_error"}
MAX_ATTEMPTS = 3
MAX_CONSECUTIVE_NETWORK = 3
FETCH_TIMEOUT_SEC = 3 * 3600

# 상태 값
PENDING, OK, FAILED, RETRY = "pending", "ok", "failed", "retry"
DONE, SKIPPED = "done", "skipped_fetch_failed"


# ---------- 공통 ----------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    """원자적 쓰기: 중간에 꺼져도 이전 내용이나 새 내용 둘 중 하나만 남는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_role(role: str, lists=RANGE_LISTS) -> list[dict]:
    """v2 역할 목록. 해시가 커밋한 값과 다르면 멈춘다."""
    path, expected = lists[role]
    if sha256_file(path) != expected:
        raise SystemExit(f"{path.name} 해시가 커밋한 값과 다르다. 멈춘다.")
    with path.open(newline="", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["order"]))
    if [int(r["order"]) for r in rows] != list(range(len(rows))) or any(r["role"] != role for r in rows):
        raise SystemExit(f"{path.name} 순서나 역할이 올바르지 않다")
    return rows


def session_dir(root: Path, role: str, order: int) -> Path:
    return root / role / f"{order:04d}"


@dataclass
class Progress:
    """한 줄 진행 로그. 숫자와 상태 코드만 쓴다."""
    log_path: Path
    started: float = field(default_factory=time.monotonic)
    clock: Callable[[], float] = time.monotonic

    def line(self, stage: str, role: str, order: int, status: str, processed: int, passed: int,
             total: int, free_bytes: int) -> str:
        sec = int(self.clock() - self.started)
        text = (f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {stage} {role} #{order:04d} {status} "
                f"processed={processed}/{total} passed={passed} free={free_bytes / 1e9:.1f}GB "
                f"elapsed={sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
        print(text, flush=True)
        return text


# ---------- fetch ----------

def official_index(file_ids: set[str], filelist: Path = FILELIST) -> dict[str, dict]:
    out = {}
    with filelist.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["file_id"] in file_ids:
                out[r["file_id"]] = r
    return out


def original_paths(file_id: str, index_row: dict, media: Path = fetch_pilot.MEDIA) -> list[Path]:
    """공식 패키지가 원본을 두는 위치(fetch_pilot.main과 같은 규칙). 이 세션의 파일만 가리킨다."""
    target = (media / index_row["label"] / index_row["split"] / f"{int(index_row['batch_idx']):04d}"
              / f"{int(index_row['archive_idx']):04d}")
    return [target / f"{file_id}.{ext}" for ext in ("mp4", "wav", "json", "npz")]


def remove_files(paths: list[Path]) -> bool:
    for p in paths:
        p.unlink(missing_ok=True)
        p.with_name(p.name + ".partial").unlink(missing_ok=True)
    return not any(p.exists() for p in paths)


def download_session(role: str, order: int, person: Optional[str] = None) -> dict:
    """별도 venv에서 공식 S3 래퍼를 부른다. stdout·stderr는 남기지 않는다(URL이 들어갈 수 있다)."""
    args = [str(VENV_PYTHON), "-I", str(FETCH_SCRIPT), "--role", role, "--order", str(order)]
    if person:
        args.extend(["--person", person])
    try:
        proc = subprocess.run(args,
                              cwd=str(REPO_ROOT), capture_output=True, timeout=FETCH_TIMEOUT_SEC)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    rec = read_json(session_dir(RANGE_DIR, role, order) / "fetch.json")
    return {"returncode": rc, "record": rec}


def classify_download(result: dict, file_ids: list[str]) -> tuple[str, Optional[str]]:
    """(OK | RETRY | FAILED, 원인 코드)."""
    downloads = (result.get("record") or {}).get("downloads") or {}
    if not downloads:
        # 보호 장치 거부·venv 문제·시간 초과. 영구 실패로 찍지 않고 다시 시도한다(연속 3회면 멈춘다)
        return RETRY, f"fetch_no_record_rc{result.get('returncode')}"
    kinds = set()
    for fid in file_ids:
        d = downloads.get(fid)
        if d is None:
            return FAILED, "download_record_missing"
        if d.get("status") != "ok":
            kinds.update(v.get("kind", "unknown") for v in (d.get("diagnosis") or {}).values())
            kinds.add("incomplete")
    if not kinds:
        return OK, None
    status = RETRY if kinds & NETWORK_KINDS else FAILED
    return status, "download_" + "+".join(sorted(kinds))


def preprocess_person(mp4: Path, wav: Path, vad_json: Path, out: Path) -> dict:
    """전처리 규칙(6bc3493) 그대로: VAD 발화량 최대 25초 얼굴 창 → x264-crf20-1080p + AAC. 확인 결과를 돌려준다."""
    from scripts import seamless_first_pair as fp
    from scripts import seamless_preprocess as pre

    vad = pre.load_vad(vad_json)
    video_probe, audio_probe = fp.ffprobe(mp4), fp.ffprobe(wav)
    try:
        tl = pre.timeline_from_probe(video_probe, audio_probe)
    except StopIteration as exc:
        exc.stream_counts = {
            "mp4_video": sum(s["codec_type"] == "video" for s in video_probe["streams"]),
            "mp4_total": len(video_probe["streams"]), "wav_total": len(audio_probe["streams"]),
        }
        raise
    face = pre.face_window(vad, tl["video_start_sec"], tl["video_start_sec"] + tl["video_duration_sec"],
                           tl["wav_duration_sec"])
    if face is None:
        return {"status": FAILED, "reason_code": pre.FACE_UNAVAILABLE, "timeline": tl}
    enc = pre.encode(mp4, wav, face["start_sec"], out)
    probe = fp.ffprobe(out)
    ref = fp.pcm_window(wav, "0:a:0", face["start_sec"], pre.WINDOW_SEC)
    got = fp.pcm_window(out, "0:a:0", 0.0, pre.WINDOW_SEC)
    audio = fp.xcorr_lag(ref, got)
    kinds = [s["codec_type"] for s in probe["streams"]]
    rec = {"window": face, "timeline": tl, "bytes": enc["bytes"], "sha256": enc["sha256"],
           "encode_sec": enc["elapsed_sec"], "duration": probe["duration"], "streams": kinds,
           "audio_vs_source_wav_window": audio}
    return {**rec, **verify_preprocessed(rec)}


def verify_preprocessed(rec: dict) -> dict:
    if rec["duration"] is None or abs(rec["duration"] - 25.0) > DURATION_TOL_SEC:
        return {"status": FAILED, "reason_code": "pre_duration"}
    if sorted(rec["streams"]) != ["audio", "video"]:
        return {"status": FAILED, "reason_code": "pre_streams"}
    a = rec["audio_vs_source_wav_window"]
    if a["lag_sec"] != 0.0 or a["peak_ncc"] < MIN_AUDIO_NCC:
        return {"status": FAILED, "reason_code": "pre_audio_mismatch"}
    return {"status": OK, "reason_code": None}


@dataclass
class FetchDeps:
    download: Callable[..., dict] = download_session
    preprocess: Callable[[Path, Path, Path, Path], dict] = preprocess_person
    index: Callable[[set], dict] = official_index
    free_bytes: Callable[[], int] = lambda: shutil.disk_usage(SEAMLESS).free
    media: Path = fetch_pilot.MEDIA


DIAGNOSTIC_ORDERS = {42, 119, 169, 180}


def retry_target(role: str, order: int, fetch: dict) -> bool:
    if fetch.get("status") != FAILED or fetch.get("one_time_retry"):
        return False
    if fetch.get("reason_code") == "download_incomplete+reachable":
        return True
    return (role == "range_fit" and order in DIAGNOSTIC_ORDERS
            and fetch.get("reason_code") == "no_person_preprocessed"
            and all(fetch["people"][who]["reason_code"] == "preprocess_StopIteration" for who in WHO))


def damaged_person(sdir: Path, row: dict, fetch: dict) -> Optional[str]:
    """성공 세션의 실패자에게만 최초 원본의 객관적 결함을 확인한다."""
    if fetch.get("status") != OK or fetch.get("one_time_retry"):
        return None
    for who, person in fetch["people"].items():
        if person["status"] != FAILED:
            continue
        path = sdir / "fetch.json"
        if not path.exists():  # 최초 기록 보관 뒤 상태 쓰기 전에 중단된 경우
            path = sdir / "attempts" / f"{fetch['attempts']}.json"
        entry = read_json(path).get("downloads", {}).get(row[f"file_id_{who.lower()}"], {})
        for ext in fetch_pilot.REQUIRED_STREAM:
            file = entry.get("files", {}).get(ext, {})
            size = file.get("bytes")
            if (("bytes" in file and (size is None or size < fetch_pilot.MIN_MEDIA_BYTES))
                    or ("required_stream_count" in file and not file["required_stream_count"])):
                return who
        if person.get("stream_counts", {}).get("mp4_video") == 0:
            return who
    return None


def fetch_one(root: Path, role: str, row: dict, deps: FetchDeps, one_time_retry: bool = False,
              person: Optional[str] = None) -> dict:
    order = int(row["order"])
    sdir = session_dir(root, role, order)
    state = read_json(sdir / "state.json")
    fetch = state.get("fetch") or {"status": PENDING, "attempts": 0}
    ids = {"A": row["file_id_a"], "B": row["file_id_b"]}
    person = fetch.get("retry_person", person)
    if person:
        ids = {person: ids[person]}
    index = deps.index(set(ids.values()))
    originals = [p for fid in ids.values() for p in original_paths(fid, index[fid], deps.media)]

    def finish_cleanup():
        if not remove_files(originals):
            raise SystemExit("원본을 지우지 못했다. 디스크 규칙(1세션) 때문에 멈춘다.")
        fetch["originals_removed"] = True
        fetch["free_bytes_after"] = deps.free_bytes()
        write_json(sdir / "state.json", state)
        return state

    if fetch.get("originals_removed") is False:
        return finish_cleanup()

    interrupted = fetch.get("one_time_retry") and fetch.get("status") == PENDING
    record_path = sdir / "fetch.json"
    if not interrupted:
        if one_time_retry:
            # 원본 기록과 현재 상태를 보존한 뒤 한 번의 다운로드 권한을 소비한다.
            archive = sdir / "attempts" / f"{fetch['attempts']}.json"
            if record_path.exists():
                write_json(archive, read_json(record_path))
            state.setdefault("attempts", []).append({
                "fetch": fetch, "download_record": str(archive.relative_to(sdir)) if archive.exists() else None,
            })
        remove_files(originals)
        record_path.unlink(missing_ok=True)
        fetch = {"status": PENDING, "attempts": fetch.get("attempts", 0) + 1, "started": time.time()}
        if one_time_retry:
            fetch["one_time_retry"] = True
            if person:
                fetch["retry_person"] = person
        state.update({"role": role, "order": order, "interaction_key": row["interaction_key"],
                      "vendor": row["vendor"], "fetch": fetch})
        write_json(sdir / "state.json", state)
    if person:
        (sdir / "pre" / f"{person}.mp4").unlink(missing_ok=True)
    else:
        shutil.rmtree(sdir / "pre", ignore_errors=True)
    t0 = time.monotonic()
    if interrupted:
        # 완료된 다운로드 기록과 필수 원본이 남아 있으면 전처리만 재개한다.
        try:
            record = read_json(record_path)
        except (ValueError, UnicodeError):
            record = {}
        for fid, entry in record.get("downloads", {}).items():
            if fid in index and entry.get("status") == OK:
                required = original_paths(fid, index[fid], deps.media)[:3]
                if not all(p.is_file() and p.stat().st_size for p in required):
                    record = {}
                    break
        result = {"record": record, "returncode": None}
    else:
        result = deps.download(role, order, person) if person else deps.download(role, order)
    status, reason = classify_download(result, list(ids.values()))
    if interrupted and not result["record"]:
        status, reason = FAILED, "retry_interrupted"
    fetch["download_sec"] = round(time.monotonic() - t0, 1)
    fetch["download_bytes"] = sum(p.stat().st_size for p in originals if p.exists())
    people = {}
    if person:
        people = {who: value for who, value in state["attempts"][-1]["fetch"]["people"].items() if who != person}
        people[person] = {"status": FAILED, "reason_code": reason}
    downloads = (result.get("record") or {}).get("downloads") or {}
    if downloads:
        for who, fid in ids.items():
            person_download = downloads.get(fid, {})
            if person_download.get("status") != OK:
                people[who] = {"status": FAILED, "reason_code": "download_incomplete" if person_download
                               else "download_record_missing", "missing_required": person_download.get("missing_required")}
                files = person_download.get("files", {})
                people[who]["media_checks"] = {
                    ext: {k: files[ext][k] for k in ("bytes", "required_stream_count") if k in files[ext]}
                    for ext in fetch_pilot.REQUIRED_STREAM if ext in files
                }
                continue
            (sdir / "pre").mkdir(parents=True, exist_ok=True)
            mp4, wav, vad_json, _ = original_paths(fid, index[fid], deps.media)
            try:
                people[who] = deps.preprocess(mp4, wav, vad_json, sdir / "pre" / f"{who}.mp4")
            except Exception as e:   # 한 사람이 실패해도 다른 사람은 계속한다
                people[who] = {"status": FAILED, "reason_code": f"preprocess_{type(e).__name__}"}
                if isinstance(e, StopIteration):
                    people[who]["traceback"] = [
                        {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(e.__traceback__)
                    ]
                    people[who]["stream_counts"] = getattr(e, "stream_counts", {})
            if people[who]["status"] != OK:
                (sdir / "pre" / f"{who}.mp4").unlink(missing_ok=True)
    if status == RETRY and (fetch.get("one_time_retry") or fetch["attempts"] >= MAX_ATTEMPTS):
        status = FAILED
    if any(p["status"] == OK for p in people.values()):
        status, reason = OK, None
    elif status == OK:
        status, reason = FAILED, "no_person_preprocessed"
    fetch.update({"status": status, "reason_code": reason, "people": people, "finished": time.time(),
                  "originals_removed": False})
    write_json(sdir / "state.json", state)
    return finish_cleanup()


FETCH_RATIO = (("range_fit", 5), ("range_check", 3))


def fetch_sequence(roles, rows_by_role: dict) -> list[tuple[str, dict]]:
    """fetch 처리 순서. 두 역할이면 5:3(F F C F F C F C 반복)으로 번갈아, 역할 안은 order 순서다.

    k번째까지 range_fit 수는 ceil(5(k+1)/8)이다. 한 역할이 끝나면 남은 역할을 이어서 받는다.
    상태와 무관한 고정 순서라 중간에 멈췄다 다시 돌려도 같은 순서를 따른다.
    """
    queues = {role: list(rows_by_role[role]) for role in roles}
    (first, a), (second, b) = FETCH_RATIO
    seq: list[tuple[str, dict]] = []
    k = 0
    while any(queues.values()):
        if set(queues) == {first, second}:
            want = first if math.ceil(a * (k + 1) / (a + b)) > math.ceil(a * k / (a + b)) else second
            k += 1
            role = want if queues[want] else (second if want == first else first)
        else:
            role = next(r for r in queues if queues[r])
        seq.append((role, queues[role].pop(0)))
    return seq


def run_fetch(root: Path, roles, rows_by_role: dict, deps: FetchDeps, progress: Progress,
              min_free_bytes: int, max_sessions: Optional[int] = None, retry_incomplete: bool = False) -> str:
    """반환: 멈춘 이유(complete | low_disk | network | max_sessions)."""
    if retry_incomplete and (root / "reference_version.json").exists():
        raise SystemExit("analyze 기준 버전 봉인 뒤에는 재처리할 수 없다")
    handled = 0
    consecutive_network = 0
    for role, row in fetch_sequence(roles, rows_by_role):
        rows = rows_by_role[role]
        order = int(row["order"])
        prev = (read_json(session_dir(root, role, order) / "state.json").get("fetch") or {})
        cleanup_pending = prev.get("originals_removed") is False
        person = None
        if retry_incomplete:
            person = damaged_person(session_dir(root, role, order), row, prev)
            resume = prev.get("one_time_retry") and (cleanup_pending or prev["status"] == PENDING)
            if not person and not resume and not retry_target(role, order, prev):
                continue
        elif not cleanup_pending and prev.get("status") in (OK, FAILED):
            continue
        if max_sessions is not None and handled >= max_sessions:
            return "max_sessions"
        free = deps.free_bytes()
        if free < min_free_bytes and not cleanup_pending:
            progress.line("fetch", role, order, "stop_low_disk", *_fetch_counts(root, role, rows),
                          len(rows), free)
            return "low_disk"
        state = fetch_one(root, role, row, deps, retry_incomplete, person)
        handled += 1
        st = state["fetch"]
        progress.line("fetch", role, order, f"{st['status']}" + (f":{st['reason_code']}" if st["reason_code"]
                                                                   else ""),
                      *_fetch_counts(root, role, rows), len(rows), deps.free_bytes())
        consecutive_network = consecutive_network + 1 if st["status"] == RETRY else 0
        if consecutive_network >= MAX_CONSECUTIVE_NETWORK:
            return "network"
    return "complete"


def _fetch_counts(root: Path, role: str, rows) -> tuple[int, int]:
    """(끝난 세션 수, 25초본을 만든 세션 수)."""
    done = ok = 0
    for row in rows:
        st = (read_json(session_dir(root, role, int(row["order"])) / "state.json").get("fetch") or {})
        done += st.get("status") in (OK, FAILED)
        ok += st.get("status") == OK
    return done, ok


# ---------- analyze ----------

def gate_passed(result: Optional[dict]) -> bool:
    return bool(result and ((result.get("gate") or {}).get("eligible_segments")))


def run_condition(src: Path, gate_only: bool, work: Path) -> dict:
    from scripts import seamless_first_pair as fp
    return fp.run_file(src, work, gate_only=gate_only)


def recompress(src: Path, out_dir: Path) -> tuple[dict, Optional[Path]]:
    from training.emulator.video import emulate, output_name
    rec = emulate(src, RECOMPRESS_PROFILE, out_dir)
    keep = {k: rec.get(k) for k in ("status", "reason_code", "profile_id", "ffmpeg_version")}
    keep["input_sha256"] = (rec.get("input") or {}).get("sha256")
    keep["output_sha256"] = (rec.get("output") or {}).get("sha256")
    out = out_dir / output_name(src, RECOMPRESS_PROFILE)
    return keep, (out if rec.get("status") == "completed" and out.exists() else None)


@dataclass
class AnalyzeDeps:
    run_condition: Callable[[Path, bool, Path], dict] = run_condition
    recompress: Callable[[Path, Path], tuple] = recompress
    free_bytes: Callable[[], int] = lambda: shutil.disk_usage(SEAMLESS).free


def analyze_one(root: Path, role: str, order: int, deps: AnalyzeDeps) -> dict:
    sdir = session_dir(root, role, order)
    state = read_json(sdir / "state.json")
    work = sdir / "work"
    shutil.rmtree(work, ignore_errors=True)          # 끝나지 않은 이전 시도
    shutil.rmtree(sdir / "results", ignore_errors=True)
    analysis = {"status": PENDING, "started": time.time(), "people": {}}
    state["analyze"] = analysis
    write_json(sdir / "state.json", state)
    for who in WHO:
        pre = sdir / "pre" / f"{who}.mp4"
        person = {}
        analysis["people"][who] = person
        if not pre.exists():
            person["status"] = "no_preprocessed_input"
            continue
        person["input_sha256"] = sha256_file(pre)
        expected = ((state.get("fetch") or {}).get("people") or {}).get(who, {}).get("sha256")
        if expected and person["input_sha256"] != expected:
            person["status"] = "input_hash_mismatch"
            continue
        results = {}
        try:
            results["original"] = deps.run_condition(pre, False, work)
        except Exception as e:
            results["original"] = {"exception": type(e).__name__}
        passed = gate_passed(results["original"])
        person["original_gate_passed"] = passed
        try:
            emu, out = deps.recompress(pre, work / "emu")
        except Exception as e:
            emu, out = {"status": "error", "reason_code": f"recompress_{type(e).__name__}"}, None
        person["recompress"] = emu
        if out is not None:
            try:
                results[RECOMPRESS_PROFILE] = deps.run_condition(out, not passed, work)
            except Exception as e:
                results[RECOMPRESS_PROFILE] = {"exception": type(e).__name__}
            out.unlink(missing_ok=True)
        person["recompressed_gate_passed"] = gate_passed(results.get(RECOMPRESS_PROFILE))
        person["status"] = "measured"
        for cond, res in results.items():
            write_json(sdir / "results" / f"{who}.{cond}.json", res)
    analysis["session_passed"] = any(p.get("original_gate_passed") for p in analysis["people"].values())
    analysis.update({"status": DONE, "finished": time.time()})
    write_json(sdir / "state.json", state)
    cleanup_media(sdir)
    return state


def cleanup_media(sdir: Path) -> None:
    """측정이 끝난 세션의 25초본과 파생본을 지운다. 수치·상태·해시만 남는다."""
    shutil.rmtree(sdir / "work", ignore_errors=True)
    shutil.rmtree(sdir / "pre", ignore_errors=True)


def analyze_counts(root: Path, role: str, rows) -> tuple[int, int, Optional[int]]:
    """(처리한 세션 수, 통과 세션 수, 처음 처리 안 된 order)."""
    processed = passed = 0
    for row in rows:
        order = int(row["order"])
        st = read_json(session_dir(root, role, order) / "state.json").get("analyze") or {}
        if st.get("status") not in (DONE, SKIPPED):
            return processed, passed, order
        processed += 1
        passed += bool(st.get("session_passed"))
    return processed, passed, None


def seal_reference(root: Path, gate_version: str, extra: dict) -> dict:
    """기준 버전 기록. 이미 있으면 같은 Gate 버전이어야 한다(다른 버전은 다른 기준으로 분리)."""
    path = root / "reference_version.json"
    rec = read_json(path)
    if rec:
        if rec["gate_version"] != gate_version:
            raise SystemExit(f"기준 버전의 Gate가 {rec['gate_version']}이다. 다른 Gate는 다른 기준 폴더에서 돈다.")
        return rec
    rec = {"gate_version": gate_version, "sealed": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra}
    write_json(path, rec)
    return rec


def run_analyze(root: Path, roles, rows_by_role: dict, deps: AnalyzeDeps, progress: Progress,
                min_free_bytes: int, targets=TARGETS) -> str:
    """반환: complete | low_disk | waiting_fetch."""
    for role in roles:
        rows = rows_by_role[role]
        while True:
            processed, passed, order = analyze_counts(root, role, rows)
            if passed >= targets[role] or order is None:
                status = "target_reached" if passed >= targets[role] else "reservation_exhausted"
                summary = read_json(root / "analyze_summary.json")
                summary[role] = {"status": status, "processed": processed, "passed_sessions": passed,
                                 "target": targets[role], "reserved": len(rows)}
                write_json(root / "analyze_summary.json", summary)
                progress.line("analyze", role, max(processed - 1, 0), status, processed, passed, len(rows),
                              deps.free_bytes())
                break
            sdir = session_dir(root, role, order)
            # 끝난 세션이 측정 전 지워지지 않은 경우(정리 중 꺼짐)도 여기서 정리된다
            fetch = read_json(sdir / "state.json").get("fetch") or {}
            if fetch.get("status") == FAILED:
                state = read_json(sdir / "state.json")
                state["analyze"] = {"status": SKIPPED, "reason_code": fetch.get("reason_code")}
                write_json(sdir / "state.json", state)
                cleanup_media(sdir)
                progress.line("analyze", role, order, SKIPPED, processed + 1, passed, len(rows), deps.free_bytes())
                continue
            if fetch.get("status") != OK:
                # 고정 순서를 지키려고 건너뛰지 않는다. fetch를 먼저 끝낸다.
                progress.line("analyze", role, order, "wait_fetch", processed, passed, len(rows), deps.free_bytes())
                return "waiting_fetch"
            free = deps.free_bytes()
            if free < min_free_bytes:
                progress.line("analyze", role, order, "stop_low_disk", processed, passed, len(rows), free)
                return "low_disk"
            state = analyze_one(root, role, order, deps)
            a = state["analyze"]
            progress.line("analyze", role, order, "passed" if a["session_passed"] else "not_passed",
                          processed + 1, passed + bool(a["session_passed"]), len(rows), deps.free_bytes())
    return "complete"


# ---------- status ----------

def status_report(root: Path, rows_by_role: dict) -> dict:
    out = {}
    for role, rows in rows_by_role.items():
        f_counts: dict[str, int] = {}
        reasons: dict[str, int] = {}
        pre_left = 0
        for row in rows:
            sdir = session_dir(root, role, int(row["order"]))
            st = read_json(sdir / "state.json")
            f = (st.get("fetch") or {}).get("status", PENDING)
            f_counts[f] = f_counts.get(f, 0) + 1
            r = (st.get("fetch") or {}).get("reason_code")
            if r:
                reasons[r] = reasons.get(r, 0) + 1
            pre_left += any((sdir / "pre" / f"{who}.mp4").is_file() for who in WHO)
        diagnostic_counts = {}
        if role == "range_fit":
            for order in sorted(DIAGNOSTIC_ORDERS):
                fetch = read_json(session_dir(root, role, order) / "state.json").get("fetch", {})
                for who in WHO:
                    person = fetch.get("people", {}).get(who, {})
                    if not fetch.get("one_time_retry") or fetch.get("status") == PENDING:
                        code = "awaiting_diagnosis"
                    elif (person.get("stream_counts", {}).get("mp4_video") == 0 or
                          person.get("media_checks", {}).get("mp4", {}).get("required_stream_count") == 0):
                        code = "mp4_video_stream_absent"
                    else:
                        code = person.get("reason_code") or ("preprocessed" if person.get("status") == OK
                                                            else fetch.get("reason_code") or "diagnosis_unavailable")
                    diagnostic_counts[code] = diagnostic_counts.get(code, 0) + 1
        processed, passed, nxt = analyze_counts(root, role, rows)
        out[role] = {"reserved": len(rows), "fetch": f_counts, "fetch_reasons": reasons,
                     "sessions_with_preprocessed_media": pre_left,
                     "analyze": {"processed": processed, "passed_sessions": passed, "target": TARGETS[role],
                                 "next_order": nxt}}
        if diagnostic_counts:
            out[role]["stop_iteration_diagnosis_people"] = diagnostic_counts
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "analyze", "status"):
        p = sub.add_parser(name)
        p.add_argument("--role", choices=(*ROLES, "all"), default="all")
        if name != "status":
            p.add_argument("--min-free-gb", type=float, default=10.0)
    sub.choices["fetch"].add_argument("--retry-incomplete", action="store_true",
                                      help="reachable 실패·지정 진단 쌍과 성공 세션 내 원본 결함이 확인된 실패자만 한 번 재처리")
    sub.choices["fetch"].add_argument("--max-sessions", type=int, default=None)
    sub.choices["analyze"].add_argument("--gate-version", required=True,
                                        help="12-03에 확정한 Gate 버전. 코드의 GATE_VERSION과 같아야 한다")
    opt = ap.parse_args(argv)

    roles = ROLES if opt.role == "all" else (opt.role,)
    rows_by_role = {role: load_role(role) for role in roles}
    progress = Progress(RANGE_DIR / "run.log")
    if opt.cmd == "status":
        print(json.dumps(status_report(RANGE_DIR, rows_by_role), ensure_ascii=False, indent=2))
        return 0
    RANGE_DIR.mkdir(parents=True, exist_ok=True)
    with (RANGE_DIR / ".runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("fetch 또는 analyze가 이미 실행 중이다")
        return run_command(opt, roles, rows_by_role, progress)


def run_command(opt, roles, rows_by_role, progress) -> int:
    min_free = int(opt.min_free_gb * 1e9)
    if opt.cmd == "fetch":
        if not VENV_PYTHON.exists():
            raise SystemExit("data/research/seamless/.venv가 없다(docs/seamless-first-pair.md)")
        why = run_fetch(RANGE_DIR, roles, rows_by_role, FetchDeps(), progress, min_free, opt.max_sessions,
                        opt.retry_incomplete)
    else:
        from training.features.extract import GATE_VERSION
        if opt.gate_version != GATE_VERSION:
            raise SystemExit(f"--gate-version {opt.gate_version} != 코드의 GATE_VERSION {GATE_VERSION}")
        from training.emulator.profiles import PROFILES
        seal_reference(RANGE_DIR, GATE_VERSION, {
            "reservation_sha256": {role: RANGE_LISTS[role][1] for role in ROLES},
            "preprocess_rule": PREPROCESS_RULE, "recompress_profile": PROFILES[RECOMPRESS_PROFILE].to_dict(),
            "targets": TARGETS, "runner_sha256": sha256_file(Path(__file__)),
            "statistics": "plan 2026-11-27 v2: 세션별·신호별 최댓값, 세션 단위 부트스트랩, 단측 2.5%×2",
        })
        why = run_analyze(RANGE_DIR, roles, rows_by_role, AnalyzeDeps(), progress, min_free)
    print(f"멈춘 이유: {why}", flush=True)
    return 0 if why == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
