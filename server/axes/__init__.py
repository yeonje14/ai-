"""축 실행에 넘기는 공통 입력."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from server.config import Settings


@dataclass
class AxisContext:
    # 서버가 발급한 작업 폴더. 모델 프로세스에는 이 안의 경로만 넘긴다.
    job_dir: Path
    settings: Settings = field(default_factory=Settings)
    # 작업 폴더로 복사한 허가 미디어. 없으면 None.
    media_path: Optional[Path] = None
    # 분석할 구간 [(start_sec, end_sec), ...]. Gate가 없으면 비어 있다.
    segments: tuple[tuple[float, float], ...] = ()
    # 추론을 기다리는 동안 주기적으로 부른다. False를 돌려주면 추론을 중단한다.
    heartbeat: Optional[Callable[[], bool]] = None
    # 이 축이 쓸 수 있는 최대 시간(초). 작업 전체 타임아웃의 남은 시간을 넘지 않는다.
    timeout_seconds: Optional[float] = None
    # 축이 읽어 낸 영상 정보(fps, frame_count 등). coverage 계산에만 쓴다.
    media_info: dict[str, Any] = field(default_factory=dict)
    # 검증을 통과한 모델 묶음(training.bundle.Bundle). 없으면 None이고 축은 지금까지와 똑같이 동작한다.
    bundle: Any = None
    # 결합 모델의 입력값(내부 전달용, API 결과가 아니다). 계산하지 못한 값은 넣지 않는다.
    fusion_inputs: dict[str, float] = field(default_factory=dict)
    # 축이 덧붙이는 설명(template_id, reason_code, message). 결과의 기존 explanations에 이어 붙인다.
    explanations: list[dict[str, str]] = field(default_factory=list)
    # 이 축의 실행기가 실제로 쓴 장치(cpu·mps·gpu). 실행기를 부르지 않았거나 보고가 없으면 None.
    # Worker 로그와 jobs의 내부 기록에만 쓴다(API 결과 아님). Worker가 축마다 None으로 되돌린다.
    device_used: Optional[str] = None
