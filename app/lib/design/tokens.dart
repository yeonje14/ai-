/// 디자인 토큰. 정의와 변경 이유는 docs/design-system.md.
library;

import 'package:flutter/material.dart';

/// 역할 이름으로 부르는 색. 밝은 테마가 기본이고 어두운 테마는 시스템 설정을 따른다.
@immutable
class TPalette extends ThemeExtension<TPalette> {
  const TPalette({
    required this.brightness,
    required this.bg,
    required this.paper,
    required this.soft,
    required this.line,
    required this.controlLine,
    required this.ink,
    required this.muted,
    required this.suspicious,
    required this.suspiciousBg,
    required this.warning,
    required this.warningBg,
    required this.low,
    required this.lowBg,
  });

  final Brightness brightness;

  /// 화면 배경.
  final Color bg;

  /// 카드·입력란 바탕. 기본 버튼의 글자색이기도 하다.
  final Color paper;

  /// 옅은 면(고지 띠, 현재 단계, 범위 막대의 바탕).
  final Color soft;

  /// 장식용 구분선·카드 테두리. 대비가 낮아 조작 요소에는 쓰지 않는다.
  final Color line;

  /// 조작 요소(입력란, 보조 버튼)의 테두리. 배경 대비 3:1 이상.
  final Color controlLine;

  /// 본문 글자, 기본 버튼의 바탕.
  final Color ink;

  /// 보조 글자.
  final Color muted;

  /// "의심 신호 발견"에만 쓴다.
  final Color suspicious;
  final Color suspiciousBg;

  /// "판단 보류", "영상 접근 불가", 작업 실패.
  final Color warning;
  final Color warningBg;

  /// "의심 신호 낮음". 완전한 무채색이다. 초록을 쓰지 않는다(안전·진짜로 읽힌다).
  final Color low;
  final Color lowBg;

  static const light = TPalette(
    brightness: Brightness.light,
    bg: Color(0xFFF5F5F0),
    paper: Color(0xFFFFFFFF),
    soft: Color(0xFFE9ECE4),
    line: Color(0xFFD7DBD2),
    controlLine: Color(0xFF7C857C),
    ink: Color(0xFF202923),
    muted: Color(0xFF626A63),
    // 기존 #FF3D00(흰 배경 3.55:1)과 #FACC15(1.53:1)는 밝은 배경에서 글자로 읽을 수 없어 진한 색을 따로 둔다
    suspicious: Color(0xFFB63A13),
    suspiciousBg: Color(0xFFFFF0E9),
    warning: Color(0xFF805B05),
    warningBg: Color(0xFFFBF0CD),
    low: Color(0xFF2B2B2B),
    lowBg: Color(0xFFE8E8E8),
  );

  static const dark = TPalette(
    brightness: Brightness.dark,
    bg: Color(0xFF171918),
    paper: Color(0xFF222523),
    soft: Color(0xFF303831),
    line: Color(0xFF414942),
    controlLine: Color(0xFF829083),
    ink: Color(0xFFEEF0E9),
    muted: Color(0xFFAAB3AA),
    suspicious: Color(0xFFFF9671),
    suspiciousBg: Color(0xFF422920),
    warning: Color(0xFFF4D26D),
    warningBg: Color(0xFF3B3422),
    low: Color(0xFFE6E6E6),
    lowBg: Color(0xFF333333),
  );

  static const all = [light, dark];

  @override
  TPalette copyWith() => this;

  @override
  TPalette lerp(TPalette? other, double t) => t < 0.5 ? this : (other ?? this);
}

extension TPaletteContext on BuildContext {
  TPalette get palette => Theme.of(this).extension<TPalette>() ?? TPalette.light;
}

/// 상태의 색조. 색만으로 뜻을 전하지 않는다. 항상 글자 라벨이 함께 있다.
enum StatusTone {
  suspicious,
  warning,
  low,
  muted;

  /// 글자·아이콘 색.
  Color fg(TPalette p) => switch (this) {
        StatusTone.suspicious => p.suspicious,
        StatusTone.warning => p.warning,
        StatusTone.low => p.low,
        StatusTone.muted => p.muted,
      };

  /// 라벨·안내 박스의 바탕색.
  Color bg(TPalette p) => switch (this) {
        StatusTone.suspicious => p.suspiciousBg,
        StatusTone.warning => p.warningBg,
        StatusTone.low => p.lowBg,
        StatusTone.muted => p.soft,
      };
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

/// 모서리 반경. 기존의 0에서 바꿨다(docs/design-system.md "변경 기록").
abstract final class TRadius {
  static const double panel = 14;
  static const double control = 8;
  static const double chip = 6;
  static const double bar = 4;

  /// 웹 홈의 캡슐형 주소 입력창.
  static const double pill = 32;
}

abstract final class TSize {
  /// 최소 터치 영역.
  static const double touch = 48;

  /// 본문 최대 너비.
  static const double contentMax = 760;

  /// 웹 홈의 입력창 너비.
  static const double searchMax = 680;

  /// 이 너비 이하에서는 앱(세로형) 배치를 쓴다.
  static const double appLayoutMax = 768;
}

abstract final class TFont {
  static const sans = 'InterTight';
  static const mono = 'JetBrainsMono';
  static const korean = 'NotoSansKR';
  static const fallback = <String>[korean];

  static const double body = 16;
  static const double secondary = 14;
  static const double small = 13;
  static const double h3 = 17;
  static const double title = 20;
  static const double display = 30;
  static const double lineHeight = 1.5;
}

/// 글자 스타일. 색은 넣지 않는다(테마의 기본 글자색을 따르고, 필요한 곳에서 팔레트 색을 준다).
abstract final class TText {
  static const body = TextStyle(
    fontFamily: TFont.sans,
    fontFamilyFallback: TFont.fallback,
    fontSize: TFont.body,
    height: TFont.lineHeight,
    fontWeight: FontWeight.w400,
  );
  static final bodyStrong = body.copyWith(fontWeight: FontWeight.w700);
  static final secondary = body.copyWith(fontSize: TFont.secondary);
  static final small = body.copyWith(fontSize: TFont.small);
  static final label = body.copyWith(fontSize: TFont.secondary, fontWeight: FontWeight.w700);
  static final overline = body.copyWith(fontSize: TFont.small, fontWeight: FontWeight.w700, letterSpacing: 1.1);
  static final h3 = body.copyWith(fontSize: TFont.h3, fontWeight: FontWeight.w700, height: 1.45);
  static final title = body.copyWith(fontSize: TFont.title, fontWeight: FontWeight.w700, height: 1.4);
  static final display =
      body.copyWith(fontSize: TFont.display, fontWeight: FontWeight.w700, height: 1.4, letterSpacing: -0.6);
  static const mono = TextStyle(
    fontFamily: TFont.mono,
    fontFamilyFallback: TFont.fallback,
    fontSize: TFont.body,
    height: TFont.lineHeight,
    fontWeight: FontWeight.w400,
  );
}

/// WCAG 2.x 대비 비율. 테스트와 문서의 수치 확인에 쓴다.
double contrastRatio(Color a, Color b) {
  final la = a.computeLuminance(), lb = b.computeLuminance();
  final hi = la > lb ? la : lb, lo = la > lb ? lb : la;
  return (hi + 0.05) / (lo + 0.05);
}
