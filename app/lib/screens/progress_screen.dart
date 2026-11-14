import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design/tokens.dart';
import '../design/widgets.dart';
import '../view_state.dart';

/// 화면 2: 분석 중. 단계 이름만 보여 준다. 진행률 숫자(%)는 쓰지 않는다.
///
/// 작업이 실패·취소로 끝나면 같은 화면에서 "끝내지 못함"을 알린다(판정이 아니다).
class ProgressScreen extends StatelessWidget {
  const ProgressScreen({
    super.key,
    required this.state,
    this.connectionLost = false,
    this.failureReasonCode,
    required this.onRestart,
  });

  final JobState state;

  /// 상태 조회가 실패해 다시 시도하는 중인지.
  final bool connectionLost;
  final String? failureReasonCode;
  final VoidCallback onRestart;

  static const notVerdict = '결과가 없습니다. 영상에 대한 판정이 아니에요.';

  Widget _row(String stage, Set<String> done) => StageRow(
        label: stageLabels[stage]!,
        state: done.contains(stage)
            ? StageState.done
            : (stage == state.stage && state.jobStatus == JobStatus.processing ? StageState.current : StageState.pending),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final job = state.jobStatus;
    final stopped = job == JobStatus.failed || job == JobStatus.cancelled;
    final (label, tone, headline, body) = switch (job) {
      JobStatus.queued => ('대기 중', StatusTone.muted, '분석 순서를 기다리고 있어요.', '앞선 분석이 끝나면 시작합니다.'),
      JobStatus.failed => ('분석 실패', StatusTone.warning, '분석을 끝내지 못했어요.', notVerdict),
      JobStatus.cancelled => ('취소됨', StatusTone.muted, '분석이 취소됐어요.', notVerdict),
      JobStatus.finished => ('작업 종료', StatusTone.muted, '결과를 불러오고 있어요.', '잠시만 기다려 주세요.'),
      _ => ('분석 중', StatusTone.muted, '영상을 살펴보고 있어요.', '영상 접근을 확인한 뒤, 말하는 사람이 나오는 구간을 살펴봅니다.'),
    };
    final done = state.completedStages.toSet();
    final half = (stageOrder.length / 2).ceil();
    return TrinityScaffold(
      children: [
        const Overline('ANALYSIS IN PROGRESS'),
        const SizedBox(height: TSpace.x2),
        StatusLabel(text: label, tone: tone),
        const SizedBox(height: TSpace.x3),
        Semantics(header: true, liveRegion: true, child: Text(headline, style: TText.display.copyWith(color: p.ink))),
        const SizedBox(height: TSpace.x2),
        Text(body, style: TText.body.copyWith(color: p.muted)),
        if (stopped) ...[
          const SizedBox(height: TSpace.x3),
          InfoBox(
            title: '끝내지 못한 이유',
            body: reasonText(failureReasonCode) ?? '이유가 기록되지 않았습니다.',
            tone: StatusTone.warning,
          ),
        ],
        if (connectionLost && !stopped) ...[
          const SizedBox(height: TSpace.x3),
          const InfoBox(
            title: '연결이 끊겼어요',
            body: '상태를 다시 확인하고 있습니다. 분석은 서버에서 계속됩니다.',
            tone: StatusTone.warning,
          ),
        ],
        const SizedBox(height: TSpace.x4),
        if (isAppLayout(context))
          for (final stage in stageOrder) _row(stage, done)
        else
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: Column(children: [for (final s in stageOrder.take(half)) _row(s, done)])),
              const SizedBox(width: TSpace.x5),
              Expanded(child: Column(children: [for (final s in stageOrder.skip(half)) _row(s, done)])),
            ],
          ),
        if (stopped) ...[
          const SizedBox(height: TSpace.x4),
          PrimaryButton(label: '처음으로', onPressed: onRestart),
        ],
      ],
    );
  }
}
