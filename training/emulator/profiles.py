"""압축 프로파일 정의.

초기 실험값이다(README §6.2). YouTube 내부 설정이 아니며 플랫폼 처리본에서 추정한 값도 아니다.
ID 형식: x264-crf<CRF>-<source|1080p|720p|480p>. "<N>p"는 짧은 변의 픽셀 수다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

# 소프트웨어 인코더만 쓴다. 하드웨어 인코더(h264_videotoolbox 등)는 넣지 않는다 (AGENTS.md).
ALLOWED_ENCODERS = ("libx264",)
CRF_VALUES = (20, 28, 34)
SHORT_SIDES = (None, 1080, 720, 480)  # None은 해상도를 바꾸지 않는다


class ProfileError(ValueError):
    """프로파일이 없거나 허용하지 않는 설정이다."""


@dataclass(frozen=True)
class Profile:
    profile_id: str
    crf: int
    short_side: Optional[int]       # 목표 짧은 변(px). None이면 원본 해상도
    encoder: str = "libx264"
    preset: str = "medium"
    pix_fmt: str = "yuv420p"
    scale_flags: str = "bicubic"
    threads: int = 4                # 고정한다. 스레드 수가 달라지면 출력이 달라질 수 있다
    audio: str = "copy"             # 오디오 재인코딩은 별도 실험 축이다 (README §6.2)

    def __post_init__(self) -> None:
        if self.encoder not in ALLOWED_ENCODERS:
            raise ProfileError(f"허용하지 않는 인코더: {self.encoder!r}. 허용: {ALLOWED_ENCODERS}")
        if not 0 <= self.crf <= 51:
            raise ProfileError(f"crf는 0~51: {self.crf!r}")
        if self.short_side is not None and (self.short_side < 2 or self.short_side % 2):
            raise ProfileError(f"short_side는 2 이상의 짝수: {self.short_side!r}")
        if self.threads < 1:
            raise ProfileError("threads는 1 이상")
        if self.audio != "copy":
            raise ProfileError("오디오는 copy만 지원한다")

    def to_dict(self) -> dict:
        return asdict(self)


def _build() -> dict[str, Profile]:
    out = {}
    for crf in CRF_VALUES:
        for side in SHORT_SIDES:
            pid = f"x264-crf{crf}-{'source' if side is None else f'{side}p'}"
            out[pid] = Profile(profile_id=pid, crf=crf, short_side=side)
    return out


PROFILES: dict[str, Profile] = _build()


def get_profile(profile_id: str) -> Profile:
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise ProfileError(f"없는 프로파일: {profile_id!r}. 있는 것: {sorted(PROFILES)}") from None
