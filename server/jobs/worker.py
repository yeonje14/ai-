"""단일 Worker 프로세스. 추론은 여기서만 한다(FastAPI 핸들러에서 하지 않는다).

실행: python -m server.jobs.worker          # 계속 대기하며 처리
      python -m server.jobs.worker --drain  # 대기열이 빌 때까지만 처리하고 종료

로그에는 analysis_id와 단계명만 남긴다. URL, 인증값, 영상 내용은 남기지 않는다.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import socket
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from server import fusion
from server.axes import AxisContext, alignment, physics, signal as signal_axis
from server.config import Settings
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.ingest.youtube_url import is_valid_video_id
from server.jobs.queue import LEASE_CANCEL, LEASE_LOST, Job, JobQueue
from server.schemas import AnalysisResult, dump

log = logging.getLogger("trinity.worker")

ACCESS_NOT_AUTHORIZED = "access_not_authorized"
VIDEO_ACCESS_UNAVAILABLE = "video_access_unavailable"
GATE_BYPASSED = "gate_bypassed"

_UNAVAILABLE_EXPLANATIONS = {
    ACCESS_NOT_AUTHORIZED: (
        "ACCESS_NOT_AUTHORIZED",
        "분석이 허가된 미디어로 등록되지 않은 영상이라 분석하지 않았습니다.",
    ),
    VIDEO_ACCESS_UNAVAILABLE: (
        "VIDEO_ACCESS_UNAVAILABLE",
        "허가된 영상이지만 분석할 미디어 파일에 접근할 수 없어 분석하지 않았습니다.",
    ),
}

# (진행 단계명, 결과의 축 이름, 축 실행 함수 모듈)
AXES = (
    ("waverep", "signal", signal_axis),
    ("motionphys", "physics", physics),
    ("syncnet", "alignment", alignment),
)


class _LeaseLost(Exception):
    pass


class _Cancelled(Exception):
    pass


class _Timeout(Exception):
    pass


def _empty_coverage() -> dict[str, Any]:
    return {
        "video_duration_sec": None,
        "eligible_duration_sec": None,
        "analyzed_duration_sec": None,
        "full_video_coverage": None,
        "eligible_coverage": None,
        "analyzed_segments": [],
    }


def build_coverage(
    media_info: dict[str, Any],
    segments: tuple[tuple[float, float], ...],
    signal_completed: bool,
) -> dict[str, Any]:
    """분석한 양만 적는다(정확도·신뢰도가 아니다). 알 수 없는 값은 null이다.

    Gate가 없으므로 적합 구간(eligible_*)은 알 수 없다. 분석한 구간은 signal 축이
    실제로 끝낸 구간을 영상 길이에 맞춰 자르고 겹친 부분을 합친 것이다.
    """
    coverage = _empty_coverage()
    fps, frame_count = media_info.get("fps"), media_info.get("frame_count")
    if not (isinstance(fps, (int, float)) and isinstance(frame_count, int) and fps > 0 and frame_count > 0):
        return coverage
    duration = frame_count / fps
    coverage["video_duration_sec"] = round(duration, 3)
    if not signal_completed:
        return coverage
    merged: list[list[float]] = []
    for start, end in sorted((s, min(e, duration)) for s, e in segments if s < duration):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    analyzed = sum(end - start for start, end in merged)
    coverage["analyzed_segments"] = [
        {"start_sec": round(start, 3), "end_sec": round(end, 3)} for start, end in merged
    ]
    coverage["analyzed_duration_sec"] = round(analyzed, 3)
    coverage["full_video_coverage"] = round(analyzed / duration, 4)
    return coverage


def _axis_not_run(axis_name: str, reason_code: str, status: str) -> dict[str, Any]:
    if axis_name == "alignment":
        return {
            "status": status,
            "reason_code": reason_code,
            "lse_c": None,
            "lse_d": None,
            "included_in_fusion": False,
        }
    return {"status": status, "reason_code": reason_code, "raw_score": None}


def build_unavailable_result(job: Job, reason_code: str) -> dict[str, Any]:
    return {
        "analysis_id": job.analysis_id,
        "youtube_video_id": job.youtube_video_id,
        "job_status": "finished",
        "analysis_status": "analysis_unavailable",
        "verdict_status": "abstained",
        "verdict_label": None,
        "overall_score": None,
        "abstention_reason": reason_code,
        "reason_code": reason_code,
        "media_provenance": None,
        "coverage": _empty_coverage(),
        "axes": {
            name: _axis_not_run(name, reason_code, "insufficient_input")
            for _, name, _ in AXES
        },
        "explanations": [
            {
                "template_id": _UNAVAILABLE_EXPLANATIONS[reason_code][0],
                "reason_code": reason_code,
                "message": _UNAVAILABLE_EXPLANATIONS[reason_code][1],
            }
        ],
    }


def build_result(
    job: Job,
    provenance: str,
    axes: dict[str, dict[str, Any]],
    fused: dict[str, Any],
    coverage: dict[str, Any] | None = None,
    gate_bypassed: bool = False,
) -> dict[str, Any]:
    all_completed = all(a["status"] == "completed" for a in axes.values())
    explanations = [
        {
            "template_id": "NO_VALID_FUSION",
            "reason_code": fused["abstention_reason"],
            "message": "검증된 종합 판정 모델이 없어 판단을 보류합니다.",
        }
    ]
    if gate_bypassed:
        explanations.append(
            {
                "template_id": "GATE_BYPASSED_DEV",
                "reason_code": GATE_BYPASSED,
                "message": "개발용 수동 구간으로 발화 구간 확인을 건너뛴 결과라 판단에 쓸 수 없습니다.",
            }
        )
    return {
        "analysis_id": job.analysis_id,
        "youtube_video_id": job.youtube_video_id,
        "job_status": "finished",
        # Gate를 건너뛴 결과는 축이 모두 끝났어도 partial이고 판정하지 않는다.
        "analysis_status": "completed" if all_completed and not gate_bypassed else "partial",
        "verdict_status": "abstained" if gate_bypassed else fused["verdict_status"],
        # 검증된 결합 모델이 없으므로 라벨을 붙이지 않는다 (README §9)
        "verdict_label": None,
        "overall_score": None if gate_bypassed else fused["overall_score"],
        "abstention_reason": fused["abstention_reason"],
        "reason_code": None,
        "media_provenance": provenance,
        "gate_bypassed": gate_bypassed,
        "coverage": coverage if coverage is not None else _empty_coverage(),
        "axes": axes,
        "explanations": explanations,
    }


def run_axis(
    axis_name: str, fn: Callable[[AxisContext], dict[str, Any]], ctx: AxisContext
) -> dict[str, Any]:
    """한 축이 실패해도 나머지 축은 계속 처리한다. 실패한 축의 점수는 null이다."""
    try:
        return fn(ctx)
    except Exception:
        log.exception("axis failed: %s", axis_name)
        return _axis_not_run(axis_name, "inference_error", "error")


def process(
    job: Job,
    queue: JobQueue,
    registry: AuthorizedMediaRegistry,
    settings: Settings,
    worker_id: str,
) -> None:
    deadline = time.monotonic() + settings.job_timeout_seconds
    completed: list[str] = []
    # 모델에는 서버가 발급한 analysis_id로 만든 작업 경로만 넘긴다.
    job_dir = settings.runtime_dir / job.analysis_id

    def enter(stage: str) -> None:
        if time.monotonic() > deadline:
            raise _Timeout()
        state = queue.advance_stage(
            job.analysis_id, worker_id, stage, completed, settings.lease_seconds
        )
        if state == LEASE_LOST:
            raise _LeaseLost()
        if state == LEASE_CANCEL:
            raise _Cancelled()
        log.info("job %s stage %s", job.analysis_id, stage)
        if settings.stub_stage_delay_seconds > 0:
            time.sleep(settings.stub_stage_delay_seconds)

    interrupted: list[Exception] = []

    def heartbeat() -> bool:
        """긴 추론 중에 주기적으로 불린다. lease를 연장하고, 계속해도 되는지 돌려준다."""
        if time.monotonic() > deadline:
            interrupted.append(_Timeout())
            return False
        try:
            state = queue.heartbeat(job.analysis_id, worker_id, settings.lease_seconds)
        except sqlite3.Error:
            # 한 번의 실패로 추론을 버리지 않는다. 계속 실패하면 lease가 만료되어 다음 단계에서 멈춘다.
            log.warning("job %s heartbeat failed", job.analysis_id)
            return True
        if state == LEASE_LOST:
            interrupted.append(_LeaseLost())
            return False
        if state == LEASE_CANCEL:
            interrupted.append(_Cancelled())
            return False
        return True

    def finalize(result: dict[str, Any]) -> None:
        enter("finalizing")
        validated = dump(AnalysisResult.model_validate(result))
        completed.append("finalizing")
        if not queue.finish(job.analysis_id, worker_id, validated, completed):
            raise _LeaseLost()

    try:
        enter("validating")
        if not is_valid_video_id(job.youtube_video_id):
            raise ValueError("invalid video id in queue")
        completed.append("validating")

        enter("access_check")
        media = registry.resolve(job.youtube_video_id)
        completed.append("access_check")
        if media is None:
            finalize(build_unavailable_result(job, ACCESS_NOT_AUTHORIZED))
            return
        if media.local_path is None or not media.local_path.is_file():
            # 등록은 됐지만 분석할 허가 미디어 파일이 없다. 내려받아 채우지 않는다.
            finalize(build_unavailable_result(job, VIDEO_ACCESS_UNAVAILABLE))
            return

        enter("preprocessing")
        # 허가 미디어를 작업 폴더로 복사한다. 모델에는 이 작업 폴더 안의 경로만 넘긴다.
        job_dir.mkdir(parents=True, exist_ok=True)
        media_path = job_dir / f"media{media.local_path.suffix.lower()}"
        shutil.copyfile(media.local_path, media_path)
        completed.append("preprocessing")

        # Gate는 아직 연결하지 않았다. 개발 전용 수동 구간이 켜져 있을 때만 구간이 있다.
        segments = settings.dev_manual_segments
        gate_bypassed = bool(segments)
        if gate_bypassed:
            log.warning("job %s gate bypassed by dev manual segments", job.analysis_id)

        ctx = AxisContext(
            job_dir=job_dir,
            settings=settings,
            media_path=media_path,
            segments=segments,
            heartbeat=heartbeat,
        )
        axes: dict[str, dict[str, Any]] = {}
        for stage, axis_name, module in AXES:
            enter(stage)
            ctx.timeout_seconds = max(deadline - time.monotonic(), 0.0)
            axes[axis_name] = run_axis(axis_name, module.run, ctx)
            if interrupted:
                # 추론 중에 lease를 잃었거나 취소·작업 타임아웃이 났다. 결과를 만들지 않는다.
                raise interrupted[0]
            completed.append(stage)

        enter("fusion")
        fused = fusion.fuse(axes)
        completed.append("fusion")

        coverage = build_coverage(
            ctx.media_info, segments, axes["signal"]["status"] == "completed"
        )
        finalize(build_result(job, media.provenance, axes, fused, coverage, gate_bypassed))
    except _LeaseLost:
        log.warning("job %s lease lost; abandoning", job.analysis_id)
    except _Cancelled:
        queue.mark_cancelled(job.analysis_id, worker_id)
        log.info("job %s cancelled", job.analysis_id)
    except _Timeout:
        queue.fail(job.analysis_id, worker_id, "timeout")
        log.warning("job %s timed out", job.analysis_id)
    except Exception:
        log.exception("job %s failed", job.analysis_id)
        queue.fail(job.analysis_id, worker_id, "worker_error")
    finally:
        # 임시 클립·오디오·얼굴 crop은 작업이 끝나면 삭제한다.
        shutil.rmtree(job_dir, ignore_errors=True)


def run_once(
    queue: JobQueue,
    registry: AuthorizedMediaRegistry,
    settings: Settings,
    worker_id: str,
) -> bool:
    """작업 하나를 선점해 처리한다. 처리할 작업이 없었으면 False."""
    job = queue.claim(worker_id, settings.lease_seconds, settings.max_attempts)
    if job is None:
        return False
    log.info("job %s claimed (attempt %d)", job.analysis_id, job.attempts)
    process(job, queue, registry, settings, worker_id)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TRINITY worker")
    parser.add_argument(
        "--drain", action="store_true", help="대기열이 비면 종료한다"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = Settings.from_env()
    queue = JobQueue(settings.db_path)
    queue.init_schema()
    registry = AuthorizedMediaRegistry.from_file(
        settings.authorized_media_path, settings.authorized_media_root
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    stop = False

    def _stop(signum: int, frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    if settings.dev_manual_segments:
        log.warning(
            "DEV ONLY: manual segments are on; gate is bypassed and every result is partial/abstained"
        )
    log.info("worker started")
    while not stop:
        worked = run_once(queue, registry, settings, worker_id)
        if not worked:
            if args.drain:
                break
            time.sleep(settings.poll_interval_seconds)
    log.info("worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
