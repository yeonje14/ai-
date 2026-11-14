/// 서버 응답의 상태 → 화면과 문구 대응. 화면 코드는 여기 정한 대응만 쓴다.
library;

import 'api/analysis_api.dart';
import 'api/models.dart';

/// 작업이 끝난 뒤 보여 줄 화면.
enum ScreenKind { suspicious, low, abstained, unavailable, outOfScope, jobFailed }

/// 결과 → 화면.
///
/// - 작업 종료(job_status) ≠ 분석 완료(analysis_status) ≠ 판정(verdict_status)이므로 순서대로 본다.
/// - 발견·낮음은 서버가 준 verdict_label로만 정한다. overall_score를 보지 않는다.
/// - [allowVerdictLabels]가 false면(실제 서버 모드, 모델 미연결) 라벨이 와도 판단 보류로 둔다.
/// - 모르는 조합은 판단 보류다.
ScreenKind resolveScreen(AnalysisResult r, {required bool allowVerdictLabels}) {
  if (r.jobStatus != JobStatus.finished) return ScreenKind.jobFailed;
  switch (r.analysisStatus) {
    case AnalysisStatus.analysisUnavailable:
      return ScreenKind.unavailable;
    case AnalysisStatus.outOfScope:
    case AnalysisStatus.unsupported:
    case AnalysisStatus.insufficientQuality:
      return ScreenKind.outOfScope;
    default:
      break;
  }
  if (allowVerdictLabels && r.verdictStatus == VerdictStatus.assessed) {
    switch (r.verdictLabel) {
      case VerdictLabel.suspiciousSignals:
        return ScreenKind.suspicious;
      case VerdictLabel.lowSuspicion:
        return ScreenKind.low;
      case null:
        break;
    }
  }
  return ScreenKind.abstained;
}

const stageLabels = <String, String>{
  'validating': '주소 확인',
  'access_check': '영상 접근 권한 확인',
  'preprocessing': '발화 구간 준비',
  'waverep': '신호 분석 (WaveRep)',
  'motionphys': '움직임 분석 (MotionPhys)',
  'syncnet': '입술·음성 동기화 측정 (SyncNet)',
  'fusion': '결과 종합',
  'finalizing': '마무리',
};

const _reasonText = <String, String>{
  // 보류 원인 (README §10)
  'insufficient_evidence': '판단할 근거가 충분하지 않습니다.',
  'unvalidated_condition': '검증되지 않은 조건의 영상입니다.',
  'no_valid_fusion_model': '검증된 종합 판정 모델이 없습니다.',
  'video_access_unavailable': '영상에 접근할 수 없습니다.',
  'access_not_authorized': '분석이 허가된 미디어로 등록되지 않은 영상입니다.',
  'speaker_unconfirmed': '말하는 사람을 확인하지 못했습니다.',
  // 축별 세부 원인
  'tracking_failed': '추적에 실패했습니다.',
  'insufficient_motion': '움직임이 부족합니다.',
  'occluded_mouth': '입이 가려져 있습니다.',
  'audio_missing': '음성이 없습니다.',
  'inference_error': '모델 실행 중 오류가 났습니다.',
  // 작업 실패 원인
  'timeout': '정해진 시간 안에 끝나지 않았습니다.',
  'worker_error': '분석 프로세스에서 오류가 났습니다.',
  'max_attempts_exceeded': '여러 번 시도했지만 끝내지 못했습니다.',
};

/// 원인 코드의 설명. 모르는 코드는 꾸며 내지 않고 null을 돌려준다.
String? reasonText(String? code) => _reasonText[code];

const axisStatusText = <String, String>{
  'completed': '측정됨',
  'insufficient_input': '입력 부족',
  'unsupported_input': '지원하지 않는 입력',
  'out_of_distribution': '검증 범위 밖',
  'error': '오류',
};

const analysisStatusText = <AnalysisStatus, String>{
  AnalysisStatus.outOfScope: '이 영상은 분석 범위(말하는 사람이 나오는 영상) 밖입니다.',
  AnalysisStatus.unsupported: '지원하지 않는 형식의 영상입니다.',
  AnalysisStatus.insufficientQuality: '영상 품질이 분석하기에 부족합니다.',
};

/// 요청 실패(HTTP)의 안내 문구. 분석 결과가 아니다.
String apiErrorText(ApiException e) => switch (e.kind) {
      ApiErrorKind.invalidUrl => 'YouTube 영상 주소가 아닙니다. youtube.com 또는 youtu.be 주소를 넣어 주세요.',
      ApiErrorKind.queueFull => '지금은 대기 중인 분석이 많습니다. 잠시 뒤에 다시 요청해 주세요.',
      ApiErrorKind.unauthorized => '요청을 확인할 수 없습니다. 앱을 다시 열고 시도해 주세요.',
      ApiErrorKind.notFound => '요청한 분석을 찾을 수 없습니다.',
      ApiErrorKind.network => '서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요.',
      ApiErrorKind.server => '서버에서 요청을 처리하지 못했습니다.',
    };

/// 초 → "1분 5초". 소수점 아래는 버린다.
String formatDuration(double seconds) {
  final total = seconds.floor();
  final m = total ~/ 60, s = total % 60;
  if (m == 0) return '$s초';
  return '$m분 $s초';
}

/// 분석 범위 문구. 값이 없으면 없다고 말한다.
String coverageCaption(Coverage? c) {
  final total = c?.videoDurationSec, done = c?.analyzedDurationSec;
  if (total == null || done == null) return '분석 범위 정보가 없습니다.';
  return '영상 ${formatDuration(total)} 가운데 ${formatDuration(done)}를 분석했습니다.';
}

/// 원시 지표 값. null은 "값 없음"이다. 0으로 바꾸지 않는다.
String metricText(double? v) => v == null ? '값 없음' : v.toStringAsFixed(2);
