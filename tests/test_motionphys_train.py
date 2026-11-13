"""LightGBM 학습 스크립트와 압축 측정 스크립트의 동작 확인. 합성 데이터만 쓴다.

실제 학습이 아니다. 합성 특징(일부 차원에 신호를 심은 난수)으로 학습 → 점수 파일 →
평가 파이프라인까지 이어지는지만 본다. LightGBM이 없으면(trinity 환경) 건너뛴다.
research/motionphys/.venv에서 실행한다.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("lightgbm")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "research" / "motionphys"))

import train_lgbm  # noqa: E402
from training.datasets import groups, manifest  # noqa: E402
from training.datasets.manifest import Record  # noqa: E402
from training.evaluation import run  # noqa: E402

DIM = 24


def _records(n_sources=90) -> list[Record]:
    out = []
    for s in range(n_sources):
        for c in range(2):
            out.append(Record("synth", f"r{s}_{c}", f"synth/r{s}_{c}.mp4", "real", f"s{s}"))
            out.append(Record("synth", f"f{s}_{c}", f"synth/f{s}_{c}.mp4", "fake", f"s{s}",
                              manipulation_type="A1", generator_id=f"gen{s % 2}"))
    return groups.assign_splits(out, {"train": 0.5, "dev": 0.25, "test": 0.25}, seed=3)


@pytest.fixture
def world(tmp_path):
    rng = np.random.default_rng(0)
    records = _records()
    external = [Record("ext-set", "e1", "ext/e1.mp4", "fake", "ext-s1", generator_id="new", split="external")]
    m, feats = tmp_path / "manifest.csv", tmp_path / "features.csv"
    manifest.write_manifest(m, records + external)
    missing = {r.uid for r in records if r.split == "test"}
    missing = set(sorted(missing)[:5])                     # 특징이 없는 test 영상 5개
    with feats.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "video_id", "status", "reason_code", *[f"f{i}" for i in range(DIM)]])
        for r in records + external:
            if r.uid in missing:
                w.writerow([r.dataset_id, r.video_id, "insufficient_input", "insufficient_motion", *[""] * DIM])
                continue
            x = rng.normal(0, 1, DIM)
            if r.label == "fake":
                x[:3] += 1.5                               # 신호를 심은 차원
            w.writerow([r.dataset_id, r.video_id, "completed", "", *[repr(float(v)) for v in x]])
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"datasets": {"ext-set": {"status": "locked"}}}))
    return {"dir": tmp_path, "manifest": m, "features": feats, "lock": lock, "records": records, "missing": missing}


def train(world, **override):
    args = {"--manifest": world["manifest"], "--features": world["features"], "--variant": "full",
            "--out-dir": world["dir"] / "out", "--lock": world["lock"], **override}
    return train_lgbm.main([str(x) for kv in args.items() for x in kv])


def read_scores(path):
    with path.open(newline="") as f:
        return {f"{r['dataset_id']}:{r['video_id']}": r for r in csv.DictReader(f)}


def test_train_on_synthetic_features_and_score_dev_test_only(world):
    assert train(world) == 0
    out = world["dir"] / "out"
    assert (out / "model.txt").is_file()
    meta = json.loads((out / "train_meta.json").read_text())
    n = {s: sum(1 for r in world["records"] if r.split == s) for s in ("train", "dev", "test")}
    assert meta["train_videos"] == n["train"] and meta["feature_dim"] == DIM
    assert meta["external_videos_ignored"] == 1 and meta["scored_null"] == 5
    scores = read_scores(out / "scores.csv")
    by_uid = {r.uid: r for r in world["records"]}
    assert set(scores) == {u for u, r in by_uid.items() if r.split in ("dev", "test")}   # train·external 없음
    assert not any(uid.startswith("ext-set:") for uid in scores)
    for uid in world["missing"]:
        assert scores[uid]["score"] == "" and scores[uid]["reason_code"] == "insufficient_motion"
    fake = [float(s["score"]) for u, s in scores.items() if s["score"] and by_uid[u].label == "fake"]
    real = [float(s["score"]) for u, s in scores.items() if s["score"] and by_uid[u].label == "real"]
    assert np.mean(fake) > np.mean(real)                   # 심은 신호를 배웠다(합성 데이터)
    assert min(fake + real) < 0 or max(fake + real) > 1    # 확률이 아니라 원시 margin이다


def test_training_is_reproducible(world):
    assert train(world) == 0
    first = (world["dir"] / "out" / "scores.csv").read_text()
    assert train(world, **{"--out-dir": world["dir"] / "out2"}) == 0
    assert (world["dir"] / "out2" / "scores.csv").read_text() == first


def test_scores_feed_the_evaluation_pipeline(world):
    assert train(world) == 0
    scores = world["dir"] / "out" / "scores.csv"
    threshold = world["dir"] / "threshold.json"
    assert run.main(["fit-threshold", "--manifest", str(world["manifest"]), "--scores", str(scores),
                     "--model-id", "motionphys-full-lgbm", "--out", str(threshold), "--lock", str(world["lock"])]) == 0
    report = world["dir"] / "report.json"
    assert run.main(["evaluate", "--manifest", str(world["manifest"]), "--scores", str(scores),
                     "--threshold", str(threshold), "--split", "test", "--out", str(report),
                     "--lock", str(world["lock"]), "--n-boot", "30"]) == 0
    out = json.loads(report.read_text())
    assert out["selective"]["abstained_by_reason"] == {"insufficient_motion": 5}
    assert out["overall"]["roc_auc"]["value"] > 0.8        # 합성 데이터에서의 값. 성능이 아니다


def test_leaky_manifest_is_not_trained_on(world, capsys):
    records = manifest.read_manifest(world["manifest"])
    dev = next(r for r in records if r.split == "dev")
    leaky = world["dir"] / "leaky.csv"
    manifest.write_manifest(leaky, records + [Record("synth", "leak", "synth/leak.mp4", "real", dev.source_recording_id, split="train")])
    assert train(world, **{"--manifest": leaky}) == 1
    assert "group_spans_splits" in capsys.readouterr().err
    assert not (world["dir"] / "out" / "model.txt").exists()


def test_external_data_cannot_be_moved_into_train(world, capsys):
    records = [r.with_split("train") if r.dataset_id == "ext-set" else r for r in manifest.read_manifest(world["manifest"])]
    moved = world["dir"] / "moved.csv"
    manifest.write_manifest(moved, records)
    assert train(world, **{"--manifest": moved}) == 1
    assert "external_dataset_in_internal_split" in capsys.readouterr().err


def test_train_needs_both_classes_and_known_videos(world, capsys):
    only_real = world["dir"] / "only_real.csv"
    manifest.write_manifest(only_real, [r for r in manifest.read_manifest(world["manifest"])
                                        if not (r.split == "train" and r.label == "fake")])
    assert train(world, **{"--manifest": only_real}) == 1
    with world["features"].open("a", newline="") as f:
        csv.writer(f).writerow(["synth", "ghost", "completed", "", *["0.0"] * DIM])
    assert train(world) == 1
    assert "manifest에 없는" in capsys.readouterr().err


def test_partially_empty_feature_row_is_rejected(tmp_path):
    path = tmp_path / "f.csv"
    path.write_text("dataset_id,video_id,status,reason_code,f0,f1\nsynth,a,completed,,1.0,\n")
    with pytest.raises(train_lgbm.TrainError):
        train_lgbm.read_features(path)
    path.write_text("dataset_id,video_id,status,reason_code,f0,f1\nsynth,a,insufficient_input,insufficient_motion,,\n")
    feats, dim = train_lgbm.read_features(path)
    assert dim == 2 and feats["synth:a"]["x"] is None      # 특징 없음은 None이다. 0이 아니다


# ---------- 압축 측정 스크립트의 순수 함수 ----------

def test_compression_spike_uses_software_encoder_and_argument_list(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import motionphys_compression_spike as spike

    cmd = spike.encode_command(tmp_path / "a b.mp4", tmp_path / "out.mp4", 28)
    assert isinstance(cmd, list) and cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-c:v") + 1] == "libx264" and cmd[cmd.index("-crf") + 1] == "28"
    assert not any("videotoolbox" in part for part in cmd)
    assert str(tmp_path / "a b.mp4") in cmd
    assert spike.CRFS == (20, 28, 34)


def test_relative_change_skips_zero_baselines():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import motionphys_compression_spike as spike

    rel = spike.relative_change([2.0, 0.0, -4.0], [3.0, 1.0, -2.0])
    assert rel[0] == pytest.approx(0.5) and np.isnan(rel[1]) and rel[2] == pytest.approx(0.5)
    names = ["L8.jerk.mean.median", "L8.jerk.std.mean", "L8.curvature.mean.median"]
    out = spike.compare(names, [1.0, 2.0, 0.0], [1.5, 2.0, 1.0])
    assert out["by_quantity"]["jerk"]["features_compared"] == 2
    assert out["by_quantity"]["jerk"]["median_abs_rel_change"] == pytest.approx(0.25)
    assert out["by_quantity"]["curvature"]["median_abs_rel_change"] is None   # 견줄 수 없으면 null
    assert out["selected"]["L8.jerk.mean.median"]["rel_change"] == pytest.approx(0.5)
    assert out["selected"]["L8.curvature.mean.median"]["rel_change"] is None
