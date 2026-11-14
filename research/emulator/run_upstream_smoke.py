"""truebees-ai/social_emulator 원본 코드를 수정 없이 실행해 보는 동작 확인.

    research/emulator/.venv/bin/python research/emulator/run_upstream_smoke.py \
        --video data/research/samples/<허가 영상>.mp4

**플랫폼 파라미터 추정이 아니다.** 원본 코드는 "원본 영상 + 플랫폼에서 받은 같은 영상" 쌍이 필요한데
우리는 플랫폼 처리본이 없다(영상을 YouTube에 올리지 않는다). 그래서 플랫폼 처리본 자리에
로컬에서 libx264로 만든 파일(범용 프로파일, 답을 아는 값)을 넣는다. 확인하는 것은 두 가지다.
1. 원본 코드 두 단계(추정 → 인코딩)가 macOS ARM64에서 끝까지 도는가.
2. 추정 단계가 우리가 넣은 CRF와 해상도를 되찾는가.

원본 코드의 --platform은 Youtube/Facebook만 받는다. 여기서 주는 "Youtube"는 필수 인자를 채우는
이름표일 뿐이고, 결과는 YouTube와 무관하다. 그래서 산출 파일 이름에 NOT_PLATFORM을 붙인다.

원본 SN_parameters_emulation.py에는 breakpoint() 호출이 남아 있다. 파일을 고치지 않고
PYTHONBREAKPOINT=0 환경 변수로 끈다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from training.datasets.manifest import sha256_file  # noqa: E402
from training.emulator.profiles import get_profile  # noqa: E402
from training.emulator.video import emulate, probe_video  # noqa: E402

UPSTREAM = Path(__file__).resolve().parent / "upstream"
PINNED_COMMIT = "3e1a39a46c17d0357c0c991663ba878cb25cf25f"
PLATFORM_LABEL = "Youtube"  # 이름표일 뿐이다. 위 설명 참고
MODEL_FILE = "NOT_PLATFORM_local_standin_models.json"


def run(args: list[str], cwd: Path) -> None:
    # 원본 폴더에 .pyc를 남기지 않는다
    env = {**os.environ, "PYTHONBREAKPOINT": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"원본 스크립트 실패({Path(args[1]).name}):\n{proc.stdout[-800:]}\n{proc.stderr[-800:]}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--video", type=Path, required=True, help="권한이 확인된 영상")
    p.add_argument("--standin-profile", default="x264-crf28-720p", help="플랫폼 처리본 자리에 넣을 범용 프로파일")
    p.add_argument("--work-dir", type=Path, default=ROOT / "data/research/emulator/upstream-smoke")
    opt = p.parse_args()

    head = subprocess.run(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(UPSTREAM), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if head != PINNED_COMMIT or dirty:
        raise SystemExit(f"원본 저장소가 고정한 커밋의 수정 없는 상태가 아니다: {head} {dirty!r}")
    if opt.work_dir.exists():
        raise SystemExit(f"작업 폴더가 이미 있다. 덮어쓰지 않는다: {opt.work_dir}")

    work = opt.work_dir.resolve()
    originals, shared, new, emulated = (work / n for n in ("non-shared", "shared", "new", "emulated"))
    for d in (originals, shared, new):
        d.mkdir(parents=True)
    name = "sample.mp4"
    shutil.copy(opt.video, originals / name)
    shutil.copy(opt.video, new / name)
    standin = emulate(opt.video, opt.standin_profile, work / "standin")
    if standin["status"] != "completed":
        raise SystemExit(f"대역 파일을 만들지 못했다: {standin['status']} {standin['reason']}")
    shutil.copy(work / "standin" / standin["output"]["name"], shared / name)

    py = sys.executable
    model = work / MODEL_FILE
    run([py, str(UPSTREAM / "SN_parameters_emulation.py"),
         "--originals-dir", str(originals), "--socials-dir", str(shared),
         "--platform", PLATFORM_LABEL, "--codec", "libx264",
         "--output-model-file", str(model), "--crf-min", "20", "--crf-max", "40"], UPSTREAM)
    run([py, str(UPSTREAM / "SN_encoding_emulation.py"),
         "--input-dir", str(new), "--output-dir", str(emulated),
         "--platform", PLATFORM_LABEL, "--codec", "libx264", "--model-file", str(model)], UPSTREAM)

    samples = json.loads(model.read_text())[PLATFORM_LABEL]["libx264"]
    out_path = emulated / name
    profile = get_profile(opt.standin_profile)
    summary = {
        "note": "동작 확인이다. 플랫폼 처리본을 쓰지 않았고 YouTube 파라미터가 아니다.",
        "upstream_commit": head,
        "python": sys.version.split()[0],
        "input_sha256": sha256_file(opt.video),
        "standin": {"profile_id": profile.profile_id, "crf": profile.crf, **standin["output"]},
        "estimated_samples": samples,
        "upstream_output": {"sha256": sha256_file(out_path), **probe_video(out_path)} if out_path.is_file() else None,
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
