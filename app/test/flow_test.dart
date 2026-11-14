import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/api/models.dart';
import 'package:trinity_app/app.dart';
import 'package:trinity_app/config.dart';
import 'package:trinity_app/screens/detail_screen.dart';
import 'package:trinity_app/screens/progress_screen.dart';
import 'package:trinity_app/screens/result_screen.dart';

const tick = Duration(milliseconds: 100);
const url = 'https://www.youtube.com/watch?v=abc';

Future<void> start(WidgetTester tester, AnalysisApi api, {ApiMode mode = ApiMode.mock}) async {
  tester.view.physicalSize = const Size(360, 640);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(TrinityApp(config: AppConfig(mode: mode, pollInterval: tick), api: api));
}

Future<void> submit(WidgetTester tester, String text) async {
  await tester.enterText(find.byType(TextField), text);
  // 시나리오를 고르느라 내려간 화면을 맨 위로 되돌린다
  await tester.drag(find.byType(SingleChildScrollView), const Offset(0, 5000));
  await tester.pump();
  await tester.tap(find.text('분석 요청'));
  await tester.pump();
}

/// 끝날 때까지 상태 조회 주기를 돌린다.
Future<void> runToEnd(WidgetTester tester) async {
  for (var i = 0; i < 15; i++) {
    await tester.pump(tick);
  }
}

/// mock의 결과를 실제 서버 모드에서 받는 것처럼 감싼다(MockAnalysisApi가 아니므로 시나리오 선택이 안 보인다).
class FakeServerApi implements AnalysisApi {
  FakeServerApi(MockScenario s) : _inner = MockAnalysisApi(scenario: s);
  final MockAnalysisApi _inner;
  @override
  Future<CreatedAnalysis> create(String url) => _inner.create(url);
  @override
  Future<JobState> status(String id) => _inner.status(id);
  @override
  Future<ResultResponse> result(String id) => _inner.result(id);
}

/// 처음 몇 번은 연결이 실패하는 API.
class FlakyApi extends FakeServerApi {
  FlakyApi() : super(MockScenario.abstained);
  int failures = 2;
  @override
  Future<JobState> status(String id) {
    if (failures-- > 0) throw const ApiException(ApiErrorKind.network);
    return super.status(id);
  }
}

void main() {
  testWidgets('mock: 입력 → 분석 중 → 판단 보류 → 상세 → 요약 → 처음', (tester) async {
    await start(tester, MockAnalysisApi());
    expect(find.text('가상 결과 고르기'), findsOneWidget);
    await submit(tester, url);
    expect(find.byType(ProgressScreen), findsOneWidget);
    expect(find.text('대기 중'), findsOneWidget);
    await tester.pump(tick);
    await tester.pump(tick);
    expect(find.text('분석 중'), findsOneWidget);
    await runToEnd(tester);
    expect(find.byType(ResultScreen), findsOneWidget);
    expect(find.text('판단 보류'), findsOneWidget);

    await tester.ensureVisible(find.text('판단 근거 보기'));
    await tester.tap(find.text('판단 근거 보기'));
    await tester.pump();
    expect(find.byType(DetailScreen), findsOneWidget);
    await tester.tap(find.text('결과 요약으로 돌아가기').first);
    await tester.pump();
    expect(find.byType(ResultScreen), findsOneWidget);
    await tester.ensureVisible(find.text('다른 영상 분석'));
    await tester.tap(find.text('다른 영상 분석'));
    await tester.pump();
    expect(find.byType(TextField), findsOneWidget);
  });

  final outcomes = {
    MockScenario.suspicious: '의심 신호 발견',
    MockScenario.low: '의심 신호 낮음',
    MockScenario.abstained: '판단 보류',
    MockScenario.unavailable: '영상 접근 불가',
    MockScenario.outOfScope: '분석 대상 아님',
    MockScenario.failed: '분석 실패',
  };
  outcomes.forEach((scenario, label) {
    testWidgets('mock ${scenario.name} → "$label"', (tester) async {
      await start(tester, MockAnalysisApi());
      await tester.ensureVisible(find.text(scenario.label));
      await tester.tap(find.text(scenario.label));
      await tester.pump();
      await submit(tester, url);
      await runToEnd(tester);
      expect(find.text(label), findsOneWidget);
      for (final other in outcomes.values.where((l) => l != label)) {
        expect(find.text(other), findsNothing);
      }
      expect(find.text('모델 미연결 · 가상 데이터'), findsOneWidget);
    });
  });

  for (final scenario in [MockScenario.suspicious, MockScenario.low]) {
    testWidgets('실제 서버 모드: ${scenario.name} 라벨이 와도 판단 보류로 보인다', (tester) async {
      await start(tester, FakeServerApi(scenario), mode: ApiMode.server);
      expect(find.text('가상 결과 고르기'), findsNothing);
      await submit(tester, url);
      await runToEnd(tester);
      expect(find.text('판단 보류'), findsOneWidget);
      expect(find.text('의심 신호 발견'), findsNothing);
      expect(find.text('의심 신호 낮음'), findsNothing);
    });
  }

  testWidgets('잘못된 주소(422)는 입력 화면에 안내를 보이고 넘어가지 않는다', (tester) async {
    await start(tester, MockAnalysisApi());
    await submit(tester, 'https://example.com/video');
    await tester.pump();
    expect(find.byType(ProgressScreen), findsNothing);
    expect(find.textContaining('YouTube 영상 주소가 아닙니다'), findsOneWidget);
  });

  testWidgets('연결이 끊기면 알리고 다시 조회해 끝까지 간다', (tester) async {
    await start(tester, FlakyApi(), mode: ApiMode.server);
    await submit(tester, url);
    await tester.pump(tick);
    await tester.pump();
    expect(find.text('연결이 끊겼습니다'), findsOneWidget);
    await runToEnd(tester);
    expect(find.text('연결이 끊겼습니다'), findsNothing);
    expect(find.text('판단 보류'), findsOneWidget);
  });
}
