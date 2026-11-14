"""Worker 생존 파이프를 감시하며 Gate/모델 프로세스 그룹을 소유한다.

Worker가 SIGKILL되어도 파이프 EOF를 감지해 그룹 전체를 종료한다. runtime 잠금 FD를
상속받아 종료 전 새 Worker의 복구/파일 정리를 막는다. 모델의 Python 환경은 유지한다.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> int:
    read_fd = int(sys.argv[1])
    # 모델/FFmpeg 후손은 이 세션의 그룹에 남는다. supervisor 자신은 그룹 밖에서 거둔다.
    child = subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL, start_new_session=True)

    def watch_parent() -> None:
        try:
            while os.read(read_fd, 1):
                pass
        finally:
            _kill_group(child.pid)

    watcher = threading.Thread(target=watch_parent, daemon=True)
    try:
        watcher.start()
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        # 부모가 정상 실행을 마쳐도 살아 있는 후손이 파일을 다시 만들지 못하게 한다.
        _kill_group(child.pid)
        child.wait()
        # 상속된 runtime 잠금은 supervisor 종료 때 닫는다.


if __name__ == '__main__':
    raise SystemExit(main())
