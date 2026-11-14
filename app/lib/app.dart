import 'dart:async';

import 'package:flutter/material.dart';

import 'api/analysis_api.dart';
import 'api/mock_api.dart';
import 'api/models.dart';
import 'config.dart';
import 'design/theme.dart';
import 'screens/detail_screen.dart';
import 'screens/input_screen.dart';
import 'screens/progress_screen.dart';
import 'screens/result_screen.dart';
import 'view_state.dart';

class TrinityApp extends StatelessWidget {
  const TrinityApp({super.key, required this.config, required this.api});

  final AppConfig config;
  final AnalysisApi api;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TRINITY',
      debugShowCheckedModeBanner: false,
      theme: buildTrinityTheme(),
      home: AnalysisFlow(config: config, api: api),
    );
  }
}

enum _Phase { input, progress, result, detail }

/// 입력 → 분석 중(상태 조회 반복) → 결과 → 상세.
class AnalysisFlow extends StatefulWidget {
  const AnalysisFlow({super.key, required this.config, required this.api});

  final AppConfig config;
  final AnalysisApi api;

  @override
  State<AnalysisFlow> createState() => _AnalysisFlowState();
}

class _AnalysisFlowState extends State<AnalysisFlow> {
  _Phase _phase = _Phase.input;
  bool _busy = false;
  String? _inputError;
  String? _analysisId;
  JobState _job = const JobState(jobStatus: JobStatus.queued);
  bool _connectionLost = false;
  AnalysisResult? _result;
  Timer? _timer;
  bool _polling = false;

  MockAnalysisApi? get _mock => widget.api is MockAnalysisApi ? widget.api as MockAnalysisApi : null;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _submit(String url) async {
    setState(() {
      _busy = true;
      _inputError = null;
    });
    try {
      final created = await widget.api.create(url);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _analysisId = created.analysisId;
        _job = JobState(jobStatus: created.jobStatus);
        _connectionLost = false;
        _result = null;
        _phase = _Phase.progress;
      });
      _timer?.cancel();
      _timer = Timer.periodic(widget.config.pollInterval, (_) => _poll());
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _inputError = apiErrorText(e);
      });
    }
  }

  Future<void> _poll() async {
    final id = _analysisId;
    if (_polling || id == null) return;
    _polling = true;
    try {
      final job = await widget.api.status(id);
      if (!mounted || id != _analysisId) return;
      if (job.isActive) {
        setState(() {
          _job = job;
          _connectionLost = false;
        });
        return;
      }
      // 작업이 끝났다(finished·failed·cancelled). 결과를 받아 화면을 정한다.
      final res = await widget.api.result(id);
      if (!mounted || id != _analysisId) return;
      final result = res.result;
      if (result == null) {
        setState(() => _job = res.pending ?? job); // 아직 202면 다음 주기에 다시 본다
        return;
      }
      _timer?.cancel();
      setState(() {
        _job = job;
        _connectionLost = false;
        _result = result;
        _phase = result.jobStatus == JobStatus.finished ? _Phase.result : _Phase.progress;
      });
    } on ApiException catch (e) {
      if (!mounted || id != _analysisId) return;
      if (e.kind == ApiErrorKind.network || e.kind == ApiErrorKind.server) {
        setState(() => _connectionLost = true); // 다음 주기에 다시 조회한다
      } else {
        _timer?.cancel();
        setState(() {
          _phase = _Phase.input;
          _inputError = apiErrorText(e);
        });
      }
    } finally {
      _polling = false;
    }
  }

  void _restart() {
    _timer?.cancel();
    setState(() {
      _phase = _Phase.input;
      _analysisId = null;
      _result = null;
      _inputError = null;
      _busy = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final result = _result;
    switch (_phase) {
      case _Phase.input:
        return InputScreen(
          onSubmit: _submit,
          busy: _busy,
          errorText: _inputError,
          mockScenario: _mock?.scenario,
          onMockScenarioChanged: (s) => setState(() => _mock!.scenario = s),
        );
      case _Phase.progress:
        return ProgressScreen(
          state: _job,
          connectionLost: _connectionLost,
          failureReasonCode: result?.reasonCode,
          onRestart: _restart,
        );
      case _Phase.detail:
        return DetailScreen(result: result!, onBack: () => setState(() => _phase = _Phase.result));
      case _Phase.result:
        void detail() => setState(() => _phase = _Phase.detail);
        final kind = resolveScreen(result!, allowVerdictLabels: widget.config.allowVerdictLabels);
        return switch (kind) {
          ScreenKind.unavailable => UnavailableScreen(result: result, onShowDetail: detail, onRestart: _restart),
          ScreenKind.outOfScope => OutOfScopeScreen(result: result, onShowDetail: detail, onRestart: _restart),
          ScreenKind.jobFailed => ProgressScreen(
              state: _job,
              failureReasonCode: result.reasonCode,
              onRestart: _restart,
            ),
          _ => ResultScreen(kind: kind, result: result, onShowDetail: detail, onRestart: _restart),
        };
    }
  }
}
