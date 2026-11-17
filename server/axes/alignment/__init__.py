"""Gate 적합 구간의 SyncNet 실행. 대표값 집계와 진위 판정은 하지 않는다."""
import statistics

from server.axes import AxisContext
from . import syncnet
from .report import MODEL_VERSION


def build_config(ctx: AxisContext) -> syncnet.SyncNetConfig:
    timeout = 600.0
    if ctx.timeout_seconds is not None:
        timeout = min(timeout, ctx.timeout_seconds)
    return syncnet.SyncNetConfig(timeout_sec=timeout, device=ctx.settings.syncnet_device)


def run(ctx: AxisContext) -> dict:
    result = {'status': 'insufficient_input', 'reason_code': 'no_segments',
              'lse_c': None, 'lse_d': None, 'included_in_fusion': False,
              'model_version': MODEL_VERSION}
    if ctx.settings.dev_manual_segments:
        result['reason_code'] = 'speaker_unconfirmed'
        return result
    if not ctx.segments:
        return result
    if ctx.media_path is None:
        result.update(status='error', reason_code='media_unreadable')
        return result
    raw = syncnet.run_syncnet(ctx.media_path, ctx.segments, ctx.job_dir, build_config(ctx),
                             on_tick=ctx.heartbeat, tick_sec=ctx.settings.heartbeat_interval_seconds)
    result.update(status=raw['status'], reason_code=raw['reason_code'])
    if ctx.bundle is not None and raw['status'] == 'completed':
        # 학습 때와 같은 집계(전 구간·전 트랙의 중앙값). 결합 입력으로만 넘긴다
        tracks = [t for seg in raw['segments'] for t in seg['tracks']]
        for key, values in (('lse_c_median', [t['lse_c'] for t in tracks]),
                            ('lse_d_median', [t['lse_d'] for t in tracks]),
                            ('abs_offset_median', [abs(t['offset_frames']) for t in tracks])):
            ctx.fusion_inputs[f'S.{key}'] = float(statistics.median(values))
    return result
