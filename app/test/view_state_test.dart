import 'package:flutter_test/flutter_test.dart';
import 'package:trinity_app/api/analysis_api.dart';
import 'package:trinity_app/api/mock_api.dart';
import 'package:trinity_app/api/models.dart';
import 'package:trinity_app/view_state.dart';

AnalysisResult r(Map<String, dynamic> j) =>
    AnalysisResult.fromJson({'analysis_id': 'a', 'youtube_video_id': 'v', 'job_status': 'finished', ...j});

void main() {
  group('resolveScreen', () {
    final cases = <(Map<String, dynamic>, ScreenKind)>[
      ({'analysis_status': 'completed', 'verdict_status': 'assessed', 'verdict_label': 'suspicious_signals'}, ScreenKind.suspicious),
      ({'analysis_status': 'completed', 'verdict_status': 'assessed', 'verdict_label': 'low_suspicion'}, ScreenKind.low),
      ({'analysis_status': 'partial', 'verdict_status': 'assessed', 'verdict_label': 'low_suspicion'}, ScreenKind.low),
      ({'analysis_status': 'partial', 'verdict_status': 'abstained'}, ScreenKind.abstained),
      ({'analysis_status': 'completed', 'verdict_status': 'abstained'}, ScreenKind.abstained),
      ({'analysis_status': 'analysis_unavailable', 'verdict_status': 'abstained'}, ScreenKind.unavailable),
      ({'analysis_status': 'out_of_scope', 'verdict_status': 'not_applicable'}, ScreenKind.outOfScope),
      ({'analysis_status': 'unsupported', 'verdict_status': 'not_applicable'}, ScreenKind.outOfScope),
      ({'analysis_status': 'insufficient_quality', 'verdict_status': 'not_applicable'}, ScreenKind.outOfScope),
      ({'job_status': 'failed', 'reason_code': 'timeout'}, ScreenKind.jobFailed),
      ({'job_status': 'cancelled'}, ScreenKind.jobFailed),
    ];
    for (final (json, expected) in cases) {
      test('$json → ${expected.name}', () {
        expect(resolveScreen(r(json), allowVerdictLabels: true), expected);
      });
    }

    test('라벨 없는 assessed는 판단 보류다. 점수가 높아도 낮아도 그렇다', () {
      for (final score in [0.99, 0.01, null]) {
        final res = r({'analysis_status': 'completed', 'verdict_status': 'assessed', 'overall_score': score});
        expect(resolveScreen(res, allowVerdictLabels: true), ScreenKind.abstained);
      }
    });

    test('모르는 라벨·모르는 상태는 판단 보류다', () {
      expect(
        resolveScreen(r({'analysis_status': 'completed', 'verdict_status': 'assessed', 'verdict_label': 'real'}),
            allowVerdictLabels: true),
        ScreenKind.abstained,
      );
      expect(
        resolveScreen(r({'analysis_status': 'something_new', 'verdict_status': 'something_new'}),
            allowVerdictLabels: true),
        ScreenKind.abstained,
      );
      expect(resolveScreen(r({}), allowVerdictLabels: true), ScreenKind.abstained);
    });

    test('abstained에 라벨이 붙어 와도 발견·낮음으로 보이지 않는다', () {
      final res = r({'analysis_status': 'completed', 'verdict_status': 'abstained', 'verdict_label': 'low_suspicion'});
      expect(resolveScreen(res, allowVerdictLabels: true), ScreenKind.abstained);
    });

    test('실제 서버 모드에서는 라벨이 와도 판단 보류다', () {
      for (final s in [MockScenario.suspicious, MockScenario.low]) {
        final res = AnalysisResult.fromJson(mockResultJson(s, 'x'));
        expect(resolveScreen(res, allowVerdictLabels: false), ScreenKind.abstained);
      }
      // 접근 불가·대상 아님은 모드와 무관하다
      expect(
        resolveScreen(AnalysisResult.fromJson(mockResultJson(MockScenario.unavailable, 'x')), allowVerdictLabels: false),
        ScreenKind.unavailable,
      );
    });

    test('접근 불가는 판정 상태보다 먼저 본다', () {
      final res = r({'analysis_status': 'analysis_unavailable', 'verdict_status': 'assessed', 'verdict_label': 'low_suspicion'});
      expect(resolveScreen(res, allowVerdictLabels: true), ScreenKind.unavailable);
    });
  });

  test('단계 이름은 서버의 여덟 단계를 모두 덮는다', () {
    expect(stageLabels.keys.toList(), stageOrder);
    for (final label in stageLabels.values) {
      expect(label.contains('%'), isFalse);
      expect(RegExp(r'\d').hasMatch(label), isFalse);
    }
  });

  test('문구 도우미', () {
    expect(formatDuration(65.9), '1분 5초');
    expect(formatDuration(20), '20초');
    expect(metricText(null), '값 없음');
    expect(metricText(0), '0.00');
    expect(coverageCaption(null), '분석 범위 정보가 없습니다.');
    expect(coverageCaption(const Coverage(videoDurationSec: 60, analyzedDurationSec: 20)),
        '영상 1분 0초 가운데 20초를 분석했습니다.');
    expect(reasonText('no_valid_fusion_model'), isNotNull);
    expect(reasonText('made_up_code'), isNull);
    for (final kind in ApiErrorKind.values) {
      expect(apiErrorText(ApiException(kind)), isNotEmpty);
    }
  });

  test('없는 점수는 null로 남는다', () {
    final res = AnalysisResult.fromJson(mockResultJson(MockScenario.unavailable, 'x'));
    expect(res.overallScore, isNull);
    expect(res.axes['signal']!.rawScore, isNull);
    expect(res.axes['alignment']!.lseC, isNull);
    expect(res.coverage!.videoDurationSec, isNull);
    expect(res.verdictLabel, isNull);
  });
}
