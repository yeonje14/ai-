"""Gate 적합 구간의 SyncNet 실행. 대표값 집계와 진위 판정은 하지 않는다."""
from server.axes import AxisContext
from . import syncnet
from .report import MODEL_VERSION, SEGMENT_TOO_SHORT, excluded_short, fusion_features


def stage_timeout(ctx: AxisContext) -> float:
    """SyncNet 단계 제한(초) = min(기본항 + 계수 × 적합 구간 초, 남은 작업 시간 − 마무리 여유).

    SyncNet이 느려져도 작업 전체 제한보다 먼저 이 단계만 멈추게 해서, 작업은 finished로 끝나고
    다른 축 결과가 남게 한다(docs/DESIGN.md §15.3 2026-11-18). 0 이하이면 SyncNet을 시작하지 않는다.
    """
    s = ctx.settings
    eligible_sec = sum(end - start for start, end in ctx.segments)
    limit = s.syncnet_timeout_base_seconds + s.syncnet_timeout_per_eligible_second * eligible_sec
    if ctx.timeout_seconds is not None:
        limit = min(limit, ctx.timeout_seconds - s.job_finalize_margin_seconds)
    return limit


def build_config(ctx: AxisContext) -> syncnet.SyncNetConfig:
    return syncnet.SyncNetConfig(timeout_sec=stage_timeout(ctx), device=ctx.settings.syncnet_device)


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
    config = build_config(ctx)
    if config.timeout_sec <= 0:
        # 마무리 여유를 빼면 남은 시간이 없다. 시작하지 않고 이 축만 단계 제한 초과로 끝낸다
        result.update(status='error', reason_code='timeout')
        return result
    raw = syncnet.run_syncnet(ctx.media_path, ctx.segments, ctx.job_dir, config,
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
    if features and raw.get('device_used') != ctx.settings.syncnet_device:
        # 장치가 대체되면 특징 버전과 다른 값이다(docs/DESIGN.md §15.3 결정 9 보완). 결합 입력으로 넘기지 않는다(감사 A4)
        features = None
    if features:
        # 학습과 같은 함수·같은 기준(completed일 때만). 결합 입력으로만 넘긴다
        for key, value in features.items():
            ctx.fusion_inputs[f'S.{key}'] = value
    return result
