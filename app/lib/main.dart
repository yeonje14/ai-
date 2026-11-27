import 'package:flutter/material.dart';

import 'api/analysis_api.dart';
import 'api/mock_api.dart';
import 'api/replay_api.dart';
import 'app.dart';
import 'config.dart';

void main() {
  final config = AppConfig.fromEnvironment();
  final AnalysisApi api = switch (config.mode) {
    ApiMode.replay => ReplayApi(),
    ApiMode.mock => MockAnalysisApi(),
    ApiMode.server => HttpAnalysisApi(baseUrl: config.baseUrl),
  };
  runApp(TrinityApp(config: config, api: api));
}
