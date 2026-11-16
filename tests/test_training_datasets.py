"""데이터셋 어댑터, 그룹 크기 요약, 파생본의 부모 분할 상속. 합성 행만 쓴다."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from training import hygiene
from training.datasets import adapters, groups
from training.datasets.manifest import Record, read_manifest
from training.emulator.pipeline import derive_record

REPO_ROOT = Path(__file__).resolve().parent.parent
DEEPSPEAK = REPO_ROOT / "configs/datasets/deepspeak_v2.json"
LOCK = {"mavos-dd": {"status": "locked"}}


def real(i, identity, split="train", nested=False):
    meta = {"identity": identity}
    row = {"video-file": f"real/{i}.mp4", "type": "real", "split": split}
    row.update({"metadata-real": meta} if nested else meta)
    return row


def fake(i, kind, src, tgt, split="train", engine="facefusion", gen="", rec_t=None):
    return {"video-file": f"fake/{i}.mp4", "type": "fake", "split": split, "kind": kind, "engine": engine,
            "identity-source": src, "identity-target": tgt, "recording-source": 100 + src,
            "recording-target": rec_t if rec_t is not None else 200 + tgt, "gen-config": gen, "audio-config": "real"}


def rows_clean():
    rows = []
    for person in range(40):
        split = "test" if person >= 32 else "train"
        rows.append(real(person, person, split, nested=person % 2 == 0))
        # 같은 분할의 이웃 인물과만 얼굴을 바꾼다(짝 단위 그룹)
        partner = person + 1 if person % 2 == 0 else person - 1
        rows.append(fake(person, "face-swap", person, partner, split))
    return rows


def test_deepspeak_config_marks_card_and_unconfirmed_fields():
    config = adapters.load_config(DEEPSPEAK)
    assert config["status"] == "card_only"
    unconfirmed = adapters.unconfirmed_fields(config)
    assert {"official_split", "video_id", "real_recording"} <= set(unconfirmed)
    assert "fake_engine" not in unconfirmed and "real_identity" not in unconfirmed
    assert config["manipulation_type"]["provisional"] is True


def test_hidf_config_is_empty_and_refused():
    raw = json.loads((REPO_ROOT / "configs/datasets/hidf.json").read_text(encoding="utf-8"))
    assert raw["fields"] == {} and raw["status"] == "unconfirmed"
    with pytest.raises(adapters.AdapterError, match="확인하지 않은"):
        adapters.load_config(REPO_ROOT / "configs/datasets/hidf.json")


def test_rows_become_common_records_with_group_keys():
    config = adapters.load_config(DEEPSPEAK)
    r, official = adapters.to_record(real(1, 7, nested=True), config, 1)
    assert (r.label, r.identity_ids, official) == ("real", ("deepspeak:id:7",), "train")
    assert r.source_unverified  # 진짜 영상의 녹화 ID는 카드에 없다. 추측하지 않는다
    f, _ = adapters.to_record(fake(2, "face-swap", 7, 9, gen="inswapper_128_fp16_codeformer_512512"), config, 2)
    assert f.identity_ids == ("deepspeak:id:7", "deepspeak:id:9")
    assert f.source_recording_id == "deepspeak:rec:209"
    assert f.generator_id == "facefusion/inswapper_128_fp16_codeformer_512512" and f.manipulation_type == "C2"
    lip, _ = adapters.to_record(fake(3, "lip-sync", 7, 7, engine="diff2lip"), config, 3)
    assert lip.manipulation_type == "B2" and lip.identity_ids == ("deepspeak:id:7",)
    gid = groups.group_ids([r, f, lip])
    assert len(set(gid.values())) == 1  # 인물로 한 그룹에 묶인다


def test_official_test_is_kept_and_train_is_split_by_group():
    config = adapters.load_config(DEEPSPEAK)
    records = adapters.convert(rows_clean(), config)
    by_uid = {r.video_path: r for r in records}
    assert all(by_uid[f"real/{p}.mp4"].split == "test" for p in range(32, 40))
    assert {r.split for r in records} == {"train", "dev", "test"}
    summary = adapters.summarize(records, config, LOCK)
    assert summary["hygiene"]["ok"] and summary["unconfirmed_fields"]
    assert summary["group_sizes"]["groups"] == 20 and summary["group_sizes"]["within_limit"]
    assert adapters.convert(rows_clean(), config) == records  # 결정적이다


def test_official_split_that_cuts_a_group_fails_instead_of_resplitting(tmp_path):
    rows = rows_clean()
    rows.append(fake(999, "face-swap", 0, 39, "train"))  # 공식 train의 가짜가 공식 test 인물과 이어진다
    src = tmp_path / "rows.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tmp_path / "manifest.csv"
    assert adapters.main(["--config", str(DEEPSPEAK), "--rows", str(src), "--out", str(out)]) == 1
    assert not out.exists()
    config = adapters.load_config(DEEPSPEAK)
    report = adapters.summarize(adapters.convert(rows, config), config, LOCK)["hygiene"]
    assert "group_spans_splits" in [e["code"] for e in report["errors"]]


def test_cli_writes_manifest_for_clean_rows(tmp_path):
    src = tmp_path / "rows.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in rows_clean()), encoding="utf-8")
    out = tmp_path / "manifest.csv"
    assert adapters.main(["--config", str(DEEPSPEAK), "--rows", str(src), "--out", str(out)]) == 0
    assert len(read_manifest(out)) == 80


@pytest.mark.parametrize("row", [
    {"type": "real", "split": "train", "identity": 1},
    {"video-file": "a.mp4", "type": "audio-only", "split": "train"},
    {"video-file": "a.mp4", "type": "real", "identity": 1},
    {"video-file": "a.mp4", "type": "real", "identity": 1, "split": "validation"},
])
def test_unreadable_rows_are_errors_not_guesses(row):
    with pytest.raises(adapters.AdapterError):
        adapters.convert([row], adapters.load_config(DEEPSPEAK))


def rec(vid, split="train", **kw):
    return Record(dataset_id="synth", video_id=vid, video_path=f"{vid}.mp4", label=kw.pop("label", "real"),
                  source_recording_id=kw.pop("source", f"s-{vid}"), split=split, **kw)


def test_group_size_summary_flags_giant_group():
    chained = [rec(f"v{i}", identity_ids=(f"p{i}", f"p{i + 1}")) for i in range(6)] + [rec("solo1"), rec("solo2")]
    s = groups.size_summary(chained)
    assert s["largest_group_videos"] == 6 and s["largest_group_share"] == 0.75
    assert s["max_group_share"] == 0.25 and not s["within_limit"]
    assert s["groups"] == 3 and s["groups_by_size"] == {"1": 2, "2-5": 0, "6-20": 1, "21-100": 0, "101+": 0}
    assert groups.size_summary(chained, max_share=0.8)["within_limit"]
    assert groups.size_summary([rec("e", split="external")])["largest_group_share"] is None


def test_derived_rows_inherit_parent_split_and_violations_fail():
    parent = rec("a", split="dev", label="fake", generator_id="g")
    child = derive_record(parent, "x264-crf28-720p", "out/a.mp4", "h")
    assert (child.split, child.label, child.parent_video_id) == ("dev", "fake", "a")
    assert hygiene.check([parent, child], LOCK).ok
    for bad in (replace(child, split="train"), replace(child, split="test")):
        codes = [e["code"] for e in hygiene.check([parent, bad], LOCK).errors]
        assert "derived_not_inheriting_parent" in codes and "group_spans_splits" in codes
    relabeled = replace(child, label="real", generator_id="")
    assert "derived_not_inheriting_parent" in [e["code"] for e in hygiene.check([parent, relabeled], LOCK).errors]
    orphan = hygiene.check([child], LOCK)
    assert orphan.warnings["derived_parent_missing"] == 1
