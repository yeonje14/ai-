// 실제 서버에 앱의 API 클라이언트로 요청을 보내 끝까지 가는지 확인한다 (브라우저 없이).
//
//   dart run tool/smoke_server.dart [서버 주소] [YouTube 주소]
//
// 서버와 Worker가 떠 있어야 한다. 결과의 상태 값과 앱이 고를 화면 이름을 출력한다.
import 'dart:io';

import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/view_state.dart';

Future<void> main(List<String> args) async {
  final base = args.isNotEmpty ? args[0] : 'http://localhost:8000';
  final url = args.length > 1 ? args[1] : 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';
  final api = HttpAnalysisApi(baseUrl: base);
  try {
    final created = await api.create(url);
    stdout.writeln('접수: job_status=${created.jobStatus.name}');
    final seen = <String>[];
    for (var i = 0; i < 120; i++) {
      final s = await api.status(created.analysisId);
      final line = '${s.jobStatus.name}${s.stage == null ? '' : ' / ${s.stage}'}';
      if (seen.isEmpty || seen.last != line) seen.add(line);
      if (!s.isActive) break;
      await Future<void>.delayed(const Duration(milliseconds: 200));
    }
    stdout.writeln('상태 변화: ${seen.join(' → ')}');
    final res = (await api.result(created.analysisId)).result;
    if (res == null) {
      stdout.writeln('아직 끝나지 않았다. Worker가 떠 있는지 확인한다.');
      exit(2);
    }
    stdout.writeln('결과: job=${res.rawString('job_status')} analysis=${res.rawString('analysis_status')} '
        'verdict=${res.rawString('verdict_status')} verdict_label=${res.raw['verdict_label']} '
        'overall_score=${res.overallScore} reason=${res.abstentionReason ?? res.reasonCode}');
    stdout.writeln('화면(server 모드): ${resolveScreen(res, allowVerdictLabels: false).name}');
  } on ApiException catch (e) {
    stdout.writeln('요청 실패: ${e.kind.name} (HTTP ${e.statusCode}, ${e.reasonCode})');
    exit(1);
  }
  exit(0);
}
