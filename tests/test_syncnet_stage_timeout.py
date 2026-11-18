"""SyncNet 단계 제한(docs/DESIGN.md §15.3 2026-11-18 보완).

규칙: min(60 + 16 × 적합 구간 초, 남은 작업 시간 − 마무리 여유).
SyncNet이 느려져도 작업 전체는 finished로 끝나고 SyncNet 축만 error/timeout, 다른 축 결과는 남는다.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from server.axes import AxisContext, alignment
from server.axes.alignment import syncnet
from server.config import Settings
from server.gate.types import GateResult, Segment
from server.jobs import worker
from tests.test_gate_worker import MEDIA, run_job
from tests.test_syncnet_adapter import fake_config


def ctx_for(segments, remaining=None, **overrides):
    return AxisContext(job_dir=Path("/nonexistent"), settings=replace(Settings(), **overrides),
                       segments=segments, timeout_seconds=remaining)


# ---------- 규칙 ----------

def test_defaults():
    s = Settings()
    assert (s.syncnet_timeout_base_seconds, s.syncnet_timeout_per_eligible_second) == (60.0, 16.0)
    assert 0 < s.job_finalize_margin_seconds < s.job_timeout_base_seconds


@pytest.mark.parametrize("segments,expected", [
    (((1.0, 3.0), (5.0, 5.5)), 60 + 16 * 2.5),     # 짧음
    (((0.0, 30.0), (40.0, 47.0)), 60 + 16 * 37.0),  # 길음(A 37초: 652초, 기존 고정값 600초보다 길다)
    (((0.0, 150.0),), 60 + 16 * 150.0),             # 남은 시간 제한이 없으면 길이만큼
])
def test_length_rule_when_time_is_ample(segments, expected):
    assert alignment.stage_timeout(ctx_for(segments, remaining=10_000.0)) == pytest.approx(expected)
    assert alignment.stage_timeout(ctx_for(segments, remaining=None)) == pytest.approx(expected)


def test_remaining_time_minus_margin_caps_the_stage():
    margin = Settings().job_finalize_margin_seconds
    ctx = ctx_for(((0.0, 37.0),), remaining=300.0)
    assert alignment.stage_timeout(ctx) == pytest.approx(300.0 - margin)


def test_default_job_limit_leaves_room_for_syncnet_rule():
    # 작업 제한 식(180 + 20x)이 SyncNet 규칙(60 + 16x) + 마무리 여유보다 항상 크다(상한 전까지)
    s = Settings()
    for x in (0.0, 2.5, 24.9, 37.0, 81.0):
        assert s.job_timeout_after_gate(x) > 60 + 16 * x + s.job_finalize_margin_seconds


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("TRINITY_SYNCNET_TIMEOUT_BASE_SECONDS", "10")
    monkeypatch.setenv("TRINITY_SYNCNET_TIMEOUT_PER_ELIGIBLE_SECOND", "2")
    monkeypatch.setenv("TRINITY_JOB_FINALIZE_MARGIN_SECONDS", "7")
    s = Settings.from_env()
    ctx = AxisContext(job_dir=Path("/nonexistent"), settings=s, segments=((0.0, 5.0),), timeout_seconds=100.0)
    assert alignment.stage_timeout(ctx) == 20.0
    assert alignment.stage_timeout(replace(ctx, timeout_seconds=25.0)) == 18.0


@pytest.mark.parametrize("field,value", [
    ("syncnet_timeout_base_seconds", 0.0), ("syncnet_timeout_per_eligible_second", -1.0),
    ("job_finalize_margin_seconds", 0.0), ("job_finalize_margin_seconds", float("inf")),
])
def test_invalid_settings_rejected(field, value):
    with pytest.raises(ValueError):
        Settings(**{field: value})


def test_no_time_left_after_margin_skips_syncnet(tmp_path, monkeypatch):
    monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, **k: pytest.fail("must not start"))
    media = tmp_path / "media.mp4"
    media.write_bytes(b"x")
    ctx = AxisContext(job_dir=tmp_path, settings=Settings(), media_path=media, segments=((0.0, 5.0),),
                      timeout_seconds=Settings().job_finalize_margin_seconds - 0.1)
    out = alignment.run(ctx)
    assert (out["status"], out["reason_code"]) == ("error", "timeout")
    assert out["lse_c"] is None and out["lse_d"] is None and out["included_in_fusion"] is False


# ---------- Worker ----------

def slow_syncnet(monkeypatch, tmp_path):
    """실제 별도 프로세스로 도는 가짜 SyncNet. 단계 제한보다 오래 걸린다. 제한은 실제 규칙으로 정한다."""
    cfg = fake_config(tmp_path, "time.sleep(30); Path(a.output).write_text(json.dumps(out))")
    monkeypatch.setattr(alignment, "build_config", lambda ctx: replace(cfg, timeout_sec=alignment.stage_timeout(ctx)))


def other_axes(monkeypatch):
    monkeypatch.setattr(worker, "run_gate_process",
                        lambda *a, **k: GateResult(MEDIA, None, eligible_segments=(Segment(1, 3), Segment(5, 8))))
    monkeypatch.setattr(worker.signal_axis, "run", lambda ctx: {
        "status": "completed", "raw_score": None, "raw_metrics": {"frame_logit": {"frames": 2}}})
    monkeypatch.setattr(worker.physics, "run", lambda ctx: {
        "status": "completed", "reason_code": None, "raw_score": None, "model_version": "fake-physics"})


@pytest.mark.parametrize("by", ["remaining_time", "length_rule"])
def test_slow_syncnet_times_out_alone_and_job_finishes(queue, registry, settings, monkeypatch, tmp_path, by):
    slow_syncnet(monkeypatch, tmp_path)
    other_axes(monkeypatch)
    if by == "remaining_time":
        # 작업 제한(Gate 뒤 2초)이 SyncNet 길이 규칙(60 + 16 × 5초)보다 훨씬 짧다 → 남은 시간 − 여유로 멈춘다
        s = replace(settings, job_timeout_base_seconds=2.0, job_timeout_per_eligible_second=0.0,
                    job_finalize_margin_seconds=0.8, heartbeat_interval_seconds=0.1)
    else:
        # 작업 시간은 넉넉하고 SyncNet 길이 규칙(0.5 + 0.1 × 5초 = 1초)에서 멈춘다
        s = replace(settings, syncnet_timeout_base_seconds=0.5, syncnet_timeout_per_eligible_second=0.1,
                    heartbeat_interval_seconds=0.1)
    _, job = run_job(queue, registry, s)
    assert job.job_status == "finished"
    r = job.result
    assert (r["axes"]["alignment"]["status"], r["axes"]["alignment"]["reason_code"]) == ("error", "timeout")
    assert r["axes"]["alignment"]["lse_c"] is None and r["axes"]["alignment"]["lse_d"] is None
    # 다른 축 결과가 남는다
    assert r["axes"]["signal"]["status"] == "completed"
    assert r["axes"]["signal"]["raw_metrics"]["frame_logit"]["frames"] == 2
    assert r["axes"]["physics"]["status"] == "completed"
    assert r["analysis_status"] == "partial"
    assert r["overall_score"] is None
    assert "syncnet" in job.completed_stages and "finalizing" in job.completed_stages


def test_syncnet_started_with_no_time_left_ends_axis_only(queue, registry, settings, monkeypatch, tmp_path):
    # SyncNet 진입 때 남은 시간이 마무리 여유보다 짧으면 시작하지 않고 축만 timeout, 작업은 finished
    slow_syncnet(monkeypatch, tmp_path)
    other_axes(monkeypatch)
    s = replace(settings, job_timeout_base_seconds=1.0, job_timeout_per_eligible_second=0.0,
                job_finalize_margin_seconds=5.0)
    _, job = run_job(queue, registry, s)
    assert job.job_status == "finished"
    assert job.result["axes"]["alignment"]["reason_code"] == "timeout"
    assert job.result["axes"]["signal"]["status"] == "completed"
