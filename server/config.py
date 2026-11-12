"""런타임 설정. 환경 변수(TRINITY_*)로 덮어쓴다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
        )
