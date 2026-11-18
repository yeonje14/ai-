"""SyncNet 전용 venv 실행기. 원본을 수정하지 않고 구간별 트랙 지표만 JSON으로 쓴다."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from server.axes.alignment.report import (SEGMENT_TOO_SHORT, metrics_null, segment_failure, validate_segments,
                                         validate_tracks)


def verify_weights(weights_dir: Path) -> None:
    manifest = json.loads((HERE / 'manifest.json').read_text())
    for name, spec in manifest['weights'].items():
        with (weights_dir / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != spec['sha256']:
                raise ValueError('weight hash mismatch')


DEVICES = ('cpu', 'mps')  # cuda는 받지 않는다(AGENTS.md). 기본은 cpu다


def resolve_device(requested: str) -> str:
    """mps를 요청했는데 쓸 수 없으면 cpu로 대체한다. torch는 여기서 처음 import한다."""
    if requested not in DEVICES:
        raise ValueError('unsupported device')
    if requested == 'mps':
        # MPS가 지원하지 않는 연산은 CPU로 넘긴다. torch import 전에 설정해야 한다
        os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')
        import torch
        if not torch.backends.mps.is_available():
            return 'cpu'
    return requested


def load_pipeline(weights_dir: Path, device: str = 'cpu'):
    verify_weights(weights_dir)
    # 이 지점 이전과 부모 서버 프로세스에는 torch import가 없다.
    from syncnet_python import SyncNetPipeline
    return SyncNetPipeline(device=device, syncnet_weights=str(weights_dir / 'syncnet_v2.model'),
                           s3fd_weights=str(weights_dir / 'sfd_face.pth'))


def count_frames(cache_dir: Path) -> int:
    """upstream이 이 구간에서 만든 프레임 수: 추출된 JPEG 수와 25fps AVI의 프레임 수 중 큰 값."""
    jpgs = sum(1 for _ in (cache_dir / 'frames').glob('*.jpg'))
    import cv2
    capture = cv2.VideoCapture(str(cache_dir / 'video.avi'))
    try:
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    return max(jpgs, frames)


class ShortSegmentGuard:
    """트랙이 나올 수 없는 짧은 구간에서 S3FD 검출을 건너뛰고 그 구간을 짧은 구간으로 표시한다.

    트랙 결과는 건너뛰지 않았을 때와 같다(트랙 없음). 구간의 원인 코드만 segment_too_short가 된다.

    upstream은 장면 길이가 min_track 프레임 이상일 때만 트래킹한다(`if e - s >= cfg.min_track`).
    장면 길이는 구간의 프레임 수를 넘지 못하므로, 프레임 수가 min_track보다 적으면 검출 결과와
    무관하게 트랙이 없고 upstream은 빈 결과를 돌려준다. 그 경우 검출 대신 빈 목록을 돌려준다.
    upstream 파일과 min_track 값은 바꾸지 않는다. 프레임 수를 셀 수 없으면 건너뛰지 않는다.
    """

    def __init__(self, detect, min_track: int, counter=count_frames):
        self.detect, self.min_track, self.counter = detect, min_track, counter
        self.cache_dir: Path | None = None
        self.frames: int | None = None
        self.skipped = 0

    def start(self, cache_dir: Path) -> None:
        self.cache_dir, self.frames = cache_dir, None

    def short(self) -> bool:
        """이번 구간의 프레임 수를 셌고 min_track보다 적었는지. 세지 못했으면 False."""
        return self.frames is not None and self.frames < self.min_track

    def __call__(self, image, *args, **kwargs):
        if self.frames is None:
            try:
                self.frames = self.counter(self.cache_dir)
            except Exception:
                self.frames = self.min_track  # 셀 수 없으면 원래대로 검출한다
        if self.frames < self.min_track:
            self.skipped += 1
            return []
        return self.detect(image, *args, **kwargs)


def install_guard(pipeline) -> ShortSegmentGuard | None:
    detector = getattr(pipeline, 's3fd', None)
    min_track = getattr(getattr(pipeline, 'cfg', None), 'min_track', None)
    if detector is None or type(min_track) is not int:
        return None
    guard = ShortSegmentGuard(detector.detect_faces, min_track)
    detector.detect_faces = guard
    return guard


def tracks_from_output(output) -> list[dict]:
    if not isinstance(output, (tuple, list)) or len(output) != 7:
        raise ValueError('invalid upstream output')
    offsets, confidences, distances, _, _, _, has_face = output
    if (not all(isinstance(v, list) for v in (offsets, confidences, distances))
            or not len(offsets) == len(confidences) == len(distances)
            or type(has_face) is not bool):
        raise ValueError('track lengths mismatch')
    if not offsets:
        return []
    if not has_face:
        raise ValueError('tracks without face')
    # 최대 confidence/최소 distance 요약은 버린다. 세 값은 반드시 같은 트랙의 것이다.
    return validate_tracks([
        {'track_index': i, 'offset_frames': offset, 'lse_c': conf, 'lse_d': dist}
        for i, (offset, conf, dist) in enumerate(zip(offsets, confidences, distances))])


def cut_segment(video: Path, start: float, end: float, dest: Path) -> None:
    # 같은 입력의 비디오/오디오를 동일 시간 창으로 절단한다. 하드웨어 인코더는 쓰지 않는다.
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(video),
           '-ss', str(start), '-t', str(end - start), '-map', '0:v:0', '-map', '0:a:0',
           '-c:v', 'ffv1', '-c:a', 'pcm_s16le', '-ar', '16000', '-ac', '1', str(dest)]
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def infer_segments(request: dict, work: Path, pipeline) -> dict:
    rows = []
    guard = install_guard(pipeline)
    for start, end in validate_segments(request['segments']):
        try:
            with tempfile.TemporaryDirectory(prefix='segment-', dir=work) as tmp:
                segment_dir = Path(tmp)
                clip = segment_dir / 'clip.avi'
                cut_segment(Path(request['video']), start, end, clip)
                if guard is not None:
                    guard.start(segment_dir / 'cache')
                output = pipeline.inference(str(clip), cache_dir=str(segment_dir / 'cache'))
                tracks = tracks_from_output(output)
                if guard is not None and guard.short():
                    # upstream min_track 미만: SyncNet 판단에서 제외한다(docs/DESIGN.md §15.3 2026-11-17)
                    row = segment_failure(start, end, 'insufficient_input', SEGMENT_TOO_SHORT)
                elif tracks:
                    row = {'start_sec': start, 'end_sec': end, 'status': 'completed',
                           'reason_code': None, **metrics_null(), 'tracks': tracks}
                else:
                    row = segment_failure(start, end, 'insufficient_input', 'tracking_failed')
        except Exception:
            # 한 구간 실패로 나머지 구간을 막지 않고 예외의 미디어 정보는 내보내지 않는다.
            row = segment_failure(start, end, 'error', 'inference_error')
        rows.append(row)
    return {'schema_version': 1, 'segments': rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source, dest = args.request.resolve(), args.output.resolve()
        work = source.parent
        if dest.parent != work or source == dest:
            return 1
        request = json.loads(source.read_text())
        video = Path(request['video']).resolve()
        # 어댑터가 만든 job/syncnet-*/request.json과 같은 job의 미디어만 허용한다.
        if not video.is_relative_to(work.parent) or not video.is_file():
            return 1
        request['segments'] = validate_segments(request['segments'])
        request['video'] = str(video)
        device = request.get('device')
        if request['segments']:
            if device is None:
                pipeline = load_pipeline(Path(request['weights_dir']))
            else:
                device = resolve_device(device)
                pipeline = load_pipeline(Path(request['weights_dir']), device)
            result = infer_segments(request, work, pipeline)
        else:
            result = {'schema_version': 1, 'segments': []}
        if device is not None:
            result['device_used'] = device  # 내부 기록. mps를 못 쓰면 cpu다
        dest.write_text(json.dumps(result, allow_nan=False))
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
