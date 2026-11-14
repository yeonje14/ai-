/// 공통 컴포넌트. 정의는 docs/design-system.md.
///
/// 글자 크기를 키워도 깨지지 않도록 고정 높이를 쓰지 않고(최소 높이만 둔다),
/// 가로로 나란한 글자는 Expanded/Wrap으로 줄바꿈되게 한다.
library;

import 'package:flutter/material.dart';

import 'tokens.dart';

/// 상태의 색조. 색만으로 뜻을 전하지 않는다. 항상 글자 라벨이 함께 있다.
enum StatusTone {
  accent(TColors.accent),
  warning(TColors.warning),
  neutral(TColors.neutral),
  muted(TColors.textSecondary);

  const StatusTone(this.color);
  final Color color;
}

/// 상단 고지 띠. 실제 모델을 연결하기 전까지 모든 화면에 둔다.
class NoticeBand extends StatelessWidget {
  const NoticeBand({super.key, this.text = defaultText});

  static const defaultText = '모델 미연결 · 가상 데이터';
  final String text;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: text,
      child: Container(
        width: double.infinity,
        decoration: const BoxDecoration(
          color: TColors.surface,
          border: Border(bottom: BorderSide(color: TColors.border)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: TSpace.screen, vertical: TSpace.x2),
        child: ExcludeSemantics(child: Text(text, style: TText.mono)),
      ),
    );
  }
}

/// 화면 공통 틀: 고지 띠 + 스크롤되는 본문(좌우 여백 20, 넓은 화면에서는 가운데 정렬).
class TrinityScaffold extends StatelessWidget {
  const TrinityScaffold({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            const NoticeBand(),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: TSpace.screen, vertical: TSpace.x4),
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: TSize.contentMax),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ButtonBase extends StatelessWidget {
  const _ButtonBase({required this.label, required this.onPressed, required this.filled});

  final String label;
  final VoidCallback? onPressed;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final fg = filled ? TColors.background : TColors.text;
    final bg = filled ? (enabled ? TColors.text : TColors.textSecondary) : Colors.transparent;
    return Semantics(
      button: true,
      enabled: enabled,
      child: Material(
        color: bg,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.zero,
          side: filled ? BorderSide.none : BorderSide(color: enabled ? TColors.text : TColors.textSecondary),
        ),
        child: InkWell(
          onTap: onPressed,
          focusColor: filled ? TColors.neutral : TColors.border,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: TSize.touch),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: TSpace.x3, vertical: TSpace.x2),
              child: Center(
                child: Text(
                  label,
                  textAlign: TextAlign.center,
                  style: TText.bodyStrong.copyWith(color: enabled || filled ? fg : TColors.textSecondary),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 기본 버튼: 화면에서 가장 중요한 동작 하나에 쓴다. 강조색(주황)은 쓰지 않는다.
class PrimaryButton extends StatelessWidget {
  const PrimaryButton({super.key, required this.label, required this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => _ButtonBase(label: label, onPressed: onPressed, filled: true);
}

/// 보조 버튼: 테두리만 있는 버튼.
class SecondaryButton extends StatelessWidget {
  const SecondaryButton({super.key, required this.label, required this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => _ButtonBase(label: label, onPressed: onPressed, filled: false);
}

/// 상태 라벨: 색 사각형 + 글자. 테두리와 글자가 같은 색조다.
class StatusLabel extends StatelessWidget {
  const StatusLabel({super.key, required this.text, required this.tone});

  final String text;
  final StatusTone tone;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: AlignmentDirectional.centerStart,
      child: Container(
        decoration: BoxDecoration(color: TColors.surface, border: Border.all(color: tone.color)),
        padding: const EdgeInsets.symmetric(horizontal: TSpace.x2, vertical: TSpace.x1),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(width: 10, height: 10, color: tone.color),
            const SizedBox(width: TSpace.x2),
            Flexible(child: Text(text, style: TText.label.copyWith(color: tone.color))),
          ],
        ),
      ),
    );
  }
}

enum StageState { done, current, pending }

/// 단계 목록 행. 진행률 숫자를 쓰지 않고 단계 이름과 상태 글자만 보여 준다.
class StageRow extends StatelessWidget {
  const StageRow({super.key, required this.label, required this.state});

  final String label;
  final StageState state;

  static const stateText = {
    StageState.done: '완료',
    StageState.current: '진행 중',
    StageState.pending: '대기',
  };

  @override
  Widget build(BuildContext context) {
    final current = state == StageState.current;
    final color = state == StageState.pending ? TColors.textSecondary : TColors.text;
    return Semantics(
      container: true,
      label: '$label, ${stateText[state]}',
      child: ExcludeSemantics(
        child: Container(
          constraints: const BoxConstraints(minHeight: TSize.touch),
          decoration: BoxDecoration(
            color: current ? TColors.surface : null,
            border: const Border(bottom: BorderSide(color: TColors.border)),
          ),
          padding: const EdgeInsets.symmetric(horizontal: TSpace.x2, vertical: TSpace.x2),
          child: Row(
            children: [
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  color: state == StageState.pending ? null : color,
                  border: Border.all(color: color),
                ),
              ),
              const SizedBox(width: TSpace.x3),
              Expanded(child: Text(label, style: (current ? TText.bodyStrong : TText.body).copyWith(color: color))),
              const SizedBox(width: TSpace.x2),
              Text(stateText[state]!, style: TText.secondary.copyWith(color: color)),
            ],
          ),
        ),
      ),
    );
  }
}

/// 분석 범위 막대. 영상 전체 길이 위에 분석한 구간을 표시한다.
/// 분석한 양이며 정확도나 신뢰도가 아니다. 그 문구를 항상 함께 둔다.
class CoverageBar extends StatelessWidget {
  const CoverageBar({
    super.key,
    required this.videoDurationSec,
    required this.segments,
    required this.caption,
    this.showTitle = true,
  });

  /// 바로 위에 같은 이름의 구역 제목이 있으면 끈다.
  final bool showTitle;
  final double? videoDurationSec;

  /// (시작 초, 끝 초)
  final List<(double, double)> segments;
  final String caption;

  static const disclaimer = '분석한 양이며 정확도나 신뢰도가 아닙니다.';

  @override
  Widget build(BuildContext context) {
    final total = videoDurationSec;
    return Semantics(
      container: true,
      label: '분석 범위. $caption $disclaimer',
      child: ExcludeSemantics(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (showTitle) ...[
              Text('분석 범위', style: TText.label),
              const SizedBox(height: TSpace.x2),
            ],
            Container(
              height: 16,
              decoration: BoxDecoration(color: TColors.surface, border: Border.all(color: TColors.textSecondary)),
              child: (total == null || total <= 0)
                  ? null
                  : LayoutBuilder(
                      builder: (context, box) => Stack(
                        children: [
                          for (final (start, end) in segments)
                            Positioned(
                              left: box.maxWidth * (start / total).clamp(0.0, 1.0),
                              width: box.maxWidth * ((end - start) / total).clamp(0.0, 1.0),
                              top: 0,
                              bottom: 0,
                              child: const ColoredBox(color: TColors.text),
                            ),
                        ],
                      ),
                    ),
            ),
            const SizedBox(height: TSpace.x2),
            Text(caption, style: TText.body),
            Text(disclaimer, style: TText.secondary),
          ],
        ),
      ),
    );
  }
}

/// 축별 결과 행. 지표는 이름 위, 값 아래로 쌓아 글자가 커져도 넘치지 않게 한다.
class AxisResultRow extends StatelessWidget {
  const AxisResultRow({
    super.key,
    required this.title,
    required this.description,
    required this.statusText,
    required this.metrics,
    this.note,
  });

  final String title;
  final String description;
  final String statusText;

  /// (지표 이름, 값). 값이 없으면 "값 없음"을 넘긴다. 0으로 바꾸지 않는다.
  final List<(String, String)> metrics;
  final String? note;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(color: TColors.surface, border: Border.all(color: TColors.border)),
      padding: const EdgeInsets.all(TSpace.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: TText.bodyStrong),
          Text(description, style: TText.secondary),
          const SizedBox(height: TSpace.x2),
          Text('상태: $statusText', style: TText.body),
          for (final (name, value) in metrics) ...[
            const SizedBox(height: TSpace.x2),
            Text(name, style: TText.secondary),
            // 숫자는 고정폭, 글자("값 없음" 등)는 본문 글꼴
            Text(
              value,
              style: RegExp(r'^[-\d]').hasMatch(value) ? TText.mono.copyWith(fontSize: TFont.body) : TText.body,
            ),
          ],
          if (note != null) ...[
            const SizedBox(height: TSpace.x2),
            Text(note!, style: TText.secondary),
          ],
        ],
      ),
    );
  }
}

/// 안내 박스. 왼쪽 굵은 선의 색으로 색조를 보이고 내용은 글자로 전한다.
class InfoBox extends StatelessWidget {
  const InfoBox({super.key, this.title, required this.body, this.tone = StatusTone.muted});

  final String? title;
  final String body;
  final StatusTone tone;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: TColors.surface,
        border: Border(
          left: BorderSide(color: tone.color, width: 4),
          top: const BorderSide(color: TColors.border),
          right: const BorderSide(color: TColors.border),
          bottom: const BorderSide(color: TColors.border),
        ),
      ),
      padding: const EdgeInsets.all(TSpace.x3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (title != null) ...[
            Text(title!, style: TText.bodyStrong),
            const SizedBox(height: TSpace.x1),
          ],
          Text(body, style: TText.body),
        ],
      ),
    );
  }
}

/// 구역 제목.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: TSpace.x5, bottom: TSpace.x2),
      child: Semantics(header: true, child: Text(text, style: TText.title)),
    );
  }
}

/// 이름-값 한 쌍(세로로 쌓는다).
class KeyValue extends StatelessWidget {
  const KeyValue({super.key, required this.name, required this.value, this.mono = false});

  final String name;
  final String value;
  final bool mono;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: TSpace.x2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(name, style: TText.secondary),
          Text(value, style: mono ? TText.mono.copyWith(fontSize: TFont.body) : TText.body),
        ],
      ),
    );
  }
}
