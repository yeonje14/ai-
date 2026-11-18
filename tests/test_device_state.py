"""server/jobs/device_state.py: macOS thermalState를 Worker 밖의 짧은 프로세스로 읽는다."""
import subprocess
import sys
from types import SimpleNamespace

import pytest

from server.jobs import device_state


def _fake_run(stdout="0", returncode=0, exc=None, calls=None):
    def run(cmd, **kwargs):
        if calls is not None:
            calls.append((cmd, kwargs))
        if exc is not None:
            raise exc
        return SimpleNamespace(stdout=stdout, returncode=returncode)
    return run


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(device_state.sys, "platform", "darwin")


def test_maps_probe_output_to_names(monkeypatch, darwin):
    for raw, name in (("0\n", "nominal"), ("1", "fair"), ("2\n", "serious"), ("3", "critical")):
        monkeypatch.setattr(device_state.subprocess, "run", _fake_run(stdout=raw))
        assert device_state.thermal_state() == name
    for raw in ("7", "-1", "x", "", "1 2"):
        monkeypatch.setattr(device_state.subprocess, "run", _fake_run(stdout=raw))
        assert device_state.thermal_state() is None
    assert device_state.THERMAL_NAMES == ("nominal", "fair", "serious", "critical")


def test_probe_failure_or_timeout_is_none(monkeypatch, darwin):
    for exc in (subprocess.TimeoutExpired(cmd="x", timeout=2.0), OSError("no exec"), ValueError("bad")):
        monkeypatch.setattr(device_state.subprocess, "run", _fake_run(exc=exc))
        assert device_state.thermal_state() is None
    monkeypatch.setattr(device_state.subprocess, "run", _fake_run(stdout="0", returncode=1))
    assert device_state.thermal_state() is None


def test_non_darwin_is_none_without_spawning(monkeypatch):
    calls = []
    monkeypatch.setattr(device_state.sys, "platform", "linux")
    monkeypatch.setattr(device_state.subprocess, "run", _fake_run(calls=calls))
    assert device_state.thermal_state() is None
    assert calls == []


def test_probe_runs_isolated_with_arg_list(monkeypatch, darwin):
    calls = []
    monkeypatch.setattr(device_state.subprocess, "run", _fake_run(calls=calls))
    device_state.thermal_state(timeout=1.5)
    (cmd, kwargs), = calls
    assert cmd == [sys.executable, "-I", "-c", device_state._PROBE]
    assert not kwargs.get("shell") and kwargs["timeout"] == 1.5
    assert kwargs.get("stdin") == subprocess.DEVNULL and kwargs.get("stderr") == subprocess.DEVNULL


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS 전용")
def test_real_probe_returns_a_name():
    assert device_state.thermal_state() in device_state.THERMAL_NAMES
