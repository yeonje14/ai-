"""외부 최종 평가 자료 잠금 (README §6.3, §6.4 "외부 평가 접근 제한", AGENTS.md).

configs/external_eval_lock.json에 등록된 데이터셋은 최종 평가 전용이다.
- 학습, OOF, 확률 보정, 임계값 결정, 내부 분할 배정에 쓸 수 없다.
- status가 "locked"인 동안에는 평가(추론 결과 집계)도 거부한다.
- 풀려면 이 파일의 status를 "unlocked"로 고쳐 커밋해야 한다. 기록이 Git에 남는다.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_LOCK_PATH = Path(__file__).resolve().parents[2] / "configs" / "external_eval_lock.json"
STATUSES = ("locked", "unlocked")


class ExternalEvalLocked(RuntimeError):
    """잠긴 외부 평가 자료를 쓰려고 했다."""


def load_lock(path: Path = DEFAULT_LOCK_PATH) -> dict[str, dict]:
    """{dataset_id: 항목}. 형식이 어긋나면 ValueError (조용히 '잠금 없음'으로 넘어가지 않는다)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    datasets = data.get("datasets")
    if not isinstance(datasets, dict):
        raise ValueError("lock 파일에 datasets가 없다")
    for name, entry in datasets.items():
        if not isinstance(entry, dict) or entry.get("status") not in STATUSES:
            raise ValueError(f"lock 항목 {name!r}의 status는 {STATUSES} 중 하나여야 한다")
    return datasets


def external_dataset_ids(lock: dict[str, dict]) -> set[str]:
    return set(lock)


def assert_unlocked(dataset_ids: set[str], lock: dict[str, dict]) -> None:
    """모든 데이터셋이 등록되어 있고 unlocked일 때만 통과한다."""
    unknown = sorted(dataset_ids - set(lock))
    if unknown:
        raise ExternalEvalLocked(f"lock 파일에 등록되지 않은 외부 데이터셋: {unknown}")
    locked = sorted(d for d in dataset_ids if lock[d]["status"] != "unlocked")
    if locked:
        raise ExternalEvalLocked(
            f"외부 최종 평가 자료가 잠겨 있다: {locked}. 모델과 임계값을 고정한 뒤 "
            "configs/external_eval_lock.json의 status를 고쳐 커밋해야 평가할 수 있다"
        )
