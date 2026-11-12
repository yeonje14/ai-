"""WaveRep 어댑터: 프레임 샘플링, 명령 구성, 실패 격리, (가능하면) 실제 추론 1건.

trinity 환경에는 torch가 없다. 추론 프로세스는 가짜 스크립트로 대신하고,
실제 추론 테스트는 research/waverep/.venv·가중치·샘플 영상이 있을 때만 돈다.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from research.waverep import frame_sampling
from server.axes.signal import waverep
from server.axes.signal.waverep import WaveRepConfig, run_waverep

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = REPO_ROOT / "data" / "research" / "samples"


# ---------- 샘플링 (순수 함수) ----------

def test_all_frames_in_segment_is_half_open():
    # 30fps, [1.0, 2.0) → 프레임 30..59
    assert frame_sampling.select_frame_indices([(1.0, 2.0)], 30.0, 300) == list(range(30, 60))


@pytest.mark.parametrize("fps,expected", [
    (1, [0, 30, 60]),
    (2, [0, 15, 30, 45, 60, 75]),
    (4, [0, 7, 15, 22, 30, 37, 45, 52, 60, 67, 75, 82]),
])
def test_sampling_at_fixed_interval(fps, expected):
    assert frame_sampling.select_frame_indices([(0.0, 3.0)], 30.0, 300, fps) == expected


def test_sampling_starts_at_segment_start():
    assert frame_sampling.select_frame_indices([(0.5, 2.5)], 30.0, 300, 1) == [15, 45]


def test_overlapping_segments_do_not_duplicate_frames():
    got = frame_sampling.select_frame_indices([(0.0, 1.0), (0.5, 1.5)], 30.0, 300)
    assert got == list(range(0, 45))


def test_segment_past_video_end_is_clipped():
    assert frame_sampling.select_frame_indices([(9.0, 20.0)], 30.0, 300, 1) == [270]
    assert frame_sampling.select_frame_indices([(50.0, 60.0)], 30.0, 300) == []


def test_sample_fps_above_video_fps_gives_every_frame_once():
    assert frame_sampling.select_frame_indices([(0.0, 1.0)], 30.0, 300, 120) == list(range(30))


def test_sampled_frames_are_subset_of_all_frames():
    segs = [(0.3, 4.7), (6.0, 9.9)]
    every = set(frame_sampling.select_frame_indices(segs, 29.97, 313))
    for fps in (1, 2, 4):
        assert set(frame_sampling.select_frame_indices(segs, 29.97, 313, fps)) <= every


@pytest.mark.parametrize("segments", [[(1.0, 1.0)], [(2.0, 1.0)], [(-1.0, 1.0)], [(0.0, math.inf)], [(0.0,)], ["ab"]])
def test_invalid_segments_are_rejected(segments):
    with pytest.raises(ValueError):
        frame_sampling.select_frame_indices(segments, 30.0, 300)


@pytest.mark.parametrize("fps", [0, -1, math.nan, "2", True])
def test_invalid_sample_fps_is_rejected(fps):
    with pytest.raises(ValueError):
        frame_sampling.select_frame_indices([(0.0, 1.0)], 30.0, 300, fps)


# ---------- 명령 구성 ----------

def test_command_is_argument_list_with_only_work_paths(tmp_path):
    cfg = WaveRepConfig(python=Path("/venv/python"), script=Path("/r/infer_frames.py"))
    cmd = waverep.build_command(cfg, tmp_path / "a b" / "req.json", tmp_path / "out.json")
    assert cmd == [
        "/venv/python", "/r/infer_frames.py",
        "--request", str(tmp_path / "a b" / "req.json"),
        "--output", str(tmp_path / "out.json"),
    ]


def test_command_wraps_with_time_only_when_measuring(tmp_path):
    cfg = WaveRepConfig(measure_peak_footprint=True)
    assert waverep.build_command(cfg, tmp_path / "r", tmp_path / "o")[:2] == ["/usr/bin/time", "-l"]


def test_parse_peak_footprint_missing_is_none_not_zero():
    assert waverep.parse_peak_footprint("  3221225472  peak memory footprint\n") == 3221225472
    assert waverep.parse_peak_footprint("Traceback ...") is None


def test_summarize_logits_empty_is_none_not_zero():
    s = waverep.summarize_logits([])
    assert s["frames"] == 0 and s["mean"] is None and s["stdev"] is None
    s = waverep.summarize_logits([-2.0, 0.0, 2.0, 4.0])
    assert (s["frames"], s["mean"], s["median"], s["min"], s["max"]) == (4, 1.0, 1.0, -2.0, 4.0)


def test_adapter_module_does_not_import_torch():
    assert "torch" not in sys.modules


# ---------- 가짜 추론 프로세스로 어댑터 동작 확인 ----------

FAKE_HEAD = """
import argparse, json, sys, time
p = argparse.ArgumentParser()
p.add_argument("--request"); p.add_argument("--output")
o = p.parse_args()
req = json.load(open(o.request))
"""


@pytest.fixture
def fake(tmp_path):
    """가짜 추론 스크립트를 만들고, 그것을 쓰는 설정과 입력 경로를 돌려준다."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"not a real video")
    weights = tmp_path / "w.ckpt"
    weights.write_bytes(b"w")
    work = tmp_path / "work"
    work.mkdir()

    def make(body: str, **overrides) -> WaveRepConfig:
        script = tmp_path / "fake_infer.py"
        script.write_text(FAKE_HEAD + body, encoding="utf-8")
        return replace(
            WaveRepConfig(python=Path(sys.executable), script=script, weights=weights, timeout_sec=20),
            **overrides,
        )

    return make, video, work


OK_BODY = """
frames = [{"index": i, "time_sec": i / 30, "logit": float(i) - 1.0} for i in range(3)]
json.dump({"status": "completed", "reason_code": None, "frames": frames,
           "echo": req, "memory": {"max_rss_bytes": 1}}, open(o.output, "w"))
"""


def test_completed_result_keeps_raw_logits_and_does_not_judge(fake):
    make, video, work = fake
    out = run_waverep(video, [(0.0, 1.0)], work, make(OK_BODY, sample_fps=2, batch_size=4, device="cpu"))
    assert out["status"] == "completed" and out["reason_code"] is None
    assert [f["logit"] for f in out["frames"]] == [-1.0, 0.0, 1.0]
    assert out["raw_metrics"]["frame_logit"]["mean"] == 0.0
    assert out["raw_score"] is None  # 집계·판정하지 않는다
    assert not {"overall_score", "verdict", "prob", "probability", "label"} & set(out)
    assert out["memory"]["peak_footprint_bytes"] is None  # 측정하지 않은 값은 null


def test_request_and_result_files_are_removed_from_work_dir(fake):
    make, video, work = fake
    run_waverep(video, [(0.0, 1.0)], work, make(OK_BODY))
    assert list(work.iterdir()) == []


def test_request_passes_config_to_process(fake, tmp_path):
    make, video, work = fake
    body = OK_BODY + f"\njson.dump(req, open({str(tmp_path / 'seen.json')!r}, 'w'))\n"
    cfg = make(body, sample_fps=4, batch_size=16, device="cpu", pretrained=False)
    run_waverep(video, [(0.5, 1.5), (2, 3)], work, cfg)
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert seen["segments"] == [[0.5, 1.5], [2.0, 3.0]]
    assert (seen["sample_fps"], seen["batch_size"], seen["device"], seen["pretrained"]) == (4, 16, "cpu", False)
    assert seen["video"] == str(video.resolve())


def assert_failed(out, status, reason_code):
    assert (out["status"], out["reason_code"]) == (status, reason_code)
    assert out["raw_score"] is None and out["raw_metrics"] is None and out["frames"] is None


def test_process_crash_becomes_error_with_null_scores(fake):
    make, video, work = fake
    out = run_waverep(video, [(0.0, 1.0)], work, make("raise RuntimeError('boom')\n"))
    assert_failed(out, "error", "inference_error")
    assert out["returncode"] != 0 and "boom" in out["stderr_tail"]
    assert list(work.iterdir()) == []


def test_broken_json_becomes_error(fake):
    make, video, work = fake
    out = run_waverep(video, [(0.0, 1.0)], work, make("open(o.output, 'w').write('{not json')\n"))
    assert_failed(out, "error", "inference_error")


@pytest.mark.parametrize("payload", [
    '{"status": "completed", "frames": []}',
    '{"status": "completed", "frames": [{"index": 0, "logit": null}]}',
    '{"status": "completed", "frames": [{"index": 0, "logit": NaN}]}',
    '{"status": "great"}',
])
def test_malformed_completed_result_is_not_trusted(fake, payload):
    make, video, work = fake
    out = run_waverep(video, [(0.0, 1.0)], work, make(f"open(o.output, 'w').write({payload!r})\n"))
    assert_failed(out, "error", "inference_error")


def test_process_reported_status_is_passed_through(fake):
    make, video, work = fake
    body = (
        'json.dump({"status": "unsupported_input", "reason_code": "frame_smaller_than_crop",'
        ' "frames": None}, open(o.output, "w"))\nsys.exit(1)\n'
    )
    out = run_waverep(video, [(0.0, 1.0)], work, make(body))
    assert_failed(out, "unsupported_input", "frame_smaller_than_crop")


def test_timeout_kills_process_and_returns_error(fake):
    make, video, work = fake
    out = run_waverep(video, [(0.0, 1.0)], work, make("time.sleep(60)\n", timeout_sec=1))
    assert_failed(out, "error", "timeout")
    assert list(work.iterdir()) == []


def test_stale_result_from_previous_run_is_not_read(fake):
    make, video, work = fake
    (work / waverep.RESULT_NAME).write_text(
        '{"status": "completed", "frames": [{"index": 0, "logit": 9.0}]}'
    )
    out = run_waverep(video, [(0.0, 1.0)], work, make("sys.exit(3)\n"))
    assert_failed(out, "error", "inference_error")


# ---------- 프로세스를 띄우기 전에 거르는 입력 ----------

def test_empty_segments_is_insufficient_input(fake):
    make, video, work = fake
    assert_failed(run_waverep(video, [], work, make(OK_BODY)), "insufficient_input", "no_segments")


@pytest.mark.parametrize("overrides", [
    {"device": "cuda"}, {"device": "cuda:0"}, {"device": "cpu; rm -rf /"},
    {"batch_size": 0}, {"batch_size": 2.5}, {"sample_fps": 0}, {"sample_fps": -1},
])
def test_invalid_config_is_rejected_before_running(fake, overrides):
    make, video, work = fake
    marker = work.parent / "ran"
    cfg = make(f"open({str(marker)!r}, 'w').write('x')\n" + OK_BODY, **overrides)
    assert_failed(run_waverep(video, [(0.0, 1.0)], work, cfg), "error", "invalid_request")
    assert not marker.exists()


@pytest.mark.parametrize("segments", [[(1.0, 1.0)], [(2.0, 1.0)], [(-1.0, 1.0)], [(0.0, math.inf)], [(0.0,)]])
def test_invalid_segments_are_rejected_before_running(fake, segments):
    make, video, work = fake
    assert_failed(run_waverep(video, segments, work, make(OK_BODY)), "error", "invalid_request")


def test_missing_video_and_missing_model_files(fake, tmp_path):
    make, video, work = fake
    assert_failed(run_waverep(tmp_path / "none.mp4", [(0.0, 1.0)], work, make(OK_BODY)), "error", "media_unreadable")
    cfg = make(OK_BODY, weights=tmp_path / "none.ckpt")
    assert_failed(run_waverep(video, [(0.0, 1.0)], work, cfg), "error", "model_unavailable")
    cfg = make(OK_BODY, python=tmp_path / "no-python")
    assert_failed(run_waverep(video, [(0.0, 1.0)], work, cfg), "error", "model_unavailable")


# ---------- 실제 추론 (환경이 있을 때만) ----------

def _real_sample() -> Path | None:
    cfg = WaveRepConfig()
    if not (cfg.python.is_file() and cfg.weights.is_file() and SAMPLE_DIR.is_dir()):
        return None
    videos = sorted(SAMPLE_DIR.glob("*.mp4"))
    return videos[0] if videos else None


@pytest.mark.skipif(_real_sample() is None, reason="research/waverep/.venv·가중치·샘플 영상이 없다")
def test_real_inference_on_cpu_two_frames(tmp_path):
    out = run_waverep(
        _real_sample(), [(0.0, 2.0)], tmp_path,
        WaveRepConfig(device="cpu", sample_fps=1, batch_size=2, pretrained=False, timeout_sec=300),
    )
    assert out["status"] == "completed", out
    assert [f["index"] for f in out["frames"]] == [0, 30]
    assert all(math.isfinite(f["logit"]) for f in out["frames"])
    assert out["raw_score"] is None
    assert out["model"]["device_used"] == "cpu" and out["model"]["pretrained_init"] is False
    assert out["memory"]["mps_driver_allocated_peak_bytes"] is None  # CPU 실행에서는 읽지 않는다
    assert list(tmp_path.iterdir()) == []
