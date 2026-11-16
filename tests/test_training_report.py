"""비교 리포트와 채택 판단 (조각 3), 그리고 합성 데이터 종단 시나리오. 수치는 성능이 아니다.

판단 규칙은 표준 라이브러리라 trinity에서 항상 돈다. 종단 시나리오는 학습 venv가 있을 때만 돈다.
"""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from training import synth
from training.evaluation.metrics import Item
from training.report import build, decision as rules
from tests.test_training_train import PYTHON, config, run_train

needs_venv = pytest.mark.skipif(not PYTHON.is_file(), reason="research/training/.venv 없음")
ADOPTION = {"g2_min_auc_ci_low": 0.5, "min_tpr_gain_ci_low": 0.0, "max_fpr_worsening": 0.02,
            "max_coverage_drop": 0.05, "max_test_fpr_ci_high": 0.10, "n_boot": 200, "bootstrap_seed": 1, "confidence": 0.95}


# ---------- 판단 규칙 (항상 실행) ----------

def own(auc_low=0.7, fpr_high=0.08):
    return rules.own_gates({"overall": {"roc_auc": {"ci_low": auc_low}, "fpr": {"ci_high": fpr_high}}}, ADOPTION)


def diff(tpr_low=0.05, fpr=0.0, coverage=0.0):
    return {"tpr": {"ci_low": tpr_low}, "fpr": {"value": fpr}, "coverage": {"value": coverage}}


SELECTION = {"fusion": "W+M", "best_single": "W"}


def decide(own_w=None, own_f=None, fusion=None, selection=SELECTION):
    return rules.decide(selection, {"W": own_w or own(), "W+M": own_f or own()},
                        {"W+M": fusion or rules.fusion_gates(diff(), None, ADOPTION)})


def test_fusion_is_adoptable_only_when_every_gate_passes():
    ok = decide()
    assert ok["decision"] == "fusion_adoptable" and ok["decision_ko"] == "채택 가능"
    assert ok["servable_candidates"] == ["W+M", "W"] and ok["three_axis_forced"] is False
    for bad in (diff(tpr_low=0.0), diff(tpr_low=-0.01), diff(fpr=0.021), diff(coverage=-0.051), diff(tpr_low=None)):
        out = decide(fusion=rules.fusion_gates(bad, None, ADOPTION))
        assert out["decision"] == "waverep_only" and out["servable_candidates"] == ["W"]
    assert decide(fusion=rules.fusion_gates(diff(fpr=0.02, coverage=-0.05), None, ADOPTION))["decision"] == "fusion_adoptable"


def test_fusion_must_also_beat_the_best_single_axis():
    selection = {"fusion": "W+M", "best_single": "M-full"}
    weak = rules.fusion_gates(diff(), diff(tpr_low=-0.02), ADOPTION)
    assert decide(fusion=weak, selection=selection)["decision"] == "waverep_only"
    strong = rules.fusion_gates(diff(), diff(tpr_low=0.02), ADOPTION)
    assert decide(fusion=strong, selection=selection)["decision"] == "fusion_adoptable"


def test_fpr_ci_upper_bound_above_ten_percent_means_hold():
    assert decide(own_f=own(fpr_high=0.11))["decision"] == "waverep_only"  # 결합만 못 넘으면 단독으로
    held = decide(own_w=own(fpr_high=0.11), own_f=own(fpr_high=0.11))
    assert held["decision"] == "hold" and held["decision_ko"] == "보류" and held["servable_candidates"] == []
    assert decide(own_w=own(fpr_high=0.10), own_f=own(fpr_high=0.11))["decision"] == "waverep_only"
    assert decide(own_w=own(fpr_high=None), own_f=own(fpr_high=None))["decision"] == "hold"  # 계산 못 하면 통과 아님


def test_no_discrimination_means_hold_and_no_fusion_candidate_means_no_adoption():
    assert decide(own_w=own(auc_low=0.5), own_f=own(auc_low=0.5))["decision"] == "hold"
    out = rules.decide({"fusion": None, "best_single": "W"}, {"W": own()}, {})
    assert out["decision"] == "waverep_only"
    # 결합이 통과해도 WaveRep 단독이 자기 관문을 못 넘으면 대체 후보에 넣지 않는다
    only = decide(own_w=own(fpr_high=0.2))
    assert only["decision"] == "fusion_adoptable" and only["servable_candidates"] == ["W+M"]


def test_selection_uses_dev_auc_only_and_prefers_fewer_inputs_on_ties():
    def dev(auc):
        return {"overall": {"roc_auc": {"value": auc}}}
    cands = [{"candidate": "W", "axes": ["signal"], "inputs": ["W"]},
             {"candidate": "M-full", "axes": ["physics"], "inputs": ["M-full"]},
             {"candidate": "W+M", "axes": ["signal", "physics"], "inputs": ["W", "M-full"]},
             {"candidate": "W+M+S", "axes": ["signal", "physics", "alignment"], "inputs": ["W", "M-full", "a", "b", "c"]}]
    s = rules.select_on_dev({"W": dev(0.7), "M-full": dev(0.8), "W+M": dev(0.9), "W+M+S": dev(0.9)}, cands)
    assert (s["best_single"], s["fusion"]) == ("M-full", "W+M")  # SyncNet은 더 나을 때만 들어간다
    s = rules.select_on_dev({"W": dev(0.7), "M-full": dev(None), "W+M": dev(0.8), "W+M+S": dev(0.85)}, cands)
    assert (s["best_single"], s["fusion"]) == ("W", "W+M+S")


def items(scores_real, scores_fake, groups_of=None):
    out = []
    for i, s in enumerate(scores_real):
        out.append(Item(f"r{i}", "real", f"g{i % 5}", s))
    for i, s in enumerate(scores_fake):
        out.append(Item(f"f{i}", "fake", f"g{i % 5}", s))
    return out


def test_paired_difference_is_zero_for_identical_candidates_and_signed_otherwise():
    a = items([0.1, 0.2, 0.3, 0.4, 0.6] * 4, [0.5, 0.7, 0.8, 0.9, 0.3] * 4)
    same = rules.paired_difference(a, a, 0.45, 0.45, 100, 0)
    assert all(same[m]["value"] == 0 and same[m]["ci_low"] == 0 == same[m]["ci_high"] for m in same)
    b = [replace(it, score=it.score - 0.3) if it.label == "fake" else it for it in a]
    d = rules.paired_difference(a, b, 0.45, 0.45, 100, 0)
    assert d["tpr"]["value"] > 0 and d["tpr"]["ci_low"] >= 0 and d["tpr"]["ci_high"] > 0 and d["fpr"]["value"] == 0
    c = [replace(it, score=None) if it.uid in ("r0", "f0") else it for it in a]
    assert rules.paired_difference(c, a, 0.45, 0.45, 50, 0)["coverage"]["value"] == pytest.approx(-0.05)
    with pytest.raises(ValueError):
        rules.paired_difference(a, a[:-1], 0.45, 0.45, 10, 0)


def test_calibration_metrics_hand_values_and_empty():
    perfect = [Item("a", "real", "g", -50.0), Item("b", "fake", "g", 50.0)]
    m = rules.calibration_metrics(perfect, {"a": 1.0, "b": 0.0})
    assert m["brier"] == pytest.approx(0, abs=1e-9) and m["ece"] == pytest.approx(0, abs=1e-9) and m["n"] == 2
    coin = [Item("a", "real", "g", 0.0), Item("b", "fake", "g", 0.0)]
    m = rules.calibration_metrics(coin, {"a": 1.0, "b": 0.0})
    assert m["brier"] == pytest.approx(0.25) and m["ece"] == pytest.approx(0)
    assert rules.calibration_metrics([Item("a", "real", "g", None)], {"a": 1.0, "b": 0.0})["brier"] is None


# ---------- 합성 종단 시나리오 (venv 필요) ----------

def scenario(tmp_path, cfg: synth.SynthConfig, name="run", **conf) -> dict:
    c = config(**conf)
    c["adoption"] = {**c["adoption"], "n_boot": 200}
    proc = run_train(tmp_path, cfg, c, name)
    assert proc.returncode == 0, proc.stderr
    return build.build(tmp_path / f"{name}-data/manifest.csv", tmp_path / name)


@needs_venv
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_no_signal_never_yields_adoption(tmp_path, seed):
    r = scenario(tmp_path, synth.SynthConfig(identities=100, seed=seed))
    assert r["decision"]["decision"] == "hold"
    assert r["decision"]["servable_candidates"] == []


@needs_venv
def test_signal_only_in_waverep_means_waverep_alone(tmp_path):
    r = scenario(tmp_path, synth.SynthConfig(identities=600, signal={"waverep": 2.0}, seed=5))
    assert r["decision"]["best_single"] == "W"
    assert r["decision"]["decision"] == "waverep_only" and r["decision"]["servable_candidates"] == ["W"]


@needs_venv
def test_signal_only_in_one_motion_candidate_makes_that_single_axis_win(tmp_path):
    r = scenario(tmp_path, synth.SynthConfig(identities=160, signal={"face_roi": 2.5}, seed=6))
    assert r["decision"]["best_single"] == "M-face_roi"
    assert r["data"]["motionphys_dev_auc"]["face_roi"] > 0.8
    t = r["candidates"]
    assert t["M-face_roi"]["test"]["overall"]["roc_auc"]["value"] > t["W"]["test"]["overall"]["roc_auc"]["value"] + 0.2
    # 결합이 단일 최강보다 낫다는 근거가 없으므로 채택하지 않는다. 신호 없는 WaveRep도 단독으로 못 쓴다
    assert r["decision"]["decision"] == "hold"


@needs_venv
def test_complementary_signals_can_reach_adoption_and_report_is_complete(tmp_path):
    cfg = synth.SynthConfig(identities=400, signal={"waverep": 1.3, "full": 1.6}, missing={"syncnet": 0.3},
                            profiles=("x264-crf28-720p",), seed=7)
    r = scenario(tmp_path, cfg)
    d = r["decision"]
    assert d["decision"] == "fusion_adoptable" and d["selected_fusion"] == "W+M"
    assert d["servable_candidates"][0] == "W+M" and "W+M+S" not in d["servable_candidates"][:1]
    assert r["dev_compression_conditions"] == ["original"] and r["synthetic"] is True
    test = r["candidates"]["W+M"]["test"]
    assert set(test["by_compression"]) == {"original", "x264-crf28-720p"}
    assert test["calibration"]["brier"] is not None and test["selective"]["verdict_coverage"] == 1.0
    assert r["candidates"]["W+M+S"]["test"]["selective"]["verdict_coverage"] < 0.8  # SyncNet 결측은 보류로 센다
    assert all(c["passed"] for c in r["gates"]["fusion"]["W+M"])
    md = build.to_markdown(r)
    assert md.index("dev 압축 조건") < md.index("## 후보별 지표")  # 맨 위에 표시
    assert "합성 데이터다" in md and "채택 가능" in md and "x264-crf28-720p" in md
    json.dumps(r, allow_nan=False)


@needs_venv
def test_report_cli_writes_json_and_markdown_and_refuses_tampering(tmp_path):
    c = config()
    c["adoption"] = {**c["adoption"], "n_boot": 50}
    assert run_train(tmp_path, synth.SynthConfig(identities=60, signal={"waverep": 1.5}, seed=8), c).returncode == 0
    manifest = tmp_path / "run-data/manifest.csv"
    assert build.main(["--manifest", str(manifest), "--run", str(tmp_path / "run"), "--out", str(tmp_path / "rep")]) == 0
    assert json.loads((tmp_path / "rep/report.json").read_text())["decision"]["decision"] in ("waverep_only", "hold")
    assert (tmp_path / "rep/report.md").read_text().startswith("# 학습 비교 리포트")
    assert build.main(["--manifest", str(manifest), "--run", str(tmp_path / "run"), "--out", str(tmp_path / "rep")]) == 1
    scores = tmp_path / "run/scores/W.csv"
    scores.write_text(scores.read_text().replace("completed", "completed ", 1))
    with pytest.raises(build.ReportError, match="바뀌었다"):
        build.build(manifest, tmp_path / "run")


@needs_venv
def test_leak_injected_after_training_blocks_the_report(tmp_path):
    cfg = synth.SynthConfig(identities=100, signal={"waverep": 1.5}, seed=9)
    c = config()
    assert run_train(tmp_path, cfg, c).returncode == 0
    with pytest.raises(build.ReportError, match="manifest"):
        leaky = tmp_path / "leaky.csv"
        from training.datasets.manifest import write_manifest
        write_manifest(leaky, synth.generate(replace(cfg, leak=True))[0])
        build.build(leaky, tmp_path / "run")
    assert run_train(tmp_path, replace(cfg, leak=True), c, name="leak").returncode == 1


def test_shortcut_diagnostic_flags_metadata_that_predicts_label():
    labels = {f"r{i}": "real" for i in range(20)} | {f"f{i}": "fake" for i in range(20)}
    media = {u: {"width": 1920 if u[0] == "r" else 1280, "height": 1080, "fps": 30.0 + (int(u[1:]) % 2),
                 "duration_sec": 10.0, "has_audio": True} for u in labels}
    d = rules.shortcut_diagnostic(labels, media)
    assert d["available"] and d["warnings"] == ["width"] and d["fields"]["width"]["roc_auc"] == 0.0
    assert d["fields"]["fps"]["roc_auc"] == 0.5
    assert rules.shortcut_diagnostic(labels, {})["available"] is False
    assert rules.shortcut_diagnostic(labels, {"r0": None})["available"] is False
    assert "x" not in rules.shortcut_diagnostic({"r0": "real"}, {"x": media["r0"]})["fields"]
