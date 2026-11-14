"""평가 지표 (README §6.3, §13.1). 표준 라이브러리만 쓴다.

점수는 클수록 "가짜"라는 방향의 원시 점수다. 판정 규칙은 `점수 >= 임계값 → 가짜`.
계산할 수 없는 값은 None이다. 0으로 채우지 않는다.
신뢰구간은 인물·원본 계보 그룹을 복원 추출하는 bootstrap이다(영상 단위가 아니다).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

UNKNOWN = "(미상)"
ORIGINAL = "original"  # 압축 조건이 빈칸인 영상


@dataclass(frozen=True)
class Item:
    """평가 단위(영상 하나). score가 None이면 판정을 내지 못한 영상이다."""

    uid: str
    label: str                      # real / fake
    group: str                      # 인물·원본 계보 그룹
    score: Optional[float] = None
    generator: str = ""
    manipulation_type: str = ""
    reason_code: str = ""           # score가 None인 이유
    compression: str = ""           # 압축 조건(프로파일 ID). 빈칸은 원본


def roc_auc(fake_scores: Sequence[float], real_scores: Sequence[float]) -> Optional[float]:
    """가짜 점수가 진짜 점수보다 클 확률(동점은 0.5). 한쪽이 비면 None."""
    n_pos, n_neg = len(fake_scores), len(real_scores)
    if n_pos == 0 or n_neg == 0:
        return None
    ordered = sorted([(s, 1) for s in fake_scores] + [(s, 0) for s in real_scores])
    rank_sum = 0.0
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j][0] == ordered[i][0]:
            j += 1
        mean_rank = (i + 1 + j) / 2  # 동점 구간의 평균 순위(1부터)
        rank_sum += mean_rank * sum(flag for _, flag in ordered[i:j])
        i = j
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def threshold_at_fpr(real_scores: Sequence[float], target_fpr: float) -> float:
    """진짜 점수에서 FPR이 target 이하가 되는 가장 낮은 임계값.

    허용 오탐 수 k = floor(target × n). (k+1)번째로 큰 진짜 점수보다 바로 위의 값을
    돌려주므로, 동점이 있어도 실제 FPR이 target을 넘지 않는다.
    """
    if not 0 < target_fpr < 1:
        raise ValueError(f"target_fpr은 0과 1 사이여야 한다: {target_fpr!r}")
    if not real_scores:
        raise ValueError("진짜 영상의 점수가 없어 임계값을 정할 수 없다")
    desc = sorted(real_scores, reverse=True)
    k = math.floor(target_fpr * len(desc) + 1e-12)
    return math.nextafter(desc[k], math.inf)


def rate_at(scores: Sequence[float], threshold: float) -> Optional[float]:
    """점수 >= 임계값인 비율. 점수가 없으면 None."""
    if not scores:
        return None
    return sum(1 for s in scores if s >= threshold) / len(scores)


def _scored(items: Sequence[Item], label: str) -> list[float]:
    return [it.score for it in items if it.label == label and it.score is not None]


def point_metrics(items: Sequence[Item], threshold: float) -> dict[str, Optional[float]]:
    """한 집합의 점 추정값. 이름 → 값의 평평한 사전이라 bootstrap에서 그대로 다시 쓴다."""
    real, fake = _scored(items, "real"), _scored(items, "fake")
    out: dict[str, Optional[float]] = {
        "roc_auc": roc_auc(fake, real),
        "tpr": rate_at(fake, threshold),
        "fpr": rate_at(real, threshold),
    }
    for kind, key in (("generator", lambda it: it.generator), ("manipulation_type", lambda it: it.manipulation_type)):
        by: dict[str, list[float]] = defaultdict(list)
        for it in items:
            if it.label == "fake" and it.score is not None:
                by[key(it) or UNKNOWN].append(it.score)
        for name, scores in by.items():
            out[f"{kind}\x1f{name}\x1ftpr"] = rate_at(scores, threshold)
            # 그 범주의 가짜 대 전체 진짜
            out[f"{kind}\x1f{name}\x1froc_auc"] = roc_auc(scores, real)
    # 압축 조건별: 같은 조건의 진짜와 가짜끼리만 견준다
    conditions = {it.compression or ORIGINAL for it in items}
    if conditions != {ORIGINAL}:
        for name in conditions:
            members = [it for it in items if (it.compression or ORIGINAL) == name]
            c_real, c_fake = _scored(members, "real"), _scored(members, "fake")
            out[f"compression\x1f{name}\x1froc_auc"] = roc_auc(c_fake, c_real)
            out[f"compression\x1f{name}\x1ftpr"] = rate_at(c_fake, threshold)
            out[f"compression\x1f{name}\x1ffpr"] = rate_at(c_real, threshold)
    else:  # 조건이 원본 하나뿐이면 전체와 같다
        for m in ("roc_auc", "tpr", "fpr"):
            out[f"compression\x1f{ORIGINAL}\x1f{m}"] = out[m]
    return out


def group_bootstrap(
    items: Sequence[Item],
    stat: Callable[[Sequence[Item]], dict[str, Optional[float]]],
    n_boot: int,
    seed: int,
    confidence: float = 0.95,
) -> dict[str, dict]:
    """그룹을 복원 추출해 이름별 백분위 신뢰구간을 구한다.

    한 번의 추출에서 값이 None인 지표(예: 진짜가 하나도 안 뽑힘)는 그 회차만 뺀다.
    n_valid로 몇 회가 쓰였는지 알린다. 유효 회차가 없으면 low/high는 None.
    """
    if n_boot < 1:
        raise ValueError("n_boot는 1 이상이어야 한다")
    by_group: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_group[it.group].append(it)
    groups = sorted(by_group)
    rng = random.Random(seed)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(n_boot):
        drawn: list[Item] = []
        for g in rng.choices(groups, k=len(groups)):
            drawn.extend(by_group[g])
        for name, value in stat(drawn).items():
            if value is not None:
                samples[name].append(value)

    alpha = (1 - confidence) / 2
    out: dict[str, dict] = {}
    for name, values in samples.items():
        values.sort()
        out[name] = {
            "low": _percentile(values, alpha),
            "high": _percentile(values, 1 - alpha),
            "n_valid": len(values),
        }
    return out


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """선형 보간 백분위."""
    pos = q * (len(sorted_values) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def evaluate(
    items: Sequence[Item],
    threshold: float,
    n_boot: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
) -> dict:
    """전체·생성기별·유형별·압축 조건별 지표와 그룹 bootstrap 신뢰구간, 보류 현황."""
    items = list(items)
    point = point_metrics(items, threshold)
    ci = group_bootstrap(items, lambda xs: point_metrics(xs, threshold), n_boot, seed, confidence) if items else {}

    def with_ci(name: str) -> dict:
        c = ci.get(name)
        return {
            "value": point.get(name),
            "ci_low": c["low"] if c else None,
            "ci_high": c["high"] if c else None,
            "n_boot_valid": c["n_valid"] if c else 0,
        }

    def breakdown(kind: str, key) -> dict:
        names = sorted({key(it) or UNKNOWN for it in items if it.label == "fake"})
        out = {}
        for name in names:
            members = [it for it in items if it.label == "fake" and (key(it) or UNKNOWN) == name]
            scored = [it for it in members if it.score is not None]
            out[name] = {
                "fake_videos": len(members),
                "fake_scored": len(scored),
                "fake_groups": len({it.group for it in members}),
                "tpr": with_ci(f"{kind}\x1f{name}\x1ftpr"),
                # 이 범주의 가짜 대 전체 진짜
                "roc_auc_vs_all_real": with_ci(f"{kind}\x1f{name}\x1froc_auc"),
            }
        return out

    def by_compression() -> dict:
        out = {}
        for name in sorted({it.compression or ORIGINAL for it in items}):
            members = [it for it in items if (it.compression or ORIGINAL) == name]
            out[name] = {
                "videos": len(members),
                "groups": len({it.group for it in members}),
                "real": sum(1 for it in members if it.label == "real"),
                "fake": sum(1 for it in members if it.label == "fake"),
                "real_scored": len(_scored(members, "real")),
                "fake_scored": len(_scored(members, "fake")),
                **{m: with_ci(f"compression\x1f{name}\x1f{m}") for m in ("roc_auc", "tpr", "fpr")},
            }
        return out

    scored = [it for it in items if it.score is not None]
    reasons: dict[str, int] = defaultdict(int)
    for it in items:
        if it.score is None:
            reasons[it.reason_code or UNKNOWN] += 1
    total = len(items)
    return {
        "counts": {
            "videos": total,
            "groups": len({it.group for it in items}),
            "real": sum(1 for it in items if it.label == "real"),
            "fake": sum(1 for it in items if it.label == "fake"),
            "real_scored": len(_scored(items, "real")),
            "fake_scored": len(_scored(items, "fake")),
        },
        # 판정을 낸 영상의 비율. 정확도나 신뢰도가 아니다
        "selective": {
            "verdict_coverage": len(scored) / total if total else None,
            "abstention_rate": (total - len(scored)) / total if total else None,
            "abstained": total - len(scored),
            "abstained_by_reason": dict(sorted(reasons.items())),
        },
        "overall": {name: with_ci(name) for name in ("roc_auc", "tpr", "fpr")},
        "by_generator": breakdown("generator", lambda it: it.generator),
        "by_manipulation_type": breakdown("manipulation_type", lambda it: it.manipulation_type),
        # 압축 조건별. 그 조건의 진짜와 가짜만으로 계산한다. 임계값은 dev에서 고정한 값 그대로다
        "by_compression": by_compression(),
        "bootstrap": {"unit": "group", "n_boot": n_boot, "seed": seed, "confidence": confidence},
    }
