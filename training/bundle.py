"""검증된 모델 묶음: 만들기, digest 고정, 불러올 때의 검증, 점수 계산. 표준 라이브러리만 쓴다.

묶음 = 서버가 쓸 수 있는 후보의 계수·표준화·보정 + 잠근 임계값 + MotionPhys 모델 + 특징 버전
      + 학습 manifest·특징 해시 + 검증 리포트. 폴더 하나에 담고 bundle.json의 digest로 고정한다.
서버는 digest가 저장소에 커밋된 값(configs/fusion_bundle.json)과 같고 검증 리포트의 판단이
"채택 가능" 또는 "WaveRep 단독"일 때만 쓴다(README §15.3). 합성 데이터의 묶음은 테스트에서만 허용한다.

감사(2026-11-18)로 더한 확인. 만들 때와 불러올 때 모두 한다.
- 학습 설정이 커밋된 configs/training.json과 같아야 한다(사전 고정 기준, A2). 설정이 바뀌면 다시 검증한다.
- 판단은 리포트에 적힌 지표와 그 설정의 채택 기준으로 다시 계산한 것과 같아야 한다(A1).
- 서버가 읽는 파일(리포트·모델·임계값·MotionPhys 모델)은 모두 digest가 덮는 files에 있어야 한다(A5).

감사 결정(2026-11-18, README §15.3)으로 더한 것.
- 후보마다 역할(primary/fallback)을 적고 서버는 training/serving.py의 규칙으로 후보를 고른다(A9).
- 만들기 전에 같은 manifest·특징·커밋된 설정으로 새 폴더에서 학습·리포트를 다시 돌려, 학습 결과 폴더의 모든 파일과
  리포트가 같은지 확인한다(A16). 학습은 결정적이다(고정 시드, LightGBM deterministic).
  **한계:** features.jsonl 자체를 고친 경우는 잡지 못한다(같은 특징으로 다시 돌리기 때문). 그것은 추출을 다시 돌려야 확인된다.

    python -m training.bundle --run <학습 결과 폴더> --report <리포트 폴더>/report.json \
        --manifest <manifest.csv> --features <특징 폴더> --out data/models/fusion/<id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from training import config as training_config, serving
from training.evaluation import thresholds
from training.evaluation.lock import DEFAULT_LOCK_PATH
from training.report import decision as rules
from training.report.decision import FUSION_ADOPTABLE, WAVEREP_ONLY

# 2: training_config, 판단 재계산·파일 포함 확인(감사). 3: 후보 역할(primary/fallback), 재현 검증(감사 결정 2026-11-18)
SCHEMA_VERSION = 3
REPO_ROOT = Path(__file__).resolve().parents[1]
TRAIN_PYTHON = REPO_ROOT / "research/training/.venv/bin/python"
TRAIN_SCRIPT = REPO_ROOT / "research/training/train.py"
# 재현 비교에서 빼는 리포트 항목: shortcut 진단(--features 유무에 따라 달라지고 판단에 쓰지 않는다),
# 커밋된 설정 일치 표시(create가 학습 설정을 커밋된 설정과 직접 견준다)
REPORT_KEYS_NOT_COMPARED = ("shortcut_diagnostic", "training_config_matches_committed")
USABLE_DECISIONS = (FUSION_ADOPTABLE, WAVEREP_ONLY)
MANIFEST_NAME = "bundle.json"
MOTION_VARIANTS = ("full", "face_roi", "face_motion")


class BundleError(RuntimeError):
    """묶음을 만들 수 없거나, 불러온 묶음을 쓸 수 없다. code는 로그에 남기는 짧은 이유다."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _committed(expected_config: Optional[dict]) -> dict:
    """비교 기준이 되는 학습 설정. 주지 않으면 저장소에 커밋된 configs/training.json."""
    try:
        conf = expected_config if expected_config is not None else training_config.load()
        return training_config.without_comment(training_config.validate(conf))
    except (OSError, ValueError) as e:
        raise BundleError("config_unreadable", type(e).__name__) from e


def _check_report(report: dict, training: dict) -> None:
    """리포트가 이 설정의 채택 기준으로 계산한 것이고, 판단이 지표에서 다시 나오는지(감사 A1·A2)."""
    if report.get("gates", {}).get("adoption_config") != training["adoption"]:
        raise BundleError("config_not_committed", "리포트의 채택 기준이 커밋된 설정과 다르다")
    try:
        again = rules.rederive(report, training["adoption"])
    except (KeyError, TypeError, ValueError) as e:
        raise BundleError("report_inconsistent", type(e).__name__) from e
    if not rules.same_decision(again, report["decision"]):
        raise BundleError("report_inconsistent", "리포트의 판단이 리포트의 지표로 다시 계산한 판단과 다르다")


def _tree(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): _sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def _comparable(report: dict) -> dict:
    return {k: v for k, v in report.items() if k not in REPORT_KEYS_NOT_COMPARED}


def reproduce(run: Path, report: dict, meta: dict, manifest: Path, features: Path,
              lock_path: Path = DEFAULT_LOCK_PATH) -> dict:
    """같은 manifest·특징·설정으로 새 폴더에서 학습·리포트를 다시 돌려 같은지 확인한다(감사 A16). 다르면 BundleError."""
    from training.report import build  # build가 이 모듈을 쓰지 않지만 순환을 피하려고 여기서 읽는다

    if not TRAIN_PYTHON.is_file():
        raise BundleError("reproduction_unavailable", "research/training/.venv가 없어 다시 학습할 수 없다")
    with tempfile.TemporaryDirectory(prefix="bundle-repro-") as tmp:
        tmp = Path(tmp)
        (tmp / "config.json").write_text(json.dumps(meta["config"], ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([str(TRAIN_PYTHON), str(TRAIN_SCRIPT), "--manifest", str(manifest), "--features", str(features),
                               "--config", str(tmp / "config.json"), "--out", str(tmp / "run"), "--lock", str(lock_path)],
                              capture_output=True, text=True, cwd=REPO_ROOT)
        if proc.returncode != 0:
            raise BundleError("not_reproducible", "같은 입력으로 다시 학습하지 못했다")
        theirs, ours = _tree(run), _tree(tmp / "run")
        if theirs != ours:
            diff = sorted(k for k in set(theirs) | set(ours) if theirs.get(k) != ours.get(k))
            raise BundleError("not_reproducible", f"다시 학습한 결과와 다른 파일 {len(diff)}개: {diff[:5]}")
        try:
            again = build.build(manifest, tmp / "run", lock_path, features_dir=features,
                                committed_config=meta["config"])
        except (build.ReportError, ValueError, OSError) as e:
            raise BundleError("not_reproducible", f"리포트를 다시 만들지 못했다: {type(e).__name__}") from e
        if _comparable(json.loads(json.dumps(again))) != _comparable(report):
            raise BundleError("not_reproducible", "다시 만든 리포트가 검증 리포트와 다르다")
    return {"verified": True, "run_files": len(ours), "run_tree_sha256": _digest(ours),
            "report_sha256": _digest(_comparable(report))}


def create(run: Path, report_path: Path, out: Path, *, manifest: Path, features: Path,
           expected_config: Optional[dict] = None, lock_path: Path = DEFAULT_LOCK_PATH) -> dict:
    """학습 결과와 검증 리포트에서 묶음을 만든다. 판단이 보류면 만들지 않는다.

    manifest·features는 재현 검증(감사 A16)에 쓴다. expected_config는 테스트용이다.
    주지 않으면 커밋된 configs/training.json과 견준다.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    meta = json.loads((run / "train_meta.json").read_text(encoding="utf-8"))
    decision = report["decision"]
    if decision["decision"] not in USABLE_DECISIONS or not decision["servable_candidates"]:
        raise BundleError("report_not_adoptable", f"검증 리포트의 판단이 {decision['decision']!r}다. 묶음을 만들지 않는다")
    if report["data"]["manifest_sha256"] != meta["manifest_sha256"] \
            or report["data"]["features_sha256"] != meta["features_sha256"]:
        raise BundleError("report_mismatch", "리포트와 학습 결과가 다른 manifest·특징의 것이다")
    committed = _committed(expected_config)
    if training_config.without_comment(meta["config"]) != committed:
        raise BundleError("config_not_committed", "학습 설정이 커밋된 configs/training.json과 다르다")
    _check_report(report, committed)
    if out.exists():
        raise FileExistsError(out)
    reproduction = reproduce(run, report, meta, manifest, features, lock_path)
    out.mkdir(parents=True, exist_ok=False)
    files, candidates = {}, []
    for name in decision["servable_candidates"]:
        model = json.loads((run / "models" / f"{name}.json").read_text(encoding="utf-8"))
        if model["threshold_digest"] != report["candidates"][name]["threshold_digest"]:
            raise BundleError("report_mismatch", f"{name}: 리포트가 본 임계값과 학습 결과의 임계값이 다르다")
        copies = {f"models/{name}.json": run / "models" / f"{name}.json",
                  f"thresholds/{name}.json": run / "thresholds" / f"{name}.json"}
        variant = model["motion_variant"] if "physics" in model["axes"] else None
        if variant:
            copies[f"models/motionphys-{variant}.txt"] = run / "models" / f"motionphys-{variant}.txt"
        for rel, src in copies.items():
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copyfile(src, dst)
            files[rel] = _sha256(dst)
        role = serving.PRIMARY if name == decision["primary"] else serving.FALLBACK
        candidates.append({"candidate": name, "axes": model["axes"], "motion_variant": variant, "role": role})
    shutil.copyfile(report_path, out / "report.json")
    files["report.json"] = _sha256(out / "report.json")
    body = {
        "schema_version": SCHEMA_VERSION, "synthetic": bool(meta.get("synthetic")),
        "decision": decision["decision"], "candidates": candidates,
        "feature_version": meta["feature_version"], "waverep_score": meta["config"]["waverep_score"],
        "manifest_sha256": meta["manifest_sha256"], "features_sha256": meta["features_sha256"],
        "dev_compression_conditions": meta["dev_compression_conditions"], "files": files,
        "training_config": committed, "serving_rule": serving.RULE, "reproduction": reproduction,
    }
    manifest = {**body, "digest": _digest(body)}
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


@dataclass(frozen=True)
class Candidate:
    name: str
    axes: frozenset
    inputs: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float
    calibration_a: float
    calibration_b: float
    threshold: float
    motion_variant: Optional[str]
    motion_model: Optional[Path]

    def score(self, values: dict[str, Optional[float]]) -> Optional[float]:
        """결합 점수(decision value). 입력이 하나라도 없으면 None이다. 0이나 평균으로 채우지 않는다."""
        xs = [values.get(name) for name in self.inputs]
        if any(x is None or not math.isfinite(x) for x in xs):
            return None
        return self.intercept + sum(c * (x - m) / s for c, x, m, s in zip(self.coef, xs, self.mean, self.scale))

    def calibrated(self, score: float) -> float:
        z = self.calibration_a * score + self.calibration_b
        return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


@dataclass(frozen=True)
class Bundle:
    digest: str
    feature_version: dict
    waverep_score: str
    candidates: tuple[Candidate, ...]  # 축이 많은 것부터
    primary: str = ""                  # 선택 후보. 나머지는 대체 후보다

    def choose(self, available: frozenset, inputs: dict[str, Optional[float]]) -> Optional[Candidate]:
        """이번 요청에 쓸 후보(README §15.3 2026-11-18, 감사 A9). 규칙은 학습·리포트와 같은 training/serving.choose다.

        선택 후보는 그 축이 모두 성공했고 입력이 모두 있으면 쓴다. 아니면 성공한 축 집합과 정확히 같은 대체 후보.
        """
        by = {c.name: c for c in self.candidates}
        primary = (self.primary, by[self.primary].axes) if self.primary in by else None
        fallbacks = [(c.name, c.axes) for c in self.candidates if c.name != self.primary]
        name = serving.choose(primary, fallbacks, frozenset(available), lambda n: by[n].score(inputs) is not None)
        return by[name] if name else None

    @property
    def motion(self) -> Optional[tuple[str, Path]]:
        return next(((c.motion_variant, c.motion_model) for c in self.candidates if c.motion_model), None)


def load(folder: Path, expected_digest: str, allow_synthetic: bool = False,
         expected_config: Optional[dict] = None) -> Bundle:
    """검증을 모두 통과한 묶음만 돌려준다. 하나라도 어긋나면 BundleError.

    expected_config는 서버가 읽은 커밋된 학습 설정이다. 주지 않으면 저장소의 configs/training.json.
    """
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BundleError("bundle_unreadable", type(e).__name__) from e
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise BundleError("bundle_schema")
    body = {k: v for k, v in manifest.items() if k != "digest"}
    if _digest(body) != manifest.get("digest"):
        raise BundleError("bundle_tampered", "bundle.json의 내용이 digest와 다르다")
    if not expected_digest or manifest["digest"] != expected_digest:
        raise BundleError("digest_mismatch", "저장소에 고정한 digest와 다르다")
    if manifest["synthetic"] and not allow_synthetic:
        raise BundleError("synthetic_bundle", "합성 데이터로 만든 묶음은 쓰지 않는다")
    committed = _committed(expected_config)
    if manifest.get("training_config") != committed:
        raise BundleError("config_not_committed", "묶음의 학습 설정이 커밋된 configs/training.json과 다르다")
    try:
        files = manifest["files"]
        for rel, sha in files.items():
            path = (folder / rel).resolve()
            if not path.is_relative_to(folder.resolve()) or _sha256(path) != sha:
                raise BundleError("file_hash_mismatch", rel)

        def covered(rel: str) -> Path:
            # digest가 덮지 않는 파일은 고정한 뒤에 바꿀 수 있다. 읽는 파일은 모두 files에 있어야 한다(감사 A5)
            if rel not in files:
                raise BundleError("file_not_pinned", rel)
            return folder / rel

        report = json.loads(covered("report.json").read_text(encoding="utf-8"))
        decision = report["decision"]
        if decision["decision"] not in USABLE_DECISIONS or decision["decision"] != manifest["decision"]:
            raise BundleError("report_not_adoptable")
        if report["data"]["manifest_sha256"] != manifest["manifest_sha256"] or bool(report["synthetic"]) != bool(manifest["synthetic"]):
            raise BundleError("report_mismatch")
        _check_report(report, committed)
        roles = {e["candidate"]: e.get("role") for e in manifest["candidates"]}
        expected = {n: serving.PRIMARY if n == decision["primary"] else serving.FALLBACK
                    for n in decision["servable_candidates"]}
        if roles != expected:
            # 리포트가 정한 선택·대체 후보와 묶음의 역할이 다르다(감사 A9)
            raise BundleError("candidate_roles_mismatch")
        out = []
        for entry in manifest["candidates"]:
            name = entry["candidate"]
            if name not in decision["servable_candidates"]:
                raise BundleError("candidate_not_validated", name)
            model = json.loads(covered(f"models/{name}.json").read_text(encoding="utf-8"))
            threshold = thresholds.load_threshold(covered(f"thresholds/{name}.json"))
            if threshold["digest"] != model["threshold_digest"] or threshold["model_id"] != name \
                    or threshold["digest"] != report["candidates"][name]["threshold_digest"]:
                raise BundleError("threshold_mismatch", name)
            m, variant = model["model"], entry["motion_variant"]
            if ("physics" in model["axes"]) != (variant is not None) or (
                    variant is not None and (variant not in MOTION_VARIANTS or variant != model["motion_variant"])):
                raise BundleError("motion_variant_invalid", name)
            if variant is not None:
                covered(f"models/motionphys-{variant}.txt")
            if sorted(entry["axes"]) != sorted(model["axes"]):
                raise BundleError("candidate_axes_mismatch", name)
            out.append(Candidate(
                name=name, axes=frozenset(model["axes"]), inputs=tuple(model["inputs"]),
                mean=tuple(m["mean"]), scale=tuple(m["scale"]), coef=tuple(m["coef"]), intercept=m["intercept"],
                calibration_a=model["calibration"]["a"], calibration_b=model["calibration"]["b"],
                threshold=threshold["threshold"], motion_variant=variant,
                motion_model=(folder / "models" / f"motionphys-{variant}.txt").resolve() if variant else None))
    except BundleError:
        raise
    except (OSError, ValueError, KeyError, TypeError, thresholds.ThresholdError) as e:
        raise BundleError("bundle_invalid", type(e).__name__) from e
    if not out:
        raise BundleError("bundle_empty")
    out.sort(key=lambda c: -len(c.axes))
    return Bundle(manifest["digest"], manifest["feature_version"], manifest["waverep_score"], tuple(out),
                  primary=decision["primary"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True, help="학습에 쓴 manifest(재현 검증용)")
    p.add_argument("--features", type=Path, required=True, help="학습에 쓴 특징 폴더(재현 검증용)")
    p.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    p.add_argument("--out", type=Path, required=True, help="새 폴더(이미 있으면 거부)")
    opt = p.parse_args(argv)
    try:
        manifest = create(opt.run, opt.report, opt.out, manifest=opt.manifest, features=opt.features,
                          lock_path=opt.lock)
    except (BundleError, OSError, ValueError, KeyError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"digest": manifest["digest"], "decision": manifest["decision"],
                      "candidates": [c["candidate"] for c in manifest["candidates"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
