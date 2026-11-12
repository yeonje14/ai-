"""research/waverep/run_spike.py: 명령 구성, time -l 파싱, logit 요약."""

import pytest

from research.waverep import run_spike

TIME_L = """result line
       12.34 real        40.00 user         3.00 sys
          2147483648  maximum resident set size
                   0  average shared memory size
               12345  page reclaims
          3221225472  peak memory footprint
"""


def test_command_is_argument_list_with_absolute_inputs(tmp_path):
    cmd = run_spike.build_command(
        "/venv/python", tmp_path / "a b.mp4", tmp_path / "o.csv", tmp_path / "w.ckpt", "cpu", 8
    )
    assert cmd[:4] == ["/usr/bin/time", "-l", "/venv/python", "main_avideo.py"]
    assert cmd[cmd.index("--video_input") + 1] == str(tmp_path / "a b.mp4")
    assert cmd[cmd.index("--device") + 1] == "cpu"
    assert cmd[-2:] == ["--limit", "8"]


def test_command_omits_limit_when_none(tmp_path):
    cmd = run_spike.build_command("py", tmp_path / "v", tmp_path / "o", tmp_path / "w", "mps", None)
    assert "--limit" not in cmd


@pytest.mark.parametrize("device", ["cuda", "cuda:0", "cpu; rm -rf /"])
def test_cuda_and_unknown_devices_are_rejected(tmp_path, device):
    with pytest.raises(ValueError):
        run_spike.build_command("py", tmp_path / "v", tmp_path / "o", tmp_path / "w", device, None)


def test_parse_time_l_reads_bytes():
    assert run_spike.parse_time_l(TIME_L) == {
        "max_rss_bytes": 2147483648,
        "peak_footprint_bytes": 3221225472,
    }


def test_parse_time_l_missing_values_are_none_not_zero():
    assert run_spike.parse_time_l("Traceback ...") == {
        "max_rss_bytes": None,
        "peak_footprint_bytes": None,
    }


def test_summarize_logits():
    s = run_spike.summarize_logits([-2.0, 0.0, 2.0, 4.0])
    assert (s["frames"], s["mean"], s["median"], s["min"], s["max"]) == (4, 1.0, 1.0, -2.0, 4.0)


def test_summarize_empty_is_none_not_zero():
    s = run_spike.summarize_logits([])
    assert s["frames"] == 0
    assert s["mean"] is None and s["min"] is None and s["max"] is None


def test_read_logits_from_demo_csv(tmp_path):
    f = tmp_path / "o.csv"
    f.write_text("index,logit\n0,-1.5\n1,2.25\n")
    assert run_spike.read_logits(f) == [-1.5, 2.25]


def test_missing_video_stops_before_running(tmp_path, capsys):
    rc = run_spike.main(
        ["--video", str(tmp_path / "none.mp4"), "--device", "cpu", "--tag", "t", "--out-dir", str(tmp_path)]
    )
    assert rc == 2
    assert "파일 없음" in capsys.readouterr().err


def test_state_dict_filter_matches_demo_rule():
    from research.waverep import check_state_dict

    kept, dropped = check_state_dict.filter_like_demo(
        {"state_dict": {"model.blocks.0.w": 1, "loss.weight": 2}}
    )
    assert kept == {"blocks.0.w": 1}
    assert dropped == ["loss.weight"]
    assert check_state_dict.filter_like_demo({"blocks.0.w": 1}) == ({"blocks.0.w": 1}, [])
