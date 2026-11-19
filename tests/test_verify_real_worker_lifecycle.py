"""scripts/verify_real_worker_lifecycle.py의 보조 논리(프로세스 찾기, 단계 시간). 영상·모델·서버는 쓰지 않는다."""
import importlib.util
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
