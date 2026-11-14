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

  @override
  Widget build(BuildContext context) {
    final job = state.jobStatus;
    final stopped = job == JobStatus.failed || job == JobStatus.cancelled;
    final (label, tone, headline, body) = switch (job) {
      JobStatus.queued => ('대기 중', StatusTone.muted, '분석 순서를 기다리고 있습니다', '앞선 분석이 끝나면 시작합니다.'),
      JobStatus.failed => ('분석 실패', StatusTone.warning, '분석을 끝내지 못했습니다', '결과가 없습니다. 영상에 대한 판정이 아닙니다.'),
      JobStatus.cancelled => ('취소됨', StatusTone.muted, '분석이 취소됐습니다', '결과가 없습니다. 영상에 대한 판정이 아닙니다.'),
      JobStatus.finished => ('작업 종료', StatusTone.muted, '결과를 불러오고 있습니다', '잠시만 기다려 주세요.'),
      _ => ('분석 중', StatusTone.muted, '영상을 분석하고 있습니다', '단계가 끝날 때마다 아래 목록이 바뀝니다.'),
    };
    final done = state.completedStages.toSet();
    return TrinityScaffold(
      children: [
        StatusLabel(text: label, tone: tone),
        const SizedBox(height: TSpace.x3),
        Semantics(header: true, liveRegion: true, child: Text(headline, style: TText.display)),
        const SizedBox(height: TSpace.x2),
        Text(body, style: TText.body),
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
            title: '연결이 끊겼습니다',
            body: '상태를 다시 확인하고 있습니다. 분석은 서버에서 계속됩니다.',
            tone: StatusTone.warning,
          ),
        ],
        const SectionTitle('단계'),
        for (final stage in stageOrder)
          StageRow(
            label: stageLabels[stage]!,
            state: done.contains(stage)
                ? StageState.done
                : (stage == state.stage && job == JobStatus.processing ? StageState.current : StageState.pending),
          ),
        if (stopped) ...[
          const SizedBox(height: TSpace.x4),
          PrimaryButton(label: '처음으로', onPressed: onRestart),
        ],
      ],
    );
  }
}
