import 'dart:convert';

import 'package:flutter/services.dart';

import 'analysis_api.dart';
import 'models.dart';

typedef RecordingEntry = ({String filename, String label});
typedef _Frame = ({Duration at, JobState state});

class _Recording {
  const _Recording(this.label, this.frames, this.result);

  factory _Recording.parse(String contents) {
    final data = jsonDecode(contents) as Map<String, dynamic>;
    final label = data['label'] as String;
    if (data['schema'] != 1 ||
        data['source'] != 'real_run' ||
        label.trim().isEmpty) {
      throw const FormatException('녹화 형식 오류');
    }
    final frames = <_Frame>[];
    for (final item in data['status_sequence'] as List) {
      final seconds = item['after_sec'] as num;
      if (!seconds.isFinite || seconds < 0) {
        throw const FormatException('녹화 시각 오류');
      }
      final at = Duration(
        microseconds: (seconds * Duration.microsecondsPerSecond).round(),
      );
      final state = JobState.fromJson(item['body'] as Map<String, dynamic>);
      if (state.jobStatus == JobStatus.unknown ||
          (frames.isNotEmpty &&
              (frames.last.at > at || !frames.last.state.isActive))) {
        throw const FormatException('녹화 상태 오류');
      }
      frames.add((at: at, state: state));
    }
    final result = AnalysisResult.fromJson(
      data['result'] as Map<String, dynamic>,
    );
    if (frames.isEmpty ||
        frames.last.state.isActive ||
        frames.last.state.jobStatus != result.jobStatus ||
        result.analysisId != 'recorded-1') {
      throw const FormatException('녹화 결과 오류');
    }
    return _Recording(label, frames, result);
  }

  final String label;
  final List<_Frame> frames;
  final AnalysisResult result;
}

/// 앱에 포함된 실제 분석 기록을 상대 시간에 맞춰 재생한다.
class ReplayApi implements AnalysisApi {
  ReplayApi({
    Future<String> Function(String)? loadAsset,
    Duration Function()? now,
  }) : _loadAsset = loadAsset ?? rootBundle.loadString,
       _now = now ?? _monotonicClock();

  static Duration Function() _monotonicClock() {
    final clock = Stopwatch()..start();
    return () => clock.elapsed;
  }

  final Future<String> Function(String) _loadAsset;
  final Duration Function() _now;
  Future<Map<String, _Recording>>? _catalog;
  _Recording? _active;
  Duration _started = Duration.zero;
  int _next = 0;

  Future<Map<String, _Recording>> _load() async {
    final manifest =
        jsonDecode(await _loadAsset('assets/replay/index.json')) as List;
    final catalog = <String, _Recording>{};
    for (final name in manifest.cast<String>()) {
      if (!RegExp(r'^[a-zA-Z0-9_-]+\.json$').hasMatch(name) ||
          name == 'index.json' ||
          catalog.containsKey(name)) {
        throw const FormatException('녹화 목록 오류');
      }
      catalog[name] = _Recording.parse(await _loadAsset('assets/replay/$name'));
    }
    return catalog;
  }

  Future<List<RecordingEntry>> recordings() async {
    final catalog = await (_catalog ??= _load());
    return [
      for (final e in catalog.entries) (filename: e.key, label: e.value.label),
    ];
  }

  @override
  Future<CreatedAnalysis> create(String filename) async {
    final catalog = await (_catalog ??= _load());
    final recording = catalog[filename];
    if (recording == null) throw const ApiException(ApiErrorKind.notFound);
    _active = recording;
    _started = _now();
    _next = 0;
    final state = _current();
    return CreatedAnalysis(
      analysisId: recording.result.analysisId,
      youtubeVideoId: recording.result.youtubeVideoId,
      jobStatus: state.jobStatus,
    );
  }

  JobState _current() {
    final frames = _active!.frames;
    final elapsed = _now() - _started;
    while (_next < frames.length && frames[_next].at <= elapsed) {
      _next++;
    }
    return _next == 0
        ? const JobState(jobStatus: JobStatus.queued)
        : frames[_next - 1].state;
  }

  Duration get untilNextState {
    final frames = _active!.frames;
    if (_next == frames.length) return Duration.zero;
    final remaining = frames[_next].at - (_now() - _started);
    return remaining.isNegative ? Duration.zero : remaining;
  }

  void _requireActive(String analysisId) {
    if (_active == null || _active!.result.analysisId != analysisId) {
      throw const ApiException(ApiErrorKind.notFound);
    }
  }

  @override
  Future<JobState> status(String analysisId) async {
    _requireActive(analysisId);
    return _current();
  }

  @override
  Future<ResultResponse> result(String analysisId) async {
    final state = await status(analysisId);
    return state.isActive
        ? ResultResponse.pending(state)
        : ResultResponse.done(_active!.result);
  }

  @override
  Future<void> cancel(String analysisId) async {
    _requireActive(analysisId);
    _active = null;
  }
}
