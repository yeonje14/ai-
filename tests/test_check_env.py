"""scripts/check_env.py: 없는 것은 설치하지 않고 "없음"으로만 기록하는지 확인한다."""

import sys

from scripts import check_env
from scripts.check_env import FAILED, MISSING, OK, Check


def test_missing_module_is_recorded_as_missing():
    check = check_env.check_module("가짜", "trinity_no_such_module_xyz")
    assert check.status == MISSING


def test_broken_import_is_failed_not_missing(tmp_path, monkeypatch):
    # 설치는 됐지만 가져오다 깨지는 경우(예: dylib 누락)는 "없음"과 구별한다.
    (tmp_path / "trinity_broken_mod.py").write_text("raise OSError('libomp.dylib not found')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    check = check_env.check_module("깨짐", "trinity_broken_mod")
    assert check.status == FAILED
    assert "libomp" in check.detail


def test_missing_tool_is_recorded_as_missing(monkeypatch):
    monkeypatch.setattr(check_env.shutil, "which", lambda name: None)
    assert check_env.check_tool("ffmpeg").status == MISSING
    assert check_env.check_ffmpeg_encoder().status == MISSING


def test_tool_version_is_read_with_argument_list(monkeypatch):
    monkeypatch.setattr(check_env.shutil, "which", lambda name: sys.executable)
    seen = []

    def fake_run(args, timeout=15.0):
        seen.append(args)
        return "ffmpeg version 9.9 Copyright\nbuilt with clang"

    monkeypatch.setattr(check_env, "_run", fake_run)
    check = check_env.check_tool("ffmpeg")
    assert check.status == OK
    assert check.detail.startswith("ffmpeg version 9.9")
    assert seen == [[sys.executable, "-version"]]


def test_torch_missing_marks_cpu_and_mps_missing(monkeypatch):
    monkeypatch.setattr(check_env, "_import", lambda module: (None, (MISSING, "설치되지 않음")))
    checks = check_env.check_torch()
    assert [c.name for c in checks] == ["PyTorch", "PyTorch CPU", "PyTorch MPS"]
    assert all(c.status == MISSING for c in checks)
    assert check_env.available_devices(checks) == []


def test_available_devices_follow_mps_then_cpu_order():
    checks = [Check("PyTorch CPU", OK), Check("PyTorch MPS", OK)]
    assert check_env.available_devices(checks) == ["mps", "cpu"]
    checks = [Check("PyTorch CPU", OK), Check("PyTorch MPS", FAILED)]
    assert check_env.available_devices(checks) == ["cpu"]


def test_markdown_lists_problems_and_console_log():
    checks = [
        Check("Python", OK, "3.11.0"),
        Check("LightGBM", MISSING, "설치되지 않음"),
        Check("PyTorch MPS", FAILED, "a|b"),
    ]
    text = check_env.render_markdown(checks, "2026-01-01 00:00:00 +0900")
    assert "- **LightGBM** — 없음: 설치되지 않음" in text
    assert "- **PyTorch MPS** — 실패: a|b" in text
    assert "| PyTorch MPS | 실패 | a\\|b |" in text
    assert "[없음] LightGBM" in text
    assert "- **Python**" not in text


def test_main_writes_report_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_env, "run_checks", lambda: [Check("LightGBM", MISSING, "설치되지 않음")])
    out = tmp_path / "sub" / "env-check.md"
    assert check_env.main(["--output", str(out)]) == 0
    assert "| LightGBM | 없음 | 설치되지 않음 |" in out.read_text(encoding="utf-8")
    assert "[없음] LightGBM" in capsys.readouterr().out
