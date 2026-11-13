"""MAVOS-DD 표본의 공통 manifest 변환과 메타데이터 검사. 추론하지 않는다.

합성한 표본 목록으로 규칙을 확인하고, 실제 목록 파일이 있으면 그것도 검사한다(없으면 건너뜀).
"""

from __future__ import annotations

import hashlib

import pytest

from scripts import mavos_sample
from training import hygiene
from training.datasets import mavos
from training.evaluation import lock as lock_mod

REAL_MANIFEST = mavos.DATA_DIR / f"manifest-q{mavos_sample.PER_STRATUM}.csv"


def row(path, label="fake", category="sonic", language="english", source=None, size=1000):
    return {
        "video_path": path, "label": label, "category": category, "language": language,
        "open_set_model": "true", "audio_fake": "false", "video_fake": str(label == "fake").lower(),
        "source_group": source or f"yt:{hashlib.md5(path.encode()).hexdigest()[:11]}", "size_bytes": str(size),
    }


def sample_rows():
    rows = [row(f"english/sonic/{i}.mp4") for i in range(20)]
    rows += [row(f"english/knnvc/{i}.mp4", category="knnvc") for i in range(20)]
    rows += [row(f"english/real/{i}.mp4", label="real", category="real") for i in range(40)]
    # sonic 층의 하나는 원본 식별자가 없는 파일로 바꾼다
    rows[19] = row("english/sonic/uuid.mp4", source="unknown:english/sonic/uuid.mp4")
    return rows


def lock_for(sha):
    return {"mavos-dd": {"status": "locked", "manifest_sha256": sha}}


def test_to_records_uses_common_schema_and_marks_external():
    records = mavos.to_records(sample_rows())
    assert {r.dataset_id for r in records} == {"mavos-dd"} and {r.split for r in records} == {"external"}
    assert all(r.identity_ids == () and r.source_recording_id for r in records)
    by_path = {r.video_path: r for r in records}
    assert (by_path["english/sonic/0.mp4"].generator_id, by_path["english/sonic/0.mp4"].manipulation_type) == ("sonic", "A1")
    assert by_path["english/knnvc/0.mp4"].manipulation_type == "B1"
    real = by_path["english/real/0.mp4"]
    assert (real.label, real.generator_id, real.manipulation_type) == ("real", "", "")


def test_manipulation_type_mapping_is_marked_provisional_and_covers_all_folders():
    assert mavos.MANIPULATION_TYPE_PROVISIONAL is True
    assert set(mavos.MANIPULATION_TYPE_BY_GENERATOR) == {
        "echomimic", "memo", "sonic", "liveportrait", "hififace", "roop", "inswapper", "freevc", "knnvc"}


def test_check_sample_passes_and_reports_no_inference(tmp_path):
    rows = sample_rows()
    out = mavos.check_sample(rows, "abc", lock_for("abc"), data_dir=tmp_path)
    assert out["ok"] and out["problems"] == []
    assert (out["videos"], out["real"], out["fake"]) == (80, 40, 40)
    assert out["source_unverified"] == 1 and out["files_missing"] == 80
    assert out["inference_run"] is False and out["lock_status"] == "locked"


def test_check_sample_detects_rule_violations(tmp_path):
    rows = sample_rows()
    assert "sha256" in mavos.check_sample(rows, "abc", lock_for("other"), tmp_path)["problems"][0]
    assert not mavos.check_sample(rows, "abc", {}, tmp_path)["ok"]
    too_many = rows + [row("english/sonic/extra.mp4")]
    assert any("층당 개수" in p for p in mavos.check_sample(too_many, "abc", lock_for("abc"), tmp_path)["problems"])
    same_source = [dict(r, source_group="yt:AAAAAAAAAAA") if r["category"] == "sonic" else r for r in rows]
    assert any("원본 묶음" in p for p in mavos.check_sample(same_source, "abc", lock_for("abc"), tmp_path)["problems"])
    huge = [dict(rows[0], size_bytes=str(11 * 10**9))] + rows[1:]
    assert any("10 GB" in p for p in mavos.check_sample(huge, "abc", lock_for("abc"), tmp_path)["problems"])
    mislabeled = [dict(rows[0], label="real")] + rows[1:]
    assert any("라벨" in p for p in mavos.check_sample(mislabeled, "abc", lock_for("abc"), tmp_path)["problems"])


def test_check_sample_compares_file_sizes_without_reading_content(tmp_path):
    rows = sample_rows()
    target = tmp_path / rows[0]["video_path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * 1000)
    assert mavos.check_sample(rows, "abc", lock_for("abc"), tmp_path)["files_present"] == 1
    target.write_bytes(b"x" * 999)
    assert any("크기" in p for p in mavos.check_sample(rows, "abc", lock_for("abc"), tmp_path)["problems"])


def test_mavos_records_pass_hygiene_with_identity_warning_and_fail_if_used_internally():
    records = mavos.to_records(sample_rows())
    lock = lock_for("abc")
    report = hygiene.check(records, lock)
    assert report.ok
    assert report.warnings["identity_missing"] == 80 and report.warnings["source_unverified"] == 1
    moved = [r.with_split("dev") for r in records]
    assert "external_dataset_in_internal_split" in {e["code"] for e in hygiene.check(moved, lock).errors}


def test_cli_missing_manifest(tmp_path, capsys):
    assert mavos.main(["check", "--manifest", str(tmp_path / "none.csv")]) == 2
    assert "파일 없음" in capsys.readouterr().err


@pytest.mark.skipif(not REAL_MANIFEST.is_file(), reason="MAVOS-DD 표본 목록이 없다 (data/research/mavos-dd)")
def test_real_sample_manifest_matches_lock_and_rules():
    """실제 표본 목록의 메타데이터 검사. 영상을 열지 않고 추론하지 않는다."""
    rows, sha256 = mavos.read_sample_manifest(REAL_MANIFEST)
    lock = lock_mod.load_lock()
    out = mavos.check_sample(rows, sha256, lock)
    assert out["ok"], out["problems"]
    assert (out["videos"], out["real"], out["fake"]) == (2160, 1080, 1080)
    assert out["bytes"] == 6_766_772_622 and out["strata"] == 60
    assert out["lock_status"] == "locked"
    report = hygiene.check(mavos.to_records(rows), lock)
    assert report.ok
    assert report.warnings["identity_missing"] == 2160
