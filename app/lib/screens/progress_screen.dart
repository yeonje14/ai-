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
    this.pollWarning,
    this.failureReasonCode,
    this.onCancel,
    this.cancelRequested = false,
    this.cancelError,
    required this.onRestart,
  });

  final JobState state;

  /// 상태 조회가 실패해 다시 시도하는 중인지.
  final String? pollWarning;
  final String? failureReasonCode;
  final VoidCallback onRestart;
  final VoidCallback? onCancel;
  final bool cancelRequested;
  final String? cancelError;

  static const notVerdict = '결과가 없습니다. 영상에 대한 판정이 아니에요.';

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
    return TrinityScaffold(
      children: [
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
        if (pollWarning != null && !stopped) ...[
          const SizedBox(height: TSpace.x3),
          InfoBox(
            title: pollWarning!,
            body: '상태를 다시 확인하고 있습니다. 분석은 서버에서 계속됩니다.',
            tone: StatusTone.warning,
          ),
        ],
        const SizedBox(height: TSpace.x4),
        StageProgress(state: state),
        if (job == JobStatus.processing && ['fusion', 'finalizing'].contains(state.stage))
          Text(stageLabels[state.stage]!, style: TText.bodyStrong.copyWith(color: p.ink)),
        if (state.isActive && onCancel != null) ...[
          const SizedBox(height: TSpace.x4),
          OutlinedButton(
            onPressed: cancelRequested ? null : onCancel,
            child: Text(TrinityNav.of(context)?.replayMode == true ? '재생 종료' : (cancelRequested ? '취소 요청 중…' : '분석 취소')),
          ),
          if (cancelRequested) ...[
            const SizedBox(height: TSpace.x2),
            Text('작업을 멈추고 정리한 뒤 결과를 보여 드립니다.', style: TText.body.copyWith(color: p.muted)),
          ],
          if (cancelError != null) ...[
            const SizedBox(height: TSpace.x2),
            InfoBox(title: '취소 요청을 확인하지 못했어요', body: cancelError!, tone: StatusTone.warning),
          ],
        ],
        if (stopped) ...[
          const SizedBox(height: TSpace.x4),
          PrimaryButton(label: '처음으로', onPressed: onRestart),
        ],
      ],
    );
  }
}

/// 서버가 완료한 단계만 막대에 채운다. 후속 단계로 넘어간 기록으로 건너뜀을 구분한다.
class StageProgress extends StatelessWidget {
  const StageProgress({super.key, required this.state});

  final JobState state;
  static const stages = [
    ('preprocessing', '영상 확인 · Gate'),
    ('waverep', '화질 신호'),
    ('motionphys', '움직임'),
    ('syncnet', '입과 소리'),
  ];

  String _status(String stage) {
    if (state.completedStages.contains(stage)) return '끝남';
    final current = state.stage;
    if (state.jobStatus == JobStatus.processing &&
        (current == stage || (stage == 'preprocessing' && ['validating', 'access_check'].contains(current)))) {
      return '진행 중';
    }
    final position = stageOrder.indexOf(stage);
    if (state.jobStatus == JobStatus.finished ||
        (current != null && stageOrder.indexOf(current) > position) ||
        state.completedStages.any((s) => stageOrder.indexOf(s) > position)) {
      return '건너뜀';
    }
    if (state.jobStatus == JobStatus.cancelled || state.jobStatus == JobStatus.failed) return '중단';
    return '대기';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      ExcludeSemantics(child: Row(children: [
        for (final (stage, _) in stages)
          Expanded(child: Container(
            height: 10, margin: const EdgeInsets.symmetric(horizontal: 2),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              color: p.soft,
              gradient: _status(stage) == '끝남' ? const LinearGradient(
                colors: [Color(0xFF7C6CFF), Color(0xFF3D7BFF)]) : null,
            ),
          )),
      ])),
      const SizedBox(height: TSpace.x3),
      for (final (stage, label) in stages)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Wrap(alignment: WrapAlignment.spaceBetween, spacing: TSpace.x2, children: [
            Text(label, style: TText.bodyStrong.copyWith(color: p.ink)),
            Text(_status(stage), style: TText.body.copyWith(color: p.muted)),
          ]),
        ),
    ]));
  }
}
