import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/api/models.dart';
import 'package:trinity_app/design/tokens.dart';
import 'package:trinity_app/design/widgets.dart';
import 'package:trinity_app/screens/detail_screen.dart';
import 'package:trinity_app/screens/guide_screen.dart';
import 'package:trinity_app/screens/input_screen.dart';
import 'package:trinity_app/screens/progress_screen.dart';
import 'package:trinity_app/screens/result_screen.dart';
import 'package:trinity_app/view_state.dart';

import 'helpers.dart';

const band = '모델 미연결 · 가상 데이터';
const light = TPalette.light;
void noop() {}

Widget result(ScreenKind kind, MockScenario s) =>
    ResultScreen(kind: kind, result: mockResult(s), onShowDetail: noop, onRestart: noop);

/// 모든 화면. 이름 → 위젯.
Map<String, Widget> screens() => {
      '홈(mock)': InputScreen(onSubmit: (_) {}, mockScenario: MockScenario.abstained, onMockScenarioChanged: (_) {}),
      '홈(오류)': InputScreen(onSubmit: (_) {}, errorText: 'YouTube 영상 주소가 아닙니다. youtube.com 또는 youtu.be 주소를 넣어 주세요.'),
      '분석 중': ProgressScreen(
        state: const JobState(jobStatus: JobStatus.processing, stage: 'waverep', completedStages: ['validating', 'access_check', 'preprocessing']),
        connectionLost: true,
        onRestart: noop,
      ),
      '의심 신호 발견': result(ScreenKind.suspicious, MockScenario.suspicious),
      '의심 신호 낮음': result(ScreenKind.low, MockScenario.low),
      '판단 보류': result(ScreenKind.abstained, MockScenario.abstained),
      '판단 근거 상세': DetailScreen(result: mockResult(MockScenario.abstained), onBack: noop),
      '판단 근거 상세(값 없음)': DetailScreen(result: mockResult(MockScenario.unavailable), onBack: noop),
      '영상 접근 불가': result(ScreenKind.unavailable, MockScenario.unavailable),
      '분석 대상 아님': result(ScreenKind.outOfScope, MockScenario.outOfScope),
      '작업 실패': ProgressScreen(
        state: const JobState(jobStatus: JobStatus.failed, completedStages: ['validating']),
        failureReasonCode: 'timeout',
        onRestart: noop,
      ),
      '이용 안내': GuideScreen(onStart: noop),
    };

Future<void> scrollToEnd(WidgetTester tester) async {
  await tester.drag(find.byType(SingleChildScrollView), const Offset(0, -8000));
  await tester.pump();
}

void main() {
  group('모든 화면', () {
    screens().forEach((name, bare) {
      // 실제 앱처럼 상단 메뉴(영상 확인 / 이용 안내)가 있는 상태로 본다
      final screen = TrinityNav(onHome: noop, onGuide: noop, child: bare);
      for (final size in [phone, desktop]) {
        testWidgets('$name ${size.width.toInt()}: 맨 위에 고지 띠가 있다', (tester) async {
          await pumpScreen(tester, screen, size: size);
          expect(find.text(band), findsOneWidget);
          expect(tester.getTopLeft(find.byType(NoticeBand)).dy, 0);
          expect(tester.takeException(), isNull);
        });
      }

      for (final scale in [1.3, 2.0]) {
        testWidgets('$name: 글자 크기 $scale배, 360×640에서 넘치지 않는다', (tester) async {
          await pumpScreen(tester, screen, scale: scale);
          expect(tester.takeException(), isNull);
          await scrollToEnd(tester);
          expect(tester.takeException(), isNull);
        });
      }

      testWidgets('$name: 320, 768, 769, 1280 너비와 어두운 테마에서 넘치지 않는다', (tester) async {
        await pumpScreen(tester, screen, scale: 2.0, size: const Size(320, 568));
        expect(tester.takeException(), isNull);
        for (final width in [768.0, 769.0, 1280.0]) {
          for (final scale in [1.0, 2.0]) {
            await pumpScreen(tester, screen, scale: scale, size: Size(width, 800));
            expect(tester.takeException(), isNull, reason: '$width × $scale');
          }
        }
        await pumpScreen(tester, screen, brightness: Brightness.dark);
        expect(tester.takeException(), isNull);
      });

      testWidgets('$name: 초록 계열 글자가 없다', (tester) async {
        await pumpScreen(tester, screen);
        for (final t in tester.widgetList<Text>(find.byType(Text, skipOffstage: false))) {
          final c = t.style?.color;
          // 본문·보조색의 옅은 초록빛 회색(채도 낮음)은 허용하고, 뚜렷한 초록만 막는다
          if (c != null) expect(c.g - (c.r > c.b ? c.r : c.b) > 0.06, isFalse, reason: '초록 계열 글자: ${t.data}');
        }
      });
    });
  });

  group('홈: 앱 배치(좁은 화면)', () {
    testWidgets('왼쪽 정렬 두 줄 제목, 설명, 입력 카드, 폭을 채우는 버튼', (tester) async {
      await pumpScreen(tester, InputScreen(onSubmit: (_) {}));
      final title = find.text('영상 속 단서,\n차분히 확인하세요.');
      expect(title, findsOneWidget);
      expect(tester.getTopLeft(title).dx, TSpace.screen);
      expect(find.text(InputScreen.lead), findsOneWidget);
      // 입력란과 버튼이 같은 카드 안에 있다
      final card = find.ancestor(of: find.byType(TextField), matching: find.byType(Panel));
      expect(card, findsOneWidget);
      expect(find.descendant(of: card, matching: find.text(InputScreen.submitLabel)), findsOneWidget);
      // 버튼이 카드 안쪽 폭을 채운다
      final button = tester.getSize(find.byType(PrimaryButton));
      final field = tester.getSize(find.byType(TextField));
      expect(button.width, field.width);
      expect(button.width, greaterThan(250));
      // 상단: 로고와 메뉴가 아닌 웹 전용 요소는 없다
      expect(find.text('TRINITY'), findsOneWidget); // 로고
      expect(find.text(InputScreen.permissionShort), findsNothing);
      expect(find.text('이런 단서를 살펴봐요', skipOffstage: false), findsOneWidget);
    });

    testWidgets('768 너비까지는 앱 배치, 769부터 웹 배치', (tester) async {
      await pumpScreen(tester, InputScreen(onSubmit: (_) {}), size: const Size(768, 900));
      expect(find.text('영상 속 단서,\n차분히 확인하세요.'), findsOneWidget);
      expect(find.ancestor(of: find.byType(TextField), matching: find.byType(Panel)), findsOneWidget);
      await pumpScreen(tester, InputScreen(onSubmit: (_) {}), size: const Size(769, 900));
      expect(find.text('영상 속 단서,\n차분히 확인하세요.'), findsNothing);
      expect(find.text(InputScreen.tagline), findsOneWidget);
    });
  });

  group('홈: 웹 배치(넓은 화면)', () {
    Future<void> pumpWeb(WidgetTester tester, {MockScenario? mock, ValueChanged<String>? onSubmit}) => pumpScreen(
          tester,
          TrinityNav(
            onHome: noop,
            onGuide: noop,
            child: InputScreen(onSubmit: onSubmit ?? (_) {}, mockScenario: mock, onMockScenarioChanged: (_) {}),
          ),
          size: desktop,
        );

    testWidgets('가운데 워드마크, 한 줄 소개, 폭 680의 캡슐 입력창', (tester) async {
      await pumpWeb(tester);
      final mark = find.text('TRINITY');
      expect(mark, findsOneWidget);
      expect(tester.getCenter(mark).dx, closeTo(640, 1));
      expect(tester.widget<Text>(mark).style!.fontSize, greaterThanOrEqualTo(40));
      expect(tester.getCenter(find.text(InputScreen.tagline)).dx, closeTo(640, 1));
      // 워드마크는 화면 가운데보다 위에 있다
      expect(tester.getCenter(mark).dy, lessThan(400));
      final field = tester.getRect(find.byType(TextField));
      expect(field.width, 680);
      expect(field.center.dx, closeTo(640, 1));
      final deco = tester.widget<TextField>(find.byType(TextField)).decoration!;
      expect((deco.enabledBorder as OutlineInputBorder).borderRadius, BorderRadius.circular(32));
      expect((deco.prefixIcon as Icon).icon, Icons.link);
      // 순서: 워드마크 → 소개 → 입력창 → 버튼 → 허가 안내 → 접힌 설명
      final ys = [
        tester.getCenter(mark).dy,
        tester.getCenter(find.text(InputScreen.tagline)).dy,
        field.center.dy,
        tester.getCenter(find.text(InputScreen.submitLabel)).dy,
        tester.getCenter(find.text(InputScreen.permissionShort)).dy,
        tester.getCenter(find.text(InputScreen.helpTitle)).dy,
      ];
      expect(ys, [...ys]..sort());
    });

    testWidgets('입력창을 감싼 카드, 큰 메뉴, 영문 머리글, 원형 장식이 없다', (tester) async {
      await pumpWeb(tester);
      expect(find.ancestor(of: find.byType(TextField), matching: find.byType(Panel)), findsNothing);
      expect(find.text('영상 확인'), findsNothing);
      expect(find.byType(Overline), findsNothing);
      for (final text in allText(tester)) {
        expect(text.toUpperCase().contains('CLOSER LOOK'), isFalse);
        expect(text.contains('LOOK CLOSER'), isFalse);
      }
      for (final c in tester.widgetList<Container>(find.byType(Container))) {
        final d = c.decoration;
        if (d is BoxDecoration) expect(d.shape, BoxShape.rectangle);
      }
    });

    testWidgets('오른쪽 위에 작은 "이용 안내"만 있다', (tester) async {
      await pumpWeb(tester);
      final guide = find.text('이용 안내');
      expect(guide, findsOneWidget);
      final pos = tester.getCenter(guide);
      expect(pos.dx, greaterThan(1280 - 150));
      expect(pos.dy, lessThan(120));
      expect(tester.widget<Text>(guide).style!.fontSize, lessThanOrEqualTo(14));
    });

    testWidgets('"분석 요청"과 mock 전용 "예시로 둘러보기"가 입력창 아래 가운데에 나란히 있다', (tester) async {
      final sent = <String>[];
      await pumpWeb(tester, mock: MockScenario.abstained, onSubmit: sent.add);
      final submit = tester.getRect(find.byType(PrimaryButton));
      final example = tester.getRect(find.byType(SecondaryButton));
      expect(submit.center.dy, example.center.dy);
      expect(submit.right, lessThan(example.left));
      expect((submit.left + example.right) / 2, closeTo(640, 1));
      expect(submit.top, greaterThan(tester.getRect(find.byType(TextField)).bottom));
      await tester.tap(find.text(InputScreen.exampleLabel));
      expect(sent, [InputScreen.exampleUrl]);
    });

    testWidgets('mock이 아니면 "예시로 둘러보기"와 가상 결과 고르기가 없다', (tester) async {
      await pumpWeb(tester);
      expect(find.text(InputScreen.exampleLabel), findsNothing);
      expect(find.text('가상 결과 고르기'), findsNothing);
      expect(tester.getCenter(find.byType(PrimaryButton)).dx, closeTo(640, 1));
    });

    testWidgets('"무엇을 분석하나요?"는 접혀 있다가 펴진다', (tester) async {
      await pumpWeb(tester);
      expect(find.text('영상의 미세한 신호'), findsNothing);
      await tester.tap(find.text(InputScreen.helpTitle));
      await tester.pump();
      expect(find.text('영상의 미세한 신호'), findsOneWidget);
      expect(find.textContaining('영상 파일은 받지 않습니다'), findsOneWidget);
    });
  });

  group('홈: 입력', () {
    for (final size in [phone, desktop]) {
      testWidgets('${size.width.toInt()}: 주소를 넘기고 빈 입력은 막는다. 파일 고르기는 없다', (tester) async {
        final sent = <String>[];
        await pumpScreen(tester, InputScreen(onSubmit: sent.add), size: size);
        await tester.tap(find.text(InputScreen.submitLabel));
        await tester.pump();
        expect(sent, isEmpty);
        expect(find.text('YouTube 영상 주소를 넣어 주세요.'), findsOneWidget);
        await tester.enterText(find.byType(TextField), '  https://youtu.be/abc  ');
        await tester.tap(find.text(InputScreen.submitLabel));
        expect(sent, ['https://youtu.be/abc']);
        expect(find.textContaining('파일 선택', skipOffstage: false), findsNothing);
        expect(find.textContaining('업로드하', skipOffstage: false), findsNothing);
      });
    }

    testWidgets('앱 배치: mock에서만 예시 버튼과 가상 결과 고르기가 보인다', (tester) async {
      MockScenario? picked;
      final sent = <String>[];
      await pumpScreen(tester, InputScreen(onSubmit: sent.add));
      expect(find.text(InputScreen.exampleLabel, skipOffstage: false), findsNothing);
      expect(find.text('가상 결과 고르기', skipOffstage: false), findsNothing);
      await pumpScreen(
        tester,
        InputScreen(onSubmit: sent.add, mockScenario: MockScenario.abstained, onMockScenarioChanged: (s) => picked = s),
      );
      await tester.ensureVisible(find.text('가상 결과 고르기', skipOffstage: false));
      await tester.pump();
      await tester.tap(find.text('가상 결과 고르기'));
      await tester.pump();
      await tester.ensureVisible(find.text('의심 신호 발견', skipOffstage: false));
      await tester.pump();
      await tester.tap(find.text('의심 신호 발견'));
      expect(picked, MockScenario.suspicious);
      await tester.ensureVisible(find.text(InputScreen.exampleLabel, skipOffstage: false));
      await tester.pump();
      await tester.tap(find.text(InputScreen.exampleLabel));
      expect(sent, [InputScreen.exampleUrl]);
    });

    testWidgets('요청 중에는 버튼이 꺼진다', (tester) async {
      final sent = <String>[];
      await pumpScreen(tester, InputScreen(onSubmit: sent.add, busy: true));
      await tester.tap(find.text('요청하는 중…'));
      expect(sent, isEmpty);
    });
  });

  group('분석 중', () {
    testWidgets('단계 이름과 상태만 보이고 숫자 %는 없다', (tester) async {
      await pumpScreen(
        tester,
        ProgressScreen(
          state: const JobState(jobStatus: JobStatus.processing, stage: 'waverep', completedStages: ['validating', 'access_check', 'preprocessing']),
          onRestart: noop,
        ),
      );
      expect(colorOfText(tester, '분석 중'), light.muted);
      for (final label in stageLabels.values) {
        expect(find.text(label, skipOffstage: false), findsOneWidget);
      }
      final rows = tester.widgetList<StageRow>(find.byType(StageRow, skipOffstage: false)).toList();
      expect(rows.map((r) => r.state).toList(), [
        StageState.done, StageState.done, StageState.done, StageState.current,
        StageState.pending, StageState.pending, StageState.pending, StageState.pending,
      ]);
      for (final text in allText(tester)) {
        expect(text.contains('%'), isFalse, reason: text);
        expect(RegExp(r'\d').hasMatch(text), isFalse, reason: text);
      }
      expect(find.byType(LinearProgressIndicator, skipOffstage: false), findsNothing);
      expect(find.byType(CircularProgressIndicator, skipOffstage: false), findsNothing);
      expect(find.text('처음으로', skipOffstage: false), findsNothing);
    });

    testWidgets('넓은 화면에서는 단계를 두 줄로 나눠도 순서가 같다', (tester) async {
      await pumpScreen(
        tester,
        ProgressScreen(state: const JobState(jobStatus: JobStatus.processing, stage: 'validating'), onRestart: noop),
        size: desktop,
      );
      final rows = tester.widgetList<StageRow>(find.byType(StageRow)).toList();
      expect(rows.map((r) => r.label).toList(), stageLabels.values.toList());
      expect(tester.getTopLeft(find.byWidget(rows[0])).dy, tester.getTopLeft(find.byWidget(rows[4])).dy);
    });

    testWidgets('대기 중은 따로 표시한다', (tester) async {
      await pumpScreen(tester, ProgressScreen(state: const JobState(jobStatus: JobStatus.queued), onRestart: noop));
      expect(find.text('대기 중'), findsOneWidget);
      final rows = tester.widgetList<StageRow>(find.byType(StageRow, skipOffstage: false));
      expect(rows.every((r) => r.state == StageState.pending), isTrue);
    });

    testWidgets('작업 실패는 판정이 아니라고 알린다', (tester) async {
      var restarted = false;
      await pumpScreen(
        tester,
        ProgressScreen(
          state: const JobState(jobStatus: JobStatus.failed, completedStages: ['validating']),
          failureReasonCode: 'timeout',
          onRestart: () => restarted = true,
        ),
      );
      expect(colorOfText(tester, '분석 실패'), light.warning);
      expect(find.text(ProgressScreen.notVerdict), findsOneWidget);
      expect(find.text(reasonText('timeout')!), findsOneWidget);
      expect(find.text('의심 신호 낮음', skipOffstage: false), findsNothing);
      await tester.ensureVisible(find.text('처음으로', skipOffstage: false));
      await tester.pump();
      await tester.tap(find.text('처음으로'));
      expect(restarted, isTrue);
    });
  });

  group('결과 요약', () {
    final expected = {
      ScreenKind.suspicious: (MockScenario.suspicious, '의심 신호 발견', StatusTone.suspicious),
      ScreenKind.low: (MockScenario.low, '의심 신호 낮음', StatusTone.low),
      ScreenKind.abstained: (MockScenario.abstained, '판단 보류', StatusTone.warning),
      ScreenKind.unavailable: (MockScenario.unavailable, '영상 접근 불가', StatusTone.warning),
      ScreenKind.outOfScope: (MockScenario.outOfScope, '분석 대상 아님', StatusTone.muted),
    };
    expected.forEach((kind, e) {
      final (scenario, label, tone) = e;
      for (final p in TPalette.all) {
        testWidgets('$label (${p.brightness.name}): 라벨과 색', (tester) async {
          await pumpScreen(tester, result(kind, scenario), brightness: p.brightness);
          expect(find.text(label), findsOneWidget);
          expect(colorOfText(tester, label), tone.fg(p));
          for (final other in expected.values.map((v) => v.$2).where((l) => l != label)) {
            expect(find.text(other, skipOffstage: false), findsNothing);
          }
        });
      }

      testWidgets('$label: 숫자 점수와 퍼센트가 없다', (tester) async {
        await pumpScreen(tester, result(kind, scenario));
        for (final text in allText(tester)) {
          expect(text.contains('%'), isFalse, reason: text);
          expect(RegExp(r'\d[.,]\d').hasMatch(text), isFalse, reason: '소수 점수로 보이는 글자: $text');
          expect(text.contains('확률'), isFalse, reason: text);
          expect(text.contains('점수'), isFalse, reason: text);
        }
      });

      testWidgets('$label: 작업·분석·판정을 따로 보여 준다', (tester) async {
        await pumpScreen(tester, result(kind, scenario));
        expect(find.text('이번 요청의 상태', skipOffstage: false), findsOneWidget);
        expect(find.text('종료', skipOffstage: false), findsOneWidget);
        expect(find.text(verdictText(kind), skipOffstage: false), findsOneWidget);
        expect(find.text(analysisStatusLabel[mockResult(scenario).analysisStatus]!, skipOffstage: false), findsOneWidget);
        expect(find.text(ResultScreen.summaryNote, skipOffstage: false), findsOneWidget);
      });
    });

    testWidgets('발견: 조작을 확정하지 않는다고 적는다', (tester) async {
      await pumpScreen(tester, result(ScreenKind.suspicious, MockScenario.suspicious));
      expect(find.text(ResultScreen.suspiciousDisclaimer), findsOneWidget);
    });

    testWidgets('낮음: 무채색 라벨, 진짜라는 뜻이 아니라는 문구, "안전"·"진짜 영상입니다" 없음', (tester) async {
      for (final p in TPalette.all) {
        await pumpScreen(tester, result(ScreenKind.low, MockScenario.low), brightness: p.brightness);
        expect(isAchromatic(colorOfText(tester, '의심 신호 낮음')!), isTrue);
        final chip = tester.widget<Container>(
            find.ancestor(of: find.text('의심 신호 낮음'), matching: find.byType(Container)).first);
        expect(isAchromatic((chip.decoration as BoxDecoration).color!), isTrue);
      }
      expect(find.text(ResultScreen.lowDisclaimer), findsOneWidget);
      for (final text in allText(tester)) {
        expect(text.contains('안전'), isFalse, reason: text);
        expect(text.contains('진짜 영상입니다'), isFalse, reason: text);
      }
    });

    testWidgets('보류: 이유를 적고 어느 쪽으로도 판단하지 않았다고 적는다', (tester) async {
      await pumpScreen(tester, result(ScreenKind.abstained, MockScenario.abstained));
      expect(find.text('판단을 보류한 이유'), findsOneWidget);
      expect(find.text(reasonText('no_valid_fusion_model')!), findsOneWidget);
      expect(find.text(ResultScreen.noJudgement), findsOneWidget);
    });

    testWidgets('발견·낮음·보류는 분석 범위를 보여 준다', (tester) async {
      for (final (kind, s) in [
        (ScreenKind.suspicious, MockScenario.suspicious),
        (ScreenKind.low, MockScenario.low),
        (ScreenKind.abstained, MockScenario.abstained),
      ]) {
        await pumpScreen(tester, result(kind, s));
        expect(find.text(CoverageBar.title, skipOffstage: false), findsOneWidget);
        expect(find.text(CoverageBar.disclaimer, skipOffstage: false), findsOneWidget);
        expect(find.text('영상 1분 0초 가운데 20초를 분석했습니다.', skipOffstage: false), findsOneWidget);
      }
    });

    testWidgets('접근 불가: 이유를 적고 판정하지 않으며 분석 범위를 그리지 않는다', (tester) async {
      await pumpScreen(tester, result(ScreenKind.unavailable, MockScenario.unavailable));
      expect(find.text(reasonText('access_not_authorized')!), findsOneWidget);
      expect(find.textContaining(ResultScreen.noJudgement), findsOneWidget);
      expect(find.byType(CoverageBar, skipOffstage: false), findsNothing);
    });

    testWidgets('대상 아님: 이유를 적고 판정하지 않는다', (tester) async {
      await pumpScreen(tester, result(ScreenKind.outOfScope, MockScenario.outOfScope));
      expect(find.textContaining(analysisStatusText[AnalysisStatus.outOfScope]!), findsOneWidget);
      expect(find.text(ResultScreen.noJudgement), findsOneWidget);
      expect(find.byType(CoverageBar, skipOffstage: false), findsNothing);
    });

    testWidgets('넓은 화면에서는 요청 상태가 오른쪽에 놓인다', (tester) async {
      await pumpScreen(tester, result(ScreenKind.abstained, MockScenario.abstained), size: desktop);
      expect(tester.getTopLeft(find.text('이번 요청의 상태')).dx,
          greaterThan(tester.getTopLeft(find.text('판단 보류')).dx + 300));
    });

    testWidgets('버튼이 동작한다', (tester) async {
      final calls = <String>[];
      await pumpScreen(tester, ResultScreen(
        kind: ScreenKind.abstained, result: mockResult(MockScenario.abstained),
        onShowDetail: () => calls.add('detail'), onRestart: () => calls.add('restart'),
      ));
      await tester.tap(find.text('새 영상 확인'));
      for (final label in ['판단 근거 살펴보기', '다른 영상 확인']) {
        await tester.ensureVisible(find.text(label, skipOffstage: false));
        await tester.pump();
        await tester.tap(find.text(label));
      }
      expect(calls, ['restart', 'detail', 'restart']);
    });
  });

  group('판단 근거 상세', () {
    testWidgets('원시 지표에 "확률 아님"을 표시한다', (tester) async {
      await pumpScreen(tester, DetailScreen(result: mockResult(MockScenario.abstained), onBack: noop));
      expect(find.text(DetailScreen.notProbability, skipOffstage: false), findsOneWidget);
      expect(find.text(DetailScreen.rawNotice, skipOffstage: false), findsOneWidget);
      expect(find.text('원시 점수 · 확률 아님', skipOffstage: false), findsNWidgets(2));
      expect(find.text('LSE-C · 확률 아님', skipOffstage: false), findsOneWidget);
      expect(find.text('0.81', skipOffstage: false), findsOneWidget);
      expect(find.text('4.20', skipOffstage: false), findsOneWidget);
      for (final text in allText(tester)) {
        expect(text.contains('%'), isFalse, reason: text);
      }
    });

    testWidgets('없는 값은 0이 아니라 "값 없음"이다', (tester) async {
      await pumpScreen(tester, DetailScreen(result: mockResult(MockScenario.abstained), onBack: noop));
      final physics = tester.widget<AxisResultRow>(find.byWidgetPredicate(
          (w) => w is AxisResultRow && w.description.contains('MotionPhys'), skipOffstage: false));
      expect(physics.metrics.single.$2, '값 없음');
      expect(physics.statusText, '입력 부족 · 움직임이 부족합니다.');
      expect(find.text('0.00', skipOffstage: false), findsNothing);
      expect(find.textContaining('종합 점수는 값 없음', skipOffstage: false), findsOneWidget);
    });

    testWidgets('SyncNet은 보조 지표라고 적고 종합 판정 포함 여부를 보여 준다', (tester) async {
      await pumpScreen(tester, DetailScreen(result: mockResult(MockScenario.abstained), onBack: noop));
      final row = tester.widget<AxisResultRow>(find.byWidgetPredicate(
          (w) => w is AxisResultRow && w.description.contains('SyncNet'), skipOffstage: false));
      expect(row.metrics.last, ('종합 판정에 포함', '아니오'));
      expect(find.textContaining(DetailScreen.syncNote, skipOffstage: false), findsOneWidget);
    });

    testWidgets('서버가 보낸 세 상태를 그대로 보여 준다', (tester) async {
      await pumpScreen(tester, DetailScreen(result: mockResult(MockScenario.abstained), onBack: noop));
      for (final wire in ['finished', 'partial', 'abstained', 'no_valid_fusion_model']) {
        expect(find.text(wire, skipOffstage: false), findsOneWidget);
      }
    });

    testWidgets('접근 불가 결과의 상세는 모든 지표가 "값 없음"이다', (tester) async {
      await pumpScreen(tester, DetailScreen(result: mockResult(MockScenario.unavailable), onBack: noop));
      final rows = tester.widgetList<AxisResultRow>(find.byType(AxisResultRow, skipOffstage: false));
      expect(rows, hasLength(3));
      for (final r in rows) {
        for (final (name, value) in r.metrics) {
          if (name.contains('확률 아님')) expect(value, '값 없음');
        }
      }
      expect(find.text('분석한 구간이 기록되지 않았습니다.', skipOffstage: false), findsOneWidget);
    });
  });

  group('이용 안내', () {
    testWidgets('네 가지 안내와 시작 버튼', (tester) async {
      var started = false;
      await pumpScreen(tester, GuideScreen(onStart: () => started = true));
      for (final (title, body) in GuideScreen.items) {
        expect(find.text(title, skipOffstage: false), findsOneWidget);
        expect(find.text(body, skipOffstage: false), findsOneWidget);
      }
      expect(find.textContaining('진짜 영상이라는 뜻은 아닙니다', skipOffstage: false), findsOneWidget);
      expect(find.textContaining('영상 파일 업로드는 받지 않습니다', skipOffstage: false), findsOneWidget);
      await tester.ensureVisible(find.text('영상 확인하러 가기', skipOffstage: false));
      await tester.pump();
      await tester.tap(find.text('영상 확인하러 가기'));
      expect(started, isTrue);
    });
  });
}
