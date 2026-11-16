"""런타임 설정. 환경 변수(TRINITY_*)로 덮어쓴다."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


# Flutter 웹 개발 서버의 기본 주소(app/README.md의 --web-port 8080)
DEFAULT_CORS_ORIGINS = ("http://localhost:8080", "http://127.0.0.1:8080")
_LOCAL_HOSTS = ("localhost", "127.0.0.1")


def parse_cors_origins(text: str) -> tuple[str, ...]:
    """쉼표로 구분한 출처 목록. localhost 개발 주소만 받는다. 와일드카드는 거부한다."""
    origins = []
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        parts = urlsplit(item)
        ok = (
            "*" not in item
            and parts.scheme in ("http", "https")
            and parts.hostname in _LOCAL_HOSTS
            and parts.path == "" and not parts.query and not parts.fragment
            and parts.username is None
            and item == f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")
        )
        if not ok:
            raise ValueError(
                f"TRINITY_CORS_ORIGINS에 쓸 수 없는 출처: {item!r}. "
                "http(s)://localhost[:포트] 또는 http(s)://127.0.0.1[:포트]만 받는다"
            )
        origins.append(item)
    return tuple(origins)


def parse_manual_segments(text: str) -> tuple[tuple[float, float], ...]:
    """개발 전용 수동 구간. "0-10,12.5-20"처럼 초 단위 시작-끝을 쉼표로 잇는다. 빈 문자열이면 꺼짐."""
    segments = []
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        try:
            start_text, end_text = item.split("-")
            start, end = float(start_text), float(end_text)
        except ValueError:
            raise ValueError(
                f"TRINITY_DEV_MANUAL_SEGMENTS 형식 오류: {item!r}. 예: 0-10,12.5-20"
            ) from None
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError(f"TRINITY_DEV_MANUAL_SEGMENTS: 0 <= 시작 < 끝 이어야 한다: {item!r}")
        segments.append((start, end))
    return tuple(segments)


def format_manual_segments(segments: tuple[tuple[float, float], ...]) -> str:
    return ",".join(f"{a}-{b}" for a, b in segments)


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("data/runtime/trinity.sqlite3")
    runtime_dir: Path = Path("data/runtime/jobs")
    authorized_media_path: Path = Path("configs/authorized_media.json")
    # Gate 모델 파일은 Git 밖에 둔다. 해시는 configs/gate_models.json과 대조한다.
    gate_model_dir: Path = Path("data/models/gate")
    gate_models_config_path: Path = Path("configs/gate_models.json")
    gate_timeout_seconds: float = 120.0
    # README §8 초기값: 동시 분석 1건(큐가 강제), 대기 3건. 실측 후 조정한다.
    max_queued: int = 3
    lease_seconds: float = 30.0
    max_attempts: int = 2
    job_timeout_seconds: float = 600.0
    poll_interval_seconds: float = 0.5
    # stub 단계 사이 지연(초). 단계 전이를 눈으로 확인할 때만 쓴다.
    stub_stage_delay_seconds: float = 0.0
    # 브라우저에서 API를 부를 수 있는 출처. 비우면 CORS를 켜지 않는다.
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    # 허가 미디어 파일을 두는 폴더. 레지스트리의 local_path는 이 폴더 안의 상대 경로여야 한다.
    authorized_media_root: Path = Path("data")
    # WaveRep 추론 (백로그 7번). 측정 근거: docs/waverep-adapter.md
    waverep_device: str = "mps"
    waverep_batch_size: int = 1
    waverep_sample_fps: float = 2.0
    waverep_timeout_seconds: float = 300.0
    # MotionPhys 특징 추출(후보 A·B·C)의 단계 제한 시간. 임시값이며 실측 후 조정한다.
    motionphys_timeout_seconds: float = 300.0
    # 추론을 기다리는 동안 lease를 연장하는 간격. lease_seconds보다 짧아야 한다.
    heartbeat_interval_seconds: float = 10.0
    # 검증된 모델 묶음(README §15.3 결정 5·8 보완). 묶음은 Git 밖, digest는 저장소에 커밋한 설정 파일에 둔다.
    fusion_bundle_dir: Path = Path("data/models/fusion")
    fusion_bundle_config_path: Path = Path("configs/fusion_bundle.json")
    # 합성 데이터로 만든 묶음 허용. 테스트 전용이며 환경 변수로는 켤 수 없다.
    allow_synthetic_bundle: bool = False
    # 개발 전용: Gate 대신 손으로 정한 구간을 분석한다. 기본은 꺼짐(빈 값).
    # 켜면 결과에 gate_bypassed=true가 남고 analysis_status=partial, verdict_status=abstained로 고정된다.
    dev_manual_segments: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        parse_cors_origins(",".join(self.cors_origins))  # 코드로 넣은 값도 같은 규칙으로 본다
        parse_manual_segments(format_manual_segments(self.dev_manual_segments))
        if not math.isfinite(self.gate_timeout_seconds) or self.gate_timeout_seconds <= 0:
            raise ValueError("gate_timeout_seconds는 유한한 양수여야 한다")
        if not 0 < self.heartbeat_interval_seconds < self.lease_seconds:
            raise ValueError("heartbeat_interval_seconds는 0보다 크고 lease_seconds보다 짧아야 한다")

    @classmethod
    def from_env(cls) -> "Settings":
        d = cls()
        env = os.environ.get
        return cls(
            db_path=Path(env("TRINITY_DB_PATH", str(d.db_path))),
            runtime_dir=Path(env("TRINITY_RUNTIME_DIR", str(d.runtime_dir))),
            authorized_media_path=Path(
                env("TRINITY_AUTHORIZED_MEDIA", str(d.authorized_media_path))
            ),
            gate_model_dir=Path(env("TRINITY_GATE_MODEL_DIR", str(d.gate_model_dir))),
            gate_models_config_path=Path(
                env("TRINITY_GATE_MODELS_CONFIG", str(d.gate_models_config_path))
            ),
            gate_timeout_seconds=float(env("TRINITY_GATE_TIMEOUT_SECONDS", d.gate_timeout_seconds)),
            max_queued=int(env("TRINITY_MAX_QUEUED", d.max_queued)),
            lease_seconds=float(env("TRINITY_LEASE_SECONDS", d.lease_seconds)),
            max_attempts=int(env("TRINITY_MAX_ATTEMPTS", d.max_attempts)),
            job_timeout_seconds=float(
                env("TRINITY_JOB_TIMEOUT_SECONDS", d.job_timeout_seconds)
            ),
            poll_interval_seconds=float(
                env("TRINITY_POLL_INTERVAL_SECONDS", d.poll_interval_seconds)
            ),
            stub_stage_delay_seconds=float(
                env("TRINITY_STUB_STAGE_DELAY_SECONDS", d.stub_stage_delay_seconds)
            ),
            cors_origins=parse_cors_origins(
                env("TRINITY_CORS_ORIGINS", ",".join(d.cors_origins))
            ),
            authorized_media_root=Path(
                env("TRINITY_AUTHORIZED_MEDIA_ROOT", str(d.authorized_media_root))
            ),
            waverep_device=env("TRINITY_WAVEREP_DEVICE", d.waverep_device),
            waverep_batch_size=int(env("TRINITY_WAVEREP_BATCH_SIZE", d.waverep_batch_size)),
            waverep_sample_fps=float(env("TRINITY_WAVEREP_SAMPLE_FPS", d.waverep_sample_fps)),
            waverep_timeout_seconds=float(
                env("TRINITY_WAVEREP_TIMEOUT_SECONDS", d.waverep_timeout_seconds)
            ),
            motionphys_timeout_seconds=float(
                env("TRINITY_MOTIONPHYS_TIMEOUT_SECONDS", d.motionphys_timeout_seconds)
            ),
            heartbeat_interval_seconds=float(
                env("TRINITY_HEARTBEAT_INTERVAL_SECONDS", d.heartbeat_interval_seconds)
            ),
            dev_manual_segments=parse_manual_segments(env("TRINITY_DEV_MANUAL_SEGMENTS", "")),
        )
