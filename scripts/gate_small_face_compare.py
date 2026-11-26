"""Gate 입 벌림 측정 비교: V0(현행, 전체 프레임) 대 Va(검출 박스 주변 crop, 배율 3).

계획: docs/superpowers/plans/2026-11-26-gate-small-face.md §3. 기준은 확인용 영상을 받기 전에 커밋했다(cd8175f).
서버 Gate 코드는 바꾸지 않는다. Va는 이 스크립트 안에서만 구현하고, 승인되면 server/gate로 옮긴다.

    conda activate trinity
    python scripts/gate_small_face_compare.py run --repeat 3
    python scripts/gate_small_face_compare.py report        # 마크다운 표와 기준 판정

- 입력은 VIDEOS로 고정한다(Seamless 파일럿 0~3번 전처리본, 본인 촬영 A~E). 임의 경로를 받지 않는다.
- 숫자만 남긴다. 프레임·crop·특징점 좌표는 저장하지 않는다. 표본별 입 벌림 값은 메모리에서
  V0·Va 비교(|Δopening|)에만 쓰고 파일에 쓰지 않는다.
- Gate 순서는 server/gate/__init__.py와 같다(probe → VAD → 얼굴 검출 → 트랙 → 입 측정 → 구간 규칙).
  Worker처럼 별도 프로세스·제한시간으로 돌리지 않는다(측정 전용).
- 결과: data/research/gate-small-face/results.json (Git 제외)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.gate import mouth  # noqa: E402
from server.gate.segments import _dominant_reason  # noqa: E402
from server.gate.types import (  # noqa: E402
    NO_MOUTH_MOVEMENT,
    FrameFaces,
    GateConfig,
    MouthSample,
    Segment,
)

Interval = tuple[float, float]
Box = tuple[float, float, float, float]

CROP_SCALE = 3.0                 # 고정(2026-11-26). B를 보고 정한 값이라 확인용 영상에서 다시 고르지 않는다
MOUTH_UNMEASURABLE = "mouth_unmeasurable"   # (c) 제안 코드. 서버에는 아직 없다
MIN_MEASURED_RATIO = 0.5         # (c) 제안 임시값
VARIANTS = ("V0", "Va")
SAMPLES = REPO_ROOT / "data/research/samples"
PILOT = REPO_ROOT / "data/research/seamless/pilot"
OUT = REPO_ROOT / "data/research/gate-small-face/results.json"
VIDEOS: tuple[tuple[str, str, Path], ...] = (
    *(("dev", f"S0-{w}", PILOT / f"pilot-00/pre/{w}.mp4") for w in "AB"),
    *(("confirm", f"S{n}-{w}", PILOT / f"pilot-{n:02d}/pre/{w}.mp4") for n in (1, 2, 3) for w in "AB"),
    *(("regression", f"self-{w}", SAMPLES / f"{w}.MOV") for w in "ABCDE"),
)
E_SPEECH: tuple[Interval, ...] = ((0.0, 10.0), (20.0, 30.0), (40.0, 50.0))   # 촬영자 기록(docs/gate.md)
SET_TITLES = (("dev", "개발용 (Seamless pilot#0, 진단·배율 결정에 본 영상)"),
              ("confirm", "확인용 (예약 파일럿 1~3번, 측정 전 미열람)"),
              ("regression", "회귀 (본인 촬영 A~E)"))


# ---------- 순수 함수 ----------

def crop_square(box: Box, scale: float, width: int, height: int) -> tuple[int, int, int, int]:
    """박스 중심의 정사각형(한 변 = 박스 긴 변 × scale)을 프레임 안으로 자른 (x0, y0, x1, y1).

    남는 영역이 2px보다 좁으면 전체 프레임을 돌려준다.
    """
    x, y, w, h = box
    cx, cy, half = x + w / 2, y + h / 2, scale * max(w, h) / 2
    x0, y0 = max(0, int(round(cx - half))), max(0, int(round(cy - half)))
    x1, y1 = min(width, int(round(cx + half))), min(height, int(round(cy + half)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0, 0, width, height
    return x0, y0, x1, y1


def nearest_box(frames: Sequence[FrameFaces], t: float, max_dt: float) -> Optional[Box]:
    """시각이 가장 가까운 검출 표본(차이 max_dt 이하)의 가장 큰(높이) 얼굴 박스."""
    best: Optional[tuple[float, FrameFaces]] = None
    for f in frames:
        d = abs(f.t - t)
        if d <= max_dt + 1e-9 and (best is None or d < best[0]):
            best = (d, f)
    if best is None or not best[1].faces:
        return None
    face = max(best[1].faces, key=lambda f: f.h)
    return face.x, face.y, face.w, face.h


def sample_from_crop(t: float, faces, x0: int, y0: int, cw: int, ch: int) -> MouthSample:
    """crop 기준 특징점으로 서버 _sample을 계산하고 박스만 원래 프레임 좌표로 옮긴다.

    입 벌림은 같은 픽셀 단위의 거리 비율이라 crop 원점과 무관하다.
    """
    s = mouth._sample(t, faces, cw, ch)
    if s.box is None:
        return s
    bx, by, bw, bh = s.box
    return MouthSample(s.t, s.opening, (bx + x0, by + y0, bw, bh))


def measured_fraction(samples: Sequence[MouthSample], start: float, end: float) -> Optional[float]:
    inside = [s for s in samples if start - 1e-9 <= s.t <= end + 1e-9]
    if not inside:
        return None
    return sum(1 for s in inside if s.opening is not None) / len(inside)


def overlap_sec(a: Sequence[Interval], b: Sequence[Interval]) -> float:
    return round(sum(max(0.0, min(e1, e2) - max(s1, s2)) for s1, e1 in a for s2, e2 in b), 3)


def outside_sec(a: Sequence[Interval], b: Sequence[Interval]) -> float:
    return round(sum(e - s for s, e in a) - overlap_sec(a, b), 3)


def relabel_unmeasurable(excluded: Sequence[Segment], samples: Sequence[MouthSample],
                         ratio: float = MIN_MEASURED_RATIO) -> list[Segment]:
    """(c) 규칙: no_mouth_movement 조각 가운데 입 벌림을 잰 표본이 ratio 미만이면 mouth_unmeasurable.

    정확히 ratio이거나 조각 안에 표본이 없으면 그대로 둔다. 다른 원인은 건드리지 않는다.
    """
    out = []
    for seg in excluded:
        if seg.reason_code == NO_MOUTH_MOVEMENT:
            f = measured_fraction(samples, seg.start_sec, seg.end_sec)
            if f is not None and f < ratio:
                seg = Segment(seg.start_sec, seg.end_sec, MOUTH_UNMEASURABLE, seg.quality)
        out.append(seg)
    return out


def opening_delta(a: Sequence[MouthSample], b: Sequence[MouthSample]) -> dict:
    """같은 시각 표본을 둘 다 쟀을 때 |Δopening|의 개수·중앙값·최대."""
    bv = {s.t: s.opening for s in b}
    d = [abs(s.opening - bv[s.t]) for s in a if s.opening is not None and bv.get(s.t) is not None]
    if not d:
        return {"n": 0, "median": None, "max": None}
    return {"n": len(d), "median": round(statistics.median(d), 5), "max": round(max(d), 5)}


# ---------- 기준 판정 (계획 §3, cd8175f) ----------

def _median(xs):
    return statistics.median(xs) if xs else None


def evaluate(videos: dict) -> list[dict]:
    rows: list[dict] = []

    def add(name, set_, criterion, value, threshold, ok):
        rows.append({"video": name, "set": set_, "criterion": criterion, "value": value,
                     "threshold": threshold, "pass": ok})

    for name, v in videos.items():
        if not v.get("exists") or not all(k in v.get("variants", {}) for k in VARIANTS):
            continue
        s, v0, va = v["set"], v["variants"]["V0"], v["variants"]["Va"]
        r0, ra = v0["mouth"]["rate"], va["mouth"]["rate"]
        e0, ea = v0["gate"]["eligible_sec"], va["gate"]["eligible_sec"]
        if r0 is not None and ra is not None:
            add(name, s, "rate_drop_le_2pp", round(r0 - ra, 4), "≤ 0.02", r0 - ra <= 0.02 + 1e-9)
        d = v.get("delta") or {}
        add(name, s, "delta_median_le_0.01", d.get("median"), "≤ 0.01",
            None if d.get("median") is None else d["median"] <= 0.01 + 1e-12)
        t0, ta = _median(v0["times"]["total_sec"]), _median(va["times"]["total_sec"])
        if t0 and ta:
            add(name, s, "time_increase_le_20pct", round(ta / t0 - 1, 4), "≤ 0.20", ta / t0 - 1 <= 0.20 + 1e-9)
        if name == "S0-B":
            add(name, s, "dev_B_rate_ge_0.8", ra, "≥ 0.8", ra is not None and ra >= 0.8)
            add(name, s, "c_dev_B_reason_is_mouth_unmeasurable", v0["relabel"]["reason_code"],
                MOUTH_UNMEASURABLE, v0["relabel"]["reason_code"] == MOUTH_UNMEASURABLE)
        if s == "confirm":
            if r0 is not None and r0 < 0.8:
                add(name, s, "confirm_low_rate_reaches_0.8", ra, "≥ 0.8", ra is not None and ra >= 0.8)
            if e0 and e0 > 0:
                add(name, s, "confirm_eligible_drop_le_5pct", round(ea / e0 - 1, 4), "≥ -0.05",
                    ea / e0 - 1 >= -0.05 - 1e-9)
        if name in ("self-C", "self-D"):
            ok = all(x["gate"]["eligible_sec"] == 0 and x["gate"]["reason_code"] == NO_MOUTH_MOVEMENT
                     for x in (v0, va))
            add(name, s, "regression_CD_still_rejected", f"{va['gate']['reason_code']}, {ea}s",
                "no_mouth_movement, 0s", ok)
            okc = all(x["relabel"]["reason_code"] == NO_MOUTH_MOVEMENT for x in (v0, va))
            add(name, s, "c_CD_stay_no_mouth_movement", va["relabel"]["reason_code"], NO_MOUTH_MOVEMENT, okc)
        if name in ("self-A", "self-B", "self-E") and e0:
            add(name, s, "regression_eligible_change_le_5pct", round(ea / e0 - 1, 4), "|x| ≤ 0.05",
                abs(ea / e0 - 1) <= 0.05 + 1e-9)
        if name == "self-E":
            o0 = overlap_sec([tuple(x) for x in v0["gate"]["eligible_intervals"]], E_SPEECH)
            oa = overlap_sec([tuple(x) for x in va["gate"]["eligible_intervals"]], E_SPEECH)
            add(name, s, "regression_E_overlap_drop_le_1s", round(o0 - oa, 3), "≤ 1.0", o0 - oa <= 1.0 + 1e-9)
    return rows


# ---------- 실행 ----------

def measure_mouth_cropped(path: Path, media, model_path: Path, config: GateConfig,
                          within: Sequence[Interval], frames: Sequence[FrameFaces],
                          scale: float = CROP_SCALE) -> list[MouthSample]:
    """server.gate.mouth.measure_mouth와 같은 표본 선택. 가까운 검출 박스가 있으면 그 주변 crop에 특징점."""
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=mouth._MAX_FACES,
    )
    margin = config.mouth_max_reversal_gap_sec
    stride = max(1, round(media.fps / config.mouth_sample_fps))
    max_dt = 0.5 / config.face_sample_fps
    out: list[MouthSample] = []
    cap = cv2.VideoCapture(str(path))
    try:
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            index = 0
            while True:
                t = index / media.fps
                wanted = index % stride == 0 and any(a - margin <= t <= b + margin for a, b in within)
                if not wanted:
                    if not cap.grab():
                        break
                    index += 1
                    continue
                ok, frame = cap.read()
                if not ok:
                    break
                h, w = frame.shape[:2]
                box = nearest_box(frames, t, max_dt)
                x0, y0, x1, y1 = (0, 0, w, h) if box is None else crop_square(box, scale, w, h)
                rgb = np.ascontiguousarray(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2RGB))
                result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                out.append(sample_from_crop(round(t, 3), result.face_landmarks, x0, y0, x1 - x0, y1 - y0))
                index += 1
    finally:
        cap.release()
    return out


def run_variant(path: Path, variant: str, models: dict[str, Path], config: GateConfig) -> dict:
    """Gate 한 번. 반환 dict의 "_samples"는 메모리 전용(파일에 쓰지 않는다)."""
    from server.gate import faces, mouth_activity, probe, segments, vad

    t0 = time.monotonic()
    media = probe.probe(path, config.subprocess_timeout_sec)
    speech = vad.detect_speech(path, config) if media is not None and media.has_audio else []
    t1 = time.monotonic()
    frames: list[FrameFaces] = []
    samples: list[MouthSample] = []
    if speech:
        frames = segments.assign_tracks(faces.detect_faces(path, media, models["face"], config), config)
    t2 = time.monotonic()
    if speech:
        if variant == "V0":
            samples = mouth.measure_mouth(path, media, models["landmark"], config, within=speech)
        else:
            samples = measure_mouth_cropped(path, media, models["landmark"], config, speech, frames)
    t3 = time.monotonic()
    result = segments.build_result(media, speech, frames, config,
                                   mouth_active=mouth_activity.active_intervals(samples, config),
                                   mouth_summary=mouth_activity.summarize(samples, config))
    t4 = time.monotonic()

    short = min(media.width, media.height)
    main_min = config.main_face_min_height_ratio * short
    excl: dict[str, float] = {}
    for s in result.excluded_segments:
        excl[s.reason_code] = round(excl.get(s.reason_code, 0.0) + s.duration_sec, 3)
    relabeled = relabel_unmeasurable(result.excluded_segments, samples)
    unmeasurable = round(sum(s.duration_sec for s in relabeled if s.reason_code == MOUTH_UNMEASURABLE), 3)
    measured = sum(1 for s in samples if s.opening is not None)
    digest = hashlib.sha256(json.dumps([result.to_dict(), [asdict(s) for s in samples]],
                                       sort_keys=True).encode()).hexdigest()[:16]
    return {
        "media": {"width": media.width, "height": media.height, "fps": round(media.fps, 3),
                  "duration_sec": media.duration_sec},
        "speech_sec": round(sum(b - a for a, b in speech), 3),
        "detector": {"samples": len(frames), "with_face": sum(1 for f in frames if f.faces),
                     "with_main_face": sum(1 for f in frames if any(x.h >= main_min for x in f.faces))},
        "mouth": {"samples": len(samples), "measured": measured,
                  "rate": round(measured / len(samples), 4) if samples else None,
                  "reversals": (result.mouth_summary or {}).get("reversals")},
        "gate": {"reason_code": result.reason_code, "eligible_sec": result.eligible_duration_sec,
                 "eligible_count": len(result.eligible_segments),
                 "eligible_intervals": [[s.start_sec, s.end_sec] for s in result.eligible_segments],
                 "excluded_sec": excl},
        "relabel": {"mouth_unmeasurable_sec": unmeasurable,
                    "reason_code": None if result.eligible_segments else _dominant_reason(relabeled)},
        "times": {"probe_vad_sec": round(t1 - t0, 3), "detect_sec": round(t2 - t1, 3),
                  "mouth_sec": round(t3 - t2, 3), "total_sec": round(t4 - t0, 3)},
        "digest": digest,
        "_samples": samples,
    }


def _models() -> dict[str, Path]:
    from server.config import Settings
    from server.gate.faces import resolve_face_model, resolve_landmark_model

    s = Settings()
    d = s.gate_model_dir if s.gate_model_dir.is_absolute() else REPO_ROOT / s.gate_model_dir
    c = s.gate_models_config_path if s.gate_models_config_path.is_absolute() else REPO_ROOT / s.gate_models_config_path
    return {"face": resolve_face_model(d, c), "landmark": resolve_landmark_model(d, c)}


def _meta(repeat: int) -> dict:
    import mediapipe

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                            capture_output=True, text=True).stdout.strip()
    models = json.loads((REPO_ROOT / "configs/gate_models.json").read_text(encoding="utf-8"))
    return {"git_commit": commit, "mediapipe": mediapipe.__version__, "crop_scale": CROP_SCALE,
            "min_measured_ratio": MIN_MEASURED_RATIO, "repeat": repeat, "platform": platform.platform(),
            "models_sha256": {k: v["sha256"] for k, v in models.items() if isinstance(v, dict)},
            "gate_config": asdict(GateConfig()), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def run(repeat: int, only: Optional[Sequence[str]] = None) -> dict:
    config, models = GateConfig(), _models()
    data = {"meta": _meta(repeat), "videos": {}}
    for set_, name, path in VIDEOS:
        if only and name not in only:
            continue
        entry: dict = {"set": set_, "exists": path.is_file(), "variants": {}}
        data["videos"][name] = entry
        if not entry["exists"]:
            print(f"{name}: 없음", flush=True)
            continue
        runs: dict[str, list[dict]] = {v: [] for v in VARIANTS}
        for r in range(repeat):
            for v in (VARIANTS if r % 2 == 0 else VARIANTS[::-1]):   # 순서를 돌려 열 상태 영향을 줄인다
                runs[v].append(run_variant(path, v, models, config))
        for v, rs in runs.items():
            first = {k: val for k, val in rs[0].items() if k != "_samples"}
            first["times"] = {k: [x["times"][k] for x in rs] for k in rs[0]["times"]}
            first["deterministic"] = len({x["digest"] for x in rs}) == 1
            entry["variants"][v] = first
        entry["delta"] = opening_delta(runs["V0"][0]["_samples"], runs["Va"][0]["_samples"])
        print(f"{name}: V0 측정률 {entry['variants']['V0']['mouth']['rate']} → "
              f"Va {entry['variants']['Va']['mouth']['rate']}", flush=True)
    data["criteria"] = evaluate(data["videos"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


# ---------- 보고 ----------

def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def _arrow(a, b, fmt=str):
    return f"{fmt(a)} → {fmt(b)}"


def render_report(data: dict) -> str:
    lines: list[str] = []
    videos = data.get("videos", {})
    for set_, title in SET_TITLES:
        names = [n for n, v in videos.items() if v["set"] == set_]
        if not names:
            continue
        lines += [f"#### {title}", "",
                  "| 영상 | 입력 | 입 측정률 V0 → Va | 검출(얼굴 있음/표본) | 적합 구간 V0 → Va | 대표 원인 V0 → Va "
                  "| (c) 적용 시 대표 원인 V0 → Va | (c) 측정 불가 초 V0 → Va | \\|Δopening\\| 중앙/최대(n) "
                  "| Gate 시간 중앙값 V0 → Va (초) |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for n in names:
            v = videos[n]
            if not v.get("exists") or not all(k in v.get("variants", {}) for k in VARIANTS):
                lines.append(f"| {n} | 없음 | — | — | — | — | — | — | — | — |")
                continue
            v0, va = v["variants"]["V0"], v["variants"]["Va"]
            m = v0["media"]
            d = v.get("delta") or {}

            def elig(x):
                return f"{x['gate']['eligible_sec']:g}초({x['gate']['eligible_count']})"

            def reason(x, key="gate"):
                return x[key]["reason_code"] or "통과"

            lines.append(
                f"| {n} | {m['width']}×{m['height']}, {m['duration_sec']:g}초 "
                f"| {_arrow(v0['mouth']['rate'], va['mouth']['rate'], _pct)} "
                f"| {v0['detector']['with_face']}/{v0['detector']['samples']} "
                f"| {elig(v0)} → {elig(va)} | {reason(v0)} → {reason(va)} "
                f"| {reason(v0, 'relabel')} → {reason(va, 'relabel')} "
                f"| {v0['relabel']['mouth_unmeasurable_sec']:g} → {va['relabel']['mouth_unmeasurable_sec']:g} "
                f"| {d.get('median')}/{d.get('max')}({d.get('n')}) "
                f"| {_median(v0['times']['total_sec']):.2f} → {_median(va['times']['total_sec']):.2f} |")
        lines.append("")
    crit = data.get("criteria") or evaluate(videos)
    if crit:
        lines += ["#### 기준 판정", "", "| 묶음 | 영상 | 기준 | 값 | 기준값 | 결과 |", "|---|---|---|---|---|---|"]
        for r in crit:
            res = "판정 불가" if r["pass"] is None else ("통과" if r["pass"] else "**미달**")
            lines.append(f"| {r['set']} | {r['video']} | {r['criterion']} | {r['value']} | {r['threshold']} | {res} |")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--repeat", type=int, default=3)
    r.add_argument("--only", nargs="*", choices=[n for _, n, _ in VIDEOS])
    sub.add_parser("report")
    opt = ap.parse_args(argv)
    if opt.cmd == "run":
        data = run(opt.repeat, opt.only)
    else:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    print(render_report(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
