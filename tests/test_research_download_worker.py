"""연구용 미디어 접근 경로를 실제 SQLite 작업 수명주기로 검증한다."""
from dataclasses import replace
from pathlib import Path

import pytest

from server.config import Settings
from server.gate.types import GateResult
from server.ingest.speech_window import Window
from server.jobs import worker
from tests.conftest import REGISTERED_ID, UNREGISTERED_ID

OWNER = "download-owner"


@pytest.fixture
def research_download():
    from server.ingest import research_download
    return research_download


def test_download_opt_in_settings(monkeypatch):
    monkeypatch.delenv("TRINITY_RESEARCH_DOWNLOAD", raising=False)
    assert Settings.from_env().research_download_enabled is False
    monkeypatch.setenv("TRINITY_RESEARCH_DOWNLOAD", "1")
    monkeypatch.setenv("TRINITY_DOWNLOAD_EXECUTABLE", "/opt/research/bin/yt-dlp")
    monkeypatch.setenv("TRINITY_DENO_EXECUTABLE", "/opt/bin/deno")
    monkeypatch.setenv("TRINITY_DOWNLOAD_TIMEOUT_SECONDS", "12")
    settings = Settings.from_env()
    assert settings.research_download_enabled is True
    assert settings.download_executable == Path("/opt/research/bin/yt-dlp")
    assert settings.deno_executable == Path("/opt/bin/deno")
    assert settings.download_timeout_seconds == 12


@pytest.mark.parametrize("reason,status", [
    ("download_blocked", "analysis_unavailable"),
    ("video_removed", "analysis_unavailable"),
    ("video_private", "analysis_unavailable"),
    ("age_restricted", "analysis_unavailable"),
    ("video_too_long", "unsupported"),
    ("live_not_supported", "unsupported"),
    ("download_network_error", "analysis_unavailable"),
    ("no_suitable_format", "analysis_unavailable"),
    ("download_failed", "analysis_unavailable"),
])
def test_download_reason_and_retry(queue, settings, registry, monkeypatch, research_download, reason, status):
    settings = replace(settings, research_download_enabled=True)
    aid = queue.enqueue(UNREGISTERED_ID, OWNER, 3)

    def failed_fetch(video_id, job_dir, settings, on_tick):
        assert queue.get(aid, OWNER).stage == "access_check"
        assert on_tick()
        (job_dir / "media.part").touch()
        raise research_download.DownloadError(reason)

    monkeypatch.setattr(research_download, "fetch", failed_fetch)
    assert worker.run_once(queue, registry, settings, "w")
    job = queue.get(aid, OWNER)
    assert not (settings.runtime_dir / aid).exists()
    if reason == "download_network_error":
        assert job.job_status == "queued"
        assert worker.run_once(queue, registry, settings, "w")
        job = queue.get(aid, OWNER)
        assert job.attempts == 2
    assert job.job_status == "finished"
    assert job.result["reason_code"] == reason
    assert job.result["analysis_status"] == status
    assert job.result["verdict_status"] == "abstained"
    assert job.result["overall_score"] is None
    assert not (settings.runtime_dir / aid).exists()


@pytest.mark.parametrize("video_id", [REGISTERED_ID, UNREGISTERED_ID])
def test_gate_receives_registered_or_fetched_media(queue, settings, registry, monkeypatch, research_download, video_id):
    settings = replace(settings, research_download_enabled=True)
    aid = queue.enqueue(video_id, OWNER, 3)
    expected = b"download fixture" if video_id == UNREGISTERED_ID else b"not a real video"

    def fetch(id_, job_dir, settings, on_tick):
        assert id_ == UNREGISTERED_ID
        path = job_dir / "download.mp4"
        path.write_bytes(expected)
        return path, Window(180, 80, 140)

    def gate(path, job_dir, **kwargs):
        assert path.parent == job_dir
        assert path.read_bytes() == expected
        return GateResult(None, "gate_timeout")

    monkeypatch.setattr(research_download, "fetch", fetch)
    monkeypatch.setattr(worker, "run_gate_process", gate)
    worker.run_once(queue, registry, settings, "w")
    result = queue.get(aid, OWNER).result
    assert result["reason_code"] == "gate_timeout"
    assert result["media_provenance"] == (
        "research_download" if video_id == UNREGISTERED_ID else "registered_authorized_source"
    )
    if video_id == UNREGISTERED_ID:
        assert result["coverage"]["video_duration_sec"] == 180
        assert any(e["template_id"] == "ANALYSIS_WINDOW" for e in result["explanations"])
    assert not (settings.runtime_dir / aid).exists()


def test_download_cancellation_precedes_network_retry(queue, settings, registry, monkeypatch, research_download):
    settings = replace(settings, research_download_enabled=True)
    aid = queue.enqueue(UNREGISTERED_ID, OWNER, 3)

    def cancel(id_, job_dir, settings, on_tick):
        (job_dir / "media.part").touch()
        queue.request_cancel(aid, OWNER)
        assert not on_tick()
        raise research_download.DownloadError("download_network_error")

    monkeypatch.setattr(research_download, "fetch", cancel)
    worker.run_once(queue, registry, settings, "w")
    assert queue.get(aid, OWNER).job_status == "cancelled"
    assert not (settings.runtime_dir / aid).exists()


def test_job_deadline_precedes_download_retry(queue, settings, registry, monkeypatch, research_download):
    settings = replace(settings, research_download_enabled=True)
    aid = queue.enqueue(UNREGISTERED_ID, OWNER, 3)

    def timeout(id_, job_dir, settings, on_tick):
        (job_dir / "media.part").touch()
        expired = worker.time.monotonic() + settings.job_timeout_seconds + 1
        monkeypatch.setattr(worker.time, "monotonic", lambda: expired)
        assert not on_tick()
        raise research_download.DownloadError("download_network_error")

    monkeypatch.setattr(research_download, "fetch", timeout)
    worker.run_once(queue, registry, settings, "w")
    job = queue.get(aid, OWNER)
    assert (job.job_status, job.failure_reason) == ("failed", "timeout")
    assert not (settings.runtime_dir / aid).exists()


def test_registered_window_with_network_disabled(queue, settings, registry, monkeypatch):
    aid = queue.enqueue(REGISTERED_ID, OWNER, 3)

    def prepare(path, job_dir, settings, on_tick):
        assert on_tick()
        clip = job_dir / "selected.mkv"
        clip.write_bytes(b"selected")
        return clip, Window(300, 100, 160)

    def gate(path, job_dir, **kwargs):
        assert path.read_bytes() == b"selected"
        return GateResult(None, "gate_timeout")

    monkeypatch.setattr(worker.speech_window, "prepare_window", prepare)
    monkeypatch.setattr(worker, "run_gate_process", gate)
    worker.run_once(queue, registry, settings, "w")
    result = queue.get(aid, OWNER).result
    assert result["coverage"]["video_duration_sec"] == 300
    assert result["reason_code"] == "gate_timeout"
