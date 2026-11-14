/// README §9, §10의 응답 모델. 서버가 보낸 상태 값을 그대로 담는다.
///
/// 모르는 값은 unknown으로, 없는 값은 null로 둔다. 0이나 추측값으로 채우지 않는다.
library;

enum JobStatus { queued, processing, finished, failed, cancelled, unknown }

enum AnalysisStatus {
  completed('completed'),
  partial('partial'),
  outOfScope('out_of_scope'),
  unsupported('unsupported'),
  insufficientQuality('insufficient_quality'),
  analysisUnavailable('analysis_unavailable'),
  unknown('');

  const AnalysisStatus(this.wire);
  final String wire;
}

enum VerdictStatus {
  assessed('assessed'),
  abstained('abstained'),
  notApplicable('not_applicable'),
  unknown('');

  const VerdictStatus(this.wire);
  final String wire;
}

/// 서버가 정한 판정 라벨. 클라이언트는 점수로 라벨을 만들지 않는다.
enum VerdictLabel {
  suspiciousSignals('suspicious_signals'),
  lowSuspicion('low_suspicion');

  const VerdictLabel(this.wire);
  final String wire;
}

/// 진행 단계 (서버의 순서 그대로).
const stageOrder = <String>[
  'validating',
  'access_check',
  'preprocessing',
  'waverep',
  'motionphys',
  'syncnet',
  'fusion',
  'finalizing',
];

JobStatus parseJobStatus(Object? v) =>
    JobStatus.values.firstWhere((e) => e.name == v, orElse: () => JobStatus.unknown);

AnalysisStatus? parseAnalysisStatus(Object? v) => v == null
    ? null
    : AnalysisStatus.values.firstWhere((e) => e.wire == v, orElse: () => AnalysisStatus.unknown);

VerdictStatus? parseVerdictStatus(Object? v) => v == null
    ? null
    : VerdictStatus.values.firstWhere((e) => e.wire == v, orElse: () => VerdictStatus.unknown);

VerdictLabel? parseVerdictLabel(Object? v) {
  for (final e in VerdictLabel.values) {
    if (e.wire == v) return e;
  }
  return null; // 없거나 모르는 값은 라벨 없음으로 본다
}

double? _num(Object? v) => v is num ? v.toDouble() : null;
String? _str(Object? v) => v is String ? v : null;

class CreatedAnalysis {
  const CreatedAnalysis({required this.analysisId, required this.youtubeVideoId, required this.jobStatus});

  factory CreatedAnalysis.fromJson(Map<String, dynamic> j) => CreatedAnalysis(
        analysisId: j['analysis_id'] as String,
        youtubeVideoId: _str(j['youtube_video_id']) ?? '',
        jobStatus: parseJobStatus(j['job_status']),
      );

  final String analysisId;
  final String youtubeVideoId;
  final JobStatus jobStatus;
}

/// GET /analyses/{id}
class JobState {
  const JobState({required this.jobStatus, this.stage, this.completedStages = const []});

  factory JobState.fromJson(Map<String, dynamic> j) => JobState(
        jobStatus: parseJobStatus(j['job_status']),
        stage: _str(j['stage']),
        completedStages: [for (final s in (j['completed_stages'] as List? ?? const [])) s.toString()],
      );

  final JobStatus jobStatus;
  final String? stage;
  final List<String> completedStages;

  bool get isActive => jobStatus == JobStatus.queued || jobStatus == JobStatus.processing;
}

class Coverage {
  const Coverage({
    this.videoDurationSec,
    this.eligibleDurationSec,
    this.analyzedDurationSec,
    this.segments = const [],
  });

  factory Coverage.fromJson(Map<String, dynamic> j) => Coverage(
        videoDurationSec: _num(j['video_duration_sec']),
        eligibleDurationSec: _num(j['eligible_duration_sec']),
        analyzedDurationSec: _num(j['analyzed_duration_sec']),
        segments: [
          for (final s in (j['analyzed_segments'] as List? ?? const []))
            if (s is Map && _num(s['start_sec']) != null && _num(s['end_sec']) != null)
              (_num(s['start_sec'])!, _num(s['end_sec'])!),
        ],
      );

  final double? videoDurationSec;
  final double? eligibleDurationSec;
  final double? analyzedDurationSec;
  final List<(double, double)> segments;
}

/// 축 하나의 결과. 점수가 없으면 null이다.
class AxisResult {
  const AxisResult({
    required this.status,
    this.reasonCode,
    this.rawScore,
    this.lseC,
    this.lseD,
    this.includedInFusion,
    this.modelVersion,
  });

  factory AxisResult.fromJson(Map<String, dynamic> j) => AxisResult(
        status: _str(j['status']) ?? '',
        reasonCode: _str(j['reason_code']),
        rawScore: _num(j['raw_score']),
        lseC: _num(j['lse_c']),
        lseD: _num(j['lse_d']),
        includedInFusion: j['included_in_fusion'] is bool ? j['included_in_fusion'] as bool : null,
        modelVersion: _str(j['model_version']),
      );

  final String status;
  final String? reasonCode;
  final double? rawScore;
  final double? lseC;
  final double? lseD;
  final bool? includedInFusion;
  final String? modelVersion;
}

class Explanation {
  const Explanation({required this.templateId, required this.reasonCode, required this.message});

  final String templateId;
  final String reasonCode;
  final String message;
}

/// GET /analyses/{id}/result 의 200 응답.
class AnalysisResult {
  const AnalysisResult({
    required this.analysisId,
    required this.youtubeVideoId,
    required this.jobStatus,
    this.analysisStatus,
    this.verdictStatus,
    this.verdictLabel,
    this.overallScore,
    this.abstentionReason,
    this.reasonCode,
    this.mediaProvenance,
    this.coverage,
    this.axes = const {},
    this.explanations = const [],
    this.raw = const {},
  });

  factory AnalysisResult.fromJson(Map<String, dynamic> j) {
    final axes = j['axes'];
    return AnalysisResult(
      analysisId: _str(j['analysis_id']) ?? '',
      youtubeVideoId: _str(j['youtube_video_id']) ?? '',
      jobStatus: parseJobStatus(j['job_status']),
      analysisStatus: parseAnalysisStatus(j['analysis_status']),
      verdictStatus: parseVerdictStatus(j['verdict_status']),
      verdictLabel: parseVerdictLabel(j['verdict_label']),
      overallScore: _num(j['overall_score']),
      abstentionReason: _str(j['abstention_reason']),
      reasonCode: _str(j['reason_code']),
      mediaProvenance: _str(j['media_provenance']),
      coverage: j['coverage'] is Map ? Coverage.fromJson(Map<String, dynamic>.from(j['coverage'] as Map)) : null,
      axes: {
        if (axes is Map)
          for (final e in axes.entries)
            if (e.value is Map) e.key.toString(): AxisResult.fromJson(Map<String, dynamic>.from(e.value as Map)),
      },
      explanations: [
        for (final e in (j['explanations'] as List? ?? const []))
          if (e is Map)
            Explanation(
              templateId: _str(e['template_id']) ?? '',
              reasonCode: _str(e['reason_code']) ?? '',
              message: _str(e['message']) ?? '',
            ),
      ],
      raw: j,
    );
  }

  final String analysisId;
  final String youtubeVideoId;
  final JobStatus jobStatus;
  final AnalysisStatus? analysisStatus;
  final VerdictStatus? verdictStatus;
  final VerdictLabel? verdictLabel;

  /// 요약 화면에 쓰지 않는다. 라벨을 이 값으로 만들지 않는다.
  final double? overallScore;
  final String? abstentionReason;
  final String? reasonCode;
  final String? mediaProvenance;
  final Coverage? coverage;
  final Map<String, AxisResult> axes;
  final List<Explanation> explanations;

  /// 서버가 보낸 원문. 상세 화면에서 상태 값을 그대로 보여 줄 때 쓴다.
  final Map<String, dynamic> raw;

  String? rawString(String key) => raw[key] is String ? raw[key] as String : null;
}

/// GET /result 의 응답: 아직 끝나지 않았으면(202) pending, 끝났으면(200) result.
class ResultResponse {
  const ResultResponse.pending(JobState this.pending) : result = null;
  const ResultResponse.done(AnalysisResult this.result) : pending = null;

  final JobState? pending;
  final AnalysisResult? result;
}
