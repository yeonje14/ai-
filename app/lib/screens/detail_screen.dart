import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design/tokens.dart';
import '../design/widgets.dart';
import '../view_state.dart';

/// 화면 6: 판단 근거 상세. 축별 원시 지표, 분석 범위, 서버가 보낸 상태 값.
///
/// 원시 지표는 확률이 아니다. 값이 없으면 "값 없음"으로 적는다(0이 아니다).
class DetailScreen extends StatelessWidget {
  const DetailScreen({super.key, required this.result, required this.onBack});

  final AnalysisResult result;
  final VoidCallback onBack;

  static const notProbability = '확률 아님';
  static const rawNotice = '아래 값은 모델이 낸 원시 지표입니다. 가짜일 확률이 아니며, 값 하나로 진위를 말할 수 없습니다.';

  String _status(AxisResult a) {
    final text = axisStatusText[a.status] ?? '알 수 없음';
    final why = reasonText(a.reasonCode);
    return why == null ? text : '$text · $why';
  }

  @override
  Widget build(BuildContext context) {
    final signal = result.axes['signal'], physics = result.axes['physics'], alignment = result.axes['alignment'];
    final c = result.coverage;
    String orNone(String? v) => (v == null || v.isEmpty) ? '값 없음' : v;
    String sec(double? v) => v == null ? '값 없음' : formatDuration(v);
    return TrinityScaffold(
      children: [
        SecondaryButton(label: '결과 요약으로 돌아가기', onPressed: onBack),
        const SizedBox(height: TSpace.x4),
        Semantics(header: true, child: Text('판단 근거', style: TText.display)),
        const SectionTitle('축별 원시 지표'),
        const InfoBox(title: DetailScreen.notProbability, body: DetailScreen.rawNotice, tone: StatusTone.warning),
        const SizedBox(height: TSpace.x3),
        if (signal != null)
          AxisResultRow(
            title: '신호 (WaveRep)',
            description: '프레임에서 AI 생성 관련 신호와 비슷한 특징을 찾습니다.',
            statusText: _status(signal),
            metrics: [('원시 점수 · ${DetailScreen.notProbability}', metricText(signal.rawScore))],
            note: '모델 버전: ${orNone(signal.modelVersion)}',
          ),
        const SizedBox(height: TSpace.x2),
        if (physics != null)
          AxisResultRow(
            title: '움직임 (MotionPhys)',
            description: '추적한 점들의 움직임 통계를 봅니다.',
            statusText: _status(physics),
            metrics: [('원시 점수 · ${DetailScreen.notProbability}', metricText(physics.rawScore))],
            note: '모델 버전: ${orNone(physics.modelVersion)}',
          ),
        const SizedBox(height: TSpace.x2),
        if (alignment != null)
          AxisResultRow(
            title: '입술·음성 동기화 (SyncNet)',
            description: '입 움직임과 음성이 시간상 얼마나 맞는지 잽니다.',
            statusText: _status(alignment),
            metrics: [
              ('LSE-C · ${DetailScreen.notProbability}', metricText(alignment.lseC)),
              ('LSE-D · ${DetailScreen.notProbability}', metricText(alignment.lseD)),
              ('종합 판정에 포함', alignment.includedInFusion == true ? '예' : '아니오'),
            ],
            note: 'SyncNet은 진위를 가리는 모델이 아니라 동기화를 재는 보조 지표입니다.',
          ),
        if (result.axes.isEmpty) Text('축별 결과가 없습니다.', style: TText.body),
        const SectionTitle('분석 범위'),
        CoverageBar(
          videoDurationSec: c?.videoDurationSec,
          segments: c?.segments ?? const [],
          caption: coverageCaption(c),
          showTitle: false,
        ),
        const SizedBox(height: TSpace.x3),
        KeyValue(name: '영상 전체 길이', value: sec(c?.videoDurationSec)),
        KeyValue(name: '분석 대상 구간 길이', value: sec(c?.eligibleDurationSec)),
        KeyValue(name: '분석한 길이', value: sec(c?.analyzedDurationSec)),
        KeyValue(
          name: '분석한 구간',
          value: (c == null || c.segments.isEmpty)
              ? '없음'
              : [for (final (s, e) in c.segments) '${formatDuration(s)} ~ ${formatDuration(e)}'].join(', '),
        ),
        const SectionTitle('서버가 보낸 상태'),
        Text('작업이 끝난 것, 분석이 된 것, 판정을 낸 것은 서로 다릅니다.', style: TText.secondary),
        const SizedBox(height: TSpace.x2),
        KeyValue(name: '작업 (job_status)', value: orNone(result.rawString('job_status')), mono: true),
        KeyValue(name: '분석 (analysis_status)', value: orNone(result.rawString('analysis_status')), mono: true),
        KeyValue(name: '판정 (verdict_status)', value: orNone(result.rawString('verdict_status')), mono: true),
        KeyValue(
          name: '보류·실패 원인',
          value: orNone(result.abstentionReason ?? result.reasonCode),
          mono: true,
        ),
        KeyValue(name: '미디어 출처 (media_provenance)', value: orNone(result.mediaProvenance), mono: true),
        KeyValue(name: '분석 ID', value: orNone(result.analysisId), mono: true),
        KeyValue(name: 'YouTube 영상 ID', value: orNone(result.youtubeVideoId), mono: true),
        const SizedBox(height: TSpace.x4),
        SecondaryButton(label: '결과 요약으로 돌아가기', onPressed: onBack),
      ],
    );
  }
}
