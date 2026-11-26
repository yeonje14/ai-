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

/// 단계 이름. 서버의 여덟 단계와 1:1이다. 모델 이름 대신 하는 일을 적는다.
const stageLabels = <String, String>{
  'validating': '주소 확인',
  'access_check': '분석 권한 확인',
  'preprocessing': '분석 구간 준비',
  'waverep': '영상 신호 확인',
  'motionphys': '움직임 확인',
  'syncnet': '입술·음성 확인',
  'fusion': '근거 종합',
  'finalizing': '결과 정리',
};

/// "이번 요청의 상태"에 쓰는 말. 작업·분석·판정은 서로 다른 상태다.
const jobStatusText = <JobStatus, String>{
  JobStatus.queued: '대기',
  JobStatus.processing: '진행 중',
  JobStatus.finished: '종료',
  JobStatus.failed: '실패',
  JobStatus.cancelled: '취소',
  JobStatus.unknown: '알 수 없음',
};

const analysisStatusLabel = <AnalysisStatus, String>{
  AnalysisStatus.completed: '완료',
  AnalysisStatus.partial: '부분 분석',
  AnalysisStatus.outOfScope: '범위 밖',
  AnalysisStatus.unsupported: '미지원',
  AnalysisStatus.insufficientQuality: '품질 부족',
  AnalysisStatus.analysisUnavailable: '분석 불가',
  AnalysisStatus.unknown: '알 수 없음',
};

/// 화면이 보여 주는 판정 상태. 화면 종류에서 정하므로 요약의 라벨과 어긋나지 않는다.
String verdictText(ScreenKind kind) => switch (kind) {
      ScreenKind.suspicious || ScreenKind.low => '판정함',
      ScreenKind.outOfScope => '해당 없음',
      ScreenKind.jobFailed => '없음',
      _ => '보류',
    };

const _reasonText = <String, String>{
  // 보류 원인 (docs/DESIGN.md §10)
  'insufficient_evidence': '판단할 근거가 충분하지 않습니다.',
  'unvalidated_condition': '검증되지 않은 조건의 영상입니다.',
  'no_valid_fusion_model': '검증된 종합 판정 모델이 없습니다.',
  'video_access_unavailable': '영상에 접근할 수 없습니다.',
  'download_blocked': 'YouTube가 영상 받기를 막아서 분석하지 못했습니다.',
  'video_removed': '삭제된 영상이라 찾을 수 없습니다.',
  'video_private': '비공개 영상이라 분석할 수 없습니다.',
  'age_restricted': '나이 제한이 있는 영상은 로그인 없이 받을 수 없어 분석하지 못했습니다.',
  'video_too_long': '영상이 길어서 분석하지 않았습니다. 30분 이하 영상만 분석합니다.',
  'live_not_supported': '실시간 방송은 분석하지 않습니다. 방송이 끝난 뒤 다시 보내 주세요.',
  'download_network_error': '인터넷 문제로 영상을 받지 못했습니다. 잠시 뒤 다시 시도해 주세요.',
  'no_suitable_format': '분석할 수 있는 형태의 영상(소리 포함)을 찾지 못했습니다.',
  'download_failed': '영상을 받는 중 문제가 생겨 분석하지 못했습니다.',
  'access_not_authorized': '분석이 허가된 미디어로 등록되지 않은 영상입니다.',
  'speaker_unconfirmed': '말하는 사람을 확인하지 못했습니다.',
  'media_unreadable': '허가된 영상 파일을 읽지 못해 분석하지 못했습니다.',
  'gate_error': '발화 구간을 확인하는 중 오류가 발생해 분석하지 못했습니다.',
  'gate_timeout': '정해진 시간 안에 발화 구간 확인을 마치지 못했습니다.',
  'no_speech_detected': '음성으로 감지된 구간이 없습니다.',
  'no_mouth_movement': '음성 구간에서 반복되는 입 움직임을 확인하지 못했습니다.',
  'no_face_detected': '음성 구간에서 분석할 주된 얼굴을 찾지 못했습니다.',
  'low_resolution': '영상 해상도가 발화 구간 분석 기준보다 낮습니다.',
  'face_too_small': '얼굴이 작아 분석할 구간을 확보하지 못했습니다.',
  'too_blurry': '얼굴 영역이 흐려 분석할 구간을 확보하지 못했습니다.',
  'segment_too_short': '분석할 발화 구간이 너무 짧습니다.',
  'mouth_unmeasurable': '얼굴이 작거나 가려져서 입 움직임을 잴 수 없었습니다. 그래서 판단을 보류합니다.',
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
  AnalysisStatus.unsupported: '현재 지원하지 않는 분석 조건입니다.',
  AnalysisStatus.insufficientQuality: '영상 품질이 분석하기에 부족합니다.',
};

/// 요청 실패(HTTP)의 안내 문구. 분석 결과가 아니다.
String apiErrorText(ApiException e) {
  if (e.retryAt case final deadline?) {
    final seconds = (deadline.difference(DateTime.now()).inMilliseconds / 1000).ceil();
    return '$seconds초 뒤에 다시 요청해 주세요.';
  }
  if (e.reasonCode == 'user_active_limit') return '진행 중인 작업이 있습니다. 내 작업에서 확인해 주세요.';
  if (e.reasonCode == 'retry_expired') return '재시도 기한이 지났습니다. 내 작업을 확인한 뒤 새 분석을 요청해 주세요.';
  final guidance = switch ((e.statusCode, e.reasonCode)) {
    (422, 'invalid_request') => '요청 형식에 문제가 있습니다. 입력 내용을 확인하고 다시 시도해 주세요.',
    (422, 'invalid_idempotency_key') => '접수 번호가 올바르지 않습니다. 내 작업에서 새 분석을 시작해 주세요.',
    (422, 'invalid_cursor') => '목록의 다음 페이지를 열 수 없습니다. 목록 다시 조회를 눌러 처음부터 확인해 주세요.',
    (409, 'idempotency_conflict') => '이 접수 번호는 다른 영상에 사용됐습니다. 내 작업을 확인한 뒤 새 분석을 시작해 주세요.',
    (410, 'analysis_deleted') => '이미 삭제된 작업입니다. 다시 확인하려면 내 작업에서 새 분석을 시작해 주세요.',
    (503, 'temporarily_unavailable') => '서버가 사용 중입니다. 잠시 뒤 다시 시도해 주세요.',
    _ => null,
  };
  if (guidance != null) return guidance;
  return switch (e.kind) {
      ApiErrorKind.invalidUrl => 'YouTube 영상 주소가 아닙니다. youtube.com 또는 youtu.be 주소를 넣어 주세요.',
      ApiErrorKind.queueFull => '지금은 대기 중인 분석이 많습니다. 잠시 뒤에 다시 요청해 주세요.',
      ApiErrorKind.unauthorized => '요청을 확인할 수 없습니다. 앱을 다시 열고 시도해 주세요.',
      ApiErrorKind.notFound => '요청한 분석을 찾을 수 없습니다.',
      ApiErrorKind.network => '서버에 연결하지 못했습니다. 연결 상태를 확인해 주세요.',
      ApiErrorKind.server => '서버에서 요청을 처리하지 못했습니다.',
    };
}

/// 초 → "1분 5초". 소수점 아래는 버린다.
String formatDuration(double seconds) {
  final total = seconds.floor();
  final m = total ~/ 60, s = total % 60;
  if (m == 0) return '$s초';
  return '$m분 $s초';
}

/// 초 → "4:32". 막대 끝의 시각 표시에 쓴다.
String formatClock(double seconds) {
  final total = seconds.floor();
  return '${total ~/ 60}:${(total % 60).toString().padLeft(2, '0')}';
}

/// 분석 범위 문구. 값이 없으면 없다고 말한다.
String coverageCaption(Coverage? c) {
  final total = c?.videoDurationSec, done = c?.analyzedDurationSec;
  if (total == null || done == null) return '분석한 구간이 기록되지 않았습니다.';
  return '영상 ${formatDuration(total)} 가운데 ${formatDuration(done)}를 분석했습니다.';
}

/// 원시 지표 값. null은 "값 없음"이다. 0으로 바꾸지 않는다.
String metricText(double? v) => v == null ? '값 없음' : v.toStringAsFixed(2);
