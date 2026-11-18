"""서버(결합 판정)와 학습·리포트가 함께 쓰는 서빙 규칙 (docs/DESIGN.md §15.3 2026-11-18, 감사 A9). 표준 라이브러리만 쓴다.

- 축 성공: 축 상태가 completed인 축. 서버는 API 결과의 axes.*.status를, 학습은 features.jsonl의 축 상태를
  같은 함수(successful_axes)로 읽는다. MotionPhys 축 상태는 서버와 같이 full 변형(후보 A)의 상태다.
- 후보 고르기(choose):
  1) 선택 후보(primary)는 그 후보의 축이 모두 성공했고 입력이 모두 있으면 쓴다. 다른 축이 더 성공해도 쓴다.
  2) 아니면 성공한 축 집합과 정확히 같은 대체 후보(fallback) 가운데 입력이 모두 있는 것을 쓴다.
  3) 없으면 판정하지 않는다(보류).
- 대체 후보는 이 규칙으로 실제로 쓰일 test 영상(축 성공 패턴이 정확히 같은 영상)에서만 따로 검증한다(training/report).
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

# features.jsonl의 축 이름 → 서버 결과의 축 이름
SERVER_AXIS = {"waverep": "signal", "motionphys": "physics", "syncnet": "alignment"}
PRIMARY, FALLBACK = "primary", "fallback"
RULE = ("선택 후보는 축이 모두 성공하고 입력이 모두 있으면 사용한다. 아니면 성공한 축 집합이 정확히 같은 "
        "대체 후보를 쓴다. 없으면 보류한다.")


def successful_axes(statuses: Mapping[str, Optional[str]]) -> frozenset:
    """{축 이름: 상태} → 성공한(completed) 축. 서버와 학습이 같은 함수를 쓴다."""
    return frozenset(axis for axis, status in statuses.items() if status == "completed")


def feature_statuses(axes: Mapping[str, Mapping]) -> dict[str, Optional[str]]:
    """features.jsonl 한 줄의 axes → {서버 축 이름: 상태}. motionphys의 상태는 추출기가 full 변형 기준으로 적은 값이다."""
    return {SERVER_AXIS[name]: (value or {}).get("status") for name, value in axes.items() if name in SERVER_AXIS}


def choose(primary: Optional[tuple[str, frozenset]], fallbacks: Sequence[tuple[str, frozenset]],
           available: frozenset, usable: Callable[[str], bool]) -> Optional[str]:
    """이번 영상에 쓸 후보 이름. usable(이름)은 그 후보의 입력이 모두 있는지다. 없으면 None(보류)."""
    if primary is not None and primary[1] <= available and usable(primary[0]):
        return primary[0]
    for name, axes in fallbacks:
        if axes == available and usable(name):
            return name
    return None
