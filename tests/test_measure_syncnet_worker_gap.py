"""scripts/measure_syncnet_worker_gap.py와 research/syncnet/profile_adapter_shim.py의 측정 보조 논리. 영상·모델은 쓰지 않는다."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('measure_syncnet_worker_gap', REPO_ROOT / 'scripts/measure_syncnet_worker_gap.py')
gap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gap)

IOREG = '''+-o AppleSmartBattery  <class AppleSmartBattery>
    {
      "ExternalConnected" = Yes
      "AdapterDetails" = {"IsWireless"=No,"Watts"=20,"Current"=1670}
      "CurrentCapacity" = 28
      "PowerTelemetryData" = {"SystemLoad"=21161,"SystemPowerIn"=19060,"BatteryPower"=18446744073709549515}
      "IsCharging" = Yes
    }
'''


def test_plan_parses_condition_and_repeat_and_rejects_unknown():
    assert gap.parse_plan('a1, b2,c3,d10,e4') == [('a', 1), ('b', 2), ('c', 3), ('d', 10), ('e', 4)]
    with pytest.raises(ValueError):
        gap.parse_plan('f1')
    with pytest.raises(ValueError):
        gap.parse_plan('a')


def test_power_telemetry_reads_signed_battery_power(monkeypatch):
    monkeypatch.setattr(gap, '_cmd', lambda *a, **k: IOREG)
    power = gap.power_telemetry()
    assert power['SystemLoad'] == 21161 and power['SystemPowerIn'] == 19060
    assert power['BatteryPower'] == 18446744073709549515 - 2 ** 64 < 0  # 방전은 음수
    assert power['adapter_watts'] == 20 and power['CurrentCapacity'] == '28' and power['IsCharging'] == 'Yes'


def test_power_telemetry_missing_values_are_none(monkeypatch):
    monkeypatch.setattr(gap, '_cmd', lambda *a, **k: '')
    assert gap.power_telemetry() == {'SystemLoad': None, 'SystemPowerIn': None, 'BatteryPower': None,
                                     'adapter_watts': None, 'CurrentCapacity': None, 'IsCharging': None,
                                     'ExternalConnected': None}


def test_descendants_follow_the_whole_tree_only():
    rows = [(10, 1, 0, 'x'), (11, 10, 0, 'x'), (12, 11, 0, 'x'), (20, 1, 0, 'y'), (21, 20, 0, 'y')]
    assert gap._descendants(rows, 10) == {11, 12}
    assert gap._descendants(rows, 12) == set()


def test_syncnet_samples_use_the_same_monotonic_clock_for_worker_and_outside_runs():
    samples = [{'t': t} for t in (0, 5, 10, 15, 20, 25)]
    worker = {'cond': 'a', 'samples_t0_mono': 100.0, 'samples': samples,
              'trace': {'syncnet_adapter': {'mono': [109.0, 121.0]}}}
    outside = {'cond': 'c', 'samples_t0_mono': 100.0, 'samples': samples, 'syncnet': {'mono': [100.0, 105.0]}}
    assert [s['t'] for s in gap.syncnet_samples(worker)] == [10, 15, 20]
    assert [s['t'] for s in gap.syncnet_samples(outside)] == [0, 5]
    assert gap.syncnet_samples({'cond': 'b', 'samples_t0_mono': 0.0, 'samples': samples, 'trace': None}) == []


def test_rest_waits_until_thermal_state_and_probe_recover(monkeypatch):
    states, probes = iter([1, 0]), iter([0.050, 0.041])
    monkeypatch.setattr(gap, 'thermal_state', lambda probe: next(states))
    monkeypatch.setattr(gap, 'cpu_probe', lambda repeats=5: {'min_sec': next(probes)})
    monkeypatch.setattr(gap.time, 'sleep', lambda s: None)
    baseline = [0.040]
    out = gap.rest(0.0, 900.0, None, baseline)
    assert out['reached'] is True and len(out['trail']) == 2 and out['trail'][-1][1:] == [0, 0.041]


def test_shim_dry_writes_adapter_format_result(tmp_path):
    work = tmp_path / 'syncnet-x'
    work.mkdir()
    (work / 'request.json').write_text(json.dumps({'segments': [[0.0, 2.0], [3.0, 6.0]]}))
    copy = tmp_path / 'copy.json'
    code = subprocess.run([sys.executable, str(REPO_ROOT / 'research/syncnet/profile_adapter_shim.py'),
                           '--request', str(work / 'request.json'), '--output', str(work / 'result.json')],
                          env={'SYNCNET_GAP_DRY': '1', 'SYNCNET_PROFILE_COPY_TO': str(copy), 'PATH': '/usr/bin:/bin'}).returncode
    assert code == 0
    from server.axes.alignment.report import parse_result
    parsed = parse_result(json.loads((work / 'result.json').read_text()), [[0.0, 2.0], [3.0, 6.0]])
    assert parsed['status'] == 'insufficient_input' and len(parsed['segments']) == 2
    assert json.loads(copy.read_text()) == {'dry': True}
