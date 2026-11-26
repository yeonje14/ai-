"""v2 예약은 미디어와 신호값을 읽지 않고 기관마다 격리한 쌍을 나눈다."""
from collections import Counter
from hashlib import sha256

from scripts import seamless_reserve as sr
from tests.test_seamless_reservation import _pair, _world


def test_balances_each_vendor_after_deduplicating_all_pairs():
    from scripts.evidence_range_reserve_v2 import select

    rows = _world(16, 8)
    prior = sr.reserve(rows, roles=())
    assigned = prior["assignment"]
    selected = select(rows, [], assigned)
    assert Counter((r["vendor"], r["role"]) for r in selected) == {
        ("00", "range_fit"): 10, ("00", "range_check"): 6,
        ("01", "range_fit"): 5, ("01", "range_check"): 3,
    }
    assert selected == select(rows[::-1], [], assigned[::-1])
    for role in ("range_fit", "range_check"):
        orders = [r["order"] for r in selected if r["role"] == role]
        assert orders == list(range(len(orders)))
    assert len({r["interaction_key"].split("_I")[0] for r in selected}) == 24


def test_both_sides_original_lineage_and_official_holdouts_stay_isolated():
    from scripts.evidence_range_reserve import identities
    from scripts.evidence_range_reserve_v2 import select

    rows = _world(14, 2)
    prior = sr.reserve(rows, roles=(("test", 1), ("dev", 1), ("pilot", 1)))
    # 공식 test의 다른 라벨 영상은 세션만 같아도 빼야 한다. P코드의 앞자리 0도 같은 인물이다.
    holdout = _pair(0, 5, 998, 1001, 1002, split="test", label="improvised")
    holdout += _pair(2, 987, 989, 1, 1010, split="dev", label="improvised")
    selected = select(rows + holdout, prior["reservation"], prior["assignment"])
    assert selected
    excluded = set().union(*(identities(r["file_id"]) for r in holdout))
    for row in prior["reservation"]:
        excluded |= identities(row["file_id_a"]) | identities(row["file_id_b"])
    for row in selected:
        keys = identities(row["file_id_a"]) | identities(row["file_id_b"])
        assert not keys & excluded
        excluded.update(keys)
        a, b = sr.target_a(20261127, row["interaction_key"], [row["file_id_a"], row["file_id_b"]])
        assert (a, b) == (row["file_id_a"], row["file_id_b"])


def test_role_pattern_is_five_to_three_and_fit_first():
    from scripts.evidence_range_reserve_v2 import role_at

    pattern = [role_at(k)[6] for k in range(16)]  # range_f / range_c
    assert "".join(pattern) == "ffcffcfc" * 2
    for n in range(1, 40):
        fit = sum(role_at(k) == "range_fit" for k in range(n))
        assert fit == -(-5 * n // 8)
