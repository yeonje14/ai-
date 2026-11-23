"""수명주기 검증의 프로세스 관찰, 단계 시간과 격리 API 접수. 영상·모델은 쓰지 않는다."""
import importlib.util
import json
import os
import secrets
import sqlite3
from contextlib import closing
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('verify_real_worker_lifecycle', REPO_ROOT / 'scripts/verify_real_worker_lifecycle.py')
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

JOB = '/repo/data/runtime/real-lifecycle/x/jobs/11111111-2222-3333-4444-555555555555'


def test_short_name_keeps_only_executable_and_script_names():
    assert lc.short_name('/a/.venv/bin/python /repo/research/syncnet/infer_segments.py --request /p/q.json') \
        == 'python infer_segments.py'
    assert lc.short_name('/opt/env/bin/python -m server.jobs.supervisor 5 /x/python /y/infer_frames.py') \
        == 'python server.jobs.supervisor'
    assert lc.short_name('/opt/homebrew/bin/ffmpeg -y -i /secret/clip.avi out.avi') == 'ffmpeg'


def test_job_processes_include_process_group_members_without_the_job_path():
    rows = [
        {'pid': 10, 'ppid': 1, 'pgid': 10, 'stat': 'S', 'command': f'python -m server.jobs.supervisor 5 py {JOB}/r.json'},
        {'pid': 11, 'ppid': 10, 'pgid': 11, 'stat': 'S', 'command': f'python infer_segments.py --request {JOB}/s/r.json'},
        {'pid': 12, 'ppid': 11, 'pgid': 11, 'stat': 'S', 'command': 'ffmpeg -i pipe:0 out.wav'},  # 경로 없는 후손
        {'pid': 20, 'ppid': 1, 'pgid': 20, 'stat': 'S', 'command': 'python other.py'},
        {'pid': 30, 'ppid': 1, 'pgid': 30, 'stat': 'S', 'command': f'python -m server.jobs.worker {JOB}'},
    ]
    found = lc.job_processes(rows, JOB, exclude={30})
    assert sorted(p['pid'] for p in found) == [10, 11, 12]
    assert {p['name'] for p in found} == {'python server.jobs.supervisor', 'python infer_segments.py', 'ffmpeg'}


def test_stage_durations_only_within_the_same_worker():
    times = [[1, 'validating', 0.0], [1, 'preprocessing', 1.0], [1, 'waverep', 13.5], [2, 'validating', 50.0],
             [2, 'preprocessing', 50.5]]
    assert lc.stage_durations(times) == {'w1.validating': 1.0, 'w1.preprocessing': 12.5, 'w2.validating': 0.5}


def test_stage_line_pattern_matches_worker_log_format():
    m = lc.STAGE_LINE.match('2026-11-19 01:57:49,106 trinity.worker job c9f2971d-f3d3-4602-a889-2ed9ec59b08a stage waverep')
    assert m and m.group(2) == '106' and m.group(3) == 'waverep'
    assert lc.STAGE_LINE.match('2026-11-19 01:57:49,106 trinity.worker job c9f2971d-f3d3-4602-a889-2ed9ec59b08a cancelled') is None


def test_every_scenario_has_a_runner_and_env():
    assert set(lc.SCENARIOS) == set(lc.RUNNERS) == set(lc.SCENARIO_ENV)
    # 제한을 낮추는 시나리오만 제한 환경 변수를 바꾼다
    assert lc.SCENARIO_ENV['sigkill-syncnet'] == {} and lc.SCENARIO_ENV['cancel-syncnet'] == {}


def test_process_query_failure_cannot_count_as_dead(monkeypatch):
    def denied(args, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="denied")

    monkeypatch.setattr(lc.subprocess, "run", denied)
    with pytest.raises(subprocess.CalledProcessError):
        lc.alive(123)


def test_cached_failed_run_cannot_succeed(tmp_path, monkeypatch):
    sample = tmp_path / "data/research/samples/A.MOV"
    sample.parent.mkdir(parents=True)
    sample.touch()
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    monkeypatch.setattr(lc, "OUT", tmp_path)
    (tmp_path / "sigkill-gate.json").write_text('{"scenario":"sigkill-gate"}')
    assert lc.main(["--only", "sigkill-gate"]) == 1


def test_harness_runs_owned_job_without_disclosing_credential(tmp_path, monkeypatch, capfd):
    """미등록 ID로 실제 API·Worker와 정상/오류 응답을 검증한다."""
    from server import accounts

    monkeypatch.setattr(lc, "RUNTIME", tmp_path)
    key = secrets.token_urlsafe(32)
    monkeypatch.setattr(accounts.secrets, "token_urlsafe", lambda _: key)
    # 실제 API·Worker를 띄우기 직전에 원문 노출 여부만 남긴다.
    launch = subprocess.Popen
    child_exposures = []

    def checked_launch(args, **kwargs):
        child_exposures.append(key in repr((args, kwargs.get("env", os.environ))))
        return launch(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", checked_launch)
    harness = lc.Harness("cancel-motionphys")
    try:
        # WAL/SHM이 검사 전에 마지막 연결과 함께 제거되지 않게 유지한다.
        with closing(sqlite3.connect(harness.db)) as db:
            db.execute("SELECT 1 FROM credentials").fetchone()
            status, created, _ = harness.call("/analyses", "POST", {"url": "https://youtu.be/TRINITYnone"})
            assert status == 202
            aid = created["analysis_id"]
            status, job, headers = harness.call("/analyses/" + aid)
            assert status == 200 and job["job_status"] == "queued" and headers["ETag"]
            worker = harness.start_worker(drain=True)
            assert worker.wait(timeout=20) == 0
            result = lc.summarize_result(harness, aid)
            assert result["job_status"] == "finished" and result["analysis_status"] == "analysis_unavailable"
            missing = lc.summarize_result(harness, "00000000-0000-4000-8000-000000000000")
            assert missing == {"http": 404}

            record = json.dumps([created, job, result, missing, harness.log_lines()])
            result_exposed = key in record
            files = [p for p in harness.work.rglob("*") if p.is_file()]
            assert {"server.log", "worker1.log", "registry.json", "queue.sqlite3",
                    "queue.sqlite3-wal", "queue.sqlite3-shm"} <= {p.name for p in files}
            file_exposed = any(key.encode() in p.read_bytes() for p in files)
    finally:
        harness.close()
        stdout, stderr = capfd.readouterr()
    output_exposed = key in stdout or key in stderr
    assert child_exposures == [False, False]
    assert not result_exposed
    assert not file_exposed
    assert not output_exposed
