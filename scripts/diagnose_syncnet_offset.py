"""허가된 발화 영상의 원본/오디오 지연본 비교 도구. 자동 판정하지 않는다."""
import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.ingest.media_resolver import AuthorizedMediaRegistry
from server.axes.alignment.syncnet import run_syncnet


def shift_command(source: Path, target: Path, delay: float) -> list[str]:
    if not math.isfinite(delay):
        raise ValueError('delay must be finite seconds')
    audio_filter = (f'adelay={delay * 1000:g}:all=1' if delay > 0 else
                    f'atrim=start={-delay:g},asetpts=PTS-STARTPTS' if delay < 0 else 'anull')
    return ['ffmpeg', '-nostdin', '-y', '-i', str(source), '-map', '0:v:0', '-map', '0:a:0',
            '-c:v', 'copy', '-af', audio_filter, '-c:a', 'pcm_s16le',
            '-shortest', str(target)]


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',type=Path,required=True)
    p.add_argument('--media-root',type=Path,required=True)
    p.add_argument('--video-id',required=True)
    p.add_argument('--start',type=float,required=True)
    p.add_argument('--end',type=float,required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--delay',type=float)
    group.add_argument('--delays',type=float,nargs='+')
    args=p.parse_args(argv)
    if not all(math.isfinite(v) for v in (args.start,args.end)) or not 0 <= args.start < args.end:
        p.error('0 <= start < end required')
    media=AuthorizedMediaRegistry.from_file(args.registry,args.media_root).resolve(args.video_id)
    if media is None or media.local_path is None or not media.local_path.is_file():
        p.error('authorized media unavailable')
    runtime=ROOT/'data/runtime';runtime.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='syncnet-diagnostic-',dir=runtime) as tmp:
        work=Path(tmp);source=work/'source.mp4';shifted=work/'shifted.mkv'
        shutil.copyfile(media.local_path,source)
        results={'original':run_syncnet(source,[(args.start,args.end)],work)}
        delays=args.delays if args.delays is not None else [args.delay]
        for delay in delays:
            subprocess.run(shift_command(source,shifted,delay),check=True,timeout=120,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            key=f'audio_shift_{delay:+g}s' if args.delays is not None else 'audio_delayed'
            results[key]=run_syncnet(shifted,[(args.start,args.end)],work)
            shifted.unlink()
        print(json.dumps({'delay_seconds':delays if args.delays is not None else args.delay,
                          'results':results},ensure_ascii=False,allow_nan=False))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
