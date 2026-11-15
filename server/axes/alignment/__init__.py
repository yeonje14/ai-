"""Gate 적합 구간의 SyncNet 실행. 대표값 집계와 진위 판정은 하지 않는다."""
from server.axes import AxisContext
from . import syncnet
from .report import MODEL_VERSION


def build_config(ctx: AxisContext) -> syncnet.SyncNetConfig:
    timeout = 600.0
    if ctx.timeout_seconds is not None:
        timeout = min(timeout, ctx.timeout_seconds)
    return syncnet.SyncNetConfig(timeout_sec=timeout)


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
    return result
