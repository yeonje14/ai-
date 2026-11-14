import 'package:flutter/material.dart';

import 'tokens.dart';

/// 밝은 테마가 기본이다. 어두운 테마는 시스템 설정이 어두울 때 쓴다.
ThemeData buildTrinityTheme([Brightness brightness = Brightness.light]) {
  final p = brightness == Brightness.dark ? TPalette.dark : TPalette.light;
  final scheme = ColorScheme(
    brightness: brightness,
    surface: p.bg,
    onSurface: p.ink,
    primary: p.ink,
    onPrimary: p.paper,
    secondary: p.muted,
    onSecondary: p.paper,
    error: p.warning,
    onError: p.paper,
    outline: p.controlLine,
    outlineVariant: p.line,
  );
  OutlineInputBorder inputBorder(Color c, [double w = 1]) => OutlineInputBorder(
        borderRadius: BorderRadius.circular(TRadius.control),
        borderSide: BorderSide(color: c, width: w),
      );
  final body = TText.body.copyWith(color: p.ink);
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    extensions: [p],
    scaffoldBackgroundColor: p.bg,
    fontFamily: TFont.sans,
    fontFamilyFallback: TFont.fallback,
    splashFactory: NoSplash.splashFactory,
    iconTheme: IconThemeData(color: p.ink, size: 20),
    textTheme: TextTheme(
      bodyLarge: body,
      bodyMedium: body,
      bodySmall: TText.secondary.copyWith(color: p.muted),
      titleLarge: TText.title.copyWith(color: p.ink),
      headlineSmall: TText.display.copyWith(color: p.ink),
      labelLarge: TText.bodyStrong.copyWith(color: p.ink),
    ),
    dividerTheme: DividerThemeData(color: p.line, thickness: 1, space: 1),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.paper,
      contentPadding: const EdgeInsets.symmetric(horizontal: TSpace.x3, vertical: TSpace.x3),
      hintStyle: body.copyWith(color: p.muted),
      errorStyle: TText.secondary.copyWith(color: p.warning),
      errorMaxLines: 6,
      prefixIconColor: p.muted,
      enabledBorder: inputBorder(p.controlLine),
      focusedBorder: inputBorder(p.ink, 2),
      disabledBorder: inputBorder(p.line),
      errorBorder: inputBorder(p.warning),
      focusedErrorBorder: inputBorder(p.warning, 2),
      border: inputBorder(p.controlLine),
    ),
  );
}
