"""서버(정합 축·결합 입력)와 학습(특징 추출)이 같은 SyncNet 기준을 쓰는지 (README §15.3 결정 2·8 보완, 2026-11-17).

같은 어댑터 결과를 서버의 alignment.run과 학습의 summarize_video에 넣어,
"축이 completed ⟺ SyncNet 특징이 있다"와 값이 같다는 것을 확인한다.
"""
from types import SimpleNamespace

import pytest

from server.axes import AxisContext, alignment
from server.axes.alignment import syncnet
from server.axes.alignment.report import parse_result
from training.datasets.manifest import Record
from training.features.extract import summarize_video

SEGS = [[0.0, 1.5], [2.0, 6.0], [7.0, 9.0], [10.0, 11.4]]


def row(seg, kind):
    start, end = seg
    if kind == "ok":
        return {"start_sec": start, "end_sec": end, "status": "completed",
                "tracks": [{"track_index": 0, "lse_c": 4.0 + start, "lse_d": 9.0 - start / 10, "offset_frames": -3}]}
    if kind == "short":
        return {"start_sec": start, "end_sec": end, "status": "insufficient_input", "reason_code": "segment_too_short"}
    if kind == "notrack":
        return {"start_sec": start, "end_sec": end, "status": "insufficient_input"}
    return {"start_sec": start, "end_sec": end, "status": "error"}


SCENARIOS = {
    "all_ok": (["ok", "ok", "ok", "ok"], "completed", None),
    "short_excluded": (["short", "ok", "ok", "short"], "completed", None),
    "all_short": (["short", "short", "short", "short"], "insufficient_input", "segment_too_short"),
    "short_and_notrack": (["short", "ok", "notrack", "short"], "insufficient_input", "tracking_failed"),
    "short_and_error": (["short", "ok", "error", "ok"], "error", "inference_error"),
    "notrack_without_short": (["ok", "ok", "notrack", "ok"], "insufficient_input", "tracking_failed"),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_server_and_training_use_the_same_syncnet_rule(name, tmp_path, monkeypatch, settings):
    kinds, status, reason = SCENARIOS[name]
    raw = parse_result({"schema_version": 1, "segments": [row(s, k) for s, k in zip(SEGS, kinds)]}, SEGS)
    monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, **k: raw)
    ctx = AxisContext(job_dir=tmp_path, settings=settings, media_path=tmp_path / "m.mp4",
                      segments=tuple(tuple(s) for s in SEGS), bundle=SimpleNamespace())
    server = alignment.run(ctx)
    assert (server["status"], server["reason_code"]) == (status, reason)
    assert server["lse_c"] is None and server["included_in_fusion"] is False  # API 값은 결정 5·8 보완을 따른다

    rec = Record("synth", "v", "v.mp4", "real", source_recording_id="s")
    training = summarize_video(rec, {"syncnet": {"status": raw["status"], "reason_code": raw["reason_code"],
                                                 "segments": raw["segments"]}})["axes"]["syncnet"]
    assert training["status"] == server["status"]
    server_values = {k[2:]: v for k, v in ctx.fusion_inputs.items() if k.startswith("S.")}
    training_values = {k: training[k] for k in ("lse_c_median", "lse_d_median", "abs_offset_median")}
    if status == "completed":
        assert server_values == training_values and None not in training_values.values()
    else:
        # 일부 구간의 트랙이 있어도 completed가 아니면 양쪽 모두 값을 쓰지 않는다
        assert server_values == {} and set(training_values.values()) == {None}

    shorts = kinds.count("short")
    notes = [e for e in ctx.explanations if e["template_id"] == "SYNCNET_SHORT_SEGMENTS_EXCLUDED"]
    assert len(notes) == (1 if shorts else 0)
    if shorts:
        assert notes[0]["reason_code"] == "segment_too_short" and f"{shorts}개" in notes[0]["message"]
        assert ("남은 구간이 없어" in notes[0]["message"]) == (name == "all_short")


def test_short_segments_reach_the_api_only_as_status_and_explanation(queue, registry, settings, monkeypatch):
    from server.gate.types import GateResult, Segment
    from server.jobs import worker
    from server.schemas import AnalysisResult
    from tests.test_gate_worker import MEDIA, run_job
    raw = parse_result({"schema_version": 1, "segments": [row(s, k) for s, k in zip(SEGS, ["short", "ok", "ok", "short"])]}, SEGS)
    monkeypatch.setattr(worker, "run_gate_process", lambda *a, **k: GateResult(
        MEDIA, None, eligible_segments=tuple(Segment(*s) for s in SEGS)))
    monkeypatch.setattr(worker.signal_axis, "run", lambda ctx: {"status": "completed", "raw_score": None})
    monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, **k: raw)
    _, job = run_job(queue, registry, settings)
    r = job.result
    AnalysisResult.model_validate(r)
    assert r["axes"]["alignment"] == {"status": "completed", "reason_code": None, "lse_c": None, "lse_d": None,
                                      "included_in_fusion": False, "model_version": alignment.MODEL_VERSION}
    ids = [e["template_id"] for e in r["explanations"]]
    assert "SYNCNET_SHORT_SEGMENTS_EXCLUDED" in ids and "SYNCNET_UNAGGREGATED" in ids
    assert "segments" not in r["axes"]["alignment"]  # 구간별 값은 API에 나가지 않는다


def test_default_device_is_mps_in_settings_and_feature_version(settings):
    from server.config import Settings
    from training.features.extract import default_settings, feature_version
    assert Settings().syncnet_device == "mps" and syncnet.SyncNetConfig().device == "mps"
    assert feature_version(default_settings())["syncnet"]["device"] == "mps"
