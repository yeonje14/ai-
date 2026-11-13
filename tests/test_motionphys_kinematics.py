"""MotionPhys 특징 계산(research/motionphys/kinematics.py)을 합성 궤적으로 확인한다.

매끄러운 운동과 떨리는 운동에서 곡률·각속도·jerk가 식대로 나오는지 본다.
영상이나 모델은 필요 없다. NumPy가 없으면 건너뛴다.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research" / "motionphys"))

import kinematics as k  # noqa: E402


def line(n=12, velocity=(2.0, 1.0), start=(5.0, 5.0)):
    t = np.arange(n)[:, None]
    return (np.array(start) + t * np.array(velocity))[None]          # (1, n, 2)


def circle(n=12, radius=50.0, theta=0.1):
    a = np.arange(n) * theta
    return np.stack([radius * np.cos(a), radius * np.sin(a)], axis=1)[None]


def test_constant_velocity_has_zero_curvature_turning_and_jerk():
    kappa, omega, jerk = k.kinematic_sequences(line())
    assert kappa.shape == (1, 10) and omega.shape == (1, 10) and jerk.shape == (1, 9)
    assert np.allclose(kappa, 0) and np.allclose(jerk, 0)
    # 식 (6)의 ε 때문에 직선 운동에서도 각속도가 정확히 0은 아니다: 약 sqrt(4ε/|v|)
    speed = math.hypot(2.0, 1.0)
    assert np.allclose(omega, math.sqrt(4 * k.EPS / speed), rtol=1e-3)
    assert omega.max() < 0.002


def test_circular_motion_matches_closed_form():
    radius, theta = 50.0, 0.1
    kappa, omega, jerk = k.kinematic_sequences(circle(radius=radius, theta=theta))
    step = 2 * radius * math.sin(theta / 2)                 # 한 걸음의 길이
    # 이산 곡률: |v×a| / |v|^3 = sinθ / |v| = cos(θ/2) / R (R이 크면 1/R)
    assert np.allclose(kappa, math.cos(theta / 2) / radius, rtol=1e-4)
    assert np.allclose(omega, theta, atol=1e-5)             # 걸음마다 θ만큼 방향이 돈다(ε의 영향 1e-5 이내)
    assert np.allclose(jerk, step * (2 * math.sin(theta / 2)) ** 2, rtol=1e-6)
    assert jerk.std() < 1e-9                                # 등속 원운동의 jerk 크기는 일정하다


def test_constant_acceleration_has_zero_jerk():
    t = np.arange(12)[:, None].astype(float)
    traj = (np.array([1.0, 0.5]) * t + 0.5 * np.array([0.2, -0.1]) * t ** 2)[None]
    kappa, _, jerk = k.kinematic_sequences(traj)
    assert np.allclose(jerk, 0, atol=1e-9)
    assert kappa.max() > 0                                  # 속도와 가속도가 나란하지 않아 휜다


def test_jitter_inflates_jerk_by_the_expected_factor():
    """잡음 σ를 더하면 jerk는 약 5.6σ, 속도는 약 1.77σ만큼 흔들린다(3차 차분의 증폭)."""
    rng = np.random.default_rng(0)
    smooth = np.repeat(line(n=24), 4000, axis=0)
    for sigma in (0.1, 0.4):
        shaky = smooth + rng.normal(0, sigma, smooth.shape)
        jerk = k.kinematic_sequences(shaky)[2]
        # j = p3 - 3p2 + 3p1 - p0 → 성분 분산 20σ², 2차원 크기의 평균 = sqrt(20)σ·sqrt(π/2)
        assert jerk.mean() == pytest.approx(math.sqrt(20) * sigma * math.sqrt(math.pi / 2), rel=0.03)
    assert np.allclose(k.kinematic_sequences(smooth)[2], 0)
    # 같은 잡음이 속도에는 sqrt(2)σ, jerk에는 sqrt(20)σ로 들어간다: sqrt(10)배
    noise = rng.normal(0, 0.2, (4000, 24, 2))
    velocity_noise = np.linalg.norm(np.diff(noise, axis=1), axis=2).mean()
    jerk_noise = k.kinematic_sequences(noise)[2].mean()
    assert jerk_noise / velocity_noise == pytest.approx(math.sqrt(10), rel=0.03)


def test_shaky_trajectories_score_higher_on_jerk_features_than_smooth_ones():
    rng = np.random.default_rng(1)
    smooth = np.repeat(circle(n=12, radius=40, theta=0.15), 300, axis=0)
    shaky = smooth + rng.normal(0, 0.5, smooth.shape)
    names = k.feature_names()
    f_smooth = {s: k.trajectory_features(smooth[:, :s]) for s in k.SCALES[:2]}
    f_shaky = {s: k.trajectory_features(shaky[:, :s]) for s in k.SCALES[:2]}
    for s in k.SCALES[:2]:
        jerk_mean = k.TRAJ_STATS.index("mean") + 2 * len(k.TRAJ_STATS)
        assert f_shaky[s][:, jerk_mean].mean() > 10 * f_smooth[s][:, jerk_mean].mean()
        omega_std = k.TRAJ_STATS.index("std") + 1 * len(k.TRAJ_STATS)
        assert f_shaky[s][:, omega_std].mean() > f_smooth[s][:, omega_std].mean()
    assert len(names) == k.FEATURE_DIM


def test_stationary_point_follows_the_paper_formula():
    """정지한 점: 곡률 0, jerk 0. 각속도는 식 (6)(7)대로 π/2가 된다(v̂가 0벡터라 내적이 0)."""
    still = np.zeros((1, 8, 2)) + 3.0
    kappa, omega, jerk = k.kinematic_sequences(still)
    assert np.allclose(kappa, 0) and np.allclose(jerk, 0)
    assert np.allclose(omega, math.pi / 2)


def test_tiny_motion_makes_curvature_large():
    """아주 작은 움직임(추적 잡음 수준)에서는 |v|^3이 작아 곡률이 크게 나온다."""
    rng = np.random.default_rng(2)
    barely = 3.0 + rng.normal(0, 0.02, (500, 8, 2))
    moving = line(n=8, velocity=(3.0, 0.0)) + rng.normal(0, 0.02, (500, 8, 2))
    assert np.median(k.kinematic_sequences(barely)[0]) > 100 * np.median(k.kinematic_sequences(moving)[0])


def test_stats8_matches_hand_values():
    out = k.stats8(np.array([[1.0, 2.0, 3.0, 4.0, 10.0]]))[0]
    mean, std, lo, hi, skew, kurt, median, iqr = out
    assert (mean, lo, hi, median, iqr) == (4.0, 1.0, 10.0, 3.0, 2.0)
    assert std == pytest.approx(math.sqrt(10.0))            # 모집단 표준편차
    assert skew == pytest.approx((-27 - 8 - 1 + 0 + 216) / 5 / 10 ** 1.5)
    assert kurt == pytest.approx((81 + 16 + 1 + 0 + 1296) / 5 / 100 - 3)
    assert skew > 0


def test_constant_sequence_has_zero_skew_and_kurtosis_not_nan():
    out = k.stats8(np.full((2, 6), 0.7))
    assert np.all(np.isfinite(out))
    assert np.allclose(out[:, [1, 4, 5, 7]], 0)


def test_dimensions_24_168_504():
    rng = np.random.default_rng(3)
    by_scale = {s: k.trajectory_features(rng.normal(0, 1, (30, s, 2)).cumsum(axis=1)) for s in k.SCALES}
    assert all(f.shape == (30, 24) for f in by_scale.values())
    assert k.aggregate_scale(by_scale[8]).shape == (168,)
    z = k.video_feature(by_scale)
    assert z.shape == (504,) and np.all(np.isfinite(z))
    assert (k.TRAJ_DIM, k.SCALE_DIM, k.FEATURE_DIM) == (24, 168, 504)


def test_feature_names_follow_output_order():
    names = k.feature_names()
    assert len(names) == len(set(names)) == 504
    assert names[0] == "L8.curvature.mean.mean" and names[1] == "L8.curvature.mean.std"
    assert names[7] == "L8.curvature.std.mean"
    assert names[168] == "L12.curvature.mean.mean" and names[-1] == "L24.jerk.iqr.q75"
    # 이름이 실제 값의 위치와 맞는지: L8에서 jerk 평균의 궤적 간 최댓값
    rng = np.random.default_rng(4)
    trajs = {s: rng.normal(0, 1, (20, s, 2)).cumsum(axis=1) for s in k.SCALES}
    z = k.video_feature({s: k.trajectory_features(t) for s, t in trajs.items()})
    expected = k.kinematic_sequences(trajs[8])[2].mean(axis=1).max()
    assert z[names.index("L8.jerk.mean.max")] == pytest.approx(expected)
    assert k.feature_names("head.")[0] == "head.L8.curvature.mean.mean"


def test_aggregation_does_not_depend_on_trajectory_order():
    rng = np.random.default_rng(5)
    f = k.trajectory_features(rng.normal(0, 1, (50, 12, 2)).cumsum(axis=1))
    assert np.allclose(k.aggregate_scale(f), k.aggregate_scale(f[rng.permutation(50)]))


def test_missing_scale_or_bad_shapes_are_errors_not_zeros():
    f = k.trajectory_features(np.random.default_rng(6).normal(0, 1, (5, 8, 2)).cumsum(axis=1))
    with pytest.raises(ValueError):
        k.video_feature({8: f, 12: f})
    with pytest.raises(ValueError):
        k.video_feature({8: f, 12: f, 24: np.empty((0, 24))})
    with pytest.raises(ValueError):
        k.kinematic_sequences(np.zeros((3, 4, 2)))          # 너무 짧다
    with pytest.raises(ValueError):
        k.kinematic_sequences(np.zeros((3, 8)))
    with pytest.raises(ValueError):
        k.aggregate_scale(np.empty((0, 24)))


def test_mean_step():
    assert k.mean_step(line(velocity=(3.0, 4.0)))[0] == pytest.approx(5.0)
    assert k.mean_step(np.zeros((2, 8, 2))).tolist() == [0.0, 0.0]
