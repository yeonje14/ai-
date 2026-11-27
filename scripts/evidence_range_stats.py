"""봉인된 25초 기준의 오프라인 통계. 실행은 python -m scripts.evidence_range_stats."""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, median

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import evidence_range_run as run

SEED = 20261127
REPLICATES = 2000
BOUNDARY = 97.5
MIN_FIT, MIN_CHECK = 50, 30
MAX_FPR = 0.05
SIGNALS = ("waverep", "syncnet")


def measurements(result):
    """Gate 구간에서 성공한 트랙과 시간 대응이 기록된 프레임만 집계한다."""
    gate = {(s["start_sec"], s["end_sec"]) for s in
            (result.get("gate") or {}).get("eligible_segments", [])}
    sync = (result.get("axis_raw") or {}).get("syncnet") or {}
    values = {}
    for row in sync.get("segments") or []:
        bounds = row["start_sec"], row["end_sec"]
        if bounds not in gate or row.get("status") != "completed" or sync.get("offset_fps") != 25:
            continue
        offsets = [t.get("offset_frames") for t in row.get("tracks") or []]
        if offsets and all(type(x) is int for x in offsets):
            values[bounds] = median(abs(x) for x in offsets) / 25
    wave = (result.get("axis_raw") or {}).get("waverep") or {}
    frames = wave.get("frames") or []
    wave_values = {}
    if wave.get("status") == "completed" and frames and all(
        type(frame.get(key)) in (int, float) and math.isfinite(frame[key])
        for frame in frames for key in ("clip_pts_sec", "logit")
    ):
        for start, end in gate:
            logits = [f["logit"] for f in frames if start <= f["clip_pts_sec"] < end]
            if logits:
                wave_values[start, end] = median(logits)
    return {"syncnet": values, "waverep": wave_values}


def read_sessions(root, role, rows):
    sessions = []
    passed = 0
    stopped = False
    warnings = []
    institutions = {}
    mapping = {"mapped": 0, "unverified": 0}
    gate_by_condition = {c: {"observed": 0, "passed": 0} for c in run.CONDITIONS}
    for row in rows:
        order = int(row["order"])
        directory = run.session_dir(root, role, order)
        state = run.read_json(directory / "state.json").get("analyze") or {}
        if state.get("status") not in (run.DONE, run.SKIPPED):
            stopped = True
            continue
        if stopped or passed >= run.TARGETS[role]:
            warnings.append(order)
            continue
        values = defaultdict(dict)
        gate_flags = defaultdict(list)
        if state["status"] == run.DONE:
            if type(state.get("session_passed")) is not bool:
                raise ValueError(f"{role}/{order}: session_passed 확인 필요")
            passed += state["session_passed"]
            for who, person in state["people"].items():
                if who not in run.WHO or person.get("status") != "measured":
                    continue
                for condition in run.CONDITIONS:
                    result = run.read_json(directory / "results" / f"{who}.{condition}.json")
                    if isinstance(result.get("gate"), dict):
                        gate_flags[condition].append(run.gate_passed(result))
                    signals = measurements(result)
                    wave = (result.get("axis_raw") or {}).get("waverep") or {}
                    if wave.get("status") == "completed":
                        mapping["mapped" if signals["waverep"] else "unverified"] += 1
                    for signal, segments in signals.items():
                        values[condition, signal].update({(who, *k): v for k, v in segments.items()})
        for condition, flags in gate_flags.items():
            gate_by_condition[condition]["observed"] += 1
            gate_by_condition[condition]["passed"] += any(flags)
        counts = institutions.setdefault(row["vendor"], dict(processed=0, passed=0))
        counts["processed"] += 1
        counts["passed"] += bool(state.get("session_passed"))
        sessions.append((row["vendor"], values))
    return sessions, dict(reserved=len(rows), processed=len(sessions), passed=passed,
                          target=run.TARGETS[role], waverep_mapping_counts=mapping, institutions=institutions, gate_by_condition=gate_by_condition,
                          excluded_after_stop_orders=warnings)


def bootstrap_weights(vendors):
    """하나의 가중치 행은 한 복제 표본. 모든 조건과 신호에 같은 행을 적용한다."""
    rng = np.random.default_rng(SEED)
    weights = np.zeros((REPLICATES, len(vendors)), dtype=int)
    for vendor in sorted(set(vendors)):
        indices = np.flatnonzero(np.array(vendors) == vendor)
        weights[:, indices] = rng.multinomial(len(indices), np.full(len(indices), 1 / len(indices)),
                                              size=REPLICATES)
    return weights


def classify(x, threshold, low, high):
    if x > threshold and low >= BOUNDARY:
        return "rare"
    if high < BOUNDARY:
        return "within_range"
    return "abstained"


class Reference:
    def __init__(self, maxima, weights):
        valid = np.flatnonzero(np.isfinite(maxima))
        indices = valid[np.argsort(np.asarray(maxima)[valid])]
        self.values = np.asarray(maxima)[indices]
        rank = (975 * (len(valid) + 1) + 999) // 1000
        self.threshold = float(self.values[rank - 1]) if rank <= len(valid) else None
        self.counts = np.pad(weights[:, indices].cumsum(axis=1), ((0, 0), (1, 0)))

    def compare(self, x):
        left, right = self.values.searchsorted(x), self.values.searchsorted(x, side="right")
        if not len(self.values):
            return dict(percentile=None, percentile_ci95=None, status="abstained")
        p = 50 * (left + right) / len(self.values)
        total = self.counts[:, -1]
        if self.threshold is None or not np.all(total):
            return dict(percentile=p, percentile_ci95=None, status="abstained")
        samples = 50 * (self.counts[:, left] + self.counts[:, right]) / total
        low, high = np.percentile(samples, [2.5, 97.5])
        return dict(percentile=p, percentile_ci95=[low, high],
                    status=classify(x, self.threshold, low, high))


def rate(ratios, n_sessions):
    n = len(ratios)
    numerator = math.fsum(ratios)
    p = numerator / n if n else None
    ci = None
    if n:
        z = NormalDist().inv_cdf(0.975)
        center = p + z*z/(2*n)
        width = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
        scale = 1 + z*z/n
        ci = [max(0, (center-width)/scale), min(1, (center+width)/scale)]
    return dict(numerator=numerator, denominator=n, estimate=p, wilson95=ci, missing=n_sessions-n)


def compute(fit, check):
    weights = bootstrap_weights([v for v, _ in fit])
    output = {}
    labels = {}
    for condition in run.CONDITIONS:
        signals = {}
        for signal in SIGNALS:
            key = condition, signal
            maxima = [max(values.get(key, {}).values(), default=np.nan) for _, values in fit]
            ref = Reference(maxima, weights)
            n = len(ref.values)
            ncheck = sum(bool(values.get(key)) for _, values in check)
            publish = n >= MIN_FIT and ncheck >= MIN_CHECK and ref.threshold is not None
            by_vendor = {}
            for role, samples in (("range_fit", fit), ("range_check", check)):
                for vendor, values in samples:
                    counts = by_vendor.setdefault(vendor, {}).setdefault(role, {"total": 0, "measured": 0})
                    counts["total"] += 1
                    counts["measured"] += bool(values.get(key))
            signals[signal] = dict(by_vendor=by_vendor, n_fit=n, n_check=ncheck, missing_fit=len(fit)-n,
                                   missing_check=len(check)-ncheck, upper_reference_value=ref.threshold,
                                   session_maxima=ref.values.tolist(),
                                   status="eligible" if publish else "not_published")
            cache = {}
            observations = []
            if publish:
                for i, (_, values) in enumerate(check):
                    for segment, value in values.get(key, {}).items():
                        if value not in cache:
                            cache[value] = ref.compare(value)
                        comparison = cache[value]

                        observation = dict(session=i, person=segment[0], start_sec=segment[1],
                                           end_sec=segment[2], value=value, **comparison)
                        observations.append(observation)
                        labels[i, condition, segment, signal] = observation
            signals[signal]["comparisons"] = observations
        output[condition] = dict(signals=signals)

    # 같은 사람의 두 조건 중 공통 Gate 시간에서만 표시 판정을 검증한다.
    marginal = {}
    for condition, other in (run.CONDITIONS, run.CONDITIONS[::-1]):
        marginal[condition] = {}
        fractions, events = [], []
        for i, (_, values) in enumerate(check):
            flags = {}
            condition_labels = []
            for signal in SIGNALS:
                for segment in values.get((condition, signal), {}):
                    label = labels.get((i, condition, segment, signal))
                    if label is None:
                        continue
                    condition_labels.append(label["status"])
                    who, start, end = segment
                    # 다른 조건의 같은 사람·시간에 같은 신호가 있을 때만 화면 비교 가능.
                    peers = [labels.get((i, other, peer, signal))
                             for peer in values.get((other, signal), {})
                             if peer[0] == who and max(start, peer[1]) < min(end, peer[2])]
                    peer_status = {p["status"] for p in peers if p is not None}
                    agrees = peer_status == {label["status"]}
                    display = label["status"] if agrees else "abstained"
                    label["display_status"] = display
                    if peer_status:
                        flags[segment] = flags.get(segment, False) or display == "rare"
            if condition_labels:
                marginal[condition][i] = "rare" in condition_labels
            if flags:
                fractions.append(sum(flags.values()) / len(flags))
                events.append(any(flags.values()))
        combined = rate(events, len(check))
        output[condition].update(mean_session_segment_rate=rate(fractions, len(check)),
                                 any_rare_session_rate=combined)
        for row in output[condition]["signals"].values():
            if row["status"] == "eligible":
                if not events:
                    row["status"] = "not_published"
                elif combined["estimate"] > MAX_FPR:
                    row["status"] = "release_blocked"
                else:
                    row["status"] = "published"
    original, compressed = run.CONDITIONS
    paired = sorted(marginal[original].keys() & marginal[compressed].keys())
    changes = [int(marginal[compressed][i]) - int(marginal[original][i]) for i in paired]
    for condition in run.CONDITIONS:
        output[condition]["condition_only_session_rate"] = rate(list(marginal[condition].values()), len(check))
    output[compressed]["paired_session_rate_difference_from_original"] = {
        "n_sessions": len(paired), "difference": sum(changes) / len(changes) if changes else None}
    for signal in SIGNALS:
        a, b = (output[c]["signals"][signal]["upper_reference_value"] for c in run.CONDITIONS)
        output[compressed]["signals"][signal]["boundary_difference_from_original"] = (
            b - a if a is not None and b is not None else None)
    return output


def generate(root, rows):
    seal = run.read_json(root / "reference_version.json")
    hashes = {role: run.RANGE_LISTS[role][1] for role in run.ROLES}
    if not seal.get("gate_version") or seal.get("reservation_sha256") != hashes or seal.get("targets") != run.TARGETS:
        raise ValueError("Gate 봉인·예약 해시·정지 규칙 확인 필요")
    samples, stops = {}, {}
    for role in run.ROLES:
        samples[role], stops[role] = read_sessions(root, role, rows[role])
    version = {k: seal.get(k) for k in ("gate_version", "reservation_sha256", "runner_sha256", "preprocess_rule")}
    version.update(seed=SEED, replicates=REPLICATES, conditions=run.CONDITIONS, rules="range-v2.1",
                   targets=run.TARGETS, window_sec=25, upper_percentile=BOUNDARY,
                   min_fit=MIN_FIT, min_check=MIN_CHECK, max_session_fpr=MAX_FPR,
                   signals=SIGNALS, stats_sha256=run.sha256_file(Path(__file__)))
    mapped = sum(s["waverep_mapping_counts"]["mapped"] for s in stops.values())
    unverified = sum(s["waverep_mapping_counts"]["unverified"] for s in stops.values())
    mapping_status = "대응 미검증(보류)"
    if mapped:
        mapping_status = "일부 대응 미검증(보류)" if unverified else "프레임 PTS 대응"
    report = dict(reference_version=version, stopping=stops, waverep_mapping=mapping_status,
                  conditions=compute(samples["range_fit"], samples["range_check"]))
    incomplete = any(s["passed"] < s["target"] and s["processed"] < s["reserved"] for s in stops.values())
    report["analysis_prefix_complete"] = not incomplete
    if incomplete:
        for condition in report["conditions"].values():
            for row in condition["signals"].values():
                row["status"] = "not_published"
    dest = root / "stats"
    run.write_json(dest / "stats.json", report)
    lines = ["# 25초 구간 기준 검증", "", f"Gate {version['gate_version']} · 시드 {SEED}",
             "", f"WaveRep 시간 대응 · {mapping_status}", ""]
    for role, stop in stops.items():
        lines.append(f"- {role} 예약 {stop['reserved']}, 처리 {stop['processed']}, 원본 통과 {stop['passed']}")
        if stop["excluded_after_stop_orders"]:
            warning = f"경고 · {role} 정지 이후 처리되어 제외한 순번 {stop['excluded_after_stop_orders']}"
            lines.append(f"- {warning}")
            print(warning, file=sys.stderr)
    for cond, result in report["conditions"].items():
        lines.extend(["", f"## {cond}", ""])
        for sig, row in result["signals"].items():
            lines.append(f"- {sig} 기준 {row['n_fit']} / 검증 {row['n_check']}세션 · {row['status']}")
        for k, title in (("mean_session_segment_rate", "세션별 구간 오탐 비율의 평균"),
                         ("any_rare_session_rate", "한 구간 이상 드문 세션 비율")):
            r = result[k]
            interval = r["wilson95"]
            ci = f"{interval[0]:.1%}–{interval[1]:.1%}" if interval else "계산 불가"
            lines.append(f"- {title} {r['numerator']:g}/{r['denominator']} · Wilson 95% {ci} · 결측 {r['missing']}")
    lines.extend(["", "구간 오탐 비율의 분자는 세션별 비율의 합이다. 이 지표의 Wilson 구간은",
                  "세션 수를 유효 표본 수로 대입한 근사치다. 한 구간 이상 드문 세션 비율은 이항 Wilson 구간이다."])
    (dest / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    generate(run.RANGE_DIR, {role: run.load_role(role) for role in run.ROLES})
