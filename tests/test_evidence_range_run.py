"""scripts/evidence_range_run.py: 네트워크·공식 패키지·모델 없이 상태 기록, 재개, 정리, 정지 규칙을 확인한다."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import evidence_range_run as er


def _rows(role, n):
    return [{"role": role, "order": str(i), "vendor": "00", "interaction_key": f"V00_S{i:04d}_I{i:08d}",
             "file_id_a": f"V00_S{i:04d}_I{i:08d}_P{2 * i + 1:04d}",
             "file_id_b": f"V00_S{i:04d}_I{i:08d}_P{2 * i + 2:04d}"} for i in range(n)]


def _index(ids):
    return {fid: {"label": "naturalistic", "split": "train", "batch_idx": "0", "archive_idx": "0"} for fid in ids}


class World:
    """가짜 다운로드: 원본 4종을 media에 만든다. 다른 세션 원본이 남아 있으면 실패시킨다."""

    def __init__(self, tmp_path, rows_by_role, free=50e9):
        self.root = tmp_path / "range_v2"
        self.media = tmp_path / "media"
        self.rows = rows_by_role
        self.free = free
        self.diag = {}          # (role, order) -> 진단 종류 (실패시킬 세션)
        self.pre_fail = set()   # 전처리를 실패시킬 (role, order, who)
        self.downloads = []

    def originals(self):
        return sorted(p.name for p in self.media.rglob("*") if p.is_file())

    def download(self, role, order):
        assert self.originals() == [], "원본은 한 번에 1세션만 있어야 한다"
        self.downloads.append((role, order))
        row = self.rows[role][order]
        ids = [row["file_id_a"], row["file_id_b"]]
        kind = self.diag.get((role, order))
        rec = {"downloads": {}}
        for fid in ids:
            if kind:
                rec["downloads"][fid] = {"status": "incomplete", "diagnosis": {"x.mp4": {"kind": kind}}}
                continue
            for p in er.original_paths(fid, _index([fid])[fid], self.media):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"x" * 10)
            rec["downloads"][fid] = {"status": "ok", "diagnosis": {}}
        return {"returncode": 0, "record": rec}

    def preprocess(self, mp4, wav, vad_json, out):
        assert mp4.exists() and wav.exists() and vad_json.exists()
        sdir = out.parent.parent
        key = (sdir.parent.name, int(sdir.name), out.stem)
        if key in self.pre_fail:
            raise RuntimeError("encode")
        out.write_bytes(b"pre" + out.stem.encode())
        return {"status": er.OK, "reason_code": None, "sha256": er.sha256_file(out), "bytes": out.stat().st_size}

    def fetch_deps(self):
        return er.FetchDeps(download=self.download, preprocess=self.preprocess, index=_index,
                            free_bytes=lambda: self.free, media=self.media)

    def progress(self):
        return er.Progress(self.root / "run.log")

    def fetch(self, roles=None, **kw):
        roles = roles or tuple(self.rows)
        return er.run_fetch(self.root, roles, self.rows, self.fetch_deps(), self.progress(), int(10e9), **kw)

    def state(self, role, order):
        return json.loads((er.session_dir(self.root, role, order) / "state.json").read_text())


def test_fetch_keeps_one_session_of_originals_and_resumes(tmp_path):
    w = World(tmp_path, {"range_fit": _rows("range_fit", 3), "range_check": _rows("range_check", 2)})
    assert w.fetch(max_sessions=2) == "max_sessions"
    assert w.originals() == []
    assert w.downloads == [("range_fit", 0), ("range_fit", 1)]
    assert w.fetch() == "complete"
    assert w.downloads[2:] == [("range_fit", 2), ("range_check", 0), ("range_check", 1)]
    st = w.state("range_fit", 0)["fetch"]
    assert st["status"] == er.OK and st["originals_removed"] and st["attempts"] == 1
    assert (er.session_dir(w.root, "range_fit", 0) / "pre/A.mp4").exists()
    # 다시 돌려도 끝난 세션은 받지 않는다
    assert w.fetch() == "complete" and len(w.downloads) == 5


def test_interrupted_session_is_cleaned_and_restarted(tmp_path):
    w = World(tmp_path, {"range_fit": _rows("range_fit", 1)})
    row = w.rows["range_fit"][0]
    # 이전 실행이 다운로드 뒤 꺼졌다: 상태는 pending, 원본과 부분 전처리본이 남아 있다
    for p in er.original_paths(row["file_id_a"], _index([row["file_id_a"]])[row["file_id_a"]], w.media):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"old")
    sdir = er.session_dir(w.root, "range_fit", 0)
    (sdir / "pre").mkdir(parents=True)
    (sdir / "pre/A.mp4").write_bytes(b"partial")
    er.write_json(sdir / "state.json", {"fetch": {"status": er.PENDING, "attempts": 1}})
    assert w.fetch() == "complete"
    st = w.state("range_fit", 0)["fetch"]
    assert st["status"] == er.OK and st["attempts"] == 2
    assert (sdir / "pre/A.mp4").read_bytes() == b"preA"
    assert w.originals() == []


def test_low_disk_stops_before_download(tmp_path):
    w = World(tmp_path, {"range_fit": _rows("range_fit", 2)}, free=9.9e9)
    assert w.fetch() == "low_disk"
    assert w.downloads == []
    assert "stop_low_disk" in (w.root / "run.log").read_text()


def test_network_failures_retry_then_stop_and_permanent_failures_move_on(tmp_path):
    w = World(tmp_path, {"range_fit": _rows("range_fit", 5)})
    w.diag = {("range_fit", 0): "http_404", ("range_fit", 1): "dns_error", ("range_fit", 2): "dns_error",
              ("range_fit", 3): "network_error"}
    assert w.fetch() == "network"
    assert w.state("range_fit", 0)["fetch"]["status"] == er.FAILED
    assert w.state("range_fit", 0)["fetch"]["reason_code"] == "download_http_404+incomplete"
    assert w.state("range_fit", 1)["fetch"]["status"] == er.RETRY
    w.diag = {("range_fit", 1): "dns_error"}
    assert w.fetch() == "complete"   # 1은 두 번째 시도도 실패, 나머지는 성공
    assert w.state("range_fit", 2)["fetch"]["status"] == er.OK
    assert w.fetch() == "complete"   # 세 번째 시도에서 영구 실패로 바뀐다
    st = w.state("range_fit", 1)["fetch"]
    assert (st["status"], st["attempts"]) == (er.FAILED, 3)
    assert w.originals() == []


def test_missing_record_is_retry_not_permanent(tmp_path):
    assert er.classify_download({"returncode": 2, "record": {}}, ["a", "b"]) == (er.RETRY, "fetch_no_record_rc2")


def test_one_person_preprocess_failure_keeps_other(tmp_path):
    w = World(tmp_path, {"range_fit": _rows("range_fit", 2)})
    w.pre_fail = {("range_fit", 0, "B"), ("range_fit", 1, "A"), ("range_fit", 1, "B")}
    assert w.fetch() == "complete"
    s0 = w.state("range_fit", 0)["fetch"]
    assert s0["status"] == er.OK and s0["people"]["B"]["reason_code"] == "preprocess_RuntimeError"
    assert not (er.session_dir(w.root, "range_fit", 0) / "pre/B.mp4").exists()
    assert w.state("range_fit", 1)["fetch"]["reason_code"] == "no_person_preprocessed"


def test_progress_log_has_counts_only(tmp_path):
    w = World(tmp_path, {"range_fit": _rows("range_fit", 2)})
    w.fetch()
    lines = (w.root / "run.log").read_text().splitlines()
    assert len(lines) == 2
    assert "processed=2/2 passed=2 free=50.0GB elapsed=0:00:" in lines[-1]
    assert not any(s in lines[-1] for s in ("V00_", "http", "s3:", "media", ".mp4"))


def test_verify_preprocessed():
    ok = {"duration": 25.025, "streams": ["video", "audio"], "audio_vs_source_wav_window": {"lag_sec": 0.0,
                                                                                            "peak_ncc": 0.9999}}
    assert er.verify_preprocessed(ok)["status"] == er.OK
    assert er.verify_preprocessed({**ok, "duration": 24.5})["reason_code"] == "pre_duration"
    assert er.verify_preprocessed({**ok, "streams": ["video"]})["reason_code"] == "pre_streams"
    bad = {**ok, "audio_vs_source_wav_window": {"lag_sec": 0.01, "peak_ncc": 1.0}}
    assert er.verify_preprocessed(bad)["reason_code"] == "pre_audio_mismatch"


def test_load_role_refuses_changed_list(tmp_path):
    p = tmp_path / "range_fit_v2.csv"
    p.write_text("role,order,vendor,interaction_key,file_id_a,file_id_b\nrange_fit,0,00,k,a,b\n")
    rows = er.load_role("range_fit", {"range_fit": (p, er.sha256_file(p))})
    assert rows[0]["file_id_a"] == "a"
    with pytest.raises(SystemExit, match="해시"):
        er.load_role("range_fit", {"range_fit": (p, "0" * 64)})


def test_committed_list_hashes_match_fetch_guard_and_plan():
    plan = (er.REPO_ROOT / "docs/superpowers/plans/2026-11-27-evidence-range.md").read_text(encoding="utf-8")
    for role, (path, sha) in er.RANGE_LISTS.items():
        assert path.name == f"{role}_v2.csv"
        assert sha in plan


# ---------- analyze ----------

class Lab:
    """가짜 측정: pass_map[(role, order, who, 조건)]이 참이면 Gate 적합 구간 하나."""

    def __init__(self, pass_map):
        self.pass_map = pass_map
        self.calls = []

    def run_condition(self, src, gate_only, work):
        sdir = src.parent.parent if src.parent.name == "pre" else src.parent.parent.parent
        who = src.name[0]
        cond = "original" if src.parent.name == "pre" else er.RECOMPRESS_PROFILE
        key = (sdir.parent.name, int(sdir.name), who, cond)
        self.calls.append((*key, gate_only))
        segs = [{"start_sec": 1.0, "end_sec": 4.0}] if self.pass_map.get(key) else []
        out = {"gate": {"eligible_segments": segs}}
        if segs and not gate_only:
            out["axes"] = {"waverep": {"status": "completed"}}
        return out

    def recompress(self, src, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{src.stem}__{er.RECOMPRESS_PROFILE}.mp4"
        out.write_bytes(b"emu")
        return {"status": "completed", "profile_id": er.RECOMPRESS_PROFILE}, out


def _fetched(tmp_path, n_fit, n_check):
    w = World(tmp_path, {"range_fit": _rows("range_fit", n_fit), "range_check": _rows("range_check", n_check)})
    assert w.fetch() == "complete"
    return w


def _analyze(w, lab, targets, free=50e9):
    deps = er.AnalyzeDeps(run_condition=lab.run_condition, recompress=lab.recompress, free_bytes=lambda: free)
    return er.run_analyze(w.root, tuple(w.rows), w.rows, deps, w.progress(), int(10e9), targets)


def test_analyze_stop_rule_counts_sessions_with_any_person_passing(tmp_path):
    w = _fetched(tmp_path, 5, 2)
    o = "original"
    lab = Lab({("range_fit", 0, "B", o): True, ("range_fit", 2, "A", o): True, ("range_fit", 2, "B", o): True,
               ("range_fit", 2, "A", er.RECOMPRESS_PROFILE): True, ("range_check", 1, "A", o): True})
    assert _analyze(w, lab, {"range_fit": 2, "range_check": 5}) == "complete"
    # range_fit: 0 통과, 1 미통과, 2 통과(두 사람) → 2세션에서 멈춘다. 3·4는 측정하지 않는다
    assert {c[1] for c in lab.calls if c[0] == "range_fit"} == {0, 1, 2}
    summary = json.loads((w.root / "analyze_summary.json").read_text())
    assert summary["range_fit"] == {"status": "target_reached", "processed": 3, "passed_sessions": 2,
                                    "target": 2, "reserved": 5}
    assert summary["range_check"]["status"] == "reservation_exhausted"
    assert summary["range_check"]["passed_sessions"] == 1
    # 원본 Gate 미통과자는 재압축에서 Gate만 돈다. 원본 통과자는 재압축에서 세 축까지 간다
    assert ("range_fit", 0, "A", er.RECOMPRESS_PROFILE, True) in lab.calls
    assert ("range_fit", 0, "B", er.RECOMPRESS_PROFILE, False) in lab.calls
    st = w.state("range_fit", 2)["analyze"]
    assert st["session_passed"] and st["people"]["A"]["recompressed_gate_passed"]
    assert not st["people"]["B"]["recompressed_gate_passed"]
    # 측정한 세션의 25초본·파생본은 지우고, 측정 안 한 세션의 25초본은 남는다
    assert not (er.session_dir(w.root, "range_fit", 2) / "pre").exists()
    assert not (er.session_dir(w.root, "range_fit", 2) / "work").exists()
    assert (er.session_dir(w.root, "range_fit", 2) / "results/A.original.json").exists()
    assert (er.session_dir(w.root, "range_fit", 3) / "pre/A.mp4").exists()
    # 다시 돌려도 측정을 반복하지 않는다
    n = len(lab.calls)
    assert _analyze(w, lab, {"range_fit": 2, "range_check": 5}) == "complete" and len(lab.calls) == n


def test_analyze_skips_failed_fetch_and_waits_for_unfinished(tmp_path):
    w = World(tmp_path, {"range_fit": _rows("range_fit", 3)})
    w.diag = {("range_fit", 0): "http_403", ("range_fit", 1): "dns_error"}
    w.fetch()
    lab = Lab({})
    assert _analyze(w, lab, {"range_fit": 1}) == "waiting_fetch"
    assert w.state("range_fit", 0)["analyze"]["status"] == er.SKIPPED
    assert "analyze" not in w.state("range_fit", 1)
    assert lab.calls == []   # 순서를 지키려고 2번으로 건너뛰지 않는다


def test_analyze_low_disk_and_interrupted_session(tmp_path):
    w = _fetched(tmp_path, 2, 0)
    w.rows.pop("range_check")
    lab = Lab({})
    assert _analyze(w, lab, {"range_fit": 1}, free=1e9) == "low_disk"
    sdir = er.session_dir(w.root, "range_fit", 0)
    # 측정 중 꺼짐: analyze pending, 작업 폴더가 남았다
    st = w.state("range_fit", 0)
    st["analyze"] = {"status": er.PENDING}
    er.write_json(sdir / "state.json", st)
    (sdir / "work").mkdir()
    (sdir / "work/junk").write_bytes(b"x")
    assert _analyze(w, lab, {"range_fit": 1}) == "complete"
    assert w.state("range_fit", 0)["analyze"]["status"] == er.DONE
    assert not (sdir / "work").exists()


def test_analyze_refuses_changed_input(tmp_path):
    w = _fetched(tmp_path, 1, 0)
    w.rows.pop("range_check")
    (er.session_dir(w.root, "range_fit", 0) / "pre/A.mp4").write_bytes(b"changed")
    lab = Lab({})
    _analyze(w, lab, {"range_fit": 1})
    people = w.state("range_fit", 0)["analyze"]["people"]
    assert people["A"]["status"] == "input_hash_mismatch" and people["B"]["status"] == "measured"


def test_reference_version_is_sealed_once(tmp_path):
    rec = er.seal_reference(tmp_path, "gate-v2", {"x": 1})
    assert er.seal_reference(tmp_path, "gate-v2", {"x": 2}) == rec
    with pytest.raises(SystemExit, match="Gate"):
        er.seal_reference(tmp_path, "gate-v3", {})


def test_analyze_requires_matching_gate_version(monkeypatch):
    monkeypatch.setattr(er, "load_role", lambda role: _rows(role, 1))
    with pytest.raises(SystemExit, match="GATE_VERSION"):
        er.main(["analyze", "--gate-version", "gate-v0"])
