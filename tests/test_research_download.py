"""연구용 다운로드 입출력 경계. 외부 네트워크나 설치된 yt-dlp를 쓰지 않는다."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.ingest import research_download as download


@pytest.mark.parametrize(("message", "reason"), [
    ("Sign in to confirm you’re not a bot", "download_blocked"),
    ("This video is not available in your country", "download_blocked"),
    ("Private video. Sign in if you have been granted access", "video_private"),
    ("Sign in to confirm your age", "age_restricted"),
    ("Video unavailable. This video has been removed", "video_removed"),
    ("Requested format is not available", "no_suitable_format"),
    ("Connection reset by peer", "download_network_error"),
    ("Video unavailable", "download_failed"),
])
def test_messages(message, reason):
    assert download.classify_error(message) == reason


def test_invalid_id_cannot_start_process(tmp_path):
    with pytest.raises(download.DownloadError, match="download_failed"):
        download.fetch("https://youtu.be/12345678901", tmp_path,
                       SimpleNamespace(research_download_enabled=True), lambda: True)


def test_denied_when_disabled(tmp_path):
    with pytest.raises(download.DownloadError, match="access_not_authorized"):
        download.fetch("12345678901", tmp_path, SimpleNamespace(research_download_enabled=False),
                       lambda: True)


@pytest.fixture
def offline(tmp_path):
    # Fake executables store the argv only in the test-controlled directory.
    import sys
    deno = tmp_path / "deno"
    deno.write_text("#!/bin/sh\necho 'deno 2.3.0 (release)'\n")
    deno.chmod(0o700)
    exe = tmp_path / "yt-dlp"
    exe.write_text(f"#!{sys.executable}\n" + """
import json, sys
from pathlib import Path
base = Path(__file__).parent
args = sys.argv[1:]
with (base/'calls').open('a') as f:
    f.write(json.dumps(args) + '\\n')
if '--version' in args:
    print('2026.11.23')
elif '--skip-download' in args:
    print((base/'metadata').read_text())
elif '-o' in args:
    dest = Path(args[args.index('-o')+1].replace('%(ext)s', 'mp4'))
    dest.write_bytes(b'test media')
""")
    exe.chmod(0o700)
    job = tmp_path / "job"
    job.mkdir()
    (tmp_path / "metadata").write_text("not_live\t42\t1920\t1080\t0\tpublic")
    return job, SimpleNamespace(research_download_enabled=True, download_executable=exe,
                                deno_executable=deno, download_timeout_seconds=30,
                                heartbeat_interval_seconds=.1)


def test_short_video_command_and_probe(offline, monkeypatch):
    import json
    job, settings = offline
    monkeypatch.setattr(download, "probe", lambda *a, **kw: SimpleNamespace(
        duration_sec=42, width=1920, height=1080, has_audio=True))
    path, window = download.fetch("A1b2C3d4E5f", job, settings, lambda: True)
    assert path.is_file() and path.parent == job
    assert (window.duration_sec, window.start_sec, window.end_sec) == (42, 0, 42)
    calls = [json.loads(line) for line in (job.parent / "calls").read_text().splitlines()]
    for args in calls[1:]:
        assert args[-2:] == ["--", "https://www.youtube.com/watch?v=A1b2C3d4E5f"]
        assert {"--ignore-config", "--no-cache-dir", "--no-playlist"} <= set(args)
        assert args[args.index("--js-runtimes")+1] == f"deno:{settings.deno_executable}"
        assert not any("cookies" in arg for arg in args)
    assert "--download-sections" not in calls[-1]


@pytest.mark.parametrize(("meta","reason"), [("is_live\tNA\tNA\tNA\tNA\tpublic", "live_not_supported"),
                                            ("not_live\t1801\t1920\t1080\t0\tpublic", "video_too_long")])
def test_refuse_before_media_request(offline, meta, reason):
    job, settings = offline
    (job.parent / "metadata").write_text(meta)
    with pytest.raises(download.DownloadError, match=reason):
        download.fetch("A1b2C3d4E5f", job, settings, lambda: True)
    assert not list(job.glob("download.*"))


def test_old_deno_refused_before_youtube(offline):
    job, settings = offline
    settings.deno_executable.write_text("#!/bin/sh\necho 'deno 2.2.9'\n")
    with pytest.raises(download.DownloadError, match="download_failed"):
        download.fetch("A1b2C3d4E5f", job, settings, lambda: True)
    assert not (job.parent / "calls").exists()


def test_missing_audio(offline, monkeypatch):
    job, settings = offline
    monkeypatch.setattr(download, "probe", lambda *a, **kw: SimpleNamespace(
        duration_sec=42, width=1920, height=1080, has_audio=False))
    with pytest.raises(download.DownloadError, match="no_suitable_format"):
        download.fetch("A1b2C3d4E5f", job, settings, lambda: True)


def test_long_download_requests_only_selected_section(offline, monkeypatch):
    import json
    job, settings = offline
    (job.parent / "metadata").write_text("not_live\t150\t1080\t1920\t0\tpublic")

    def choose(path, duration, directory, config, tick):
        assert path.is_file() and duration == 150 and tick()
        return download.Window(150, 34, 94)

    monkeypatch.setattr(download, "select_audio_window", choose)
    monkeypatch.setattr(download, "probe", lambda *a, **kw: SimpleNamespace(
        duration_sec=60, width=1080, height=1920, has_audio=True))
    path, window = download.fetch("A1b2C3d4E5f", job, settings, lambda: True)
    assert path.is_file() and window.start_sec == 34
    assert not list(job.glob("speech.*"))
    commands = [json.loads(line) for line in (job.parent / "calls").read_text().splitlines()]
    assert commands[-2][commands[-2].index("-f") + 1] == "ba"
    assert commands[-1][commands[-1].index("--download-sections") + 1] == "*34.000-94.000"


def test_failed_audio_selection_has_scrubbed_download_reason(offline, monkeypatch):
    from server.ingest.speech_window import WindowError
    job, settings = offline
    (job.parent / "metadata").write_text("not_live\t150\t1080\t1920\t0\tpublic")
    def fail(*args):
        raise WindowError("media_unreadable")
    monkeypatch.setattr(download, "select_audio_window", fail)
    with pytest.raises(download.DownloadError, match="no_suitable_format"):
        download.fetch("A1b2C3d4E5f", job, settings, lambda: True)
    assert not list(job.glob("speech.*"))


@pytest.mark.parametrize("timeout", [False, True], ids=["cancel", "deadline"])
def test_downloader_process_group_is_stopped(offline, timeout):
    import os
    import time
    job, settings = offline
    settings.download_executable.write_text(
        "#!/bin/sh\necho $$ > \"$HOME/download-pid\"\nexec sleep 60\n"
    )
    settings.download_timeout_seconds = 1 if timeout else 30
    pid_file = job / "download-pid"
    started = time.monotonic()
    with pytest.raises(download.DownloadError, match="download_network_error" if timeout else "download_failed"):
        download.fetch("A1b2C3d4E5f", job, settings, lambda: timeout or not pid_file.exists())
    assert time.monotonic() - started < 5
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
