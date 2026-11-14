/// 공통 컴포넌트. 정의는 docs/design-system.md.
///
/// 글자 크기를 키워도 깨지지 않도록 고정 높이를 쓰지 않고(최소 높이만 둔다),
/// 가로로 나란한 글자는 Expanded/Wrap으로 줄바꿈되게 한다.
library;

import 'package:flutter/material.dart';

import 'tokens.dart';

export 'tokens.dart' show StatusTone;

/// 화면들이 공유하는 이동 동작(처음으로, 이용 안내). 없으면 상단의 해당 버튼을 그리지 않는다.
class TrinityNav extends InheritedWidget {
  const TrinityNav({super.key, required this.onHome, required this.onGuide, this.inGuide = false, required super.child});

  final VoidCallback onHome;
  final VoidCallback onGuide;
  final bool inGuide;

  static TrinityNav? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<TrinityNav>();

  @override
  bool updateShouldNotify(TrinityNav old) => old.inGuide != inGuide;
}

/// 좁은 화면(앱 배치)인지. 768 이하면 앱 배치다.
bool isAppLayout(BuildContext context) => MediaQuery.sizeOf(context).width <= TSize.appLayoutMax;

/// 상단 고지 띠. 실제 모델을 연결하기 전까지 모든 화면 맨 위에 둔다.
class NoticeBand extends StatelessWidget {
  const NoticeBand({super.key});

  static const text = '모델 미연결 · 가상 데이터';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      container: true,
      label: text,
      child: ExcludeSemantics(
        child: Container(
          width: double.infinity,
          color: p.soft,
          padding: const EdgeInsets.symmetric(horizontal: TSpace.screen, vertical: TSpace.x2),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.science_outlined, size: 16, color: p.ink),
              const SizedBox(width: TSpace.x2),
              Flexible(child: Text(text, style: TText.small.copyWith(color: p.ink, fontWeight: FontWeight.w700))),
            ],
          ),
        ),
      ),
    );
  }
}

/// 상단 줄의 모양.
enum HeaderStyle {
  /// 로고 + 메뉴(영상 확인 / 이용 안내). 앱 배치와 홈이 아닌 화면.
  full,

  /// 오른쪽 위의 작은 "이용 안내"만. 웹 홈.
  guideOnly,
}

class TrinityHeader extends StatelessWidget {
  const TrinityHeader({super.key, required this.style});

  final HeaderStyle style;

  @override
  Widget build(BuildContext context) {
    final nav = TrinityNav.of(context);
    final p = context.palette;
    if (style == HeaderStyle.guideOnly) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: TSpace.screen),
        child: Align(
          alignment: AlignmentDirectional.centerEnd,
          child: nav == null ? const SizedBox(height: TSize.touch) : TextLinkButton(label: '이용 안내', onPressed: nav.onGuide),
        ),
      );
    }
    Widget item(String label, bool current, VoidCallback onTap) => Semantics(
          button: true,
          selected: current,
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(TRadius.control),
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: TSize.touch),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: TSpace.x2),
                child: Center(
                  widthFactor: 1,
                  child: Text(
                    label,
                    style: TText.secondary.copyWith(
                      color: current ? p.ink : p.muted,
                      fontWeight: FontWeight.w700,
                      decoration: current ? TextDecoration.underline : null,
                    ),
                  ),
                ),
              ),
            ),
          ),
        );
    final logo = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 30,
          height: 30,
          decoration: BoxDecoration(color: p.ink, borderRadius: BorderRadius.circular(7)),
          child: Icon(Icons.remove_red_eye_outlined, size: 18, color: p.paper),
        ),
        const SizedBox(width: TSpace.x2),
        // 글자를 크게 키운 좁은 화면에서는 로고 글자를 줄여 한 줄에 맞춘다
        Flexible(
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Text('TRINITY', style: TText.bodyStrong.copyWith(fontSize: 18, letterSpacing: 1.6, color: p.ink)),
          ),
        ),
      ],
    );
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: TSpace.screen, vertical: TSpace.x1),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Semantics(
            button: nav != null,
            label: 'TRINITY 처음으로',
            child: ExcludeSemantics(
              child: InkWell(
                onTap: nav?.onHome,
                borderRadius: BorderRadius.circular(TRadius.control),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: TSize.touch),
                  child: Center(widthFactor: 1, child: logo),
                ),
              ),
            ),
          ),
          if (nav != null)
            Wrap(
              children: [
                item('영상 확인', !nav.inGuide, nav.onHome),
                item('이용 안내', nav.inGuide, nav.onGuide),
              ],
            ),
        ],
      ),
    );
  }
}

/// 화면 공통 틀: 고지 띠 + 상단 줄 + 스크롤되는 본문 + 맨 아래 한 줄 안내.
class TrinityScaffold extends StatelessWidget {
  const TrinityScaffold({
    super.key,
    required this.children,
    this.header = HeaderStyle.full,
    this.maxWidth = TSize.contentMax,
    this.topGap = TSpace.x4,
  });

  final List<Widget> children;
  final HeaderStyle header;
  final double maxWidth;

  /// 상단 줄과 본문 사이의 간격.
  final double topGap;

  static const footerText = '영상 내용의 사실 여부를 확인하는 서비스는 아닙니다.';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            const NoticeBand(),
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TrinityHeader(style: header),
                    Padding(
                      padding: EdgeInsets.fromLTRB(TSpace.screen, topGap, TSpace.screen, TSpace.x5),
                      child: Center(
                        child: ConstrainedBox(
                          constraints: BoxConstraints(maxWidth: maxWidth),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(TSpace.screen, 0, TSpace.screen, TSpace.x4),
                      child: Text(
                        footerText,
                        textAlign: TextAlign.center,
                        style: TText.small.copyWith(color: p.muted),
                      ),
                    ),
                  ],
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
  const _ButtonBase({required this.label, required this.onPressed, required this.filled, this.icon});

  final String label;
  final VoidCallback? onPressed;
  final bool filled;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final enabled = onPressed != null;
    final fg = filled ? p.paper : (enabled ? p.ink : p.muted);
    final bg = filled ? (enabled ? p.ink : p.muted) : p.paper;
    return Semantics(
      button: true,
      enabled: enabled,
      child: Material(
        color: bg,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(TRadius.control),
          side: filled ? BorderSide.none : BorderSide(color: enabled ? p.controlLine : p.line),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onPressed,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: TSize.touch),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: TSpace.x4, vertical: TSpace.x2),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Flexible(
                    child: Text(label, textAlign: TextAlign.center, style: TText.bodyStrong.copyWith(color: fg)),
                  ),
                  if (icon != null) ...[
                    const SizedBox(width: TSpace.x2),
                    Icon(icon, size: 18, color: fg),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 기본 버튼: 화면에서 가장 중요한 동작 하나. 본문색 바탕. 상태 색을 쓰지 않는다.
class PrimaryButton extends StatelessWidget {
  const PrimaryButton({super.key, required this.label, required this.onPressed, this.icon});

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => _ButtonBase(label: label, onPressed: onPressed, filled: true, icon: icon);
}

/// 보조 버튼: 테두리가 있는 밝은 버튼.
class SecondaryButton extends StatelessWidget {
  const SecondaryButton({super.key, required this.label, required this.onPressed, this.icon});

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => _ButtonBase(label: label, onPressed: onPressed, filled: false, icon: icon);
}

/// 글자 버튼: 밑줄 있는 글자. 터치 영역은 48을 지킨다.
class TextLinkButton extends StatelessWidget {
  const TextLinkButton({super.key, required this.label, required this.onPressed, this.leading, this.trailing});

  final String label;
  final VoidCallback? onPressed;
  final IconData? leading;
  final IconData? trailing;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      button: true,
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(TRadius.control),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: TSize.touch, minWidth: TSize.touch),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: TSpace.x1),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (leading != null) ...[Icon(leading, size: 18, color: p.ink), const SizedBox(width: TSpace.x2)],
                Flexible(
                  child: Text(
                    label,
                    style: TText.label.copyWith(color: p.ink, decoration: TextDecoration.underline),
                  ),
                ),
                if (trailing != null) ...[const SizedBox(width: TSpace.x2), Icon(trailing, size: 18, color: p.ink)],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 상태 라벨: 옅은 바탕 + 아이콘 + 글자.
class StatusLabel extends StatelessWidget {
  const StatusLabel({super.key, required this.text, required this.tone, this.icon});

  final String text;
  final StatusTone tone;
  final IconData? icon;

  static const _icons = {
    StatusTone.suspicious: Icons.error_outline,
    StatusTone.warning: Icons.remove_circle_outline,
    StatusTone.low: Icons.radio_button_unchecked,
    StatusTone.muted: Icons.more_horiz,
  };

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final fg = tone.fg(p);
    return Align(
      alignment: AlignmentDirectional.centerStart,
      child: Container(
        decoration: BoxDecoration(color: tone.bg(p), borderRadius: BorderRadius.circular(TRadius.chip)),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            ExcludeSemantics(child: Icon(icon ?? _icons[tone], size: 16, color: fg)),
            const SizedBox(width: TSpace.x2),
            Flexible(child: Text(text, style: TText.label.copyWith(color: fg))),
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
    final p = context.palette;
    final current = state == StageState.current;
    final color = state == StageState.pending ? p.muted : p.ink;
    final icon = switch (state) {
      StageState.done => Icons.check,
      StageState.current => Icons.radio_button_checked,
      StageState.pending => Icons.radio_button_unchecked,
    };
    return Semantics(
      container: true,
      label: '$label, ${stateText[state]}',
      child: ExcludeSemantics(
        child: Container(
          constraints: const BoxConstraints(minHeight: TSize.touch),
          decoration: BoxDecoration(
            color: current ? p.soft : null,
            borderRadius: current ? BorderRadius.circular(TRadius.control) : null,
            border: current ? null : Border(bottom: BorderSide(color: p.line)),
          ),
          padding: const EdgeInsets.symmetric(horizontal: TSpace.x2, vertical: TSpace.x2),
          child: Row(
            children: [
              Icon(icon, size: 18, color: color),
              const SizedBox(width: TSpace.x3),
              Expanded(child: Text(label, style: (current ? TText.bodyStrong : TText.body).copyWith(color: color))),
              const SizedBox(width: TSpace.x2),
              Text(stateText[state]!, style: TText.small.copyWith(color: color)),
            ],
          ),
        ),
      ),
    );
  }
}

/// 흰 카드.
class Panel extends StatelessWidget {
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(TSpace.x4)});

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(
        color: p.paper,
        border: Border.all(color: p.line),
        borderRadius: BorderRadius.circular(TRadius.panel),
      ),
      padding: padding,
      child: child,
    );
  }
}

/// 분석 범위 카드. 영상 전체 길이 위에 분석한 구간을 표시한다.
/// 분석한 양이며 정확도나 신뢰도가 아니다. 그 문구를 항상 함께 둔다.
class CoverageBar extends StatelessWidget {
  const CoverageBar({
    super.key,
    required this.videoDurationSec,
    required this.segments,
    required this.caption,
    this.endLabel,
  });

  final double? videoDurationSec;

  /// (시작 초, 끝 초)
  final List<(double, double)> segments;
  final String caption;

  /// 막대 오른쪽 끝의 시각(영상 길이). 모르면 null.
  final String? endLabel;

  static const title = '어디까지 살펴봤나요?';
  static const disclaimer = '분석한 양이며, 정확도나 신뢰도가 아닙니다.';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final total = videoDurationSec;
    final known = total != null && total > 0;
    return Semantics(
      container: true,
      label: '분석 범위. $caption $disclaimer',
      child: ExcludeSemantics(
        child: Panel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(title, style: TText.h3.copyWith(color: p.ink)),
              const SizedBox(height: TSpace.x3),
              if (known) ...[
                ClipRRect(
                  borderRadius: BorderRadius.circular(TRadius.bar),
                  child: Container(
                    height: 16,
                    color: p.soft,
                    child: LayoutBuilder(
                      builder: (context, box) => Stack(
                        children: [
                          for (final (start, end) in segments)
                            Positioned(
                              left: box.maxWidth * (start / total).clamp(0.0, 1.0),
                              width: box.maxWidth * ((end - start) / total).clamp(0.0, 1.0),
                              top: 0,
                              bottom: 0,
                              child: ColoredBox(key: const ValueKey('coverage-segment'), color: p.ink),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
                if (endLabel != null)
                  Padding(
                    padding: const EdgeInsets.only(top: TSpace.x1),
                    child: Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      children: [
                        Text('0:00', style: TText.small.copyWith(color: p.muted)),
                        Text(endLabel!, style: TText.small.copyWith(color: p.muted)),
                      ],
                    ),
                  ),
                const SizedBox(height: TSpace.x2),
                Text(caption, style: TText.body.copyWith(color: p.ink)),
              ] else
                Container(
                  decoration: BoxDecoration(color: p.bg, borderRadius: BorderRadius.circular(TRadius.chip)),
                  padding: const EdgeInsets.all(TSpace.x3),
                  child: Text(caption, style: TText.body.copyWith(color: p.muted)),
                ),
              const SizedBox(height: TSpace.x2),
              Text(disclaimer, style: TText.small.copyWith(color: p.muted)),
            ],
          ),
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
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(border: Border(top: BorderSide(color: p.line))),
      padding: const EdgeInsets.symmetric(vertical: TSpace.x4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: TText.h3.copyWith(color: p.ink)),
          const SizedBox(height: TSpace.x1),
          Text(description, style: TText.secondary.copyWith(color: p.muted)),
          Text(statusText, style: TText.secondary.copyWith(color: p.muted)),
          for (final (name, value) in metrics) ...[
            const SizedBox(height: TSpace.x3),
            Text(name, style: TText.small.copyWith(color: p.muted)),
            // 숫자는 고정폭, 글자("값 없음" 등)는 본문 글꼴
            Text(
              value,
              style: (RegExp(r'^[-\d]').hasMatch(value) ? TText.mono : TText.body)
                  .copyWith(fontSize: TFont.title, fontWeight: FontWeight.w700, color: p.ink),
            ),
          ],
          if (note != null) ...[
            const SizedBox(height: TSpace.x2),
            Text(note!, style: TText.secondary.copyWith(color: p.muted)),
          ],
        ],
      ),
    );
  }
}

/// 안내 박스. 색조의 옅은 바탕 위에 본문색 글자. 제목만 색조의 색이다.
class InfoBox extends StatelessWidget {
  const InfoBox({super.key, this.title, required this.body, this.tone = StatusTone.muted});

  final String? title;
  final String body;
  final StatusTone tone;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(color: tone.bg(p), borderRadius: BorderRadius.circular(TRadius.panel)),
      padding: const EdgeInsets.all(TSpace.x3 + TSpace.x1),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (title != null) ...[
            Text(title!, style: TText.label.copyWith(color: tone == StatusTone.muted ? p.ink : tone.fg(p))),
            const SizedBox(height: TSpace.x1),
          ],
          Text(body, style: TText.body.copyWith(color: p.ink)),
        ],
      ),
    );
  }
}

/// 작은 영문 머리글.
class Overline extends StatelessWidget {
  const Overline(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) =>
      ExcludeSemantics(child: Text(text, style: TText.overline.copyWith(color: context.palette.muted)));
}

/// 구역 제목.
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: TSpace.x5, bottom: TSpace.x2),
      child: Semantics(header: true, child: Text(text, style: TText.title.copyWith(color: context.palette.ink))),
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
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: TSpace.x2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(name, style: TText.small.copyWith(color: p.muted)),
          Text(value, style: (mono ? TText.mono : TText.body).copyWith(color: p.ink)),
        ],
      ),
    );
  }
}

/// 접었다 펴는 구역. 제목 줄을 누르면 내용이 보인다.
class Disclosure extends StatefulWidget {
  const Disclosure({super.key, required this.title, required this.child, this.centered = false});

  final String title;
  final Widget child;
  final bool centered;

  @override
  State<Disclosure> createState() => _DisclosureState();
}

class _DisclosureState extends State<Disclosure> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: widget.centered ? Alignment.center : AlignmentDirectional.centerStart,
          child: Semantics(
            button: true,
            expanded: _open,
            child: InkWell(
              onTap: () => setState(() => _open = !_open),
              borderRadius: BorderRadius.circular(TRadius.control),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: TSize.touch),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: TSpace.x2),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(_open ? Icons.expand_less : Icons.expand_more, size: 18, color: p.muted),
                      const SizedBox(width: TSpace.x1),
                      Flexible(child: Text(widget.title, style: TText.label.copyWith(color: p.muted))),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
        if (_open) Padding(padding: const EdgeInsets.only(top: TSpace.x2), child: widget.child),
      ],
    );
  }
}
