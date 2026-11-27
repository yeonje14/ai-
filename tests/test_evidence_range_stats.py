import numpy as np
import pytest

from scripts import evidence_range_stats as stats

run = stats.run


def sessions(numbers, duplicate=False):
    return [("V00" if i % 2 else "V01",
             {(cond, "syncnet"): {("A", 0, 1): x + j*100,
                                  **({("B", 1, 2): x + j*100} if duplicate else {})}
              for j, cond in enumerate(run.CONDITIONS)})
            for i, x in enumerate(numbers)]


def test_reference_and_bootstrap():
    vendors = ["a", "a", "b"]
    weights = stats.bootstrap_weights(vendors)
    assert stats.SEED == 20261127 and weights.shape == (2000, 3)
    assert np.array_equal(weights, stats.bootstrap_weights(vendors))
    assert np.all(weights[:, :2].sum(axis=1) == 2) and np.all(weights[:, 2] == 1)
    assert weights[:, 0].max() == 2
    ref = stats.Reference([1, 1, 2], weights)
    assert ref.compare(1)["percentile"] == pytest.approx(100/3)
    assert ref.threshold is None
    assert stats.BOUNDARY == 97.5
    assert stats.classify(11, 10, 97.5, 100) == "rare"
    assert stats.classify(10, 10, 98, 100) == "abstained"
    assert stats.classify(9.999, 10, 97.5, 100) == "abstained"
    assert stats.classify(9.999, 10, 97, 97.5) == "abstained"
    assert stats.classify(11, 10, 96, 99) == "abstained"
    assert stats.classify(9, 10, 94, 97.49) == "within_range"


def test_rates_and_conditions():
    fit = sessions(range(50))
    check = sessions([90]*2 + [10]*28) + [("V00", {})]
    report = stats.compute(fit, check)
    assert stats.compute(sessions(range(50), True), check) == report
    for j, cond in enumerate(run.CONDITIONS):
        result = report[cond]
        row = result["signals"]["syncnet"]
        assert row["upper_reference_value"] == 49 + 100*j
        assert row["status"] == "release_blocked"
        assert row["missing_check"] == 1
        assert result["signals"]["waverep"]["status"] == "not_published"
        for k in ("any_rare_session_rate", "mean_session_segment_rate"):
            r = result[k]
            assert (r["numerator"], r["denominator"], r["missing"]) == (2, 30, 1)
            assert r["wilson95"] == pytest.approx([0.018477, 0.213235], abs=1e-5)


@pytest.mark.parametrize("n,m", [(49, 30), (50, 29), (1, 30)])
def test_minimum(n, m):
    row = stats.compute(sessions(range(n)), sessions(range(m)))["original"]["signals"]["syncnet"]
    assert row["status"] == "not_published"


def test_paired_display_and_session_weight():
    check = sessions([0]*40)
    for condition in run.CONDITIONS:
        check[0][1][condition, "syncnet"][("B", 0, 1)] = 200
    check[1][1]["original", "syncnet"][("A", 0, 1)] = 200
    result = stats.compute(sessions(range(50)), check)["original"]
    assert result["mean_session_segment_rate"]["numerator"] == 0.5
    assert result["any_rare_session_rate"]["numerator"] == 1
    assert result["signals"]["syncnet"]["comparisons"][2]["display_status"] == "abstained"


def test_files_and_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "TARGETS", dict(range_fit=1, range_check=1))
    rows = {role: [dict(order=i, vendor="V00") for i in range(2)] for role in run.ROLES}
    run.write_json(tmp_path / "reference_version.json", dict(gate_version="synthetic",
                   targets=run.TARGETS, reservation_sha256={k: v[1] for k, v in run.RANGE_LISTS.items()}))
    for role in run.ROLES:
        for i in range(2):
            directory = run.session_dir(tmp_path, role, i)
            run.write_json(directory / "state.json", dict(analyze=dict(status="done", session_passed=True,
                           people={"A": {"status": "measured"}})))
            segment = dict(start_sec=1, end_sec=2)
            result = dict(gate=dict(eligible_segments=[segment]), axis_raw=dict(
                syncnet=dict(offset_fps=25, segments=[dict(**segment, status="completed",
                             tracks=[dict(offset_frames=-3), dict(offset_frames=1)])]),
                waverep=dict(frames=[dict(index=30, logit=5)], sampling=dict(sample_fps=1))))
            run.write_json(directory / "results/A.original.json", result)
    report = stats.generate(tmp_path, rows)
    assert report["conditions"]["original"]["signals"]["syncnet"]["session_maxima"] == [0.08]
    assert report["conditions"][run.RECOMPRESS_PROFILE]["signals"]["syncnet"]["missing_fit"] == 1
    assert report["stopping"]["range_fit"]["excluded_after_stop_orders"] == [1]
    assert report["waverep_mapping"] == "대응 미검증(보류)"
    assert run.read_json(tmp_path / "stats/stats.json")["reference_version"]["seed"] == 20261127
    assert "경고" in (tmp_path / "stats/summary.md").read_text()


def test_union_across_signals_and_exact_five_percent():
    fit = sessions(range(50))
    check = sessions([90] + [0]*39)
    for _, values in fit + check:
        for condition in run.CONDITIONS:
            values[condition, "waverep"] = dict(values[condition, "syncnet"])
    for condition in run.CONDITIONS:
        check[1][1][condition, "waverep"][("A", 0, 1)] = 300
    result = stats.compute(fit, check)["original"]
    assert result["any_rare_session_rate"]["estimate"] == 0.05
    assert result["signals"]["syncnet"]["status"] == "published"
    assert result["signals"]["waverep"]["status"] == "published"


def test_corrupt_prefix_excludes_results_beyond_gap(tmp_path):
    rows = [dict(order=i, vendor="V01") for i in range(3)]
    for i in (0, 2):
        directory = run.session_dir(tmp_path, "range_fit", i)
        run.write_json(directory / "state.json", {"analyze": {"status": run.SKIPPED}})
    samples, stop = stats.read_sessions(tmp_path, "range_fit", rows)
    assert len(samples) == 1 and stop["passed"] == 0
    assert stop["excluded_after_stop_orders"] == [2]


def test_order_statistic_and_missing_fit():
    fit = sessions(range(100)) + [("V00", {})]
    report = stats.compute(fit, sessions(range(30)))["original"]["signals"]["syncnet"]
    assert report["n_fit"] == 100 and report["missing_fit"] == 1
    assert report["upper_reference_value"] == 98
    assert stats.classify(98.01, 98, 97.49, 97.499) == "within_range"

def test_wave_frame_times_and_legacy():
    gate = {"eligible_segments": [{"start_sec": 1, "end_sec": 2}, {"start_sec": 2, "end_sec": 3}]}
    wave = dict(status="completed", frames=[dict(index=i, clip_pts_sec=t, logit=x)
                for i, t, x in [(30, 1, -4), (53, 1.8, 2), (60, 2, 8), (90, 3, 99)]])
    result = {"gate": gate, "axis_raw": {"waverep": wave}}
    assert stats.measurements(result)["waverep"] == {(1, 2): -1, (2, 3): 8}
    del wave["frames"][0]["clip_pts_sec"]
    assert stats.measurements(result)["waverep"] == {}


def test_wave_summary_uses_decoded_index_and_clip_origin(monkeypatch, tmp_path):
    from scripts import seamless_first_pair as pair

    raw = dict(status="completed", video={"frame_count": 4},
               frames=[dict(index=2, time_sec=0.2, logit=-1.25)])
    monkeypatch.setattr(pair, "_frame_pts", lambda src, n: [3, 3.09, 3.21, 3.29])
    summary = pair._summ_waverep(raw, tmp_path / "synthetic")
    assert summary["first_frame_pts_sec"] == 3
    assert summary["frames"] == [dict(index=2, clip_pts_sec=0.21, logit=-1.25)]
    monkeypatch.setattr(pair, "_frame_pts", lambda src, n: [])
    assert "clip_pts_sec" not in pair._summ_waverep(raw, tmp_path / "synthetic")["frames"][0]
