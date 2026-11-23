import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/config.dart';
import 'package:trinity_app/screens/result_screen.dart';

import 'flow_test.dart' show start, submit, tick, url;

void main() {
  for (final reason in ['user_submission_limit', 'request_rate_limited']) {
    testWidgets('$reason 대기는 현재 세션에서만 제출을 막는다', (tester) async {
      final posts = <String>[];
      final api = HttpAnalysisApi(baseUrl: 'http://localhost', client: MockClient((req) async {
        if (req.method == 'GET') return http.Response('{"items":[],"next_cursor":null}', 200);
        final token = req.headers['authorization']!;
        posts.add(token);
        if (token == 'Bearer A') {
          return http.Response(jsonEncode({'detail': {'reason_code': reason}}), 429,
              headers: {'retry-after': '60'});
        }
        return http.Response('{"analysis_id":"job-b","youtube_video_id":"abc","job_status":"queued"}', 202);
      }));

      Future<void> openSubmission(String key) async {
        await start(tester, api, mode: ApiMode.server);
        await tester.enterText(find.byType(TextField), key);
        await tester.tap(find.text('인증'));
        await tester.pumpAndSettle();
        expect(find.text('새 분석'), findsOneWidget);
        await tester.tap(find.text('새 분석'));
        await tester.pumpAndSettle();
      }

      await openSubmission('A');
      await submit(tester, url);
      expect(find.textContaining('초 뒤에 다시 요청'), findsOneWidget);
      await submit(tester, url);
      expect(posts, ['Bearer A']);

      await tester.pumpWidget(const SizedBox.shrink());
      await openSubmission('B');
      await submit(tester, url);
      expect(posts, ['Bearer A', 'Bearer B']);
      expect(find.text('대기 중'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('401에서 폴링을 중단하고 새 키로 목록과 결과를 복원한다', (tester) async {
    final lists = <String>[];
    var reads = 0;
    final api = HttpAnalysisApi(baseUrl: 'http://localhost', client: MockClient((req) async {
      final token = req.headers['authorization']!;
      if (req.url.path.endsWith('/analyses')) {
        lists.add(token);
        return http.Response(jsonEncode({'items': [
          {'analysis_id': 'owned-job', 'job_status': 'processing', 'created_at': 1}
        ], 'next_cursor': null}), 200);
      }
      reads++;
      if (token == 'Bearer first') return http.Response('{}', 401);
      if (req.url.path.endsWith('/result')) {
        return http.Response.bytes(utf8.encode(jsonEncode(mockResultJson(MockScenario.abstained, 'owned-job'))), 200);
      }
      return http.Response('{"job_status":"finished"}', 200);
    }));
    await start(tester, api, mode: ApiMode.server);
    Future<void> authenticate(String key) async {
      await tester.enterText(find.byType(TextField), key);
      await tester.tap(find.text('인증'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('owned-job'));
      await tester.pumpAndSettle();
    }
    await authenticate('first');
    expect(find.text('인증'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, isEmpty);
    await tester.pump(tick * 10);
    expect(reads, 1);
    await authenticate('replacement');
    expect(lists, ['Bearer first', 'Bearer replacement']);
    expect(find.byType(ResultScreen), findsOneWidget);
    expect(reads, 3);
  });
}
