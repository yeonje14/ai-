"""평가 파이프라인 뼈대: manifest, 그룹 분할, 누수 검사, 지표, 임계값 고정, 외부 평가 잠금.

모두 합성 데이터(가짜 manifest와 가짜 점수)다. 실제 데이터셋이나 모델은 필요 없다.
"""

from __future__ import annotations

import csv
import json
import random
import stat
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from training import hygiene
from training.datasets import groups, manifest
from training.datasets.manifest import ManifestError, Record
from training.evaluation import lock as lock_mod
from training.evaluation import metrics, run, thresholds
from training.evaluation.metrics import Item

LOCK = {"ext-set": {"status": "locked"}}


def rec(video_id, label="real", source=None, split="train", dataset="synth", **kw) -> Record:
    return Record(
        dataset_id=dataset, video_id=video_id, video_path=f"{dataset}/{video_id}.mp4",
        label=label, source_recording_id=source or f"src-{video_id}", split=split, **kw,
    )


def fake(video_id, generator="genA", mtype="A1", **kw) -> Record:
    return rec(video_id, label="fake", generator_id=generator, manipulation_type=mtype, **kw)


# ---------- manifest ----------

def test_manifest_roundtrip(tmp_path):
    records = [
        rec("r1", identity_ids=("p1",), file_hash="h1"),
        fake("f1", source="src-r1", identity_ids=("p1", "p2"), parent_video_id="r1", derivation_group_id="d1"),
    ]
    path = tmp_path / "m.csv"
    manifest.write_manifest(path, records)
    assert manifest.read_manifest(path) == sorted(records, key=lambda r: r.uid)
    assert path.read_text().splitlines()[0] == ",".join(manifest.FIELDS)


@pytest.mark.parametrize("bad", [
    replace(rec("x"), source_recording_id=""),
    replace(rec("x"), label="maybe"),
    replace(rec("x"), split="holdout"),
    replace(rec("x"), generator_id="genA"),          # real에는 생성기를 쓰지 않는다
    replace(fake("x"), manipulation_type="Z9"),
    replace(rec("x"), video_path=""),
])
def test_manifest_rejects_invalid_records(bad):
    with pytest.raises(ManifestError):
        manifest.validate([bad])


def test_source_recording_id_is_required_but_identity_is_not():
    assert manifest.validate([rec("ok", identity_ids=())])
    with pytest.raises(ManifestError) as e:
        manifest.validate([replace(rec("x"), source_recording_id="")])
    assert "source_recording_id" in e.value.problems[0]


def test_manifest_rejects_duplicate_video():
    with pytest.raises(ManifestError):
        manifest.validate([rec("a"), rec("a")])


def test_read_manifest_requires_all_columns(tmp_path):
    path = tmp_path / "m.csv"
    path.write_text("dataset_id,video_id\nsynth,a\n")
    with pytest.raises(ManifestError):
        manifest.read_manifest(path)


# ---------- 그룹 ----------

def test_groups_link_by_source_identity_parent_and_derivation():
    records = [
        rec("a", source="s1", identity_ids=("p1",)),
        rec("b", source="s1"),                              # 같은 원본
        fake("c", source="s2", identity_ids=("p1", "p2")),  # 얼굴 교체: 출처 p1, 대상 p2
        rec("d", source="s3", identity_ids=("p2",)),        # p2를 거쳐 a와 이어진다
        rec("e", source="s4", parent_video_id="d"),         # 부모 영상
        rec("f", source="s5", derivation_group_id="x"),
        rec("g", source="s6", derivation_group_id="x"),
        rec("h", source="s7"),
    ]
    gid = groups.group_ids(records)
    assert len({gid[f"synth:{v}"] for v in "abcde"}) == 1
    assert gid["synth:f"] == gid["synth:g"] != gid["synth:a"]
    assert gid["synth:h"] not in {gid["synth:a"], gid["synth:f"]}


def test_group_ids_do_not_depend_on_input_order():
    records = [rec(f"v{i}", source=f"s{i % 7}", identity_ids=(f"p{i % 5}",)) for i in range(40)]
    shuffled = records[:]
    random.Random(3).shuffle(shuffled)
    assert groups.group_ids(records) == groups.group_ids(shuffled)


def test_identity_and_source_namespaces_do_not_collide():
    gid = groups.group_ids([rec("a", source="X"), rec("b", source="s2", identity_ids=("X",))])
    assert gid["synth:a"] != gid["synth:b"]


def _pool(n_sources=60, clips=3) -> list[Record]:
    out = []
    for s in range(n_sources):
        for c in range(clips):
            out.append(rec(f"r{s}_{c}", source=f"s{s}", split="", identity_ids=(f"p{s}",)))
            out.append(fake(f"f{s}_{c}", source=f"s{s}", split="", generator=f"gen{s % 3}",
                            mtype=("A1", "C1", "B1")[s % 3], identity_ids=(f"p{s}",)))
    return out


def test_assign_splits_keeps_groups_whole_and_is_deterministic():
    pool = _pool()
    fractions = {"train": 0.6, "dev": 0.2, "test": 0.2}
    a = groups.assign_splits(pool, fractions, seed=1)
    b = groups.assign_splits(list(reversed(pool)), fractions, seed=1)
    assert {r.uid: r.split for r in a} == {r.uid: r.split for r in b}
    by_source: dict[str, set] = {}
    for r in a:
        by_source.setdefault(r.source_recording_id, set()).add(r.split)
    assert all(len(s) == 1 for s in by_source.values())
    share = Counter(r.split for r in a)
    assert abs(share["train"] / len(a) - 0.6) < 0.05 and abs(share["dev"] / len(a) - 0.2) < 0.05
    assert hygiene.check(a, LOCK).ok
    assert {r.uid: r.split for r in groups.assign_splits(pool, fractions, seed=2)} != {r.uid: r.split for r in a}


def test_assign_splits_never_moves_external_records():
    pool = _pool(10) + [rec("e1", split="external", dataset="ext-set")]
    out = groups.assign_splits(pool, {"train": 0.5, "dev": 0.5}, seed=1)
    assert [r.split for r in out if r.dataset_id == "ext-set"] == ["external"]
    assert {r.split for r in out if r.dataset_id == "synth"} == {"train", "dev"}


@pytest.mark.parametrize("fractions", [{}, {"train": 0.5}, {"train": 0.5, "external": 0.5}, {"train": 1.5, "dev": -0.5}])
def test_assign_splits_rejects_bad_fractions(fractions):
    with pytest.raises(ValueError):
        groups.assign_splits(_pool(3), fractions, seed=1)


# ---------- 누수 검사 ----------

def codes(report) -> set[str]:
    return {e["code"] for e in report.errors}


def test_clean_manifest_passes_and_always_lists_warnings():
    report = hygiene.check([rec("a", identity_ids=("p1",), file_hash="h"), fake("b", split="dev", identity_ids=("p2",), file_hash="h2")], LOCK)
    assert report.ok and report.groups == 2
    assert report.warnings == {
        "identity_missing": 0, "source_unverified": 0, "fake_generator_missing": 0,
        "fake_manipulation_type_missing": 0, "file_hash_missing": 0,
    }


def test_group_spanning_splits_fails():
    report = hygiene.check([rec("a", source="s1", split="train"), fake("b", source="s1", split="test")], LOCK)
    assert not report.ok and "group_spans_splits" in codes(report)
    example = next(e for e in report.errors if e["code"] == "group_spans_splits")["examples"][0]
    assert example["splits"] == ["test", "train"] and example["videos"] == ["synth:a", "synth:b"]


def test_identity_shared_across_splits_fails_even_with_different_sources():
    report = hygiene.check([
        rec("a", source="s1", split="train", identity_ids=("p1",)),
        fake("b", source="s2", split="dev", identity_ids=("p9", "p1")),
    ], LOCK)
    assert "group_spans_splits" in codes(report)


def test_source_overlap_between_external_and_training_is_reported_separately():
    report = hygiene.check([
        rec("a", source="yt:AAAAAAAAAAA", split="train"),
        fake("e", source="yt:AAAAAAAAAAA", split="external", dataset="ext-set"),
    ], LOCK)
    assert {"source_overlap_external_internal", "group_spans_splits"} <= codes(report)
    err = next(e for e in report.errors if e["code"] == "source_overlap_external_internal")
    assert err["examples"] == ["yt:AAAAAAAAAAA"]


def test_identity_and_hash_overlap_with_external_fail():
    report = hygiene.check([
        rec("a", split="dev", identity_ids=("p1",), file_hash="same"),
        rec("e", split="external", dataset="ext-set", identity_ids=("p1",), file_hash="same"),
    ], LOCK)
    assert {"identity_overlap_external_internal", "file_hash_overlap_external_internal", "file_hash_spans_splits"} <= codes(report)


def test_external_dataset_must_stay_external_and_be_registered():
    assert "external_dataset_in_internal_split" in codes(hygiene.check([rec("e", split="dev", dataset="ext-set")], LOCK))
    assert "external_dataset_not_registered" in codes(hygiene.check([rec("e", split="external", dataset="other")], LOCK))
    assert hygiene.check([rec("e", split="external", dataset="ext-set")], LOCK).ok


def test_missing_split_fails():
    assert "split_missing" in codes(hygiene.check([rec("a", split="")], LOCK))


def test_missing_identity_is_a_warning_not_an_error():
    report = hygiene.check([
        rec("a"), rec("b", source="unknown:synth/b.mp4"), replace(fake("c"), generator_id="", manipulation_type=""),
    ], LOCK)
    assert report.ok
    assert report.warnings["identity_missing"] == 3
    assert report.warnings["source_unverified"] == 1
    assert report.warnings["fake_generator_missing"] == report.warnings["fake_manipulation_type_missing"] == 1


def test_hygiene_cli_exit_codes(tmp_path, capsys):
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps({"datasets": LOCK}))
    good, bad = tmp_path / "good.csv", tmp_path / "bad.csv"
    manifest.write_manifest(good, [rec("a"), rec("b", split="dev")])
    manifest.write_manifest(bad, [rec("a", source="s"), rec("b", source="s", split="dev")])
    assert hygiene.main([str(good), "--lock", str(lock_path)]) == 0
    assert hygiene.main([str(bad), "--lock", str(lock_path)]) == 1
    assert '"group_spans_splits"' in capsys.readouterr().out
    assert hygiene.main([str(tmp_path / "none.csv"), "--lock", str(lock_path)]) == 2


# ---------- 지표 ----------

@pytest.mark.parametrize("fakes,reals,expected", [
    ([3, 4], [1, 2], 1.0),
    ([1, 2], [3, 4], 0.0),
    ([1, 3], [2, 2], 0.5),
    ([1], [1], 0.5),                 # 동점은 0.5
    ([2, 2, 3], [1, 2], 5 / 6),      # (1 + 1 + 1 + 0.5 + 0.5 + 1) / 6
])
def test_roc_auc_matches_hand_computation(fakes, reals, expected):
    assert metrics.roc_auc(fakes, reals) == pytest.approx(expected)


def test_roc_auc_is_none_without_both_classes():
    assert metrics.roc_auc([], [1.0]) is None and metrics.roc_auc([1.0], []) is None


def test_roc_auc_matches_pairwise_definition_on_random_scores():
    rng = random.Random(0)
    f = [round(rng.gauss(0.5, 1), 1) for _ in range(40)]
    r = [round(rng.gauss(0, 1), 1) for _ in range(30)]
    brute = sum((a > b) + 0.5 * (a == b) for a in f for b in r) / (len(f) * len(r))
    assert metrics.roc_auc(f, r) == pytest.approx(brute)


def test_threshold_at_fpr_keeps_actual_fpr_at_or_below_target():
    reals = [float(i) for i in range(100)]
    t = metrics.threshold_at_fpr(reals, 0.05)
    assert 94 < t < 95 and metrics.rate_at(reals, t) == 0.05
    # 진짜가 적으면 허용 오탐이 0개다: 최댓값보다 위
    few = [0.1, 0.9, 0.5]
    assert metrics.rate_at(few, metrics.threshold_at_fpr(few, 0.05)) == 0.0
    # 동점이 있어도 목표를 넘지 않는다
    tied = [1.0] * 50 + [0.0] * 50
    assert metrics.rate_at(tied, metrics.threshold_at_fpr(tied, 0.05)) == 0.0


@pytest.mark.parametrize("target", [0, 1, -0.1, 1.5])
def test_threshold_at_fpr_rejects_bad_target(target):
    with pytest.raises(ValueError):
        metrics.threshold_at_fpr([0.0, 1.0], target)


def test_threshold_needs_real_scores():
    with pytest.raises(ValueError):
        metrics.threshold_at_fpr([], 0.05)


def _items(n_groups=80, seed=0, sep=2.0, null_every=0) -> list[Item]:
    rng = random.Random(seed)
    out = []
    for g in range(n_groups):
        for c in range(2):
            out.append(Item(f"r{g}_{c}", "real", f"g{g}", rng.gauss(0, 1)))
            score = rng.gauss(sep, 1)
            if null_every and (g * 2 + c) % null_every == 0:
                out.append(Item(f"f{g}_{c}", "fake", f"g{g}", None, f"gen{g % 2}", ("A1", "C1")[g % 2], "no_face_detected"))
            else:
                out.append(Item(f"f{g}_{c}", "fake", f"g{g}", score, f"gen{g % 2}", ("A1", "C1")[g % 2]))
    return out


def test_evaluate_reports_overall_breakdowns_and_ci():
    items = _items()
    out = metrics.evaluate(items, threshold=1.0, n_boot=200, seed=7)
    assert out["counts"] == {"videos": 320, "groups": 80, "real": 160, "fake": 160, "real_scored": 160, "fake_scored": 160}
    for name in ("roc_auc", "tpr", "fpr"):
        m = out["overall"][name]
        assert m["ci_low"] <= m["value"] <= m["ci_high"] and m["n_boot_valid"] == 200
    assert out["overall"]["roc_auc"]["value"] > 0.85
    assert set(out["by_generator"]) == {"gen0", "gen1"} and set(out["by_manipulation_type"]) == {"A1", "C1"}
    g0 = out["by_generator"]["gen0"]
    assert g0["fake_videos"] == 80 and g0["fake_groups"] == 40
    assert g0["tpr"]["value"] is not None and g0["roc_auc_vs_all_real"]["value"] is not None
    assert out["bootstrap"] == {"unit": "group", "n_boot": 200, "seed": 7, "confidence": 0.95}


def test_evaluate_is_reproducible_with_same_seed():
    items = _items()
    a = metrics.evaluate(items, 1.0, n_boot=100, seed=3)
    assert a == metrics.evaluate(list(reversed(items)), 1.0, n_boot=100, seed=3)
    assert a["overall"]["tpr"]["ci_low"] != metrics.evaluate(items, 1.0, n_boot=100, seed=4)["overall"]["tpr"]["ci_low"]


def test_bootstrap_resamples_groups_not_videos():
    # 모든 영상이 한 그룹이면 어떤 추출도 원래 집합의 배수라서 구간의 폭이 0이다
    one_group = [replace(it, group="only") for it in _items(20)]
    m = metrics.evaluate(one_group, 1.0, n_boot=50, seed=1)["overall"]["roc_auc"]
    assert m["ci_low"] == pytest.approx(m["value"]) and m["ci_high"] == pytest.approx(m["value"])
    # 그룹이 여럿이면 폭이 생긴다
    m = metrics.evaluate(_items(20), 1.0, n_boot=50, seed=1)["overall"]["roc_auc"]
    assert m["ci_high"] > m["ci_low"]


def test_null_scores_are_counted_as_abstained_not_dropped_or_zero():
    items = _items(40, null_every=4)
    out = metrics.evaluate(items, 1.0, n_boot=20, seed=1)
    assert out["counts"]["fake"] == 80 and out["counts"]["fake_scored"] == 60
    assert out["selective"]["abstained"] == 20
    assert out["selective"]["abstained_by_reason"] == {"no_face_detected": 20}
    assert out["selective"]["verdict_coverage"] == pytest.approx(140 / 160)
    assert out["selective"]["abstention_rate"] == pytest.approx(20 / 160)
    gen = out["by_generator"]["gen0"]
    assert gen["fake_videos"] == 40 and gen["fake_scored"] < 40


def test_metrics_are_none_not_zero_when_not_computable():
    only_fake = [Item("f1", "fake", "g1", 2.0, "genA"), Item("f2", "fake", "g2", None, "genA", reason_code="error")]
    out = metrics.evaluate(only_fake, 1.0, n_boot=10, seed=1)
    assert out["overall"]["roc_auc"] == {"value": None, "ci_low": None, "ci_high": None, "n_boot_valid": 0}
    assert out["overall"]["fpr"]["value"] is None
    empty = metrics.evaluate([], 1.0, n_boot=10)
    assert empty["selective"]["verdict_coverage"] is None and empty["overall"]["tpr"]["value"] is None


def test_unknown_generator_is_grouped_under_placeholder():
    out = metrics.evaluate([Item("f", "fake", "g", 2.0), Item("r", "real", "g2", 0.0)], 1.0, n_boot=5)
    assert list(out["by_generator"]) == [metrics.UNKNOWN]


# ---------- 임계값 고정 ----------

def _dev_items(n=100, seed=0):
    rng = random.Random(seed)
    items = [Item(f"r{i}", "real", f"g{i}", rng.gauss(0, 1)) for i in range(n)]
    items += [Item(f"f{i}", "fake", f"g{i}", rng.gauss(2, 1), "genA") for i in range(n)]
    return items


def _fit(items, splits=None, **kw):
    kw = {"model_id": "synthetic-model", "manifest_sha256": "m" * 64, "scores_sha256": "s" * 64, **kw}
    return thresholds.fit_threshold(items, splits or ["dev"] * len(items), **kw)


def test_fit_threshold_on_dev_records_actual_dev_fpr():
    t = _fit(_dev_items())
    assert t["source_split"] == "dev" and t["target_fpr"] == 0.05
    assert t["dev_fpr"] == 0.05 and t["dev_real_scored"] == 100 and t["dev_groups"] == 100
    assert thresholds.verify(t) is t


@pytest.mark.parametrize("other", ["test", "external", "train"])
def test_threshold_cannot_be_fit_on_other_splits(other):
    items = _dev_items(10)
    with pytest.raises(thresholds.ThresholdError):
        _fit(items, ["dev"] * (len(items) - 1) + [other])
    with pytest.raises(thresholds.ThresholdError):
        _fit(items, [other] * len(items))


def test_threshold_needs_scored_real_dev_videos_and_model_id():
    with pytest.raises(thresholds.ThresholdError):
        _fit([Item("f", "fake", "g", 1.0), Item("r", "real", "g2", None)])
    with pytest.raises(thresholds.ThresholdError):
        _fit(_dev_items(5), model_id="")


def test_threshold_file_cannot_be_overwritten_and_is_read_only(tmp_path):
    path = tmp_path / "threshold.json"
    t = _fit(_dev_items())
    thresholds.save_threshold(path, t)
    assert thresholds.load_threshold(path) == t
    assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    with pytest.raises(thresholds.ThresholdError):
        thresholds.save_threshold(path, _fit(_dev_items(seed=1)))
    assert thresholds.load_threshold(path) == t


@pytest.mark.parametrize("field,value", [("threshold", -100.0), ("source_split", "test"), ("target_fpr", 0.5), ("dev_fpr", 0.0)])
def test_tampered_threshold_file_is_rejected(tmp_path, field, value):
    t = dict(_fit(_dev_items()))
    t[field] = value
    path = tmp_path / "t.json"
    path.write_text(json.dumps(t))
    with pytest.raises(thresholds.ThresholdError):
        thresholds.load_threshold(path)


def test_threshold_claiming_test_split_is_rejected_even_with_valid_digest():
    body = {k: v for k, v in _fit(_dev_items()).items() if k != "digest"}
    body["source_split"] = "test"
    with pytest.raises(thresholds.ThresholdError):
        thresholds.verify({**body, "digest": thresholds._digest(body)})


def test_missing_or_broken_threshold_file(tmp_path):
    with pytest.raises(thresholds.ThresholdError):
        thresholds.load_threshold(tmp_path / "none.json")
    (tmp_path / "bad.json").write_text("{not json")
    with pytest.raises(thresholds.ThresholdError):
        thresholds.load_threshold(tmp_path / "bad.json")


# ---------- 잠금 ----------

def test_lock_file_in_repo_keeps_final_external_sets_locked():
    lock = lock_mod.load_lock()
    assert {"mavos-dd", "talkingheadbench", "deepfake-eval-2024"} <= set(lock)
    assert all(entry["status"] == "locked" for entry in lock.values())
    assert lock["mavos-dd"]["manifest_sha256"] == "c7df59677463faebcd6cf16831e1a4156d43d98a5f18414ffc12e8fd900e1aba"


def test_assert_unlocked():
    with pytest.raises(lock_mod.ExternalEvalLocked):
        lock_mod.assert_unlocked({"ext-set"}, LOCK)
    with pytest.raises(lock_mod.ExternalEvalLocked):
        lock_mod.assert_unlocked({"unregistered"}, LOCK)
    lock_mod.assert_unlocked({"ext-set"}, {"ext-set": {"status": "unlocked"}})


def test_malformed_lock_file_is_an_error_not_an_empty_lock(tmp_path):
    for text in ('{"datasets": {"x": {"status": "open"}}}', '{"nothing": 1}'):
        p = tmp_path / "lock.json"
        p.write_text(text)
        with pytest.raises(ValueError):
            lock_mod.load_lock(p)


# ---------- 명령 (합성 manifest와 합성 점수로 끝까지) ----------

@pytest.fixture
def world(tmp_path):
    """train/dev/test로 나눈 합성 manifest, external manifest, 점수 파일, 잠금 파일."""
    rng = random.Random(11)
    records = groups.assign_splits(_pool(120, clips=2), {"train": 0.5, "dev": 0.25, "test": 0.25}, seed=5)
    external = []
    for s in range(30):
        external.append(rec(f"er{s}", source=f"unknown:ext/er{s}.mp4" if s % 5 == 0 else f"ext-s{s}",
                            split="external", dataset="ext-set"))
        external.append(fake(f"ef{s}", source=f"ext-s{s}", split="external", dataset="ext-set", generator=f"new{s % 2}", mtype="C1"))
    m, x = tmp_path / "manifest.csv", tmp_path / "external.csv"
    scores, ext_scores = tmp_path / "scores.csv", tmp_path / "external_scores.csv"
    manifest.write_manifest(m, records)
    manifest.write_manifest(x, external)
    # 외부 평가의 점수는 내부 점수와 다른 파일에 둔다
    for path, rows in ((scores, records), (ext_scores, external)):
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["dataset_id", "video_id", "score", "status", "reason_code",
                        "video_duration_sec", "eligible_duration_sec", "analyzed_duration_sec"])
            for i, r in enumerate(rows):
                if r.split == "test" and i % 10 == 0:
                    w.writerow([r.dataset_id, r.video_id, "", "insufficient_input", "no_speech_detected", 10, 0, 0])
                elif r.split == "test" and i % 10 == 1:
                    continue  # 점수 행이 아예 없는 영상
                else:
                    w.writerow([r.dataset_id, r.video_id, repr(rng.gauss(2.0 if r.label == "fake" else 0.0, 1)), "completed", "", 10, 8, 6])
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps({"datasets": {"ext-set": {"status": "locked"}}}))
    return {"dir": tmp_path, "manifest": m, "external": x, "scores": scores, "ext_scores": ext_scores, "lock": lock_path,
            "threshold": tmp_path / "threshold.json", "records": records}


def fit(world, **override):
    args = {"--manifest": world["manifest"], "--scores": world["scores"], "--model-id": "synthetic-model",
            "--out": world["threshold"], "--lock": world["lock"], **override}
    return run.main(["fit-threshold", *[str(x) for kv in args.items() for x in kv]])


def evaluate(world, split="test", manifests=None, extra=(), out="report.json"):
    scores = world["ext_scores"] if split == "external" else world["scores"]
    args = ["evaluate", "--scores", str(scores), "--threshold", str(world["threshold"]),
            "--split", split, "--out", str(world["dir"] / out), "--lock", str(world["lock"]),
            "--n-boot", "50", "--seed", "1", *extra]
    for path in manifests or [world["manifest"]]:
        args += ["--manifest", str(path)]
    return run.main(args)


def test_end_to_end_fit_then_evaluate_test_split(world, capsys):
    assert fit(world) == 0
    t = thresholds.load_threshold(world["threshold"])
    assert t["dev_fpr"] <= 0.05 and t["dev_manifest_sha256"] == manifest.sha256_file(world["manifest"])
    assert evaluate(world) == 0
    report = json.loads((world["dir"] / "report.json").read_text())
    n_test = sum(1 for r in world["records"] if r.split == "test")
    assert report["split"] == "test" and report["counts"]["videos"] == n_test
    assert report["threshold"]["digest"] == t["digest"] and report["threshold"]["source_split"] == "dev"
    assert report["overall"]["roc_auc"]["value"] > 0.8
    assert report["overall"]["tpr"]["ci_low"] <= report["overall"]["tpr"]["value"] <= report["overall"]["tpr"]["ci_high"]
    # 점수가 없는 영상은 사유별로 세고 지표에서 조용히 빠지지 않는다
    reasons = report["selective"]["abstained_by_reason"]
    assert set(reasons) == {"no_speech_detected", "missing_score"}
    assert report["selective"]["abstained"] == sum(reasons.values()) > 0
    assert report["selective"]["verdict_coverage"] < 1
    # 생성기별이 기본, 유형별은 보조(잠정)
    assert set(report["by_generator"]) == {"gen0", "gen1", "gen2"}
    assert set(report["by_manipulation_type"]) == {"A1", "B1", "C1"}
    assert "잠정" in report["notes"][0]
    # 경고 개수는 항상 리포트에 있다
    assert report["hygiene"]["ok"] is True
    assert set(report["hygiene"]["warnings"]) == set(report["hygiene_warnings_in_split"])
    assert report["hygiene_warnings_in_split"]["file_hash_missing"] == n_test
    assert report["coverage"]["full_video_coverage"] is not None
    assert "경고:" in capsys.readouterr().out


def test_fit_threshold_uses_only_dev_rows(world):
    assert fit(world) == 0
    t = thresholds.load_threshold(world["threshold"])
    assert t["dev_videos"] == sum(1 for r in world["records"] if r.split == "dev")


def test_second_fit_cannot_replace_the_frozen_threshold(world, capsys):
    assert fit(world) == 0
    before = world["threshold"].read_text()
    assert fit(world, **{"--target-fpr": 0.2}) == 3
    assert world["threshold"].read_text() == before
    assert "덮어쓰지 않는다" in capsys.readouterr().err


def test_evaluate_has_no_numeric_threshold_option(world):
    assert fit(world) == 0
    with pytest.raises(SystemExit):
        evaluate(world, extra=("--threshold-value", "0.0"))


def test_evaluate_rejects_tampered_threshold(world, capsys):
    assert fit(world) == 0
    data = json.loads(world["threshold"].read_text())
    data["threshold"] = -5.0
    world["threshold"].chmod(0o644)
    world["threshold"].write_text(json.dumps(data))
    assert evaluate(world) == 3
    assert "digest" in capsys.readouterr().err


def test_evaluate_requires_the_dev_manifest_used_for_the_threshold(world):
    assert fit(world) == 0
    other = world["dir"] / "other.csv"
    manifest.write_manifest(other, [r.with_split("test") for r in world["records"][:20]])
    assert evaluate(world, manifests=[other]) == 3


def test_leaky_manifest_blocks_threshold_and_evaluation(world, capsys):
    leaky = world["dir"] / "leaky.csv"
    records = list(world["records"])
    dev = next(r for r in records if r.split == "dev")
    records.append(rec("leak", source=dev.source_recording_id, split="test"))
    manifest.write_manifest(leaky, records)
    assert fit(world, **{"--manifest": leaky}) == 1
    assert not world["threshold"].exists()
    assert "group_spans_splits" in capsys.readouterr().err


def test_external_split_is_locked(world, capsys):
    assert fit(world) == 0
    both = [world["manifest"], world["external"]]
    assert evaluate(world, "external", both) == 3                                 # 표시도 없고 잠겨 있다
    assert evaluate(world, "external", both, extra=("--final-external",)) == 3    # 표시만으로는 안 된다
    assert "잠겨 있다" in capsys.readouterr().err
    assert not (world["dir"] / "report.json").exists()
    world["lock"].write_text(json.dumps({"datasets": {"ext-set": {"status": "unlocked"}}}))
    assert evaluate(world, "external", both) == 3                                 # 풀려도 표시가 필요하다
    assert evaluate(world, "external", both, extra=("--final-external",)) == 0
    report = json.loads((world["dir"] / "report.json").read_text())
    assert report["split"] == "external" and set(report["by_generator"]) == {"new0", "new1"}
    assert report["hygiene_warnings_in_split"]["identity_missing"] == 60
    assert report["hygiene_warnings_in_split"]["source_unverified"] == 6
    assert report["threshold"]["source_split"] == "dev"


def test_external_overlap_with_training_sources_blocks_evaluation(world, capsys):
    assert fit(world) == 0
    train = next(r for r in world["records"] if r.split == "train")
    overlap = world["dir"] / "overlap.csv"
    manifest.write_manifest(overlap, [fake("ex", source=train.source_recording_id, split="external", dataset="ext-set")])
    world["lock"].write_text(json.dumps({"datasets": {"ext-set": {"status": "unlocked"}}}))
    assert evaluate(world, "external", [world["manifest"], overlap], extra=("--final-external",)) == 1
    assert "source_overlap_external_internal" in capsys.readouterr().err


def test_external_records_cannot_be_used_to_fit_threshold(world):
    as_dev = world["dir"] / "as_dev.csv"
    manifest.write_manifest(as_dev, [r.with_split("dev") for r in manifest.read_manifest(world["external"])])
    assert fit(world, **{"--manifest": as_dev}) == 1  # 누수 검사에서 걸린다
    assert not world["threshold"].exists()


def test_scores_for_unknown_videos_are_an_error(world):
    assert fit(world) == 0
    with world["scores"].open("a", newline="") as f:
        csv.writer(f).writerow(["synth", "ghost", "1.0", "completed", "", "", "", ""])
    assert evaluate(world) == 1


@pytest.mark.parametrize("cell", ["abc", "nan", "inf"])
def test_non_finite_or_non_numeric_scores_are_rejected(tmp_path, cell):
    path = tmp_path / "s.csv"
    path.write_text(f"dataset_id,video_id,score\nsynth,a,{cell}\n")
    with pytest.raises(run.InputError):
        run.read_scores(path)


def test_blank_score_is_none_not_zero(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("dataset_id,video_id,score,status,reason_code\nsynth,a,,error,inference_error\nsynth,b,0,completed,\n")
    scores = run.read_scores(path)
    assert scores["synth:a"]["score"] is None and scores["synth:b"]["score"] == 0.0
    items = run.build_items([rec("a"), rec("b"), rec("c")], {"synth:a": "g", "synth:b": "g", "synth:c": "g"}, scores)
    assert [(it.score, it.reason_code) for it in items] == [(None, "inference_error"), (0.0, ""), (None, "missing_score")]


def test_coverage_summary_is_none_without_durations():
    out = run.coverage_summary([rec("a")], {"synth:a": {"score": 1.0, **{k: None for k in run.DURATION_FIELDS}}})
    assert out["full_video_coverage"] is None and out["video_duration_sec"] is None
    assert out["videos_with_duration"] == 0
