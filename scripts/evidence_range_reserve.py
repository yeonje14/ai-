"""python -m scripts.evidence_range_reserve · 로컬 메타데이터만 읽는다."""
from collections import Counter
from hashlib import sha256
from pathlib import Path

from scripts import seamless_reserve as sr

SEED = 20261127
ROLES = (("range_fit", 500), ("range_check", 300))
INPUTS = {
    sr.DEFAULT_FILELIST: "e8ecdfd690286502193489b638208b70d1834dc3e25e2145050618e14dd568dc",
    sr.DEFAULT_OUT / "reservation.csv": "2cd2ddc8ff89e85abf03c3ea2a1b84f0b03119d16bc02e01203d180dbf6538c0",
    sr.DEFAULT_OUT / "assignment.csv": "af08c93fa9673ec81cd5f5ecb0311a5bfe57965b718b6367225b5517f056bca5",
}


def identities(file_id):
    p = sr.parse_file_id(file_id)
    if p is None:
        raise ValueError("알 수 없는 파일 ID")
    return {("person", p.pcode), ("session", p.vendor, p.session),
            ("interaction", p.vendor, p.session, p.interaction), ("file", file_id)}


def select(rows, previous, assignment, roles=ROLES):
    forbidden = set()
    for row in previous:
        for field in ("file_id_a", "file_id_b"):
            forbidden.update(identities(row[field]))
    for row in rows:
        if row["split"] in sr.HOLDOUT_SPLITS:
            forbidden.update(identities(row["file_id"]))
    eligible = set()
    for row in assignment:
        ids = row["file_ids"].split()
        if row["role"] == "train_candidate" and not any(identities(f) & forbidden for f in ids):
            eligible.update(ids)
    pool = [r for r in rows if r["label"] == sr.LABEL and r["split"] == "train" and r["file_id"] in eligible]
    selected = sr.reserve(pool, seed=SEED, roles=roles)["reservation"]
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
    selected = select(*(sr.load_rows(path) for path in INPUTS))
    for role, _ in ROLES:
        rows = [r for r in selected if r["role"] == role]
        payload = sr.csv_bytes(rows, sr.RESERVATION_COLUMNS)
        out = sr.DEFAULT_OUT / f"{role}.csv"
        if out.exists() and out.read_bytes() != payload:
            raise ValueError("다른 예약 목록이 이미 존재함")
        out.write_bytes(payload)
        print(role, sorted(Counter(r["vendor"] for r in rows).items()), sha256(payload).hexdigest())
    print("교집합 검사 통과")


if __name__ == "__main__":
    main()
