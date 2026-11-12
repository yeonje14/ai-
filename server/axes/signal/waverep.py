"""WaveRep 어댑터 (README §14.1 백로그 7번의 앞부분). Gate·Worker에는 아직 연결하지 않았다.

영상 파일과 시간 구간 목록을 받아 프레임별 원시 logit을 돌려준다.

- 이 모듈은 torch를 import하지 않는다. research/waverep/.venv의 Python으로
  research/waverep/infer_frames.py를 별도 프로세스(인자 리스트)로 실행하고 결과를 JSON으로 받는다.
- 점수는 원시 logit이다. 확률로 바꾸지 않고, 임계값을 적용하지 않고, 판정하지 않는다.
  집계 방법이 정해지지 않았으므로 raw_score는 null이고, 프레임 logit 요약만 raw_metrics에 둔다.
- 실패는 예외로 던지지 않고 status=error(점수 null)로 돌려준다. 한 축의 실패가 다른 축을 막지 않게 한다.
- 로그·결과에 영상 내용과 프레임 이미지를 남기지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
WAVEREP_DIR = REPO_ROOT / "research" / "waverep"

ALLOWED_DEVICES = ("cpu", "mps")
TIME_BIN = "/usr/bin/time"
REQUEST_NAME = "waverep_request.json"
RESULT_NAME = "waverep_result.json"
MODEL_VERSION = "waverep-dinov2-G4"

# axes.*.status (README §10)
COMPLETED = "completed"
INSUFFICIENT_INPUT = "insufficient_input"
UNSUPPORTED_INPUT = "unsupported_input"
ERROR = "error"
_KNOWN_STATUS = (COMPLETED, INSUFFICIENT_INPUT, UNSUPPORTED_INPUT, ERROR)


@dataclass(frozen=True)
class WaveRepConfig:
    python: Path = WAVEREP_DIR / ".venv" / "bin" / "python"
    script: Path = WAVEREP_DIR / "infer_frames.py"
    weights: Path = WAVEREP_DIR / "upstream" / "demo" / "weights" / "weights_dinov2_G4.ckpt"
    device: str = "mps"                 # cpu 또는 mps. mps를 못 쓰면 추론 프로세스가 cpu로 대체한다
    sample_fps: Optional[float] = None  # None이면 구간 안 모든 프레임. 1, 2, 4 등은 초당 장수
    batch_size: int = 8
    # False면 Hugging Face Hub에 접근하지 않는다. 체크포인트가 177개 키를 모두 덮어쓰므로
    # 점수가 같다는 것을 확인했다(docs/waverep-adapter.md).
    pretrained: bool = False
    timeout_sec: float = 600.0
    # True면 /usr/bin/time -l로 감싸 peak memory footprint를 읽는다(측정용, macOS)
    measure_peak_footprint: bool = False


def summarize_logits(logits: Sequence[float]) -> dict[str, Any]:
    """프레임 logit 요약. 프레임이 없으면 통계는 None이다(0이 아님)."""
    n = len(logits)
    if n == 0:
        return {"frames": 0, "mean": None, "median": None, "min": None, "max": None, "stdev": None}
    return {
        "frames": n,
        "mean": statistics.fmean(logits),
        "median": statistics.median(logits),
        "min": min(logits),
        "max": max(logits),
        "stdev": statistics.pstdev(logits) if n > 1 else None,
    }


def build_command(config: WaveRepConfig, request_path: Path, output_path: Path) -> list[str]:
    """인자 리스트만 만든다(셸 문자열 없음). 모델 프로세스에는 작업 폴더 안 경로 두 개만 넘긴다."""
    cmd = [
        str(config.python), str(config.script),
        "--request", str(request_path),
        "--output", str(output_path),
    ]
    if config.measure_peak_footprint:
        cmd = [TIME_BIN, "-l", *cmd]
    return cmd


def parse_peak_footprint(stderr: str) -> Optional[int]:
    """macOS `/usr/bin/time -l` 출력의 peak memory footprint(바이트). 없으면 None."""
    m = re.search(r"^\s*(\d+)\s+peak memory footprint\s*$", stderr, re.MULTILINE)
    return int(m.group(1)) if m else None


def _failure(status: str, reason_code: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "detail": detail,
        "raw_score": None,
        "raw_metrics": None,
        "frames": None,
        "model_version": MODEL_VERSION,
        **extra,
    }


def _check_inputs(config: WaveRepConfig, segments: Sequence[Sequence[float]]) -> Optional[str]:
    """프로세스를 띄우기 전에 걸러낼 수 있는 잘못된 입력. 문제가 없으면 None."""
    if config.device not in ALLOWED_DEVICES:
        return f"device는 {ALLOWED_DEVICES} 중 하나여야 한다"
    if isinstance(config.batch_size, bool) or not isinstance(config.batch_size, int) or config.batch_size < 1:
        return "batch_size는 1 이상의 정수여야 한다"
    fps = config.sample_fps
    if fps is not None and (
        isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0
    ):
        return "sample_fps는 양수 또는 None이어야 한다"
    for seg in segments:
        if isinstance(seg, (str, bytes)) or len(seg) != 2:
            return "구간은 [start_sec, end_sec] 두 값이어야 한다"
        for v in seg:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return "구간 값은 유한한 숫자여야 한다"
        if seg[0] < 0 or seg[1] <= seg[0]:
            return "구간은 0 <= start < end 여야 한다"
    return None


def _run_process(cmd: list[str], timeout_sec: float) -> tuple[Optional[int], str]:
    """(종료 코드, stderr)를 돌려준다. 타임아웃이면 프로세스 그룹 전체를 죽이고 종료 코드는 None."""
    env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="1")
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # /usr/bin/time으로 감쌌을 때도 자식까지 한 번에 끝낼 수 있게
    )
    try:
        _, stderr = proc.communicate(timeout=timeout_sec)
        return proc.returncode, stderr or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _, stderr = proc.communicate()
        return None, stderr or ""


def _parse_result(raw: Any) -> dict[str, Any]:
    """추론 프로세스가 쓴 JSON을 검사한다. 형식이 어긋나면 ValueError."""
    if not isinstance(raw, dict) or raw.get("status") not in _KNOWN_STATUS:
        raise ValueError("status 없음 또는 알 수 없는 값")
    if raw["status"] != COMPLETED:
        return raw
    frames = raw.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("completed인데 frames가 비어 있음")
    for f in frames:
        if not isinstance(f, dict) or not isinstance(f.get("index"), int):
            raise ValueError("frame index 형식 오류")
        logit = f.get("logit")
        if isinstance(logit, bool) or not isinstance(logit, (int, float)) or not math.isfinite(logit):
            raise ValueError("logit이 유한한 숫자가 아님")
    return raw


def run_waverep(
    video: Path,
    segments: Sequence[Sequence[float]],
    work_dir: Path,
    config: WaveRepConfig = WaveRepConfig(),
) -> dict[str, Any]:
    """구간 안 프레임의 WaveRep 원시 logit을 계산한다. 예외를 던지지 않는다.

    video: 서버가 발급한 작업 경로 안의 허가 미디어 파일.
    segments: [(start_sec, end_sec), ...]. 비어 있으면 insufficient_input.
    work_dir: 요청·결과 JSON을 잠시 두는 작업 폴더(이미 있어야 한다). 끝나면 두 파일을 지운다.
    """
    video = Path(video)
    work_dir = Path(work_dir)
    segments = [tuple(s) if not isinstance(s, (str, bytes)) else s for s in segments]

    problem = _check_inputs(config, segments)
    if problem is not None:
        return _failure(ERROR, "invalid_request", problem)
    if not segments:
        return _failure(INSUFFICIENT_INPUT, "no_segments")
    if not video.is_file():
        return _failure(ERROR, "media_unreadable", "영상 파일 없음")
    if not work_dir.is_dir():
        return _failure(ERROR, "invalid_request", "작업 폴더 없음")
    for label, path in (("python", config.python), ("script", config.script), ("weights", config.weights)):
        if not Path(path).is_file():
            return _failure(ERROR, "model_unavailable", f"{label} 없음")

    request_path = work_dir / REQUEST_NAME
    output_path = work_dir / RESULT_NAME
    request = {
        "video": str(video.resolve()),
        "segments": [[float(a), float(b)] for a, b in segments],
        "sample_fps": config.sample_fps,
        "batch_size": config.batch_size,
        "device": config.device,
        "weights": str(Path(config.weights).resolve()),
        "pretrained": config.pretrained,
    }
    try:
        output_path.unlink(missing_ok=True)  # 이전 실행의 결과를 이번 결과로 읽지 않게
        request_path.write_text(json.dumps(request), encoding="utf-8")
        cmd = build_command(config, request_path, output_path)
        try:
            returncode, stderr = _run_process(cmd, config.timeout_sec)
        except OSError as e:
            return _failure(ERROR, "model_unavailable", type(e).__name__)
        if returncode is None:
            return _failure(ERROR, "timeout", f"{config.timeout_sec}초 초과")

        try:
            raw = _parse_result(json.loads(output_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            # 결과 파일이 없거나 깨졌다. stderr 끝부분만 남긴다(영상 내용은 들어가지 않는다).
            return _failure(
                ERROR, "inference_error", f"결과를 읽을 수 없음: {type(e).__name__}",
                returncode=returncode, stderr_tail=stderr[-2000:],
            )
    finally:
        request_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)

    if raw["status"] != COMPLETED:
        return _failure(
            raw["status"], raw.get("reason_code") or "inference_error", raw.get("detail") or "",
            video=raw.get("video"), returncode=returncode, stderr_tail=stderr[-2000:],
        )

    frames = raw["frames"]
    memory = dict(raw.get("memory") or {})
    memory["peak_footprint_bytes"] = (
        parse_peak_footprint(stderr) if config.measure_peak_footprint else None
    )
    return {
        "status": COMPLETED,
        "reason_code": None,
        # 집계 방법과 임계값은 정하지 않았다(백로그 8번 이후). 판정하지 않는다.
        "raw_score": None,
        "raw_metrics": {"frame_logit": summarize_logits([f["logit"] for f in frames])},
        "frames": frames,
        "model_version": MODEL_VERSION,
        "model": raw.get("model"),
        "video": raw.get("video"),
        "sampling": raw.get("sampling"),
        "timing": raw.get("timing"),
        "memory": memory,
    }
