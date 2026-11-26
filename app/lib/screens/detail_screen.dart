import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design/tokens.dart';
import '../design/widgets.dart';
import '../view_state.dart';
import 'result_screen.dart';

/// 분석한 구간의 품질, 신호별 상태와 서버 기록을 보여 준다.
class DetailScreen extends StatelessWidget {
  const DetailScreen({super.key, required this.result, required this.onBack});

  final AnalysisResult result;
  final VoidCallback onBack;

  static const serverRawNotice = '연구용 시제품에서 관찰한 구간과 신호입니다.';
  static const syncNote = 'SyncNet은 입술과 음성의 동기화를 확인하는 보조 지표입니다.';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
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
        Semantics(header: true, child: Text('판단 근거 살펴보기', style: TText.display.copyWith(color: p.ink))),
        const SizedBox(height: TSpace.x3),
        Text(serverRawNotice, style: TText.body.copyWith(color: p.muted)),
        const SectionTitle('구간별 영상 품질'),
        for (final e in result.explanations.where(isWindowEvidence))
          Padding(padding: const EdgeInsets.only(bottom: TSpace.x2), child: Text(e.message, style: TText.body.copyWith(color: p.ink))),
        if (!result.explanations.any((e) => e.templateId == 'GATE_ELIGIBLE_SEGMENT' || e.templateId == 'GATE_EXCLUDED_SEGMENT'))
          Text('얼굴 크기와 선명도 측정 기록이 없습니다.', style: TText.body.copyWith(color: p.muted)),
        const SectionTitle('신호별 확인 내용'),
        SignalCards(result: result, includeReasons: true),
        const InfoBox(body: syncNote),
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
        KeyValue(name: '보류·실패 원인', value: orNone(result.reasonCode ?? result.abstentionReason), mono: true),
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
