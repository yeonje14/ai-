"""python -m scripts.evidence_range_reserve_v2 · 기준 범위 예약 v2. 로컬 메타데이터만 읽는다.

v1(scripts/evidence_range_reserve.py)을 미디어를 열기 전에 대체한다. 사유: 역할 배분(2026-11-27 사용자 결정).
v1 목록(range_fit.csv, range_check.csv)은 지우지 않는다.

- 그룹 단위는 세션(쌍)이다. 두 참가자를 모두 쓴다. file_id_a/b 순서는 기존 A-select 규칙 그대로다.
- 기존 test·dev·pilot 예약의 양쪽 참가자·세션·대화·파일과 공식 dev/test 행(label 무관)에 닿는 쌍은 뺀다.
- 남은 train_candidate 대화를 기관별로 sha256(시드|range-v2|키) 순서로 보며, 이미 고른 참가자나 세션이
  있으면 건너뛴다(서로 독립인 쌍만 남는다).
- 기관마다 그 순서대로 range_fit : range_check = 5 : 3이 되게 번갈아 배정한다. k번째(0부터)까지의 fit 수는
  ceil(5(k+1)/8)이다(F F C F F C F C 반복).
- 역할 안 처리 순서(order)는 sha256(시드|order|역할|키) 순서다.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math

from scripts import seamless_reserve as sr
from scripts.evidence_range_reserve import INPUTS, identities

SEED = 20261127
RATIO = (("range_fit", 5), ("range_check", 3))
SUFFIX = "_v2"
# v1 산출물. 지우지 않고 대체 기록만 남긴다(계획 문서의 v1 해시와 같아야 한다).
V1_OUTPUTS = {
    "range_fit.csv": "6bdfd1f8455e3581f46553aed56a00426125c2fa9d4e1615a55435e2c124dd7c",
    "range_check.csv": "bf43a500f38daaeab73494e1b8bf5f45d06b6d41a68dea3f4b63e582eb608fc1",
}
SUPERSEDES = {"version": "v1", "basis": "메타데이터만 보고 대체", "reason": "역할 배분"}


def forbidden_identities(rows, previous):
    forbidden = set()
    for row in previous:
        for field in ("file_id_a", "file_id_b"):
            forbidden.update(identities(row[field]))
    for row in rows:
        if row["split"] in sr.HOLDOUT_SPLITS and sr.parse_file_id(row["file_id"]) is not None:
            forbidden.update(identities(row["file_id"]))
    return forbidden


def role_at(k, ratio=RATIO):
    """기관 안 k번째 쌍의 역할. 앞 역할의 누적 수가 ceil(비율×(k+1))을 따른다."""
    (first, a), (second, b) = ratio
    return first if math.ceil(a * (k + 1) / (a + b)) > math.ceil(a * k / (a + b)) else second


def select(rows, previous, assignment, seed=SEED, ratio=RATIO):
    forbidden = forbidden_identities(rows, previous)
    eligible = set()
    for row in assignment:
        ids = row["file_ids"].split()
        if row["role"] == "train_candidate" and not any(identities(f) & forbidden for f in ids):
            eligible.update(ids)
    pool = [r for r in rows if r["label"] == sr.LABEL and r["split"] == "train" and r["file_id"] in eligible]
    inter, _, _ = sr.build(pool)

    by_vendor = defaultdict(list)
    for it in inter.values():
        if len(it.file_ids) == 2 and len(set(it.pcodes)) == 2:
            by_vendor[it.vendor].append(it)
    picked = defaultdict(list)
    used = set()
    for vendor in sorted(by_vendor):
        k = 0
        for it in sorted(by_vendor[vendor], key=lambda it: sr._rank(seed, "range-v2", it.key)):
            keys = {("session", it.session_key)} | {("person", p) for p in it.pcodes}
            if keys & used:
                continue
            used |= keys
            picked[role_at(k, ratio)].append(it)
            k += 1

    selected = []
    for role, _ in ratio:
        ordered = sorted(picked[role], key=lambda it: sr._rank(seed, "order", role, it.key))
        for order, it in enumerate(ordered):
            a, b = sr.target_a(seed, it.key, it.file_ids)
            selected.append({"role": role, "order": order, "vendor": it.vendor, "interaction_key": it.key,
                             "file_id_a": a, "file_id_b": b})

    seen = set()
    for r in selected:
        group = identities(r["file_id_a"]) | identities(r["file_id_b"])
        if group & (forbidden | seen):
            raise ValueError("예약 누수")
        seen.update(group)
    return selected


def main():
    for path, expected in INPUTS.items():
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"입력 해시 불일치: {path.name}")
    v1 = {}
    for name, expected in V1_OUTPUTS.items():
        got = sha256((sr.DEFAULT_OUT / name).read_bytes()).hexdigest()
        if got != expected:
            raise ValueError(f"v1 목록이 기록과 다름: {name}")
        v1[name] = got
    rows, previous, assignment = (sr.load_rows(path) for path in INPUTS)
    selected = select(rows, previous, assignment)

    summary = {"seed": SEED, "ratio": dict(RATIO), "group_unit": "session", "people_per_group": 2,
               "supersedes": {**SUPERSEDES, "sha256": v1}, "roles": {}}
    for role, _ in RATIO:
        part = [r for r in selected if r["role"] == role]
        payload = sr.csv_bytes(part, sr.RESERVATION_COLUMNS)
        out = sr.DEFAULT_OUT / f"{role}{SUFFIX}.csv"
        if out.exists() and out.read_bytes() != payload:
            raise ValueError("다른 v2 예약 목록이 이미 존재함")
        out.write_bytes(payload)
        summary["roles"][role] = {"sessions": len(part), "people": 2 * len(part),
                                  "by_vendor": dict(sorted(Counter(r["vendor"] for r in part).items())),
                                  "sha256": sha256(payload).hexdigest()}
    summary["intersection_check"] = "passed"
    summary["script_sha256"] = sha256(open(__file__, "rb").read()).hexdigest()
    summary["inputs_sha256"] = {p.name: h for p, h in INPUTS.items()}
    (sr.DEFAULT_OUT / f"range{SUFFIX}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
