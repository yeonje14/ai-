"""인물·원본 계보 연결 그룹과 그룹 단위 분할 (README §6.4).

인물 ID, 원본 녹화 ID, 파생 계보 ID, 부모 영상 중 하나라도 공유하는 영상은 같은 그룹이다.
얼굴 교체처럼 인물이 여럿이면 identity_ids에 모두 적으므로 출처와 대상이 함께 이어진다.
분할은 그룹을 통째로 한 분할에 넣는다. 압축·증강은 분할을 정한 뒤에 한다.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Iterable, Mapping

from training.datasets.manifest import INTERNAL_SPLITS, Record


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # 경로 압축
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # 사전순으로 작은 쪽을 대표로 삼아 입력 순서와 무관하게 만든다
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def link_keys(rec: Record) -> list[str]:
    """이 영상을 다른 영상과 잇는 키. 종류별 접두사로 서로 섞이지 않게 한다."""
    keys = [f"vid\x1f{rec.uid}", f"src\x1f{rec.source_recording_id}"]
    keys += [f"id\x1f{i}" for i in rec.identity_ids]
    if rec.derivation_group_id:
        keys.append(f"der\x1f{rec.dataset_id}\x1f{rec.derivation_group_id}")
    if rec.parent_video_id:
        keys.append(f"vid\x1f{rec.dataset_id}:{rec.parent_video_id}")
    return keys


def group_ids(records: Iterable[Record]) -> dict[str, str]:
    """{uid: 그룹 ID}. 그룹 ID는 그룹에 속한 키 중 가장 작은 것의 해시라 입력 순서와 무관하다."""
    records = list(records)
    uf = _UnionFind()
    for rec in records:
        keys = link_keys(rec)
        for k in keys[1:]:
            uf.union(keys[0], k)
    members: dict[str, list[str]] = defaultdict(list)
    for key in list(uf.parent):
        members[uf.find(key)].append(key)
    name = {root: "g" + hashlib.sha256(min(keys).encode("utf-8")).hexdigest()[:16]
            for root, keys in members.items()}
    return {rec.uid: name[uf.find(f"vid\x1f{rec.uid}")] for rec in records}


def assign_splits(
    records: Iterable[Record],
    fractions: Mapping[str, float],
    seed: int,
) -> list[Record]:
    """split이 external이 아닌 영상을 그룹 단위로 train/dev/test에 배정한다.

    그룹을 sha256("<시드>:<그룹 ID>") 순서로 놓고, 영상 수 누적 비율로 경계를 나눈다.
    그룹을 쪼개지 않으므로 실제 비율은 목표와 조금 다를 수 있다.
    external 영상은 그대로 두지만, 그룹 계산에는 넣는다. external과 이어진 그룹이
    내부 분할에 들어가면 누수이므로 여기서 막지 않고 hygiene 검사에서 실패로 잡는다.
    """
    records = list(records)
    if set(fractions) - set(INTERNAL_SPLITS) or not fractions:
        raise ValueError(f"fractions의 키는 {INTERNAL_SPLITS} 중에서 고른다: {sorted(fractions)}")
    if any(v <= 0 for v in fractions.values()) or abs(sum(fractions.values()) - 1.0) > 1e-9:
        raise ValueError("fractions는 양수이고 합이 1이어야 한다")

    gid = group_ids(records)
    internal = [r for r in records if r.split != "external"]
    size: dict[str, int] = defaultdict(int)
    for r in internal:
        size[gid[r.uid]] += 1
    order = sorted(size, key=lambda g: hashlib.sha256(f"{seed}:{g}".encode("utf-8")).hexdigest())

    names = [s for s in INTERNAL_SPLITS if s in fractions]
    bounds, acc = [], 0.0
    for s in names:
        acc += fractions[s]
        bounds.append(acc)
    total = len(internal)
    split_of: dict[str, str] = {}
    seen = 0
    for g in order:
        mid = (seen + size[g] / 2) / total  # 그룹의 가운데가 놓인 누적 위치
        split_of[g] = next((s for s, b in zip(names, bounds) if mid < b), names[-1])
        seen += size[g]
    return [r if r.split == "external" else r.with_split(split_of[gid[r.uid]]) for r in records]
