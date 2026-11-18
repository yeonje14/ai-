"""scripts/audit_null_adoption.py의 시드별 기록과 요약 집계. 학습·리포트는 가짜로 바꿔 판단 논리를 다시 돌리지 않는다."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('audit_null_adoption', REPO_ROOT / 'scripts/audit_null_adoption.py')
aud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aud)


def _check(passed, value=None):
    return {'check': 'x', 'value': value, 'rule': '<= 0.1', 'passed': passed}


def fake_report(boot=0.07, exact=0.12, fusion='W+M'):
    test = {'overall': {'roc_auc': {'ci_low': 0.46}, 'fpr': {'ci_high': boot},
                        'fpr_exact_upper': {'value': exact, 'video_fpr': 0.055, 'n_real_groups': 100}},
            'counts': {'real_scored': 400, 'groups': 100}}
    return {'decision': {'decision': 'hold', 'servable_candidates': []},
            'candidates': {'W': {'test': test}},
            'selection': {'fusion': fusion},
            'gates': {'own': {'W': [_check(False, 0.46), _check(False, max(boot, exact))],
                              'W+M': [_check(False), _check(True)]},
                      'fusion': {'W+M': [_check(False), _check(True), _check(True), _check(False)]}}}


def test_one_records_fpr_gate_value_as_max_of_bootstrap_and_exact(monkeypatch, tmp_path):
    monkeypatch.setattr(aud.synth, 'write', lambda *a, **k: None)
    monkeypatch.setattr(aud.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stderr=''))
    monkeypatch.setattr(aud.build, 'build', lambda *a, **k: fake_report())
    (tmp_path / 'seed1').mkdir()
    r = aud.one(1, 1000, tmp_path, {})
    assert r['w_fpr_ci_high'] == 0.07  # 기존 필드: bootstrap 상한만
    assert r['w_fpr_gate_value'] == 0.12 and r['w_fpr_exact_upper'] == 0.12  # 관문 값은 둘 중 큰 값
    assert r['test_real_groups'] == 100 and r['w_test_video_fpr'] == 0.055
    assert r['own_fpr_passed'] == {'W': False, 'W+M': True} and r['own_auc_passed'] == {'W': False, 'W+M': False}
    assert r['fusion_selected'] == 'W+M' and r['fusion_checks_passed'] == [False, True, True, False]
    assert r['own_passed'] == {'W': False, 'W+M': False}


def test_one_without_fusion_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(aud.synth, 'write', lambda *a, **k: None)
    monkeypatch.setattr(aud.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stderr=''))
    monkeypatch.setattr(aud.build, 'build', lambda *a, **k: fake_report(fusion=None))
    (tmp_path / 'seed2').mkdir()
    r = aud.one(2, 1000, tmp_path, {})
    assert r['fusion_selected'] is None and r['fusion_checks_passed'] is None


def test_summary_counts_gate_passes(monkeypatch, tmp_path, capsys):
    records = iter([
        {'seed': 1, 'decision': 'hold', 'w_auc_ci_low': 0.4, 'own_passed': {'W': False, 'W+M': False},
         'own_fpr_passed': {'W': True, 'W+M': True}, 'own_auc_passed': {'W': False, 'W+M': False}, 'fusion_selected': 'W+M'},
        {'seed': 2, 'decision': 'waverep_only', 'w_auc_ci_low': 0.51, 'own_passed': {'W': True, 'W+M': False},
         'own_fpr_passed': {'W': True, 'W+M': False}, 'own_auc_passed': {'W': True, 'W+M': False}, 'fusion_selected': 'W+M'},
        {'seed': 3, 'decision': 'train_refused', 'detail': 'x'},
    ])
    monkeypatch.setattr(aud, 'one', lambda *a, **k: next(records))
    assert aud.main(['--identities', '10', '--seeds', '3', '--out', str(tmp_path / 'out')]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out['decisions'] == {'hold': 1, 'waverep_only': 1, 'train_refused': 1}
    assert out['w_auc_ci_low_above_0.5'] == 1
    assert out['gates'] == {'W_fpr_gate_passed': 2, 'W_auc_gate_passed': 1, 'fusion_fpr_gate_passed': 1,
                            'any_candidate_own_passed': 1}
