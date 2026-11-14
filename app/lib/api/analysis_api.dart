import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

import 'models.dart';

/// 요청이 실패한 이유. HTTP 요청의 실패이며 분석 결과가 아니다.
enum ApiErrorKind { invalidUrl, queueFull, unauthorized, notFound, network, server }

class ApiException implements Exception {
  const ApiException(this.kind, {this.reasonCode, this.statusCode});

  final ApiErrorKind kind;
  final String? reasonCode;
  final int? statusCode;

  @override
  String toString() => 'ApiException(${kind.name}, $statusCode, $reasonCode)';
}

/// 서버와 주고받는 세 가지 호출. 파일 업로드는 없다. 입력은 YouTube URL 문자열뿐이다.
abstract interface class AnalysisApi {
  /// POST /api/v1/analyses
  Future<CreatedAnalysis> create(String url);

  /// GET /api/v1/analyses/{id}
  Future<JobState> status(String analysisId);

  /// GET /api/v1/analyses/{id}/result
  Future<ResultResponse> result(String analysisId);
}

/// 작업 소유권 확인용 임시 토큰. 메모리에만 둔다(정식 인증은 백로그 14번).
String generateClientToken([Random? random]) {
  final r = random ?? Random.secure();
  return List.generate(32, (_) => r.nextInt(16).toRadixString(16)).join();
}

class HttpAnalysisApi implements AnalysisApi {
  HttpAnalysisApi({required String baseUrl, http.Client? client, String? clientToken})
      : _base = Uri.parse(baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl),
        _client = client ?? http.Client(),
        _token = clientToken ?? generateClientToken();

  final Uri _base;
  final http.Client _client;
  final String _token;

  Uri _uri(String path) => _base.replace(path: '${_base.path}/api/v1/analyses$path');

  Map<String, String> get _headers => {'X-Client-Token': _token, 'Accept': 'application/json'};

  @override
  Future<CreatedAnalysis> create(String url) async {
    final res = await _send(() => _client.post(
          _uri(''),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode({'url': url}),
        ));
    if (res.statusCode != 202) throw _error(res);
    return CreatedAnalysis.fromJson(_json(res));
  }

  @override
  Future<JobState> status(String analysisId) async {
    final res = await _send(() => _client.get(_uri('/${Uri.encodeComponent(analysisId)}'), headers: _headers));
    if (res.statusCode != 200) throw _error(res);
    return JobState.fromJson(_json(res));
  }

  @override
  Future<ResultResponse> result(String analysisId) async {
    final res =
        await _send(() => _client.get(_uri('/${Uri.encodeComponent(analysisId)}/result'), headers: _headers));
    if (res.statusCode == 202) return ResultResponse.pending(JobState.fromJson(_json(res)));
    if (res.statusCode != 200) throw _error(res);
    return ResultResponse.done(AnalysisResult.fromJson(_json(res)));
  }

  Future<http.Response> _send(Future<http.Response> Function() call) async {
    try {
      return await call().timeout(const Duration(seconds: 15));
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
      429 || 503 => ApiErrorKind.queueFull,
      401 || 403 => ApiErrorKind.unauthorized,
      404 => ApiErrorKind.notFound,
      _ => ApiErrorKind.server,
    };
    return ApiException(kind, reasonCode: reason, statusCode: res.statusCode);
  }
}
