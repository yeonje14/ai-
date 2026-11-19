"""각 축이 실행기의 device_used를 API 결과가 아닌 내부 문맥(AxisContext.device_used)으로 넘기는지."""
import ast
from dataclasses import replace
from pathlib import Path

import pytest

from server.axes import AxisContext, alignment, physics, signal as signal_axis
from server.axes.alignment import syncnet
from server.axes.device import clean_device
from server.axes.physics import motionphys
from server.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
SEGMENTS = ((0.0, 3.0),)


def ctx_for(tmp_path, **kw):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"x")
    return AxisContext(job_dir=tmp_path, settings=kw.pop("settings", Settings()), media_path=media,
                       segments=kw.pop("segments", SEGMENTS), heartbeat=lambda: True, **kw)


def waverep_out(device):
    return {"status": "completed", "reason_code": None, "raw_score": None,
            "raw_metrics": {"frame_logit": {"frames": 2, "mean": 1.0, "median": 1.0, "min": 0.5, "max": 1.5, "stdev": 0.5}},
            "frames": [{"logit": 0.5}, {"logit": 1.5}], "model_version": "w", "model": {"device_used": device},
            "video": None, "timing": {"total_sec": 1.0}}


def motion_raw(device):
    ok = {"status": "completed", "reason_code": None,
          "valid_trajectories": {"8": 40, "12": 20, "24": 10}, "moving_trajectories": {"8": 40, "12": 20, "24": 10},
          "tracking_success_rate": {"8": 0.9, "12": 0.9, "24": 0.9}, "face_detection_rate": None, "timing_sec": 0.1}
    raw = {"schema_version": 1, "variants": {"full": dict(ok), "face_roi": dict(ok), "face_motion": dict(ok, face_detection_rate=1.0)}}
    if device is not ...:
        raw["device_used"] = device
    return raw


def test_clean_device_accepts_only_known_names():
    for name in ("cpu", "mps", "gpu"):
        assert clean_device(name) == name
    for bad in ("cuda", "/tmp/x", "MPS", "mps ", "", 1, None, ["cpu"]):
        assert clean_device(bad) is None


def test_signal_axis_sets_device_from_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(signal_axis, "run_waverep", lambda *a, **k: waverep_out("mps"))
    ctx = ctx_for(tmp_path)
    signal_axis.run(ctx)
    assert ctx.device_used == "mps"
    monkeypatch.setattr(signal_axis, "run_waverep", lambda *a, **k: waverep_out("cuda"))
    ctx = ctx_for(tmp_path)
    signal_axis.run(ctx)
    assert ctx.device_used is None


def test_alignment_axis_sets_device_from_runner(tmp_path, monkeypatch):
    for reported, expected in (("cpu", "cpu"), ("mps", "mps"), ("cuda", None), (None, None)):
        monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, _d=reported, **k: {
            "status": "completed", "reason_code": None, "segments": [], "device_used": _d})
        ctx = ctx_for(tmp_path)
        alignment.run(ctx)
        assert ctx.device_used == expected


def test_physics_axis_sets_device_from_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(motionphys, "run_motionphys", lambda *a, **k: motionphys.parse_result(motion_raw("cpu")))
    ctx = ctx_for(tmp_path)
    physics.run(ctx)
    assert ctx.device_used == "cpu"


def test_axes_without_runner_leave_device_none(tmp_path, monkeypatch):
    for module in (signal_axis, physics, alignment):
        ctx = ctx_for(tmp_path, segments=())
        module.run(ctx)
        assert ctx.device_used is None
    monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, **k: pytest.fail("실행하면 안 된다"))
    ctx = ctx_for(tmp_path, settings=replace(Settings(), dev_manual_segments=((0.0, 3.0),)))
    alignment.run(ctx)
    assert ctx.device_used is None


def test_motionphys_parse_passes_only_clean_device():
    assert motionphys.parse_result(motion_raw("cpu"))["device_used"] == "cpu"
    assert motionphys.parse_result(motion_raw("x"))["device_used"] is None
    assert motionphys.parse_result(motion_raw(...))["device_used"] is None
    assert motionphys.failure("error", "timeout")["device_used"] is None


def _calls(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Attribute) and n.func.attr == name) or (isinstance(n.func, ast.Name) and n.func.id == name))]


def test_motionphys_runner_reports_cpu_and_mediapipe_uses_default_delegate():
    # MediaPipe는 delegate가 없으면 CPU를 쓴다(mediapipe 1.2.3 base_options.py). 누가 delegate를 지정하면
    # 실행기의 "cpu" 보고가 거짓이 되므로 이 테스트가 깨져야 한다.
    research = REPO_ROOT / "research/motionphys"
    options = [c for f in sorted(research.glob("*.py")) for c in _calls(ast.parse(f.read_text(encoding="utf-8")), "BaseOptions")]
    assert options, "BaseOptions 호출을 찾지 못했다"
    assert all(kw.arg != "delegate" for c in options for kw in c.keywords)
    tree = ast.parse((research / "infer_axis.py").read_text(encoding="utf-8"))
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run")
    reported = [(k.value, v.value) for d in ast.walk(run) if isinstance(d, ast.Dict)
                for k, v in zip(d.keys, d.values) if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)]
    assert ("device_used", "cpu") in reported


def test_axis_api_payload_has_no_device_key(tmp_path, monkeypatch):
    monkeypatch.setattr(signal_axis, "run_waverep", lambda *a, **k: waverep_out("mps"))
    monkeypatch.setattr(motionphys, "run_motionphys", lambda *a, **k: motionphys.parse_result(motion_raw("cpu")))
    monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, **k: {
        "status": "completed", "reason_code": None, "segments": [], "device_used": "mps"})
    for module in (signal_axis, physics, alignment):
        out = module.run(ctx_for(tmp_path))
        assert "device_used" not in out
