"""개발 환경 스모크 점검 (README §14.1 백로그 2번).

Python·아키텍처, FFmpeg/ffprobe, PyTorch CPU/MPS, OpenCV, LightGBM을 점검하고
결과를 docs/env-check.md에 기록한다. 아무것도 설치하지 않는다.
없는 것은 "없음", 있지만 동작하지 않는 것은 "실패"로 적는다.

사용: python scripts/check_env.py [--output docs/env-check.md]
"""

from __future__ import annotations

import argparse
import importlib
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

OK = "정상"
MISSING = "없음"
FAILED = "실패"

EXPECTED_PYTHON = (3, 11)
EXPECTED_MACHINE = "arm64"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "env-check.md"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def _run(args: list[str], timeout: float = 15.0) -> str:
    """인자 리스트로만 실행한다(셸 문자열 없음). stdout+stderr를 돌려준다."""
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    return (done.stdout + done.stderr).strip()


def _short(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".strip()
    first = text.splitlines()[0] if text else type(exc).__name__
    return first[:300]


def check_python() -> list[Check]:
    version = platform.python_version()
    ok_version = sys.version_info[:2] == EXPECTED_PYTHON
    machine = platform.machine()
    ok_machine = machine == EXPECTED_MACHINE
    checks = [
        Check(
            "Python",
            OK if ok_version else FAILED,
            f"{version} ({sys.executable})"
            + ("" if ok_version else f" — 기대 버전 {EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}"),
        ),
        Check(
            "아키텍처",
            OK if ok_machine else FAILED,
            f"{platform.system()} {platform.release()} / {machine}"
            + ("" if ok_machine else f" — 기대 값 {EXPECTED_MACHINE}"),
        ),
    ]
    if platform.system() == "Darwin":
        # 1이면 x86_64 Python이 Rosetta로 도는 중이다.
        try:
            translated = _run(["sysctl", "-n", "sysctl.proc_translated"])
            checks.append(
                Check("Rosetta 변환", OK if translated == "0" else FAILED, f"proc_translated={translated}")
            )
        except Exception as exc:  # noqa: BLE001 - 점검 도구라 모든 실패를 기록한다
            checks.append(Check("Rosetta 변환", FAILED, _short(exc)))
    return checks


def check_tool(name: str) -> Check:
    path = shutil.which(name)
    if path is None:
        return Check(name, MISSING, "PATH에서 찾지 못함")
    try:
        first_line = _run([path, "-version"]).splitlines()[0]
    except Exception as exc:  # noqa: BLE001
        return Check(name, FAILED, f"{path} — {_short(exc)}")
    return Check(name, OK, f"{first_line} ({path})")


def check_ffmpeg_encoder(encoder: str = "libx264") -> Check:
    """압축 에뮬레이터는 소프트웨어 인코더를 쓰므로 libx264 유무를 본다."""
    label = f"ffmpeg 인코더 {encoder}"
    path = shutil.which("ffmpeg")
    if path is None:
        return Check(label, MISSING, "ffmpeg 없음")
    try:
        listing = _run([path, "-hide_banner", "-encoders"])
    except Exception as exc:  # noqa: BLE001
        return Check(label, FAILED, _short(exc))
    found = any(encoder in line.split() for line in listing.splitlines())
    return Check(label, OK if found else MISSING, "사용 가능" if found else "이 빌드에 포함되지 않음")


def _import(module: str):
    """(모듈, None) 또는 (None, Check 상태·사유)를 돌려준다."""
    try:
        return importlib.import_module(module), None
    except ModuleNotFoundError as exc:
        if exc.name == module.split(".")[0]:
            return None, (MISSING, "설치되지 않음")
        return None, (FAILED, _short(exc))
    except Exception as exc:  # noqa: BLE001 - dylib 누락(OSError) 등
        return None, (FAILED, _short(exc))


def check_module(label: str, module: str) -> Check:
    mod, problem = _import(module)
    if problem:
        return Check(label, *problem)
    return Check(label, OK, str(getattr(mod, "__version__", "버전 확인 불가")))


def _tensor_smoke(torch, device: str) -> str:
    x = torch.ones(64, 64, device=device)
    total = float((x @ x).sum().item())
    if total != 64.0 * 64 * 64:
        raise RuntimeError(f"연산 결과 불일치: {total}")
    return "행렬곱 스모크 통과"


def check_torch() -> list[Check]:
    torch, problem = _import("torch")
    if problem:
        status, detail = problem
        note = "PyTorch 없음" if status == MISSING else "PyTorch 가져오기 실패"
        return [
            Check("PyTorch", status, detail),
            Check("PyTorch CPU", status, note),
            Check("PyTorch MPS", status, note),
        ]

    checks = [Check("PyTorch", OK, str(torch.__version__))]
    try:
        checks.append(Check("PyTorch CPU", OK, _tensor_smoke(torch, "cpu")))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("PyTorch CPU", FAILED, _short(exc)))

    try:
        built = bool(torch.backends.mps.is_built())
        available = bool(torch.backends.mps.is_available())
        flags = f"is_built={built}, is_available={available}"
        if available:
            checks.append(Check("PyTorch MPS", OK, f"{flags}, {_tensor_smoke(torch, 'mps')}"))
        else:
            checks.append(Check("PyTorch MPS", FAILED, f"{flags} — cpu로 대체"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("PyTorch MPS", FAILED, _short(exc)))
    return checks


def run_checks() -> list[Check]:
    checks = check_python()
    checks.append(check_tool("ffmpeg"))
    checks.append(check_tool("ffprobe"))
    checks.append(check_ffmpeg_encoder("libx264"))
    checks.extend(check_torch())
    checks.append(check_module("OpenCV (cv2)", "cv2"))
    checks.append(check_module("LightGBM", "lightgbm"))
    return checks


def available_devices(checks: list[Check]) -> list[str]:
    """장치 선택 순서(mps → cpu)대로 실제 스모크를 통과한 장치만 돌려준다."""
    by_name = {c.name: c for c in checks}
    order = [("mps", "PyTorch MPS"), ("cpu", "PyTorch CPU")]
    return [dev for dev, name in order if name in by_name and by_name[name].status == OK]


def console_log(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    return "\n".join(f"[{c.status}] {c.name.ljust(width)}  {c.detail}" for c in checks)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(checks: list[Check], generated_at: str) -> str:
    devices = available_devices(checks)
    problems = [c for c in checks if c.status != OK]
    fallback = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "설정 안 됨")

    lines = [
        "# 개발 환경 점검 결과",
        "",
        "README §14.1 백로그 2번(P0-1). `python scripts/check_env.py`가 만든 파일이다. 직접 고치지 않는다.",
        "",
        f"- 점검 시각: {generated_at}",
        f"- 플랫폼: {platform.platform()}",
        f"- 사용 가능한 추론 장치(선택 순서): {', '.join(devices) if devices else '없음'}",
        f"- `PYTORCH_ENABLE_MPS_FALLBACK`: {fallback}",
        "",
        "상태 값: `정상` 동작 확인, `없음` 설치되지 않음(설치하지 않고 기록만 함), `실패` 있지만 동작하지 않거나 기대와 다름.",
        "",
        "## 점검 표",
        "",
        "| 항목 | 상태 | 내용 |",
        "|---|---|---|",
    ]
    lines += [f"| {_cell(c.name)} | {c.status} | {_cell(c.detail)} |" for c in checks]
    lines += ["", "## 없음·실패 목록", ""]
    if problems:
        lines += [f"- **{c.name}** — {c.status}: {c.detail}" for c in problems]
    else:
        lines.append("- 없음")
    lines += ["", "## 콘솔 로그", "", "```text", console_log(checks), "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="개발 환경 스모크 점검")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="결과 Markdown 경로")
    args = parser.parse_args(argv)

    checks = run_checks()
    print(console_log(checks))

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(checks, generated_at), encoding="utf-8")
    print(f"\n기록: {args.output}")
    # 점검 보고서이므로 없음·실패가 있어도 0으로 끝낸다. 판단은 문서를 읽고 한다.
    return 0


if __name__ == "__main__":
    sys.exit(main())
