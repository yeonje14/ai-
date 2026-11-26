import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/api/models.dart';
import 'package:trinity_app/api/replay_api.dart';
import 'package:trinity_app/app.dart';
import 'package:trinity_app/config.dart';

void main() {
  final data = {
    'schema': 1,
    'source': 'real_run',
    'label': '녹화 예제',
    'status_sequence': [
      {
        'after_sec': 0,
        'body': {'job_status': 'queued'},
      },
      {
        'after_sec': 2.5,
        'body': {'job_status': 'processing', 'stage': 'waverep'},
      },
      {
        'after_sec': 7,
        'body': {'job_status': 'finished'},
      },
    ],
    'result': {
      'job_status': 'finished',
      'analysis_id': 'recorded-1',
      'youtube_video_id': 'recorded',
    },
  };
  Future<String> asset(String path) async =>
      path.endsWith('index.json') ? '["a.json"]' : jsonEncode(data);

  test('녹화 상대 시각에 도달해야 기록된 상태와 결과를 볼 수 있다', () async {
    var now = Duration.zero;
    final api = ReplayApi(loadAsset: asset, now: () => now);
    final catalog = await api.recordings();
    expect(catalog.single.label, '녹화 예제');
    final job = await api.create(catalog.single.filename);
    expect(api.untilNextState, const Duration(milliseconds: 2500));
    now = const Duration(milliseconds: 2499);
    expect((await api.status(job.analysisId)).jobStatus, JobStatus.queued);
    now += const Duration(milliseconds: 1);
    expect((await api.result(job.analysisId)).pending?.stage, 'waverep');
    now = const Duration(seconds: 7);
    expect((await api.result(job.analysisId)).result?.analysisId, 'recorded-1');
    await api.create(catalog.single.filename);
    expect(api.untilNextState, const Duration(milliseconds: 2500));
  });

  test('목록 밖 이름과 임의 URL은 재생할 수 없다', () async {
    final api = ReplayApi(loadAsset: asset);
    await expectLater(
      api.create('https://example.com/'),
      throwsA(isA<ApiException>()),
    );
  });

  testWidgets('선택·안내·진행·결과·상세에서 시연 고지를 유지한다', (tester) async {
    var now = Duration.zero;
    final api = ReplayApi(loadAsset: asset, now: () => now);
    await tester.pumpWidget(
      TrinityApp(
        config: const AppConfig(mode: ApiMode.replay),
        api: api,
      ),
    );
    await tester.pump();
    void banner() {
      expect(find.text('시연용 녹화 결과'), findsOneWidget);
      expect(find.textContaining('가상 데이터'), findsNothing);
    }

    banner();
    await tester.tap(find.text('이용 안내'));
    await tester.pump();
    banner();
    await tester.tap(find.text('영상 확인'));
    await tester.pump();
    await tester.pump();
    await tester.tap(find.text('녹화 예제'));
    await tester.pump();
    banner();
    expect(find.text('대기 중'), findsWidgets);
    now = const Duration(milliseconds: 2500);
    await tester.pump(now);
    banner();
    expect(find.text('분석 중'), findsWidgets);
    now = const Duration(seconds: 7);
    await tester.pump(const Duration(milliseconds: 4500));
    await tester.pump();
    banner();
    final detail = find.text('판단 근거 살펴보기');
    await tester.ensureVisible(detail);
    await tester.tap(detail);
    await tester.pump();
    banner();
    expect(find.text('결과 요약으로 돌아가기'), findsOneWidget);
  });

  test('합성 출처나 목록 경로를 거부한다', () async {
    final mock = ReplayApi(
      loadAsset: (name) async => name.endsWith('index.json')
          ? '["a.json"]'
          : jsonEncode({...data, 'source': 'mock'}),
    );
    await expectLater(mock.recordings(), throwsFormatException);
    final traversal = ReplayApi(loadAsset: (_) async => '["../example.json"]');
    await expectLater(traversal.recordings(), throwsFormatException);
  });

  testWidgets('빈 목록에는 URL 입력란이나 가상 데이터 고지 대신 녹화 안내가 보인다', (tester) async {
    final api = ReplayApi(loadAsset: (_) async => '[]');
    await tester.pumpWidget(
      TrinityApp(
        config: const AppConfig(mode: ApiMode.replay),
        api: api,
      ),
    );
    await tester.pump();
    expect(find.text('시연용 녹화 결과'), findsOneWidget);
    expect(find.text('아직 등록된 녹화가 없습니다.'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(find.textContaining('가상 데이터'), findsNothing);
  });
}
