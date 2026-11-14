/// 디자인 토큰. 정의와 근거는 docs/design-system.md.
library;

import 'package:flutter/painting.dart';

abstract final class TColors {
  static const background = Color(0xFF0A0A0A);
  static const surface = Color(0xFF141414);
  static const border = Color(0xFF2A2A2A);
  static const text = Color(0xFFFAFAFA);
  static const textSecondary = Color(0xFF9A9A9A);

  /// 강조: "의심 신호 발견"에만 쓴다. 버튼이나 장식에 쓰지 않는다.
  static const accent = Color(0xFFFF3D00);

  /// 경고: "판단 보류".
  static const warning = Color(0xFFFACC15);

  /// 중립: "의심 신호 낮음". 초록을 쓰지 않는다(안전·진짜로 읽힌다).
  static const neutral = Color(0xFFD4D4D4);
}

/// 8pt 그리드.
abstract final class TSpace {
  static const double x1 = 4;
  static const double x2 = 8;
  static const double x3 = 16;
  static const double x4 = 24;
  static const double x5 = 32;

  /// 화면 좌우 여백.
  static const double screen = 20;
}

abstract final class TSize {
  /// 최소 터치 영역.
  static const double touch = 48;

  /// 넓은 화면(웹)에서 본문 최대 너비.
  static const double contentMax = 560;
}

abstract final class TFont {
  static const sans = 'InterTight';
  static const mono = 'JetBrainsMono';
  static const korean = 'NotoSansKR';
  static const fallback = <String>[korean];

  static const double body = 16;
  static const double secondary = 13;
  static const double title = 20;
  static const double display = 26;
  static const double lineHeight = 1.5;
}

abstract final class TText {
  static const body = TextStyle(
    fontFamily: TFont.sans,
    fontFamilyFallback: TFont.fallback,
    fontSize: TFont.body,
    height: TFont.lineHeight,
    fontWeight: FontWeight.w400,
    color: TColors.text,
  );
  static final bodyStrong = body.copyWith(fontWeight: FontWeight.w700);
  static final secondary = body.copyWith(fontSize: TFont.secondary, color: TColors.textSecondary);
  static final label = body.copyWith(fontSize: TFont.secondary, fontWeight: FontWeight.w700);
  static final title = body.copyWith(fontSize: TFont.title, fontWeight: FontWeight.w700, height: 1.4);
  static final display = body.copyWith(fontSize: TFont.display, fontWeight: FontWeight.w700, height: 1.35);
  static const mono = TextStyle(
    fontFamily: TFont.mono,
    fontFamilyFallback: TFont.fallback,
    fontSize: TFont.secondary,
    height: TFont.lineHeight,
    fontWeight: FontWeight.w400,
    color: TColors.text,
  );
}

/// WCAG 2.x 대비 비율. 테스트와 문서의 수치 확인에 쓴다.
double contrastRatio(Color a, Color b) {
  final la = a.computeLuminance(), lb = b.computeLuminance();
  final hi = la > lb ? la : lb, lo = la > lb ? lb : la;
  return (hi + 0.05) / (lo + 0.05);
}
