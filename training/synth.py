"""합성 데이터 생성기: 파이프라인이 규칙대로 도는지 보기 위한 가짜 manifest와 가짜 특징.

영상 파일도 모델도 쓰지 않는다. 숫자는 난수이며 어떤 모델의 성능과도 무관하다.
조절할 수 있는 것: 그룹 구조(인물 수, 얼굴 교체로 이어지는 짝), 축별 신호 강도, 축별 결측률,
압축 파생본(부모 분할 상속), 일부러 넣는 누수.

    python -m training.synth --out data/research/synth-demo --signal waverep=1.5 --profiles x264-crf28-720p

출력: manifest.csv, features.jsonl(training/features/extract.py와 같은 형식), features.meta.json.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from training.datasets import groups
from training.datasets.manifest import Record, sha256_file, write_manifest
from training.emulator.pipeline import derive_record

AXIS_KEYS = ("waverep", "full", "face_roi", "face_motion", "syncnet")
MOTION_VARIANTS = ("full", "face_roi", "face_motion")
DATASET_ID = "synth"
FEATURE_VERSION = {"gate": {"version": "synthetic"}, "waverep": {"version": "synthetic"},
                   "motionphys": {"version": "synthetic"}, "syncnet": {"version": "synthetic"}}


@dataclass(frozen=True)
class SynthConfig:
    identities: int = 120
    reals_per_identity: int = 2
    fakes_per_identity: int = 2
    # 축별 신호 강도(가짜와 진짜의 평균 차이, 잡음 표준편차 1 기준). 0이면 신호가 없다
    signal: dict = field(default_factory=dict)
    # 축별 결측률(그 축만 계산하지 못한 영상의 비율)
    missing: dict = field(default_factory=dict)
    identity_effect: float = 0.5     # 같은 인물의 영상이 공유하는 치우침(그룹 안 상관)
    motion_dim: int = 8              # 합성 MotionPhys 특징 차원(실제는 504/1512)
    profiles: tuple[str, ...] = ()   # 압축 파생본을 만들 프로파일
    compression_shift: float = 0.3   # 파생본 특징에 더하는 잡음의 크기
    fractions: tuple[float, float, float] = (0.6, 0.2, 0.2)
    leak: bool = False               # True면 train 그룹의 영상 하나를 test로 옮긴다
    seed: int = 0


def _features(rng: random.Random, y: int, effect: float, cfg: SynthConfig) -> dict:
    def s(key: str) -> float:
        return float(cfg.signal.get(key, 0.0))

    def missing(key: str) -> bool:
        return rng.random() < float(cfg.missing.get(key, 0.0))

    axes: dict = {}
    if missing("waverep"):
        axes["waverep"] = {"status": "error", "reason_code": "inference_error", "frames": 0,
                           "logit_median": None, "logit_mean": None, "logit_q75": None}
    else:
        base = s("waverep") * y + effect + rng.gauss(0, 1)
        axes["waverep"] = {"status": "completed", "reason_code": None, "frames": 60, "logit_median": base,
                           "logit_mean": base + rng.gauss(0, 0.2), "logit_q75": base + 0.5 + rng.gauss(0, 0.2)}
    variants = {}
    for name in MOTION_VARIANTS:
        if missing(name):
            variants[name] = {"status": "insufficient_input", "reason_code": "insufficient_motion", "features": None}
        else:
            # 앞의 두 차원에만 신호를 싣는다
            vec = [(s(name) * y if i < 2 else 0.0) + effect * (i == 0) + rng.gauss(0, 1) for i in range(cfg.motion_dim)]
            variants[name] = {"status": "completed", "reason_code": None, "features": vec}
    axes["motionphys"] = {"status": variants["full"]["status"], "reason_code": variants["full"]["reason_code"],
                          "variants": variants}
    if missing("syncnet"):
        axes["syncnet"] = {"status": "insufficient_input", "reason_code": "tracking_failed", "tracks": 0,
                           "lse_c_median": None, "lse_d_median": None, "abs_offset_median": None}
    else:
        axes["syncnet"] = {"status": "completed", "reason_code": None, "tracks": 1,
                           "lse_c_median": 5.0 - s("syncnet") * y + rng.gauss(0, 1),
                           "lse_d_median": max(0.0, 8.0 + s("syncnet") * y + rng.gauss(0, 1)),
                           "abs_offset_median": abs(rng.gauss(0, 1)) + s("syncnet") * y}
    return axes


def _shift(axes: dict, rng: random.Random, amount: float) -> dict:
    """압축 파생본: 부모의 값에 잡음을 더한다(결측은 그대로)."""
    out = json.loads(json.dumps(axes))
    w = out["waverep"]
    for k in ("logit_median", "logit_mean", "logit_q75"):
        if w[k] is not None:
            w[k] += rng.gauss(0, amount)
    for v in out["motionphys"]["variants"].values():
        if v["features"] is not None:
            v["features"] = [x + rng.gauss(0, amount) for x in v["features"]]
    s = out["syncnet"]
    for k in ("lse_c_median", "lse_d_median"):
        if s[k] is not None:
            s[k] = max(0.0, s[k] + rng.gauss(0, amount))
    return out


def generate(cfg: SynthConfig) -> tuple[list[Record], list[dict]]:
    """(분할이 정해진 레코드, features.jsonl의 행). 같은 설정이면 같은 결과다."""
    rng = random.Random(cfg.seed)
    effects = [rng.gauss(0, cfg.identity_effect) for _ in range(cfg.identities)]
    records, feats = [], {}
    for person in range(cfg.identities):
        partner = person + 1 if person % 2 == 0 else person - 1  # 얼굴 교체는 짝 안에서만(그룹 = 짝)
        partner = partner if partner < cfg.identities else person
        for i in range(cfg.reals_per_identity):
            rec = Record(DATASET_ID, f"r{person:04d}_{i}", f"real/{person}_{i}.mp4", "real",
                         source_recording_id=f"rec{person:04d}_{i}", identity_ids=(f"p{person:04d}",),
                         file_hash=f"h-r{person}-{i}")
            records.append(rec)
            feats[rec.uid] = _features(rng, 0, effects[person], cfg)
        for i in range(cfg.fakes_per_identity):
            swap = i % 2 == 1
            rec = Record(DATASET_ID, f"f{person:04d}_{i}", f"fake/{person}_{i}.mp4", "fake",
                         source_recording_id=f"rec{person:04d}_0",
                         manipulation_type="C1" if swap else "B2", generator_id="swapgen" if swap else "lipgen",
                         identity_ids=(f"p{person:04d}", f"p{partner:04d}") if swap else (f"p{person:04d}",),
                         file_hash=f"h-f{person}-{i}")
            records.append(rec)
            feats[rec.uid] = _features(rng, 1, effects[person], cfg)
    names = ("train", "dev", "test")
    records = groups.assign_splits(records, dict(zip(names, cfg.fractions)), cfg.seed)
    for profile in cfg.profiles:  # 분할을 정한 뒤에 압축한다. 파생본은 부모의 분할을 물려받는다
        for parent in [r for r in records if not r.compression_profile_id]:
            child = derive_record(parent, profile, f"derived/{profile}/{parent.video_id}.mp4",
                                  f"{parent.file_hash}@{profile}")
            records.append(child)
            feats[child.uid] = _shift(feats[parent.uid], rng, cfg.compression_shift)
    if cfg.leak:
        victim = next(r for r in sorted(records, key=lambda r: r.uid) if r.split == "train" and r.label == "fake")
        records = [replace(r, split="test") if r.uid == victim.uid else r for r in records]
    rows = [{"uid": r.uid, "dataset_id": r.dataset_id, "video_id": r.video_id, "video_duration_sec": 40.0,
             "eligible_duration_sec": 30.0, "gate_reason": None, "axes": feats[r.uid]}
            for r in sorted(records, key=lambda r: r.uid)]
    return records, rows


def write(cfg: SynthConfig, out: Path) -> dict:
    records, rows = generate(cfg)
    out.mkdir(parents=True, exist_ok=True)
    write_manifest(out / "manifest.csv", records)
    with (out / "features.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, allow_nan=False) + "\n")
    meta = {"schema_version": 1, "synthetic": True, "manifest_sha256": sha256_file(out / "manifest.csv"),
            "feature_version": FEATURE_VERSION, "videos": len(rows),
            "features_sha256": sha256_file(out / "features.jsonl")}
    (out / "features.meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def _pairs(items: list[str]) -> dict:
    out = {}
    for item in items:
        key, _, value = item.partition("=")
        if key not in AXIS_KEYS:
            raise SystemExit(f"축 이름은 {AXIS_KEYS} 중 하나: {key!r}")
        out[key] = float(value)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--identities", type=int, default=120)
    p.add_argument("--signal", nargs="*", default=[], help="축=강도 (예: waverep=1.5 full=1.0)")
    p.add_argument("--missing", nargs="*", default=[], help="축=결측률")
    p.add_argument("--profiles", nargs="*", default=[])
    p.add_argument("--leak", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    opt = p.parse_args(argv)
    cfg = SynthConfig(identities=opt.identities, signal=_pairs(opt.signal), missing=_pairs(opt.missing),
                      profiles=tuple(opt.profiles), leak=opt.leak, seed=opt.seed)
    print(json.dumps(write(cfg, opt.out), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
