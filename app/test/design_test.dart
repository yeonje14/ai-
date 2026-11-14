import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/design/theme.dart';
import 'package:trinity_app/design/tokens.dart';
import 'package:trinity_app/design/widgets.dart';

import 'helpers.dart';

void main() {
  test('밝은 테마의 색 토큰이 정한 값과 같다', () {
    const p = TPalette.light;
    expect(p.bg, const Color(0xFFF5F5F0));
    expect(p.paper, const Color(0xFFFFFFFF));
    expect(p.ink, const Color(0xFF202923));
    expect(p.muted, const Color(0xFF626A63));
    expect(p.suspicious, const Color(0xFFB63A13));
    expect(p.warning, const Color(0xFF805B05));
    expect(p.low, const Color(0xFF2B2B2B));
    expect(p.lowBg, const Color(0xFFE8E8E8));
  });

  test('예전 다크용 상태 색은 흰 배경에서 4.5:1에 못 미친다(밝은 테마용 색을 따로 둔 이유)', () {
    const white = Color(0xFFFFFFFF);
    expect(contrastRatio(const Color(0xFFFF3D00), white), lessThan(4.5));
    expect(contrastRatio(const Color(0xFFFACC15), white), lessThan(4.5));
    expect(TPalette.light.suspicious, isNot(const Color(0xFFFF3D00)));
    expect(TPalette.light.warning, isNot(const Color(0xFFFACC15)));
  });

  for (final p in TPalette.all) {
    final name = p.brightness.name;

    test('$name: 상태 색은 글자·라벨로 놓이는 모든 배경에서 대비 4.5:1 이상이다', () {
      for (final tone in StatusTone.values) {
        // 라벨 바탕(색조별), 카드, 화면 배경
        for (final bg in [tone.bg(p), p.paper, p.bg]) {
          expect(contrastRatio(tone.fg(p), bg), greaterThanOrEqualTo(4.5),
              reason: '$name ${tone.name} ${tone.fg(p)} on $bg');
        }
      }
    });

    test('$name: 본문·보조 글자와 버튼 글자의 대비가 4.5:1 이상이다', () {
      // 본문색은 안내 박스의 옅은 바탕 위에도 놓인다
      for (final bg in [p.bg, p.paper, p.soft, p.suspiciousBg, p.warningBg, p.lowBg]) {
        expect(contrastRatio(p.ink, bg), greaterThanOrEqualTo(4.5), reason: '$name ink on $bg');
      }
      for (final bg in [p.bg, p.paper, p.soft]) {
        expect(contrastRatio(p.muted, bg), greaterThanOrEqualTo(4.5), reason: '$name muted on $bg');
      }
      expect(contrastRatio(p.paper, p.ink), greaterThanOrEqualTo(4.5), reason: '기본 버튼 글자');
      expect(contrastRatio(p.paper, p.muted), greaterThanOrEqualTo(4.5), reason: '꺼진 기본 버튼 글자');
    });

    test('$name: 조작 요소의 테두리는 3:1 이상이다', () {
      for (final bg in [p.bg, p.paper]) {
        expect(contrastRatio(p.controlLine, bg), greaterThanOrEqualTo(3.0), reason: '$name controlLine on $bg');
      }
    });

    test('$name: "의심 신호 낮음"은 완전한 무채색이고, 어떤 상태 색도 초록 계열이 아니다', () {
      expect(isAchromatic(p.low), isTrue);
      expect(isAchromatic(p.lowBg), isTrue);
      for (final c in [p.suspicious, p.suspiciousBg, p.warning, p.warningBg]) {
        expect(c.g > c.r && c.g > c.b, isFalse, reason: '$c');
      }
    });

    test('$name: 테마가 팔레트를 쓴다', () {
      final theme = buildTrinityTheme(p.brightness);
      expect(theme.extension<TPalette>(), same(p));
      expect(theme.scaffoldBackgroundColor, p.bg);
      expect(theme.brightness, p.brightness);
    });
  }

  test('기본 테마는 밝은 테마다', () {
    expect(buildTrinityTheme().brightness, Brightness.light);
  });

  test('글자 크기와 줄간격, 간격·반경 토큰', () {
    expect(TText.body.fontSize, 16);
    expect(TText.secondary.fontSize, greaterThanOrEqualTo(13));
    expect(TText.small.fontSize, greaterThanOrEqualTo(13));
    expect(TText.label.fontSize, greaterThanOrEqualTo(13));
    expect(TText.overline.fontSize, greaterThanOrEqualTo(13));
    expect(TText.body.height, 1.5);
    expect(TText.secondary.height, 1.5);
    expect(TText.small.height, 1.5);
    expect([TSpace.x1, TSpace.x2, TSpace.x3, TSpace.x4, TSpace.x5], [4, 8, 16, 24, 32]);
    expect(TSpace.screen, 20);
    expect([TRadius.panel, TRadius.control, TRadius.chip, TRadius.pill], [14, 8, 6, 32]);
    expect(TSize.appLayoutMax, 768);
    expect(TSize.searchMax, 680);
    expect(TText.body.fontFamily, 'InterTight');
    expect(TText.body.fontFamilyFallback, contains('NotoSansKR'));
    expect(TText.mono.fontFamily, 'JetBrainsMono');
    // 번들한 굵기(400, 700)만 쓴다
    for (final s in [TText.body, TText.bodyStrong, TText.secondary, TText.small, TText.label, TText.overline, TText.h3, TText.title, TText.display, TText.mono]) {
      expect([FontWeight.w400, FontWeight.w700], contains(s.fontWeight));
    }
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
      expect(box.height, greaterThanOrEqualTo(48), reason: label);
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
    expect(material.color, TPalette.light.ink);
    expect(colorOfText(tester, '기본'), TPalette.light.paper);
    expect((material.shape as RoundedRectangleBorder).borderRadius, BorderRadius.circular(8));
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
      expect(tester.getSize(find.byWidget(row)).height, greaterThanOrEqualTo(48));
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
        greaterThanOrEqualTo(48));
    await tester.tap(find.text('더 보기'));
    await tester.pump();
    expect(find.text('숨은 내용'), findsOneWidget);
  });
}
