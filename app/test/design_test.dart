import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/design/theme.dart';
import 'package:trinity_app/design/tokens.dart';
import 'package:trinity_app/design/widgets.dart';

import 'helpers.dart';

void main() {
  test('색 토큰이 정한 값과 같다', () {
    expect(TColors.background, const Color(0xFF0A0A0A));
    expect(TColors.surface, const Color(0xFF141414));
    expect(TColors.border, const Color(0xFF2A2A2A));
    expect(TColors.text, const Color(0xFFFAFAFA));
    expect(TColors.textSecondary, const Color(0xFF9A9A9A));
    expect(TColors.accent, const Color(0xFFFF3D00));
    expect(TColors.warning, const Color(0xFFFACC15));
    expect(TColors.neutral, const Color(0xFFD4D4D4));
  });

  test('"의심 신호 낮음" 색은 초록이 아니라 무채색이다', () {
    final c = TColors.neutral;
    expect(c.r, c.g);
    expect(c.g, c.b);
    for (final tone in StatusTone.values) {
      final t = tone.color;
      expect(t.g > t.r && t.g > t.b, isFalse, reason: '${tone.name}이 초록 계열이다');
    }
  });

  test('글자색은 배경과 표면 위에서 대비 4.5:1 이상이다', () {
    for (final fg in [TColors.text, TColors.textSecondary, TColors.accent, TColors.warning, TColors.neutral]) {
      for (final bg in [TColors.background, TColors.surface]) {
        expect(contrastRatio(fg, bg), greaterThanOrEqualTo(4.5), reason: '$fg on $bg');
      }
    }
    // 기본 버튼: 밝은 바탕 위 어두운 글자
    expect(contrastRatio(TColors.background, TColors.text), greaterThanOrEqualTo(4.5));
    // 조작 요소의 테두리(입력란·보조 버튼)는 3:1 이상
    expect(contrastRatio(TColors.textSecondary, TColors.background), greaterThanOrEqualTo(3.0));
  });

  test('글자 크기와 줄간격, 간격 토큰', () {
    expect(TText.body.fontSize, greaterThanOrEqualTo(16));
    expect(TText.secondary.fontSize, greaterThanOrEqualTo(13));
    expect(TText.label.fontSize, greaterThanOrEqualTo(13));
    expect(TText.mono.fontSize, greaterThanOrEqualTo(13));
    expect(TText.body.height, 1.5);
    expect(TText.secondary.height, 1.5);
    expect([TSpace.x1, TSpace.x2, TSpace.x3, TSpace.x4, TSpace.x5], [4, 8, 16, 24, 32]);
    expect(TSpace.screen, 20);
    expect(TText.body.fontFamily, 'InterTight');
    expect(TText.body.fontFamilyFallback, contains('NotoSansKR'));
    expect(TText.mono.fontFamily, 'JetBrainsMono');
  });

  test('테마의 모서리 반경은 0이다', () {
    final theme = buildTrinityTheme();
    expect((theme.cardTheme.shape as RoundedRectangleBorder).borderRadius, BorderRadius.zero);
    expect((theme.inputDecorationTheme.enabledBorder as OutlineInputBorder).borderRadius, BorderRadius.zero);
    expect(theme.scaffoldBackgroundColor, TColors.background);
  });

  testWidgets('버튼의 터치 영역은 48 이상이고 눌린다', (tester) async {
    var taps = 0;
    await pumpScreen(
      tester,
      TrinityScaffold(children: [
        PrimaryButton(label: '기본', onPressed: () => taps++),
        SecondaryButton(label: '보조', onPressed: () => taps++),
        const PrimaryButton(label: '꺼짐', onPressed: null),
      ]),
    );
    for (final label in ['기본', '보조', '꺼짐']) {
      final box = tester.getSize(find.ancestor(of: find.text(label), matching: find.byType(InkWell)));
      expect(box.height, greaterThanOrEqualTo(48), reason: label);
    }
    await tester.tap(find.text('기본'));
    await tester.tap(find.text('보조'));
    await tester.tap(find.text('꺼짐'));
    expect(taps, 2);
  });

  testWidgets('상태 라벨은 색조의 색으로 글자와 테두리를 그린다', (tester) async {
    await pumpScreen(
      tester,
      const TrinityScaffold(children: [
        StatusLabel(text: '의심 신호 발견', tone: StatusTone.accent),
        StatusLabel(text: '판단 보류', tone: StatusTone.warning),
        StatusLabel(text: '의심 신호 낮음', tone: StatusTone.neutral),
      ]),
    );
    expect(colorOfText(tester, '의심 신호 발견'), TColors.accent);
    expect(colorOfText(tester, '판단 보류'), TColors.warning);
    expect(colorOfText(tester, '의심 신호 낮음'), TColors.neutral);
  });

  testWidgets('단계 행은 상태를 글자로 보여 주고 높이가 48 이상이다', (tester) async {
    await pumpScreen(
      tester,
      const TrinityScaffold(children: [
        StageRow(label: '주소 확인', state: StageState.done),
        StageRow(label: '신호 분석', state: StageState.current),
        StageRow(label: '마무리', state: StageState.pending),
      ]),
    );
    expect(find.text('완료'), findsOneWidget);
    expect(find.text('진행 중'), findsOneWidget);
    expect(find.text('대기'), findsOneWidget);
    for (final row in tester.widgetList(find.byType(StageRow))) {
      expect(tester.getSize(find.byWidget(row)).height, greaterThanOrEqualTo(48));
    }
  });

  testWidgets('분석 범위 막대는 "정확도가 아님"을 함께 적고 구간을 그린다', (tester) async {
    await pumpScreen(
      tester,
      const TrinityScaffold(children: [
        CoverageBar(videoDurationSec: 60, segments: [(5.0, 25.0)], caption: '영상 1분 0초 가운데 20초를 분석했습니다.'),
      ]),
    );
    expect(find.text(CoverageBar.disclaimer), findsOneWidget);
    final filled = tester.getSize(find.byWidgetPredicate((w) => w is ColoredBox && w.color == TColors.text));
    final whole = tester.getSize(find.byType(LayoutBuilder));
    expect(filled.width / whole.width, closeTo(20 / 60, 0.01));
  });

  testWidgets('길이를 모르면 구간을 그리지 않는다', (tester) async {
    await pumpScreen(
      tester,
      const TrinityScaffold(children: [
        CoverageBar(videoDurationSec: null, segments: [], caption: '분석 범위 정보가 없습니다.'),
      ]),
    );
    expect(find.byWidgetPredicate((w) => w is ColoredBox && w.color == TColors.text), findsNothing);
    expect(find.text('분석 범위 정보가 없습니다.'), findsOneWidget);
  });

  testWidgets('고지 띠 문구', (tester) async {
    await pumpScreen(tester, const TrinityScaffold(children: []));
    expect(find.text('모델 미연결 · 가상 데이터'), findsOneWidget);
  });
}
