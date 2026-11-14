"""Gate → Worker: 원인별 상태·구간 전달·실패 격리. 모델 대신 외부 실행 경계만 대체한다."""
from dataclasses import replace

import pytest

from server.axes import signal as signal_axis
from server.gate.types import GateResult, MediaInfo, Segment, SegmentQuality
from server.jobs import worker
from tests.conftest import REGISTERED_ID

OWNER = "gate-owner"
MEDIA = MediaInfo(10.0, 1920, 1080, 30.0, 0, True)
QUALITY = SegmentQuality(200.0, 0.185, 42.0, 1080, 10)

# 기대값은 승인된 표에서 직접 적는다. 운영 코드의 대응표를 가져오지 않는다.
CASES = [
    ("audio_missing", "out_of_scope", "not_applicable"),
    ("no_speech_detected", "out_of_scope", "not_applicable"),
    ("no_mouth_movement", "out_of_scope", "not_applicable"),
    ("no_face_detected", "out_of_scope", "not_applicable"),
    ("speaker_unconfirmed", "unsupported", "abstained"),
    ("low_resolution", "insufficient_quality", "abstained"),
    ("face_too_small", "insufficient_quality", "abstained"),
    ("too_blurry", "insufficient_quality", "abstained"),
    ("segment_too_short", "insufficient_quality", "abstained"),
    ("media_unreadable", "analysis_unavailable", "abstained"),
    ("gate_error", "analysis_unavailable", "abstained"),
    ("gate_timeout", "analysis_unavailable", "abstained"),
]


def run_job(queue, registry, settings):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    assert worker.run_once(queue, registry, settings, "gate-worker")
    return aid, queue.get(aid, OWNER)


def fake_gate(monkeypatch, result):
    # Gate는 미디어를 읽고 별도 프로세스를 돌린다. 이 경계만 가짜 결과로 대체한다.
    monkeypatch.setattr(worker, "run_gate_process", lambda *a, **kw: result, raising=False)


@pytest.mark.parametrize("reason,analysis,verdict", CASES)
def test_gate_reason_maps_status_and_prevents_model(queue, registry, settings, monkeypatch,
                                                   reason, analysis, verdict):
    gate = GateResult(MEDIA, reason, excluded_segments=(Segment(0, 10, reason, QUALITY),))
    fake_gate(monkeypatch, gate)
    calls = []
    monkeypatch.setattr(signal_axis, "run", lambda ctx: calls.append(ctx))
    aid, job = run_job(queue, registry, settings)
    assert calls == []
    assert job.job_status == "finished"
    r = job.result
    assert (r["analysis_status"], r["verdict_status"]) == (analysis, verdict)
    assert r["reason_code"] == reason
    assert r["gate_bypassed"] is False
    assert r["overall_score"] is None and r["verdict_label"] is None
    assert r["axes"]["signal"]["raw_score"] is None
    assert r["axes"]["signal"]["raw_metrics"] is None
    assert r["axes"]["physics"]["raw_score"] is None
    assert r["axes"]["alignment"]["lse_c"] is None
    assert r["axes"]["alignment"]["lse_d"] is None
    assert r["coverage"]["eligible_duration_sec"] == 0
    assert r["coverage"]["analyzed_duration_sec"] is None
    assert r["coverage"]["analyzed_segments"] == []
    assert "waverep" not in job.completed_stages
    assert any(e["reason_code"] == reason for e in r["explanations"])
    assert not (settings.runtime_dir / aid).exists()


@pytest.mark.parametrize("status", ["completed", "error"])
def test_gate_segments_reach_waverep_and_coverage_counts_only_success(
        queue, registry, settings, monkeypatch, status):
    gate = GateResult(MEDIA, None, eligible_segments=(Segment(1, 3, quality=QUALITY),
                                                     Segment(5, 8, quality=QUALITY)),
                      excluded_segments=(Segment(3, 5, "too_blurry", QUALITY),))
    received = []
    def gate_run(media, work_dir, **kwargs):
        assert media.parent == work_dir
        assert media.read_bytes() == registry.resolve(REGISTERED_ID).local_path.read_bytes()
        return gate
    monkeypatch.setattr(worker, "run_gate_process", gate_run, raising=False)
    def model(ctx):
        received.append(ctx.segments)
        ctx.media_info.update(fps=30.0, frame_count=300)
        return {"status": status, "reason_code": None if status == "completed" else "inference_error",
                "raw_score": None, "raw_metrics": None}
    monkeypatch.setattr(signal_axis, "run", model)
    _, job = run_job(queue, registry, settings)
    assert received == [((1, 3), (5, 8))]
    r = job.result
    assert (r["analysis_status"], r["verdict_status"]) == ("partial", "abstained")
    assert r["overall_score"] is None and r["axes"]["signal"]["raw_score"] is None
    c = r["coverage"]
    assert (c["video_duration_sec"], c["eligible_duration_sec"]) == (10, 5)
    if status == "completed":
        assert (c["analyzed_duration_sec"], c["full_video_coverage"], c["eligible_coverage"]) == (5, .5, 1)
        assert c["analyzed_segments"] == [{"start_sec": 1, "end_sec": 3}, {"start_sec": 5, "end_sec": 8}]
    else:
        assert c["analyzed_duration_sec"] is None and c["full_video_coverage"] is None
        assert c["eligible_coverage"] is None and c["analyzed_segments"] == []
    excluded = [e for e in r["explanations"] if e["template_id"] == "GATE_EXCLUDED_SEGMENT"]
    assert excluded[0]["reason_code"] == "too_blurry"
    assert "3" in excluded[0]["message"] and "5" in excluded[0]["message"]
    eligible = [e for e in r["explanations"] if e["template_id"] == "GATE_ELIGIBLE_SEGMENT"]
    assert len(eligible) == 2
    assert "200" in eligible[0]["message"] and "42" in eligible[0]["message"]


def test_manual_segments_alone_bypass_gate(queue, registry, settings, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "run_gate_process", lambda *a, **kw: calls.append(True), raising=False)
    monkeypatch.setattr(signal_axis, "run", lambda ctx: {"status": "completed", "raw_score": None})
    _, job = run_job(queue, registry, replace(settings, dev_manual_segments=((0, 2),)))
    assert calls == []
    assert job.result["gate_bypassed"] is True
    assert job.result["coverage"]["eligible_duration_sec"] is None
    assert (job.result["analysis_status"], job.result["verdict_status"]) == ("partial", "abstained")


def test_unexpected_gate_exception_is_isolated(queue, registry, settings, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("private media information")
    monkeypatch.setattr(worker, "run_gate_process", broken, raising=False)
    _, job = run_job(queue, registry, settings)
    assert job.job_status == "finished"
    assert job.result["reason_code"] == "gate_error"
    assert "private media" not in str(job.result)
