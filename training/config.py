"""학습·채택 판단 설정 읽기. 표준 라이브러리만 쓴다.

모르는 키는 거부한다. 임계값을 정하는 분할을 바꾸는 키(threshold_split 등)는 존재하지 않으며,
넣으면 여기서 실패한다. 임계값은 dev에서만 정한다(training/evaluation/thresholds.py가 다시 확인한다).
dev 압축 조건은 기본값이 없다. 적지 않으면 학습을 시작하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "configs" / "training.json"
KEYS = {"schema_version", "_comment", "dev_compression_conditions", "max_group_share", "n_folds", "fold_seed",
        "target_fpr", "waverep_score", "lightgbm", "logistic", "adoption"}
ADOPTION_KEYS = {"g2_min_auc_ci_low", "min_tpr_gain_ci_low", "max_fpr_worsening", "max_coverage_drop",
                 "max_test_fpr_ci_high", "n_boot", "bootstrap_seed", "confidence"}
WAVEREP_SCORES = ("logit_median", "logit_mean", "logit_q75")
ORIGINAL = "original"


class ConfigError(ValueError):
    pass


def validate(config: dict) -> dict:
    unknown = sorted(set(config) - KEYS)
    if unknown:
        raise ConfigError(f"모르는 설정 키: {unknown}. 임계값 분할이나 test 기반 조정은 설정할 수 없다")
    missing = sorted(KEYS - {"_comment"} - set(config))
    if missing:
        raise ConfigError(f"설정에 없는 키: {missing}")
    dev = config["dev_compression_conditions"]
    if not isinstance(dev, list) or not dev or not all(isinstance(c, str) and c for c in dev):
        raise ConfigError(
            "dev_compression_conditions를 명시해야 한다(기본값 없음). "
            f"임계값과 후보 선택에 쓸 dev 압축 조건의 목록이다. 원본은 {ORIGINAL!r}로 적는다")
    if len(set(dev)) != len(dev):
        raise ConfigError("dev_compression_conditions에 같은 조건이 두 번 있다")
    if not 0 < config["max_group_share"] <= 1:
        raise ConfigError("max_group_share는 0 초과 1 이하")
    if not isinstance(config["n_folds"], int) or config["n_folds"] < 2:
        raise ConfigError("n_folds는 2 이상의 정수")
    if not 0 < config["target_fpr"] < 1:
        raise ConfigError("target_fpr은 0과 1 사이")
    if config["waverep_score"] not in WAVEREP_SCORES:
        raise ConfigError(f"waverep_score는 {WAVEREP_SCORES} 중 하나")
    adoption = config["adoption"]
    if set(adoption) != ADOPTION_KEYS:
        raise ConfigError(f"adoption의 키는 정확히 {sorted(ADOPTION_KEYS)}")
    return config


def load(path: Path = DEFAULT_PATH) -> dict:
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))
