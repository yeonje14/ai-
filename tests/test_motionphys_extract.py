"""MotionPhys 궤적 추출과 추출기 인터페이스. 합성 프레임과 합성 영상을 쓴다.

OpenCV가 없으면 건너뛴다. 얼굴 후보의 실제 실행은 샘플 영상·모델 파일·MediaPipe가 있을 때만 돈다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "research" / "motionphys"))

import extract  # noqa: E402
import kinematics  # noqa: E402
import tracking  # noqa: E402

SAMPLE_DIR = REPO_ROOT / "data" / "research" / "samples"
CONFIG = tracking.TrackingConfig()


def texture(h=240, w=320, seed=0) -> np.ndarray:
    """추적하기 쉬운 무늬(부드럽게 한 잡음)."""
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h // 8, w // 8), dtype=np.uint8)
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC)
    return cv2.GaussianBlur(img, (5, 5), 0)


def shifted(base: np.ndarray, dx: float, dy: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(base, m, (base.shape[1], base.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def moving_frames(n, step=(1.5, 0.5), jitter=0.0, seed=0, color=True):
    """무늬 전체가 걸음마다 step만큼 움직인다. jitter가 있으면 위치에 잡음을 더한다(떨리는 운동)."""
    rng = np.random.default_rng(seed)
    base = texture()
    frames = []
    for i in range(n):
        dx = step[0] * i + (rng.normal(0, jitter) if jitter else 0.0)
        dy = step[1] * i + (rng.normal(0, jitter) if jitter else 0.0)
        f = shifted(base, dx, dy)
        frames.append(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR) if color else f)
    return frames


def write_video(path: Path, frames, fps=30.0) -> Path:
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert writer.isOpened()
    for f in frames:
        writer.write(f)
    writer.release()
    return path


# ---------- 프레임 표본과 클립 ----------

def test_sample_indices_uniform_48():
    idx = tracking.sample_indices(0, 313)
    assert len(idx) == 48 and idx[0] == 0 and idx[-1] == 312
    assert max(np.diff(idx)) - min(np.diff(idx)) <= 1
    assert tracking.sample_indices(10, 40) == list(range(10, 40))    # 48프레임보다 적으면 전부
    assert tracking.sample_indices(5, 5) == []


def test_clip_ranges_are_non_overlapping():
    assert len(tracking.clip_ranges(48, 8)) == 6
    assert len(tracking.clip_ranges(48, 12)) == 4
    assert tracking.clip_ranges(48, 24) == [(0, 24), (24, 48)]
    assert tracking.clip_ranges(30, 12) == [(0, 12), (12, 24)]       # 남는 프레임은 버린다
    assert tracking.clip_ranges(7, 8) == []


# ---------- 점 초기화와 추적 ----------

def test_init_points_combines_corners_and_grid_and_respects_mask():
    gray = texture()
    pts = tracking.init_points(gray, CONFIG)
    n_grid = len(range(16, 240, 32)) * len(range(16, 320, 32))
    assert n_grid < len(pts) <= n_grid + CONFIG.max_corners
    mask = np.zeros_like(gray)
    mask[60:180, 100:220] = 255
    inside = tracking.init_points(gray, CONFIG, mask)
    assert 0 < len(inside) < len(pts)
    assert inside[:, 0].min() >= 100 and inside[:, 0].max() < 220
    assert inside[:, 1].min() >= 60 and inside[:, 1].max() < 180


def test_tracker_recovers_known_translation():
    step = (1.5, 0.5)
    frames = moving_frames(8, step, color=False)
    trajs = tracking.track_clip(frames, tracking.init_points(frames[0], CONFIG), CONFIG)
    assert trajs.shape[1:] == (8, 2) and len(trajs) > 50
    velocity = np.diff(trajs, axis=1)
    assert np.median(velocity[..., 0]) == pytest.approx(step[0], abs=0.1)
    assert np.median(velocity[..., 1]) == pytest.approx(step[1], abs=0.1)


def test_extract_trajectories_gives_all_scales():
    trajs, info = tracking.extract_trajectories(moving_frames(48))
    assert set(trajs) == {8, 12, 24}
    for s in (8, 12, 24):
        assert trajs[s].shape[1:] == (s, 2) and len(trajs[s]) > 0
        assert info[s]["clips_used"] == info[s]["clips"] == 48 // s
        assert len(trajs[s]) <= info[s]["initialized"]


def test_mask_returning_none_skips_the_clip():
    trajs, info = tracking.extract_trajectories(moving_frames(48), CONFIG, lambda start, frame: None)
    assert all(len(trajs[s]) == 0 and info[s]["clips_used"] == 0 for s in (8, 12, 24))


def test_shaky_video_has_larger_jerk_features_than_smooth_video():
    """영상에서 추적한 궤적으로도 떨리는 운동의 jerk가 더 크게 나온다."""
    def jerk_level(frames):
        trajs, _ = tracking.extract_trajectories(frames)
        z = kinematics.video_feature({s: kinematics.trajectory_features(trajs[s]) for s in kinematics.SCALES})
        names = kinematics.feature_names()
        return [z[names.index(f"L{s}.jerk.mean.median")] for s in kinematics.SCALES]

    smooth = jerk_level(moving_frames(48))
    shaky = jerk_level(moving_frames(48, jitter=0.8, seed=3))
    assert all(b > 3 * a for a, b in zip(smooth, shaky))


# ---------- 추출기 인터페이스 ----------

def test_moving_video_gives_504_features(tmp_path):
    video = write_video(tmp_path / "moving.mp4", moving_frames(60))
    out = extract.extract(video, [(0.0, 2.0)], "full")
    assert out["status"] == "completed" and out["reason_code"] is None
    assert out["feature_dim"] == 504 == len(out["features"])
    assert all(np.isfinite(out["features"]))
    assert out["segments"][0]["frames_sampled"] == 48
    for s in ("8", "12", "24"):
        assert out["by_scale"][s]["valid_trajectories"] >= out["by_scale"][s]["moving_trajectories"] > 0
        assert 0 < out["tracking_success_rate"][s] <= 1
    assert not {"score", "verdict", "label", "prob", "overall_score"} & set(out)   # 특징만 낸다


def test_static_video_is_insufficient_motion_with_null_features(tmp_path):
    video = write_video(tmp_path / "static.mp4", moving_frames(60, step=(0.0, 0.0)))
    out = extract.extract(video, [(0.0, 2.0)], "full")
    assert (out["status"], out["reason_code"]) == ("insufficient_input", "insufficient_motion")
    assert out["features"] is None and out["feature_dim"] is None
    assert out["by_scale"]["8"]["valid_trajectories"] > 0          # 추적은 됐지만 움직이지 않았다
    assert out["by_scale"]["8"]["moving_trajectories"] == 0


def test_flat_video_has_null_features(tmp_path):
    flat = [np.full((240, 320, 3), 128, np.uint8) for _ in range(60)]
    out = extract.extract(write_video(tmp_path / "flat.mp4", flat), [(0.0, 2.0)], "full")
    assert out["status"] == "insufficient_input" and out["features"] is None
    assert out["reason_code"] in ("tracking_failed", "insufficient_motion")


def test_multiple_segments_pool_trajectories(tmp_path):
    video = write_video(tmp_path / "moving.mp4", moving_frames(120))
    one = extract.extract(video, [(0.0, 2.0)], "full")
    two = extract.extract(video, [(0.0, 2.0), (2.0, 4.0)], "full")
    assert two["status"] == "completed" and len(two["segments"]) == 2
    assert two["by_scale"]["8"]["valid_trajectories"] > one["by_scale"]["8"]["valid_trajectories"]


def test_extraction_is_deterministic(tmp_path):
    video = write_video(tmp_path / "moving.mp4", moving_frames(60))
    assert extract.extract(video, [(0.0, 2.0)], "full")["features"] == extract.extract(video, [(0.0, 2.0)], "full")["features"]


def test_short_segment_is_insufficient_input(tmp_path):
    video = write_video(tmp_path / "moving.mp4", moving_frames(60))
    out = extract.extract(video, [(0.0, 0.1)], "full")       # 3프레임
    assert (out["status"], out["reason_code"]) == ("insufficient_input", "segment_too_short")
    assert out["features"] is None


@pytest.mark.parametrize("segments,variant,reason", [
    ([(0.0, 1.0)], "optical", "invalid_request"),
    ([(1.0, 1.0)], "full", "invalid_request"),
    ([(-1.0, 1.0)], "full", "invalid_request"),
    ([(0.0, float("inf"))], "full", "invalid_request"),
    ("ab", "full", "invalid_request"),
])
def test_invalid_requests(tmp_path, segments, variant, reason):
    video = write_video(tmp_path / "moving.mp4", moving_frames(20))
    out = extract.extract(video, segments, variant)
    assert (out["status"], out["reason_code"]) == ("error", reason) and out["features"] is None


def test_no_segments_and_missing_video(tmp_path):
    video = write_video(tmp_path / "moving.mp4", moving_frames(20))
    assert extract.extract(video, [], "full")["reason_code"] == "no_segments"
    out = extract.extract(tmp_path / "none.mp4", [(0.0, 1.0)], "full")
    assert (out["status"], out["reason_code"]) == ("error", "media_unreadable")
    (tmp_path / "broken.mp4").write_bytes(b"not a video")
    assert extract.extract(tmp_path / "broken.mp4", [(0.0, 1.0)], "full")["status"] == "error"


def test_feature_dims_and_names_per_variant():
    assert extract.feature_dim("full") == extract.feature_dim("face_roi") == 504
    assert extract.feature_dim("face_motion") == 1512
    names = extract.feature_names("face_motion")
    assert len(names) == len(set(names)) == 1512
    assert names[0].startswith("head.") and names[504].startswith("eyebrows.") and names[1008].startswith("lips.")


def test_cli_writes_result_json(tmp_path):
    video = write_video(tmp_path / "moving.mp4", moving_frames(60))
    req, out = tmp_path / "req.json", tmp_path / "out.json"
    req.write_text(json.dumps({"video": str(video), "segments": [[0.0, 2.0]], "variant": "full"}))
    assert extract.main(["--request", str(req), "--output", str(out)]) == 0
    assert json.loads(out.read_text())["feature_dim"] == 504
    req.write_text(json.dumps({"segments": [[0.0, 2.0]]}))            # video 없음
    assert extract.main(["--request", str(req), "--output", str(out)]) == 1
    assert json.loads(out.read_text())["features"] is None


# ---------- 얼굴 후보 ----------

def test_region_trajectories_remove_head_translation_and_scale():
    faces = pytest.importorskip("faces")
    rng = np.random.default_rng(0)
    base = rng.uniform(100, 200, (478, 2))
    regions = {"head": list(range(0, 36)), "eyebrows": list(range(40, 60)), "lips": list(range(60, 100))}
    # 머리 전체가 이동하면서 1.5배까지 커진다. 얼굴 안의 상대 위치는 그대로다
    frames = []
    for t in range(8):
        scale = 1 + 0.5 * t / 7
        frames.append((base - base.mean(0)) * scale + base.mean(0) + np.array([3.0 * t, -2.0 * t]))
    out = faces.region_trajectories(np.stack(frames), regions)
    assert out["head"].shape == (36, 8, 2) and out["lips"].shape == (40, 8, 2)
    assert np.abs(np.diff(out["head"], axis=1)).max() > 1            # 머리는 화면에서 움직였다
    for name in ("eyebrows", "lips"):                                # 상대 좌표는 거의 그대로다
        assert np.abs(np.diff(out[name], axis=1)).max() < 0.5


def test_model_file_hash_is_checked(tmp_path, monkeypatch):
    faces = pytest.importorskip("faces")
    model = tmp_path / "m.task"
    model.write_bytes(b"model")
    cfg = tmp_path / "models.json"
    monkeypatch.setattr(faces, "REPO_ROOT", tmp_path)
    cfg.write_text(json.dumps({"x": {"path": "m.task", "sha256": "0" * 64}}))
    with pytest.raises(faces.ModelFileError):
        faces.model_path("x", cfg)
    cfg.write_text(json.dumps({"x": {"path": "none.task", "sha256": "0" * 64}}))
    with pytest.raises(faces.ModelFileError):
        faces.model_path("x", cfg)
    import hashlib
    cfg.write_text(json.dumps({"x": {"path": "m.task", "sha256": hashlib.sha256(b"model").hexdigest()}}))
    assert faces.model_path("x", cfg) == model


def test_models_config_lists_sources_and_hashes():
    cfg = json.loads((REPO_ROOT / "configs" / "motionphys_models.json").read_text())
    for key in ("face_detector", "face_landmarker"):
        assert len(cfg[key]["sha256"]) == 64 and cfg[key]["source"].startswith("https://storage.googleapis.com/mediapipe-models/")
        assert cfg[key]["path"].startswith("data/models/")          # Git 밖


def _face_ready() -> bool:
    try:
        import faces
        import mediapipe  # noqa: F401
        faces.model_path("face_detector")
        faces.model_path("face_landmarker")
    except Exception:
        return False
    return SAMPLE_DIR.is_dir() and any(SAMPLE_DIR.glob("*.mp4"))


needs_face = pytest.mark.skipif(not _face_ready(), reason="MediaPipe·모델 파일·샘플 영상이 없다")


@needs_face
def test_face_variants_on_real_sample():
    video = sorted(SAMPLE_DIR.glob("*.mp4"))[0]
    roi = extract.extract(video, [(0.0, 4.0)], "face_roi")
    assert roi["status"] == "completed" and roi["feature_dim"] == 504
    full = extract.extract(video, [(0.0, 4.0)], "full")
    assert roi["by_scale"]["8"]["valid_trajectories"] < full["by_scale"]["8"]["valid_trajectories"]
    motion = extract.extract(video, [(0.0, 4.0)], "face_motion")
    assert motion["status"] == "completed" and motion["feature_dim"] == 1512
    assert set(motion["by_region"]) == {"head", "eyebrows", "lips"}
    assert motion["landmarks_per_region"] == {"head": 36, "eyebrows": 20, "lips": 40}
    assert motion["face_detection_rate"] == 1.0


@needs_face
def test_face_variants_fail_cleanly_without_a_face(tmp_path):
    video = write_video(tmp_path / "moving.mp4", moving_frames(60))
    for variant in ("face_roi", "face_motion"):
        out = extract.extract(video, [(0.0, 2.0)], variant)
        assert (out["status"], out["reason_code"]) == ("insufficient_input", "tracking_failed")
        assert out["features"] is None
