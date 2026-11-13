"""임계값 고정 (README §13.3 숫자 사용 규칙, AGENTS.md "데이터와 평가 규칙").

임계값은 dev 분할에서만 정하고 파일로 고정한다. test나 external로는 정할 수 없고,
한 번 쓴 파일은 덮어쓸 수 없으며, 내용이 바뀌면 불러올 때 거부한다.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

from training.evaluation.metrics import Item, rate_at, threshold_at_fpr

SCHEMA_VERSION = 1
SOURCE_SPLIT = "dev"
DEFAULT_TARGET_FPR = 0.05


class ThresholdError(RuntimeError):
    """임계값을 정하거나 불러올 수 없다."""


def _digest(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fit_threshold(
    items: Sequence[Item],
    splits: Sequence[str],
    *,
    model_id: str,
    manifest_sha256: str,
    scores_sha256: str,
    target_fpr: float = DEFAULT_TARGET_FPR,
) -> dict:
    """dev 영상의 점수로 임계값을 정한다.

    splits는 items와 같은 순서의 분할 이름이다. dev가 아닌 영상이 하나라도 있으면 거부한다.
    호출자가 걸러서 넘기는 것에 기대지 않고 여기서 다시 확인한다.
    """
    if len(items) != len(splits):
        raise ValueError("items와 splits의 길이가 다르다")
    foreign = sorted({s for s in splits if s != SOURCE_SPLIT})
    if foreign:
        raise ThresholdError(f"임계값은 {SOURCE_SPLIT} 분할에서만 정한다. 섞여 있는 분할: {foreign}")
    if not model_id:
        raise ThresholdError("model_id가 필요하다")
    real = [it.score for it in items if it.label == "real" and it.score is not None]
    fake = [it.score for it in items if it.label == "fake" and it.score is not None]
    if not real:
        raise ThresholdError("dev에 점수가 있는 진짜 영상이 없다")
    threshold = threshold_at_fpr(real, target_fpr)
    body = {
        "schema_version": SCHEMA_VERSION,
        "model_id": model_id,
        "rule": "score >= threshold → fake",
        "threshold": threshold,
        "target_fpr": target_fpr,
        "source_split": SOURCE_SPLIT,
        "dev_fpr": rate_at(real, threshold),
        "dev_tpr": rate_at(fake, threshold),
        "dev_real_scored": len(real),
        "dev_fake_scored": len(fake),
        "dev_videos": len(items),
        "dev_groups": len({it.group for it in items}),
        "dev_manifest_sha256": manifest_sha256,
        "dev_scores_sha256": scores_sha256,
    }
    return {**body, "digest": _digest(body)}


def save_threshold(path: Path, threshold: dict) -> None:
    """새 파일로만 쓴다. 이미 있으면 거부한다(다시 정하려면 다른 이름으로, 기록이 남게)."""
    path = Path(path)
    verify(threshold)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as e:
        raise ThresholdError(f"임계값 파일이 이미 있다. 덮어쓰지 않는다: {path}") from e
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(threshold, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def verify(threshold: dict) -> dict:
    """형식과 digest를 확인한다. 어긋나면 ThresholdError."""
    if not isinstance(threshold, dict) or "digest" not in threshold:
        raise ThresholdError("임계값 파일 형식 오류")
    body = {k: v for k, v in threshold.items() if k != "digest"}
    if _digest(body) != threshold["digest"]:
        raise ThresholdError("임계값 파일의 내용이 고정한 뒤에 바뀌었다(digest 불일치)")
    if body.get("source_split") != SOURCE_SPLIT:
        raise ThresholdError(f"{SOURCE_SPLIT}에서 정한 임계값이 아니다")
    if not isinstance(body.get("threshold"), float):
        raise ThresholdError("threshold 값이 없다")
    return threshold


def load_threshold(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ThresholdError(f"임계값 파일을 읽을 수 없다: {path}") from e
    return verify(data)
