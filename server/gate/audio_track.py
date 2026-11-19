"""오디오 트랙 선택. Gate VAD·SyncNet 구간 절단·압축 에뮬레이터가 같은 함수로 고른다.

규칙(docs/DESIGN.md §15.3 2026-11-19): 디코딩할 수 있는 오디오 트랙 가운데 default 표시가 있는 것
(여럿이면 index가 가장 작은 것). 없으면 디코딩할 수 있는 트랙 가운데 index가 가장 작은 것. 그것도 없으면 None.
세 경로는 고른 트랙을 `-map 0:<index>`로 명시해 쓴다. FFmpeg의 자동 선택(default·채널 수 기준)에 맡기지 않는다.

디코딩 가능 = ffprobe가 준 `codec_name`이 이 FFmpeg의 `-codecs` 목록에서 디코딩(D) 표시가 있는 오디오 코덱이다.
코덱 태그로 판단하지 않는다. Apple APAC(태그 `apac`)은 ffprobe에 `codec_name`이 없고,
`-codecs` 목록의 `apac`은 이름만 같은 다른 코덱(Marian's A-pac)이다.

표준 라이브러리만 쓴다(SyncNet venv의 실행기와 학습 코드도 import한다). 서브프로세스는 인자 리스트로만 실행하고,
미디어 내용이나 경로를 로그에 남기지 않는다.
"""

from __future__ import annotations

import functools
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Optional, Sequence

# 규칙이 바뀌면 이름을 바꾼다. 학습 특징 버전(캐시 키·묶음 확인)에 들어간다(training/features/extract.py)
RULE = "decodable-default-first-v1"
DEFAULT_TIMEOUT_SEC = 120.0


class AudioTrackError(RuntimeError):
    """ffprobe·ffmpeg를 실행하지 못했거나 출력을 읽지 못했다."""


@dataclass(frozen=True)
class AudioSelection:
    # 입력의 오디오 트랙 전부(index 순). 항목: index, codec_name, codec_tag_string, channels, sample_rate,
    # default, decodable. ffprobe가 모르는 값은 None이다
    streams: tuple[dict, ...]
    # 규칙이 고른 트랙(streams의 한 항목). 디코딩할 수 있는 트랙이 없으면 None
    selected: Optional[dict]

    @property
    def index(self) -> Optional[int]:
        return None if self.selected is None else self.selected["index"]


def _run(args: list[str], timeout_sec: float) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout_sec, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioTrackError(type(exc).__name__) from exc
    if proc.returncode != 0:
        raise AudioTrackError(f"{Path(args[0]).name} exit {proc.returncode}")
    return proc.stdout


def parse_decodable_audio_codecs(text: str) -> frozenset[str]:
    """`ffmpeg -codecs` 출력에서 디코딩(D)할 수 있는 오디오(A) 코덱 이름."""
    out, started = set(), False
    for line in text.splitlines():
        if not started:
            started = line.strip().startswith("---")
            continue
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] == "D" and parts[0][2] == "A":
            out.add(parts[1])
    return frozenset(out)


@functools.lru_cache(maxsize=4)
def decodable_audio_codecs(ffmpeg: str = "ffmpeg", timeout_sec: float = 30.0) -> frozenset[str]:
    """이 FFmpeg 빌드가 디코딩할 수 있는 오디오 코덱. 프로세스마다 한 번 읽는다(실패는 기억하지 않는다)."""
    codecs = parse_decodable_audio_codecs(_run([ffmpeg, "-hide_banner", "-codecs"], timeout_sec))
    if not codecs:
        raise AudioTrackError("no audio decoders listed")
    return codecs


def probe_audio_streams(path: Path, ffprobe: str = "ffprobe",
                        timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> list[dict]:
    """오디오 트랙 목록(index 순). index는 입력 전체의 스트림 번호라 `-map 0:<index>`에 그대로 쓴다."""
    stdout = _run([
        ffprobe, "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index,codec_name,codec_tag_string,channels,sample_rate"
        ":stream_disposition=default",
        "-of", "json", str(path),
    ], timeout_sec)
    try:
        raw = json.loads(stdout).get("streams", [])
        streams = [
            {"index": int(st["index"]), "codec_name": st.get("codec_name"),
             "codec_tag_string": st.get("codec_tag_string"), "channels": st.get("channels"),
             "sample_rate": st.get("sample_rate"),
             "default": bool((st.get("disposition") or {}).get("default"))}
            for st in raw
        ]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AudioTrackError("unreadable ffprobe output") from exc
    return sorted(streams, key=lambda st: st["index"])


def choose(streams: Sequence[dict], decodable: Collection[str]) -> Optional[dict]:
    """규칙만 담은 순수 함수. streams 항목에는 index, codec_name, default가 있어야 한다."""
    usable = sorted((st for st in streams if st.get("codec_name") in decodable), key=lambda st: st["index"])
    return next((st for st in usable if st.get("default")), usable[0] if usable else None)


def select_audio_stream(path: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
                        timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> AudioSelection:
    """path의 오디오 트랙을 규칙대로 고른다. 실행·해석 실패는 AudioTrackError다."""
    decodable = decodable_audio_codecs(ffmpeg)
    streams = tuple({**st, "decodable": st["codec_name"] in decodable}
                    for st in probe_audio_streams(path, ffprobe, timeout_sec))
    return AudioSelection(streams=streams, selected=choose(streams, decodable))
