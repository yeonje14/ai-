"""독립 감사(2026-11-18): 학습 파이프라인과 서버 관문의 공격 시나리오 (docs/audit-training-pipeline.md).

테스트 이름의 A<번호>는 감사 문서의 발견 번호, OK<번호>는 "시도했지만 문제없던 공격" 번호다.
- 고친 발견: 보통 테스트다. 고치기 전의 코드에서는 실패했다(재현 테스트).
- 감사 때 설계 결정이 필요해 xfail(strict=True)로 남겼던 A9·A10·A11·A16·A17과 지금 동작을 고정했던 A15는
  2026-11-18 사용자 결정(docs/DESIGN.md §15.3)대로 고쳐 보통 테스트로 바꿨다. 지금 xfail은 없다.
- 합성 데이터만 쓴다. 수치는 어떤 모델의 성능도 아니다.
"""
import json
import math
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from server import fusion
from server.axes import AxisContext, alignment, signal as signal_axis
from server.axes.alignment import report as syncnet_report, syncnet
from server.axes.signal import waverep
from server.config import Settings
from training import bundle as bundles, config as training_config, hygiene, serving, synth
from training.datasets import adapters, groups
from training.datasets.manifest import Record, read_manifest, sha256_file, write_manifest
from training.emulator import profiles
from training.evaluation import metrics
from training.evaluation.metrics import Item
from training.features import extract
from training.report import build, decision as rules
from tests.test_feature_extract import env, rows as feature_rows  # noqa: F401 (env는 fixture)
from tests.test_fusion_bundle import assert_abstained, fake_axes, made, pinned  # noqa: F401 (fixture)
from tests.test_gate_worker import run_job
from tests.test_training_report import ADOPTION
from tests.test_training_train import PYTHON, TRAIN, config

REPO_ROOT = Path(__file__).resolve().parent.parent
needs_venv = pytest.mark.skipif(not PYTHON.is_file(), reason="research/training/.venv 없음")
DEEPSPEAK = adapters.load_config(REPO_ROOT / "configs/datasets/deepspeak_v2.json")
LOCK = {"mavos-dd": {"status": "locked"}}
SMALL = synth.SynthConfig(identities=100, signal={"waverep": 1.5, "full": 1.0}, seed=11)


# ---------- 도우미 ----------

def make_data(folder: Path, cfg: synth.SynthConfig, edit_rows=None, keep=None) -> Path:
    """합성 manifest·특징을 쓰고, 필요하면 특징 행이나 manifest 행을 고친 뒤 해시를 다시 맞춘다."""
    synth.write(cfg, folder)
    if keep is not None:
        records = [r for r in read_manifest(folder / "manifest.csv") if keep(r)]
        write_manifest(folder / "manifest.csv", records)
    rows = [json.loads(line) for line in (folder / "features.jsonl").read_text().splitlines()]
    if keep is not None:
        uids = {r.uid for r in read_manifest(folder / "manifest.csv")}
        rows = [r for r in rows if r["uid"] in uids]
    if edit_rows is not None:
        rows = edit_rows(rows)
    (folder / "features.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    meta = json.loads((folder / "features.meta.json").read_text())
    meta.update(features_sha256=sha256_file(folder / "features.jsonl"),
                manifest_sha256=sha256_file(folder / "manifest.csv"))
    (folder / "features.meta.json").write_text(json.dumps(meta))
    return folder


def train_on(data: Path, out: Path, conf: dict) -> subprocess.CompletedProcess:
    path = out.parent / f"{out.name}.config.json"
    path.write_text(json.dumps(conf), encoding="utf-8")
    return subprocess.run([str(PYTHON), str(TRAIN), "--manifest", str(data / "manifest.csv"), "--features", str(data),
                           "--config", str(path), "--out", str(out)],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=300)


def fast_config(**kw) -> dict:
    c = config(**kw)
    c["adoption"] = {**c["adoption"], "n_boot": 200}
    return c


def media_of(short_side: int) -> dict:
    return {"duration_sec": 10.0, "width": short_side * 16 // 9, "height": short_side, "fps": 30.0,
            "rotation": 0, "has_audio": True}


# ================= 시나리오 1. 누수 =================

@needs_venv
@pytest.mark.parametrize("source_short_side, accepted", [(1080, False), (None, False), (1440, True)])
def test_A3_train_refuses_1080p_twin_of_held_out_profile(tmp_path, source_short_side, accepted):
    """짧은 변이 1080px인 원본에서 x264-crf34-1080p는 최종 평가 전용 x264-crf34-source와 같은 바이트다."""
    def add_media(rows):
        for r in rows:
            if "@" not in r["video_id"] and source_short_side is not None:
                r["media"] = media_of(source_short_side)
        return rows

    data = make_data(tmp_path / "d", replace(SMALL, profiles=("x264-crf34-1080p",)), add_media)
    proc = train_on(data, tmp_path / "run", fast_config())
    if accepted:
        assert proc.returncode == 0, proc.stderr
    else:
        assert proc.returncode == 1, "최종 평가 전용 프로파일과 같은 출력의 파생본으로 학습했다"
        assert "x264-crf34-1080p" in proc.stderr and "x264-crf34-source" in proc.stderr


def test_A3_profile_equivalence_rule():
    same = profiles.may_equal_output
    assert same("x264-crf34-1080p", "x264-crf34-source", 1080)
    assert same("x264-crf34-1080p", "x264-crf34-source", None)      # 원본 크기를 모르면 같을 수 있다고 본다
    assert not same("x264-crf34-1080p", "x264-crf34-source", 1440)
    assert not same("x264-crf28-1080p", "x264-crf34-source", 1080)  # CRF가 다르면 다른 파일
    assert same("x264-crf20-720p", "x264-crf20-source", 720)
    assert not same("x264-crf20-720p", "x264-crf20-1080p", 1080)


def test_A8_extract_records_input_hash_for_rows_without_manifest_hash(env):  # noqa: F811
    make, run, _, out = env
    records = make(["a"]) + make(["b"], split="test")
    media = out.parent / "media"
    (media / "b.mp4").write_bytes((media / "a.mp4").read_bytes())  # 다른 이름, 같은 바이트
    run(records)
    r = feature_rows(out)
    assert r["synth:a"]["input_sha256"] == r["synth:b"]["input_sha256"] == sha256_file(media / "a.mp4")


@needs_venv
def test_A8_train_refuses_same_bytes_in_two_splits(tmp_path):
    """어댑터는 영상을 열지 않아 원본 행의 file_hash가 비어 있다. 추출기가 계산한 해시로 막아야 한다."""
    records, _ = synth.generate(SMALL)
    a = next(r for r in records if r.split == "train")
    b = next(r for r in records if r.split == "test")

    def same_bytes(rows):
        for r in rows:
            r["input_sha256"] = {a.uid: "dup", b.uid: "dup"}.get(r["uid"], r["uid"])
        return rows

    data = make_data(tmp_path / "d", SMALL, same_bytes)
    proc = train_on(data, tmp_path / "run", fast_config())
    assert proc.returncode == 1, "같은 바이트의 영상이 train과 test에 있는데 학습했다"
    assert "같은 바이트" in proc.stderr


def test_A7_locked_external_dataset_under_alias_id_is_a_leak():
    for alias in ("mavos_dd", "MAVOS-DD", "mavosdd"):
        rec = Record(alias, "v1", "a.mp4", "fake", "unknown:a.mp4", split="train")
        report = hygiene.check([rec], LOCK)
        assert not report.ok, alias
        assert report.errors[0]["code"] == "external_dataset_alias_in_internal_split"
    assert hygiene.check([Record("deepspeak_v2", "v1", "a.mp4", "fake", "s", split="train")], LOCK).ok


def test_A12_numeric_identity_written_as_float_still_links_real_and_fake():
    """JSON Lines로 내보낼 때 결측이 섞인 정수 열은 12.0이 된다. 같은 인물이 다른 그룹이 되면 안 된다."""
    real = {"video-file": "r.mp4", "type": "real", "split": "train", "identity": 12}
    fake = {"video-file": "f.mp4", "type": "fake", "split": "train", "kind": "lip-sync", "engine": "x",
            "identity-source": 12.0, "identity-target": 12.0, "recording-target": 7.0}
    recs = [adapters.to_record(row, DEEPSPEAK, i)[0] for i, row in enumerate((real, fake))]
    gid = groups.group_ids(recs)
    assert gid[recs[0].uid] == gid[recs[1].uid]
    assert recs[1].source_recording_id == "deepspeak:rec:7"
    # NaN은 값이 아니다. 모든 결측 행을 "nan" 하나로 묶지 않는다
    nan = adapters.to_record({**real, "video-file": "n.mp4", "identity": float("nan")}, DEEPSPEAK, 3)[0]
    assert nan.identity_ids == ()


def test_A11_video_without_identity_or_verified_source_is_an_error_before_training():
    """2026-11-18 결정: 인물 ID와 확인된 원본 계보가 둘 다 없는 내부 분할 행은 학습 전 오류다."""
    rows = [{"video-file": "r0.mp4", "type": "real", "split": "train"},  # 인물 ID 빠짐
            {"video-file": "f0.mp4", "type": "fake", "split": "train", "kind": "lip-sync", "engine": "x",
             "identity-source": 0, "identity-target": 0, "recording-target": 1}]
    records = adapters.convert(rows, {**DEEPSPEAK, "split": {**DEEPSPEAK["split"], "train_fractions": {"train": 1.0}}})
    assert records[0].source_unverified and not records[0].identity_ids
    report = hygiene.check(records, LOCK)
    assert not report.ok
    assert [e["code"] for e in report.errors] == ["ungroupable_video"] and report.errors[0]["examples"] == [records[0].uid]
    # 둘 중 하나라도 있으면 묶을 수 있다. 외부 평가 자료(MAVOS-DD는 원래 인물 ID가 없다)는 이 규칙의 대상이 아니다
    ok = [Record("d", "a", "a.mp4", "real", "unknown:a.mp4", identity_ids=("p",), split="train"),
          Record("d", "b", "b.mp4", "real", "rec-b", split="train"),
          Record("mavos-dd", "c", "c.mp4", "fake", "unknown:c.mp4", split="external")]
    assert hygiene.check(ok, LOCK).ok


# ================= 시나리오 2. 임계값·선택 오염 =================

def test_A6_config_requires_out_of_range_profiles_disjoint_from_dev_and_held_out():
    base = json.loads((REPO_ROOT / "configs/training.json").read_text(encoding="utf-8"))
    assert base["out_of_range_compression_profiles"] == ["x264-crf20-480p", "x264-crf28-480p", "x264-crf34-480p"]
    for bad in (["x264-crf28-720p"], ["x264-crf34-source"], ["original"], "x264-crf28-480p", [""]):
        with pytest.raises(training_config.ConfigError):
            training_config.validate({**base, "out_of_range_compression_profiles": bad})


# ================= 시나리오 3. 관문 우회 =================

def rejection_code(settings) -> str:
    """서버와 같은 인자로 묶음을 불러 거부 이유를 돌려준다(load_active는 이유를 로그에만 남긴다)."""
    pin = json.loads(settings.fusion_bundle_config_path.read_text())
    with pytest.raises(bundles.BundleError) as e:
        bundles.load(settings.fusion_bundle_dir / pin["bundle_id"], pin["digest"], settings.allow_synthetic_bundle,
                     expected_config=training_config.load(settings.training_config_path))
    return e.value.code


def _repin(folder: Path, pin: Path, body: dict) -> None:
    body = {k: v for k, v in body.items() if k != "digest"}
    body["digest"] = bundles._digest(body)
    (folder / "bundle.json").write_text(json.dumps(body))
    pin.write_text(json.dumps({"bundle_id": "b1", "digest": body["digest"]}))


@needs_venv
def test_A1_report_listing_an_ungated_candidate_as_servable_is_rejected(pinned, queue, registry, monkeypatch, made):  # noqa: F811
    """서빙하지 않는 단일 MotionPhys 후보(M-full)를 리포트의 서빙 목록에 대체 후보로 끼워 넣고 해시·digest를 모두 다시 맞춘다."""
    settings, _, folder = pinned
    run = made[0] / "run"
    report = json.loads((folder / "report.json").read_text())
    assert "M-full" in report["candidates"] and "M-full" not in report["decision"]["servable_candidates"]
    report["decision"]["servable_candidates"].append("M-full")
    (folder / "report.json").write_text(json.dumps(report))
    for rel in ("models/M-full.json", "thresholds/M-full.json"):
        shutil.copyfile(run / rel, folder / rel)
    body = json.loads((folder / "bundle.json").read_text())
    body["files"].update({rel: bundles._sha256(folder / rel)
                          for rel in ("report.json", "models/M-full.json", "thresholds/M-full.json")})
    body["candidates"].append({"candidate": "M-full", "axes": ["physics"], "motion_variant": "full", "role": "fallback"})
    _repin(folder, settings.fusion_bundle_config_path, body)
    assert fusion.load_active(settings) is None
    assert rejection_code(settings) == "report_inconsistent"
    fake_axes(monkeypatch, signal=4.0, physics=6.0, alignment=True)
    _, job = run_job(queue, registry, settings)
    assert_abstained(job.result)


@needs_venv
def test_A9_bundle_roles_must_match_the_report(pinned):  # noqa: F811
    """선택 후보와 대체 후보의 역할을 바꾼 묶음(digest까지 다시 맞춤)은 쓰지 않는다."""
    settings, _, folder = pinned
    body = json.loads((folder / "bundle.json").read_text())
    for c in body["candidates"]:
        c["role"] = "fallback" if c["role"] == "primary" else "primary"
    _repin(folder, settings.fusion_bundle_config_path, body)
    assert fusion.load_active(settings) is None
    assert rejection_code(settings) == "candidate_roles_mismatch"


@pytest.fixture(scope="module")
def hold_run(tmp_path_factory):
    """신호가 없는 합성 데이터의 학습 결과와 보류 리포트."""
    if not PYTHON.is_file():
        pytest.skip("research/training/.venv 없음")
    folder = tmp_path_factory.mktemp("hold")
    c = fast_config()
    data = make_data(folder / "d", replace(SMALL, signal={}, seed=5))
    assert train_on(data, folder / "run", c).returncode == 0
    report = build.build(data / "manifest.csv", folder / "run", committed_config=c)
    assert report["decision"]["decision"] == "hold"
    return folder / "run", c, report, {"manifest": data / "manifest.csv", "features": data}


def test_A1_hold_report_forged_to_waverep_only_cannot_become_a_bundle(tmp_path, hold_run):
    """신호 없는 데이터의 보류 리포트를 판단 문자열만 'WaveRep 단독'으로 고쳐 묶음을 만들려 한다."""
    run, c, report, data = hold_run
    report = json.loads(json.dumps(report))
    report["decision"].update(decision="waverep_only", decision_ko="WaveRep 단독", primary="W", servable_candidates=["W"])
    (tmp_path / "forged.json").write_text(json.dumps(report))
    with pytest.raises(bundles.BundleError) as e:
        bundles.create(run, tmp_path / "forged.json", tmp_path / "fusion/b1", expected_config=c, **data)
    assert e.value.code == "report_inconsistent"


def test_A16_report_with_consistently_forged_metrics_cannot_become_a_bundle(tmp_path, hold_run):
    """2026-11-18 결정: 묶음을 만들기 전에 같은 입력으로 학습·리포트를 다시 돌려 비교한다."""
    run, c, report, data = hold_run
    report = json.loads(json.dumps(report))
    w = report["candidates"]["W"]["test"]["overall"]
    w["roc_auc"].update(value=0.8, ci_low=0.7)
    w["fpr"].update(value=0.03, ci_high=0.05)
    w["fpr_exact_upper"]["value"] = 0.05
    report["decision"] = rules.rederive(report, c["adoption"])  # 고친 숫자에 맞는 판단(WaveRep 단독)
    assert report["decision"]["decision"] == "waverep_only"
    (tmp_path / "forged.json").write_text(json.dumps(report))
    with pytest.raises(bundles.BundleError) as e:
        bundles.create(run, tmp_path / "forged.json", tmp_path / "fusion/b1", expected_config=c, **data)
    assert e.value.code == "not_reproducible" and "리포트" in str(e.value)
    assert not (tmp_path / "fusion/b1").exists()


@needs_venv
def test_A16_tampered_run_folder_is_not_reproducible(tmp_path, made):  # noqa: F811
    """리포트는 그대로 두고 학습 결과 폴더의 점수 파일을 고치면, 다시 학습한 결과와 달라 묶음을 만들지 않는다."""
    folder, _ = made
    shutil.copytree(folder / "run", tmp_path / "run")
    (tmp_path / "run/oof/W.csv").chmod(0o644)
    with (tmp_path / "run/oof/W.csv").open("a") as f:
        f.write("\n")
    with pytest.raises(bundles.BundleError) as e:
        bundles.create(tmp_path / "run", folder / "rep/report.json", tmp_path / "b",
                       expected_config=json.loads((folder / "training.json").read_text()),
                       manifest=folder / "run-data/manifest.csv", features=folder / "run-data")
    assert e.value.code == "not_reproducible" and "oof/W.csv" in str(e.value)


@needs_venv
def test_A2_run_trained_with_uncommitted_config_cannot_become_a_bundle(tmp_path):
    """채택 기준을 느슨하게 바꾼 설정으로 학습하면 리포트가 통과해도 묶음이 되지 않는다."""
    committed = fast_config()
    loose = json.loads(json.dumps(committed))
    loose["adoption"].update(g2_min_auc_ci_low=0.0, max_test_fpr_ci_high=1.0, min_tpr_gain_ci_low=-1.0)
    data = make_data(tmp_path / "d", replace(SMALL, seed=5))
    assert train_on(data, tmp_path / "run", loose).returncode == 0
    report = build.build(data / "manifest.csv", tmp_path / "run", committed_config=committed)
    assert report["decision"]["decision"] != "hold"          # 느슨한 기준으로는 통과한다
    assert report["training_config_matches_committed"] is False
    assert "커밋된 configs/training.json과 다르다" in build.to_markdown(report)
    (tmp_path / "rep.json").write_text(json.dumps(report))
    with pytest.raises(bundles.BundleError) as e:
        bundles.create(tmp_path / "run", tmp_path / "rep.json", tmp_path / "fusion/b1", expected_config=committed,
                       manifest=data / "manifest.csv", features=data)
    assert e.value.code == "config_not_committed"


@needs_venv
def test_A2_server_rejects_bundle_when_committed_training_config_changes(pinned, queue, registry, monkeypatch):  # noqa: F811
    settings, _, _ = pinned
    assert fusion.load_active(settings) is not None
    conf = json.loads(settings.training_config_path.read_text())
    conf["adoption"]["max_test_fpr_ci_high"] = 0.2  # 사전 고정 기준이 바뀌었다 → 다시 검증해야 한다
    settings.training_config_path.write_text(json.dumps(conf))
    assert fusion.load_active(settings) is None
    assert rejection_code(settings) == "config_not_committed"


@needs_venv
@pytest.mark.parametrize("case", ["model_not_in_files", "report_not_in_files", "motion_variant_path"])
def test_A5_every_file_the_server_reads_is_covered_by_the_digest(pinned, case):  # noqa: F811
    settings, _, folder = pinned
    body = json.loads((folder / "bundle.json").read_text())
    if case == "model_not_in_files":   # digest에서 빼 두면 고정한 뒤에 계수를 바꿀 수 있다
        del body["files"]["models/W+M.json"]
        _repin(folder, settings.fusion_bundle_config_path, body)
        m = json.loads((folder / "models/W+M.json").read_text())
        m["model"]["coef"] = [c * 10 for c in m["model"]["coef"]]
        (folder / "models/W+M.json").write_text(json.dumps(m))
    elif case == "report_not_in_files":
        del body["files"]["report.json"]
        _repin(folder, settings.fusion_bundle_config_path, body)
    else:
        body["candidates"][0]["motion_variant"] = "../../../outside"
        _repin(folder, settings.fusion_bundle_config_path, body)
    assert fusion.load_active(settings) is None
    assert rejection_code(settings) == ("motion_variant_invalid" if case == "motion_variant_path" else "file_not_pinned")


def _waverep_out(logits, device_used):
    return {"status": "completed", "reason_code": None, "raw_score": None,
            "raw_metrics": {"frame_logit": waverep.summarize_logits(logits)},
            "frames": [{"index": i, "logit": v} for i, v in enumerate(logits)],
            "model": {"device_used": device_used}, "model_version": waverep.MODEL_VERSION, "video": {}}


def _ctx(tmp_path, bundle, **settings):
    return AxisContext(job_dir=tmp_path, settings=replace(Settings(), **settings), media_path=tmp_path / "m.mp4",
                       segments=((0.0, 4.0),), bundle=bundle)


def test_A4_server_withholds_waverep_input_when_device_fell_back(tmp_path, monkeypatch):
    bundle = SimpleNamespace(waverep_score="logit_median")
    monkeypatch.setattr(signal_axis, "run_waverep", lambda *a, **k: _waverep_out([1.0, 2.0, 3.0], "cpu"))
    ctx = _ctx(tmp_path, bundle, waverep_device="mps")
    assert signal_axis.run(ctx)["status"] == "completed"  # 축 결과는 그대로다
    assert "W" not in ctx.fusion_inputs, "MPS로 학습한 묶음에 CPU 대체 점수를 넣었다"
    monkeypatch.setattr(signal_axis, "run_waverep", lambda *a, **k: _waverep_out([1.0, 2.0, 3.0], "mps"))
    ctx = _ctx(tmp_path, bundle, waverep_device="mps")
    signal_axis.run(ctx)
    assert ctx.fusion_inputs["W"] == 2.0


def _syncnet_raw(device_used):
    raw = syncnet_report.parse_result({"schema_version": 1, "segments": [
        {"start_sec": 0.0, "end_sec": 4.0, "status": "completed",
         "tracks": [{"track_index": 0, "lse_c": 5.0, "lse_d": 8.0, "offset_frames": 1}]}]}, [[0.0, 4.0]])
    raw["device_used"] = device_used
    return raw


def test_A4_server_withholds_syncnet_input_when_device_fell_back(tmp_path, monkeypatch):
    monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, **k: _syncnet_raw("cpu"))
    ctx = _ctx(tmp_path, SimpleNamespace(), syncnet_device="mps")
    assert alignment.run(ctx)["status"] == "completed"
    assert not any(k.startswith("S.") for k in ctx.fusion_inputs)
    monkeypatch.setattr(syncnet, "run_syncnet", lambda *a, **k: _syncnet_raw("mps"))
    ctx = _ctx(tmp_path, SimpleNamespace(), syncnet_device="mps")
    alignment.run(ctx)
    assert ctx.fusion_inputs["S.lse_c_median"] == 5.0


def test_A4_extract_does_not_label_fallback_features_with_requested_device(tmp_path, monkeypatch):
    settings = extract.default_settings(replace(Settings(), waverep_device="mps", syncnet_device="mps"))
    monkeypatch.setattr(extract, "run_waverep", lambda *a, **k: _waverep_out([1.0, 2.0], "cpu"))
    w = extract.run_waverep_axis(tmp_path / "m.mp4", tmp_path, [[0.0, 4.0]], settings)
    assert (w["status"], w["reason_code"], w["frame_logits"]) == ("error", "device_mismatch", None)
    monkeypatch.setattr(extract, "run_syncnet", lambda *a, **k: _syncnet_raw("cpu"))
    s = extract.run_syncnet_axis(tmp_path / "m.mp4", tmp_path, [[0.0, 4.0]], settings)
    assert (s["status"], s["reason_code"]) == ("error", "device_mismatch")
    assert syncnet_report.fusion_features(s) is None
    monkeypatch.setattr(extract, "run_syncnet", lambda *a, **k: _syncnet_raw("mps"))
    s = extract.run_syncnet_axis(tmp_path / "m.mp4", tmp_path, [[0.0, 4.0]], settings)
    assert s["status"] == "completed" and s["device_used"] == "mps"


def test_A4_extract_recomputes_cached_result_from_another_device(env):  # noqa: F811
    """장치 확인 전에 쓴 캐시(또는 대체 장치의 결과)는 그 특징 버전의 값으로 다시 쓰지 않는다."""
    make, run, calls, out = env
    records = make(["a"])
    run(records)
    path = next((out / "cache/waverep").glob("*.json"))
    cached = json.loads(path.read_text())
    assert cached["result"]["device_used"] == "mps"
    cached["result"]["device_used"] = "cpu"
    path.write_text(json.dumps(cached))
    calls.clear()
    run(records)
    assert ("waverep", b"a") in calls and ("syncnet", b"a") not in calls


# ================= 시나리오 4. 서버·학습 불일치 =================

@pytest.mark.parametrize("name", ["logit_median", "logit_mean", "logit_q75"])
def test_A13_server_waverep_input_equals_training_feature_for_every_allowed_aggregate(tmp_path, monkeypatch, name):
    logits = [0.5, -1.25, 3.0, 2.0, 7.5]
    monkeypatch.setattr(signal_axis, "run_waverep", lambda *a, **k: _waverep_out(logits, "mps"))
    ctx = _ctx(tmp_path, SimpleNamespace(waverep_score=name), waverep_device="mps")
    signal_axis.run(ctx)
    row = extract.summarize_video(Record("s", "v", "v.mp4", "real", "s"),
                                  {"waverep": {"status": "completed", "reason_code": None, "frame_logits": logits}})
    assert ctx.fusion_inputs.get("W") == row["axes"]["waverep"][name]


def test_A14_syncnet_status_rule_is_part_of_feature_version():
    """짧은 구간 규칙이 바뀌면 특징 버전이 바뀌어 옛 규칙의 캐시·묶음을 쓰지 않아야 한다."""
    version = extract.feature_version(extract.default_settings())
    assert version["syncnet"]["status_rule"] == syncnet_report.STATUS_RULE


def test_OK4_syncnet_short_segment_rule_and_waverep_median_are_shared_with_training():
    raw = syncnet_report.parse_result({"schema_version": 1, "segments": [
        {"start_sec": 0.0, "end_sec": 1.0, "status": "insufficient_input", "reason_code": "segment_too_short"},
        {"start_sec": 2.0, "end_sec": 6.0, "status": "completed",
         "tracks": [{"track_index": 0, "lse_c": 5.0, "lse_d": 8.0, "offset_frames": -2},
                    {"track_index": 1, "lse_c": 7.0, "lse_d": 6.0, "offset_frames": 4}]}]}, [[0.0, 1.0], [2.0, 6.0]])
    assert raw["status"] == "completed"
    row = extract.summarize_video(Record("s", "v", "v.mp4", "real", "s"),
                                  {"syncnet": {"status": raw["status"], "reason_code": raw["reason_code"],
                                               "segments": raw["segments"]}})
    server = syncnet_report.fusion_features(raw)
    assert {k: row["axes"]["syncnet"][k] for k in server} == server == {
        "lse_c_median": 6.0, "lse_d_median": 7.0, "abs_offset_median": 3.0}


def test_OK4_motionphys_margin_uses_same_lightgbm_and_numpy_as_training():
    def pins(path):
        return {line.split("==")[0].lower(): line.split("==")[1] for line in path.read_text().split()
                if "==" in line}
    train = pins(REPO_ROOT / "research/training/requirements.lock.txt")
    motion = pins(REPO_ROOT / "research/motionphys/requirements.lock.txt")
    assert train["lightgbm"] == motion["lightgbm"] and train["numpy"] == motion["numpy"]
    text = (REPO_ROOT / "research/motionphys/infer_axis.py").read_text()
    assert "raw_score=True" in text  # 학습 train.py도 predict(..., raw_score=True)
    assert "raw_score=True" in TRAIN.read_text()


# ================= 시나리오 5. 통계 함정 =================

def test_OK5_bootstrap_resamples_whole_groups_not_rows():
    items = [Item(f"{g}-{i}", "real" if g % 2 else "fake", f"g{g}", score=float(g)) for g in range(10) for i in range(3)]
    seen = []

    def stat(drawn):
        counts = {}
        for it in drawn:
            counts[it.group] = counts.get(it.group, 0) + 1
        seen.append(counts)
        return {"x": 0.0}

    metrics.group_bootstrap(items, stat, n_boot=200, seed=1)
    assert all(n % 3 == 0 for counts in seen for n in counts.values())  # 그룹의 영상 3개가 늘 함께 뽑힌다
    assert all(sum(c.values()) == 30 for c in seen)  # 매번 그룹 10개를 복원 추출한다(영상 30개)
    assert any(len(c) < 10 for c in seen)  # 같은 그룹이 두 번 뽑히는 회차가 있다(복원 추출)


def test_OK5_paired_difference_uses_the_same_resample_for_both_candidates():
    items = [Item(f"v{i}", "fake" if i % 2 else "real", f"g{i // 2}", score=float(i % 7)) for i in range(60)]
    out = rules.paired_difference(items, items, 3.0, 3.0, n_boot=300, seed=2)
    for m in ("tpr", "fpr", "roc_auc", "coverage"):  # 따로 뽑았다면 같은 후보끼리도 차이가 0이 아니다
        assert out[m]["ci_low"] == out[m]["ci_high"] == 0.0


def test_A10_fpr_upper_bound_gate_does_not_pass_on_too_few_real_videos():
    """2026-11-18 결정: FPR 관문은 그룹 bootstrap 상한과 Clopper–Pearson 정확 상한 중 큰 값으로 본다.
    정확 상한은 n = 진짜 그룹 수, k = n × 영상 단위 FPR이다(오탐 0건이면 k = 0)."""
    items = [Item(f"r{i}", "real", f"r{i}", score=0.0) for i in range(20)] + \
            [Item(f"f{i}", "fake", f"f{i}", score=1.0) for i in range(20)]
    ev = metrics.evaluate(items, threshold=0.5, n_boot=1000, seed=1)
    assert ev["overall"]["fpr"]["ci_high"] == 0.0  # bootstrap 상한은 오탐 0건에서 0으로 무너진다
    exact = ev["overall"]["fpr_exact_upper"]
    assert (exact["n_real_groups"], exact["k_effective"]) == (20, 0.0)
    assert exact["value"] == pytest.approx(0.16843347098308528, rel=1e-9)  # scipy beta.ppf(0.975, 1, 20)
    fpr_gate = rules.own_gates(ev, ADOPTION)[1]
    assert fpr_gate["value"] == exact["value"] and not fpr_gate["passed"], "진짜 20개, 오탐 0건으로 FPR ≤ 10%를 입증했다고 본다"
    # 독립 진짜 그룹이 36개면 오탐 0건으로 10% 이하를 보일 수 있다
    many = [Item(f"r{i}", "real", f"r{i}", score=0.0) for i in range(36)] + items[20:]
    assert rules.own_gates(metrics.evaluate(many, 0.5, n_boot=200, seed=1), ADOPTION)[1]["passed"]


def test_A10_exact_upper_uses_real_groups_and_video_level_fpr():
    # 진짜 그룹 80개(그룹마다 영상 4개), 영상 단위 FPR 5%(오탐 16/320) → k = 80 × 0.05 = 4
    items = [Item(f"r{g}-{i}", "real", f"g{g}", score=1.0 if g < 16 and i == 0 else 0.0)
             for g in range(80) for i in range(4)]
    ev = metrics.evaluate(items + [Item("f", "fake", "h", score=1.0)], threshold=0.5, n_boot=50, seed=1)
    exact = ev["overall"]["fpr_exact_upper"]
    assert (exact["n_real_groups"], exact["k_effective"]) == (80, pytest.approx(4.0))
    assert exact["value"] == pytest.approx(0.12309873644315293, rel=1e-9)
    # 그룹 안 오탐 수가 아니라 영상 단위 FPR을 쓴다: "오탐이 있는 그룹 수"(16)로 세지 않는다
    assert ev["overall"]["fpr"]["value"] == pytest.approx(0.05)


@pytest.mark.parametrize("k, n, expected", [
    (0, 20, 0.16843347098308528), (0, 36, 0.09739375591449193), (4, 80, 0.12309873644315293),
    (7.5, 150, 0.09810235167941703), (1.6, 80, 0.07973684236213112), (19, 20, 0.9987349105020502),
    (0.5, 3, 0.8232639028687426), (10, 1000, 0.01831324305511245),
])
def test_A10_clopper_pearson_upper_matches_scipy(k, n, expected):
    """값은 scipy.stats.beta.ppf(0.975, k + 1, n - k)로 미리 계산했다(trinity에는 scipy가 없다)."""
    assert metrics.clopper_pearson_upper(k, n, 0.95) == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert metrics.clopper_pearson_upper(n, n, 0.95) == 1.0


def test_A17_tpr_gain_is_not_produced_by_abstaining_on_hard_fakes():
    """2026-11-18 결정: TPR 차이는 두 후보가 모두 점수를 낸 영상에서 계산한다.
    결합이 어려운 가짜에서 보류해도, 함께 점수를 낸 영상에서 똑같으면 TPR 이득이 아니다."""
    real = [Item(f"r{i}", "real", f"r{i}", score=0.0) for i in range(40)]
    easy = [Item(f"e{i}", "fake", f"e{i}", score=1.0) for i in range(30)]
    hard = [Item(f"h{i}", "fake", f"h{i}", score=0.0) for i in range(10)]
    single = real + easy + hard
    fused = real + easy + [replace(it, score=None) for it in hard]  # 어려운 가짜 10개에서 보류
    out = rules.paired_difference(fused, single, 0.5, 0.5, n_boot=300, seed=3)
    assert out["coverage"]["value"] == pytest.approx(-0.125)
    assert not out["tpr"]["ci_low"] > 0, "판정 제공 비율을 줄인 만큼 TPR이 오른 것으로 셌다"
    assert out["tpr"]["value"] == out["tpr"]["ci_low"] == out["tpr"]["ci_high"] == 0.0
    assert out["tpr"]["basis"] == "both_scored"
    # 함께 점수를 낸 영상에서 실제로 더 잘 잡으면 이득으로 센다
    better = real + easy + [replace(it, score=1.0) for it in hard]
    gain = rules.paired_difference(better, single, 0.5, 0.5, n_boot=300, seed=3)["tpr"]
    assert gain["value"] == pytest.approx(0.25) and gain["ci_low"] > 0


# ================= 시나리오 6. 정직성 · 480p · 서빙 모집단 =================

@pytest.fixture(scope="module")
def run_out_of_range(tmp_path_factory):
    """test에 480p(운영 범위 밖)와 최종 평가 전용 프로파일이 섞인 합성 실행. WaveRep은 480p에서 unsupported_input."""
    if not PYTHON.is_file():
        pytest.skip("research/training/.venv 없음")
    folder = tmp_path_factory.mktemp("oor")
    cfg = replace(SMALL, missing={"syncnet": 0.3}, profiles=("x264-crf28-480p", "x264-crf34-source"))

    def waverep_unsupported_at_480p(rows):
        for r in rows:
            if r["video_id"].endswith("@x264-crf28-480p"):
                r["axes"]["waverep"] = {"status": "unsupported_input", "reason_code": "low_resolution", "frames": 0,
                                        "logit_median": None, "logit_mean": None, "logit_q75": None}
        return rows

    # 최종 평가 전용 파생본은 test에만 둔다(train·dev에 있으면 학습이 거부한다)
    data = make_data(folder / "d", cfg, waverep_unsupported_at_480p,
                     keep=lambda r: r.compression_profile_id != "x264-crf34-source" or r.split == "test")
    c = fast_config()
    assert train_on(data, folder / "run", c).returncode == 0
    return data, folder / "run", build.build(data / "manifest.csv", folder / "run", committed_config=c)


def test_A6_out_of_range_480p_is_excluded_from_test_gates_and_reported_separately(run_out_of_range):
    data, _, report = run_out_of_range
    test = [r for r in read_manifest(data / "manifest.csv") if r.split == "test"]
    low = [r for r in test if r.compression_profile_id == "x264-crf28-480p"]
    assert low
    for name, c in report["candidates"].items():
        assert "x264-crf28-480p" not in c["test"]["by_compression"], name
        held = [r for r in test if r.compression_profile_id == "x264-crf34-source"]  # A15로 관문에서도 빠진다
        assert c["test"]["counts"]["videos"] == len(test) - len(low) - len(held), name
        side = c["test_out_of_range"]
        assert side["videos"] == len(low) and "roc_auc" not in json.dumps(side) and "tpr" not in side
    # WaveRep이 들어간 후보는 480p에서 전부 보류다. 그 사실은 따로 보고된다
    assert report["candidates"]["W"]["test_out_of_range"]["verdict_coverage"] == 0.0
    assert report["candidates"]["M-full"]["test_out_of_range"]["verdict_coverage"] == 1.0
    assert "x264-crf28-480p" not in report["test_gate_compression_conditions"]
    assert "운영 범위 밖" in build.to_markdown(report)


def test_A15_held_out_profiles_are_reported_once_after_the_gate_not_used_for_adoption(run_out_of_range):
    """2026-11-18 결정: 최종 평가 전용 프로파일은 test 관문에서 빼고, 관문 뒤 따로 한 번 보고한다(탐지 지표 포함)."""
    data, _, report = run_out_of_range
    held = [r for r in read_manifest(data / "manifest.csv")
            if r.split == "test" and r.compression_profile_id == "x264-crf34-source"]
    assert held
    assert "x264-crf34-source" not in report["test_gate_compression_conditions"]
    assert report["held_out_compression_profiles"] == ["x264-crf20-source", "x264-crf34-720p", "x264-crf34-source"]
    for name, c in report["candidates"].items():
        assert "x264-crf34-source" not in c["test"]["by_compression"], name
        side = c["test_held_out"]
        assert side["counts"]["videos"] == len(held), name
        for m in ("roc_auc", "tpr", "fpr"):  # 480p와 달리 탐지 지표와 CI까지 싣는다
            assert {"value", "ci_low", "ci_high"} <= set(side["overall"][m]), name
        assert side["used_for_adoption"] is False
    # 관문 계산은 이 절을 보지 않는다: 리포트에서 지워도 판단이 같다
    stripped = json.loads(json.dumps(report))
    for c in stripped["candidates"].values():
        del c["test_held_out"]
    assert rules.same_decision(rules.rederive(stripped, fast_config()["adoption"]), report["decision"])
    md = build.to_markdown(report)
    assert "관문 뒤 1회 보고, 채택 판단에 사용하지 않음" in md


def _csv_rows(path: Path) -> dict[str, dict]:
    import csv
    with path.open(newline="", encoding="utf-8") as f:
        return {f"{r['dataset_id']}:{r['video_id']}": r for r in csv.DictReader(f)}


@needs_venv
def test_A9_each_servable_candidate_is_validated_on_the_videos_it_would_serve(made):  # noqa: F811
    """2026-11-18 결정: 리포트의 서빙 집단은 서버의 후보 고르기(training/serving.choose)를 test 영상마다 적용한 결과와 같다."""
    folder, _ = made
    report = json.loads((folder / "rep/report.json").read_text())
    d = report["decision"]
    assert (d["decision"], d["primary"], d["servable_candidates"], d["fallbacks_considered"]) == \
        ("fusion_adoptable", "W+M", ["W+M", "W"], ["W"])
    avail = _csv_rows(folder / "run/availability.csv")
    scores = {n: _csv_rows(folder / f"run/scores/{n}.csv") for n in ("W+M", "W")}
    axes = {n: frozenset(report["candidates"][n]["axes"]) for n in ("W+M", "W")}
    test = [r for r in read_manifest(folder / "run-data/manifest.csv") if r.split == "test"]
    chosen, pattern_w = {"W+M": [], "W": [], None: []}, []
    for r in test:
        ok = frozenset(a for a in ("signal", "physics", "alignment") if avail[r.uid][a] == "1")
        name = serving.choose(("W+M", axes["W+M"]), [("W", axes["W"])], ok, lambda n: bool(scores[n][r.uid]["score"]))
        chosen[name].append(r)
        if ok == axes["W"]:
            pattern_w.append(r)
    fallback = report["candidates"]["W"]["serving"]
    assert fallback["role"] == "fallback"
    counts = fallback["evaluation"]["counts"]
    assert counts["videos"] == len(pattern_w) > 0          # 축 성공 패턴이 정확히 {signal}인 test 영상
    assert counts["real_scored"] + counts["fake_scored"] == len(chosen["W"])  # 그중 서버가 실제로 W를 쓰는 영상
    assert report["candidates"]["W+M"]["serving"]["role"] == "primary"
    primary = report["candidates"]["W+M"]["test"]["counts"]
    assert primary["real_scored"] + primary["fake_scored"] == len(chosen["W+M"])
    # 대체 후보의 관문은 자기 관문과 최소 그룹 수이며 TPR 이득 비교는 없다
    checks = [g["check"] for g in fallback["gates"]]
    assert any("진짜 그룹 수" in c for c in checks) and any("가짜 그룹 수" in c for c in checks)
    assert not any("TPR" in c for c in checks)
    assert all(g["passed"] for g in fallback["gates"])
    assert "서빙 규칙과 대체 후보" in (folder / "rep/report.md").read_text()


def test_A9_serving_rule_unit():
    wm, w = ("W+M", frozenset({"signal", "physics"})), [("W", frozenset({"signal"}))]
    yes = lambda name: True  # noqa: E731
    assert serving.choose(wm, w, frozenset({"signal", "physics", "alignment"}), yes) == "W+M"  # 다른 축이 더 성공해도
    assert serving.choose(wm, w, frozenset({"signal"}), yes) == "W"
    assert serving.choose(wm, w, frozenset({"signal", "alignment"}), yes) is None  # 정확히 같은 대체 후보가 없다
    assert serving.choose(wm, w, frozenset({"signal", "physics"}), lambda n: n != "W+M") is None  # 입력 결측
    assert serving.choose(None, [], frozenset({"signal"}), yes) is None
    # 서버와 학습이 같은 함수로 축 성공을 읽는다. MotionPhys 축 상태는 full 변형(후보 A) 기준이다
    row = {"waverep": {"status": "completed"}, "syncnet": {"status": "insufficient_input"},
           "motionphys": {"status": "insufficient_input",
                          "variants": {"face_roi": {"status": "completed", "features": [1.0]}}}}
    assert serving.successful_axes(serving.feature_statuses(row)) == frozenset({"signal"})
    api = {"signal": {"status": "completed"}, "physics": {"status": "insufficient_input"}, "alignment": {"status": "error"}}
    assert serving.successful_axes({k: v["status"] for k, v in api.items()}) == frozenset({"signal"})


@needs_venv
def test_A9_training_uses_motion_features_only_when_physics_axis_succeeds(tmp_path):
    """full 변형이 실패한(physics 축 실패) 영상의 face_roi 특징은 서버에서 쓰이지 않으므로 학습·점수에도 쓰지 않는다."""
    data = make_data(tmp_path / "d", replace(SMALL, missing={"full": 0.3}))
    assert train_on(data, tmp_path / "run", fast_config()).returncode == 0
    feats = {json.loads(line)["uid"]: json.loads(line) for line in (data / "features.jsonl").read_text().splitlines()}
    avail = _csv_rows(tmp_path / "run/availability.csv")
    scores = _csv_rows(tmp_path / "run/scores/M-face_roi.csv")
    failed = [u for u, row in feats.items() if row["axes"]["motionphys"]["status"] != "completed" and u in scores]
    assert failed and all(row["axes"]["motionphys"]["variants"]["face_roi"]["features"] for u, row in feats.items()
                          if u in failed)
    assert all(avail[u]["physics"] == "0" and scores[u]["score"] == "" for u in failed)


def test_OK6_failures_are_null_not_zero_in_scores_and_server_inputs():
    cand = bundles.Candidate("W", frozenset({"signal"}), ("W",), (0.0,), (1.0,), (1.0,), 0.0, 1.0, 0.0, 0.5, None, None)
    for bad in (None, math.nan, math.inf):
        assert cand.score({"W": bad}) is None
    assert cand.score({}) is None
    with pytest.raises(ValueError):
        waverep._parse_result({"status": "completed", "frames": [{"index": 0, "logit": math.nan}]})
