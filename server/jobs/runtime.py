"""서버 발급 UUID 작업 폴더만 정리한다. 미디어 원본과 DB는 삭제하지 않는다."""
from __future__ import annotations

import fcntl
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
import uuid
from pathlib import Path


current_worker_lock: ContextVar[int | None] = ContextVar("worker_lock_fd", default=None)

def remove_job_dir(runtime_dir: Path, analysis_id: str) -> None:
    if str(uuid.UUID(analysis_id)) != analysis_id:
        raise ValueError('invalid job directory id')
    path = runtime_dir / analysis_id
    # 최상위 링크를 따라 원본/다른 작업을 지우지 않는다.
    if path.is_symlink():
        path.unlink()
    else:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            if path.exists():
                raise


@contextmanager
def worker_lock(runtime_dir: Path):
    """살아 있는 이전 Worker와 복구 Worker가 같은 폴더를 사용하지 않게 한다.

    lease는 장애 복구의 기준, flock은 같은 호스트의 실행/정리 겹침 방지다.
    잠금 파일은 작업 폴더 밖에 유지한다. 삭제하면 다른 inode에 중복 잠금이 생긴다.
    """
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with (runtime_dir / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        token = current_worker_lock.set(lock.fileno())
        try:
            yield True
        finally:
            current_worker_lock.reset(token)
            fcntl.flock(lock, fcntl.LOCK_UN)
