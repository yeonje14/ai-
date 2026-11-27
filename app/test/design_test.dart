import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/design/theme.dart';
import 'package:trinity_app/design/tokens.dart';
import 'package:trinity_app/design/widgets.dart';

import 'helpers.dart';

void main() {
  test('시스템 밝기와 관계없이 별빛 배경과 유리 카드에서 글자를 읽을 수 있다', () {
    const p = TPalette.dark;
    for (final brightness in Brightness.values) {
      expect(buildTrinityTheme(brightness).brightness, Brightness.dark);
    }
    expect(p.bg, const Color(0xFF070A1A));
    for (final background in [p.bg, p.bg2, p.paper]) {
      for (final foreground in [p.ink, p.muted, p.accent, p.warning, p.suspicious, p.low]) {
        expect(contrastRatio(foreground, background), greaterThanOrEqualTo(4.5));
      }
      expect(contrastRatio(p.controlLine, background), greaterThanOrEqualTo(3));
    }
    expect(contrastRatio(Colors.white, p.primary), greaterThanOrEqualTo(4.5));
    for (final tone in StatusTone.values) {
      expect(contrastRatio(tone.fg(p), tone.bg(p)), greaterThanOrEqualTo(4.5));
    }
    expect(TText.body.fontSize, 18);
    expect(TText.secondary.fontSize, 18);
    expect(TText.small.fontSize, 16);
    expect(TSize.touch, 56);
  });

  testWidgets('버튼의 터치 영역은 48 이상이고 눌린다', (tester) async {
    var taps = 0;
    await pumpScreen(
      tester,
      TrinityScaffold(children: [
        PrimaryButton(label: '기본', onPressed: () => taps++),
        SecondaryButton(label: '보조', onPressed: () => taps++),
        TextLinkButton(label: '글자', onPressed: () => taps++),
        const PrimaryButton(label: '꺼짐', onPressed: null),
      ]),
    );
    for (final label in ['기본', '보조', '글자', '꺼짐']) {
      final box = tester.getSize(find.ancestor(of: find.text(label), matching: find.byType(InkWell)));
      expect(box.height, greaterThanOrEqualTo(56), reason: label);
    }
    for (final label in ['기본', '보조', '글자', '꺼짐']) {
      await tester.tap(find.text(label));
    }
    expect(taps, 3);
  });

  testWidgets('기본 버튼은 본문색 바탕이고 상태 색을 쓰지 않는다', (tester) async {
    await pumpScreen(tester, TrinityScaffold(children: [PrimaryButton(label: '기본', onPressed: () {})]));
    final material = tester.widget<Material>(
        find.ancestor(of: find.text('기본'), matching: find.byType(Material)).first);
    expect(material.color, TPalette.dark.primary);
    expect(colorOfText(tester, '기본'), Colors.white);
    expect((material.shape as RoundedRectangleBorder).borderRadius, BorderRadius.circular(TRadius.pill));
  });

  for (final p in TPalette.all) {
    testWidgets('${p.brightness.name}: 상태 라벨은 색조의 글자색과 바탕색을 쓴다', (tester) async {
      await pumpScreen(
        tester,
        const TrinityScaffold(children: [
          StatusLabel(text: '의심 신호 발견', tone: StatusTone.suspicious),
          StatusLabel(text: '판단 보류', tone: StatusTone.warning),
          StatusLabel(text: '의심 신호 낮음', tone: StatusTone.low),
          StatusLabel(text: '분석 대상 아님', tone: StatusTone.muted),
        ]),
        brightness: p.brightness,
      );
      Color bgOf(String text) => (tester
              .widget<Container>(find.ancestor(of: find.text(text), matching: find.byType(Container)).first)
              .decoration as BoxDecoration)
          .color!;
      expect(colorOfText(tester, '의심 신호 발견'), p.suspicious);
      expect(bgOf('의심 신호 발견'), p.suspiciousBg);
      expect(colorOfText(tester, '판단 보류'), p.warning);
      expect(bgOf('판단 보류'), p.warningBg);
      expect(colorOfText(tester, '의심 신호 낮음'), p.low);
      expect(bgOf('의심 신호 낮음'), p.lowBg);
      expect(colorOfText(tester, '분석 대상 아님'), p.muted);
      expect(bgOf('분석 대상 아님'), p.soft);
    });
  }

  testWidgets('단계 행은 상태를 글자로 보여 주고 높이가 48 이상이다', (tester) async {
    await pumpScreen(
      tester,
      const TrinityScaffold(children: [
        StageRow(label: '주소 확인', state: StageState.done),
        StageRow(label: '영상 신호 확인', state: StageState.current),
        StageRow(label: '결과 정리', state: StageState.pending),
      ]),
    );
    expect(find.text('완료'), findsOneWidget);
    expect(find.text('진행 중'), findsOneWidget);
    expect(find.text('대기'), findsOneWidget);
    for (final row in tester.widgetList(find.byType(StageRow))) {
      expect(tester.getSize(find.byWidget(row)).height, greaterThanOrEqualTo(56));
    }
  });

  testWidgets('분석 범위 카드는 "정확도가 아님"을 함께 적고 구간을 그린다', (tester) async {
    await pumpScreen(
      tester,
      const TrinityScaffold(children: [
        CoverageBar(videoDurationSec: 60, segments: [(5.0, 25.0)], caption: '영상 1분 0초 가운데 20초를 분석했습니다.', endLabel: '1:00'),
      ]),
    );
    expect(find.text(CoverageBar.title), findsOneWidget);
    expect(find.text(CoverageBar.disclaimer), findsOneWidget);
    expect(find.text('1:00'), findsOneWidget);
    final filled = tester.getSize(find.byKey(const ValueKey('coverage-segment')));
    final whole = tester.getSize(find.byType(LayoutBuilder));
    expect(filled.width / whole.width, closeTo(20 / 60, 0.01));
  });

  testWidgets('길이를 모르면 구간을 그리지 않는다', (tester) async {
    await pumpScreen(
      tester,
      const TrinityScaffold(children: [
        CoverageBar(videoDurationSec: null, segments: [], caption: '분석한 구간이 기록되지 않았습니다.'),
      ]),
    );
    expect(find.byKey(const ValueKey('coverage-segment')), findsNothing);
    expect(find.text('분석한 구간이 기록되지 않았습니다.'), findsOneWidget);
    expect(find.text(CoverageBar.disclaimer), findsOneWidget);
  });

  testWidgets('고지 띠는 화면 맨 위에 있다', (tester) async {
    await pumpScreen(tester, const TrinityScaffold(children: []));
    expect(find.text('모델 미연결 · 가상 데이터'), findsOneWidget);
    expect(tester.getTopLeft(find.byType(NoticeBand)).dy, 0);
  });

  testWidgets('접는 구역은 누르면 펴진다', (tester) async {
    await pumpScreen(tester, const TrinityScaffold(children: [Disclosure(title: '더 보기', child: Text('숨은 내용'))]));
    expect(find.text('숨은 내용'), findsNothing);
    expect(tester.getSize(find.ancestor(of: find.text('더 보기'), matching: find.byType(InkWell))).height,
        greaterThanOrEqualTo(56));
    await tester.tap(find.text('더 보기'));
    await tester.pump();
    expect(find.text('숨은 내용'), findsOneWidget);
  });
}
