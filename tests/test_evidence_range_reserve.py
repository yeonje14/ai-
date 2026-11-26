from scripts import seamless_reserve as sr
from scripts.evidence_range_reserve import select
from tests.test_seamless_reservation import _world, _pair


def test_disjoint_ordered_reservation_and_shortfall():
    rows = _world(8, 4) + _pair(0, 200, 1, 1, 500, split="test", label="improvised")
    prior = sr.reserve(rows, roles=(("pilot", 2),))
    args = (prior["reservation"], prior["assignment"])
    roles = (("range_fit", 3), ("range_check", 99))
    selected = select(rows, *args, roles)
    assert selected == select(list(reversed(rows)), *args, roles)
    assert len([r for r in selected if r["role"] == "range_fit"]) == 3
    assert 0 < len(selected) < 102
    people = [sr.parse_file_id(r[k]).pcode for r in selected for k in ("file_id_a", "file_id_b")]
    assert len(set(people)) == len(people) and "1" not in people
    assert not set(people).intersection(sr.parse_file_id(r[k]).pcode for r in prior["reservation"]
                                       for k in ("file_id_a", "file_id_b"))
