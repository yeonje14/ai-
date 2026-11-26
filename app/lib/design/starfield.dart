import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'tokens.dart';

/// 앱을 열어 둔 동안의 설정. OS의 움직임 줄이기가 켜져 있으면 항상 우선한다.
class MotionPreferences extends StatefulWidget {
  const MotionPreferences({super.key, required this.child});
  final Widget child;

  @override
  State<MotionPreferences> createState() => _MotionPreferencesState();
}

class _MotionPreferencesState extends State<MotionPreferences> {
  bool _reduce = false;

  @override
  Widget build(BuildContext context) => MediaQuery(
    data: MediaQuery.of(context).copyWith(disableAnimations: _reduce || MediaQuery.disableAnimationsOf(context)),
    child: _MotionControl(
      change: MediaQuery.disableAnimationsOf(context) ? null : (value) => setState(() => _reduce = value),
      child: widget.child,
    ),
  );
}

class _MotionControl extends InheritedWidget {
  const _MotionControl({required this.change, required super.child});
  final ValueChanged<bool>? change;

  @override
  bool updateShouldNotify(_MotionControl oldWidget) => change != oldWidget.change;
}

class MotionToggle extends StatelessWidget {
  const MotionToggle({super.key});

  @override
  Widget build(BuildContext context) {
    final control = context.dependOnInheritedWidgetOfExactType<_MotionControl>();
    if (control == null) return const SizedBox.shrink();
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 310, minHeight: TSize.touch),
      child: SwitchListTile(
        title: Text('움직임 줄이기', style: TText.label.copyWith(color: context.palette.ink)),
        value: MediaQuery.disableAnimationsOf(context),
        onChanged: control.change,
      ),
    );
  }
}

/// 별은 고정 시드로 그린다. 스크롤만 조명을 바꾸므로 정지 화면에서 프레임을 소비하지 않는다.
class StarfieldBackground extends StatefulWidget {
  const StarfieldBackground({super.key, required this.child});
  final Widget child;

  @override
  State<StarfieldBackground> createState() => _StarfieldBackgroundState();
}

class _StarfieldBackgroundState extends State<StarfieldBackground> {
  final _scroll = ValueNotifier<double>(0);

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final reduced = MediaQuery.disableAnimationsOf(context);
    return Stack(fit: StackFit.expand, children: [
      ExcludeSemantics(child: RepaintBoundary(child: ValueListenableBuilder<double>(
        valueListenable: _scroll,
        builder: (context, offset, _) => CustomPaint(painter: _StarfieldPainter(reduced ? 1 : offset)),
      ))),
      NotificationListener<ScrollUpdateNotification>(
        onNotification: (event) {
          if (!reduced && event.depth == 0 && event.metrics.axis == Axis.vertical) {
            _scroll.value = (event.metrics.pixels / 500).clamp(0.0, 1.0);
          }
          return false;
        },
        child: widget.child,
      ),
    ]);
  }
}

class _StarfieldPainter extends CustomPainter {
  const _StarfieldPainter(this.reveal);
  final double reveal;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    canvas.drawRect(rect, Paint()..color = TPalette.dark.bg);
    final center = Offset(size.width * 0.68, size.height * 0.44);
    final glow = RadialGradient(colors: [TPalette.dark.bg2, TPalette.dark.bg]);
    canvas.drawRect(rect, Paint()..shader = glow.createShader(Rect.fromCircle(
      center: center, radius: size.longestSide * (0.47 + reveal * 0.32),
    )));
    final random = math.Random(271);
    final count = (size.width * size.height / 4200).round();
    final paint = Paint();
    for (var i = 0; i < count; i++) {
      final position = Offset(random.nextDouble() * size.width, random.nextDouble() * size.height);
      paint.color = Colors.white.withValues(alpha: 0.25 + random.nextDouble() * 0.35);
      canvas.drawCircle(position, 0.5 + random.nextDouble(), paint);
    }
  }

  @override
  bool shouldRepaint(_StarfieldPainter oldDelegate) => reveal != oldDelegate.reveal;
}
