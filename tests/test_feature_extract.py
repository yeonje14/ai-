"""일괄 특징 추출: 캐시·이어 돌리기·실패 격리·요약. 축 실행은 가짜 함수로 바꾼다(모델을 돌리지 않는다)."""
import json
import sys
from pathlib import Path

import pytest

from server.axes.physics.motionphys import MotionPhysConfig, run_motionphys
from training.datasets.manifest import Record, sha256_file, write_manifest
from training.features import extract
from tests.test_motionphys_adapter import FAKE_HEAD, WRITE

LOCK_TEXT = json.dumps({"schema_version": 1, "datasets": {"mavos-dd": {"status": "locked", "role": "final_external"}}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    lock = tmp_path / "lock.json"
    lock.write_text(LOCK_TEXT, encoding="utf-8")
    calls = []

    def gate(m, work, segments, settings):
        calls.append(("gate", m.read_bytes()))
        assert m.parent == work
        if m.read_bytes() == b"silent":
            return {"status": "insufficient_input", "reason_code": "no_speech_detected", "video_duration_sec": 9.0,
                    "eligible_duration_sec": 0.0, "eligible_segments": [], "media": None}
        return {"status": "completed", "reason_code": None, "video_duration_sec": 10.0,
                "eligible_duration_sec": 5.0, "eligible_segments": [[1.0, 6.0]], "media": None}

    def wave(m, work, segments, settings):
        calls.append(("waverep", m.read_bytes()))
        assert segments == [[1.0, 6.0]]
        # 실제 실행기처럼 쓴 장치를 적는다. 설정(기본 mps)과 다르면 캐시를 다시 계산한다(감사 A4)
        return {"status": "completed", "reason_code": None, "frame_logits": [1.0, 3.0, 8.0],
                "device_used": settings["waverep"]["device"]}

    def phys(m, work, segments, settings):
        calls.append(("motionphys", m.read_bytes()))
        ok = {"status": "completed", "reason_code": None, "features": [0.5, 1.5]}
        return {"status": "completed", "reason_code": None, "variants": {
            "full": ok, "face_roi": {"status": "insufficient_input", "reason_code": "tracking_failed", "features": None},
            "face_motion": ok}}

    def sync(m, work, segments, settings):
        calls.append(("syncnet", m.read_bytes()))
        if m.read_bytes() == b"crash":
            raise RuntimeError("secret path /x/y")
        return {"status": "completed", "reason_code": None, "device_used": settings["syncnet"]["device"], "segments": [
            {"tracks": [{"lse_c": 4.0, "lse_d": 8.0, "offset_frames": -2}, {"lse_c": 6.0, "lse_d": 7.0, "offset_frames": 4}]},
            {"tracks": None}]}

    monkeypatch.setattr(extract, "RUNNERS", {"gate": gate, "waverep": wave, "motionphys": phys, "syncnet": sync})

    def make(names, **kw):
        records = []
        for name in names:
            (media / f"{name}.mp4").write_bytes(name.encode())
            records.append(Record(dataset_id="synth", video_id=name, video_path=f"{name}.mp4", label="real",
                                  source_recording_id=f"s-{name}", split=kw.get("split", "train")))
        return records

    def run(records, **kw):
        manifest = tmp_path / "m.csv"
        write_manifest(manifest, records)
        return extract.run(manifest, media, tmp_path / "out", lock_path=lock, **kw)

    return make, run, calls, tmp_path / "out"


def rows(out):
    return {json.loads(line)["uid"]: json.loads(line) for line in (out / "features.jsonl").read_text().splitlines()}


def test_features_are_summarized_per_video_with_nulls_for_failures(env):
    make, run, calls, out = env
    meta = run(make(["ok", "silent"]))
    r = rows(out)
    ok = r["synth:ok"]["axes"]
    assert ok["waverep"]["logit_median"] == 3.0 and ok["waverep"]["logit_mean"] == 4.0 and ok["waverep"]["frames"] == 3
    assert ok["motionphys"]["variants"]["full"]["features"] == [0.5, 1.5]
    assert ok["motionphys"]["variants"]["face_roi"] == {"status": "insufficient_input",
                                                        "reason_code": "tracking_failed", "features": None}
    assert ok["syncnet"] == {"status": "completed", "reason_code": None, "tracks": 2, "lse_c_median": 5.0,
                             "lse_d_median": 7.5, "abs_offset_median": 3.0}
    silent = r["synth:silent"]
    assert silent["gate_reason"] == "no_speech_detected"
    for axis in ("waverep", "motionphys", "syncnet"):  # Gate가 거르면 모델을 돌리지 않는다
        assert silent["axes"][axis]["status"] == "insufficient_input"
        assert silent["axes"][axis]["reason_code"] == "no_speech_detected"
    assert silent["axes"]["waverep"]["logit_median"] is None  # 0이 아니다
    assert [c for c in calls if c[1] == b"silent"] == [("gate", b"silent")]
    assert meta["videos"] == 2 and meta["status_counts"]["waverep"] == {"completed": 1, "insufficient_input": 1}
    assert meta["features_sha256"] == sha256_file(out / "features.jsonl")
    assert not list((out / "work").iterdir())  # 작업 사본을 남기지 않는다


def test_second_run_uses_cache_and_only_new_videos_run(env):
    make, run, calls, out = env
    run(make(["a"]))
    first = len(calls)
    run(make(["a", "b"]))
    assert [c[1] for c in calls[first:]] == [b"b"] * 4
    log = [json.loads(line) for line in (out / "progress.jsonl").read_text().splitlines()]
    assert sum(1 for e in log if e["video"] == "synth:a" and e["cached"]) == 4
    assert all("elapsed_sec" in e for e in log if not e["cached"])


def test_cache_key_follows_file_content_and_config_not_name(env, tmp_path):
    settings = extract.default_settings()
    k = extract.cache_key("h1", "waverep", settings, [[0, 1]])
    assert k != extract.cache_key("h2", "waverep", settings, [[0, 1]])
    assert k != extract.cache_key("h1", "waverep", settings, [[0, 2]])
    changed = json.loads(json.dumps(settings))
    changed["waverep"]["sample_fps"] = 4.0
    assert k != extract.cache_key("h1", "waverep", changed, [[0, 1]])
    slower = json.loads(json.dumps(settings))
    slower["waverep"]["timeout_sec"] = 999
    assert k == extract.cache_key("h1", "waverep", slower, [[0, 1]])  # 제한 시간은 결과에 영향이 없다


def test_axis_crash_is_isolated_not_cached_and_retried(env):
    make, run, calls, out = env
    run(make(["crash", "ok"]))
    r = rows(out)
    assert r["synth:crash"]["axes"]["syncnet"]["status"] == "error"
    assert r["synth:crash"]["axes"]["syncnet"]["lse_c_median"] is None
    assert r["synth:crash"]["axes"]["waverep"]["logit_median"] == 3.0  # 다른 축은 남는다
    assert r["synth:ok"]["axes"]["syncnet"]["status"] == "completed"   # 다른 영상도 계속한다
    assert "secret" not in (out / "features.jsonl").read_text() + (out / "progress.jsonl").read_text()
    before = len(calls)
    run(make(["crash", "ok"]))
    assert calls[before:] == [("syncnet", b"crash")]  # 실패한 축만 다시 시도한다


def test_missing_file_and_hash_mismatch_do_not_get_features(env):
    make, run, calls, out = env
    records = make(["a", "b"])
    (out.parent / "media" / "a.mp4").unlink()
    from dataclasses import replace
    records[1] = replace(records[1], file_hash="0" * 64)
    run(records)
    r = rows(out)
    assert r["synth:a"]["axes"]["waverep"]["reason_code"] == "media_unreadable"
    assert r["synth:b"]["axes"]["waverep"]["reason_code"] == "file_hash_mismatch"
    assert calls == []


def test_external_videos_are_never_extracted_and_leaky_manifest_is_refused(env):
    make, run, calls, out = env
    from dataclasses import replace
    ext = [replace(r, dataset_id="mavos-dd", split="external") for r in make(["e"])]
    meta = run(make(["a"]) + ext)
    assert meta["external_videos_skipped"] == 1 and set(rows(out)) == {"synth:a"}
    assert all(c[1] == b"a" for c in calls)
    leaky = make(["x", "y"])
    leaky = [replace(leaky[0], source_recording_id="same"), replace(leaky[1], source_recording_id="same", split="test")]
    with pytest.raises(extract.ExtractError, match="누수"):
        run(leaky)


def test_feature_version_excludes_timeouts():
    v = extract.feature_version(extract.default_settings())
    assert set(v) == set(extract.AXES)
    assert all("timeout_sec" not in cfg and "version" in cfg for cfg in v.values())


def test_audio_track_rule_is_in_gate_and_syncnet_keys_only():
    """오디오를 읽는 축(Gate·SyncNet)만 트랙 선택 규칙을 키에 넣는다(docs/DESIGN.md §15.3 2026-11-19 D3)."""
    from server.gate import audio_track

    settings = extract.default_settings()
    v = extract.feature_version(settings)
    assert v["gate"]["audio_track_rule"] == v["syncnet"]["audio_track_rule"] == audio_track.RULE
    assert "audio_track_rule" not in v["waverep"] and "audio_track_rule" not in v["motionphys"]
    changed = json.loads(json.dumps(settings))
    for axis in ("gate", "syncnet"):
        changed[axis]["audio_track_rule"] = "other-rule"
        assert extract.cache_key("h", axis, settings, [[0, 1]]) != extract.cache_key("h", axis, changed, [[0, 1]])


def test_motionphys_adapter_returns_features_only_when_asked(tmp_path):
    work = tmp_path / "job"
    work.mkdir()
    video = work / "media.mp4"
    video.write_bytes(b"x")
    script = tmp_path / "fake.py"
    seen = tmp_path / "seen.json"
    script.write_text(FAKE_HEAD + f"Path({str(seen)!r}).write_text(json.dumps(r)); "
                      "out['variants']['face_roi'] = bad('tracking_failed'); " + WRITE)
    cfg = MotionPhysConfig(python=Path(sys.executable), script=script, timeout_sec=5)
    out = run_motionphys(video, [(0, 3)], work, cfg, include_features=True)
    assert json.loads(seen.read_text())["include_features"] is True
    assert out["variants"]["full"]["features"] == [1.0, 2.0]
    assert out["variants"]["face_roi"]["features"] is None  # 실패한 후보의 특징은 null
    plain = run_motionphys(video, [(0, 3)], work, cfg)
    assert "features" not in plain["variants"]["full"]
    script.write_text(FAKE_HEAD + "out['variants']['full']['features'] = [1.0, float('nan')]; " + WRITE)
    broken = run_motionphys(video, [(0, 3)], work, cfg, include_features=True)
    assert (broken["status"], broken["reason_code"]) == ("error", "inference_error")
