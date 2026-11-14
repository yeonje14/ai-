import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design/tokens.dart';
import '../design/widgets.dart';
import '../view_state.dart';

/// 화면 3·4·5: 결과 요약 (의심 신호 발견 / 의심 신호 낮음 / 판단 보류).
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
  }) : assert(kind == ScreenKind.suspicious || kind == ScreenKind.low || kind == ScreenKind.abstained);

  final ScreenKind kind;
  final AnalysisResult result;
  final VoidCallback onShowDetail;
  final VoidCallback onRestart;

  static const lowDisclaimer = '"의심 신호 낮음"은 진짜 영상이라는 뜻이 아닙니다. '
      '분석하지 않은 구간과 영상 내용의 사실 여부는 확인하지 않았습니다.';
  static const suspiciousDisclaimer = '이 결과는 조작을 확정하지 않습니다. '
      '모델이 분석한 구간에서 관련 신호를 찾았다는 뜻이며, 영상 내용의 사실 여부와는 별개입니다.';

  @override
  Widget build(BuildContext context) {
    final (label, tone, headline) = switch (kind) {
      ScreenKind.suspicious => ('의심 신호 발견', StatusTone.accent, 'AI 조작 의심 신호가 발견됐습니다'),
      ScreenKind.low => ('의심 신호 낮음', StatusTone.neutral, '분석한 구간에서 의심 신호가 낮았습니다'),
      _ => ('판단 보류', StatusTone.warning, '판단을 보류했습니다'),
    };
    final c = result.coverage;
    final reason = reasonText(result.abstentionReason);
    return TrinityScaffold(
      children: [
        StatusLabel(text: label, tone: tone),
        const SizedBox(height: TSpace.x3),
        Semantics(header: true, child: Text(headline, style: TText.display)),
        const SizedBox(height: TSpace.x3),
        if (kind == ScreenKind.suspicious) const InfoBox(body: suspiciousDisclaimer, tone: StatusTone.accent),
        if (kind == ScreenKind.low) const InfoBox(body: lowDisclaimer, tone: StatusTone.neutral),
        if (kind == ScreenKind.abstained)
          InfoBox(
            title: '보류한 이유',
            body: '${reason ?? '이유가 기록되지 않았습니다.'}\n'
                '의심 신호가 있다고도 없다고도 판단하지 않았습니다.',
            tone: StatusTone.warning,
          ),
        for (final e in result.explanations)
          if (e.message.isNotEmpty) ...[
            const SizedBox(height: TSpace.x2),
            Text(e.message, style: TText.body),
          ],
        const SizedBox(height: TSpace.x4),
        CoverageBar(
          videoDurationSec: c?.videoDurationSec,
          segments: c?.segments ?? const [],
          caption: coverageCaption(c),
        ),
        const SizedBox(height: TSpace.x5),
        SecondaryButton(label: '판단 근거 보기', onPressed: onShowDetail),
        const SizedBox(height: TSpace.x2),
        PrimaryButton(label: '다른 영상 분석', onPressed: onRestart),
      ],
    );
  }
}

/// 화면 7: 영상 접근 불가. 진위를 추정하지 않는다.
class UnavailableScreen extends StatelessWidget {
  const UnavailableScreen({super.key, required this.result, required this.onShowDetail, required this.onRestart});

  final AnalysisResult result;
  final VoidCallback onShowDetail;
  final VoidCallback onRestart;

  @override
  Widget build(BuildContext context) {
    final code = result.reasonCode ?? result.abstentionReason;
    return TrinityScaffold(
      children: [
        const StatusLabel(text: '영상 접근 불가', tone: StatusTone.warning),
        const SizedBox(height: TSpace.x3),
        Semantics(header: true, child: Text('이 영상은 분석하지 않았습니다', style: TText.display)),
        const SizedBox(height: TSpace.x3),
        InfoBox(
          title: '분석하지 않은 이유',
          body: '${reasonText(code) ?? '이유가 기록되지 않았습니다.'}\n'
              '영상을 보지 않았으므로 의심 신호가 있다고도 없다고도 판단하지 않았습니다.',
          tone: StatusTone.warning,
        ),
        const SizedBox(height: TSpace.x3),
        Text('TRINITY는 분석이 허가된 영상만 다룹니다. 주소가 올바르게 접수된 것과 영상을 분석한 것은 다릅니다.', style: TText.body),
        const SizedBox(height: TSpace.x5),
        SecondaryButton(label: '판단 근거 보기', onPressed: onShowDetail),
        const SizedBox(height: TSpace.x2),
        PrimaryButton(label: '다른 영상 분석', onPressed: onRestart),
      ],
    );
  }
}

/// 화면 8: 분석 대상 아님. 범위 밖·미지원·품질 부족.
class OutOfScopeScreen extends StatelessWidget {
  const OutOfScopeScreen({super.key, required this.result, required this.onShowDetail, required this.onRestart});

  final AnalysisResult result;
  final VoidCallback onShowDetail;
  final VoidCallback onRestart;

  @override
  Widget build(BuildContext context) {
    final detail = reasonText(result.reasonCode ?? result.abstentionReason);
    return TrinityScaffold(
      children: [
        const StatusLabel(text: '분석 대상 아님', tone: StatusTone.muted),
        const SizedBox(height: TSpace.x3),
        Semantics(header: true, child: Text('이 영상은 판정하지 않습니다', style: TText.display)),
        const SizedBox(height: TSpace.x3),
        InfoBox(
          title: '판정하지 않는 이유',
          body: '${analysisStatusText[result.analysisStatus] ?? '분석할 수 있는 영상이 아닙니다.'}'
              '${detail == null ? '' : '\n$detail'}\n'
              '의심 신호가 있다고도 없다고도 판단하지 않았습니다.',
        ),
        const SizedBox(height: TSpace.x3),
        Text('TRINITY는 한 사람이 말하는 구간이 있는 영상을 대상으로 합니다.', style: TText.body),
        const SizedBox(height: TSpace.x5),
        SecondaryButton(label: '판단 근거 보기', onPressed: onShowDetail),
        const SizedBox(height: TSpace.x2),
        PrimaryButton(label: '다른 영상 분석', onPressed: onRestart),
      ],
    );
  }
}
