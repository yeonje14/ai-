"""research/seamless/fetch_pilot.py의 보호 장치: 예약 해시, 역할, 공식 label·split, 실패 분류.

네트워크와 공식 패키지 없이 돈다(공식 패키지는 main 안에서만 import한다).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fetch_pilot", ROOT / "research/seamless/fetch_pilot.py")
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)

HEADER = "file_id,label,split,batch_idx,archive_idx,has_imitator_movement,has_annotation_1p,has_annotation_3p\n"


def _write(tmp_path, res_rows, index_rows):
    res = tmp_path / "reservation.csv"
    res.write_text("role,order,vendor,interaction_key,file_id_a,file_id_b\n"
                   + "".join(",".join(map(str, r)) + "\n" for r in res_rows))
    fl = tmp_path / "filelist.csv"
    fl.write_text(HEADER + "".join(",".join(r) + ",0,0,0\n" for r in index_rows))
    blob = fp.git_blob_sha1(fl.read_bytes())
    return res, fl, fp.sha256_file(res), blob


K = "V00_S0001_I00000001"
A, B = f"{K}_P0001", f"{K}_P0002"
T = "V00_S0002_I00000001"


def test_selects_pilot_row(tmp_path):
    res, fl, rs, blob = _write(tmp_path, [("test", 0, "00", T, f"{T}_P0003", f"{T}_P0004"),
                                          ("pilot", 0, "00", K, B, A)],
                               [(A, "naturalistic", "train", "0", "1"), (B, "naturalistic", "train", "0", "1")])
    pick = fp.select_pilot(res, fl, 0, rs, blob)
    assert (pick["file_id_a"], pick["file_id_b"]) == (B, A)
    assert pick["index"][A]["batch_idx"] == "0"


def test_refuses_changed_reservation(tmp_path):
    res, fl, rs, blob = _write(tmp_path, [("pilot", 0, "00", K, A, B)],
                               [(A, "naturalistic", "train", "0", "1"), (B, "naturalistic", "train", "0", "1")])
    with pytest.raises(fp.GuardError, match="sha256"):
        fp.select_pilot(res, fl, 0, "0" * 64, blob)
    with pytest.raises(fp.GuardError, match="blob"):
        fp.select_pilot(res, fl, 0, rs, "0" * 40)


def test_refuses_non_pilot_order(tmp_path):
    # 파일럿 1번이 없고 test 행만 있다: test는 받을 수 없다
    res, fl, rs, blob = _write(tmp_path, [("test", 1, "00", T, f"{T}_P0003", f"{T}_P0004"),
                                          ("pilot", 0, "00", K, A, B)],
                               [(A, "naturalistic", "train", "0", "1"), (B, "naturalistic", "train", "0", "1")])
    with pytest.raises(fp.GuardError, match="pilot order 1"):
        fp.select_pilot(res, fl, 1, rs, blob)


@pytest.mark.parametrize("label,split", [("naturalistic", "test"), ("naturalistic", "dev"), ("improvised", "train")])
def test_refuses_non_train_naturalistic(tmp_path, label, split):
    res, fl, rs, blob = _write(tmp_path, [("pilot", 0, "00", K, A, B)],
                               [(A, "naturalistic", "train", "0", "1"), (B, label, split, "0", "1")])
    with pytest.raises(fp.GuardError, match="naturalistic/train"):
        fp.select_pilot(res, fl, 0, rs, blob)


def test_classify_url(monkeypatch):
    def boom(exc):
        def _open(*a, **k):
            raise exc
        return _open
    monkeypatch.setattr(fp.urllib.request, "urlopen",
                        boom(urllib.error.URLError(socket.gaierror(8, "nodename nor servname"))))
    assert fp.classify_url("https://x/y")["kind"] == "dns_error"
    monkeypatch.setattr(fp.urllib.request, "urlopen",
                        boom(urllib.error.HTTPError("https://x/y", 403, "Forbidden", {}, None)))
    assert fp.classify_url("https://x/y") == {"kind": "http_403", "status": 403}
    monkeypatch.setattr(fp.urllib.request, "urlopen", boom(urllib.error.URLError(ConnectionRefusedError())))
    assert fp.classify_url("https://x/y")["kind"] == "network_error"


def test_check_downloaded_requires_mp4_wav_vad(tmp_path):
    fid = A
    (tmp_path / f"{fid}.mp4").write_bytes(b"x")
    (tmp_path / f"{fid}.json").write_text(json.dumps({"id": fid}))
    c = fp.check_downloaded(tmp_path, fid)
    assert c["missing_required"] == ["wav", "metadata:vad"]
    (tmp_path / f"{fid}.wav").write_bytes(b"x")
    (tmp_path / f"{fid}.json").write_text(json.dumps({"id": fid, "metadata:vad": []}))
    assert fp.check_downloaded(tmp_path, fid)["missing_required"] == []


def test_expected_hash_matches_committed_doc():
    doc = (ROOT / "docs/seamless-reservation.md").read_text(encoding="utf-8")
    assert fp.EXPECTED_RESERVATION_SHA256 in doc
    assert fp.EXPECTED_FILELIST_BLOB in doc
    assert hashlib.sha256(b"").hexdigest() != fp.EXPECTED_RESERVATION_SHA256


def test_range_role_selects_only_its_role(tmp_path):
    res, fl, rs, blob = _write(tmp_path, [("range_fit", 0, "00", K, A, B)],
                               [(A, "naturalistic", "train", "0", "1"), (B, "naturalistic", "train", "0", "1")])
    assert fp.select_pilot(res, fl, 0, rs, blob, role="range_fit")["file_id_b"] == B
    with pytest.raises(fp.GuardError, match="range_check order 0"):
        fp.select_pilot(res, fl, 0, rs, blob, role="range_check")
    with pytest.raises(fp.GuardError, match="pilot order 0"):
        fp.select_pilot(res, fl, 0, rs, blob)


def test_range_ids_must_not_touch_existing_reservation(tmp_path):
    prior = tmp_path / "reservation.csv"
    prior.write_text("role,order,vendor,interaction_key,file_id_a,file_id_b\n"
                     f"test,0,00,{T},{T}_P0003,{T}_P0004\n")
    fp.check_not_reserved([A, B], prior)
    with pytest.raises(fp.GuardError, match="겹치는"):
        fp.check_not_reserved([A, "V00_S0009_I00000001_P03"], prior)     # 앞자리 0만 다른 같은 사람
    with pytest.raises(fp.GuardError, match="겹치는"):
        fp.check_not_reserved([f"{T[:9]}_I00000009_P0100"], prior)         # 같은 세션


def test_range_list_hashes_match_plan():
    plan = (ROOT / "docs/superpowers/plans/2026-11-27-evidence-range.md").read_text(encoding="utf-8")
    for role, (path, sha) in fp.RANGE_LISTS.items():
        assert sha in plan and path.name == f"{role}_v2.csv"
