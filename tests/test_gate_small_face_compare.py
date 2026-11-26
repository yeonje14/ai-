"""scripts/gate_small_face_compare.py의 순수 함수 테스트(미디어·모델 불필요)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import gate_small_face_compare as cmp
from server.gate import mouth
from server.gate.types import Face, FrameFaces, MouthSample, Segment


def face(h, x=0.0, y=0.0):
    return Face(x=x, y=y, w=h, h=h, score=0.9, sharpness=50.0)


def test_crop_square_centers_box():
    assert cmp.crop_square((100.0, 100.0, 50.0, 80.0), 3.0, 1080, 1920) == (5, 20, 245, 260)


def test_crop_square_clips_at_frame_edge():
    assert cmp.crop_square((0.0, 0.0, 50.0, 80.0), 3.0, 1080, 1920) == (0, 0, 145, 160)


def test_crop_square_falls_back_to_full_frame_when_box_outside():
    assert cmp.crop_square((2000.0, 100.0, 50.0, 50.0), 3.0, 1080, 1920) == (0, 0, 1080, 1920)


def test_nearest_box_picks_largest_face():
    frames = [FrameFaces(0.0, (face(100), face(200, x=500))), FrameFaces(0.2, ())]
    assert cmp.nearest_box(frames, 0.067, 0.1) == (500.0, 0.0, 200.0, 200.0)
    assert cmp.nearest_box(frames, 0.2, 0.1) is None          # 가장 가까운 표본에 얼굴 없음
    assert cmp.nearest_box([frames[0]], 0.35, 0.1) is None    # 시각 차 상한 밖


def _landmarks(points: dict[int, tuple[float, float]]):
    lm = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    for i, (x, y) in points.items():
        lm[i] = SimpleNamespace(x=x, y=y)
    return lm


def test_sample_from_crop_maps_back_to_frame():
    # 같은 픽셀 위치: 눈 꼬리 (300,400)·(380,400), 입술 (340,450)·(340,462), 나머지 (340,430)
    px = {33: (300, 400), 263: (380, 400), 13: (340, 450), 14: (340, 462)}
    rest = (340, 430)
    full = _landmarks({i: (x / 1080, y / 1920) for i, (x, y) in px.items()})
    for p in full:
        if (p.x, p.y) == (0.5, 0.5):
            p.x, p.y = rest[0] / 1080, rest[1] / 1920
    x0, y0, cw, ch = 200, 300, 300, 300
    crop = _landmarks({i: ((x - x0) / cw, (y - y0) / ch) for i, (x, y) in px.items()})
    for p in crop:
        if (p.x, p.y) == (0.5, 0.5):
            p.x, p.y = (rest[0] - x0) / cw, (rest[1] - y0) / ch
    want = mouth._sample(1.0, [full], 1080, 1920)
    got = cmp.sample_from_crop(1.0, [crop], x0, y0, cw, ch)
    assert got.opening == pytest.approx(want.opening) == pytest.approx(12 / 80)
    assert got.box == pytest.approx(want.box)
    assert cmp.sample_from_crop(1.0, [], x0, y0, cw, ch) == MouthSample(1.0, None, None)


def samples(measured: int, total: int, start=0.0, step=0.1):
    return [MouthSample(round(start + i * step, 3), 0.05 if i < measured else None, None) for i in range(total)]


def test_measured_fraction():
    s = samples(1, 4)
    assert cmp.measured_fraction(s, 0.0, 0.3) == 0.25
    assert cmp.measured_fraction(s, 5.0, 6.0) is None


def test_overlap_and_outside_sec():
    assert cmp.overlap_sec([(0.0, 10.0)], [(5.0, 12.0)]) == 5.0
    assert cmp.outside_sec([(0.0, 10.0), (20.0, 21.0)], [(5.0, 12.0)]) == 6.0


def test_relabel_unmeasurable_threshold():
    s = samples(2, 10) + samples(5, 10, start=2.0) + samples(10, 10, start=4.0)
    excluded = [
        Segment(0.0, 0.9, "no_mouth_movement"),      # 2/10 → 측정 불가
        Segment(2.0, 2.9, "no_mouth_movement"),      # 정확히 0.5 → 그대로
        Segment(3.0, 3.05, "no_mouth_movement"),     # 표본 없음 → 그대로
        Segment(4.0, 4.9, "no_face_detected"),       # 다른 원인은 건드리지 않는다
    ]
    out = cmp.relabel_unmeasurable(excluded, s, 0.5)
    assert [x.reason_code for x in out] == ["mouth_unmeasurable", "no_mouth_movement",
                                            "no_mouth_movement", "no_face_detected"]
    assert [(x.start_sec, x.end_sec) for x in out] == [(x.start_sec, x.end_sec) for x in excluded]


def test_opening_delta():
    a = [MouthSample(0.0, 0.10, None), MouthSample(0.1, 0.20, None), MouthSample(0.2, None, None)]
    b = [MouthSample(0.0, 0.11, None), MouthSample(0.1, 0.23, None), MouthSample(0.2, 0.5, None)]
    d = cmp.opening_delta(a, b)
    assert d["n"] == 2 and d["median"] == pytest.approx(0.02) and d["max"] == pytest.approx(0.03)
    assert cmp.opening_delta(a[2:], b[2:]) == {"n": 0, "median": None, "max": None}


def run_entry(rate, eligible, reason=None, reason_c=None, total=10.0, intervals=()):
    return {"mouth": {"rate": rate}, "gate": {"eligible_sec": eligible, "reason_code": reason,
                                               "eligible_intervals": [list(x) for x in intervals]},
            "relabel": {"reason_code": reason_c if reason_c is not None else reason},
            "times": {"total_sec": [total]}}


def video(set_, v0, va, delta=0.0):
    return {"set": set_, "exists": True, "variants": {"V0": v0, "Va": va},
            "delta": {"n": 5, "median": delta, "max": delta}}


def test_evaluate_flags_regression():
    vids = {
        "S0-B": video("dev", run_entry(0.13, 0.0, "no_mouth_movement", "mouth_unmeasurable"),
                      run_entry(0.95, 10.0)),
        "S1-A": video("confirm", run_entry(0.97, 10.0), run_entry(0.90, 10.0)),          # 7%p 하락
        "self-C": video("regression", run_entry(0.99, 0.0, "no_mouth_movement"),
                        run_entry(0.99, 0.0, "no_mouth_movement")),
        "self-A": video("regression", run_entry(0.95, 20.0), run_entry(0.95, 22.0, total=13.0)),
    }
    rows = {(r["video"], r["criterion"]): r["pass"] for r in cmp.evaluate(vids)}
    assert rows[("S0-B", "dev_B_rate_ge_0.8")] is True
    assert rows[("S0-B", "c_dev_B_reason_is_mouth_unmeasurable")] is True
    assert rows[("S1-A", "rate_drop_le_2pp")] is False
    assert rows[("self-C", "regression_CD_still_rejected")] is True
    assert rows[("self-A", "regression_eligible_change_le_5pct")] is False   # +10%
    assert rows[("self-A", "time_increase_le_20pct")] is False               # +30%


def test_report_marks_missing_video():
    text = cmp.render_report({"meta": {}, "videos": {"S2-A": {"set": "confirm", "exists": False, "variants": {}}}})
    assert "S2-A" in text and "없음" in text
