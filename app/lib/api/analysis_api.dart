import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

import 'models.dart';

/// 요청이 실패한 이유. HTTP 요청의 실패이며 분석 결과가 아니다.
enum ApiErrorKind { invalidUrl, queueFull, unauthorized, notFound, network, server }

class ApiException implements Exception {
  const ApiException(this.kind, {this.reasonCode, this.statusCode, this.retryAt});

  final ApiErrorKind kind;
  final String? reasonCode;
  final int? statusCode;
  final DateTime? retryAt;

  @override
  String toString() => 'ApiException(${kind.name}, $statusCode, $reasonCode)';
}

/// 서버와 주고받는 호출. 파일 업로드는 없다. 입력은 YouTube URL 문자열뿐이다.
abstract interface class AnalysisApi {
  /// POST /api/v1/analyses
  Future<CreatedAnalysis> create(String url);

  /// GET /api/v1/analyses/{id}
  Future<JobState> status(String analysisId);

  /// GET /api/v1/analyses/{id}/result
  Future<ResultResponse> result(String analysisId);

  /// 진행 중 상태의 ETag로 조건부 DELETE. 종료됐거나 412면 삭제 없이 반환한다.
  /// 호출자는 상태·결과를 다시 조회한다. 일반 DELETE/기록 삭제 기능은 제공하지 않는다.
  Future<void> cancel(String analysisId);
}

/// 사용자 동작 하나를 나타내는 무작위 UUID v4.
String newSubmissionKey() {
  final random = Random.secure();
  final bytes = List.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  final hex = bytes.map((v) => v.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-'
      '${hex.substring(16, 20)}-${hex.substring(20)}';
}

typedef JobEntry = ({String id, JobStatus status, DateTime created});
typedef JobPage = ({List<JobEntry> items, String? cursor});

class HttpAnalysisApi implements AnalysisApi {
  HttpAnalysisApi({required String baseUrl, http.Client? client, String? bearerKey})
      : _base = Uri.parse(baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl),
        _client = client ?? http.Client(), _token = bearerKey;

  final Uri _base;
  final http.Client _client;
  String? _token;
  void Function()? onUnauthorized;
  int _session = 0;
  String? _pendingUrl;
  String? _pendingKey;
  DateTime? _pendingSince;
  DateTime? _retryAt;
  DateTime? _submitAt;

  void setCredential(String? value) {
    _session++;
    _token = value;
    clearSubmission();
  }

  void clearSubmission() {
    _pendingUrl = null;
    _pendingKey = null;
    _pendingSince = null;
  }

  Future<JobPage> jobs([String? cursor]) async {
    final uri = _uri('').replace(queryParameters: cursor == null ? null : {'cursor': cursor});
    final res = await _send(() => _client.get(uri, headers: _headers));
    if (res.statusCode != 200) throw _error(res);
    final body = _json(res);
    final items = (body['items'] as List).map((item) => (
      id: item['analysis_id'] as String, status: parseJobStatus(item['job_status']),
      created: DateTime.fromMillisecondsSinceEpoch(((item['created_at'] as num) * 1000).round()),
    )).toList();
    return (items: items, cursor: body['next_cursor'] as String?);
  }

  Uri _uri(String path) => _base.replace(path: '${_base.path}/api/v1/analyses$path');

  Map<String, String> get _headers => {'Authorization': 'Bearer $_token', 'Accept': 'application/json'};

  @override
  Future<CreatedAnalysis> create(String url) async {
    final now = DateTime.now();
    if (_pendingUrl == url && now.difference(_pendingSince!) >= const Duration(hours: 24)) {
      throw const ApiException(ApiErrorKind.server, reasonCode: 'retry_expired');
    }
    if (_pendingUrl != url) {
      _pendingUrl = url;
      _pendingKey = newSubmissionKey();
      _pendingSince = now;
    }
    final res = await _send(() => _client.post(
          _uri(''),
          headers: {..._headers, 'Content-Type': 'application/json', 'Idempotency-Key': _pendingKey!},
          body: jsonEncode({'url': url}),
        ), submitting: true);
    if (res.statusCode != 202) throw _error(res);
    final created = CreatedAnalysis.fromJson(_json(res));
    clearSubmission();
    return created;
  }

  @override
  Future<JobState> status(String analysisId) async {
    final res = await _send(() => _client.get(_uri('/${Uri.encodeComponent(analysisId)}'), headers: _headers));
    if (res.statusCode != 200) throw _error(res);
    return JobState.fromJson(_json(res), etag: res.headers['etag']);
  }

  @override
  Future<ResultResponse> result(String analysisId) async {
    final res =
        await _send(() => _client.get(_uri('/${Uri.encodeComponent(analysisId)}/result'), headers: _headers));
    if (res.statusCode == 202) return ResultResponse.pending(JobState.fromJson(_json(res)));
    if (res.statusCode != 200) throw _error(res);
    return ResultResponse.done(AnalysisResult.fromJson(_json(res)));
  }

  @override
  Future<void> cancel(String analysisId) async {
    final job = await status(analysisId);
    if (!job.isActive) return;
    final etag = job.etag;
    // ETag 누락 시 일반 DELETE로 대체하지 않는다. 기록이 지워질 수 있다.
    if (etag == null || etag.isEmpty || etag.startsWith('W/')) {
      throw const ApiException(ApiErrorKind.server);
    }
    final res = await _send(() => _client.delete(
          _uri('/${Uri.encodeComponent(analysisId)}'),
          headers: {..._headers, 'If-Match': etag},
        ));
    if (res.statusCode != 202 && res.statusCode != 412) throw _error(res);
  }

  Future<http.Response> _send(Future<http.Response> Function() call, {bool submitting = false}) async {
    if (_token == null) throw const ApiException(ApiErrorKind.unauthorized);
    final session = _session;
    final now = DateTime.now();
    for (final deadline in [_retryAt, if (submitting) _submitAt]) {
      if (deadline != null && now.isBefore(deadline)) {
        throw ApiException(ApiErrorKind.queueFull, retryAt: deadline);
      }
    }
    try {
      final response = await call().timeout(const Duration(seconds: 15));
      if (_session != session) throw const ApiException(ApiErrorKind.unauthorized);
      if (response.statusCode == 401) {
        setCredential(null);
        onUnauthorized?.call();
      }
      return response;
    } on ApiException {
      rethrow;
    } catch (_) {
      // 연결 실패·시간 초과. 원인 문자열에는 주소가 들어갈 수 있어 담지 않는다.
      throw const ApiException(ApiErrorKind.network);
    }
  }

  Map<String, dynamic> _json(http.Response res) {
    try {
      return Map<String, dynamic>.from(jsonDecode(utf8.decode(res.bodyBytes)) as Map);
    } catch (_) {
      throw ApiException(ApiErrorKind.server, statusCode: res.statusCode);
    }
  }

  ApiException _error(http.Response res) {
    String? reason;
    try {
      final detail = (jsonDecode(utf8.decode(res.bodyBytes)) as Map)['detail'];
      if (detail is Map && detail['reason_code'] is String) reason = detail['reason_code'] as String;
    } catch (_) {}
    final kind = switch (res.statusCode) {
      422 => ApiErrorKind.invalidUrl,
      429 => ApiErrorKind.queueFull,
      401 || 403 => ApiErrorKind.unauthorized,
      404 => ApiErrorKind.notFound,
      _ => ApiErrorKind.server,
    };
    DateTime? retryAt;
    final seconds = int.tryParse(res.headers['retry-after'] ?? '');
    if (res.statusCode == 429 && seconds != null && seconds > 0) {
      retryAt = DateTime.now().add(Duration(seconds: seconds));
      if (reason == 'user_submission_limit') {
        _submitAt = retryAt;
      } else {
        _retryAt = retryAt;
      }
    }
    return ApiException(kind, reasonCode: reason, statusCode: res.statusCode, retryAt: retryAt);
  }
}
