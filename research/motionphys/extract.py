"""MotionPhys 계열 특징 추출기. 세 후보가 같은 인터페이스를 쓴다 (README §5.2, 백로그 10번).

    full         A. 전체 화면. 논문(arXiv:2608.20770v1)의 재구현. 504차원
    face_roi     B. 같은 알고리즘을 MediaPipe 얼굴 박스 안으로 제한. 504차원 (논문과 다른 조건)
    face_motion  C. 얼굴 특징점 궤적(머리·눈썹·입술). 3 × 504 = 1,512차원 (프로젝트 임시 설계)

research/motionphys/.venv의 Python으로 실행한다(torch 없음).

    research/motionphys/.venv/bin/python research/motionphys/extract.py \
        --request <작업 폴더>/motionphys_request.json --output <작업 폴더>/motionphys_result.json

요청: {"video": 경로, "segments": [[start_sec, end_sec], ...], "variant": "full"}
결과: status, reason_code, features(또는 null), valid_trajectories 등.

특징 벡터만 낸다. 분류하지 않고, 점수를 내지 않고, 판정하지 않는다.
움직임이 부족하거나 추적에 실패하면 features는 null이다. 0으로 채우지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import kinematics  # noqa: E402
import tracking  # noqa: E402
from kinematics import SCALES  # noqa: E402

VARIANTS = ("full", "face_roi", "face_motion")
FACE_MOTION_REGIONS = ("head", "eyebrows", "lips")
SCHEMA_VERSION = 1

# axes.*.status (README §10)
COMPLETED = "completed"
INSUFFICIENT_INPUT = "insufficient_input"
ERROR = "error"
# 축별 세부 원인 (README §5.2, §10)
INSUFFICIENT_MOTION = "insufficient_motion"
TRACKING_FAILED = "tracking_failed"


@dataclass(frozen=True)
class Limits:
    """분석 가능 기준. 전부 임시값이다. 개발 검증 데이터에서 정한 뒤 고정한다(README §5.2)."""

    min_valid_per_scale: int = 20       # 스케일마다 끝까지 추적된 궤적 수의 하한
    min_moving_per_scale: int = 10      # 스케일마다 "움직인 궤적" 수의 하한


def feature_dim(variant: str) -> int:
    return kinematics.FEATURE_DIM * (len(FACE_MOTION_REGIONS) if variant == "face_motion" else 1)


def feature_names(variant: str) -> list[str]:
    if variant == "face_motion":
        return [n for region in FACE_MOTION_REGIONS for n in kinematics.feature_names(f"{region}.")]
    return kinematics.feature_names()


def _check_segments(segments) -> list[tuple[float, float]]:
    out = []
    for seg in segments:
        if isinstance(seg, (str, bytes)) or len(seg) != 2:
            raise ValueError("구간은 [start_sec, end_sec] 두 값이어야 한다")
        a, b = seg
        for v in (a, b):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError("구간 값은 유한한 숫자여야 한다")
        if a < 0 or b <= a:
            raise ValueError("구간은 0 <= start < end 여야 한다")
        out.append((float(a), float(b)))
    return out


def _summary(trajs: dict[int, np.ndarray], config: tracking.TrackingConfig) -> dict:
    """스케일별 유효 궤적 수, 움직인 궤적 수, 움직임 크기."""
    out = {}
    for scale in SCALES:
        t = trajs.get(scale)
        n = 0 if t is None else len(t)
        steps = kinematics.mean_step(t) if n else np.empty(0)
        out[str(scale)] = {
            "valid_trajectories": n,
            "moving_trajectories": int((steps >= config.moving_min_mean_step).sum()),
            # 한 걸음 평균 이동 거리(px)의 중앙값. 궤적이 없으면 null
            "median_mean_step_px": float(np.median(steps)) if n else None,
        }
    return out


def _features_from(trajs: dict[int, np.ndarray]) -> np.ndarray:
    return kinematics.video_feature({s: kinematics.trajectory_features(trajs[s]) for s in SCALES})


def _decide(summaries: dict[str, dict], limits: Limits) -> Optional[str]:
    """분석할 수 없으면 원인 코드, 가능하면 None. summaries는 {이름: 스케일별 요약}."""
    for per_scale in summaries.values():
        if any(per_scale[str(s)]["valid_trajectories"] < limits.min_valid_per_scale for s in SCALES):
            return TRACKING_FAILED
    for per_scale in summaries.values():
        if any(per_scale[str(s)]["moving_trajectories"] < limits.min_moving_per_scale for s in SCALES):
            return INSUFFICIENT_MOTION
    return None


def _concat(parts: list[dict[int, np.ndarray]]) -> dict[int, np.ndarray]:
    return {
        s: (np.concatenate([p[s] for p in parts], axis=0) if parts else np.empty((0, s, 2)))
        for s in SCALES
    }


def _point_variant(segment_frames, variant, config) -> tuple[dict[int, np.ndarray], dict]:
    """후보 A, B: 점 추적. 구간마다 추적하고 궤적을 스케일별로 모은다."""
    detector = None
    mask_fn = None
    if variant == "face_roi":
        import faces

        detector = faces.FaceBoxDetector()
        mask_fn = lambda _start, frame: detector.mask(frame)  # noqa: E731
    try:
        parts, initialized, clips, clips_used = [], {s: 0 for s in SCALES}, {s: 0 for s in SCALES}, {s: 0 for s in SCALES}
        for sf in segment_frames:
            trajs, info = tracking.extract_trajectories(sf.frames, config, mask_fn)
            parts.append(trajs)
            for s in SCALES:
                initialized[s] += info[s]["initialized"]
                clips[s] += info[s]["clips"]
                clips_used[s] += info[s]["clips_used"]
    finally:
        if detector is not None:
            detector.close()
    trajs = _concat(parts)
    extra = {
        "initialized_points": {str(s): initialized[s] for s in SCALES},
        "clips": {str(s): clips[s] for s in SCALES},
        "clips_used": {str(s): clips_used[s] for s in SCALES},
        # 초기화한 점 가운데 클립 끝까지 추적된 비율. 점이 없으면 null
        "tracking_success_rate": {
            str(s): (len(trajs[s]) / initialized[s] if initialized[s] else None) for s in SCALES
        },
    }
    return trajs, extra


def _landmark_variant(segment_frames) -> tuple[dict[str, dict[int, np.ndarray]], dict]:
    """후보 C: 얼굴 특징점 궤적. 클립의 모든 프레임에서 얼굴이 잡혀야 그 클립을 쓴다."""
    import faces

    regions = faces.landmark_regions()
    tracker = faces.FaceLandmarkTracker()
    parts: dict[str, list[dict[int, np.ndarray]]] = {r: [] for r in FACE_MOTION_REGIONS}
    clips = {s: 0 for s in SCALES}
    clips_used = {s: 0 for s in SCALES}
    frames_total = frames_with_face = 0
    try:
        for sf in segment_frames:
            lms = [tracker.landmarks(f) for f in sf.frames]
            frames_total += len(lms)
            frames_with_face += sum(1 for x in lms if x is not None)
            per_region: dict[str, dict[int, list]] = {r: {s: [] for s in SCALES} for r in FACE_MOTION_REGIONS}
            for s in SCALES:
                for start, stop in tracking.clip_ranges(len(lms), s):
                    clips[s] += 1
                    window = lms[start:stop]
                    if any(x is None for x in window):
                        continue
                    clips_used[s] += 1
                    for name, traj in faces.region_trajectories(np.stack(window), regions).items():
                        per_region[name][s].append(traj)
            for r in FACE_MOTION_REGIONS:
                parts[r].append({
                    s: (np.concatenate(per_region[r][s], axis=0) if per_region[r][s] else np.empty((0, s, 2)))
                    for s in SCALES
                })
    finally:
        tracker.close()
    extra = {
        "clips": {str(s): clips[s] for s in SCALES},
        "clips_used": {str(s): clips_used[s] for s in SCALES},
        "frames_sampled": frames_total,
        "frames_with_face": frames_with_face,
        "face_detection_rate": frames_with_face / frames_total if frames_total else None,
        "landmarks_per_region": {r: len(regions[r]) for r in FACE_MOTION_REGIONS},
    }
    return {r: _concat(parts[r]) for r in FACE_MOTION_REGIONS}, extra


def extract(
    video: Path,
    segments: Sequence[Sequence[float]],
    variant: str = "full",
    config: tracking.TrackingConfig = tracking.TrackingConfig(),
    limits: Limits = Limits(),
) -> dict:
    """영상과 시간 구간 → 특징 벡터와 유효 궤적 수. 예외를 던지지 않고 status로 돌려준다."""
    t0 = time.perf_counter()
    base = {
        "schema_version": SCHEMA_VERSION,
        "variant": variant,
        "features": None,           # 실패했거나 계산하지 못한 특징은 null이다
        "feature_dim": None,
        "reimplementation": True,   # 공개 코드가 없어 논문만 보고 재구현했다
    }

    def fail(status: str, reason: str, detail: str = "", **extra) -> dict:
        return {**base, "status": status, "reason_code": reason, "detail": detail, **extra,
                "timing": {"total_sec": round(time.perf_counter() - t0, 4)}}

    if variant not in VARIANTS:
        return fail(ERROR, "invalid_request", f"variant는 {VARIANTS} 중 하나여야 한다")
    try:
        segs = _check_segments(segments)
    except (ValueError, TypeError) as e:
        return fail(ERROR, "invalid_request", str(e))
    if not segs:
        return fail(INSUFFICIENT_INPUT, "no_segments")
    video = Path(video)
    if not video.is_file():
        return fail(ERROR, "media_unreadable", "영상 파일 없음")

    try:
        segment_frames = [tracking.read_segment_frames(video, a, b, config) for a, b in segs]
        usable = [sf for sf in segment_frames if len(sf.frames) >= min(SCALES)]
        segment_info = [
            {"start_sec": a, "end_sec": b, "frames_sampled": len(sf.frames), "frame_step_sec": sf.step_sec}
            for (a, b), sf in zip(segs, segment_frames)
        ]
        common = {
            "segments": segment_info,
            "config": asdict(config),
            "limits": asdict(limits),
            "processing_scale": segment_frames[0].scale,
        }
        if not usable:
            return fail(INSUFFICIENT_INPUT, "segment_too_short", "8프레임 이상인 구간이 없음", **common)

        if variant == "face_motion":
            by_region, extra = _landmark_variant(usable)
            summaries = {r: _summary(by_region[r], config) for r in FACE_MOTION_REGIONS}
            # 머리가 움직였는지만 움직임 기준으로 본다. 눈썹·입술은 상대 좌표라 움직임이 작다
            reason = _decide({r: summaries[r] for r in FACE_MOTION_REGIONS}, Limits(limits.min_valid_per_scale, 0)) \
                or _decide({"head": summaries["head"]}, limits)
            counts = {"by_region": summaries}
            build = lambda: np.concatenate([_features_from(by_region[r]) for r in FACE_MOTION_REGIONS])  # noqa: E731
        else:
            trajs, extra = _point_variant(usable, variant, config)
            summary = _summary(trajs, config)
            reason = _decide({"all": summary}, limits)
            counts = {"by_scale": summary}
            build = lambda: _features_from(trajs)  # noqa: E731

        if reason is not None:
            return fail(INSUFFICIENT_INPUT, reason, **common, **counts, **extra)
        features = build()
        if not np.all(np.isfinite(features)):
            return fail(ERROR, "non_finite_feature", **common, **counts, **extra)
    except tracking.MediaError as e:
        return fail(ERROR, "media_unreadable", str(e))
    except Exception as e:  # 한 축의 실패가 호출자까지 번지지 않게 한다
        return fail(ERROR, "extraction_error", type(e).__name__)

    return {
        **base,
        "status": COMPLETED,
        "reason_code": None,
        "features": [float(x) for x in features],
        "feature_dim": int(features.size),
        **common, **counts, **extra,
        "timing": {"total_sec": round(time.perf_counter() - t0, 4)},
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    opt = p.parse_args(argv)
    try:
        req = json.loads(opt.request.read_text(encoding="utf-8"))
        result = extract(Path(req["video"]), req["segments"], req.get("variant", "full"))
    except (OSError, ValueError, KeyError, TypeError) as e:
        result = {"schema_version": SCHEMA_VERSION, "status": ERROR, "reason_code": "invalid_request",
                  "detail": type(e).__name__, "features": None}
    tmp = opt.output.with_suffix(opt.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    os.replace(tmp, opt.output)
    return 0 if result["status"] == COMPLETED else 1


if __name__ == "__main__":
    sys.exit(main())
