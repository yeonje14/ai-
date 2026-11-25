"""Seamless Interaction naturalistic 공식 train에서 내부 test·dev·파일럿 쌍을 미리 예약한다.

계획: docs/seamless-pilot-plan.md §2. 규칙과 결과 해시: docs/seamless-reservation.md.
이 스크립트는 공식 filelist.csv(메타데이터)만 읽는다. 미디어를 받지 않고 모델을 돌리지 않는다.
표준 라이브러리만 쓴다.

사용 (저장소 루트, conda trinity):
    python scripts/seamless_reserve.py
        # 입력: data/research/seamless/src/seamless_interaction/assets/filelist.csv
        # 출력: data/research/seamless/reservation/ (Git 제외)

규칙 요약 (2026-11-25 사용자 승인):
- 참가자 신원 키는 P 숫자 코드다. 기관(V)과 접미사(A 등)를 무시해 보수적으로 묶는다.
- 예약 후보는 naturalistic 공식 train interaction 중 다음을 모두 만족하는 것이다:
  파일 2개, 서로 다른 참가자, 접미사 없는 ID, 두 참가자 코드가 공식 dev·test 행(label 무관)에 없음,
  두 참가자 코드가 한 기관에서만 나타남.
- 역할 순서 test → dev → pilot. 역할마다 목표 수를 최초 후보의 기관별 비율로 최대 잔여법 배분한다
  (나머지가 같으면 기관 번호 순). 기관 안에서는 sha256(시드|역할|키) 순서로 보며, 이미 어느 역할에 쓰인
  참가자나 세션이 있으면 건너뛴다. 부족하면 다른 기관으로 넘기지 않고 부족분을 보고한다.
- 얼굴 대상 A는 sha256(시드|A-select|키)의 짝홀로 정한다(짝수: 사전순 앞 파일 ID).
- 역할 안 순번(order)은 sha256(시드|order|역할|키) 순서다. 파일럿 0번이 첫 쌍이다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILELIST = REPO_ROOT / "data/research/seamless/src/seamless_interaction/assets/filelist.csv"
DEFAULT_OUT = REPO_ROOT / "data/research/seamless/reservation"

SEED = 20261125
# 계획서에 적은 공식 인덱스 기준(git blob sha1). 다르면 멈춘다.
EXPECTED_FILELIST_BLOB = "e759e6d00f152a4833df2b985de842ab642812cd"
LABEL = "naturalistic"
SOURCE_SPLIT = "train"
HOLDOUT_SPLITS = ("dev", "test")
ROLES = (("test", 200), ("dev", 100), ("pilot", 10))
ROLE_ORDER = {name: i for i, (name, _) in enumerate(ROLES)}

FILE_ID_RE = re.compile(r"^V(\d+)_S(\d+)_I(\d+)_P(\d+)([A-Za-z]*)$")

# 제외 사유 (검사 순서)
R_MALFORMED = "malformed_file_id"
R_SPLIT_MIXED = "split_mixed"
R_FILE_COUNT = "file_count_not_2"
R_SAME_PARTICIPANT = "same_participant_twice"
R_SUFFIX = "participant_suffix_id"
R_OFFICIAL_OVERLAP = "pcode_in_official_dev_test"
R_MULTI_VENDOR = "pcode_multi_vendor"
REASONS = (R_MALFORMED, R_SPLIT_MIXED, R_FILE_COUNT, R_SAME_PARTICIPANT, R_SUFFIX, R_OFFICIAL_OVERLAP,
           R_MULTI_VENDOR)


@dataclass(frozen=True)
class ParsedId:
    vendor: str
    session: str
    interaction: str
    pcode: str          # 신원 키: 앞의 0을 뗀 숫자 문자열
    suffix: str


def parse_file_id(file_id: str) -> ParsedId | None:
    m = FILE_ID_RE.match(file_id)
    if m is None:
        return None
    v, s, i, p, suf = m.groups()
    return ParsedId(vendor=v, session=s, interaction=i, pcode=str(int(p)), suffix=suf)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _rank(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


@dataclass
class Interaction:
    key: str                      # V.._S.._I..
    vendor: str
    session_key: str              # V.._S..
    file_ids: list[str]
    splits: set[str]
    pcodes: list[str]
    suffixes: list[str]
    reasons: list[str] = field(default_factory=list)


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build(rows: list[dict]) -> tuple[dict[str, Interaction], list[str], dict]:
    """naturalistic interaction 목록, 형식 오류 ID, 신원 대조용 집합을 만든다."""
    malformed: list[str] = []
    pcode_vendors: dict[str, set[str]] = defaultdict(set)
    holdout_pcodes: set[str] = set()
    for r in rows:
        p = parse_file_id(r["file_id"])
        if p is None:
            malformed.append(r["file_id"])
            continue
        pcode_vendors[p.pcode].add(p.vendor)
        if r["split"] in HOLDOUT_SPLITS:
            holdout_pcodes.add(p.pcode)

    inter: dict[str, Interaction] = {}
    for r in rows:
        if r["label"] != LABEL:
            continue
        p = parse_file_id(r["file_id"])
        if p is None:
            continue
        key = f"V{p.vendor}_S{p.session}_I{p.interaction}"
        it = inter.get(key)
        if it is None:
            it = inter[key] = Interaction(key=key, vendor=p.vendor, session_key=f"V{p.vendor}_S{p.session}",
                                          file_ids=[], splits=set(), pcodes=[], suffixes=[])
        it.file_ids.append(r["file_id"])
        it.splits.add(r["split"])
        it.pcodes.append(p.pcode)
        it.suffixes.append(p.suffix)
    for it in inter.values():
        it.file_ids.sort()
    lookups = {"pcode_vendors": pcode_vendors, "holdout_pcodes": holdout_pcodes}
    return inter, malformed, lookups


def exclusion_reasons(it: Interaction, lookups: dict) -> list[str]:
    reasons = []
    if len(it.splits) != 1:
        reasons.append(R_SPLIT_MIXED)
    if len(it.file_ids) != 2:
        reasons.append(R_FILE_COUNT)
    if len(set(it.pcodes)) != len(it.pcodes):
        reasons.append(R_SAME_PARTICIPANT)
    if any(it.suffixes):
        reasons.append(R_SUFFIX)
    if any(p in lookups["holdout_pcodes"] for p in it.pcodes):
        reasons.append(R_OFFICIAL_OVERLAP)
    if any(len(lookups["pcode_vendors"][p]) > 1 for p in it.pcodes):
        reasons.append(R_MULTI_VENDOR)
    return reasons


def allocate(target: int, counts: dict[str, int]) -> dict[str, int]:
    """최대 잔여법. 나머지가 같으면 기관 번호 순."""
    total = sum(counts.values())
    if total == 0:
        return {v: 0 for v in counts}
    exact = {v: target * n / total for v, n in counts.items()}
    quota = {v: int(x) for v, x in exact.items()}
    left = target - sum(quota.values())
    for v in sorted(counts, key=lambda v: (-(exact[v] - quota[v]), v))[:left]:
        quota[v] += 1
    return quota


def target_a(seed: int, key: str, file_ids: list[str]) -> tuple[str, str]:
    a_first = int(_rank(seed, "A-select", key), 16) % 2 == 0
    a, b = sorted(file_ids)
    return (a, b) if a_first else (b, a)


def reserve(rows: list[dict], seed: int = SEED, roles=ROLES) -> dict:
    inter, malformed, lookups = build(rows)
    train = {k: it for k, it in inter.items() if SOURCE_SPLIT in it.splits}
    for it in train.values():
        it.reasons = exclusion_reasons(it, lookups)
    candidates = {k: it for k, it in train.items() if not it.reasons}

    by_vendor: dict[str, list[Interaction]] = defaultdict(list)
    for it in candidates.values():
        by_vendor[it.vendor].append(it)
    pool_counts = {v: len(lst) for v, lst in sorted(by_vendor.items())}

    used_pcodes: set[str] = set()
    used_sessions: set[str] = set()
    picked: dict[str, list[Interaction]] = {}
    quotas: dict[str, dict[str, int]] = {}
    shortfall: dict[str, dict[str, int]] = {}
    for role, target in roles:
        quota = allocate(target, pool_counts)
        quotas[role] = quota
        got: list[Interaction] = []
        short = {}
        for v in sorted(by_vendor):
            need = quota[v]
            n = 0
            for it in sorted(by_vendor[v], key=lambda it: _rank(seed, role, it.key)):
                if n >= need:
                    break
                if it.session_key in used_sessions or any(p in used_pcodes for p in it.pcodes):
                    continue
                got.append(it)
                used_sessions.add(it.session_key)
                used_pcodes.update(it.pcodes)
                n += 1
            if n < need:
                short[v] = need - n
        got.sort(key=lambda it: _rank(seed, "order", role, it.key))
        picked[role] = got
        shortfall[role] = short

    role_of = {it.key: role for role, lst in picked.items() for it in lst}
    assignment = []
    for key in sorted(inter):
        it = inter[key]
        if key in role_of:
            role, reason = role_of[key], ""
        elif it.splits & set(HOLDOUT_SPLITS) and len(it.splits) == 1:
            role, reason = f"official_{next(iter(it.splits))}", ""
        elif it.session_key in used_sessions or any(p in used_pcodes for p in it.pcodes):
            # 예약 인물과 닿으면 제외 사유가 있어도 격리로 먼저 표시한다(이후 학습 manifest의 누수 방지)
            role, reason = "quarantined_linked", ";".join(it.reasons)
        elif it.reasons:
            role, reason = "excluded", ";".join(it.reasons)
        else:
            role, reason = "train_candidate", ""
        assignment.append({"interaction_key": key, "vendor": it.vendor, "role": role, "reason": reason,
                           "file_ids": " ".join(it.file_ids), "splits": " ".join(sorted(it.splits))})

    reservation = []
    for role, _ in roles:
        for order, it in enumerate(picked[role]):
            a, b = target_a(seed, it.key, it.file_ids)
            reservation.append({"role": role, "order": order, "vendor": it.vendor, "interaction_key": it.key,
                                "file_id_a": a, "file_id_b": b})

    # 정보용: 남은 학습 후보의 참가자 연결 성분 수(세션은 한 참가자 쌍만 가지므로 참가자로 충분하다)
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    train_pcodes = set()
    for row in assignment:
        if row["role"] == "train_candidate":
            p1, p2 = inter[row["interaction_key"]].pcodes
            train_pcodes.update((p1, p2))
            parent[find(p1)] = find(p2)
    components = len({find(p) for p in train_pcodes})

    # 예약 인물이 나오는 다른 label(improvised) 행. 이후 어떤 학습에도 넣지 않아야 한다.
    other_label_rows = Counter()
    for r in rows:
        p = parse_file_id(r["file_id"])
        if p is not None and r["label"] != LABEL and p.pcode in used_pcodes:
            other_label_rows[r["split"]] += 1

    reason_counts = Counter()
    for it in train.values():
        for r in it.reasons:
            reason_counts[r] += 1
    role_counts = Counter(row["role"] for row in assignment)
    role_vendor = defaultdict(dict)
    for role, lst in picked.items():
        c = Counter(it.vendor for it in lst)
        role_vendor[role] = {v: c.get(v, 0) for v in pool_counts}
    summary = {
        "seed": seed,
        "label": LABEL,
        "source_split": SOURCE_SPLIT,
        "rows_total": len(rows),
        "malformed_file_ids": len(malformed),
        "naturalistic_interactions": len(inter),
        "official_train_interactions": len(train),
        "official_train_interactions_by_vendor": dict(sorted(Counter(it.vendor for it in train.values()).items())),
        "excluded_train_interactions": sum(1 for it in train.values() if it.reasons),
        "exclusion_reason_counts": {r: reason_counts.get(r, 0) for r in REASONS if r != R_MALFORMED},
        "eligible_candidates_by_vendor": pool_counts,
        "eligible_candidates": sum(pool_counts.values()),
        "roles": {role: {"target": target, "reserved": len(picked[role]), "quota_by_vendor": quotas[role],
                         "reserved_by_vendor": role_vendor[role], "shortfall_by_vendor": shortfall[role]}
                  for role, target in roles},
        "assignment_role_counts": dict(sorted(role_counts.items())),
        "reserved_participants": len(used_pcodes),
        "other_label_rows_with_reserved_participants": dict(sorted(other_label_rows.items())),
        "train_candidate_participants": len(train_pcodes),
        "train_candidate_participant_components": components,
    }
    return {"reservation": reservation, "assignment": assignment, "summary": summary}


def csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r[c] for c in columns})
    return buf.getvalue().encode("utf-8")


RESERVATION_COLUMNS = ["role", "order", "vendor", "interaction_key", "file_id_a", "file_id_b"]
ASSIGNMENT_COLUMNS = ["interaction_key", "vendor", "role", "reason", "file_ids", "splits"]


def sorted_reservation(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (ROLE_ORDER[r["role"]], r["order"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filelist", type=Path, default=DEFAULT_FILELIST)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    opt = ap.parse_args(argv)

    data = opt.filelist.read_bytes()
    blob = git_blob_sha1(data)
    if blob != EXPECTED_FILELIST_BLOB:
        print(f"filelist blob {blob} != 기준 {EXPECTED_FILELIST_BLOB}. 멈춘다.", file=sys.stderr)
        return 2
    result = reserve(load_rows(opt.filelist))
    res_bytes = csv_bytes(sorted_reservation(result["reservation"]), RESERVATION_COLUMNS)
    asg_bytes = csv_bytes(result["assignment"], ASSIGNMENT_COLUMNS)

    opt.out.mkdir(parents=True, exist_ok=True)
    (opt.out / "reservation.csv").write_bytes(res_bytes)
    (opt.out / "assignment.csv").write_bytes(asg_bytes)
    summary = {
        **result["summary"],
        "source": {"filelist_git_blob": blob, "filelist_sha256": hashlib.sha256(data).hexdigest()},
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reservation_csv_sha256": hashlib.sha256(res_bytes).hexdigest(),
        "assignment_csv_sha256": hashlib.sha256(asg_bytes).hexdigest(),
    }
    (opt.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
