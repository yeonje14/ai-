"""MotionPhys 특징: 궤적 → 곡률·각속도·jerk → 24차원 → 168차원 → 504차원.

He et al., arXiv:2608.20770v1 식 (3)~(19)의 재구현이다. 공개 코드가 없어 논문 본문만 보고 썼다.
정의와 "논문 / 확인 필요 / 우리 선택" 구분은 docs/motionphys-spec.md에 있다.
NumPy만 쓴다. 영상이나 추적과 무관한 순수 계산이다.
"""

from __future__ import annotations

import numpy as np

SCALES = (8, 12, 24)                     # 논문: 시간 스케일(프레임 수)
EPS = 1e-6                               # 우리 선택: 논문은 "작은 상수"라고만 한다
QUANTITIES = ("curvature", "angular_velocity", "jerk")
TRAJ_STATS = ("mean", "std", "min", "max", "skew", "kurtosis", "median", "iqr")   # 식 (10)
AGG_STATS = ("mean", "std", "min", "max", "median", "q25", "q75")                 # 식 (15)
TRAJ_DIM = len(QUANTITIES) * len(TRAJ_STATS)      # 24
SCALE_DIM = TRAJ_DIM * len(AGG_STATS)             # 168
FEATURE_DIM = SCALE_DIM * len(SCALES)             # 504
MIN_TRAJECTORY_LENGTH = 5                # jerk 값이 2개 이상 나오는 최소 길이 (우리 선택)


def kinematic_sequences(trajectories: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(M, T, 2) 궤적 묶음 → 곡률 (M, T-2), 각속도 (M, T-2), jerk 크기 (M, T-3).

    v_t = p_{t+1} - p_t (식 3), a_t = v_{t+1} - v_t (식 4)
    κ_t = |v_t^x a_t^y - v_t^y a_t^x| / (||v_t||^3 + ε) (식 5)
    ω_t = arccos(clip(v̂_t · v̂_{t+1}, -1, 1)), v̂ = v / (||v|| + ε) (식 6, 7)
    ρ_t = ||a_{t+1} - a_t|| (식 8, 9)
    """
    p = np.asarray(trajectories, dtype=np.float64)
    if p.ndim != 3 or p.shape[2] != 2:
        raise ValueError(f"궤적은 (M, T, 2) 모양이어야 한다: {p.shape}")
    if p.shape[1] < MIN_TRAJECTORY_LENGTH:
        raise ValueError(f"궤적 길이는 {MIN_TRAJECTORY_LENGTH} 이상이어야 한다: {p.shape[1]}")
    v = np.diff(p, axis=1)                       # (M, T-1, 2)
    a = np.diff(v, axis=1)                       # (M, T-2, 2)
    speed = np.linalg.norm(v, axis=2)            # (M, T-1)

    v0 = v[:, :-1]                               # a_t와 짝이 되는 v_t
    cross = np.abs(v0[..., 0] * a[..., 1] - v0[..., 1] * a[..., 0])
    curvature = cross / (speed[:, :-1] ** 3 + EPS)

    unit = v / (speed[..., None] + EPS)
    cosine = np.clip(np.sum(unit[:, :-1] * unit[:, 1:], axis=2), -1.0, 1.0)
    angular_velocity = np.arccos(cosine)

    jerk = np.linalg.norm(np.diff(a, axis=1), axis=2)
    return curvature, angular_velocity, jerk


def stats8(q: np.ndarray) -> np.ndarray:
    """(M, n) → (M, 8): 평균, 표준편차, 최소, 최대, 왜도, 첨도, 중앙값, IQR (식 10).

    우리 선택: 표준편차는 모집단(ddof=0), 왜도와 첨도는 편향 표본 적률로 계산하고
    첨도는 초과 첨도(정규분포가 0)다. 분산이 0이면 왜도와 첨도는 0으로 둔다.
    """
    q = np.asarray(q, dtype=np.float64)
    mean = q.mean(axis=1)
    centered = q - mean[:, None]
    var = (centered ** 2).mean(axis=1)
    std = np.sqrt(var)
    ok = var > 1e-24
    safe = np.where(ok, var, 1.0)
    skew = np.where(ok, (centered ** 3).mean(axis=1) / safe ** 1.5, 0.0)
    kurt = np.where(ok, (centered ** 4).mean(axis=1) / safe ** 2 - 3.0, 0.0)
    q25, median, q75 = np.percentile(q, [25, 50, 75], axis=1)
    return np.stack([mean, std, q.min(axis=1), q.max(axis=1), skew, kurt, median, q75 - q25], axis=1)


def trajectory_features(trajectories: np.ndarray) -> np.ndarray:
    """(M, T, 2) → (M, 24): [φ(κ); φ(ω); φ(ρ)] (식 11)."""
    curvature, angular_velocity, jerk = kinematic_sequences(trajectories)
    return np.concatenate([stats8(curvature), stats8(angular_velocity), stats8(jerk)], axis=1)


def aggregate_scale(traj_features: np.ndarray) -> np.ndarray:
    """(M, 24) → (168,): 차원마다 궤적 간 통계 7개를 이어 붙인다 (식 15, 16)."""
    f = np.asarray(traj_features, dtype=np.float64)
    if f.ndim != 2 or f.shape[1] != TRAJ_DIM or f.shape[0] == 0:
        raise ValueError(f"궤적 특징은 (M>=1, {TRAJ_DIM}) 모양이어야 한다: {f.shape}")
    q25, median, q75 = np.percentile(f, [25, 50, 75], axis=0)
    per_dim = np.stack([f.mean(axis=0), f.std(axis=0), f.min(axis=0), f.max(axis=0), median, q25, q75], axis=1)
    return per_dim.reshape(-1)       # [ψ(F[:,1]); ψ(F[:,2]); ...]


def video_feature(traj_features_by_scale: dict[int, np.ndarray]) -> np.ndarray:
    """{8: (M8, 24), 12: ..., 24: ...} → (504,) (식 18). 빠진 스케일이 있으면 ValueError."""
    missing = [s for s in SCALES if s not in traj_features_by_scale or len(traj_features_by_scale[s]) == 0]
    if missing:
        raise ValueError(f"유효 궤적이 없는 스케일: {missing}")
    return np.concatenate([aggregate_scale(traj_features_by_scale[s]) for s in SCALES])


def feature_names(prefix: str = "") -> list[str]:
    """504개 특징의 이름. 순서는 video_feature의 출력과 같다."""
    names = []
    for scale in SCALES:
        for quantity in QUANTITIES:
            for traj_stat in TRAJ_STATS:
                for agg in AGG_STATS:
                    names.append(f"{prefix}L{scale}.{quantity}.{traj_stat}.{agg}")
    return names


def mean_step(trajectories: np.ndarray) -> np.ndarray:
    """(M, T, 2) → (M,): 한 걸음(프레임 간격)당 평균 이동 거리. 움직임 크기의 척도다."""
    p = np.asarray(trajectories, dtype=np.float64)
    return np.linalg.norm(np.diff(p, axis=1), axis=2).mean(axis=1)
