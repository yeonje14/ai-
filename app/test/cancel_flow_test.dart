import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/screens/progress_screen.dart';
import 'package:trinity_app/screens/result_screen.dart';

import 'flow_test.dart' show start, submit, tick, url, runToEnd;

http.Response response(Object body, int status, {String? etag}) => http.Response.bytes(
      utf8.encode(jsonEncode(body)), status,
      headers: {'content-type': 'application/json', 'etag': ?etag},
    );

void main() {
  for (final code in [202, 412]) {
    testWidgets('취소 DELETE $code 뒤 조회만 하여 실제 종료 화면을 표시한다', (tester) async {
      final requests = <http.Request>[];
      var ended = false;
      final api = HttpAnalysisApi(baseUrl: 'http://localhost:8000', client: MockClient((req) async {
        requests.add(req);
        if (req.method == 'POST') {
          return response({'analysis_id': 'id', 'job_status': 'queued'}, 202);
        }
        if (req.method == 'DELETE') {
          expect(req.headers['if-match'], '"id:active"');
          expect(req.headers['x-client-token'], isNotEmpty);
          ended = true;
          return response({'analysis_id': 'id', 'job_status': 'processing'}, code);
        }
        final status = ended ? (code == 202 ? 'cancelled' : 'finished') : 'processing';
        if (req.url.path.endsWith('/result')) {
          return response(code == 202
              ? {'analysis_id': 'id', 'job_status': 'cancelled'}
              : mockResultJson(MockScenario.abstained, 'id'), 200);
        }
        return response({'analysis_id': 'id', 'job_status': status, 'stage': 'preprocessing'},
            200, etag: ended ? '"id:$status"' : '"id:active"');
      }));
      await start(tester, api);
      await submit(tester, url);
      expect(find.text('분석 취소'), findsOneWidget);
      await tester.ensureVisible(find.text('분석 취소'));
      await tester.pump();
      await tester.tap(find.text('분석 취소'));
      await tester.pump();
      await runToEnd(tester);
      expect(requests.where((r) => r.method == 'DELETE').length, 1);
      expect(requests.last.method, 'GET');
      expect(find.text('연결이 끊겼어요'), findsNothing);
      if (code == 202) {
        expect(find.byType(ProgressScreen), findsOneWidget);
        expect(find.text('취소됨'), findsOneWidget);
      } else {
        expect(find.byType(ResultScreen), findsOneWidget);
        expect(find.text('판단 보류'), findsOneWidget);
      }
      expect(find.text('분석 취소'), findsNothing);
    });
  }

  testWidgets('취소 요청 중 중복 클릭과 자동 DELETE 재시도가 없다', (tester) async {
    final pendingDelete = Completer<http.Response>();
    var deletes = 0;
    var cancelled = false;
    final api = HttpAnalysisApi(baseUrl: 'http://localhost:8000', client: MockClient((req) async {
      if (req.method == 'POST') return response({'analysis_id': 'id', 'job_status': 'queued'}, 202);
      if (req.method == 'DELETE') {
        deletes++;
        final res = await pendingDelete.future;
        cancelled = true;
        return res;
      }
      return response({'analysis_id': 'id', 'job_status': cancelled ? 'cancelled' : 'processing'},
          200, etag: '"id:active"');
    }));
    await start(tester, api);
    await submit(tester, url);
    expect(find.text('분석 취소'), findsOneWidget);
    await tester.ensureVisible(find.text('분석 취소'));
    await tester.pump();
    await tester.tap(find.text('분석 취소'));
    await tester.pump();
    expect(find.text('취소 요청 중…'), findsOneWidget);
    await tester.tap(find.text('취소 요청 중…'));
    await tester.pump(tick);
    expect(deletes, 1);
    pendingDelete.complete(response({'job_status': 'processing'}, 202));
    await tester.pump();
    await runToEnd(tester);
    expect(deletes, 1);
    expect(find.text('취소됨'), findsOneWidget);
  });

  testWidgets('mock 취소도 기존 취소됨 화면에 도달한다', (tester) async {
    await start(tester, MockAnalysisApi());
    await submit(tester, url);
    expect(find.text('분석 취소'), findsOneWidget);
    await tester.ensureVisible(find.text('분석 취소'));
    await tester.pump();
    await tester.tap(find.text('분석 취소'));
    await tester.pump();
    await runToEnd(tester);
    expect(find.text('취소됨'), findsOneWidget);
  });
}
