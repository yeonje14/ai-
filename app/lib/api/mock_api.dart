import 'analysis_api.dart';
import 'models.dart';

/// mock 모드에서 고를 수 있는 가상 결과. 모두 꾸며 낸 값이며 실제 분석이 아니다.
enum MockScenario {
  suspicious('의심 신호 발견'),
  low('의심 신호 낮음'),
  abstained('판단 보류'),
  unavailable('영상 접근 불가'),
  outOfScope('분석 대상 아님'),
  failed('작업 실패');

  const MockScenario(this.label);
  final String label;
}

const _allowedHosts = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'};

/// 서버 없이 화면을 확인하기 위한 가짜 구현. 네트워크를 쓰지 않는다.
///
/// status()를 부를 때마다 한 단계씩 나아간다(타이머 없음). 발견·낮음 라벨은 여기서만 나온다.
class MockAnalysisApi implements AnalysisApi {
  MockAnalysisApi({this.scenario = MockScenario.abstained});

  MockScenario scenario;
  final Map<String, _MockJob> _jobs = {};
  int _seq = 0;

  @override
  Future<CreatedAnalysis> create(String url) async {
    final uri = Uri.tryParse(url.trim());
    if (uri == null || !uri.hasScheme || !_allowedHosts.contains(uri.host.toLowerCase())) {
      throw const ApiException(ApiErrorKind.invalidUrl, reasonCode: 'invalid_youtube_url', statusCode: 422);
    }
    final id = 'mock-${++_seq}';
    _jobs[id] = _MockJob(scenario);
    return CreatedAnalysis(analysisId: id, youtubeVideoId: 'MOCKVIDEO00', jobStatus: JobStatus.queued);
  }

  @override
  Future<JobState> status(String analysisId) async => _job(analysisId).advance();

  @override
  Future<ResultResponse> result(String analysisId) async {
    final job = _job(analysisId);
    final state = job.current();
    if (state.isActive) return ResultResponse.pending(state);
    return ResultResponse.done(AnalysisResult.fromJson(mockResultJson(job.scenario, analysisId)));
  }

  _MockJob _job(String id) =>
      _jobs[id] ?? (throw const ApiException(ApiErrorKind.notFound, statusCode: 404));
}

class _MockJob {
  _MockJob(this.scenario);

  final MockScenario scenario;
  int _step = -1; // -1: queued, 0..n-1: 단계 진행 중, n: 종료

  int get _lastStage => switch (scenario) {
        MockScenario.unavailable => 2, // 접근 확인에서 끝난다
        MockScenario.outOfScope => 3, // 전처리에서 끝난다
        MockScenario.failed => 4,
        _ => stageOrder.length,
      };

  JobState advance() {
    if (_step < _lastStage) _step++;
    return current();
  }

  JobState current() {
    if (_step < 0) return const JobState(jobStatus: JobStatus.queued);
    if (_step >= _lastStage) {
      return JobState(
        jobStatus: scenario == MockScenario.failed ? JobStatus.failed : JobStatus.finished,
        completedStages: stageOrder.sublist(0, _lastStage),
      );
    }
    return JobState(
      jobStatus: JobStatus.processing,
      stage: stageOrder[_step],
      completedStages: stageOrder.sublist(0, _step),
    );
  }
}

/// 시나리오별 결과 JSON. README §9의 예시 모양을 따른 가상의 값이다.
Map<String, dynamic> mockResultJson(MockScenario scenario, String analysisId) {
  final base = <String, dynamic>{
    'analysis_id': analysisId,
    'youtube_video_id': 'MOCKVIDEO00',
    'job_status': 'finished',
    'verdict_label': null,
    'overall_score': null,
    'abstention_reason': null,
    'reason_code': null,
    'media_provenance': 'registered_authorized_source',
  };
  const coverage = {
    'video_duration_sec': 60,
    'eligible_duration_sec': 35,
    'analyzed_duration_sec': 20,
    'full_video_coverage': 0.3333,
    'eligible_coverage': 0.5714,
    'analyzed_segments': [
      {'start_sec': 5, 'end_sec': 25},
    ],
  };
  const emptyCoverage = {
    'video_duration_sec': null,
    'eligible_duration_sec': null,
    'analyzed_duration_sec': null,
    'full_video_coverage': null,
    'eligible_coverage': null,
    'analyzed_segments': <Object>[],
  };
  Map<String, dynamic> axes({double? signal, double? physics, bool physicsOk = true}) => {
        'signal': {'status': 'completed', 'raw_score': signal, 'model_version': 'mock'},
        'physics': physicsOk
            ? {'status': 'completed', 'raw_score': physics, 'model_version': 'mock'}
            : {'status': 'insufficient_input', 'reason_code': 'insufficient_motion', 'raw_score': null},
        'alignment': {'status': 'completed', 'lse_c': 4.2, 'lse_d': 7.8, 'included_in_fusion': false},
      };
  Map<String, dynamic> notRun(String reason) => {
        for (final name in ['signal', 'physics'])
          name: {'status': 'insufficient_input', 'reason_code': reason, 'raw_score': null},
        'alignment': {
          'status': 'insufficient_input',
          'reason_code': reason,
          'lse_c': null,
          'lse_d': null,
          'included_in_fusion': false,
        },
      };

  switch (scenario) {
    case MockScenario.suspicious:
      return {
        ...base,
        'analysis_status': 'completed',
        'verdict_status': 'assessed',
        'verdict_label': 'suspicious_signals',
        'overall_score': 0.87,
        'coverage': coverage,
        'axes': axes(signal: 0.81, physics: 0.74),
        'explanations': [
          {
            'template_id': 'MOCK_SUSPICIOUS',
            'reason_code': 'mock',
            'message': '가상 데이터입니다. 분석한 구간에서 AI 생성 관련 신호와 비슷한 특징이 관찰된 경우의 예시입니다.',
          },
        ],
      };
    case MockScenario.low:
      return {
        ...base,
        'analysis_status': 'completed',
        'verdict_status': 'assessed',
        'verdict_label': 'low_suspicion',
        'overall_score': 0.12,
        'coverage': coverage,
        'axes': axes(signal: 0.09, physics: 0.15),
        'explanations': [
          {
            'template_id': 'MOCK_LOW',
            'reason_code': 'mock',
            'message': '가상 데이터입니다. 분석한 구간에서 의심 신호가 낮게 나온 경우의 예시입니다.',
          },
        ],
      };
    case MockScenario.abstained:
      return {
        ...base,
        'analysis_status': 'partial',
        'verdict_status': 'abstained',
        'abstention_reason': 'no_valid_fusion_model',
        'coverage': coverage,
        'axes': axes(signal: 0.81, physicsOk: false),
        'explanations': [
          {
            'template_id': 'NO_VALID_FUSION',
            'reason_code': 'no_valid_fusion_model',
            'message': '검증된 종합 판정 모델이 없어 판단을 보류합니다.',
          },
        ],
      };
    case MockScenario.unavailable:
      return {
        ...base,
        'analysis_status': 'analysis_unavailable',
        'verdict_status': 'abstained',
        'abstention_reason': 'access_not_authorized',
        'reason_code': 'access_not_authorized',
        'media_provenance': null,
        'coverage': emptyCoverage,
        'axes': notRun('access_not_authorized'),
        'explanations': [
          {
            'template_id': 'ACCESS_NOT_AUTHORIZED',
            'reason_code': 'access_not_authorized',
            'message': '분석이 허가된 미디어로 등록되지 않은 영상이라 분석하지 않았습니다.',
          },
        ],
      };
    case MockScenario.outOfScope:
      return {
        ...base,
        'analysis_status': 'out_of_scope',
        'verdict_status': 'not_applicable',
        'coverage': emptyCoverage,
        'axes': notRun('speaker_unconfirmed'),
        'explanations': <Object>[],
      };
    case MockScenario.failed:
      return {
        'analysis_id': analysisId,
        'youtube_video_id': 'MOCKVIDEO00',
        'job_status': 'failed',
        'reason_code': 'timeout',
      };
  }
}
