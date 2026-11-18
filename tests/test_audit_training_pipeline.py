"""독립 감사(2026-11-18): 학습 파이프라인과 서버 관문의 공격 시나리오 (docs/audit-training-pipeline.md).

테스트 이름의 A<번호>는 감사 문서의 발견 번호, OK<번호>는 "시도했지만 문제없던 공격" 번호다.
- 고친 발견: 보통 테스트다. 고치기 전의 코드에서는 실패했다(재현 테스트).
- 설계 결정이 필요해 고치지 않은 발견: xfail(strict=True). 지켜야 할 성질을 적어 두었으므로,
  설계를 바꿔 고치면 XPASS로 실패한다. 그때 표시를 지운다.
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
from training import bundle as bundles, config as training_config, hygiene, synth
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


@pytest.mark.xfail(strict=True, reason="A11 제안: 인물 ID도 확인된 원본 계보도 없는 영상은 혼자 그룹이 되고 경고만 남는다")
def test_A11_video_without_identity_or_verified_source_is_not_silently_ungrouped():
    rows = [{"video-file": "r0.mp4", "type": "real", "split": "train"},  # 인물 ID 빠짐
            {"video-file": "f0.mp4", "type": "fake", "split": "train", "kind": "lip-sync", "engine": "x",
             "identity-source": 0, "identity-target": 0, "recording-target": 1}]
    records = adapters.convert(rows, {**DEEPSPEAK, "split": {**DEEPSPEAK["split"], "train_fractions": {"train": 1.0}}})
    assert records[0].source_unverified and not records[0].identity_ids
    assert not hygiene.check(records, LOCK).ok  # 지금은 identity_missing·source_unverified 경고뿐이다


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
    """관문을 넘지 않은 W+M+S를 리포트의 서빙 목록에 끼워 넣고 해시·digest를 모두 다시 맞춘다."""
    settings, _, folder = pinned
    run = made[0] / "run"
    report = json.loads((folder / "report.json").read_text())
    assert "W+M+S" in report["candidates"] and "W+M+S" not in report["decision"]["servable_candidates"]
    report["decision"]["servable_candidates"].insert(0, "W+M+S")
    (folder / "report.json").write_text(json.dumps(report))
    for rel in ("models/W+M+S.json", "thresholds/W+M+S.json"):
        shutil.copyfile(run / rel, folder / rel)
    body = json.loads((folder / "bundle.json").read_text())
    body["files"].update({rel: bundles._sha256(folder / rel)
                          for rel in ("report.json", "models/W+M+S.json", "thresholds/W+M+S.json")})
    body["candidates"].insert(0, {"candidate": "W+M+S", "axes": ["signal", "physics", "alignment"],
                                  "motion_variant": "full"})
    _repin(folder, settings.fusion_bundle_config_path, body)
    assert fusion.load_active(settings) is None
    assert rejection_code(settings) == "report_inconsistent"
    fake_axes(monkeypatch, signal=4.0, physics=6.0, alignment=True)
    _, job = run_job(queue, registry, settings)
    assert_abstained(job.result)


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
    return folder / "run", c, report


def test_A1_hold_report_forged_to_waverep_only_cannot_become_a_bundle(tmp_path, hold_run):
    """신호 없는 데이터의 보류 리포트를 판단 문자열만 'WaveRep 단독'으로 고쳐 묶음을 만들려 한다."""
    run, c, report = hold_run
    report = json.loads(json.dumps(report))
    report["decision"].update(decision="waverep_only", decision_ko="WaveRep 단독", servable_candidates=["W"])
    (tmp_path / "forged.json").write_text(json.dumps(report))
    with pytest.raises(bundles.BundleError) as e:
        bundles.create(run, tmp_path / "forged.json", tmp_path / "fusion/b1", expected_config=c)
    assert e.value.code == "report_inconsistent"


@pytest.mark.xfail(strict=True, reason="A16 제안: 지표 숫자까지 앞뒤가 맞게 고친 리포트는 다시 계산해도 걸러지지 않는다(재현 검증 필요)")
def test_A16_report_with_consistently_forged_metrics_cannot_become_a_bundle(tmp_path, hold_run):
    run, c, report = hold_run
    report = json.loads(json.dumps(report))
    w = report["candidates"]["W"]["test"]["overall"]
    w["roc_auc"].update(value=0.8, ci_low=0.7)
    w["fpr"].update(value=0.03, ci_high=0.05)
    report["decision"] = rules.rederive(report, c["adoption"])  # 고친 숫자에 맞는 판단(WaveRep 단독)
    assert report["decision"]["decision"] == "waverep_only"
    (tmp_path / "forged.json").write_text(json.dumps(report))
    with pytest.raises(bundles.BundleError):
        bundles.create(run, tmp_path / "forged.json", tmp_path / "fusion/b1", expected_config=c)


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
        bundles.create(tmp_path / "run", tmp_path / "rep.json", tmp_path / "fusion/b1", expected_config=committed)
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


@pytest.mark.xfail(strict=True, reason="A10 제안: 오탐 0건이면 백분위 bootstrap의 FPR 상한이 0이 되어 표본이 적어도 통과한다")
def test_A10_fpr_upper_bound_gate_does_not_pass_on_too_few_real_videos():
    items = [Item(f"r{i}", "real", f"r{i}", score=0.0) for i in range(20)] + \
            [Item(f"f{i}", "fake", f"f{i}", score=1.0) for i in range(20)]
    ev = metrics.evaluate(items, threshold=0.5, n_boot=1000, seed=1)
    exact_upper = 1 - 0.025 ** (1 / 20)  # 0/20의 Clopper-Pearson 95% 상한 ≈ 16.8%
    assert exact_upper > ADOPTION["max_test_fpr_ci_high"]
    assert ev["overall"]["fpr"]["ci_high"] == 0.0  # 지금 값
    fpr_gate = rules.own_gates(ev, ADOPTION)[1]
    assert not fpr_gate["passed"], "진짜 20개, 오탐 0건으로 FPR ≤ 10%를 입증했다고 본다"


@pytest.mark.xfail(strict=True, reason="A17 제안: 결합 − 단일 최강의 TPR 차이는 서로 다른 영상 집합에서 계산된다")
def test_A17_tpr_gain_is_not_produced_by_abstaining_on_hard_fakes():
    """결합이 어려운 가짜에서 보류하면, 함께 점수를 낸 영상에서 똑같아도 TPR 이득으로 보인다."""
    real = [Item(f"r{i}", "real", f"r{i}", score=0.0) for i in range(40)]
    easy = [Item(f"e{i}", "fake", f"e{i}", score=1.0) for i in range(30)]
    hard = [Item(f"h{i}", "fake", f"h{i}", score=0.0) for i in range(10)]
    single = real + easy + hard
    fused = real + easy + [replace(it, score=None) for it in hard]  # 어려운 가짜 10개에서 보류
    out = rules.paired_difference(fused, single, 0.5, 0.5, n_boot=300, seed=3)
    assert out["coverage"]["value"] == pytest.approx(-0.125)
    assert not out["tpr"]["ci_low"] > 0, "판정 제공 비율을 줄인 만큼 TPR이 오른 것으로 셌다"


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
        assert c["test"]["counts"]["videos"] == len(test) - len(low), name
        side = c["test_out_of_range"]
        assert side["videos"] == len(low) and "roc_auc" not in json.dumps(side) and "tpr" not in side
    # WaveRep이 들어간 후보는 480p에서 전부 보류다. 그 사실은 따로 보고된다
    assert report["candidates"]["W"]["test_out_of_range"]["verdict_coverage"] == 0.0
    assert report["candidates"]["M-full"]["test_out_of_range"]["verdict_coverage"] == 1.0
    assert "x264-crf28-480p" not in report["test_gate_compression_conditions"]
    assert "운영 범위 밖" in build.to_markdown(report)


def test_A15_current_behavior_held_out_profiles_enter_the_test_gate(run_out_of_range):
    """결정 대기(제안만): 최종 평가 전용 프로파일을 test 관문에 넣을지. 지금은 넣고, 리포트에 그 사실을 적는다."""
    _, _, report = run_out_of_range
    assert "x264-crf34-source" in report["test_gate_compression_conditions"]
    assert "x264-crf34-source" in report["candidates"]["W"]["test"]["by_compression"]


@pytest.mark.xfail(strict=True, reason="A9 제안: 서버는 성공한 축 집합과 정확히 같은 후보만 쓰지만, 리포트는 후보를 그 모집단에서 검증하지 않는다")
def test_A9_each_servable_candidate_is_validated_on_the_videos_it_would_serve(run_out_of_range):
    _, _, report = run_out_of_range
    for name, c in report["candidates"].items():
        # 예: W 후보는 physics·alignment가 모두 실패한 영상에서만 쓰인다. 그 영상들만의 test 지표가 있어야 한다
        assert "serving_population" in c["test"], name


def test_OK6_failures_are_null_not_zero_in_scores_and_server_inputs():
    cand = bundles.Candidate("W", frozenset({"signal"}), ("W",), (0.0,), (1.0,), (1.0,), 0.0, 1.0, 0.0, 0.5, None, None)
    for bad in (None, math.nan, math.inf):
        assert cand.score({"W": bad}) is None
    assert cand.score({}) is None
    with pytest.raises(ValueError):
        waverep._parse_result({"status": "completed", "frames": [{"index": 0, "logit": math.nan}]})
