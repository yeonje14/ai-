import 'package:flutter/material.dart';

import 'tokens.dart';

/// 어두운 단일 테마. 모서리 반경은 모두 0이다.
ThemeData buildTrinityTheme() {
  const scheme = ColorScheme.dark(
    surface: TColors.background,
    onSurface: TColors.text,
    primary: TColors.text,
    onPrimary: TColors.background,
    secondary: TColors.neutral,
    onSecondary: TColors.background,
    error: TColors.accent,
    onError: TColors.background,
    outline: TColors.border,
  );
  const square = RoundedRectangleBorder(borderRadius: BorderRadius.zero);
  OutlineInputBorder inputBorder(Color c, [double w = 1]) => OutlineInputBorder(
        borderRadius: BorderRadius.zero,
        borderSide: BorderSide(color: c, width: w),
      );
  return ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: scheme,
    scaffoldBackgroundColor: TColors.background,
    fontFamily: TFont.sans,
    fontFamilyFallback: TFont.fallback,
    splashFactory: NoSplash.splashFactory,
    textTheme: TextTheme(
      bodyLarge: TText.body,
      bodyMedium: TText.body,
      bodySmall: TText.secondary,
      titleLarge: TText.title,
      headlineSmall: TText.display,
      labelLarge: TText.bodyStrong,
    ),
    dividerTheme: const DividerThemeData(color: TColors.border, thickness: 1, space: 1),
    cardTheme: const CardThemeData(shape: square, color: TColors.surface, elevation: 0),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: TColors.surface,
      contentPadding: const EdgeInsets.all(TSpace.x3),
      labelStyle: TText.secondary,
      hintStyle: TText.body.copyWith(color: TColors.textSecondary),
      errorStyle: TText.secondary.copyWith(color: TColors.text),
      errorMaxLines: 6,
      // 입력란은 조작 가능한 요소라 테두리를 본문 보조색(대비 3:1 이상)으로 둔다
      enabledBorder: inputBorder(TColors.textSecondary),
      focusedBorder: inputBorder(TColors.text, 2),
      errorBorder: inputBorder(TColors.warning),
      focusedErrorBorder: inputBorder(TColors.warning, 2),
      border: inputBorder(TColors.textSecondary),
    ),
  );
}
