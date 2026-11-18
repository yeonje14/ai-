"""실행기가 보고한 장치 이름 정리(내부 기록용, API 결과 아님)."""

from __future__ import annotations

from typing import Optional

# 실행기가 실제로 쓴 장치로 받아들이는 이름. 그 밖의 값은 로그·내부 기록에 원문을 남기지 않고 None으로 바꾼다
DEVICE_NAMES = ("cpu", "mps", "gpu")


def clean_device(value: object) -> Optional[str]:
    return value if isinstance(value, str) and value in DEVICE_NAMES else None
