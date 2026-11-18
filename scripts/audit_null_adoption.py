"""감사(2026-11-18) 시나리오 5: 신호가 없는 합성 데이터에서 채택 판단이 우연히 나오는 비율.

    conda activate trinity
    python scripts/audit_null_adoption.py --identities 120 --seeds 100 --out <새 폴더>

- 합성 데이터만 쓴다(training.synth, signal 없음). 숫자는 어떤 모델의 성능도 아니다.
- 학습은 research/training/.venv의 train.py, 리포트·판단은 training.report.build를 그대로 쓴다.
- 설정은 커밋된 configs/training.json에서 dev 압축 조건만 ["original"]로 바꾼다(합성 데이터에 파생본이 없다).
  n_boot는 커밋된 값(1000)을 그대로 쓴다.
- 결과: <out>/results.jsonl(시드별 판단과 W의 test AUC CI 하한·FPR CI 상한), 표준 출력에 요약.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from training import synth  # noqa: E402
from training.report import build  # noqa: E402

PYTHON = REPO_ROOT / "research/training/.venv/bin/python"
TRAIN = REPO_ROOT / "research/training/train.py"


def one(seed: int, identities: int, out: Path, config: dict) -> dict:
    folder = out / f"seed{seed}"
    data = folder / "data"
    synth.write(replace(synth.SynthConfig(identities=identities, seed=seed), signal={}), data)
    (folder / "config.json").write_text(json.dumps(config), encoding="utf-8")
    proc = subprocess.run([str(PYTHON), str(TRAIN), "--manifest", str(data / "manifest.csv"), "--features", str(data),
                           "--config", str(folder / "config.json"), "--out", str(folder / "run")],
                          capture_output=True, text=True, cwd=REPO_ROOT, timeout=600)
    if proc.returncode != 0:
        return {"seed": seed, "decision": "train_refused", "detail": proc.stderr.strip()[-200:]}
    report = build.build(data / "manifest.csv", folder / "run", committed_config=config)
    w = report["candidates"]["W"]["test"]
    return {"seed": seed, "decision": report["decision"]["decision"],
            "servable": report["decision"]["servable_candidates"],
            "w_auc_ci_low": w["overall"]["roc_auc"]["ci_low"], "w_fpr_ci_high": w["overall"]["fpr"]["ci_high"],
            "test_real_scored": w["counts"]["real_scored"], "test_groups": w["counts"]["groups"],
            "own_passed": {n: all(g["passed"] for g in gates) for n, gates in report["gates"]["own"].items()}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--identities", type=int, default=120)
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--first-seed", type=int, default=1000)
    p.add_argument("--out", type=Path, required=True, help="새 폴더(이미 있으면 거부)")
    opt = p.parse_args(argv)
    opt.out.mkdir(parents=True, exist_ok=False)
    config = json.loads((REPO_ROOT / "configs/training.json").read_text(encoding="utf-8"))
    config["dev_compression_conditions"] = ["original"]
    counts: Counter = Counter()
    auc_low_above = 0
    with (opt.out / "results.jsonl").open("w", encoding="utf-8") as f:
        for seed in range(opt.first_seed, opt.first_seed + opt.seeds):
            r = one(seed, opt.identities, opt.out, config)
            counts[r["decision"]] += 1
            auc_low_above += bool(r.get("w_auc_ci_low") is not None and r["w_auc_ci_low"] > 0.5)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
    print(json.dumps({"identities": opt.identities, "seeds": opt.seeds, "decisions": dict(counts),
                      "w_auc_ci_low_above_0.5": auc_low_above}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
