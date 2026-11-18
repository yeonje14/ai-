"""Worker가 축마다 실행기 장치와 실행 시작·끝의 thermalState를 로그 한 줄과 내부 기록(run_info_json)에 남기는지."""
import json
import logging
import sqlite3
from dataclasses import replace

import pytest

from server.axes import alignment, physics, signal as signal_axis
from server.jobs import worker
from tests.conftest import REGISTERED_ID, TOKEN

OWNER = "owner-hash"
AXIS_NAMES = ("signal", "physics", "alignment")


def fake_axis(device, before=None):
    def run(ctx):
        if before:
            before(ctx)
        ctx.device_used = device
        return {"status": "insufficient_input", "reason_code": "no_segments", "raw_score": None}
    return run


def fake_alignment(device, before=None):
    def run(ctx):
        if before:
            before(ctx)
        ctx.device_used = device
        return {"status": "insufficient_input", "reason_code": "no_segments", "lse_c": None, "lse_d": None,
                "included_in_fusion": False}
    return run


@pytest.fixture
def axes(monkeypatch):
    def install(devices=("mps", "cpu", "mps"), before=None):
        before = before or {}
        monkeypatch.setattr(signal_axis, "run", fake_axis(devices[0], before.get("signal")))
        monkeypatch.setattr(physics, "run", fake_axis(devices[1], before.get("physics")))
        monkeypatch.setattr(alignment, "run", fake_alignment(devices[2], before.get("alignment")))
    return install


def probes(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr(worker, "thermal_state", lambda: next(it))


def run_job(queue, registry, settings):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    assert worker.run_once(queue, registry, replace(settings, dev_manual_segments=((0, 2),)), "w1") is True
    return aid


def axis_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "trinity.worker" and " axis " in r.getMessage()]


def record(queue, aid):
    with sqlite3.connect(queue.db_path) as conn:
        (raw,) = conn.execute("SELECT run_info_json FROM jobs WHERE analysis_id = ?", (aid,)).fetchone()
    return None if raw is None else json.loads(raw)


def test_logs_one_line_per_axis_with_device_and_thermal(queue, registry, settings, axes, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="trinity.worker")
    axes(("mps", "cpu", "mps"))
    probes(monkeypatch, ["nominal", "fair", "fair", "fair", "fair", "serious"])
    aid = run_job(queue, registry, settings)
    assert axis_lines(caplog) == [
        f"job {aid} axis signal device=mps thermal_start=nominal thermal_end=fair",
        f"job {aid} axis physics device=cpu thermal_start=fair thermal_end=fair",
        f"job {aid} axis alignment device=mps thermal_start=fair thermal_end=serious",
    ]


def test_unknown_when_probe_or_device_missing(queue, registry, settings, axes, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="trinity.worker")
    axes((None, None, None))
    probes(monkeypatch, [None] * 6)
    aid = run_job(queue, registry, settings)
    assert axis_lines(caplog) == [
        f"job {aid} axis {name} device=unknown thermal_start=unknown thermal_end=unknown" for name in AXIS_NAMES]


def test_device_is_reset_between_axes(queue, registry, settings, monkeypatch, caplog):
    # physics가 장치를 보고하지 않으면 앞 축(signal)의 값이 남지 않아야 한다
    caplog.set_level(logging.INFO, logger="trinity.worker")
    monkeypatch.setattr(signal_axis, "run", fake_axis("mps"))
    monkeypatch.setattr(physics, "run", lambda ctx: {"status": "insufficient_input", "reason_code": "no_segments",
                                                     "raw_score": None})
    monkeypatch.setattr(alignment, "run", fake_alignment("cpu"))
    aid = run_job(queue, registry, settings)
    assert axis_lines(caplog)[1] == f"job {aid} axis physics device=unknown thermal_start=unknown thermal_end=unknown"


def test_record_saved_after_each_axis_with_attempt(queue, registry, settings, axes, monkeypatch):
    seen = []

    def check(ctx):  # physics 실행 때는 signal 기록만 있어야 한다(축이 끝날 때마다 저장)
        seen.append(record(queue, aid_box[0]))

    aid_box = []
    real_enqueue = queue.enqueue
    monkeypatch.setattr(queue, "enqueue", lambda *a: aid_box.append(real_enqueue(*a)) or aid_box[0])
    axes(("mps", "cpu", "mps"), before={"physics": check})
    probes(monkeypatch, ["nominal", "fair", "fair", "fair", "fair", "serious"])
    aid = run_job(queue, registry, settings)
    signal_entry = {"device_used": "mps", "thermal_state_start": "nominal", "thermal_state_end": "fair"}
    assert seen == [{"attempts": [{"attempt": 1, "axes": {"signal": signal_entry}}]}]
    assert record(queue, aid) == {"attempts": [{"attempt": 1, "axes": {
        "signal": signal_entry,
        "physics": {"device_used": "cpu", "thermal_state_start": "fair", "thermal_state_end": "fair"},
        "alignment": {"device_used": "mps", "thermal_state_start": "fair", "thermal_state_end": "serious"},
    }}]}
    assert queue.get(aid, OWNER).job_status == "finished"


def test_cancel_during_axis_still_logs_and_records_that_axis(queue, registry, settings, axes, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="trinity.worker")
    aid_box = []
    real_enqueue = queue.enqueue
    monkeypatch.setattr(queue, "enqueue", lambda *a: aid_box.append(real_enqueue(*a)) or aid_box[0])

    def cancel(ctx):  # 실행기가 도는 동안 취소 요청 → heartbeat가 False를 돌려준다
        queue.request_cancel(aid_box[0], OWNER)
        assert ctx.heartbeat() is False

    axes(("mps", "cpu", "mps"), before={"alignment": cancel})
    aid = run_job(queue, registry, settings)
    assert queue.get(aid, OWNER).job_status == "cancelled"
    assert [line.split(" axis ")[1].split()[0] for line in axis_lines(caplog)] == list(AXIS_NAMES)
    assert set(record(queue, aid)["attempts"][0]["axes"]) == set(AXIS_NAMES)


def test_probe_or_record_failure_does_not_fail_job(queue, registry, settings, axes, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="trinity.worker")
    axes(("mps", "cpu", "mps"))

    def broken_probe():
        raise RuntimeError("probe broke")

    def broken_save(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(worker, "thermal_state", broken_probe)
    monkeypatch.setattr(queue, "save_run_info", broken_save)
    aid = run_job(queue, registry, settings)
    job = queue.get(aid, OWNER)
    assert job.job_status == "finished"
    assert job.result["axes"]["signal"]["status"] == "insufficient_input"
    assert axis_lines(caplog)[0] == f"job {aid} axis signal device=mps thermal_start=unknown thermal_end=unknown"


def test_log_line_has_no_url_or_token(queue, registry, settings, axes, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="trinity.worker")
    axes(("mps", "cpu", "mps"))
    probes(monkeypatch, ["nominal"] * 6)
    run_job(queue, registry, settings)
    lines = axis_lines(caplog)
    assert len(lines) == 3
    for line in lines:
        for secret in (TOKEN, "youtu", REGISTERED_ID, str(settings.authorized_media_root), str(settings.runtime_dir)):
            assert secret not in line
