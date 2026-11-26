"""졸업작품 연구용 Worker 입력 경로. 출력·오류에는 원문 URL이나 제목을 남기지 않는다."""
from __future__ import annotations

import math
import os
import re
import selectors
import subprocess
import time
from pathlib import Path
from typing import Callable

from server.config import Settings
from server.gate.probe import probe
from server.ingest.speech_window import WINDOW_SECONDS, Window, WindowError, select_audio_window
from server.ingest.youtube_url import ParsedYouTubeUrl, is_valid_video_id
from server.jobs.child_process import start_process, stop_process

_REPO = Path(__file__).resolve().parents[2]
MAX_BYTES = 256 * 1024 * 1024
MAX_SECONDS = 1800
PINNED_VERSION = "2026.11.23"
_MESSAGES = {
    "age_restricted": ("confirm your age", "age-restricted", "age restricted"),
    "video_private": ("private video", "video is private"),
    "video_removed": ("has been removed", "video was removed", "has been deleted",
                      "account associated with this video has been terminated"),
    "download_blocked": ("not a bot", "not available in your country", "geo-restricted",
                         "sign in", "login required", "members-only", "http error 403",
                         "http error 429"),
    "no_suitable_format": ("requested format is not available", "no video formats found"),
    "download_network_error": ("timed out", "connection reset", "connection refused",
                               "temporary failure in name resolution", "unable to resolve",
                               "nodename nor servname", "network is unreachable",
                               "remote end closed connection", "http error 503"),
}


class DownloadError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def classify_error(message: str) -> str:
    lowered = message.lower()
    for reason, fragments in _MESSAGES.items():
        if any(fragment in lowered for fragment in fragments):
            return reason
    return "download_failed"


def _check_size(job_dir: Path) -> None:
    total = 0
    for path in job_dir.rglob("*"):
        try:
            total += path.lstat().st_size
        except FileNotFoundError:  # yt-dlp/ffmpeg renames partial files during a download
            continue
        if total > MAX_BYTES:
            raise DownloadError("download_failed")


def _run(args, job_dir, deadline, on_tick):
    """두 파이프의 최근 16 KiB만 보관한다. 취소·제한·예외 모두 같은 그룹을 정리한다."""
    on_tick()
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(job_dir),
           "DENO_DIR": str(job_dir / ".deno"), "TMPDIR": str(job_dir)}
    proc, fd = start_process(args, cwd=_REPO, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = {"out": bytearray(), "err": bytearray()}
    try:
        with selectors.DefaultSelector() as pipes:
            pipes.register(proc.stdout, selectors.EVENT_READ, "out")
            pipes.register(proc.stderr, selectors.EVENT_READ, "err")
            next_check = 0.
            while pipes.get_map() or proc.poll() is None:
                now = time.monotonic()
                if now >= next_check:
                    _check_size(job_dir)
                    on_tick()
                    next_check = now + 0.25
                timeout = min(next_check, deadline) - now
                if timeout <= 0:
                    continue
                for key, _ in pipes.select(timeout):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        pipes.unregister(key.fd)
                        continue
                    buffer = buffers[key.data]
                    buffer.extend(chunk)
                    del buffer[:-16384]
        on_tick()
        _check_size(job_dir)
        if proc.returncode:
            raise DownloadError(classify_error(buffers["err"].decode(errors="replace")))
        return buffers["out"].decode(errors="replace").strip()
    finally:
        stop_process(proc, fd)
        proc.stdout.close()
        proc.stderr.close()


def _output(job_dir, prefix):
    files = [path for path in job_dir.glob(prefix + ".*")
             if path.suffix.lower() in {".webm", ".mkv", ".mp4", ".m4a", ".opus", ".ogg"}
             and path.stem == prefix and path.is_file() and not path.is_symlink()]
    if len(files) != 1 or files[0].stat().st_size == 0:
        raise DownloadError("no_suitable_format")
    return files[0]


def fetch(video_id: str, job_dir: Path, settings: Settings,
          on_tick: Callable[[], bool]) -> tuple[Path, Window]:
    if not settings.research_download_enabled:
        raise DownloadError("access_not_authorized")
    if not is_valid_video_id(video_id):
        raise DownloadError("download_failed")
    job_dir = job_dir.resolve(strict=True)
    deadline = time.monotonic() + settings.download_timeout_seconds

    def check():
        if not on_tick():
            raise DownloadError("download_failed")
        if time.monotonic() >= deadline:
            raise DownloadError("download_network_error")
        return True

    deno = str(Path(settings.deno_executable).absolute())
    exe = str(Path(settings.download_executable).absolute())
    options = [exe, "--ignore-config", "--no-plugin-dirs", "--no-cache-dir", "--no-playlist",
               "--no-geo-bypass", "--no-js-runtimes", "--js-runtimes", f"deno:{deno}",
               "--quiet", "--no-progress", "--socket-timeout", "30", "--retries", "2",
               "--max-filesize", str(MAX_BYTES), "--paths", str(job_dir)]
    url = ParsedYouTubeUrl(video_id).canonical_url

    def request(*args):
        return _run([*options, *args, "--", url], job_dir, deadline, check)

    try:
        version = _run([deno, "--version"], job_dir, deadline, check)
        match = re.match(r"^deno (\d+)\.(\d+)\.(\d+)(?:\s|$)", version)
        if not match or tuple(map(int, match.groups())) < (2, 3, 0):
            raise DownloadError("download_failed")
        if _run([exe, "--ignore-config", "--no-plugin-dirs", "--version"],
                job_dir, deadline, check) != PINNED_VERSION:
            raise DownloadError("download_failed")
        fields = request("--skip-download", "--print",
                         "%(live_status)s\t%(duration)s\t%(width)s\t%(height)s\t%(age_limit)s\t%(availability)s")
        live, duration_text, width, height, age, access = fields.split("\t")
        if live in {"is_live", "is_upcoming", "post_live"}:
            raise DownloadError("live_not_supported")
        if live not in {"was_live", "not_live"}:
            raise DownloadError("download_failed")
        if age != "NA" and float(age) >= 18:
            raise DownloadError("age_restricted")
        if access == "private":
            raise DownloadError("video_private")
        if access not in {"public", "unlisted", "NA"}:
            raise DownloadError("download_blocked")
        duration = float(duration_text)
        if not math.isfinite(duration) or duration <= 0:
            raise DownloadError("download_failed")
        if duration > MAX_SECONDS:
            raise DownloadError("video_too_long")
        # 세로와 가로 영상 모두 짧은 변 1080px 이하 형식만 요청한다.
        side = "height" if int(width) >= int(height) else "width"
        cap = f"[{side}<=1080]"
        sections = []
        window = Window(duration, 0, duration)
        guard = ["--match-filter", f"!is_live & duration <= {MAX_SECONDS} & age_limit <? 18"]
        if duration > WINDOW_SECONDS:
            request(*guard, "-f", "ba", "-o", str(job_dir / "speech.%(ext)s"))
            audio = _output(job_dir, "speech")
            try:
                window = select_audio_window(audio, duration, job_dir, settings, check)
            except WindowError as exc:
                check()
                reason = "no_suitable_format" if exc.code == "media_unreadable" else "download_failed"
                raise DownloadError(reason) from None
            finally:
                audio.unlink(missing_ok=True)
            sections = ["--download-sections", f"*{window.start_sec:.3f}-{window.end_sec:.3f}",
                        "--force-keyframes-at-cuts"]
        request(*guard, *sections, "-S", "res:1080", "-f", f"bv{cap}+ba/b{cap}",
                "--merge-output-format", "mkv", "-o", str(job_dir / "download.%(ext)s"))
        path = _output(job_dir, "download")
        check()
        info = probe(path, timeout_sec=min(5, max(.001, deadline - time.monotonic())))
        check()
        if (info is None or not info.has_audio or min(info.width, info.height) > 1080
                or not math.isfinite(info.duration_sec)
                or abs(info.duration_sec - (window.end_sec - window.start_sec)) > 1):
            raise DownloadError("no_suitable_format")
        if not sections:
            if info.duration_sec > WINDOW_SECONDS:
                raise DownloadError("no_suitable_format")
            window = Window(info.duration_sec, 0, info.duration_sec)
        return path, window
    except (OSError, ValueError, OverflowError):
        raise DownloadError("download_failed") from None
