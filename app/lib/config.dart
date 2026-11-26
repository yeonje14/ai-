enum ApiMode { mock, server, replay }

/// 실행 설정. `--dart-define`으로 바꾼다 (app/README.md).
///
///   TRINITY_API_MODE      mock(기본) | server | replay
///   TRINITY_API_BASE_URL  server 모드의 서버 주소 (기본 http://localhost:8000)
class AppConfig {
  const AppConfig({
    this.mode = ApiMode.mock,
    this.baseUrl = defaultBaseUrl,
    this.pollInterval = const Duration(seconds: 1),
  });

  factory AppConfig.fromEnvironment() {
    const mode = String.fromEnvironment('TRINITY_API_MODE', defaultValue: 'mock');
    const baseUrl = String.fromEnvironment('TRINITY_API_BASE_URL', defaultValue: defaultBaseUrl);
    final selected = ApiMode.values.byName(mode);
    return AppConfig(mode: selected, baseUrl: baseUrl);
  }

  static const defaultBaseUrl = 'http://localhost:8000';

  final ApiMode mode;
  final String baseUrl;
  final Duration pollInterval;

  /// 발견·낮음 라벨은 mock 모드에서만 보여 준다. 실제 서버에는 검증된 결합 모델이 없다.
  bool get allowVerdictLabels => mode == ApiMode.mock;
}
