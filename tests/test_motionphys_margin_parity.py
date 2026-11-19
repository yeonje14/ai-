"""MotionPhys margin: 서버 경로(infer_axis)와 학습 쪽 predict(raw_score=True)가 같은 입력에서 같은 값인지.

실제 두 venv를 쓴다. 학습은 research/training/.venv에서 research/training/train.py를 합성 특징으로 그대로 돌리고,
서버 쪽은 research/motionphys/.venv에서 infer_axis.py(_margin)가 그 모델 파일로 margin을 낸다.
학습 쪽 값은 train.py가 메모리의 최종 모델로 dev·test에 낸 점수(scores/M-*.csv, repr)다.
특징 추출(영상 → 특징)만 합성 특징으로 바꾸고, 그 뒤(margin 계산·JSON·parse_result)는 실제 코드다.
마지막 테스트는 실제 영상 A에서 서버 어댑터가 추출한 특징과 margin을 학습 venv의 예측과 비교한다.
수치는 성능이 아니다. venv(또는 샘플·모델 파일)가 없으면 건너뛴다.
"""
import csv
import json
import os
import subprocess
from pathlib import Path

import pytest

from server.axes.physics import motionphys
from server.axes.physics.motionphys import MotionPhysConfig, run_motionphys
from training import synth

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAIN_PY = REPO_ROOT / "research/training/.venv/bin/python"
TRAIN = REPO_ROOT / "research/training/train.py"
MOTION_PY = REPO_ROOT / "research/motionphys/.venv/bin/python"
MOTION_DIR = REPO_ROOT / "research/motionphys"
SAMPLE = REPO_ROOT / "data/research/samples/A.MOV"
LANDMARKER = REPO_ROOT / "data/models/motionphys/face_landmarker.task"
VARIANTS = motionphys.VARIANTS
# 실제 추출기의 full·face_roi 특징 차원(research/motionphys/extract.py feature_names). 합성도 같은 차원으로 학습한다
DIM = 504

needs_venvs = pytest.mark.skipif(not (TRAIN_PY.is_file() and MOTION_PY.is_file()),
                                 reason="research/training/.venv 또는 research/motionphys/.venv 없음")

# 특징 추출만 합성 값으로 바꾸는 실행기 머리말. infer_axis.run·_margin·main은 그대로 쓴다.
SHIM_HEAD = f'''import json, sys
from pathlib import Path
sys.path.insert(0, {str(MOTION_DIR)!r})
import extract, infer_axis
COUNTS = {{s: {{"valid_trajectories": 100, "moving_trajectories": 100}} for s in infer_axis.SCALES}}
current = {{}}
def fake_extract(video, segments, variant):
    vec = current.get(variant)
    if vec is None:
        return {{"status": "insufficient_input", "reason_code": "insufficient_motion", "features": None}}
    return {{"status": "completed", "reason_code": None, "features": vec, "by_scale": COUNTS,
             "by_region": {{r: COUNTS for r in ("head", "brows", "lips")}}, "face_detection_rate": 1.0}}
extract.extract = fake_extract
'''

PREDICT = '''import json, sys
import lightgbm as lgb, numpy as np
model, rows = sys.argv[1], json.loads(open(sys.argv[2]).read())
booster = lgb.Booster(model_file=model)
print(json.dumps([float(v) for v in booster.predict(np.array(rows, dtype=np.float64), raw_score=True)]))
'''


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    if not (TRAIN_PY.is_file() and MOTION_PY.is_file()):
        pytest.skip("research/training/.venv 또는 research/motionphys/.venv 없음")
    folder = tmp_path_factory.mktemp("margin")
    data = folder / "data"
    synth.write(synth.SynthConfig(identities=60, signal={"waverep": 1.5, "full": 1.0, "face_roi": 1.0,
                                                         "face_motion": 1.0},
                                  missing={"full": 0.1}, motion_dim=DIM, seed=11), data)
    conf = json.loads((REPO_ROOT / "configs/training.json").read_text(encoding="utf-8"))
    conf["dev_compression_conditions"] = ["original"]
    (folder / "config.json").write_text(json.dumps(conf), encoding="utf-8")
    run = folder / "run"
    proc = subprocess.run([str(TRAIN_PY), str(TRAIN), "--manifest", str(data / "manifest.csv"), "--features", str(data),
                           "--config", str(folder / "config.json"), "--out", str(run)],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=600)
    assert proc.returncode == 0, proc.stderr
    features = {}
    with (data / "features.jsonl").open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            features[row["uid"]] = row["axes"]["motionphys"]["variants"]
    return folder, run, features


def training_scores(run: Path, variant: str) -> dict[str, float]:
    """train.py가 메모리의 최종 모델로 dev·test에 낸 raw margin(repr로 저장)."""
    with (run / "scores" / f"M-{variant}.csv").open(newline="", encoding="utf-8") as f:
        return {f"{r['dataset_id']}:{r['video_id']}": float(r["score"]) for r in csv.DictReader(f) if r["score"]}


@needs_venvs
def test_server_margin_equals_training_raw_score_on_every_dev_test_row(trained, tmp_path):
    _, run, features = trained
    rows = []
    for variant in VARIANTS:
        model = run / "models" / f"motionphys-{variant}.txt"
        scores = training_scores(run, variant)
        assert len(scores) >= 30  # dev·test에 비교할 영상이 충분히 있다
        rows += [{"uid": uid, "variant": variant, "model": str(model), "features": features[uid][variant]["features"],
                  "expected": s} for uid, s in sorted(scores.items())]
    (tmp_path / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    shim = tmp_path / "batch.py"
    shim.write_text(SHIM_HEAD + '''
rows = json.loads(Path(sys.argv[1]).read_text())
outs = []
for row in rows:
    current.clear()
    current[row["variant"]] = row["features"]
    outs.append(infer_axis.run({"video": "unused", "segments": [[0.0, 1.0]],
                                "margin_model": {"variant": row["variant"], "path": row["model"]}}))
Path(sys.argv[2]).write_text(json.dumps(outs, allow_nan=False))
''')
    proc = subprocess.run([str(MOTION_PY), str(shim), str(tmp_path / "rows.json"), str(tmp_path / "outs.json")],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=600)
    assert proc.returncode == 0, proc.stderr
    outs = json.loads((tmp_path / "outs.json").read_text())
    mismatched = []
    for row, raw in zip(rows, outs, strict=True):
        parsed = motionphys.parse_result(raw, margin_variant=row["variant"])  # 서버 어댑터가 받는 값
        if parsed["margin"] != row["expected"] or parsed["margin_variant"] != row["variant"]:
            mismatched.append((row["variant"], row["uid"], parsed["margin"], row["expected"]))
    counts = ", ".join(f"{v} {sum(r['variant'] == v for r in rows)}" for v in VARIANTS)
    values = [r["expected"] for r in rows]
    print(f"\nmargin parity: {len(rows)} rows ({counts}), mismatched {len(mismatched)},"
          f" range {min(values):.4f}..{max(values):.4f}")
    assert mismatched == []  # 비트 단위로 같다(허용 오차 없음)


@needs_venvs
@pytest.mark.parametrize("variant", VARIANTS)
def test_adapter_process_returns_the_training_margin(trained, tmp_path, variant):
    """서버 어댑터 run_motionphys → 실제 venv의 실행기 프로세스(요청 JSON의 margin_model) → parse_result."""
    _, run, features = trained
    model = run / "models" / f"motionphys-{variant}.txt"
    uid, expected = sorted(training_scores(run, variant).items())[0]
    vec = tmp_path / "vec.json"
    vec.write_text(json.dumps({variant: features[uid][variant]["features"]}))
    shim = tmp_path / "infer_axis_shim.py"
    shim.write_text(SHIM_HEAD + f"current.update(json.loads(Path({str(vec)!r}).read_text()))\n"
                    "sys.exit(infer_axis.main())\n")
    work = tmp_path / "job"
    work.mkdir()
    video = work / "media.mp4"
    video.write_bytes(b"not read: extraction is replaced")
    cfg = MotionPhysConfig(python=MOTION_PY, script=shim, timeout_sec=120, margin_model=(variant, model))
    out = run_motionphys(video, [(0.0, 3.0)], work, cfg)
    assert (out["margin"], out["margin_variant"]) == (expected, variant)
    assert out["raw_score"] is None  # API 점수는 fusion만 채운다
    assert list(work.iterdir()) == [video]


@needs_venvs
def test_real_video_margin_equals_training_venv_prediction(trained, tmp_path):
    """실제 영상 A(2~6초)에서 서버 어댑터가 추출한 full 특징과 margin을, 학습 venv의 같은 모델 예측과 비교한다."""
    if not SAMPLE.is_file() or not LANDMARKER.is_file():
        pytest.skip("샘플 A 또는 MotionPhys 모델 파일 없음")
    _, run, _ = trained
    model = run / "models" / "motionphys-full.txt"
    work = tmp_path / "job"
    work.mkdir()
    video = work / "media.mov"
    os.link(SAMPLE, video) if os.stat(SAMPLE).st_dev == os.stat(work).st_dev else video.write_bytes(SAMPLE.read_bytes())
    out = run_motionphys(video, [(2.0, 6.0)], work, MotionPhysConfig(margin_model=("full", model)),
                         include_features=True)
    full = out["variants"]["full"]
    if full["status"] != "completed":
        pytest.skip(f"A의 full 후보가 completed가 아니다: {full['reason_code']}")
    assert len(full["features"]) == DIM and out["margin_variant"] == "full"
    (tmp_path / "x.json").write_text(json.dumps([full["features"]]))
    script = tmp_path / "predict.py"
    script.write_text(PREDICT)
    proc = subprocess.run([str(TRAIN_PY), str(script), str(model), str(tmp_path / "x.json")],
                          capture_output=True, text=True, cwd=tmp_path, timeout=120)
    assert proc.returncode == 0, proc.stderr
    expected = json.loads(proc.stdout)[0]
    print(f"\nreal A full: server margin {out['margin']!r}, training venv {expected!r}")
    assert out["margin"] == expected
    assert sorted(p.name for p in work.iterdir()) == ["media.mov"]
