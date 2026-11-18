"""어댑터 자리에 끼우는 SyncNet 프로파일 실행기 (연구용 측정, 동작 변경 없음).

`infer_segments.py`와 같은 인자(`--request`, `--output`)를 받아 `profile_run.py`로 같은 요청을 돌리고,
어댑터가 읽는 결과 JSON(`infer_segments.py`의 출력 형식 + `device_used`)을 `--output`에 쓴다.
단계별 시간(profile)은 작업 폴더 안 `profile.json`에 남기고, 환경 변수 `SYNCNET_PROFILE_COPY_TO`가 있으면 그 경로로 복사한다
(Worker는 작업이 끝나면 작업 폴더를 지우기 때문이다). 측정 스크립트(`scripts/measure_syncnet_worker_gap.py`)만 이 파일을 쓴다.
서버 설정·기본 실행기는 바꾸지 않는다.

`SYNCNET_GAP_DRY=1`이면 SyncNet을 돌리지 않고 구간마다 트랙 없는 결과를 바로 쓴다(측정 하네스 점검용).

    research/syncnet/.venv/bin/python research/syncnet/profile_adapter_shim.py --request <폴더>/request.json --output <폴더>/result.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _dry(request: Path, output: Path) -> int:
    segments = json.loads(request.read_text())["segments"]
    rows = [{"start_sec": s, "end_sec": e, "status": "insufficient_input", "reason_code": "tracking_failed",
             "lse_c": None, "lse_d": None, "offset_frames": None, "tracks": []} for s, e in segments]
    output.write_text(json.dumps({"schema_version": 1, "segments": rows, "device_used": "cpu"}))
    copy_to = os.environ.get("SYNCNET_PROFILE_COPY_TO")
    if copy_to:
        Path(copy_to).write_text(json.dumps({"dry": True}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    request, output = args.request.resolve(), args.output.resolve()
    if os.environ.get("SYNCNET_GAP_DRY") == "1":
        return _dry(request, output)
    import profile_run  # 여기서 import해야 profile_run의 시작 시각이 이 프로세스의 시작과 가깝다

    profile_path = request.parent / "profile.json"
    code = profile_run.main(["--request", str(request), "--output", str(profile_path)])
    if code != 0:
        return code
    profile = json.loads(profile_path.read_text())
    result = dict(profile["result"])
    device = profile.get("config", {}).get("device")
    result["device_used"] = device if device in ("cpu", "mps") else None
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text(json.dumps(result, allow_nan=False))
    os.replace(tmp, output)
    copy_to = os.environ.get("SYNCNET_PROFILE_COPY_TO")
    if copy_to:
        shutil.copyfile(profile_path, copy_to)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
