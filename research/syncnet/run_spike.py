"""조각 1/3 CPU 재현: 원본 CLI를 수정 없이 실행하고 성공/실패만 출력한다.

SyncNet 전용 Python으로 실행한다. 연구 운영자가 지정한 허가 레지스트리만 받는다.
출력 숫자·로그·복사본·crop은 임시 폴더와 함께 삭제한다. 서비스 어댑터가 아니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server.ingest.media_resolver import AuthorizedMediaRegistry

WEIGHTS = ROOT / 'data/models/syncnet'
RUNTIME = ROOT / 'data/runtime'
MANIFEST = json.loads(Path(__file__).with_name('manifest.json').read_text())


def verify_weights() -> None:
    for name, spec in MANIFEST['weights'].items():
        with (WEIGHTS / name).open('rb') as file:
            actual = hashlib.file_digest(file, 'sha256').hexdigest()
        if actual != spec['sha256']:
            raise ValueError('weight hash mismatch')


def result_succeeded(body: object) -> bool:
    # 원본 CLI는 항목이 error여도 exit 0일 수 있다. 얼굴 트랙 없는 기본값도 성공으로 세지 않는다.
    if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict):
        return False
    result = body[0]
    return (
        result.get('status') == 'success'
        and result.get('has_face') is True
        and type(result.get('offset')) is int
        and all(type(result.get(key)) in (int, float) and math.isfinite(result[key])
                for key in ('confidence', 'min_distance'))
    )


def execute(work: Path) -> bool:
    cmd = [
        sys.executable, '-m', 'syncnet_python.cli', str(work / 'media.mp4'), '--device', 'cpu',
        '--syncnet-weights', str(WEIGHTS / 'syncnet_v2.model'),
        '--s3fd-weights', str(WEIGHTS / 'sfd_face.pth'),
        '--cache-dir', str(work / 'cache'), '--output', str(work / 'result.json'),
    ]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        code = proc.wait(timeout=600)
        return code == 0 and result_succeeded(json.loads((work / 'result.json').read_text()))
    finally:
        # 실패/timeout에도 FFmpeg 후손을 남기지 않고 폴더 정리 전에 종료한다.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--registry', required=True, type=Path)
    parser.add_argument('--media-root', required=True, type=Path)
    parser.add_argument('--video-id', required=True)
    args = parser.parse_args(argv)
    success = False
    try:
        registry = AuthorizedMediaRegistry.from_file(args.registry, args.media_root)
        media = registry.resolve(args.video_id)
        if media is None or media.local_path is None or not media.local_path.is_file():
            raise ValueError('authorized media unavailable')
        verify_weights()
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='syncnet-spike-', dir=RUNTIME) as tmp:
            work = Path(tmp)
            shutil.copyfile(media.local_path, work / 'media.mp4')
            success = execute(work)
    except Exception:
        # 원본 예외·지표·미디어 내용은 보고/로그에 노출하지 않는다.
        success = False
    print('실행 성공' if success else '실행 실패')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
