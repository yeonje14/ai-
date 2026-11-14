import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/api/models.dart';

http.Response jsonRes(Object body, int status) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

void main() {
  group('HttpAnalysisApi', () {
    test('세 엔드포인트를 계약대로 부른다', () async {
      final seen = <http.Request>[];
      final client = MockClient((req) async {
        seen.add(req);
        if (req.method == 'POST') {
          return jsonRes({'analysis_id': 'id-1', 'youtube_video_id': 'VID', 'job_status': 'queued'}, 202);
        }
        if (req.url.path.endsWith('/result')) {
          return jsonRes({'job_status': 'processing', 'stage': 'waverep'}, 202);
        }
        return jsonRes({
          'analysis_id': 'id-1', 'job_status': 'processing', 'stage': 'access_check',
          'completed_stages': ['validating'],
        }, 200);
      });
      final api = HttpAnalysisApi(baseUrl: 'http://localhost:8000/', client: client, clientToken: 't' * 32);

      final created = await api.create('https://youtu.be/abc');
      expect(created.analysisId, 'id-1');
      expect(created.jobStatus, JobStatus.queued);
      final status = await api.status('id-1');
      expect(status.jobStatus, JobStatus.processing);
      expect(status.stage, 'access_check');
      expect(status.completedStages, ['validating']);
      final pending = await api.result('id-1');
      expect(pending.result, isNull);
      expect(pending.pending!.stage, 'waverep');

      expect(seen.map((r) => '${r.method} ${r.url}'), [
        'POST http://localhost:8000/api/v1/analyses',
        'GET http://localhost:8000/api/v1/analyses/id-1',
        'GET http://localhost:8000/api/v1/analyses/id-1/result',
      ]);
      expect(jsonDecode(seen.first.body), {'url': 'https://youtu.be/abc'});
      for (final r in seen) {
        expect(r.headers['X-Client-Token'], 't' * 32);
      }
    });

    test('200 결과를 그대로 읽는다', () async {
      final body = mockResultJson(MockScenario.abstained, 'id-1');
      final api = HttpAnalysisApi(baseUrl: 'http://localhost:8000', client: MockClient((_) async => jsonRes(body, 200)));
      final res = (await api.result('id-1')).result!;
      expect(res.jobStatus, JobStatus.finished);
      expect(res.analysisStatus, AnalysisStatus.partial);
      expect(res.verdictStatus, VerdictStatus.abstained);
      expect(res.verdictLabel, isNull);
      expect(res.overallScore, isNull);
      expect(res.abstentionReason, 'no_valid_fusion_model');
      expect(res.axes['physics']!.rawScore, isNull);
      expect(res.axes['physics']!.reasonCode, 'insufficient_motion');
      expect(res.coverage!.segments, [(5.0, 25.0)]);
    });

    final errors = {
      422: ApiErrorKind.invalidUrl, 429: ApiErrorKind.queueFull, 503: ApiErrorKind.queueFull,
      401: ApiErrorKind.unauthorized, 403: ApiErrorKind.unauthorized, 404: ApiErrorKind.notFound,
      500: ApiErrorKind.server,
    };
    errors.forEach((status, kind) {
      test('HTTP $status → ${kind.name}', () async {
        final api = HttpAnalysisApi(
          baseUrl: 'http://localhost:8000',
          client: MockClient((_) async => jsonRes({'detail': {'reason_code': 'some_reason'}}, status)),
        );
        await expectLater(
          api.create('x'),
          throwsA(isA<ApiException>()
              .having((e) => e.kind, 'kind', kind)
              .having((e) => e.reasonCode, 'reasonCode', 'some_reason')),
        );
      });
    });

    test('연결 실패는 network이고 주소를 담지 않는다', () async {
      final api = HttpAnalysisApi(
        baseUrl: 'http://localhost:8000',
        client: MockClient((_) async => throw http.ClientException('refused http://localhost:8000/secret?q=1')),
      );
      try {
        await api.status('id');
        fail('예외가 나야 한다');
      } on ApiException catch (e) {
        expect(e.kind, ApiErrorKind.network);
        expect(e.toString().contains('secret'), isFalse);
      }
    });

    test('토큰은 서버가 받는 길이(16~256)다', () {
      final a = generateClientToken(), b = generateClientToken();
      expect(a.length, 32);
      expect(a, isNot(b));
    });
  });

  group('MockAnalysisApi', () {
    test('단계가 순서대로 나아가고 끝나기 전에는 결과가 202다', () async {
      final api = MockAnalysisApi(scenario: MockScenario.abstained);
      final id = (await api.create('https://www.youtube.com/watch?v=abc')).analysisId;
      expect((await api.result(id)).result, isNull);
      final stages = <String?>[];
      JobState s;
      do {
        s = await api.status(id);
        stages.add(s.stage);
      } while (s.isActive);
      expect(stages.whereType<String>().toList(), stageOrder);
      expect(s.jobStatus, JobStatus.finished);
      expect((await api.result(id)).result!.verdictStatus, VerdictStatus.abstained);
    });

    test('YouTube가 아닌 주소는 422로 거절한다', () async {
      final api = MockAnalysisApi();
      for (final bad in ['', 'hello', 'https://example.com/watch?v=1', 'file:///etc/passwd', 'http://127.0.0.1/x']) {
        await expectLater(api.create(bad),
            throwsA(isA<ApiException>().having((e) => e.kind, 'kind', ApiErrorKind.invalidUrl)));
      }
    });

    test('접근 불가 시나리오는 모델 단계까지 가지 않는다', () async {
      final api = MockAnalysisApi(scenario: MockScenario.unavailable);
      final id = (await api.create('https://youtu.be/abc')).analysisId;
      JobState s;
      final stages = <String>[];
      do {
        s = await api.status(id);
        if (s.stage != null) stages.add(s.stage!);
      } while (s.isActive);
      expect(stages, ['validating', 'access_check']);
      final res = (await api.result(id)).result!;
      expect(res.analysisStatus, AnalysisStatus.analysisUnavailable);
      expect(res.overallScore, isNull);
    });
  });
}
