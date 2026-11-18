"""작업 제한 정책(docs/DESIGN.md §15.3 2026-11-18): Gate가 끝나면 적합 구간 길이로 작업 전체 제한을 다시 정한다.

식: min(상한, 기본항 + 계수 × 적합 구간 초). 기본 180 + 20 × 초, 상한 1800.
Gate 전과 Gate가 구간 길이를 정하지 못했을 때(실패)는 기존 job_timeout_seconds(기본 600)를 쓴다.
"""
import time
from dataclasses import replace

import pytest

from server.axes import signal as signal_axis
from server.config import Settings
from server.gate.types import GateResult, MediaInfo, Segment, SegmentQuality
from server.jobs import worker
from tests.conftest import REGISTERED_ID

OWNER = "timeout-owner"
MEDIA = MediaInfo(300.0, 1920, 1080, 30.0, 0, True)
QUALITY = SegmentQuality(200.0, 0.185, 42.0, 1080, 10)


# ---------- 식 ----------

def test_defaults_match_decision():
    s = Settings()
    assert s.job_timeout_seconds == 600.0  # Gate 전·구간 길이를 모를 때의 값은 그대로
    assert (s.job_timeout_base_seconds, s.job_timeout_per_eligible_second, s.job_timeout_max_seconds) == (
        180.0, 20.0, 1800.0)


@pytest.mark.parametrize("eligible,expected", [
    (0.0, 180.0),      # 적합 구간 0초: 기본항만
    (2.5, 230.0),      # 짧음: 기존 600초보다 짧아진다
    (37.0, 920.0),     # A(37.0초)
    (81.0, 1800.0),    # 상한과 정확히 같다
    (120.0, 1800.0),   # 상한 초과 → 상한
])
def test_formula(eligible, expected):
    assert Settings().job_timeout_after_gate(eligible) == pytest.approx(expected)


def test_negative_eligible_is_treated_as_zero():
    assert Settings().job_timeout_after_gate(-5.0) == 180.0


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("TRINITY_JOB_TIMEOUT_BASE_SECONDS", "100")
    monkeypatch.setenv("TRINITY_JOB_TIMEOUT_PER_ELIGIBLE_SECOND", "12")
    monkeypatch.setenv("TRINITY_JOB_TIMEOUT_MAX_SECONDS", "900")
    s = Settings.from_env()
    assert s.job_timeout_after_gate(10.0) == 220.0
    assert s.job_timeout_after_gate(100.0) == 900.0


@pytest.mark.parametrize("field,value", [
    ("job_timeout_base_seconds", 0.0), ("job_timeout_base_seconds", float("nan")),
    ("job_timeout_max_seconds", -1.0), ("job_timeout_max_seconds", float("inf")),
    ("job_timeout_per_eligible_second", -0.1), ("job_timeout_per_eligible_second", float("nan")),
])
def test_invalid_settings_rejected(field, value):
    with pytest.raises(ValueError):
        Settings(**{field: value})


# ---------- Worker ----------

def run_job(queue, registry, settings):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    assert worker.run_once(queue, registry, settings, "timeout-worker")
    return queue.get(aid, OWNER)


def fake_gate(monkeypatch, result, delay=0.0):
    def gate_run(*args, **kwargs):
        time.sleep(delay)
        return result
    monkeypatch.setattr(worker, "run_gate_process", gate_run, raising=False)


def eligible(*bounds):
    return GateResult(MEDIA, None, eligible_segments=tuple(Segment(a, b, quality=QUALITY) for a, b in bounds))


def observe_axis_timeout(monkeypatch):
    seen = []
    def model(ctx):
        seen.append(ctx.timeout_seconds)
        return {"status": "completed", "reason_code": None, "raw_score": None, "raw_metrics": None}
    monkeypatch.setattr(signal_axis, "run", model)
    return seen


@pytest.mark.parametrize("bounds,limit", [
    (((1.0, 3.0), (5.0, 5.5)), 230.0),        # 짧음(2.5초): 600보다 짧아진다
    (((0.0, 30.0), (40.0, 47.0)), 920.0),     # 37초: 600보다 길어진다
    (((0.0, 150.0),), 1800.0),                # 상한 초과
])
def test_worker_resets_limit_after_gate(queue, registry, settings, monkeypatch, bounds, limit):
    fake_gate(monkeypatch, eligible(*bounds))
    seen = observe_axis_timeout(monkeypatch)
    job = run_job(queue, registry, settings)
    assert job.job_status == "finished"
    # 첫 축에 넘긴 남은 시간 = 새 제한 − 지금까지 걸린 시간
    assert limit - 5.0 < seen[0] <= limit


def test_new_limit_exceeded_fails_with_timeout(queue, registry, settings, monkeypatch):
    s = replace(settings, job_timeout_base_seconds=0.05, job_timeout_per_eligible_second=0.0)
    fake_gate(monkeypatch, eligible((0.0, 5.0)), delay=0.1)
    seen = observe_axis_timeout(monkeypatch)
    job = run_job(queue, registry, s)
    assert (job.job_status, job.failure_reason, job.result) == ("failed", "timeout", None)
    assert seen == []


def test_zero_eligible_uses_formula_and_finishes(queue, registry, settings, monkeypatch):
    # 기존 제한(0.2초)은 Gate(0.3초) 중에 지나지만, Gate가 끝나면 180초로 다시 정해져 보류 결과로 끝난다
    s = replace(settings, job_timeout_seconds=0.2)
    gate = GateResult(MEDIA, "no_speech_detected",
                      excluded_segments=(Segment(0, 10, "no_speech_detected", QUALITY),))
    fake_gate(monkeypatch, gate, delay=0.3)
    job = run_job(queue, registry, s)
    assert job.job_status == "finished"
    assert job.result["reason_code"] == "no_speech_detected"


@pytest.mark.parametrize("reason", ["gate_error", "gate_timeout", "media_unreadable"])
def test_gate_failure_keeps_existing_limit(queue, registry, settings, monkeypatch, reason):
    # Gate가 구간 길이를 정하지 못하면 다시 정하지 않는다. 기존 제한(0.2초)이 지나 있어 마무리에서 timeout이 된다
    s = replace(settings, job_timeout_seconds=0.2)
    fake_gate(monkeypatch, GateResult(None if reason != "media_unreadable" else MEDIA, reason), delay=0.3)
    job = run_job(queue, registry, s)
    assert (job.job_status, job.failure_reason, job.result) == ("failed", "timeout", None)


def test_gate_failure_within_existing_limit_finishes(queue, registry, settings, monkeypatch):
    fake_gate(monkeypatch, GateResult(None, "gate_error"))
    job = run_job(queue, registry, settings)
    assert job.job_status == "finished"
    assert job.result["analysis_status"] == "analysis_unavailable"


def test_gate_bypass_keeps_existing_limit(queue, registry, settings, monkeypatch):
    # 개발 전용 수동 구간은 Gate를 돌리지 않으므로 기존 제한 그대로다
    s = replace(settings, dev_manual_segments=((0.0, 100.0),))
    seen = observe_axis_timeout(monkeypatch)
    job = run_job(queue, registry, s)
    assert job.job_status == "finished"
    assert 595.0 < seen[0] <= 600.0
