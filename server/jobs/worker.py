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
from server.gate import report as gate_report
from server.gate.runner import run_gate_process
from server.gate.types import GateResult
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.ingest.youtube_url import is_valid_video_id
from server.jobs.queue import LEASE_CANCEL, LEASE_LOST, Job, JobQueue
from server.jobs.runtime import remove_job_dir, worker_lock
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
    gate: GateResult | None = None,
) -> dict[str, Any]:
    """분석한 양만 적는다(정확도·신뢰도가 아니다). 알 수 없는 값은 null이다.

    Gate는 원본/적합 길이를 제공한다. analyzed_*는 signal 축이 성공한 경우만
    채우며, 디코딩한 길이를 넘지 않도록 자르고 겹친 구간을 합친다.
    개발용 수동 구간에서는 적합 구간(eligible_*)을 알 수 없다.
    """
    coverage = _empty_coverage()
    fps, frame_count = media_info.get("fps"), media_info.get("frame_count")
    decoded_duration = None
    if isinstance(fps, (int, float)) and isinstance(frame_count, int) and fps > 0 and frame_count > 0:
        decoded_duration = frame_count / fps
    if gate is not None:
        coverage.update(gate.coverage())
        coverage["analyzed_segments"] = []
        duration = gate.media.duration_sec if gate.media else None
    else:
        duration = decoded_duration
    if duration is None:
        return coverage
    coverage["video_duration_sec"] = round(duration, 3)
    if not signal_completed:
        return coverage
    merged: list[list[float]] = []
    analyzed_end = min(duration, decoded_duration) if decoded_duration is not None else duration
    for start, end in sorted((s, min(e, analyzed_end)) for s, e in segments if s < analyzed_end):
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
    eligible = coverage["eligible_duration_sec"]
    if eligible is not None and eligible > 0:
        coverage["eligible_coverage"] = round(analyzed / eligible, 4)
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
    if axes.get("alignment", {}).get("status") == "completed":
        explanations.append({
            "template_id": "SYNCNET_UNAGGREGATED", "reason_code": "unvalidated_condition",
            "message": "모든 Gate 적합 구간의 트랙별 동기화 지표 계산을 완료했습니다. 대표값 집계는 보류 중이며 진위 판정이나 발화자 동일인 확인을 뜻하지 않습니다.",
        })
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


def build_gate_rejection(job: Job, provenance: str, gate: GateResult) -> dict[str, Any]:
    reason = gate.reason_code
    analysis, verdict = gate_report.REJECTION_STATES[reason]
    error = reason in {"gate_error", "gate_timeout"}
    return {
        "analysis_id": job.analysis_id, "youtube_video_id": job.youtube_video_id,
        "job_status": "finished", "analysis_status": analysis, "verdict_status": verdict,
        "verdict_label": None, "overall_score": None,
        "abstention_reason": None if verdict == "not_applicable" else (
            "speaker_unconfirmed" if reason == "speaker_unconfirmed" else "insufficient_evidence"
        ),
        "reason_code": reason, "media_provenance": provenance, "gate_bypassed": False,
        "coverage": build_coverage({}, (), False, gate),
        "axes": {name: _axis_not_run(name, reason, "error" if error else "insufficient_input")
                 for _, name, _ in AXES},
        "explanations": gate_report.explanations(gate),
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
    terminal_status = None
    terminal_result = None
    failure_reason = None
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
        delay_end = time.monotonic() + settings.stub_stage_delay_seconds
        while time.monotonic() < delay_end:
            time.sleep(max(0, min(settings.heartbeat_interval_seconds, delay_end - time.monotonic())))
            if not heartbeat():
                raise interrupted[0]

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
        nonlocal terminal_status, terminal_result
        enter("finalizing")
        terminal_result = dump(AnalysisResult.model_validate(result))
        completed.append("finalizing")
        terminal_status = "finished"

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
        segments = settings.dev_manual_segments
        gate_bypassed = bool(segments)
        gate = None
        if gate_bypassed:
            log.warning("job %s gate bypassed by dev manual segments", job.analysis_id)
        else:
            try:
                gate = run_gate_process(
                    media_path, job_dir, settings=settings,
                    timeout_seconds=max(deadline - time.monotonic(), 0.0), on_tick=heartbeat,
                )
            except Exception:
                # Gate 내부 실패는 작업 전체를 실패시키거나 내용을 로그에 노출하지 않는다.
                gate = GateResult(None, "gate_error")
            if interrupted:
                raise interrupted[0]
            segments = tuple((s.start_sec, s.end_sec) for s in gate.eligible_segments)
        completed.append("preprocessing")
        if gate is not None and not segments:
            finalize(build_gate_rejection(job, media.provenance, gate))
            return

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
            ctx.media_info, segments, axes["signal"]["status"] == "completed", gate
        )
        result = build_result(job, media.provenance, axes, fused, coverage, gate_bypassed)
        # 축 설명은 종합 보류 설명 바로 뒤에 둔다. 기존 항목의 순서는 그대로다.
        result["explanations"][1:1] = ctx.explanations
        if gate is not None:
            result["explanations"].extend(gate_report.explanations(gate))
        finalize(result)
    except _LeaseLost:
        log.warning("job %s lease lost; abandoning", job.analysis_id)
    except _Cancelled:
        terminal_status = "cancelled"
        log.info("job %s cancelled", job.analysis_id)
    except _Timeout:
        terminal_status, failure_reason = "failed", "timeout"
        log.warning("job %s timed out", job.analysis_id)
    except Exception:
        log.error("job %s failed", job.analysis_id)
        terminal_status, failure_reason = "failed", "worker_error"
    finally:
        # 종료 상태를 공개하기 전에 정리한다. 실패하면 processing으로 남겨 복구에서 재시도한다.
        remove_job_dir(settings.runtime_dir, job.analysis_id)
        if terminal_status == "finished":
            queue.finish(job.analysis_id, worker_id, terminal_result, completed)
        elif terminal_status == "cancelled":
            queue.mark_cancelled(job.analysis_id, worker_id)
        elif terminal_status == "failed":
            queue.fail(job.analysis_id, worker_id, failure_reason)


def run_once(
    queue: JobQueue,
    registry: AuthorizedMediaRegistry,
    settings: Settings,
    worker_id: str,
) -> bool:
    """작업 하나를 처리한다. 대기/다른 실행의 잠금/정리 실패로 처리하지 못하면 False."""
    with worker_lock(settings.runtime_dir) as acquired:
        if not acquired:
            return False
        cleanup = lambda aid: remove_job_dir(settings.runtime_dir, aid)
        try:
            # 서버 발급 UUID 이름만 정리 대상으로 삼는다. DB/잠금 파일은 건드리지 않는다.
            ids = []
            for path in settings.runtime_dir.iterdir():
                try:
                    if str(uuid.UUID(path.name)) == path.name:
                        ids.append(path.name)
                except ValueError:
                    continue
            queue.clean_inactive(ids, cleanup)
            job = queue.claim(worker_id, settings.lease_seconds, settings.max_attempts, cleanup)
            if job is None:
                return False
            log.info("job %s claimed (attempt %d)", job.analysis_id, job.attempts)
            process(job, queue, registry, settings, worker_id)
        except OSError:
            log.error("runtime cleanup or access failed; retry after recovery")
            return False
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
