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
  static const rawNotice = '아래는 가상 데이터입니다. 원시 지표는 가짜일 확률이 아니며, 값 하나로 진위를 말할 수 없어요.';
  static const syncNote = 'SyncNet은 진위를 가리는 모델이 아니라 동기화를 재는 보조 지표입니다.';
  static const noOverall = '검증된 결합 모델이 없어 종합 점수는 값 없음으로 표시합니다.';

  String _status(AxisResult a) {
    final text = axisStatusText[a.status] ?? '알 수 없음';
    final why = reasonText(a.reasonCode);
    return why == null ? text : '$text · $why';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final signal = result.axes['signal'], physics = result.axes['physics'], alignment = result.axes['alignment'];
    final c = result.coverage;
    String orNone(String? v) => (v == null || v.isEmpty) ? '값 없음' : v;
    String sec(double? v) => v == null ? '값 없음' : formatDuration(v);
    return TrinityScaffold(
      children: [
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: TextLinkButton(label: '결과 요약으로', leading: Icons.arrow_back, onPressed: onBack),
        ),
        const SizedBox(height: TSpace.x2),
        const Overline('BEHIND THE RESULT'),
        const SizedBox(height: TSpace.x2),
        Semantics(header: true, child: Text('판단 근거를\n하나씩 살펴보세요.', style: TText.display.copyWith(color: p.ink))),
        const SizedBox(height: TSpace.x3),
        const InfoBox(title: DetailScreen.notProbability, body: DetailScreen.rawNotice, tone: StatusTone.warning),
        const SizedBox(height: TSpace.x4),
        if (signal != null)
          AxisResultRow(
            title: '영상의 미세한 신호',
            description: 'WaveRep · 프레임에서 AI 생성 관련 특징을 찾습니다.',
            statusText: _status(signal),
            metrics: [('원시 점수 · ${DetailScreen.notProbability}', metricText(signal.rawScore))],
            note: '모델 버전: ${orNone(signal.modelVersion)}',
          ),
        if (physics != null)
          AxisResultRow(
            title: '움직임의 패턴',
            description: 'MotionPhys · 추적한 점들의 움직임 통계를 봅니다.',
            statusText: _status(physics),
            metrics: [('원시 점수 · ${DetailScreen.notProbability}', metricText(physics.rawScore))],
            note: '모델 버전: ${orNone(physics.modelVersion)}',
          ),
        if (alignment != null)
          AxisResultRow(
            title: '입술·음성 동기화',
            description: 'SyncNet · 소리와 입 움직임의 시간 차이를 잽니다.',
            statusText: _status(alignment),
            metrics: [
              ('LSE-C · ${DetailScreen.notProbability}', metricText(alignment.lseC)),
              ('LSE-D · ${DetailScreen.notProbability}', metricText(alignment.lseD)),
              ('종합 판정에 포함', alignment.includedInFusion == true ? '예' : '아니오'),
            ],
          ),
        if (result.axes.isEmpty) Text('축별 결과가 없습니다.', style: TText.body.copyWith(color: p.ink)),
        InfoBox(
          body: result.overallScore == null ? '${DetailScreen.syncNote} ${DetailScreen.noOverall}' : DetailScreen.syncNote,
        ),
        const SizedBox(height: TSpace.x4),
        CoverageBar(
          videoDurationSec: c?.videoDurationSec,
          segments: c?.segments ?? const [],
          caption: coverageCaption(c),
          endLabel: c?.videoDurationSec == null ? null : formatClock(c!.videoDurationSec!),
        ),
        const SizedBox(height: TSpace.x3),
        KeyValue(name: '영상 전체 길이', value: sec(c?.videoDurationSec)),
        KeyValue(name: '분석 대상 구간 길이', value: sec(c?.eligibleDurationSec)),
        KeyValue(name: '분석한 길이', value: sec(c?.analyzedDurationSec)),
        KeyValue(
          name: '분석한 구간',
          value: (c == null || c.segments.isEmpty)
              ? '없음'
              : [for (final (s, e) in c.segments) '${formatClock(s)}–${formatClock(e)}'].join(' · '),
        ),
        const SectionTitle('서버가 보낸 상태'),
        Text('작업이 끝난 것, 분석이 된 것, 판정을 낸 것은 서로 달라요.', style: TText.secondary.copyWith(color: p.muted)),
        const SizedBox(height: TSpace.x2),
        KeyValue(name: '작업 (job_status)', value: orNone(result.rawString('job_status')), mono: true),
        KeyValue(name: '분석 (analysis_status)', value: orNone(result.rawString('analysis_status')), mono: true),
        KeyValue(name: '판정 (verdict_status)', value: orNone(result.rawString('verdict_status')), mono: true),
        KeyValue(name: '보류·실패 원인', value: orNone(result.abstentionReason ?? result.reasonCode), mono: true),
        KeyValue(name: '미디어 출처 (media_provenance)', value: orNone(result.mediaProvenance), mono: true),
        KeyValue(name: '분석 ID', value: orNone(result.analysisId), mono: true),
        KeyValue(name: 'YouTube 영상 ID', value: orNone(result.youtubeVideoId), mono: true),
        const SizedBox(height: TSpace.x4),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: SecondaryButton(label: '결과 요약으로 돌아가기', onPressed: onBack),
        ),
      ],
    );
  }
}
