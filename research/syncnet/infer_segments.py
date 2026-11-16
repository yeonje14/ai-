"""SyncNet 전용 venv 실행기. 원본을 수정하지 않고 구간별 트랙 지표만 JSON으로 쓴다."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from server.axes.alignment.report import metrics_null, segment_failure, validate_segments, validate_tracks


def verify_weights(weights_dir: Path) -> None:
    manifest = json.loads((HERE / 'manifest.json').read_text())
    for name, spec in manifest['weights'].items():
        with (weights_dir / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != spec['sha256']:
                raise ValueError('weight hash mismatch')


def load_pipeline(weights_dir: Path):
    verify_weights(weights_dir)
    # 이 지점 이전과 부모 서버 프로세스에는 torch import가 없다.
    from syncnet_python import SyncNetPipeline
    return SyncNetPipeline(device='cpu', syncnet_weights=str(weights_dir / 'syncnet_v2.model'),
                           s3fd_weights=str(weights_dir / 'sfd_face.pth'))


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
    for start, end in validate_segments(request['segments']):
        try:
            with tempfile.TemporaryDirectory(prefix='segment-', dir=work) as tmp:
                segment_dir = Path(tmp)
                clip = segment_dir / 'clip.avi'
                cut_segment(Path(request['video']), start, end, clip)
                output = pipeline.inference(str(clip), cache_dir=str(segment_dir / 'cache'))
                tracks = tracks_from_output(output)
                if tracks:
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
        if request['segments']:
            pipeline = load_pipeline(Path(request['weights_dir']))
            result = infer_segments(request, work, pipeline)
        else:
            result = {'schema_version': 1, 'segments': []}
        dest.write_text(json.dumps(result, allow_nan=False))
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
