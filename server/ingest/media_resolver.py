"""AuthorizedMediaRegistry: 설정 파일에 등록된 video ID만 허가 미디어로 본다.

임의 URL을 내려받지 않는다. 등록되지 않은 ID는 None을 돌려주고,
호출자는 analysis_unavailable / access_not_authorized로 끝낸다.
이 단계(백로그 4번)에서는 다운로드가 stub이라 실제 미디어 파일을 다루지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from server.ingest.youtube_url import is_valid_video_id

DEFAULT_PROVENANCE = "registered_authorized_source"


@dataclass(frozen=True)
class AuthorizedMedia:
    youtube_video_id: str
    provenance: str


class AuthorizedMediaRegistry:
    def __init__(self, entries: dict[str, AuthorizedMedia]):
        self._entries = dict(entries)

    @classmethod
    def from_file(cls, path: Path) -> "AuthorizedMediaRegistry":
        """파일이 없으면 빈 레지스트리다(모든 ID가 미허가)."""
        if not Path(path).is_file():
            return cls({})
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entries: dict[str, AuthorizedMedia] = {}
        for item in data.get("authorized_media", []):
            video_id = item.get("youtube_video_id")
            if not is_valid_video_id(video_id):
                raise ValueError("authorized_media에 형식이 잘못된 video ID가 있다")
            entries[video_id] = AuthorizedMedia(
                youtube_video_id=video_id,
                provenance=item.get("provenance", DEFAULT_PROVENANCE),
            )
        return cls(entries)

    def resolve(self, video_id: str) -> Optional[AuthorizedMedia]:
        return self._entries.get(video_id)
