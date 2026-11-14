import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design/tokens.dart';
import '../design/widgets.dart';
import '../view_state.dart';

/// 화면 3·4·5·7·8: 결과 요약.
/// (의심 신호 발견 / 의심 신호 낮음 / 판단 보류 / 영상 접근 불가 / 분석 대상 아님)
///
/// 숫자 점수와 퍼센트를 쓰지 않는다. 분석 범위(시간)만 숫자로 나온다.
/// 진위를 확정하는 표현을 쓰지 않는다.
class ResultScreen extends StatelessWidget {
  const ResultScreen({
    super.key,
    required this.kind,
    required this.result,
    required this.onShowDetail,
    required this.onRestart,
  }) : assert(kind != ScreenKind.jobFailed);

  final ScreenKind kind;
  final AnalysisResult result;
  final VoidCallback onShowDetail;
  final VoidCallback onRestart;

  static const lowDisclaimer = '"의심 신호 낮음"은 진짜 영상이라는 뜻이 아니에요. '
      '분석하지 않은 구간과 영상 내용의 사실 여부는 확인하지 않았습니다.';
  static const suspiciousDisclaimer = '이 결과는 조작을 확정하지 않습니다. '
      '분석한 구간에서 관련 신호를 찾았다는 뜻이며, 영상 내용의 사실 여부와는 별개예요.';
  static const noJudgement = '의심 신호가 있다고도 없다고도 판단하지 않았습니다.';
  static const summaryNote = '작업이 끝났다고 진위가 확인된 것은 아니에요.';
  static const noReason = '이유가 기록되지 않았습니다.';

  static const labels = {
    ScreenKind.suspicious: '의심 신호 발견',
    ScreenKind.low: '의심 신호 낮음',
    ScreenKind.abstained: '판단 보류',
    ScreenKind.unavailable: '영상 접근 불가',
    ScreenKind.outOfScope: '분석 대상 아님',
  };

  static const tones = {
    ScreenKind.suspicious: StatusTone.suspicious,
    ScreenKind.low: StatusTone.low,
    ScreenKind.abstained: StatusTone.warning,
    ScreenKind.unavailable: StatusTone.warning,
    ScreenKind.outOfScope: StatusTone.muted,
  };

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final tone = tones[kind]!;
    final code = result.abstentionReason ?? result.reasonCode;
    final (headline, explanation, reasonTitle, reasonBody) = switch (kind) {
      ScreenKind.suspicious => ('AI 조작 의심 신호가\n발견됐어요.', suspiciousDisclaimer, null, null),
      ScreenKind.low => ('분석한 구간에서\n의심 신호가 낮았어요.', lowDisclaimer, null, null),
      ScreenKind.unavailable => (
          '이 영상은\n분석하지 않았어요.',
          '영상을 보지 않았으므로 $noJudgement',
          '분석하지 않은 이유',
          reasonText(code) ?? noReason,
        ),
      ScreenKind.outOfScope => (
          '이 영상은\n판정하지 않아요.',
          noJudgement,
          '판정하지 않는 이유',
          [
            analysisStatusText[result.analysisStatus] ?? '분석할 수 있는 영상이 아닙니다.',
            if (reasonText(code) != null) reasonText(code)!,
          ].join('\n'),
        ),
      _ => ('판단을\n보류했어요.', noJudgement, '판단을 보류한 이유', reasonText(code) ?? noReason),
    };
    final showCoverage =
        kind == ScreenKind.suspicious || kind == ScreenKind.low || kind == ScreenKind.abstained;
    final c = result.coverage;

    final main = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        StatusLabel(text: labels[kind]!, tone: tone),
        const SizedBox(height: TSpace.x3),
        Semantics(header: true, child: Text(headline, style: TText.display.copyWith(color: p.ink))),
        const SizedBox(height: TSpace.x3),
        if (reasonTitle == null)
          InfoBox(body: explanation, tone: tone)
        else ...[
          Text(explanation, style: TText.body.copyWith(color: p.muted)),
          const SizedBox(height: TSpace.x3),
          InfoBox(title: reasonTitle, body: reasonBody!, tone: tone),
        ],
        // 서버 설명 가운데 위의 이유와 같은 원인 코드는 되풀이하지 않는다
        for (final e in result.explanations)
          if (e.message.isNotEmpty && !(reasonTitle != null && e.reasonCode == code && reasonText(code) != null)) ...[
            const SizedBox(height: TSpace.x3),
            Text(e.message, style: TText.body.copyWith(color: p.ink)),
          ],
        if (kind == ScreenKind.unavailable) ...[
          const SizedBox(height: TSpace.x3),
          Text(
            'TRINITY는 분석이 허가된 영상만 다룹니다. 주소가 올바르게 접수된 것과 영상을 분석한 것은 달라요.',
            style: TText.body.copyWith(color: p.muted),
          ),
        ],
        if (kind == ScreenKind.outOfScope) ...[
          const SizedBox(height: TSpace.x3),
          Text('TRINITY는 한 사람이 말하는 구간이 있는 영상을 대상으로 합니다.', style: TText.body.copyWith(color: p.muted)),
        ],
      ],
    );
    final summary = _StatusSummary(
      job: jobStatusText[result.jobStatus]!,
      analysis: result.analysisStatus == null ? '값 없음' : analysisStatusLabel[result.analysisStatus]!,
      verdict: verdictText(kind),
    );

    return TrinityScaffold(
      children: [
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: TextLinkButton(label: '새 영상 확인', leading: Icons.arrow_back, onPressed: onRestart),
        ),
        const SizedBox(height: TSpace.x2),
        if (isAppLayout(context)) ...[
          main,
          const SizedBox(height: TSpace.x4),
          summary,
        ] else
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: main),
              const SizedBox(width: TSpace.x4),
              SizedBox(width: 250, child: summary),
            ],
          ),
        if (showCoverage) ...[
          const SizedBox(height: TSpace.x4),
          CoverageBar(
            videoDurationSec: c?.videoDurationSec,
            segments: c?.segments ?? const [],
            caption: coverageCaption(c),
            endLabel: c?.videoDurationSec == null ? null : formatClock(c!.videoDurationSec!),
          ),
        ],
        const SizedBox(height: TSpace.x4),
        Wrap(
          spacing: TSpace.x3,
          runSpacing: TSpace.x2,
          children: [
            PrimaryButton(label: '판단 근거 살펴보기', icon: Icons.arrow_forward, onPressed: onShowDetail),
            SecondaryButton(label: '다른 영상 확인', onPressed: onRestart),
          ],
        ),
      ],
    );
  }
}

/// "이번 요청의 상태": 작업·분석·판정을 따로 보여 준다.
class _StatusSummary extends StatelessWidget {
  const _StatusSummary({required this.job, required this.analysis, required this.verdict});

  final String job;
  final String analysis;
  final String verdict;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    Widget row(String name, String value) => Container(
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.line))),
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Wrap(
            alignment: WrapAlignment.spaceBetween,
            spacing: TSpace.x3,
            children: [
              Text(name, style: TText.secondary.copyWith(color: p.muted)),
              Text(value, style: TText.secondary.copyWith(color: p.ink, fontWeight: FontWeight.w700)),
            ],
          ),
        );
    return Semantics(
      container: true,
      label: '이번 요청의 상태. 작업 $job, 분석 $analysis, 판정 $verdict. ${ResultScreen.summaryNote}',
      child: ExcludeSemantics(
        child: Panel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('이번 요청의 상태', style: TText.h3.copyWith(color: p.ink)),
              const SizedBox(height: TSpace.x1),
              row('작업', job),
              row('분석', analysis),
              row('판정', verdict),
              const SizedBox(height: TSpace.x3),
              Text(ResultScreen.summaryNote, style: TText.small.copyWith(color: p.muted)),
            ],
          ),
        ),
      ),
    );
  }
}
