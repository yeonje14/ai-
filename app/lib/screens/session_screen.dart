import 'package:flutter/material.dart';

import '../api/analysis_api.dart';
import '../view_state.dart';

/// 서버 모드의 세션 경계. 키 만료 시 기존 분석 화면과 폴링 타이머도 폐기한다.
class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key, required this.api, required this.flow});
  final HttpAnalysisApi api;
  final Widget Function(String? id, VoidCallback back) flow;

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  final _keyField = TextEditingController();
  final _jobs = <JobEntry>[];
  String? _cursor;
  String? _selected;
  String? _error;
  bool _authenticated = false;
  bool _inFlow = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    widget.api.onUnauthorized = _expired;
  }

  void _expired() {
    if (!mounted) return;
    _keyField.clear();
    setState(() {
      _authenticated = false;
      _inFlow = false;
      _busy = false;
      _selected = null;
      _cursor = null;
      _jobs.clear();
      _error = '키를 확인하고 다시 인증해 주세요.';
    });
  }

  @override
  void dispose() {
    widget.api.onUnauthorized = null;
    widget.api.setCredential(null);
    _keyField.dispose();
    super.dispose();
  }

  Future<void> _load({bool more = false}) async {
    if (_busy) return;
    if (!_authenticated) {
      final key = _keyField.text.trim();
      if (key.isEmpty) return;
      widget.api.setCredential(key);
    }
    setState(() { _busy = true; _error = null; });
    try {
      final page = await widget.api.jobs(more ? _cursor : null);
      if (!mounted) return;
      _keyField.clear();
      setState(() {
        _authenticated = true;
        if (!more) _jobs.clear();
        _jobs.addAll(page.items);
        _cursor = page.cursor;
      });
    } on ApiException catch (e) {
      if (mounted && e.kind != ApiErrorKind.unauthorized) setState(() => _error = apiErrorText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _open(String? id) {
    widget.api.clearSubmission();
    setState(() { _inFlow = true; _selected = id; });
  }

  @override
  Widget build(BuildContext context) {
    if (_inFlow) {
      return widget.flow(_selected, () {
        setState(() => _inFlow = false);
        _load();
      });
    }
    return Scaffold(
      appBar: AppBar(title: Text(_authenticated ? '내 작업' : 'TRINITY 로그인')),
      body: Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 600),
        child: ListView(padding: const EdgeInsets.all(24), children: [
          if (!_authenticated) ...[
            TextField(controller: _keyField, obscureText: true, autocorrect: false,
              enableSuggestions: false, enabled: !_busy,
              decoration: const InputDecoration(labelText: '운영자가 발급한 키'),
              onSubmitted: (_) => _load()),
            FilledButton(onPressed: _busy ? null : () => _load(), child: const Text('인증')),
          ] else ...[
            FilledButton(onPressed: _busy ? null : () => _open(null), child: const Text('새 분석')),
            if (_jobs.isEmpty && !_busy) const Text('접수한 작업이 없습니다.'),
            for (final job in _jobs)
              ListTile(title: Text(job.id), subtitle: Text('${job.created.toLocal().toString().substring(0, 16)} · ${jobStatusText[job.status]}'),
                onTap: _busy ? null : () => _open(job.id)),
            if (_cursor != null)
              TextButton(onPressed: _busy ? null : () => _load(more: true), child: const Text('이전 작업 더 보기')),
            if (_error != null)
              TextButton(onPressed: _busy ? null : () => _load(), child: const Text('목록 다시 조회')),
          ],
          if (_error != null) Text(_error!),
        ]),
      )),
    );
  }
}
