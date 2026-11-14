import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/api/models.dart';
import 'package:trinity_app/design/tokens.dart';
import 'package:trinity_app/design/widgets.dart';
import 'package:trinity_app/screens/detail_screen.dart';
import 'package:trinity_app/screens/input_screen.dart';
import 'package:trinity_app/screens/progress_screen.dart';
import 'package:trinity_app/screens/result_screen.dart';
import 'package:trinity_app/view_state.dart';

import 'helpers.dart';

const band = '모델 미연결 · 가상 데이터';
void noop() {}

/// 화면 8개(+ 작업 실패 상태). 이름 → 위젯.
Map<String, Widget> screens() => {
      '입력': InputScreen(onSubmit: (_) {}, mockScenario: MockScenario.abstained, onMockScenarioChanged: (_) {}),
      '입력(오류)': InputScreen(onSubmit: (_) {}, errorText: 'YouTube 영상 주소가 아닙니다. youtube.com 또는 youtu.be 주소를 넣어 주세요.'),
      '분석 중': ProgressScreen(
        state: const JobState(jobStatus: JobStatus.processing, stage: 'waverep', completedStages: ['validating', 'access_check', 'preprocessing']),
        connectionLost: true,
        onRestart: noop,
      ),
      '의심 신호 발견': ResultScreen(kind: ScreenKind.suspicious, result: mockResult(MockScenario.suspicious), onShowDetail: noop, onRestart: noop),
      '의심 신호 낮음': ResultScreen(kind: ScreenKind.low, result: mockResult(MockScenario.low), onShowDetail: noop, onRestart: noop),
      '판단 보류': ResultScreen(kind: ScreenKind.abstained, result: mockResult(MockScenario.abstained), onShowDetail: noop, onRestart: noop),
      '판단 근거 상세': DetailScreen(result: mockResult(MockScenario.abstained), onBack: noop),
      '판단 근거 상세(값 없음)': DetailScreen(result: mockResult(MockScenario.unavailable), onBack: noop),
      '영상 접근 불가': UnavailableScreen(result: mockResult(MockScenario.unavailable), onShowDetail: noop, onRestart: noop),
      '분석 대상 아님': OutOfScopeScreen(result: mockResult(MockScenario.outOfScope), onShowDetail: noop, onRestart: noop),
      '작업 실패': ProgressScreen(
        state: const JobState(jobStatus: JobStatus.failed, completedStages: ['validating']),
        failureReasonCode: 'timeout',
        onRestart: noop,
      ),
    };

void main() {
  group('모든 화면', () {
    screens().forEach((name, screen) {
      testWidgets('$name: 상단 고지 띠가 있다', (tester) async {
        await pumpScreen(tester, screen);
        expect(find.text(band), findsOneWidget);
        expect(tester.takeException(), isNull);
      });

      for (final scale in [1.3, 2.0]) {
        testWidgets('$name: 글자 크기 $scale배, 360×640에서 넘치지 않는다', (tester) async {
          await pumpScreen(tester, screen, scale: scale);
          expect(tester.takeException(), isNull);
          // 끝까지 내려도 넘침이 없다
          await tester.drag(find.byType(SingleChildScrollView), const Offset(0, -5000));
          await tester.pump();
          expect(tester.takeException(), isNull);
        });
      }

      testWidgets('$name: 좁은 화면(320)과 넓은 화면(1280)에서 넘치지 않는다', (tester) async {
        await pumpScreen(tester, screen, scale: 2.0, size: const Size(320, 568));
        expect(tester.takeException(), isNull);
        await pumpScreen(tester, screen, size: const Size(1280, 800));
        expect(tester.takeException(), isNull);
      });
    });
  });

  group('입력', () {
    testWidgets('주소를 넘기고 빈 입력은 막는다. 파일 고르기는 없다', (tester) async {
      final sent = <String>[];
      await pumpScreen(tester, InputScreen(onSubmit: sent.add));
      await tester.tap(find.text('분석 요청'));
      await tester.pump();
      expect(sent, isEmpty);
      expect(find.text('YouTube 영상 주소를 넣어 주세요.'), findsOneWidget);
      await tester.enterText(find.byType(TextField), '  https://youtu.be/abc  ');
      await tester.tap(find.text('분석 요청'));
      expect(sent, ['https://youtu.be/abc']);
      expect(find.textContaining('업로드'), findsNothing);
      expect(find.textContaining('파일 선택'), findsNothing);
      expect(find.textContaining('영상 파일은 받지 않습니다'), findsOneWidget);
    });

    testWidgets('mock 시나리오는 mock 모드에서만 보인다', (tester) async {
      MockScenario? picked;
      await pumpScreen(tester, InputScreen(onSubmit: (_) {}));
      expect(find.text('가상 결과 고르기'), findsNothing);
      await pumpScreen(
        tester,
        InputScreen(onSubmit: (_) {}, mockScenario: MockScenario.abstained, onMockScenarioChanged: (s) => picked = s),
      );
      expect(find.text('가상 결과 고르기'), findsOneWidget);
      await tester.ensureVisible(find.text('의심 신호 발견'));
      await tester.tap(find.text('의심 신호 발견'));
      expect(picked, MockScenario.suspicious);
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
      expect(find.text('분석 중'), findsOneWidget);
      expect(colorOfText(tester, '분석 중'), TColors.textSecondary);
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
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.text('처음으로'), findsNothing);
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
      expect(colorOfText(tester, '분석 실패'), TColors.warning);
      expect(find.textContaining('판정이 아닙니다'), findsOneWidget);
      expect(find.text(reasonText('timeout')!), findsOneWidget);
      expect(find.text('의심 신호 낮음'), findsNothing);
      await tester.ensureVisible(find.text('처음으로'));
      await tester.tap(find.text('처음으로'));
      expect(restarted, isTrue);
    });
  });

  group('결과 요약', () {
    final expected = {
      ScreenKind.suspicious: (MockScenario.suspicious, '의심 신호 발견', TColors.accent),
      ScreenKind.low: (MockScenario.low, '의심 신호 낮음', TColors.neutral),
      ScreenKind.abstained: (MockScenario.abstained, '판단 보류', TColors.warning),
    };
    expected.forEach((kind, e) {
      final (scenario, label, color) = e;
      testWidgets('$label: 라벨·색·문구', (tester) async {
        await pumpScreen(tester, ResultScreen(kind: kind, result: mockResult(scenario), onShowDetail: noop, onRestart: noop));
        expect(find.text(label), findsOneWidget);
        expect(colorOfText(tester, label), color);
        for (final other in expected.values.map((v) => v.$2).where((l) => l != label)) {
          expect(find.text(other), findsNothing);
        }
        expect(find.text(CoverageBar.disclaimer, skipOffstage: false), findsOneWidget);
        expect(find.text('영상 1분 0초 가운데 20초를 분석했습니다.', skipOffstage: false), findsOneWidget);
      });

      testWidgets('$label: 숫자 점수와 퍼센트가 없다', (tester) async {
        final result = mockResult(scenario);
        await pumpScreen(tester, ResultScreen(kind: kind, result: result, onShowDetail: noop, onRestart: noop));
        for (final text in allText(tester)) {
          expect(text.contains('%'), isFalse, reason: text);
          expect(RegExp(r'\d[.,]\d').hasMatch(text), isFalse, reason: '소수 점수로 보이는 글자: $text');
          expect(text.contains('확률'), isFalse, reason: text);
          expect(text.contains('점수'), isFalse, reason: text);
        }
      });
    });

    testWidgets('발견: 조작을 확정하지 않는다고 적는다', (tester) async {
      await pumpScreen(tester, ResultScreen(kind: ScreenKind.suspicious, result: mockResult(MockScenario.suspicious), onShowDetail: noop, onRestart: noop));
      expect(find.text(ResultScreen.suspiciousDisclaimer), findsOneWidget);
    });

    testWidgets('낮음: 진짜라는 뜻이 아니라고 적고 초록·"안전"·"진짜 영상입니다"를 쓰지 않는다', (tester) async {
      await pumpScreen(tester, ResultScreen(kind: ScreenKind.low, result: mockResult(MockScenario.low), onShowDetail: noop, onRestart: noop));
      expect(find.text(ResultScreen.lowDisclaimer), findsOneWidget);
      for (final text in allText(tester)) {
        expect(text.contains('안전'), isFalse, reason: text);
        expect(text.contains('진짜 영상입니다'), isFalse, reason: text);
      }
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final c = t.style?.color;
        if (c != null) expect(c.g > c.r && c.g > c.b, isFalse, reason: '초록 계열 글자: ${t.data}');
      }
    });

    testWidgets('보류: 이유를 적고 어느 쪽으로도 판단하지 않았다고 적는다', (tester) async {
      await pumpScreen(tester, ResultScreen(kind: ScreenKind.abstained, result: mockResult(MockScenario.abstained), onShowDetail: noop, onRestart: noop));
      expect(find.textContaining(reasonText('no_valid_fusion_model')!), findsOneWidget);
      expect(find.textContaining('의심 신호가 있다고도 없다고도 판단하지 않았습니다'), findsOneWidget);
    });

    testWidgets('버튼이 동작한다', (tester) async {
      final calls = <String>[];
      await pumpScreen(tester, ResultScreen(
        kind: ScreenKind.abstained, result: mockResult(MockScenario.abstained),
        onShowDetail: () => calls.add('detail'), onRestart: () => calls.add('restart'),
      ));
      await tester.ensureVisible(find.text('판단 근거 보기'));
      await tester.tap(find.text('판단 근거 보기'));
      await tester.ensureVisible(find.text('다른 영상 분석'));
      await tester.tap(find.text('다른 영상 분석'));
      expect(calls, ['detail', 'restart']);
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
      // 움직임 축: insufficient_input, raw_score null
      final physics = tester.widget<AxisResultRow>(find.byWidgetPredicate(
          (w) => w is AxisResultRow && w.title.contains('MotionPhys'), skipOffstage: false));
      expect(physics.metrics.single.$2, '값 없음');
      expect(physics.statusText, '입력 부족 · 움직임이 부족합니다.');
      expect(find.text('0.00', skipOffstage: false), findsNothing);
    });

    testWidgets('SyncNet은 보조 지표라고 적고 종합 판정 포함 여부를 보여 준다', (tester) async {
      await pumpScreen(tester, DetailScreen(result: mockResult(MockScenario.abstained), onBack: noop));
      final row = tester.widget<AxisResultRow>(find.byWidgetPredicate(
          (w) => w is AxisResultRow && w.title.contains('SyncNet'), skipOffstage: false));
      expect(row.note, contains('보조 지표'));
      expect(row.metrics.last, ('종합 판정에 포함', '아니오'));
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
      expect(find.text('분석 범위 정보가 없습니다.', skipOffstage: false), findsOneWidget);
    });
  });

  group('영상 접근 불가 · 분석 대상 아님', () {
    testWidgets('접근 불가: 경고색 라벨, 이유, 판정 없음', (tester) async {
      await pumpScreen(tester, UnavailableScreen(result: mockResult(MockScenario.unavailable), onShowDetail: noop, onRestart: noop));
      expect(colorOfText(tester, '영상 접근 불가'), TColors.warning);
      expect(find.textContaining(reasonText('access_not_authorized')!), findsOneWidget);
      expect(find.textContaining('의심 신호가 있다고도 없다고도 판단하지 않았습니다'), findsOneWidget);
      for (final label in ['의심 신호 발견', '의심 신호 낮음', '판단 보류']) {
        expect(find.text(label), findsNothing);
      }
      expect(find.byType(CoverageBar), findsNothing);
    });

    testWidgets('분석 대상 아님: 보조색 라벨, 이유, 판정 없음', (tester) async {
      await pumpScreen(tester, OutOfScopeScreen(result: mockResult(MockScenario.outOfScope), onShowDetail: noop, onRestart: noop));
      expect(colorOfText(tester, '분석 대상 아님'), TColors.textSecondary);
      expect(find.textContaining(analysisStatusText[AnalysisStatus.outOfScope]!), findsOneWidget);
      for (final label in ['의심 신호 발견', '의심 신호 낮음', '판단 보류']) {
        expect(find.text(label), findsNothing);
      }
    });
  });
}
