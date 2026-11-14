"""백로그 7번: Worker의 signal 축에 WaveRep 어댑터를 연결한 부분.

trinity 환경에는 torch가 없다. 추론 프로세스는 가짜 스크립트로 대신한다.
실제 추론은 서버와 Worker를 띄워 따로 확인한다(docs/HANDOFF.md).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from server.axes import AxisContext, signal as signal_axis
from server.axes.signal import waverep
from server.axes.signal.waverep import WaveRepConfig, run_waverep
from server.config import Settings, parse_manual_segments
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.jobs import worker
from server.jobs.queue import LEASE_CANCEL, LEASE_LOST, LEASE_OK
from server.schemas import AnalysisResult
from tests.conftest import REGISTERED_ID, REGISTERED_NO_MEDIA_ID

OWNER = "owner-hash"

FAKE_HEAD = """
import argparse, json, sys, time
p = argparse.ArgumentParser()
p.add_argument("--request"); p.add_argument("--output")
o = p.parse_args()
req = json.load(open(o.request))
"""

# 30fps 300프레임(10초) 영상에서 프레임 4장을 계산한 것처럼 답한다.
OK_BODY = """
frames = [{"index": i * 15, "time_sec": i / 2, "logit": float(i) - 1.5} for i in range(4)]
json.dump({"status": "completed", "reason_code": None, "frames": frames,
           "video": {"fps": 30.0, "frame_count": 300, "width": 1920, "height": 1080},
           "timing": {"total_sec": 0.1}, "model": {"device_used": "cpu"}}, open(o.output, "w"))
"""


@pytest.fixture
def fake_model(tmp_path, monkeypatch):
    """signal 축이 가짜 추론 스크립트를 쓰게 한다. 스크립트가 받은 요청은 seen.json에 남는다."""
    weights = tmp_path / "w.ckpt"
    weights.write_bytes(b"w")
    seen = tmp_path / "seen.json"
    real_build = signal_axis.build_config

    def use(body: str) -> Path:
        script = tmp_path / "fake_infer.py"
        script.write_text(
            FAKE_HEAD + f"json.dump(req, open({str(seen)!r}, 'w'))\n" + body, encoding="utf-8"
        )

        def _build(ctx: AxisContext) -> WaveRepConfig:
            return replace(real_build(ctx), python=Path(sys.executable), script=script, weights=weights)

        monkeypatch.setattr(signal_axis, "build_config", _build)
        return seen

    return use


def _manual(settings: Settings, **overrides) -> Settings:
    return replace(settings, dev_manual_segments=((0.0, 2.0),), **overrides)


def _run(queue, registry, settings, video_id=REGISTERED_ID):
    aid = queue.enqueue(video_id, OWNER, 3)
    assert worker.run_once(queue, registry, settings, "w1") is True
    return aid, queue.get(aid, OWNER)


# ---------- 설정 ----------

def test_defaults_are_mps_batch_1_two_fps_and_gate_bypass_off():
    s = Settings()
    assert (s.waverep_device, s.waverep_batch_size, s.waverep_sample_fps) == ("mps", 1, 2.0)
    assert s.dev_manual_segments == ()
    assert Settings.from_env().dev_manual_segments == ()


def test_manual_segments_parse(monkeypatch):
    assert parse_manual_segments("") == ()
    assert parse_manual_segments("0-10, 12.5-20") == ((0.0, 10.0), (12.5, 20.0))
    monkeypatch.setenv("TRINITY_DEV_MANUAL_SEGMENTS", "1-3")
    assert Settings.from_env().dev_manual_segments == ((1.0, 3.0),)


@pytest.mark.parametrize("text", ["5", "3-1", "2-2", "-1-2", "a-b", "0-inf", "0-nan", "1-2-3", "0:10"])
def test_manual_segments_reject_bad_input(text):
    with pytest.raises(ValueError):
        parse_manual_segments(text)


def test_heartbeat_interval_must_be_shorter_than_lease():
    with pytest.raises(ValueError):
        Settings(lease_seconds=5, heartbeat_interval_seconds=5)


def test_build_config_uses_settings_and_caps_timeout(tmp_path):
    ctx = AxisContext(job_dir=tmp_path, settings=Settings(waverep_timeout_seconds=300), timeout_seconds=42.0)
    cfg = signal_axis.build_config(ctx)
    assert (cfg.device, cfg.batch_size, cfg.sample_fps, cfg.pretrained) == ("mps", 1, 2.0, False)
    assert cfg.timeout_sec == 42.0


# ---------- 허가 미디어 파일 ----------

def test_registered_without_media_file_is_unavailable(queue, registry, settings, monkeypatch):
    monkeypatch.setattr(signal_axis, "run", lambda ctx: pytest.fail("모델을 실행하면 안 된다"))
    _, job = _run(queue, registry, _manual(settings), REGISTERED_NO_MEDIA_ID)
    r = job.result
    assert job.job_status == "finished"
    assert (r["analysis_status"], r["verdict_status"]) == ("analysis_unavailable", "abstained")
    assert r["reason_code"] == r["abstention_reason"] == "video_access_unavailable"
    assert r["overall_score"] is None and r["verdict_label"] is None
    assert r["axes"]["signal"]["raw_score"] is None and r["axes"]["alignment"]["lse_c"] is None
    assert r["explanations"][0]["template_id"] == "VIDEO_ACCESS_UNAVAILABLE"


def test_registered_media_file_missing_on_disk_is_unavailable(queue, registry, settings):
    registry.resolve(REGISTERED_ID).local_path.unlink()
    _, job = _run(queue, registry, _manual(settings))
    assert job.result["analysis_status"] == "analysis_unavailable"
    assert job.result["reason_code"] == "video_access_unavailable"


@pytest.mark.parametrize("local_path", ["/etc/hosts", "../outside.mp4", "a/../../outside.mp4", "", 3])
def test_registry_rejects_paths_outside_media_root(tmp_path, local_path):
    root = tmp_path / "media"
    root.mkdir()
    cfg = tmp_path / "reg.json"
    cfg.write_text(json.dumps({"authorized_media": [
        {"youtube_video_id": REGISTERED_ID, "local_path": local_path}]}))
    with pytest.raises(ValueError):
        AuthorizedMediaRegistry.from_file(cfg, root)
    with pytest.raises(ValueError):
        AuthorizedMediaRegistry.from_file(cfg)  # 미디어 루트 없이 local_path를 쓸 수 없다


def test_registry_rejects_symlink_escaping_media_root(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    (root / "link.mp4").symlink_to(outside)
    cfg = tmp_path / "reg.json"
    cfg.write_text(json.dumps({"authorized_media": [
        {"youtube_video_id": REGISTERED_ID, "local_path": "link.mp4"}]}))
    with pytest.raises(ValueError):
        AuthorizedMediaRegistry.from_file(cfg, root)


# ---------- 수동 구간 꺼짐(기본) ----------

def test_without_segments_model_is_not_run(queue, registry, settings, monkeypatch):
    monkeypatch.setattr(signal_axis, "run_waverep", lambda *a, **k: pytest.fail("실행하면 안 된다"))
    aid, job = _run(queue, registry, settings)
    r = job.result
    assert r["gate_bypassed"] is False
    assert (r["analysis_status"], r["verdict_status"]) == ("partial", "abstained")
    sig = r["axes"]["signal"]
    assert (sig["status"], sig["reason_code"]) == ("insufficient_input", "gate_not_connected")
    assert sig["raw_score"] is None and sig["raw_metrics"] is None
    assert sig["model_version"] != "stub"
    assert r["coverage"]["analyzed_segments"] == [] and r["coverage"]["analyzed_duration_sec"] is None
    assert not (settings.runtime_dir / aid).exists()


# ---------- 수동 구간 켬 ----------

def test_manual_segments_run_model_and_mark_gate_bypassed(queue, registry, settings, fake_model):
    seen = fake_model(OK_BODY)
    aid, job = _run(queue, registry, _manual(settings))
    r = job.result
    assert job.job_status == "finished" and job.completed_stages[-1] == "finalizing"
    assert r["gate_bypassed"] is True
    assert (r["analysis_status"], r["verdict_status"]) == ("partial", "abstained")
    assert r["overall_score"] is None and r["verdict_label"] is None
    assert r["explanations"][-1]["reason_code"] == "gate_bypassed"

    sig = r["axes"]["signal"]
    assert sig["status"] == "completed" and sig["reason_code"] is None
    assert sig["raw_score"] is None  # 집계·판정하지 않는다
    assert sig["raw_metrics"] == {"frame_logit": {
        "frames": 4, "mean": 0.0, "median": 0.0, "min": -1.5, "max": 1.5,
        "stdev": pytest.approx(1.118034, abs=1e-6),
    }}
    # 프레임 logit 요약만 남긴다. 프레임별 값·시간·stderr는 결과에 없다.
    assert set(sig) == {"status", "reason_code", "raw_score", "raw_metrics", "model_version"}
    assert r["axes"]["physics"]["raw_score"] is None

    assert r["coverage"] == {
        "video_duration_sec": 10.0, "eligible_duration_sec": None, "analyzed_duration_sec": 2.0,
        "full_video_coverage": 0.2, "eligible_coverage": None,
        "analyzed_segments": [{"start_sec": 0.0, "end_sec": 2.0}],
    }

    # 모델 프로세스에는 서버가 발급한 작업 폴더 안의 경로만 넘어갔고, 끝난 뒤 폴더는 지워졌다.
    req = json.loads(seen.read_text())
    job_dir = (settings.runtime_dir / aid).resolve()
    assert Path(req["video"]).parent == job_dir
    assert (req["device"], req["batch_size"], req["sample_fps"], req["pretrained"]) == ("mps", 1, 2.0, False)
    assert req["segments"] == [[0.0, 2.0]]
    assert not job_dir.exists()
    assert registry.resolve(REGISTERED_ID).local_path.is_file()  # 원본 허가 미디어는 그대로다


def test_all_axes_completed_is_still_partial_when_gate_bypassed():
    job = worker.Job("a", REGISTERED_ID, "processing", None, [], None, None, 1)
    axes = {
        "signal": {"status": "completed", "raw_score": None},
        "physics": {"status": "completed", "raw_score": None},
        "alignment": {"status": "completed", "lse_c": None, "lse_d": None, "included_in_fusion": False},
    }
    fused = {"overall_score": 0.9, "verdict_status": "assessed", "abstention_reason": None}
    r = worker.build_result(job, "p", axes, fused, gate_bypassed=True)
    assert (r["analysis_status"], r["verdict_status"], r["overall_score"]) == ("partial", "abstained", None)
    assert worker.build_result(job, "p", axes, fused)["analysis_status"] == "completed"


def test_schema_refuses_assessed_result_with_gate_bypassed():
    base = dict(analysis_id="a", youtube_video_id=REGISTERED_ID, job_status="finished", gate_bypassed=True)
    AnalysisResult(**base, analysis_status="partial", verdict_status="abstained")
    for bad in (
        dict(analysis_status="completed", verdict_status="abstained"),
        dict(analysis_status="partial", verdict_status="assessed"),
        dict(analysis_status="partial", verdict_status="abstained", overall_score=0.5),
    ):
        with pytest.raises(ValueError):
            AnalysisResult(**base, **bad)


# ---------- 실패·타임아웃 격리 ----------

def test_model_crash_is_isolated_with_null_score(queue, registry, settings, fake_model):
    fake_model("raise RuntimeError('boom')\n")
    _, job = _run(queue, registry, _manual(settings))
    r = job.result
    sig = r["axes"]["signal"]
    assert job.job_status == "finished"
    assert (sig["status"], sig["reason_code"]) == ("error", "inference_error")
    assert sig["raw_score"] is None and sig["raw_metrics"] is None
    assert "boom" not in json.dumps(r)  # stderr는 결과에 넣지 않는다
    assert r["axes"]["physics"]["status"] == "insufficient_input"  # 나머지 축은 계속 처리됐다
    assert r["gate_bypassed"] is True and r["overall_score"] is None
    assert r["coverage"]["analyzed_segments"] == []


def test_axis_timeout_is_isolated_and_job_still_finishes(queue, registry, settings, fake_model):
    fake_model("time.sleep(60)\n")
    t0 = time.monotonic()
    _, job = _run(queue, registry, _manual(settings, waverep_timeout_seconds=1.0))
    assert time.monotonic() - t0 < 15
    sig = job.result["axes"]["signal"]
    assert job.job_status == "finished"
    assert (sig["status"], sig["reason_code"], sig["raw_score"]) == ("error", "timeout", None)
    assert job.completed_stages[-1] == "finalizing"


def test_job_timeout_during_inference_fails_job_without_result(queue, registry, settings, fake_model):
    fake_model("time.sleep(60)\n")
    s = _manual(settings, job_timeout_seconds=1.0, lease_seconds=5.0, heartbeat_interval_seconds=0.2)
    t0 = time.monotonic()
    aid, job = _run(queue, registry, s)
    assert time.monotonic() - t0 < 15
    assert (job.job_status, job.failure_reason, job.result) == ("failed", "timeout", None)
    assert not (settings.runtime_dir / aid).exists()


# ---------- heartbeat ----------

def test_queue_heartbeat_extends_lease_without_touching_stage(queue):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    queue.claim("w1", 30, 2)
    queue.advance_stage(aid, "w1", "waverep", ["validating"], 30)

    def expires():
        conn = sqlite3.connect(queue.db_path)
        try:
            return conn.execute(
                "SELECT lease_expires_at FROM jobs WHERE analysis_id = ?", (aid,)).fetchone()[0]
        finally:
            conn.close()

    before = expires()
    assert queue.heartbeat(aid, "w1", 600) == LEASE_OK
    assert expires() > before + 500
    job = queue.get(aid, OWNER)
    assert (job.stage, job.completed_stages) == ("waverep", ["validating"])

    assert queue.heartbeat(aid, "other", 600) == LEASE_LOST
    queue.request_cancel(aid, OWNER)
    assert queue.heartbeat(aid, "w1", 600) == LEASE_CANCEL
    queue.mark_cancelled(aid, "w1")
    assert queue.heartbeat(aid, "w1", 600) == LEASE_LOST  # 끝난 작업의 lease는 연장하지 않는다


def test_lease_is_extended_while_inference_runs_longer_than_lease(queue, registry, settings, fake_model, monkeypatch):
    fake_model("time.sleep(2.5)\n" + OK_BODY)
    beats = []
    real = queue.heartbeat

    def counting(*a, **k):
        # 다른 Worker가 선점을 시도해도 lease가 살아 있어 가져가지 못한다.
        assert queue.claim("w2", 1.0, 2) is None
        beats.append(time.monotonic())
        return real(*a, **k)

    monkeypatch.setattr(queue, "heartbeat", counting)
    s = _manual(settings, lease_seconds=1.0, heartbeat_interval_seconds=0.2)
    _, job = _run(queue, registry, s)
    assert job.job_status == "finished" and job.attempts == 1
    assert job.result["axes"]["signal"]["status"] == "completed"
    assert len(beats) >= 5


def test_cancel_during_inference_kills_model_and_cancels_job(queue, registry, settings, fake_model, monkeypatch):
    fake_model("time.sleep(60)\n")
    real = queue.heartbeat
    aid_box = []

    def cancel_then_beat(analysis_id, *a, **k):
        queue.request_cancel(analysis_id, OWNER)
        aid_box.append(analysis_id)
        return real(analysis_id, *a, **k)

    monkeypatch.setattr(queue, "heartbeat", cancel_then_beat)
    t0 = time.monotonic()
    aid, job = _run(queue, registry, _manual(settings, heartbeat_interval_seconds=0.2))
    assert time.monotonic() - t0 < 15
    assert aid_box and (job.job_status, job.result) == ("cancelled", None)
    assert not (settings.runtime_dir / aid).exists()


def test_lost_lease_during_inference_abandons_job_without_writing(queue, registry, settings, fake_model, monkeypatch):
    fake_model("time.sleep(60)\n")
    real = queue.heartbeat

    def steal_then_beat(analysis_id, *a, **k):
        conn = sqlite3.connect(queue.db_path)
        conn.execute("UPDATE jobs SET lease_owner = 'w2' WHERE analysis_id = ?", (analysis_id,))
        conn.commit()
        conn.close()
        return real(analysis_id, *a, **k)

    monkeypatch.setattr(queue, "heartbeat", steal_then_beat)
    t0 = time.monotonic()
    aid, job = _run(queue, registry, _manual(settings, heartbeat_interval_seconds=0.2))
    assert time.monotonic() - t0 < 15
    # 다른 Worker의 작업이 됐다. 이 Worker는 결과도 실패도 쓰지 않는다.
    assert (job.job_status, job.result, job.failure_reason) == ("processing", None, None)
    assert not (settings.runtime_dir / aid).exists()


# ---------- 어댑터의 on_tick ----------

@pytest.fixture
def adapter(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    weights = tmp_path / "w.ckpt"
    weights.write_bytes(b"w")
    work = tmp_path / "work"
    work.mkdir()

    def make(body: str, **overrides) -> WaveRepConfig:
        script = tmp_path / "fake.py"
        script.write_text(FAKE_HEAD + body, encoding="utf-8")
        return replace(
            WaveRepConfig(python=Path(sys.executable), script=script, weights=weights, timeout_sec=20),
            **overrides,
        )

    return make, video, work


def test_on_tick_is_called_periodically_and_result_is_kept(adapter):
    make, video, work = adapter
    ticks = []
    out = run_waverep(video, [(0.0, 1.0)], work, make("time.sleep(1.0)\n" + OK_BODY),
                      on_tick=lambda: ticks.append(1) or True, tick_sec=0.2)
    assert out["status"] == "completed" and len(ticks) >= 2


def test_on_tick_false_aborts_and_kills_process(adapter, tmp_path):
    make, video, work = adapter
    pid_file = tmp_path / "pid"
    body = f"import os\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
    t0 = time.monotonic()
    out = run_waverep(video, [(0.0, 1.0)], work, make(body), on_tick=lambda: False, tick_sec=0.5)
    assert time.monotonic() - t0 < 10
    assert (out["status"], out["reason_code"]) == ("error", "aborted")
    assert out["raw_score"] is None and out["raw_metrics"] is None
    assert list(work.iterdir()) == []
    import os
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_on_tick_exception_aborts_instead_of_raising(adapter):
    make, video, work = adapter

    def boom():
        raise RuntimeError("heartbeat bug")

    out = run_waverep(video, [(0.0, 1.0)], work, make("time.sleep(60)\n"), on_tick=boom, tick_sec=0.2)
    assert (out["status"], out["reason_code"]) == ("error", waverep.ABORTED)


# ---------- coverage ----------

def test_coverage_unknown_values_are_null_not_zero():
    c = worker.build_coverage({}, ((0.0, 2.0),), True)
    assert c["video_duration_sec"] is None and c["analyzed_duration_sec"] is None
    c = worker.build_coverage({"fps": 30.0, "frame_count": 300}, ((0.0, 2.0),), False)
    assert c["video_duration_sec"] == 10.0
    assert c["analyzed_duration_sec"] is None and c["analyzed_segments"] == []


def test_coverage_clips_to_duration_and_merges_overlaps():
    c = worker.build_coverage(
        {"fps": 30.0, "frame_count": 300}, ((0.0, 2.0), (1.0, 3.0), (8.0, 20.0), (50.0, 60.0)), True
    )
    assert c["analyzed_segments"] == [{"start_sec": 0.0, "end_sec": 3.0}, {"start_sec": 8.0, "end_sec": 10.0}]
    assert c["analyzed_duration_sec"] == 5.0 and c["full_video_coverage"] == 0.5
    assert c["eligible_duration_sec"] is None and c["eligible_coverage"] is None
