"""런타임 설정. 환경 변수(TRINITY_*)로 덮어쓴다."""

from __future__ import annotations

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


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("data/runtime/trinity.sqlite3")
    runtime_dir: Path = Path("data/runtime/jobs")
    authorized_media_path: Path = Path("configs/authorized_media.json")
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

    def __post_init__(self) -> None:
        parse_cors_origins(",".join(self.cors_origins))  # 코드로 넣은 값도 같은 규칙으로 본다

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
        )
