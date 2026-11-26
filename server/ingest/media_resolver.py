"""AuthorizedMediaRegistry: 설정 파일에 등록된 video ID만 허가 미디어로 본다.

등록부에는 운영자가 미디어 루트 안의 상대 경로를 등록한다.
Worker가 등록 파일을 우선 사용하고 연구용 어댑터 사용 여부를 결정한다.
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
    # 허가 미디어 파일의 절대 경로. 등록만 되고 파일이 연결되지 않았으면 None.
    local_path: Optional[Path] = None


def _resolve_local_path(value: object, media_root: Optional[Path]) -> Path:
    if media_root is None:
        raise ValueError("local_path를 쓰려면 미디어 루트가 필요하다")
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("authorized_media의 local_path는 비어 있지 않은 문자열이어야 한다")
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("authorized_media의 local_path는 미디어 루트 안의 상대 경로여야 한다")
    root = Path(media_root).resolve()
    resolved = (root / rel).resolve()  # 심볼릭 링크로 루트 밖을 가리키는 것도 막는다
    if not resolved.is_relative_to(root):
        raise ValueError("authorized_media의 local_path가 미디어 루트 밖을 가리킨다")
    return resolved


class AuthorizedMediaRegistry:
    def __init__(self, entries: dict[str, AuthorizedMedia]):
        self._entries = dict(entries)

    @classmethod
    def from_file(
        cls, path: Path, media_root: Optional[Path] = None
    ) -> "AuthorizedMediaRegistry":
        """파일이 없으면 빈 레지스트리다(모든 ID가 미허가)."""
        if not Path(path).is_file():
            return cls({})
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entries: dict[str, AuthorizedMedia] = {}
        for item in data.get("authorized_media", []):
            video_id = item.get("youtube_video_id")
            if not is_valid_video_id(video_id):
                raise ValueError("authorized_media에 형식이 잘못된 video ID가 있다")
            local_path = None
            if item.get("local_path") is not None:
                local_path = _resolve_local_path(item["local_path"], media_root)
            entries[video_id] = AuthorizedMedia(
                youtube_video_id=video_id,
                provenance=item.get("provenance", DEFAULT_PROVENANCE),
                local_path=local_path,
            )
        return cls(entries)

    def resolve(self, video_id: str) -> Optional[AuthorizedMedia]:
        return self._entries.get(video_id)
