"""모델별 실행 명령을 그대로 유지하면서 Worker 비정상 종료까지 감시한다."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from server.jobs.runtime import current_worker_lock


def start_process(command: list[str], **kwargs: Any) -> tuple[subprocess.Popen, int]:
    read_fd, write_fd = os.pipe()
    lock_fd = current_worker_lock.get()
    inherited = (read_fd,) if lock_fd is None else (read_fd, lock_fd)
    try:
        proc = subprocess.Popen(
            [sys.executable, '-m', 'server.jobs.supervisor', str(read_fd), *command],
            pass_fds=inherited, start_new_session=True, **kwargs,
        )
    except BaseException:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    return proc, write_fd


def stop_process(proc: subprocess.Popen, write_fd: int) -> None:
    # close는 정상·취소·timeout 모두 같은 프로세스 그룹 정리 경로를 실행시킨다.
    os.close(write_fd)
    proc.wait()
