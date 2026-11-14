"""실제 자식 프로세스로 Gate 실행 경계와 Worker의 lease/종료 동작을 검증한다."""
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from server.gate import runner
from server.gate.types import GateResult, MediaInfo, Segment
from server.jobs import worker
from tests.conftest import REGISTERED_ID

MEDIA = MediaInfo(10.0, 1920, 1080, 30.0, 0, True)
REJECT = GateResult(MEDIA, "no_mouth_movement", excluded_segments=(Segment(0, 10, "no_mouth_movement"),))
OWNER = "gate-process-owner"


@pytest.fixture
def fake_process(tmp_path, monkeypatch):
    def install(body):
        script = tmp_path / "fake_gate.py"
        script.write_text("import json, sys, time, subprocess\nfrom pathlib import Path\n"
                          "request = Path(sys.argv[1])\n"
                          "output = request.parent / 'gate_result.json'\n" + body)
        commands = []
        def command(request):
            commands.append(request)
            return [sys.executable, str(script), str(request)]
        monkeypatch.setattr(runner, "build_command", command)
        return commands
    return install


def output_result(result=REJECT):
    return f"output.write_text({json.dumps(asdict(result))!r})\n"


def test_gate_command_uses_same_python_and_only_request_path(tmp_path):
    request = tmp_path / "gate_request.json"
    assert runner.build_command(request) == [sys.executable, "-m", "server.gate.process", str(request)]


@pytest.mark.parametrize("body,reason", [
    (output_result(), "no_mouth_movement"),
    ("raise RuntimeError('private media')\n", "gate_error"),
    ("output.write_text('{broken')\n", "gate_error"),
    ("output.write_text('{}')\n", "gate_error"),
    (output_result() + "sys.exit(2)\n", "gate_error"),
    ("time.sleep(60)\n", "gate_timeout"),
])
def test_process_outcomes_reach_worker_and_cleanup(queue, registry, settings, fake_process,
                                                  monkeypatch, body, reason):
    commands = fake_process(body)
    settings = replace(settings, gate_timeout_seconds=.4, heartbeat_interval_seconds=.1)
    called = []
    monkeypatch.setattr(worker.signal_axis, "run", lambda ctx: called.append(True))
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    worker.run_once(queue, registry, settings, "w")
    job = queue.get(aid, OWNER)
    assert called == []
    assert job.job_status == "finished"
    assert job.result["reason_code"] == reason
    assert job.result["axes"]["signal"]["raw_score"] is None
    assert "private media" not in json.dumps(job.result)
    assert commands == [(settings.runtime_dir / aid / "gate_request.json").resolve()]
    assert not (settings.runtime_dir / aid).exists()


def test_heartbeat_extends_lease_in_preprocessing(queue, registry, settings, fake_process, monkeypatch):
    fake_process("time.sleep(.7)\n" + output_result())
    settings = replace(settings, lease_seconds=.4, heartbeat_interval_seconds=.1)
    observed = []
    heartbeat = queue.heartbeat
    def beat(*args):
        state = heartbeat(*args)
        with sqlite3.connect(queue.db_path) as conn:
            stage, expiry = conn.execute("SELECT stage, lease_expires_at FROM jobs WHERE analysis_id=?", (args[0],)).fetchone()
        observed.append((stage, expiry))
        assert queue.claim("competitor", .4, 2) is None
        return state
    monkeypatch.setattr(queue, "heartbeat", beat)
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    worker.run_once(queue, registry, settings, "w")
    assert queue.get(aid, OWNER).job_status == "finished"
    assert len(observed) >= 4
    assert all(stage == "preprocessing" for stage, _ in observed)
    assert observed[-1][1] > observed[0][1] + .4


@pytest.mark.parametrize("mode,expected", [("cancel", "cancelled"), ("lease", "processing"), ("timeout", "failed")])
def test_gate_interruption_stops_process_without_result(queue, registry, settings, fake_process,
                                                       monkeypatch, mode, expected):
    fake_process("time.sleep(60)\n")
    settings = replace(settings, heartbeat_interval_seconds=.1,
                       job_timeout_seconds=.3 if mode == "timeout" else 60)
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    heartbeat = queue.heartbeat
    calls = []
    def beat(*args):
        calls.append(True)
        if len(calls) == 2:
            if mode == "cancel":
                queue.request_cancel(aid, OWNER)
            elif mode == "lease":
                with sqlite3.connect(queue.db_path) as conn:
                    conn.execute("UPDATE jobs SET lease_owner='other' WHERE analysis_id=?", (aid,))
        return heartbeat(*args)
    monkeypatch.setattr(queue, "heartbeat", beat)
    started = time.monotonic()
    worker.run_once(queue, registry, settings, "w")
    assert time.monotonic() - started < 5
    job = queue.get(aid, OWNER)
    assert job.job_status == expected and job.result is None
    if mode == "timeout":
        assert job.failure_reason == "timeout"
    assert not (settings.runtime_dir / aid).exists()


def test_timeout_kills_descendant_and_removes_protocol_files(tmp_path, settings, fake_process):
    pid_file = tmp_path / "child.pid"
    fake_process("child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                 f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                 "time.sleep(60)\n")
    media = tmp_path / "media.mp4"
    media.write_bytes(b"fake")
    result = runner.run_gate_process(media, tmp_path, settings=replace(settings, gate_timeout_seconds=.5),
                                     timeout_seconds=10, on_tick=lambda: True)
    assert result.reason_code == "gate_timeout"
    pid = int(pid_file.read_text())
    # kill(0)에서는 잠시 좀비가 보일 수 있다. 실행 중인 후손만 없어야 한다.
    import subprocess
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    assert not state or state.startswith("Z")
    assert not (tmp_path / "gate_request.json").exists()
    assert not (tmp_path / "gate_result.json").exists()


@pytest.mark.parametrize("result", [
    GateResult(MEDIA, None),
    GateResult(MEDIA, "invented"),
    GateResult(None, None, eligible_segments=(Segment(0, 2),)),
    GateResult(MEDIA, None, eligible_segments=(Segment(-1, 2),)),
    GateResult(MEDIA, None, eligible_segments=(Segment(0, 11),)),
    GateResult(MEDIA, None, eligible_segments=(Segment(0, float('nan')),)),
    GateResult(MEDIA, None, eligible_segments=(Segment(0, 2), Segment(1, 3))),
    GateResult(MEDIA, "no_speech_detected", eligible_segments=(Segment(0, 2),)),
])
def test_invalid_gate_result_is_not_used(result):
    with pytest.raises(ValueError):
        runner.parse_result(json.dumps(asdict(result)))


def test_valid_eligible_result_round_trips():
    result = GateResult(MEDIA, None, eligible_segments=(Segment(1, 3),), speech_segments=((1, 3),))
    assert runner.parse_result(json.dumps(asdict(result))) == result


def test_rounded_face_and_mouth_boundary_keeps_eligible_segment():
    from server.gate.segments import build_result
    from server.gate.types import Face, FrameFaces

    media = replace(MEDIA, fps=49.95)
    face = Face(0, 0, 200, 200, .9, 42, 0)
    frames = [FrameFaces(index / 49.95, (face,) if index <= 50 else ())
              for index in range(0, 500, 10)]
    mouth_end = round(45 / 49.95 + .2, 3)
    result = build_result(media, [(0, 10)], frames, mouth_active=[(0, mouth_end)])
    parsed = runner.parse_result(json.dumps(asdict(result)))
    assert [(s.start_sec, s.end_sec) for s in parsed.eligible_segments] == [(0, 1.101)]
    assert [(s.start_sec, s.end_sec, s.reason_code) for s in parsed.excluded_segments] == [
        (1.101, 10, "no_face_detected"),
    ]


def test_stale_result_is_removed_before_launch(tmp_path, settings, fake_process):
    fake_process("pass\n")
    media = tmp_path / "media.mp4"
    media.write_bytes(b"fake")
    (tmp_path / "gate_result.json").write_text(json.dumps(asdict(REJECT)))
    result = runner.run_gate_process(media, tmp_path, settings=settings, timeout_seconds=10, on_tick=lambda: True)
    assert result.reason_code == "gate_error"


@pytest.mark.parametrize("value", [0, -1, float('inf'), float('nan')])
def test_invalid_gate_timeout_rejected(settings, value):
    with pytest.raises(ValueError):
        replace(settings, gate_timeout_seconds=value)
