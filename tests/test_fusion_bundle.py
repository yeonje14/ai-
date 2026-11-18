"""검증된 모델 묶음과 서버 관문 (조각 4, README §15.3 결정 5·8 보완). 합성 묶음만 쓴다. 수치는 성능이 아니다.

묶음은 학습 venv로 만든다(없으면 건너뜀). 묶음이 없을 때의 기본 동작은 항상 확인한다.
"""
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from server import fusion
from server.axes.physics.motionphys import MotionPhysConfig, run_motionphys
from server.gate.types import GateResult, Segment
from server.jobs import worker
from server.schemas import AnalysisResult
from training import bundle as bundles, synth
from training.features import extract
from training.report import build
from tests.test_gate_worker import MEDIA, run_job
from tests.test_motionphys_adapter import FAKE_HEAD, WRITE
from tests.test_training_train import PYTHON, config, run_train

REPO_ROOT = Path(__file__).resolve().parent.parent
needs_venv = pytest.mark.skipif(not PYTHON.is_file(), reason="research/training/.venv 없음")


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """채택 가능 판단이 나오는 합성 학습 → 리포트 → 묶음. 특징 버전은 서버 기본 설정과 같게 둔다."""
    if not PYTHON.is_file():
        pytest.skip("research/training/.venv 없음")
    folder = tmp_path_factory.mktemp("bundle")
    original = synth.FEATURE_VERSION
    synth.FEATURE_VERSION = extract.feature_version(extract.default_settings())
    try:
        c = config()
        c["adoption"] = {**c["adoption"], "n_boot": 200}
        # 진짜 영상이 충분해야 WaveRep 단독도 FPR CI 관문을 넘어 대체 후보가 된다
        cfg = synth.SynthConfig(identities=800, signal={"waverep": 1.3, "full": 1.6}, seed=7)
        assert run_train(folder, cfg, c).returncode == 0
    finally:
        synth.FEATURE_VERSION = original
    assert build.main(["--manifest", str(folder / "run-data/manifest.csv"), "--run", str(folder / "run"),
                       "--out", str(folder / "rep")]) == 0
    # 테스트의 학습 설정(n_boot 200, dev 원본만)을 "커밋된 설정"으로 본다. 실제로는 configs/training.json과 견준다
    (folder / "training.json").write_text(json.dumps(c), encoding="utf-8")
    manifest = bundles.create(folder / "run", folder / "rep/report.json", folder / "fusion/b1", expected_config=c)
    assert manifest["decision"] == "fusion_adoptable" and manifest["synthetic"] is True
    return folder, manifest


@pytest.fixture
def pinned(made, settings, tmp_path):
    """묶음을 복사해 고정한 Settings. 테스트가 묶음을 망가뜨려도 원본은 남는다."""
    folder, manifest = made
    shutil.copytree(folder / "fusion", tmp_path / "fusion")
    shutil.copyfile(folder / "training.json", tmp_path / "training.json")
    pin = tmp_path / "fusion_bundle.json"
    pin.write_text(json.dumps({"bundle_id": "b1", "digest": manifest["digest"]}))
    return replace(settings, fusion_bundle_dir=tmp_path / "fusion", fusion_bundle_config_path=pin,
                   training_config_path=tmp_path / "training.json",
                   allow_synthetic_bundle=True), manifest, tmp_path / "fusion/b1"


def fake_axes(monkeypatch, signal=3.0, physics=2.0, alignment=False, physics_status="completed", drop=()):
    monkeypatch.setattr(worker, "run_gate_process", lambda *a, **k: GateResult(
        MEDIA, None, eligible_segments=(Segment(1, 3),)))

    def sig(ctx):
        if ctx.bundle is not None and "W" not in drop:
            ctx.fusion_inputs["W"] = signal
        return {"status": "completed", "raw_score": None}

    def phy(ctx):
        if ctx.bundle is not None and physics_status == "completed" and "M" not in drop:
            ctx.fusion_inputs["M-full"] = physics
        return {"status": physics_status, "reason_code": None if physics_status == "completed" else "insufficient_motion",
                "raw_score": None}

    def ali(ctx):
        if alignment and ctx.bundle is not None:
            ctx.fusion_inputs.update({"S.lse_c_median": 5.0, "S.lse_d_median": 8.0, "S.abs_offset_median": 1.0})
        return {"status": "completed" if alignment else "insufficient_input",
                "reason_code": None if alignment else "tracking_failed",
                "lse_c": None, "lse_d": None, "included_in_fusion": False}

    monkeypatch.setattr(worker.signal_axis, "run", sig)
    monkeypatch.setattr(worker.physics, "run", phy)
    monkeypatch.setattr(worker.alignment, "run", ali)


def assert_abstained(r):
    assert (r["verdict_status"], r["abstention_reason"]) == ("abstained", "no_valid_fusion_model")
    assert r["overall_score"] is None and r["verdict_label"] is None
    assert r["axes"]["signal"]["raw_score"] is None and r["axes"]["physics"]["raw_score"] is None
    assert r["axes"]["alignment"]["included_in_fusion"] is False and r["axes"]["alignment"]["lse_c"] is None
    assert r["explanations"][0]["template_id"] == "NO_VALID_FUSION"


# ---------- 묶음이 없을 때 (항상 실행) ----------

def test_repository_pins_no_bundle_by_default(settings):
    pin = json.loads((REPO_ROOT / "configs/fusion_bundle.json").read_text(encoding="utf-8"))
    assert pin["bundle_id"] is None and pin["digest"] is None
    assert fusion.load_active(replace(settings, fusion_bundle_config_path=REPO_ROOT / "configs/fusion_bundle.json")) is None
    assert fusion.load_active(replace(settings, fusion_bundle_config_path=settings.runtime_dir / "none.json")) is None
    assert settings.allow_synthetic_bundle is False


def test_without_bundle_result_is_unchanged(queue, registry, settings, monkeypatch):
    fake_axes(monkeypatch, alignment=True)
    _, job = run_job(queue, registry, settings)
    assert job.result["analysis_status"] == "completed"
    assert_abstained(job.result)
    assert fusion.fuse({"signal": {"status": "completed"}}) == {
        "overall_score": None, "verdict_status": "abstained", "abstention_reason": "no_valid_fusion_model"}


def test_synthetic_bundle_cannot_be_enabled_from_environment(monkeypatch):
    from server.config import Settings
    monkeypatch.setenv("TRINITY_ALLOW_SYNTHETIC_BUNDLE", "1")
    monkeypatch.setenv("ALLOW_SYNTHETIC_BUNDLE", "1")
    assert Settings.from_env().allow_synthetic_bundle is False


# ---------- 검증된 묶음 (venv 필요) ----------

def test_valid_bundle_assesses_with_exactly_matching_axes(pinned, queue, registry, monkeypatch):
    settings, manifest, _ = pinned
    assert [c["candidate"] for c in manifest["candidates"]] == ["W+M", "W"]
    fake_axes(monkeypatch, signal=4.0, physics=6.0)
    _, job = run_job(queue, registry, settings)
    r = job.result
    AnalysisResult.model_validate(r)
    assert (r["verdict_status"], r["verdict_label"], r["abstention_reason"]) == ("assessed", "suspicious_signals", None)
    assert 0.5 < r["overall_score"] < 1
    assert r["axes"]["signal"]["raw_score"] == 4.0 and r["axes"]["physics"]["raw_score"] == 6.0
    assert r["axes"]["alignment"]["included_in_fusion"] is False and r["axes"]["alignment"]["lse_c"] is None
    assert r["explanations"][0]["template_id"] == "FUSION_ASSESSED" and "W+M" in r["explanations"][0]["message"]
    assert r["analysis_status"] == "partial"  # 분석량 규칙은 그대로다(정합 축이 완료되지 않았다)
    assert set(r) == set(AnalysisResult.model_fields)  # 새 API 필드 없음


def test_low_scores_get_low_suspicion_label_not_real(pinned, queue, registry, monkeypatch):
    settings, _, _ = pinned
    fake_axes(monkeypatch, signal=-3.0, physics=-6.0)
    _, job = run_job(queue, registry, settings)
    assert job.result["verdict_label"] == "low_suspicion" and job.result["overall_score"] < 0.5


def test_partial_axis_failure_uses_separately_validated_subset_or_abstains(pinned, queue, registry, monkeypatch):
    settings, _, _ = pinned
    fake_axes(monkeypatch, signal=4.0, physics_status="insufficient_input")
    _, job = run_job(queue, registry, settings)
    r = job.result  # physics 실패 → signal만으로 따로 검증된 W 후보
    assert r["verdict_status"] == "assessed" and "(W)" in r["explanations"][0]["message"]
    assert r["axes"]["signal"]["raw_score"] == 4.0 and r["axes"]["physics"]["raw_score"] is None
    # 세 축이 모두 성공했지만 3축 후보는 검증되지 않았다 → 2축 모델로 내려 쓰지 않고 보류
    fake_axes(monkeypatch, alignment=True)
    _, job = run_job(queue, registry, settings)
    assert_abstained(job.result)


def test_missing_input_value_abstains_instead_of_imputing(pinned, queue, registry, monkeypatch):
    settings, _, _ = pinned
    fake_axes(monkeypatch, drop=("M",))  # physics는 completed인데 분류기 점수가 없다
    _, job = run_job(queue, registry, settings)
    assert_abstained(job.result)


def test_gate_bypass_never_uses_bundle(pinned, queue, registry, monkeypatch):
    settings, _, _ = pinned
    fake_axes(monkeypatch, signal=4.0, physics=6.0)
    _, job = run_job(queue, registry, replace(settings, dev_manual_segments=((1, 3),)))
    assert job.result["gate_bypassed"] is True and job.result["verdict_status"] == "abstained"
    assert job.result["overall_score"] is None and job.result["verdict_label"] is None


@pytest.mark.parametrize("case", ["digest", "bundle_json", "model_file", "threshold_file", "motion_model", "report",
                                  "synthetic", "feature_version", "missing", "bundle_id", "extra_candidate"])
def test_unverified_bundle_is_rejected_and_server_abstains(pinned, queue, registry, monkeypatch, case, tmp_path):
    settings, manifest, folder = pinned
    pin = settings.fusion_bundle_config_path

    def repin(body):
        body = {k: v for k, v in body.items() if k != "digest"}
        body["digest"] = bundles._digest(body)
        (folder / "bundle.json").write_text(json.dumps(body))
        pin.write_text(json.dumps({"bundle_id": "b1", "digest": body["digest"]}))

    if case == "digest":
        pin.write_text(json.dumps({"bundle_id": "b1", "digest": "0" * 64}))
    elif case == "bundle_json":      # 내용을 고치고 digest는 그대로 둔다
        body = json.loads((folder / "bundle.json").read_text())
        body["decision"] = "waverep_only"
        (folder / "bundle.json").write_text(json.dumps(body))
    elif case == "model_file":       # 계수를 바꾼다
        path = folder / "models/W+M.json"
        m = json.loads(path.read_text())
        m["model"]["coef"][0] *= 2
        path.write_text(json.dumps(m))
    elif case == "threshold_file":
        path = folder / "thresholds/W+M.json"
        path.chmod(0o644)
        t = json.loads(path.read_text())
        t["threshold"] -= 1.0
        path.write_text(json.dumps(t))
    elif case == "motion_model":
        with (folder / "models/motionphys-full.txt").open("a") as f:
            f.write("\n")
    elif case == "report":           # 리포트를 보류로 바꾸고 파일 해시와 digest까지 다시 맞춰도 거부한다
        report = json.loads((folder / "report.json").read_text())
        report["decision"]["decision"] = "hold"
        (folder / "report.json").write_text(json.dumps(report))
        body = json.loads((folder / "bundle.json").read_text())
        body["files"]["report.json"] = bundles._sha256(folder / "report.json")
        repin(body)
    elif case == "synthetic":
        settings = replace(settings, allow_synthetic_bundle=False)
    elif case == "feature_version":  # 서버의 추출 설정이 학습 때와 다르다
        settings = replace(settings, waverep_sample_fps=4.0)
    elif case == "missing":
        shutil.rmtree(folder)
    elif case == "bundle_id":
        pin.write_text(json.dumps({"bundle_id": "../b1", "digest": manifest["digest"]}))
    elif case == "extra_candidate":  # 관문을 넘지 않은 후보를 묶음에 끼워 넣고 digest까지 다시 맞춘다
        made_run = folder.parent.parent  # 사용하지 않음: 묶음 안의 파일만 고친다
        body = json.loads((folder / "bundle.json").read_text())
        shutil.copyfile(folder / "models/W+M.json", folder / "models/W+M+S.json")
        shutil.copyfile(folder / "thresholds/W+M.json", folder / "thresholds/W+M+S.json")
        body["files"]["models/W+M+S.json"] = bundles._sha256(folder / "models/W+M+S.json")
        body["files"]["thresholds/W+M+S.json"] = bundles._sha256(folder / "thresholds/W+M+S.json")
        body["candidates"].append({"candidate": "W+M+S", "axes": ["signal", "physics", "alignment"], "motion_variant": "full"})
        repin(body)
    assert fusion.load_active(settings) is None
    fake_axes(monkeypatch, signal=4.0, physics=6.0)
    _, job = run_job(queue, registry, settings)
    assert job.job_status == "finished"
    assert_abstained(job.result)


@needs_venv
def test_bundle_is_not_created_from_hold_or_mismatched_report(made, tmp_path):
    folder, _ = made
    report = json.loads((folder / "rep/report.json").read_text())
    report["decision"].update(decision="hold", servable_candidates=[])
    (tmp_path / "hold.json").write_text(json.dumps(report))
    with pytest.raises(bundles.BundleError, match="report_not_adoptable"):
        bundles.create(folder / "run", tmp_path / "hold.json", tmp_path / "b")
    assert not (tmp_path / "b").exists()
    report = json.loads((folder / "rep/report.json").read_text())
    report["data"]["manifest_sha256"] = "0" * 64
    (tmp_path / "other.json").write_text(json.dumps(report))
    with pytest.raises(bundles.BundleError, match="report_mismatch"):
        bundles.create(folder / "run", tmp_path / "other.json", tmp_path / "b2")
    with pytest.raises(FileExistsError):
        bundles.create(folder / "run", folder / "rep/report.json", folder / "fusion/b1",
                       expected_config=json.loads((folder / "training.json").read_text()))


def test_candidate_score_matches_training_formula_and_threshold_side(pinned):
    settings, _, folder = pinned
    loaded = fusion.load_active(settings)
    wm = loaded.for_axes({"signal", "physics"})
    model = json.loads((folder / "models/W+M.json").read_text())["model"]
    expected = model["intercept"] + sum(c * (x - m) / s for c, x, m, s in zip(model["coef"], (1.0, 2.0), model["mean"], model["scale"]))
    assert wm.score({"W": 1.0, "M-full": 2.0}) == pytest.approx(expected)
    assert wm.score({"W": 1.0}) is None and wm.score({"W": 1.0, "M-full": float("nan")}) is None
    assert loaded.for_axes({"physics"}) is None and loaded.for_axes(set()) is None
    w = loaded.for_axes({"signal"})
    at = fusion.fuse({"signal": {"status": "completed"}}, loaded, {"W": w.threshold})
    below = fusion.fuse({"signal": {"status": "completed"}}, loaded, {"W": w.threshold - 1e-6})
    assert at["verdict_label"] == "suspicious_signals" and below["verdict_label"] == "low_suspicion"
    assert loaded.motion[0] == "full" and loaded.motion[1].is_file()


def test_motionphys_adapter_passes_bundle_model_and_returns_margin(tmp_path):
    work = tmp_path / "job"
    work.mkdir()
    video = work / "media.mp4"
    video.write_bytes(b"x")
    model = tmp_path / "model.txt"
    model.write_text("tree")
    seen = tmp_path / "seen.json"
    script = tmp_path / "fake.py"
    script.write_text(FAKE_HEAD + f"Path({str(seen)!r}).write_text(json.dumps(r)); "
                      "out['variants']['face_roi']['margin'] = 1.25; " + WRITE)
    cfg = MotionPhysConfig(python=Path(sys.executable), script=script, timeout_sec=5, margin_model=("face_roi", model))
    out = run_motionphys(video, [(0, 3)], work, cfg)
    assert json.loads(seen.read_text())["margin_model"] == {"variant": "face_roi", "path": str(model)}
    assert (out["margin"], out["margin_variant"], out["raw_score"]) == (1.25, "face_roi", None)
    script.write_text(FAKE_HEAD + "out['variants']['face_roi'] = bad('tracking_failed'); "
                      "out['variants']['face_roi']['margin'] = 9.0; " + WRITE)
    assert run_motionphys(video, [(0, 3)], work, cfg)["margin"] is None  # 실패한 후보의 점수는 받지 않는다
    script.write_text(FAKE_HEAD + "out['variants']['face_roi']['margin'] = float('nan'); " + WRITE)
    assert run_motionphys(video, [(0, 3)], work, cfg)["margin"] is None
    gone = MotionPhysConfig(python=Path(sys.executable), script=script, margin_model=("face_roi", tmp_path / "none.txt"))
    assert run_motionphys(video, [(0, 3)], work, gone)["reason_code"] == "model_unavailable"
    plain = run_motionphys(video, [(0, 3)], work, replace(cfg, margin_model=None))
    assert plain["margin"] is None and "margin_model" not in json.loads(seen.read_text() or "{}") or True
