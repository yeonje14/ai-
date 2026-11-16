"""채택 판단과 그에 쓰는 통계. 표준 라이브러리만 쓴다.

규칙(2026-11-16 사용자 승인, 수치는 configs/training.json의 adoption):
- 후보 선택은 dev에서만 한다. test는 선택이 끝난 뒤 한 번의 확인 관문이다. 확인에 실패해도 다른 후보로 다시 고르지 않는다.
- "채택 가능": 선택된 결합 후보가 test에서
  (1) AUC 95% CI 하한 > g2_min_auc_ci_low,
  (2) WaveRep 단독과 단일 최강 후보 각각에 대해 TPR 차이(짝지은 그룹 bootstrap)의 CI 하한 > min_tpr_gain_ci_low,
  (3) 실제 FPR이 WaveRep 단독보다 max_fpr_worsening 넘게 나쁘지 않고,
  (4) 판정 제공 비율이 max_coverage_drop 넘게 줄지 않으며,
  (5) 고정 임계값의 FPR CI 상한 ≤ max_test_fpr_ci_high.
- "WaveRep 단독": 결합이 위를 못 넘고, WaveRep 단독이 (1)과 (5)를 넘는다.
- 그 밖에는 "보류". 3축을 강제로 채택하지 않는다.
README §13.3에는 숫자 기준이 없다. G3의 "단일 최강 모델 대비"를 따라 (2)는 WaveRep과 단일 최강 둘 다 본다.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Optional, Sequence

from training.evaluation.metrics import Item, _percentile, rate_at, roc_auc

FUSION_ADOPTABLE = "fusion_adoptable"
WAVEREP_ONLY = "waverep_only"
HOLD = "hold"
LABELS_KO = {FUSION_ADOPTABLE: "채택 가능", WAVEREP_ONLY: "WaveRep 단독", HOLD: "보류"}
BASELINE = "W"


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def calibration_metrics(items: Sequence[Item], calibration: dict, bins: int = 10) -> dict:
    """보정된 값의 Brier score와 ECE(같은 폭 구간). 점수가 있는 영상만. 없으면 None."""
    pairs = [(sigmoid(calibration["a"] * it.score + calibration["b"]), 1 if it.label == "fake" else 0)
             for it in items if it.score is not None]
    if not pairs:
        return {"n": 0, "brier": None, "ece": None, "bins": bins}
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    buckets: dict[int, list] = defaultdict(list)
    for p, y in pairs:
        buckets[min(bins - 1, int(p * bins))].append((p, y))
    ece = sum(len(b) / len(pairs) * abs(sum(p for p, _ in b) / len(b) - sum(y for _, y in b) / len(b))
              for b in buckets.values())
    return {"n": len(pairs), "brier": brier, "ece": ece, "bins": bins}


def _stats(rows: Sequence[tuple], threshold: float) -> dict[str, Optional[float]]:
    """rows: (label, score 또는 None)."""
    real = [s for label, s in rows if label == "real" and s is not None]
    fake = [s for label, s in rows if label == "fake" and s is not None]
    scored = sum(1 for _, s in rows if s is not None)
    return {"tpr": rate_at(fake, threshold), "fpr": rate_at(real, threshold), "roc_auc": roc_auc(fake, real),
            "coverage": scored / len(rows) if rows else None}


def paired_difference(a: Sequence[Item], b: Sequence[Item], threshold_a: float, threshold_b: float,
                      n_boot: int, seed: int, confidence: float = 0.95) -> dict:
    """같은 영상 집합에 대한 두 후보의 차이(a − b). 그룹을 한 번 뽑아 두 후보에 똑같이 적용한다."""
    by_uid = {it.uid: it for it in b}
    if set(by_uid) != {it.uid for it in a}:
        raise ValueError("두 후보의 영상 집합이 다르다")
    by_group: dict[str, list] = defaultdict(list)
    for it in a:
        by_group[it.group].append((it.label, it.score, by_uid[it.uid].score))
    names = sorted(by_group)
    metrics = ("tpr", "fpr", "roc_auc", "coverage")

    def diff(rows) -> dict:
        sa = _stats([(label, x) for label, x, _ in rows], threshold_a)
        sb = _stats([(label, y) for label, _, y in rows], threshold_b)
        return {m: (sa[m] - sb[m] if sa[m] is not None and sb[m] is not None else None) for m in metrics}

    point = diff([row for g in names for row in by_group[g]])
    rng = random.Random(seed)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(n_boot):
        rows = [row for g in rng.choices(names, k=len(names)) for row in by_group[g]]
        for m, v in diff(rows).items():
            if v is not None:
                samples[m].append(v)
    alpha = (1 - confidence) / 2
    out = {}
    for m in metrics:
        values = sorted(samples[m])
        out[m] = {"value": point[m], "ci_low": _percentile(values, alpha) if values else None,
                  "ci_high": _percentile(values, 1 - alpha) if values else None, "n_boot_valid": len(values)}
    return out


def select_on_dev(dev: dict[str, dict], candidates: Sequence[dict]) -> dict:
    """dev AUC만으로 단일 최강과 결합 후보를 고른다(동률이면 입력이 적은 쪽). test를 보지 않는다."""
    def auc(c):
        return dev[c["candidate"]]["overall"]["roc_auc"]["value"]

    def best(pool):
        pool = [c for c in pool if auc(c) is not None]
        return max(pool, key=lambda c: (auc(c), -len(c["inputs"])))["candidate"] if pool else None

    return {"criterion": "dev ROC-AUC", "best_single": best([c for c in candidates if len(c["axes"]) == 1]),
            "fusion": best([c for c in candidates if len(c["axes"]) > 1]),
            "dev_auc": {c["candidate"]: auc(c) for c in candidates}}


def _check(name: str, value: Optional[float], op: str, limit: float) -> dict:
    ok = value is not None and (value > limit if op == ">" else value >= limit if op == ">=" else value <= limit)
    return {"check": name, "value": value, "rule": f"{op} {limit}", "passed": bool(ok)}


def own_gates(test: dict, adoption: dict) -> list[dict]:
    """후보 하나가 혼자서 넘어야 하는 관문: 구분 능력(G2)과 FPR 신뢰구간 상한."""
    return [
        _check("test ROC-AUC CI 하한", test["overall"]["roc_auc"]["ci_low"], ">", adoption["g2_min_auc_ci_low"]),
        _check("test FPR CI 상한(고정 임계값)", test["overall"]["fpr"]["ci_high"], "<=", adoption["max_test_fpr_ci_high"]),
    ]


def fusion_gates(vs_baseline: dict, vs_best_single: Optional[dict], adoption: dict) -> list[dict]:
    checks = [
        _check("TPR 차이 CI 하한 (결합 − WaveRep)", vs_baseline["tpr"]["ci_low"], ">", adoption["min_tpr_gain_ci_low"]),
        _check("FPR 차이 (결합 − WaveRep)", vs_baseline["fpr"]["value"], "<=", adoption["max_fpr_worsening"]),
        _check("판정 제공 비율 차이 (결합 − WaveRep)", vs_baseline["coverage"]["value"], ">=", -adoption["max_coverage_drop"]),
    ]
    if vs_best_single is not None:
        checks.append(_check("TPR 차이 CI 하한 (결합 − 단일 최강)", vs_best_single["tpr"]["ci_low"], ">",
                             adoption["min_tpr_gain_ci_low"]))
    return checks


def decide(selection: dict, own: dict[str, list[dict]], fusion_checks: dict[str, list[dict]]) -> dict:
    """own[후보] = own_gates 결과, fusion_checks[결합 후보] = fusion_gates 결과."""
    def passed(checks) -> bool:
        return bool(checks) and all(c["passed"] for c in checks)

    fusion = selection["fusion"]
    fusion_ok = fusion is not None and passed(own.get(fusion)) and passed(fusion_checks.get(fusion))
    baseline_ok = passed(own.get(BASELINE))
    decision = FUSION_ADOPTABLE if fusion_ok else WAVEREP_ONLY if baseline_ok else HOLD
    # 서버가 쓸 수 있는 후보. 축이 많은 것부터. 각 후보는 자기 축 조합으로 따로 관문을 넘은 것만 넣는다
    servable = []
    if decision == FUSION_ADOPTABLE:
        servable = [c for c in sorted(fusion_checks, key=lambda c: -c.count("+"))
                    if passed(own.get(c)) and passed(fusion_checks[c]) and c.count("+") <= fusion.count("+")]
    if decision != HOLD and baseline_ok:
        servable.append(BASELINE)
    return {"decision": decision, "decision_ko": LABELS_KO[decision], "selected_fusion": fusion,
            "best_single": selection["best_single"], "servable_candidates": servable,
            "three_axis_forced": False}


SHORTCUT_FIELDS = ("width", "height", "fps", "duration_sec", "has_audio")
SHORTCUT_WARN_MARGIN = 0.1  # |AUC − 0.5|가 이보다 크면 경고. 채택 판단에는 쓰지 않는다(경고만)


def shortcut_diagnostic(labels: dict[str, str], media: dict[str, Optional[dict]]) -> dict:
    """파일 메타데이터 하나만으로 라벨이 얼마나 갈리는지(README §6.4 shortcut 진단).

    labels: {uid: real/fake}(train·dev만 넘긴다), media: {uid: {width, height, fps, ...} 또는 None}.
    코덱은 수집하지 않는다(Gate가 읽는 정보에 없다). 메타데이터가 없으면 available=False.
    """
    out = {"available": False, "videos": 0, "fields": {}, "warn_margin": SHORTCUT_WARN_MARGIN, "warnings": [],
           "note": "코덱·비트레이트는 수집하지 않는다. 경고는 채택 판단에 쓰지 않는다."}
    rows = [(labels[u], m) for u, m in media.items() if u in labels and isinstance(m, dict)]
    if not rows:
        return out
    out.update(available=True, videos=len(rows))
    for name in SHORTCUT_FIELDS:
        fake = [float(m[name]) for label, m in rows if label == "fake" and m.get(name) is not None]
        real = [float(m[name]) for label, m in rows if label == "real" and m.get(name) is not None]
        auc = roc_auc(fake, real)
        out["fields"][name] = {"roc_auc": auc, "fake": len(fake), "real": len(real)}
        if auc is not None and abs(auc - 0.5) > SHORTCUT_WARN_MARGIN:
            out["warnings"].append(name)
    return out
