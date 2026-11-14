import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/api/models.dart';
import 'package:trinity_app/design/theme.dart';

/// 작은 휴대폰 화면(360×640)에 화면 하나를 띄운다. [scale]은 시스템 글자 크기 배율이다.
Future<void> pumpScreen(WidgetTester tester, Widget screen, {double scale = 1.0, Size size = const Size(360, 640)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTrinityTheme(),
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
      child: child!,
    ),
    home: screen,
  ));
}

AnalysisResult mockResult(MockScenario s) => AnalysisResult.fromJson(mockResultJson(s, 'mock-1'));

/// 화면에 보이는 모든 글자.
List<String> allText(WidgetTester tester) => [
      for (final t in tester.widgetList<Text>(find.byType(Text))) t.data ?? t.textSpan?.toPlainText() ?? '',
    ];

Color? colorOfText(WidgetTester tester, String text) => tester.widget<Text>(find.text(text)).style?.color;
