import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/api/models.dart';
import 'package:trinity_app/design/theme.dart';

const phone = Size(360, 640);
const desktop = Size(1280, 800);

/// 화면 하나를 띄운다. 기본은 작은 휴대폰(360×640), 밝은 테마. [scale]은 시스템 글자 크기 배율이다.
Future<void> pumpScreen(
  WidgetTester tester,
  Widget screen, {
  double scale = 1.0,
  Size size = phone,
  Brightness brightness = Brightness.light,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: buildTrinityTheme(brightness),
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
      child: child!,
    ),
    home: screen,
  ));
}

AnalysisResult mockResult(MockScenario s) => AnalysisResult.fromJson(mockResultJson(s, 'mock-1'));

/// 화면에 있는 모든 글자(스크롤 밖 포함).
List<String> allText(WidgetTester tester) => [
      for (final t in tester.widgetList<Text>(find.byType(Text, skipOffstage: false)))
        t.data ?? t.textSpan?.toPlainText() ?? '',
    ];

Color? colorOfText(WidgetTester tester, String text) =>
    tester.widget<Text>(find.text(text, skipOffstage: false)).style?.color;

bool isAchromatic(Color c) => c.r == c.g && c.g == c.b;
