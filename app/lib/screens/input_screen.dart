import 'package:flutter/material.dart';

import '../api/mock_api.dart';
import '../design/tokens.dart';
import '../design/widgets.dart';

/// 화면 1: YouTube 주소 입력. 파일 선택·업로드는 없다.
class InputScreen extends StatefulWidget {
  const InputScreen({
    super.key,
    required this.onSubmit,
    this.busy = false,
    this.errorText,
    this.mockScenario,
    this.onMockScenarioChanged,
  });

  final ValueChanged<String> onSubmit;
  final bool busy;

  /// 요청 실패 안내(HTTP 422·429·연결 실패 등). 분석 결과가 아니다.
  final String? errorText;

  /// mock 모드일 때만 값이 있다. 시나리오 고르기를 보여 준다.
  final MockScenario? mockScenario;
  final ValueChanged<MockScenario>? onMockScenarioChanged;

  @override
  State<InputScreen> createState() => _InputScreenState();
}

class _InputScreenState extends State<InputScreen> {
  final _controller = TextEditingController();
  String? _localError;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    final url = _controller.text.trim();
    if (url.isEmpty) {
      setState(() => _localError = 'YouTube 영상 주소를 넣어 주세요.');
      return;
    }
    setState(() => _localError = null);
    widget.onSubmit(url); // 주소 검증은 서버가 한다
  }

  @override
  Widget build(BuildContext context) {
    final error = _localError ?? widget.errorText;
    return TrinityScaffold(
      children: [
        Semantics(header: true, child: Text('TRINITY', style: TText.display)),
        const SizedBox(height: TSpace.x2),
        Text('말하는 사람이 나오는 YouTube 영상에서 AI 생성·조작 의심 신호를 살펴봅니다.', style: TText.body),
        const SizedBox(height: TSpace.x4),
        TextField(
          controller: _controller,
          enabled: !widget.busy,
          keyboardType: TextInputType.url,
          autocorrect: false,
          style: TText.body,
          minLines: 1,
          maxLines: 3,
          decoration: InputDecoration(
            labelText: 'YouTube 영상 주소',
            hintText: 'https://www.youtube.com/watch?v=…',
            errorText: error,
          ),
          onSubmitted: (_) => _submit(),
        ),
        const SizedBox(height: TSpace.x3),
        PrimaryButton(label: widget.busy ? '요청하는 중…' : '분석 요청', onPressed: widget.busy ? null : _submit),
        if (widget.mockScenario != null) ...[
          const SectionTitle('가상 결과 고르기'),
          Text('mock 모드입니다. 서버에 연결하지 않고 아래에서 고른 가상의 결과를 보여 줍니다.', style: TText.secondary),
          const SizedBox(height: TSpace.x2),
          for (final s in MockScenario.values)
            _ScenarioOption(
              scenario: s,
              selected: s == widget.mockScenario,
              onTap: widget.busy ? null : () => widget.onMockScenarioChanged?.call(s),
            ),
        ],
        const SizedBox(height: TSpace.x4),
        const InfoBox(
          title: '알아 두세요',
          body: '영상 파일은 받지 않습니다. YouTube 주소만 입력할 수 있습니다.\n'
              '분석이 허가된 영상만 분석합니다. 그 밖의 영상은 분석하지 않고 그 이유를 알려 드립니다.\n'
              '이 서비스는 영상 내용이 사실인지 확인하지 않습니다.',
        ),
      ],
    );
  }
}

class _ScenarioOption extends StatelessWidget {
  const _ScenarioOption({required this.scenario, required this.selected, required this.onTap});

  final MockScenario scenario;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      inMutuallyExclusiveGroup: true,
      checked: selected,
      button: true,
      label: scenario.label,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: onTap,
          child: Container(
            constraints: const BoxConstraints(minHeight: TSize.touch),
            decoration: BoxDecoration(
              color: selected ? TColors.surface : null,
              border: const Border(bottom: BorderSide(color: TColors.border)),
            ),
            padding: const EdgeInsets.symmetric(horizontal: TSpace.x2, vertical: TSpace.x2),
            child: Row(
              children: [
                Container(
                  width: 14,
                  height: 14,
                  decoration: BoxDecoration(
                    color: selected ? TColors.text : null,
                    border: Border.all(color: TColors.text),
                  ),
                ),
                const SizedBox(width: TSpace.x3),
                Expanded(child: Text(scenario.label, style: selected ? TText.bodyStrong : TText.body)),
                if (selected) Text('선택됨', style: TText.secondary.copyWith(color: TColors.text)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
