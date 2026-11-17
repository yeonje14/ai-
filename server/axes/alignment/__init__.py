"""Gate 적합 구간의 SyncNet 실행. 대표값 집계와 진위 판정은 하지 않는다."""
from server.axes import AxisContext
from . import syncnet
from .report import MODEL_VERSION, SEGMENT_TOO_SHORT, excluded_short, fusion_features


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
    short = excluded_short(raw)
    if short:
        seconds = sum(row['end_sec'] - row['start_sec'] for row in short)
        none_left = raw['reason_code'] == SEGMENT_TOO_SHORT
        ctx.explanations.append({
            'template_id': 'SYNCNET_SHORT_SEGMENTS_EXCLUDED', 'reason_code': SEGMENT_TOO_SHORT,
            'message': (f'입술·음성 동기화 확인에 필요한 최소 길이(약 2초)보다 짧은 적합 구간 {len(short)}개'
                        f'({seconds:.1f}초)는 동기화 확인에서 제외했습니다.'
                        + (' 남은 구간이 없어 동기화를 확인하지 못했습니다.' if none_left else '')),
        })
    features = fusion_features(raw) if ctx.bundle is not None else None
    if features:
        # 학습과 같은 함수·같은 기준(completed일 때만). 결합 입력으로만 넘긴다
        for key, value in features.items():
            ctx.fusion_inputs[f'S.{key}'] = value
    return result
