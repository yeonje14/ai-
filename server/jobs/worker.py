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
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from server import fusion
from server.axes import alignment, physics, signal as signal_axis
from server.config import Settings
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.ingest.youtube_url import is_valid_video_id
from server.jobs.queue import LEASE_CANCEL, LEASE_LOST, Job, JobQueue
from server.schemas import AnalysisResult, dump

log = logging.getLogger("trinity.worker")

ACCESS_NOT_AUTHORIZED = "access_not_authorized"

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
                "template_id": "ACCESS_NOT_AUTHORIZED",
                "reason_code": reason_code,
                "message": "분석이 허가된 미디어로 등록되지 않은 영상이라 분석하지 않았습니다.",
            }
        ],
    }


def build_result(
    job: Job, provenance: str, axes: dict[str, dict[str, Any]], fused: dict[str, Any]
) -> dict[str, Any]:
    all_completed = all(a["status"] == "completed" for a in axes.values())
    return {
        "analysis_id": job.analysis_id,
        "youtube_video_id": job.youtube_video_id,
        "job_status": "finished",
        "analysis_status": "completed" if all_completed else "partial",
        "verdict_status": fused["verdict_status"],
        "overall_score": fused["overall_score"],
        "abstention_reason": fused["abstention_reason"],
        "reason_code": None,
        "media_provenance": provenance,
        "coverage": _empty_coverage(),
        "axes": axes,
        "explanations": [
            {
                "template_id": "NO_VALID_FUSION",
                "reason_code": fused["abstention_reason"],
                "message": "검증된 종합 판정 모델이 없어 판단을 보류합니다.",
            }
        ],
    }


def run_axis(axis_name: str, fn: Callable[[Path], dict[str, Any]], job_dir: Path) -> dict[str, Any]:
    """한 축이 실패해도 나머지 축은 계속 처리한다. 실패한 축의 점수는 null이다."""
    try:
        return fn(job_dir)
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

        enter("preprocessing")
        # stub: 미디어를 내려받거나 만들지 않는다. 임시 작업 폴더만 만든다.
        job_dir.mkdir(parents=True, exist_ok=True)
        completed.append("preprocessing")

        axes: dict[str, dict[str, Any]] = {}
        for stage, axis_name, module in AXES:
            enter(stage)
            axes[axis_name] = run_axis(axis_name, module.run, job_dir)
            completed.append(stage)

        enter("fusion")
        fused = fusion.fuse(axes)
        completed.append("fusion")

        finalize(build_result(job, media.provenance, axes, fused))
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
    registry = AuthorizedMediaRegistry.from_file(settings.authorized_media_path)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    stop = False

    def _stop(signum: int, frame: Any) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

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
