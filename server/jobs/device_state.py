"""기기 상태 기록(내부용). macOS의 ProcessInfo.thermalState를 읽는다.

Worker 프로세스 안에서 Objective-C 런타임을 불러 네이티브 호출을 하지 않는다. 잘못되면 Worker가 죽고
대기열이 멈추기 때문이다. 대신 짧은 별도 프로세스(같은 Python, 격리 모드)에서 표준 라이브러리 ctypes로 읽는다.
실패·시간 초과·macOS가 아님은 모두 None이다(작업에 영향을 주지 않는다). API 결과에는 쓰지 않는다.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

# ProcessInfo.ThermalState 0~3 (nominal, fair, serious, critical)
THERMAL_NAMES = ("nominal", "fair", "serious", "critical")

# arm64에서 objc_msgSend는 가변 인자가 아니라 고정 인자 원형으로 불러야 한다
_PROBE = (
    "import ctypes, ctypes.util\n"
    "o = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))\n"
    "ctypes.cdll.LoadLibrary(ctypes.util.find_library('Foundation'))\n"
    "o.objc_getClass.restype = ctypes.c_void_p; o.objc_getClass.argtypes = [ctypes.c_char_p]\n"
    "o.sel_registerName.restype = ctypes.c_void_p; o.sel_registerName.argtypes = [ctypes.c_char_p]\n"
    "obj = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', o))\n"
    "num = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', o))\n"
    "info = obj(o.objc_getClass(b'NSProcessInfo'), o.sel_registerName(b'processInfo'))\n"
    "print(num(info, o.sel_registerName(b'thermalState')))\n"
)


def thermal_state(timeout: float = 1.0) -> Optional[str]:
    """지금의 thermalState 이름. 읽지 못하면 None.

    기본 제한 1초: 축 끝 프로브와 기록 저장이 SyncNet 마무리 여유(10초) 안에 들어가게 한다(실측 20~90ms).
    """
    if sys.platform != "darwin":
        return None
    try:
        proc = subprocess.run([sys.executable, "-I", "-c", _PROBE], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text.isdigit():
        return None
    value = int(text)
    return THERMAL_NAMES[value] if value < len(THERMAL_NAMES) else None
