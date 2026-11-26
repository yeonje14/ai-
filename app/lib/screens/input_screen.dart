import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/mock_api.dart';
import '../design/tokens.dart';
import '../design/widgets.dart';

/// 화면 1: 홈. YouTube 주소 입력. 파일 선택·업로드는 없다.
///
/// 넓은 화면(768 초과)은 검색형(가운데 워드마크와 캡슐 입력창), 좁은 화면은 앱형(세로 배치)이다.
class InputScreen extends StatefulWidget {
  const InputScreen({
    super.key,
    required this.onSubmit,
    this.busy = false,
    this.errorText,
    this.onJobs,
    this.mockScenario,
    this.onMockScenarioChanged,
  });

  final ValueChanged<String> onSubmit;
  final bool busy;
  final VoidCallback? onJobs;

  /// 요청 실패 안내(HTTP 422·429·연결 실패 등). 분석 결과가 아니다.
  final String? errorText;

  /// mock 모드일 때만 값이 있다. "예시로 둘러보기"와 가상 결과 고르기를 보여 준다.
  final MockScenario? mockScenario;
  final ValueChanged<MockScenario>? onMockScenarioChanged;

  static const tagline = '영상 속 단서,\n차분히 확인하세요.';
  static const lead = '말하는 사람이 나오는 YouTube 영상에서 AI 생성·조작 의심 신호를 살펴봅니다.';
  static const submitLabel = '확인하기';
  static const exampleLabel = '예시로 둘러보기';
  /// mock 모드의 예시 주소. 실제 영상이 아니다.
  static const exampleUrl = 'https://youtu.be/TRINITYdemo';

  @override
  State<InputScreen> createState() => _InputScreenState();
}

class _InputScreenState extends State<InputScreen> {
  final _controller = TextEditingController();
  String? _localError;
  String? _pasteHint;
  final _fieldFocus = FocusNode();

  @override
  void dispose() {
    _fieldFocus.dispose();
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

  void _example() {
    _controller.text = InputScreen.exampleUrl;
    _submit();
  }

  bool get _mock => widget.mockScenario != null;

  Future<void> _paste() async {
    String? text;
    try {
      text = (await Clipboard.getData(Clipboard.kTextPlain))?.text;
    } catch (_) {
      // 브라우저·운영체제에서 읽기를 허용하지 않으면 입력란의 기본 붙여넣기를 쓴다.
    }
    if (!mounted || widget.busy) return;
    if (text == null || text.trim().isEmpty) {
      setState(() => _pasteHint = '주소 칸을 길게 눌러 붙여넣거나 키보드의 붙여넣기를 사용해 주세요.');
      _fieldFocus.requestFocus();
      return;
    }
    _controller.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
    setState(() { _localError = null; _pasteHint = null; });
  }

  Widget _field(BuildContext context) => Semantics(
    label: 'YouTube 영상 주소',
    child: TextField(
      controller: _controller,
      focusNode: _fieldFocus,
      enabled: !widget.busy,
      keyboardType: TextInputType.url,
      textInputAction: TextInputAction.done,
      autocorrect: false,
      maxLength: null,
      minLines: 1,
      maxLines: 3,
      style: TText.body.copyWith(color: context.palette.ink),
      decoration: InputDecoration(
        hintText: 'https://youtu.be/…',
        prefixIcon: const Icon(Icons.link_rounded),
        errorText: _localError ?? widget.errorText,
      ),
      onSubmitted: (_) => _submit(),
    ),
  );

  Widget _lenses(BuildContext context, bool wide) {
    final items = [
      ('얼굴 화질 신호', '얼굴 영상의 각 프레임에서 생성·조작과 관련된 특징을 살펴봅니다.'),
      ('움직임', '화면에서 여러 점을 추적해 움직임의 변화를 살펴봅니다.'),
      ('입과 소리', '입술의 움직임과 목소리가 같은 시점에 나타나는지 살펴봅니다.'),
    ];
    final cards = [for (final (title, body) in items) Panel(child: Column(
      crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(width: 30, height: 3, decoration: const BoxDecoration(
          gradient: LinearGradient(colors: [Color(0xFF7C4DFF), Color(0xFF3D7BFF)]))),
        const SizedBox(height: TSpace.x3),
        Text(title, style: TText.h3.copyWith(color: context.palette.ink)),
        const SizedBox(height: TSpace.x2),
        Text(body, style: TText.secondary.copyWith(color: context.palette.muted)),
      ],
    ))];
    if (wide) {
      return Row(crossAxisAlignment: CrossAxisAlignment.start, spacing: TSpace.x3,
      children: [for (final card in cards) Expanded(child: card)]);
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, spacing: TSpace.x3, children: cards);
  }

  Widget _scenarios(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'mock 모드입니다. 서버에 연결하지 않고 아래에서 고른 가상의 결과를 보여 줍니다.',
            style: TText.small.copyWith(color: context.palette.muted),
          ),
          const SizedBox(height: TSpace.x2),
          for (final s in MockScenario.values)
            _ScenarioOption(
              scenario: s,
              selected: s == widget.mockScenario,
              onTap: widget.busy ? null : () => widget.onMockScenarioChanged?.call(s),
            ),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final width = MediaQuery.sizeOf(context).width;
    final wide = !isAppLayout(context) && MediaQuery.textScalerOf(context).scale(18) <= 26;
    return TrinityScaffold(
      topGap: wide ? 52 : 16,
      children: [
        Semantics(header: true, child: Text(InputScreen.tagline, style: TText.display.copyWith(
          color: p.ink, fontSize: (width * 0.06).clamp(40.0, 64.0), height: 1.15, letterSpacing: -1.5,
        ))),
        const SizedBox(height: TSpace.x3),
        Text(InputScreen.lead, style: TText.body.copyWith(color: p.muted)),
        const SizedBox(height: TSpace.x4),
        Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('YouTube 영상 주소', style: TText.label.copyWith(color: p.ink)),
          const SizedBox(height: TSpace.x2),
          _field(context),
          if (_pasteHint != null) Semantics(liveRegion: true, child: Text(_pasteHint!, style: TText.secondary)),
          const SizedBox(height: TSpace.x3),
          Wrap(spacing: TSpace.x2, runSpacing: TSpace.x2, children: [
            SecondaryButton(label: '붙여넣기', onPressed: widget.busy ? null : _paste),
            PrimaryButton(label: widget.busy ? '요청하는 중…' : InputScreen.submitLabel,
              onPressed: widget.busy ? null : _submit),
          ]),
        ])),
        if (widget.onJobs != null || _mock)
          Wrap(spacing: TSpace.x3, children: [
            if (widget.onJobs != null) TextLinkButton(label: '내 작업', onPressed: widget.busy ? null : widget.onJobs),
            if (_mock) TextLinkButton(label: InputScreen.exampleLabel, onPressed: widget.busy ? null : _example),
          ]),
        if (_mock) Disclosure(title: '가상 결과 고르기', child: _scenarios(context)),
        const SectionTitle('이런 단서를 살펴봐요'),
        _lenses(context, wide),
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
    final p = context.palette;
    return Semantics(
      inMutuallyExclusiveGroup: true,
      checked: selected,
      button: true,
      label: scenario.label,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(TRadius.control),
          child: Container(
            constraints: const BoxConstraints(minHeight: TSize.touch),
            decoration: BoxDecoration(
              color: selected ? p.soft : null,
              borderRadius: BorderRadius.circular(TRadius.control),
            ),
            padding: const EdgeInsets.symmetric(horizontal: TSpace.x2, vertical: TSpace.x2),
            child: Row(
              children: [
                Icon(
                  selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                  size: 18,
                  color: selected ? p.ink : p.muted,
                ),
                const SizedBox(width: TSpace.x3),
                Expanded(
                  child: Text(scenario.label, style: (selected ? TText.bodyStrong : TText.body).copyWith(color: p.ink)),
                ),
                if (selected) Text('선택됨', style: TText.small.copyWith(color: p.ink)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
