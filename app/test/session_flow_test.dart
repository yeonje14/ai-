import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/config.dart';
import 'package:trinity_app/screens/result_screen.dart';

import 'flow_test.dart' show start, tick;

void main() {
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
