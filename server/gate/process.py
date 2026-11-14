"""Worker가 발급한 요청 경로 하나로 실행하는 내부 Gate 프로세스."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from server.gate import run_gate


def main() -> int:
    request = Path(sys.argv[1]).resolve()
    data = json.loads(request.read_text(encoding="utf-8"))
    media = Path(data["media"]).resolve()
    if media.parent != request.parent:
        return 1
    os.environ["TRINITY_GATE_MODEL_DIR"] = data["model_dir"]
    os.environ["TRINITY_GATE_MODELS_CONFIG"] = data["models_config"]
    result = run_gate(media)
    (request.parent / "gate_result.json").write_text(
        json.dumps(asdict(result), allow_nan=False), encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
