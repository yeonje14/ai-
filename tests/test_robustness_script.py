"""scripts/robustness_selfvideo.py의 비교·건너뛰기 논리. 영상과 모델은 쓰지 않는다."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('robustness_selfvideo', REPO_ROOT / 'scripts/robustness_selfvideo.py')
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)


def test_conditions_are_original_plus_twelve_software_profiles():
    conds = rb.conditions()
    assert conds[0] == 'original' and len(conds) == 13
    assert all(p.encoder == 'libx264' for p in rb.PROFILES.values())
    assert set(rb.SYNCNET_REDUCED) <= set(conds) and not any('1080p' in c for c in rb.SYNCNET_REDUCED)


def test_feature_comparison_groups_by_quantity_and_skips_zero_base():
    names = ['L8.jerk.mean.median', 'L8.jerk.max.mean', 'L8.curvature.mean.median', 'L8.angular_velocity.std.q25']
    out = rb.compare_features(names, [2.0, 0.0, 4.0, 1.0], [2.2, 5.0, 3.0, 1.0])
    assert out['by_quantity']['jerk']['features_compared'] == 1  # 기준값 0은 뺀다
    assert out['by_quantity']['jerk']['median_abs_rel_change'] == pytest.approx(0.1)
    assert out['by_quantity']['curvature']['median_abs_rel_change'] == pytest.approx(0.25)
    assert out['by_quantity']['angular_velocity']['p90_abs_rel_change'] == 0
    assert out['selected']['L8.curvature.mean.median']['rel_change'] == pytest.approx(-0.25)
    assert set(out['selected']) == {'L8.jerk.mean.median', 'L8.curvature.mean.median'}


def test_waverep_comparison_matches_frames_by_index():
    base = {'frames': [{'index': 0, 'logit': 1.0}, {'index': 15, 'logit': -1.0}, {'index': 30, 'logit': 3.0}],
            'frame_logit': {'median': 1.0}}
    cur = {'frames': [{'index': 0, 'logit': 1.5}, {'index': 15, 'logit': 0.5}, {'index': 45, 'logit': 9.0}],
           'frame_logit': {'median': 1.5}}
    out = rb._waverep_vs(base, cur)
    assert out['frames_matched'] == 2 and out['max_abs_diff'] == 1.5 and out['median_shift'] == 0.5
    assert out['sign_changes'] == 1
    assert rb._waverep_vs(base, {'frames': None}) is None  # unsupported_input 등은 비교하지 않는다


def test_summary_marks_duplicates_and_unmeasured(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, 'OUT', tmp_path)
    rb.write_json(tmp_path / 'variants/A.index.json', {'video': 'A', 'conditions': {
        'original': {'status': 'original', 'sha256': 'o', 'duplicate_of': None},
        'x264-crf20-source': {'status': 'completed', 'sha256': 's', 'duplicate_of': None},
        'x264-crf20-1080p': {'status': 'completed', 'sha256': 's', 'duplicate_of': 'x264-crf20-source'}}})
    for cond in ('original', 'x264-crf20-source'):
        rb.write_json(rb.result_path('A', cond, 'gate'), {'elapsed_sec': 1.0, 'children_max_rss_bytes': 5, 'result': {
            'reason_code': None, 'eligible_duration_sec': 3.0, 'eligible_segments': [[0, 3]], 'excluded_segments': []}})
    rows = rb.build_summary(['A'])['videos']['A']
    assert rows['x264-crf20-1080p'] == {'file': {'status': 'completed', 'sha256': 's', 'probe': None,
                                                 'duplicate_of': 'x264-crf20-source', 'encode_sec': None, 'reason': None}}
    assert rows['x264-crf20-source']['gate']['eligible_duration_sec'] == 3.0
    assert rows['x264-crf20-source']['syncnet'] is None  # 결과 파일이 없으면 미측정
    json.dumps(rows, allow_nan=False)
