"""학습·결합·임계값 잠금 (조각 2). 합성 데이터만 쓴다. 수치는 성능이 아니다.

학습은 research/training/.venv(scikit-learn, lightgbm)의 서브프로세스로 돈다. venv가 없으면 그 테스트는 건너뛴다.
설정 검사는 trinity에서 항상 돈다.
"""
import csv
import json
import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from training import config as training_config, synth
from training.evaluation import thresholds

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = REPO_ROOT / "research/training/.venv/bin/python"
TRAIN = REPO_ROOT / "research/training/train.py"
needs_venv = pytest.mark.skipif(not PYTHON.is_file(), reason="research/training/.venv 없음")
BASE = synth.SynthConfig(identities=80, signal={"waverep": 1.5, "full": 1.0}, missing={"full": 0.1, "syncnet": 0.2},
                         profiles=("x264-crf28-720p",), seed=3)


def config(**kw) -> dict:
    c = json.loads((REPO_ROOT / "configs/training.json").read_text(encoding="utf-8"))
    c["dev_compression_conditions"] = ["original"]
    c.update(kw)
    return c


def run_train(folder: Path, cfg: synth.SynthConfig, conf: dict, name="run") -> subprocess.CompletedProcess:
    data = folder / f"{name}-data"
    if not data.exists():
        synth.write(cfg, data)
    (folder / f"{name}.json").write_text(json.dumps(conf), encoding="utf-8")
    return subprocess.run([str(PYTHON), str(TRAIN), "--manifest", str(data / "manifest.csv"), "--features", str(data),
                           "--config", str(folder / f"{name}.json"), "--out", str(folder / name)],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=300)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    if not PYTHON.is_file():
        pytest.skip("research/training/.venv 없음")
    folder = tmp_path_factory.mktemp("train")
    proc = run_train(folder, BASE, config())
    assert proc.returncode == 0, proc.stderr
    return folder


# ---------- 설정 (항상 실행) ----------

def test_committed_config_has_no_dev_compression_default_and_is_refused():
    raw = json.loads((REPO_ROOT / "configs/training.json").read_text(encoding="utf-8"))
    assert raw["dev_compression_conditions"] is None
    with pytest.raises(training_config.ConfigError, match="명시"):
        training_config.validate(raw)
    assert raw["max_group_share"] == 0.25 and raw["target_fpr"] == 0.05
    assert raw["adoption"]["max_test_fpr_ci_high"] == 0.10


@pytest.mark.parametrize("extra", [{"threshold_split": "test"}, {"tune_on_test": True}, {"threshold": 0.3}])
def test_config_cannot_express_test_based_threshold(extra):
    with pytest.raises(training_config.ConfigError, match="모르는 설정 키"):
        training_config.validate(config(**extra))


@pytest.mark.parametrize("bad", [[], "original", ["original", "original"], [""]])
def test_dev_compression_conditions_must_be_an_explicit_list(bad):
    with pytest.raises(training_config.ConfigError):
        training_config.validate(config(dev_compression_conditions=bad))


def test_threshold_fit_rejects_non_dev_splits():
    from training.evaluation.metrics import Item
    items = [Item("a", "real", "g1", 0.1), Item("b", "fake", "g2", 0.9)]
    for split in ("test", "train", "external"):
        with pytest.raises(thresholds.ThresholdError):
            thresholds.fit_threshold(items, [split, split], model_id="m", manifest_sha256="x", scores_sha256="y")


# ---------- 학습 (venv 필요) ----------

def test_outputs_candidates_locked_dev_thresholds_and_models(base):
    meta = json.loads((base / "run/train_meta.json").read_text())
    assert meta["candidates"] == ["W", "M-full", "M-face_roi", "M-face_motion", "W+M", "W+M+S"]
    assert meta["dev_compression_conditions"] == ["original"] and meta["synthetic"] is True
    assert meta["train_compression_conditions"] == ["original", "x264-crf28-720p"]
    assert meta["dev_videos_used"] * 2 == meta["split_videos"]["dev"]  # 지정한 조건의 dev만 쓴다
    assert meta["motion_variant_for_fusion"] == "full"  # 신호를 준 후보가 dev에서 뽑힌다
    for cand in meta["candidates"]:
        path = base / "run/thresholds" / f"{cand}.json"
        t = thresholds.load_threshold(path)
        assert t["source_split"] == "dev" and t["dev_fpr"] <= 0.05 and t["model_id"] == cand
        assert not os.stat(path).st_mode & stat.S_IWUSR  # 읽기 전용
        model = json.loads((base / "run/models" / f"{cand}.json").read_text())
        assert len(model["model"]["coef"]) == len(model["inputs"]) and set(model["calibration"]) == {"a", "b"}
        assert model["threshold_digest"] == t["digest"]
    assert json.loads((base / "run/models/W+M+S.json").read_text())["axes"] == ["signal", "physics", "alignment"]
    assert json.loads((base / "run/models/W.json").read_text())["model"] == {
        "mean": [0.0], "scale": [1.0], "coef": [1.0], "intercept": 0.0}


def test_missing_axis_gives_blank_score_not_zero(base):
    def blanks(name):
        with (base / "run/scores" / name).open() as f:
            return [r for r in csv.DictReader(f) if r["score"] == ""]
    assert not blanks("W.csv")
    missing = blanks("W+M+S.csv")
    assert missing and all(r["status"] == "insufficient_input" and r["reason_code"] == "missing_axis_input" for r in missing)
    assert len(blanks("W+M+S.csv")) > len(blanks("W+M.csv")) > 0
    with (base / "run/scores/W.csv").open() as f:
        ids = {r["video_id"] for r in csv.DictReader(f)}
    with (base / "run-data/manifest.csv").open() as f:
        expected = {r["video_id"] for r in csv.DictReader(f) if r["split"] in ("dev", "test")}
    assert ids == expected  # train은 scores에 없다(OOF는 oof/에 따로)


@needs_venv
def test_changing_test_rows_cannot_change_models_or_thresholds(base, tmp_path):
    """test 분할의 특징과 라벨을 바꿔도 모델·보정·임계값이 같다. test로 조정하는 경로가 없다."""
    records, rows = synth.generate(BASE)
    test_ids = {r.uid for r in records if r.split == "test"}
    for row in rows:
        if row["uid"] in test_ids:
            w = row["axes"]["waverep"]
            for k in ("logit_median", "logit_mean", "logit_q75"):
                w[k] = None if w[k] is None else w[k] * -7.0 + 100.0
    flipped = [replace(r, label="real" if r.label == "fake" else "fake",
                       manipulation_type="" , generator_id="") if r.uid in test_ids and not r.parent_video_id
               and not any(c.parent_video_id == r.video_id for c in records) else r for r in records]
    data = tmp_path / "alt-data"
    data.mkdir()
    from training.datasets.manifest import sha256_file, write_manifest
    write_manifest(data / "manifest.csv", flipped)
    with (data / "features.jsonl").open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    (data / "features.meta.json").write_text(json.dumps({
        "manifest_sha256": sha256_file(data / "manifest.csv"), "feature_version": synth.FEATURE_VERSION,
        "features_sha256": sha256_file(data / "features.jsonl"), "synthetic": True}))
    proc = run_train(tmp_path, BASE, config(), name="alt")
    assert proc.returncode == 0, proc.stderr
    for cand in ("W", "M-full", "W+M", "W+M+S"):
        a = json.loads((base / "run/models" / f"{cand}.json").read_text())
        b = json.loads((tmp_path / "alt/models" / f"{cand}.json").read_text())
        assert (a["model"], a["calibration"]) == (b["model"], b["calibration"])
        ta = thresholds.load_threshold(base / "run/thresholds" / f"{cand}.json")
        tb = thresholds.load_threshold(tmp_path / "alt/thresholds" / f"{cand}.json")
        assert ta["threshold"] == tb["threshold"]


@needs_venv
@pytest.mark.parametrize("case,message", [
    ("leak", "누수 검사 실패"), ("giant", "가장 큰 그룹"), ("nodev", "명시"), ("absent", "dev에 없는 압축 조건"),
    ("mismatch", "manifest_sha256"), ("exists", ""),
])
def test_training_refuses_unsafe_inputs(tmp_path, case, message):
    cfg, conf = replace(BASE, identities=40, profiles=()), config()
    if case == "leak":
        cfg = replace(cfg, leak=True)
    if case == "giant":
        conf["max_group_share"] = 0.01
    if case == "nodev":
        conf["dev_compression_conditions"] = None
    if case == "absent":
        conf["dev_compression_conditions"] = ["original", "x264-crf34-480p"]
    if case == "mismatch":
        synth.write(cfg, tmp_path / "run-data")
        meta = tmp_path / "run-data/features.meta.json"
        m = json.loads(meta.read_text())
        m["manifest_sha256"] = "0" * 64
        meta.write_text(json.dumps(m))
    if case == "exists":
        (tmp_path / "run").mkdir()
    proc = run_train(tmp_path, cfg, conf)
    assert proc.returncode == 1 and message in proc.stderr
    assert not (tmp_path / "run/thresholds").exists()
