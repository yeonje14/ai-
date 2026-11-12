"""YouTube URL 정규화·허용 호스트 확인·video ID 추출.

네트워크 요청을 하지 않는다. 리디렉션을 따라가지 않는다.
허용 호스트 외의 호스트, IP, 사용자 정보, 포트, 로컬 경로는 모두 거부한다(SSRF 방지).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

MAX_URL_LENGTH = 2048
WATCH_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
SHORT_HOSTS = frozenset({"youtu.be"})
PATH_PREFIXES = ("shorts", "embed", "live")
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_FORBIDDEN_CHARS_RE = re.compile(r"[\s\\\x00-\x1f\x7f]")


class InvalidYouTubeUrl(ValueError):
    """입력이 허용된 YouTube URL 형식이 아니다."""


@dataclass(frozen=True)
class ParsedYouTubeUrl:
    video_id: str

    @property
    def canonical_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def is_valid_video_id(value: str) -> bool:
    return isinstance(value, str) and VIDEO_ID_RE.fullmatch(value) is not None


def parse_youtube_url(raw: str) -> ParsedYouTubeUrl:
    if not isinstance(raw, str):
        raise InvalidYouTubeUrl("not_a_string")
    url = raw.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise InvalidYouTubeUrl("bad_length")
    if _FORBIDDEN_CHARS_RE.search(url):
        raise InvalidYouTubeUrl("forbidden_characters")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise InvalidYouTubeUrl("unparseable") from exc

    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidYouTubeUrl("bad_scheme")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise InvalidYouTubeUrl("userinfo_not_allowed")
    if port is not None:
        raise InvalidYouTubeUrl("port_not_allowed")

    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]

    if host in SHORT_HOSTS:
        if len(segments) != 1:
            raise InvalidYouTubeUrl("bad_path")
        video_id = segments[0]
    elif host in WATCH_HOSTS:
        if segments == ["watch"]:
            values = parse_qs(parts.query).get("v", [])
            if len(values) != 1:
                raise InvalidYouTubeUrl("bad_video_param")
            video_id = values[0]
        elif len(segments) == 2 and segments[0] in PATH_PREFIXES:
            video_id = segments[1]
        else:
            raise InvalidYouTubeUrl("bad_path")
    else:
        raise InvalidYouTubeUrl("host_not_allowed")

    if not is_valid_video_id(video_id):
        raise InvalidYouTubeUrl("bad_video_id")
    return ParsedYouTubeUrl(video_id=video_id)
