"""큐 신뢰성: 원자적 선점, 중복 실행 방지, lease 복구, 재시도 상한, 취소, 타임아웃, 축 실패 격리."""

import sqlite3
import threading
from dataclasses import replace

from server.axes import signal as signal_axis
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.jobs import worker
from server.jobs.queue import LEASE_CANCEL, LEASE_LOST, LEASE_OK
from tests.conftest import REGISTERED_ID

OWNER = "owner-hash"


def _expire_lease(queue, analysis_id):
    conn = sqlite3.connect(queue.db_path)
    conn.execute("UPDATE jobs SET lease_expires_at = 0 WHERE analysis_id = ?", (analysis_id,))
    conn.commit()
    conn.close()


def test_claim_is_exclusive_and_single_concurrency(queue):
    first = queue.enqueue(REGISTERED_ID, OWNER, 3)
    queue.enqueue(REGISTERED_ID, OWNER, 3)

    claimed = []
    barrier = threading.Barrier(8)

    def _claim(i):
        barrier.wait()
        job = queue.claim(f"w{i}", 30, 2)
        if job:
            claimed.append(job.analysis_id)

    threads = [threading.Thread(target=_claim, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 동시 분석 1건: 여러 worker가 한꺼번에 선점해도 한 건만, 가장 오래된 것부터.
    assert claimed == [first]


def test_expired_lease_is_requeued_then_failed_after_max_attempts(queue):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)

    assert queue.claim("w1", 30, 2).attempts == 1
    _expire_lease(queue, aid)  # w1이 죽었다고 가정

    job = queue.claim("w2", 30, 2)  # 재시작 복구
    assert job.analysis_id == aid and job.attempts == 2

    # 죽은 줄 알았던 w1의 쓰기는 무시된다(중복 실행 방지).
    assert queue.advance_stage(aid, "w1", "waverep", [], 30) == LEASE_LOST
    assert queue.finish(aid, "w1", {"x": 1}, []) is False
    assert queue.advance_stage(aid, "w2", "waverep", [], 30) == LEASE_OK

    _expire_lease(queue, aid)
    assert queue.claim("w3", 30, 2) is None
    failed = queue.get(aid, OWNER)
    assert failed.job_status == "failed"
    assert failed.failure_reason == "max_attempts_exceeded"
    assert failed.result is None


def test_cancel_queued_and_processing(queue):
    a = queue.enqueue(REGISTERED_ID, OWNER, 3)
    b = queue.enqueue(REGISTERED_ID, OWNER, 3)

    assert queue.request_cancel(b, "someone-else") is False
    assert queue.request_cancel(b, OWNER) is True
    assert queue.get(b, OWNER).job_status == "cancelled"

    queue.claim("w1", 30, 2)
    assert queue.request_cancel(a, OWNER) is True
    assert queue.advance_stage(a, "w1", "validating", [], 30) == LEASE_CANCEL
    assert queue.mark_cancelled(a, "w1") is True
    assert queue.get(a, OWNER).job_status == "cancelled"
    assert queue.claim("w1", 30, 2) is None


def test_worker_cancels_between_stages(queue, settings, monkeypatch):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    registry = AuthorizedMediaRegistry.from_file(settings.authorized_media_path)

    def _cancel_during_waverep(job_dir):
        queue.request_cancel(aid, OWNER)
        return {"status": "insufficient_input", "raw_score": None}

    monkeypatch.setattr(signal_axis, "run", _cancel_during_waverep)
    assert worker.run_once(queue, registry, settings, "w1") is True

    job = queue.get(aid, OWNER)
    assert job.job_status == "cancelled"
    assert job.result is None
    assert not (settings.runtime_dir / aid).exists()


def test_worker_timeout_fails_job_without_result(queue, settings):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    registry = AuthorizedMediaRegistry.from_file(settings.authorized_media_path)

    worker.run_once(queue, registry, replace(settings, job_timeout_seconds=-1), "w1")

    job = queue.get(aid, OWNER)
    assert job.job_status == "failed"
    assert job.failure_reason == "timeout"
    assert job.result is None


def test_axis_failure_does_not_stop_other_axes(queue, settings, monkeypatch):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)
    registry = AuthorizedMediaRegistry.from_file(settings.authorized_media_path)

    def _boom(job_dir):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(signal_axis, "run", _boom)
    worker.run_once(queue, registry, settings, "w1")

    job = queue.get(aid, OWNER)
    assert job.job_status == "finished"
    axes = job.result["axes"]
    assert axes["signal"]["status"] == "error"
    assert axes["signal"]["reason_code"] == "inference_error"
    assert axes["signal"]["raw_score"] is None  # 0이 아니라 null
    assert axes["physics"]["status"] == "insufficient_input"
    assert axes["alignment"]["status"] == "insufficient_input"
    assert job.result["overall_score"] is None
    assert job.completed_stages[-1] == "finalizing"


def test_registry_missing_file_authorizes_nothing(tmp_path):
    registry = AuthorizedMediaRegistry.from_file(tmp_path / "nope.json")
    assert registry.resolve(REGISTERED_ID) is None
