"""압축 에뮬레이터(범용 프로파일)와 manifest·지표 연결 (백로그 9번).

영상은 FFmpeg가 만든 합성 무늬다. 실제 영상도 데이터셋도 쓰지 않는다.
여기 나오는 점수는 파이프라인 동작 확인용 가짜 값이며 성능과 무관하다.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from training import hygiene
from training.datasets import manifest
from training.datasets.manifest import ManifestError, Record
from training.emulator import pipeline, profiles, video
from training.emulator.profiles import ProfileError
from training.emulator.video import EmulatorError
from training.evaluation import metrics, run
from training.evaluation.metrics import Item

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe가 없다")


def make_video(path: Path, size="640x360", seconds=1, audio=True) -> Path:
    args = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=15:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def src(tmp_path_factory) -> Path:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe가 없다")
    return make_video(tmp_path_factory.mktemp("src") / "clip.mp4")


# ---------- 프로파일 ----------

def test_profile_matrix_is_crf_times_resolution():
    assert len(profiles.PROFILES) == 12
    assert {p.crf for p in profiles.PROFILES.values()} == {20, 28, 34}
    assert {p.short_side for p in profiles.PROFILES.values()} == {None, 1080, 720, 480}
    p = profiles.get_profile("x264-crf28-720p")
    assert (p.crf, p.short_side, p.encoder) == (28, 720, "libx264")


def test_unknown_profile_is_rejected():
    with pytest.raises(ProfileError):
        profiles.get_profile("youtube-1080p")


@pytest.mark.parametrize("encoder", ["h264_videotoolbox", "hevc_videotoolbox", "h264_nvenc", "libx265"])
def test_hardware_and_other_encoders_are_rejected(encoder):
    with pytest.raises(ProfileError):
        profiles.Profile(profile_id="x", crf=28, short_side=None, encoder=encoder)


def test_ffmpeg_args_use_software_encoder_and_are_a_list():
    for p in profiles.PROFILES.values():
        args = video.build_args("ffmpeg", Path("in put;rm.mp4"), Path("out.mp4"), p)
        assert isinstance(args, list) and all(isinstance(a, str) for a in args)
        assert args[args.index("-c:v") + 1] == "libx264"
        assert not any("videotoolbox" in a for a in args)
        assert "in put;rm.mp4" in args  # 경로는 인자 하나로 그대로 간다
        assert args[args.index("-threads") + 1] == str(p.threads)
        assert "-n" in args and "-y" not in args


# ---------- 열화 영상 ----------

@needs_ffmpeg
def test_emulate_records_parameters_and_hashes(src, tmp_path):
    lineage = {"source_recording_id": "src-1", "derivation_group_id": "clip", "split": "dev"}
    r = video.emulate(src, "x264-crf28-source", tmp_path, lineage=lineage)
    out = tmp_path / "clip__x264-crf28-source.mp4"
    assert r["status"] == "completed" and out.is_file()
    assert r["profile_id"] == "x264-crf28-source" and r["profile"]["crf"] == 28
    assert r["profile"]["encoder"] == "libx264" and r["profile"]["threads"] == 4
    assert r["ffmpeg_version"].startswith("ffmpeg version")
    assert "<input>" in r["ffmpeg_args"] and "<output>" in r["ffmpeg_args"]
    assert str(tmp_path) not in json.dumps(r)  # 로컬 경로를 기록에 남기지 않는다
    assert r["input"]["sha256"] == manifest.sha256_file(src)
    assert r["output"]["sha256"] == manifest.sha256_file(out)
    assert (r["output"]["codec"], r["output"]["width"], r["output"]["height"]) == ("h264", 640, 360)
    assert r["lineage"]["split"] == "dev" and r["lineage"]["source_recording_id"] == "src-1"
    assert "YouTube" in r["note"]
    assert json.loads((tmp_path / (out.name + ".json")).read_text()) == r


@needs_ffmpeg
def test_same_input_gives_identical_output(src, tmp_path):
    a = video.emulate(src, "x264-crf34-source", tmp_path / "a")
    b = video.emulate(src, "x264-crf34-source", tmp_path / "b")
    assert a["output"]["sha256"] == b["output"]["sha256"]
    assert a == b  # 기록 전체가 같다(시각·경로가 들어가지 않는다)
    c = video.emulate(src, "x264-crf20-source", tmp_path / "c")
    assert c["output"]["sha256"] != a["output"]["sha256"]
    assert c["output"]["size_bytes"] > a["output"]["size_bytes"]


@needs_ffmpeg
def test_downscale_keeps_aspect_and_upscale_is_skipped(tmp_path):
    big = make_video(tmp_path / "big.mp4", size="1280x720", audio=False)
    r = video.emulate(big, "x264-crf28-480p", tmp_path / "out")
    assert (r["output"]["width"], r["output"]["height"]) == (854, 480)
    same = video.emulate(big, "x264-crf28-720p", tmp_path / "out")
    assert (same["output"]["width"], same["output"]["height"]) == (1280, 720)
    up = video.emulate(big, "x264-crf28-1080p", tmp_path / "out")
    assert up["status"] == "skipped_upscale" and up["output"] is None
    assert not (tmp_path / "out" / "big__x264-crf28-1080p.mp4").exists()
    assert (tmp_path / "out" / "big__x264-crf28-1080p.mp4.json").is_file()  # 건너뛴 이유는 남긴다


@needs_ffmpeg
def test_portrait_video_uses_short_side(tmp_path):
    tall = make_video(tmp_path / "tall.mp4", size="720x1280", audio=False)
    r = video.emulate(tall, "x264-crf28-480p", tmp_path / "out")
    assert (r["output"]["width"], r["output"]["height"]) == (480, 854)


@needs_ffmpeg
def test_source_is_never_modified_or_overwritten(src, tmp_path):
    copy = tmp_path / "clip.mp4"
    shutil.copy(src, copy)
    before = manifest.sha256_file(copy)
    video.emulate(copy, "x264-crf28-source", tmp_path)  # 입력과 같은 폴더여도 이름이 다르다
    assert manifest.sha256_file(copy) == before
    with pytest.raises(EmulatorError):  # 이미 있는 출력
        video.emulate(copy, "x264-crf28-source", tmp_path)
    # 출력 이름에는 항상 "__<프로파일>"이 붙어서 입력과 같은 이름이 될 수 없다
    assert video.output_name(copy, "x264-crf28-source") != copy.name
    assert manifest.sha256_file(copy) == before


@needs_ffmpeg
def test_bad_input_is_reported_as_error_without_output(tmp_path):
    with pytest.raises(EmulatorError):
        video.emulate(tmp_path / "missing.mp4", "x264-crf28-source", tmp_path)
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    with pytest.raises(EmulatorError):
        video.emulate(junk, "x264-crf28-source", tmp_path / "out")
    with pytest.raises(EmulatorError):
        video.emulate(junk, "x264-crf28-source", tmp_path / "out", lineage={"url": "x"})


@needs_ffmpeg
def test_encode_failure_returns_error_status(src, tmp_path, monkeypatch):
    real = video.build_args
    monkeypatch.setattr(video, "build_args", lambda *a: real(*a)[:-1] + ["-bogus-option", a[2].as_posix()])
    r = video.emulate(src, "x264-crf28-source", tmp_path)
    assert r["status"] == "error" and r["output"] is None and r["reason"]
    assert not list(tmp_path.glob("*.mp4")) and not list(tmp_path.glob("*.partial"))


# ---------- manifest 연결 ----------

def rec(video_id, label="real", split="test", **kw) -> Record:
    return Record(dataset_id="synth", video_id=video_id, video_path=f"synth/{video_id}.mp4",
                  label=label, source_recording_id=f"src-{video_id}", split=split, **kw)


def test_manifest_roundtrips_compression_column(tmp_path):
    parent = rec("a", identity_ids=("p1",))
    child = pipeline.derive_record(parent, "x264-crf28-720p", "out/a.mp4", "ff" * 32)
    path = tmp_path / "m.csv"
    manifest.write_manifest(path, [parent, child])
    assert manifest.read_manifest(path) == sorted([parent, child], key=lambda r: r.uid)
    assert "compression_profile_id" in path.read_text().splitlines()[0]


def test_old_manifest_without_compression_column_still_reads(tmp_path):
    path = tmp_path / "old.csv"
    old_fields = [f for f in manifest.FIELDS if f != "compression_profile_id"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_fields)
        w.writeheader()
        w.writerow({k: v for k, v in rec("a").to_row().items() if k in old_fields})
    (got,) = manifest.read_manifest(path)
    assert got.compression_profile_id == ""


def test_original_is_blank_not_a_literal():
    with pytest.raises(ManifestError):
        manifest.validate([rec("a", compression_profile_id="original")])


def test_derived_record_inherits_split_and_lineage():
    parent = rec("a", label="fake", split="dev", generator_id="genA", manipulation_type="A1",
                 identity_ids=("p1",))
    child = pipeline.derive_record(parent, "x264-crf34-480p", "out/a.mp4", "ab" * 32)
    assert child.video_id == "a@x264-crf34-480p" and child.parent_video_id == "a"
    assert child.compression_profile_id == "x264-crf34-480p"
    assert (child.split, child.label, child.source_recording_id) == ("dev", "fake", "src-a")
    assert (child.generator_id, child.manipulation_type, child.identity_ids) == ("genA", "A1", ("p1",))
    assert child.derivation_group_id == "a" and child.file_hash == "ab" * 32


def test_derive_requires_split_and_rejects_reencoding_and_unknown_profile():
    with pytest.raises(EmulatorError):
        pipeline.derive_record(rec("a", split=""), "x264-crf28-720p", "p", "")
    child = pipeline.derive_record(rec("a"), "x264-crf28-720p", "p", "")
    with pytest.raises(EmulatorError):
        pipeline.derive_record(child, "x264-crf34-720p", "p", "")
    with pytest.raises(ProfileError):
        pipeline.derive_record(rec("a"), "nope", "p", "")


def test_compressed_copy_in_another_split_fails_hygiene():
    parent = rec("a", split="train")
    child = pipeline.derive_record(parent, "x264-crf28-720p", "p", "")
    other = rec("b", split="test")
    assert hygiene.check([parent, child, other], {}).ok
    moved = child.with_split("test")
    report = hygiene.check([parent, moved, other], {})
    assert "group_spans_splits" in {e["code"] for e in report.errors}


@needs_ffmpeg
def test_pipeline_cli_writes_derived_rows(src, tmp_path, capsys):
    media = tmp_path / "media"
    (media / "synth").mkdir(parents=True)
    shutil.copy(src, media / "synth" / "a.mp4")
    make_video(media / "synth" / "b.mp4", size="320x240", audio=False)  # 분할이 다르므로 다른 영상
    m_in, m_out = tmp_path / "in.csv", tmp_path / "out.csv"
    manifest.write_manifest(m_in, [rec("a", split="dev"), rec("b", label="fake", split="test", generator_id="g")])
    argv = ["--manifest", str(m_in), "--media-root", str(media), "--out-dir", str(tmp_path / "derived"),
            "--profile", "x264-crf28-source", "--profile", "x264-crf28-1080p", "--out-manifest", str(m_out)]
    assert pipeline.main(argv) == 0
    rows = manifest.read_manifest(m_out)
    by_cond = {(r.video_id, r.compression_profile_id): r for r in rows}
    assert set(by_cond) == {("a", ""), ("b", ""), ("a@x264-crf28-source", "x264-crf28-source"),
                            ("b@x264-crf28-source", "x264-crf28-source")}  # 1080p는 업스케일이라 행이 없다
    child = by_cond[("a@x264-crf28-source", "x264-crf28-source")]
    assert child.split == "dev" and Path(child.video_path).is_file()
    assert child.file_hash == manifest.sha256_file(Path(child.video_path))
    meta = json.loads(Path(child.video_path + ".json").read_text())
    assert meta["lineage"] == {"dataset_id": "synth", "video_id": "a", "source_recording_id": "src-a",
                               "derivation_group_id": "a", "split": "dev"}
    assert hygiene.check(rows, {}).ok
    assert "skipped_upscale" in capsys.readouterr().out
    assert pipeline.main(argv) == 1  # out-manifest를 덮어쓰지 않는다


# ---------- 압축 조건별 지표 ----------

def _items() -> list[Item]:
    """원본은 잘 갈리고 압축본은 덜 갈리는 가짜 점수. 성능이 아니다."""
    rng = random.Random(0)
    out = []
    for g in range(60):
        label = "fake" if g % 2 else "real"
        for cond, sep in (("", 3.0), ("x264-crf34-480p", 0.5)):
            score = rng.gauss(sep if label == "fake" else 0.0, 1.0)
            out.append(Item(uid=f"v{g}{cond}", label=label, group=f"g{g}", score=score,
                            generator="genA" if label == "fake" else "", compression=cond))
    return out


def test_by_compression_reports_each_condition_separately():
    items = _items()
    out = metrics.evaluate(items, threshold=1.5, n_boot=100, seed=1)
    by = out["by_compression"]
    assert set(by) == {"original", "x264-crf34-480p"}
    for name, cond in (("original", ""), ("x264-crf34-480p", "x264-crf34-480p")):
        members = [it for it in items if it.compression == cond]
        expect = metrics.point_metrics([Item(**{**it.__dict__, "compression": ""}) for it in members], 1.5)
        assert by[name]["videos"] == 60 and by[name]["real"] == 30 and by[name]["fake"] == 30
        assert by[name]["groups"] == 60
        for m in ("roc_auc", "tpr", "fpr"):
            assert by[name][m]["value"] == expect[m]
            assert by[name][m]["ci_low"] <= by[name][m]["value"] <= by[name][m]["ci_high"]
    assert by["original"]["roc_auc"]["value"] > by["x264-crf34-480p"]["roc_auc"]["value"]


def test_by_compression_is_overall_when_nothing_is_compressed():
    items = [it for it in _items() if not it.compression]
    out = metrics.evaluate(items, threshold=1.5, n_boot=50, seed=1)
    assert set(out["by_compression"]) == {"original"}
    for m in ("roc_auc", "tpr", "fpr"):
        assert out["by_compression"]["original"][m] == out["overall"][m]


def test_by_compression_uses_null_not_zero_when_a_class_is_missing():
    items = [Item("a", "fake", "g1", 2.0, compression="x264-crf28-720p"),
             Item("b", "fake", "g2", None, reason_code="error", compression="x264-crf28-720p"),
             Item("c", "real", "g3", 0.0)]
    by = metrics.evaluate(items, threshold=1.0, n_boot=20, seed=0)["by_compression"]
    c = by["x264-crf28-720p"]
    assert c["roc_auc"]["value"] is None and c["fpr"]["value"] is None and c["tpr"]["value"] == 1.0
    assert (c["fake"], c["fake_scored"], c["real"]) == (2, 1, 0)
    assert by["original"]["tpr"]["value"] is None


def test_evaluate_cli_report_has_by_compression(tmp_path):
    rng = random.Random(1)
    records, rows = [], []
    for i in range(40):
        label = "fake" if i % 2 else "real"
        split = "dev" if i < 20 else "test"
        kw = {"generator_id": "genA", "manipulation_type": "A1"} if label == "fake" else {}
        parent = rec(f"v{i}", label=label, split=split, **kw)
        child = pipeline.derive_record(parent, "x264-crf28-720p", f"out/v{i}.mp4", "")
        for r, sep in ((parent, 3.0), (child, 1.0)):
            records.append(r)
            rows.append((r.video_id, rng.gauss(sep if label == "fake" else 0.0, 1.0)))
    m, s, t, out = (tmp_path / n for n in ("m.csv", "s.csv", "t.json", "r.json"))
    manifest.write_manifest(m, records)
    with s.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "video_id", "score", "status", "reason_code"])
        w.writerows(["synth", vid, score, "completed", ""] for vid, score in rows)
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"datasets": {}}))
    common = ["--manifest", str(m), "--scores", str(s), "--lock", str(lock)]
    assert run.main(["fit-threshold", *common, "--model-id", "synthetic", "--out", str(t)]) == 0
    assert run.main(["evaluate", *common, "--threshold", str(t), "--split", "test",
                     "--out", str(out), "--n-boot", "50"]) == 0
    report = json.loads(out.read_text())
    assert report["schema_version"] == 2
    by = report["by_compression"]
    assert set(by) == {"original", "x264-crf28-720p"}
    assert by["original"]["videos"] == by["x264-crf28-720p"]["videos"] == 20
    assert by["original"]["groups"] == 20 and report["counts"]["groups"] == 20  # 부모와 파생본은 한 그룹
    assert any("YouTube" in n for n in report["notes"])
