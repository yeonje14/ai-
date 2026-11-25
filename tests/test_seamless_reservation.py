"""scripts/seamless_reserve.py: 제외 규칙, 역할 간 비중복, 층화 배분, 부족분 보고, 재현성.

합성한 filelist 행만 쓴다. 실제 데이터셋이나 영상은 필요 없다.
"""

from __future__ import annotations

import hashlib

import pytest

from scripts import seamless_reserve as sr


def _row(file_id, split="train", label="naturalistic"):
    return {"file_id": file_id, "label": label, "split": split, "batch_idx": "0", "archive_idx": "0",
            "has_imitator_movement": "0", "has_annotation_1p": "0", "has_annotation_3p": "0"}


def _pair(vendor, session, inter, pa, pb, split="train", label="naturalistic", sa="", sb=""):
    base = f"V{vendor:02d}_S{session:04d}_I{inter:08d}"
    return [_row(f"{base}_P{pa:04d}{sa}", split, label), _row(f"{base}_P{pb:04d}{sb}", split, label)]


def _world(n_v0=40, n_v1=20):
    """기관마다 참가자 짝이 겹치지 않는 대화를 만든다. 세션 하나에 대화 둘씩."""
    rows, p = [], 1
    for vendor, n in ((0, n_v0), (1, n_v1)):
        for k in range(n):
            rows += _pair(vendor, 1000 * vendor + k, 2 * k, p, p + 1)
            rows += _pair(vendor, 1000 * vendor + k, 2 * k + 1, p, p + 1)
            p += 2
    return rows


ROLES = (("test", 6), ("dev", 3), ("pilot", 2))


def test_parse_file_id_strips_vendor_and_zero_padding():
    p = sr.parse_file_id("V03_S0809_I00000582_P0947A")
    assert (p.vendor, p.session, p.interaction, p.pcode, p.suffix) == ("03", "0809", "00000582", "947", "A")
    assert sr.parse_file_id("V03_S0809_I00000582") is None
    assert sr.parse_file_id("V03_S0809_I00000582_P0947_x") is None


def test_allocate_largest_remainder_ties_by_vendor():
    assert sr.allocate(10, {"00": 1, "01": 1, "02": 1}) == {"00": 4, "01": 3, "02": 3}
    assert sr.allocate(200, {"00": 3, "01": 1}) == {"00": 150, "01": 50}
    assert sum(sr.allocate(7, {"00": 5, "01": 3, "02": 2}).values()) == 7


def test_reserved_roles_share_no_participant_or_session():
    out = sr.reserve(_world(), seed=1, roles=ROLES)
    res = out["reservation"]
    assert [sum(r["role"] == role for r in res) for role, _ in ROLES] == [6, 3, 2]
    pcodes, sessions = [], []
    for r in res:
        for fid in (r["file_id_a"], r["file_id_b"]):
            pcodes.append(sr.parse_file_id(fid).pcode)
        sessions.append(r["interaction_key"].rsplit("_I", 1)[0])
    assert len(pcodes) == len(set(pcodes))
    assert len(sessions) == len(set(sessions))
    # 예약된 대화와 세션을 공유하는 다른 대화는 학습 후보가 아니라 격리된다
    asg = {a["interaction_key"]: a for a in out["assignment"]}
    for r in res:
        sess = r["interaction_key"].rsplit("_I", 1)[0]
        siblings = [k for k in asg if k.startswith(sess + "_I") and k != r["interaction_key"]]
        assert siblings and all(asg[k]["role"] == "quarantined_linked" for k in siblings)


def test_stratified_by_vendor_share():
    out = sr.reserve(_world(n_v0=40, n_v1=20), seed=1, roles=(("test", 9),))
    s = out["summary"]["roles"]["test"]
    assert s["quota_by_vendor"] == {"00": 6, "01": 3}
    assert s["reserved_by_vendor"] == {"00": 6, "01": 3}
    assert s["shortfall_by_vendor"] == {}


def test_shortfall_is_reported_not_redistributed():
    # 기관 01에는 독립 참가자 짝이 2개뿐이다. 대화 수는 많지만 같은 두 사람이다.
    rows = _world(n_v0=30, n_v1=0)
    for k in range(60):
        rows += _pair(1, 5000 + k, k, 900 + (k % 2) * 2, 901 + (k % 2) * 2)
    out = sr.reserve(rows, seed=3, roles=(("test", 10),))
    s = out["summary"]["roles"]["test"]
    assert s["quota_by_vendor"]["01"] == 5
    assert s["reserved_by_vendor"]["01"] == 2
    assert s["shortfall_by_vendor"] == {"01": 3}
    assert s["reserved_by_vendor"]["00"] == s["quota_by_vendor"]["00"] == 5
    assert s["reserved"] == 7


def test_exclusions_official_overlap_suffix_and_multi_vendor():
    rows = _world(n_v0=10, n_v1=0)
    rows += _pair(0, 7000, 1, 501, 502)                       # 501이 공식 test에도 나온다
    rows += _pair(0, 7100, 1, 503, 504, split="test", label="improvised")[:1]
    rows[-1] = _row("V00_S7100_I00000001_P0501", "test", "improvised")
    rows += _pair(0, 7200, 1, 601, 602, sa="A")               # 접미사 ID
    rows += _pair(0, 7300, 1, 701, 702)                       # 701이 다른 기관에도 나온다
    rows += [_row("V02_S7400_I00000001_P0701", "train", "improvised")]
    rows += _pair(0, 7500, 1, 801, 802, split="dev")          # 공식 dev 대화
    out = sr.reserve(rows, seed=5, roles=(("test", 40),))
    asg = {a["interaction_key"]: a for a in out["assignment"]}
    assert asg["V00_S7000_I00000001"]["reason"] == sr.R_OFFICIAL_OVERLAP
    assert asg["V00_S7200_I00000001"]["reason"] == sr.R_SUFFIX
    assert asg["V00_S7300_I00000001"]["reason"] == sr.R_MULTI_VENDOR
    assert asg["V00_S7500_I00000001"]["role"] == "official_dev"
    reserved = {r["interaction_key"] for r in out["reservation"]}
    assert not reserved & {"V00_S7000_I00000001", "V00_S7200_I00000001", "V00_S7300_I00000001",
                           "V00_S7500_I00000001"}
    c = out["summary"]["exclusion_reason_counts"]
    assert c[sr.R_OFFICIAL_OVERLAP] == 1 and c[sr.R_SUFFIX] == 1 and c[sr.R_MULTI_VENDOR] == 1


def test_official_dev_test_never_reserved_and_zero_padding_links_identity():
    rows = _world(n_v0=10, n_v1=0)
    # 같은 숫자 코드를 다른 자릿수로 쓴 공식 test 행도 같은 사람으로 본다
    rows += [_row("V00_S8000_I00000001_P00001", "test"), _row("V00_S8000_I00000001_P0999", "test")]
    out = sr.reserve(rows, seed=7, roles=(("test", 10),))
    for r in out["reservation"]:
        assert "S8000" not in r["interaction_key"]
        assert "1" not in {sr.parse_file_id(r["file_id_a"]).pcode, sr.parse_file_id(r["file_id_b"]).pcode}


def test_same_participant_twice_and_file_count():
    rows = _world(n_v0=5, n_v1=0)
    rows += _pair(0, 9000, 1, 950, 950)
    rows += [_row("V00_S9100_I00000001_P0960")]
    out = sr.reserve(rows, seed=1, roles=(("test", 2),))
    asg = {a["interaction_key"]: a for a in out["assignment"]}
    assert sr.R_SAME_PARTICIPANT in asg["V00_S9000_I00000001"]["reason"]
    assert asg["V00_S9100_I00000001"]["reason"] == sr.R_FILE_COUNT


def test_deterministic_bytes_and_seed_sensitivity():
    rows = _world()
    a = sr.reserve(rows, seed=11, roles=ROLES)
    b = sr.reserve(list(reversed(rows)), seed=11, roles=ROLES)
    ab = sr.csv_bytes(sr.sorted_reservation(a["reservation"]), sr.RESERVATION_COLUMNS)
    bb = sr.csv_bytes(sr.sorted_reservation(b["reservation"]), sr.RESERVATION_COLUMNS)
    assert ab == bb
    assert sr.csv_bytes(a["assignment"], sr.ASSIGNMENT_COLUMNS) == sr.csv_bytes(b["assignment"],
                                                                                 sr.ASSIGNMENT_COLUMNS)
    c = sr.reserve(rows, seed=12, roles=ROLES)
    cb = sr.csv_bytes(sr.sorted_reservation(c["reservation"]), sr.RESERVATION_COLUMNS)
    assert cb != ab


def test_target_a_is_one_of_pair_and_order_starts_at_zero():
    out = sr.reserve(_world(), seed=1, roles=ROLES)
    pilots = [r for r in out["reservation"] if r["role"] == "pilot"]
    assert [r["order"] for r in pilots] == [0, 1]
    for r in out["reservation"]:
        assert r["file_id_a"] != r["file_id_b"]
        assert r["interaction_key"] in r["file_id_a"] and r["interaction_key"] in r["file_id_b"]
    picks = {sr.target_a(1, f"K{i}", ["x", "y"])[0] for i in range(40)}
    assert picks == {"x", "y"}


def test_main_refuses_other_filelist(tmp_path):
    f = tmp_path / "filelist.csv"
    f.write_text("file_id,label,split,batch_idx,archive_idx,has_imitator_movement,has_annotation_1p,"
                 "has_annotation_3p\n")
    assert sr.main(["--filelist", str(f), "--out", str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()


def test_git_blob_sha1_matches_git():
    # `printf 'hello\n' | git hash-object --stdin`
    assert sr.git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert hashlib.sha256(b"").hexdigest().startswith("e3b0")


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_train_candidates_never_touch_reserved_people(seed):
    out = sr.reserve(_world(), seed=seed, roles=ROLES)
    reserved = set()
    for r in out["reservation"]:
        reserved |= {sr.parse_file_id(r["file_id_a"]).pcode, sr.parse_file_id(r["file_id_b"]).pcode}
    for a in out["assignment"]:
        if a["role"] == "train_candidate":
            assert not {sr.parse_file_id(f).pcode for f in a["file_ids"].split()} & reserved


def test_excluded_interaction_linked_to_reserved_is_quarantined():
    rows = _world(n_v0=3, n_v1=0)
    # 참가자 1·2(기관 00 첫 짝)와 같은 코드를 접미사로 쓴 대화, 같은 사람의 improvised 행
    rows += _pair(0, 9900, 1, 1, 2, sa="A")
    rows += [_row("V00_S9901_I00000001_P0001", "train", "improvised")]
    out = sr.reserve(rows, seed=1, roles=(("test", 3),))
    asg = {a["interaction_key"]: a for a in out["assignment"]}
    assert asg["V00_S9900_I00000001"]["role"] == "quarantined_linked"
    assert asg["V00_S9900_I00000001"]["reason"] == sr.R_SUFFIX
    assert out["summary"]["other_label_rows_with_reserved_participants"] == {"train": 1}
