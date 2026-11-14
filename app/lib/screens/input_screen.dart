import 'dart:math' as math;

import 'package:flutter/material.dart';

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
    this.mockScenario,
    this.onMockScenarioChanged,
  });

  final ValueChanged<String> onSubmit;
  final bool busy;

  /// 요청 실패 안내(HTTP 422·429·연결 실패 등). 분석 결과가 아니다.
  final String? errorText;

  /// mock 모드일 때만 값이 있다. "예시로 둘러보기"와 가상 결과 고르기를 보여 준다.
  final MockScenario? mockScenario;
  final ValueChanged<MockScenario>? onMockScenarioChanged;

  static const tagline = '영상 속 단서, 차분히 확인하세요.';
  static const lead = '말하는 사람이 나오는 YouTube 영상에서 AI 생성·조작 의심 신호를 살펴봅니다.';
  static const submitLabel = '분석 요청';
  static const exampleLabel = '예시로 둘러보기';
  static const permissionShort = '허가된 영상만 확인합니다';
  static const permissionLong = '분석이 허가된 영상만 다룹니다. 확인할 수 없는 영상은 그 이유를 알려드려요.';
  static const helpTitle = '무엇을 분석하나요?';
  static const noUpload = '영상 파일은 받지 않습니다. YouTube 주소만 입력할 수 있어요.';

  /// mock 모드의 예시 주소. 실제 영상이 아니다.
  static const exampleUrl = 'https://youtu.be/TRINITYdemo';

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

  void _example() {
    _controller.text = InputScreen.exampleUrl;
    _submit();
  }

  bool get _mock => widget.mockScenario != null;

  Widget _field(BuildContext context, {required bool pill}) {
    final p = context.palette;
    OutlineInputBorder border(Color c, [double w = 1]) => OutlineInputBorder(
          borderRadius: BorderRadius.circular(TRadius.pill),
          borderSide: BorderSide(color: c, width: w),
        );
    return TextField(
      controller: _controller,
      enabled: !widget.busy,
      keyboardType: TextInputType.url,
      autocorrect: false,
      style: TText.body.copyWith(color: p.ink),
      minLines: 1,
      maxLines: 3,
      decoration: InputDecoration(
        hintText: 'https://youtu.be/…',
        errorText: _localError ?? widget.errorText,
        prefixIcon: const Icon(Icons.link, size: 20),
        contentPadding: pill ? const EdgeInsets.symmetric(horizontal: TSpace.x4, vertical: 18) : null,
        enabledBorder: pill ? border(p.controlLine) : null,
        focusedBorder: pill ? border(p.ink, 2) : null,
        disabledBorder: pill ? border(p.line) : null,
        errorBorder: pill ? border(p.warning) : null,
        focusedErrorBorder: pill ? border(p.warning, 2) : null,
      ),
      onSubmitted: (_) => _submit(),
    );
  }

  Widget _label(BuildContext context, {bool centered = false}) => Text(
        'YouTube 영상 주소',
        textAlign: centered ? TextAlign.center : TextAlign.start,
        style: TText.small.copyWith(color: context.palette.muted, fontWeight: FontWeight.w700),
      );

  Widget _lenses(BuildContext context, {required bool row}) {
    final p = context.palette;
    Widget lens(IconData icon, String title, String body) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 18, color: p.ink),
                const SizedBox(width: TSpace.x2),
                Expanded(child: Text(title, style: TText.h3.copyWith(color: p.ink))),
              ],
            ),
            const SizedBox(height: TSpace.x1),
            Text(body, style: TText.secondary.copyWith(color: p.muted)),
          ],
        );
    final items = [
      lens(Icons.center_focus_weak, '영상의 미세한 신호', '프레임 속 생성·조작 관련 특징을 살펴봅니다.'),
      lens(Icons.open_with, '움직임의 패턴', '영상에서 추적한 점들의 움직임을 살펴봅니다.'),
      lens(Icons.graphic_eq, '입술과 음성의 타이밍', '소리와 입 움직임이 맞는지 보는 보조 지표입니다.'),
    ];
    if (row) {
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < items.length; i++) ...[
            if (i > 0) const SizedBox(width: TSpace.x4),
            Expanded(child: items[i]),
          ],
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < items.length; i++) ...[
          if (i > 0) const SizedBox(height: TSpace.x4),
          items[i],
        ],
      ],
    );
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
  Widget build(BuildContext context) => isAppLayout(context) ? _buildApp(context) : _buildWeb(context);

  /// 앱형: 왼쪽 정렬 두 줄 제목, 짧은 설명, 주소 입력 카드, 폭을 채우는 버튼.
  Widget _buildApp(BuildContext context) {
    final p = context.palette;
    return TrinityScaffold(
      children: [
        const Overline('YOUTUBE VIDEO CHECK'),
        const SizedBox(height: TSpace.x2),
        Semantics(
          header: true,
          child: Text('영상 속 단서,\n차분히 확인하세요.', style: TText.display.copyWith(color: p.ink)),
        ),
        const SizedBox(height: TSpace.x3),
        Text(InputScreen.lead, style: TText.body.copyWith(color: p.muted)),
        const SizedBox(height: TSpace.x4),
        Panel(
          padding: const EdgeInsets.all(TSpace.screen),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _label(context),
              const SizedBox(height: TSpace.x2),
              _field(context, pill: false),
              const SizedBox(height: TSpace.x3),
              PrimaryButton(
                label: widget.busy ? '요청하는 중…' : InputScreen.submitLabel,
                icon: widget.busy ? null : Icons.north_east,
                onPressed: widget.busy ? null : _submit,
              ),
              const SizedBox(height: TSpace.x2),
              Text('공유한 링크를 여기에 붙여넣어 주세요.', style: TText.small.copyWith(color: p.muted)),
              if (_mock)
                Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: TextLinkButton(
                    label: InputScreen.exampleLabel,
                    trailing: Icons.arrow_forward,
                    onPressed: widget.busy ? null : _example,
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: TSpace.x3),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Icon(Icons.lock_outline, size: 16, color: p.muted),
            ),
            const SizedBox(width: TSpace.x2),
            Expanded(child: Text(InputScreen.permissionLong, style: TText.secondary.copyWith(color: p.muted))),
          ],
        ),
        const SizedBox(height: TSpace.x1),
        Text(InputScreen.noUpload, style: TText.secondary.copyWith(color: p.muted)),
        const SectionTitle('이런 단서를 살펴봐요'),
        _lenses(context, row: false),
        if (_mock) ...[
          const SizedBox(height: TSpace.x4),
          Disclosure(title: '가상 결과 고르기', child: _scenarios(context)),
        ],
      ],
    );
  }

  /// 웹형: 가운데보다 조금 위에 워드마크, 한 줄 소개, 캡슐 입력창, 버튼 두 개.
  Widget _buildWeb(BuildContext context) {
    final p = context.palette;
    final size = MediaQuery.sizeOf(context);
    return TrinityScaffold(
      header: HeaderStyle.guideOnly,
      maxWidth: TSize.searchMax,
      topGap: math.max(TSpace.x5, size.height * 0.12),
      children: [
        Semantics(
          header: true,
          child: Text(
            'TRINITY',
            textAlign: TextAlign.center,
            style: TText.display.copyWith(
              fontSize: (size.width * 0.05).clamp(40.0, 66.0),
              height: 1.15,
              letterSpacing: 7,
              color: p.ink,
            ),
          ),
        ),
        const SizedBox(height: TSpace.x3),
        Text(
          InputScreen.tagline,
          textAlign: TextAlign.center,
          style: TText.title.copyWith(color: p.ink),
        ),
        const SizedBox(height: TSpace.x5),
        Semantics(label: 'YouTube 영상 주소', child: _field(context, pill: true)),
        const SizedBox(height: TSpace.x4),
        Wrap(
          alignment: WrapAlignment.center,
          spacing: TSpace.x3,
          runSpacing: TSpace.x2,
          children: [
            PrimaryButton(
              label: widget.busy ? '요청하는 중…' : InputScreen.submitLabel,
              onPressed: widget.busy ? null : _submit,
            ),
            if (_mock)
              SecondaryButton(label: InputScreen.exampleLabel, onPressed: widget.busy ? null : _example),
          ],
        ),
        const SizedBox(height: TSpace.x4),
        Text(
          InputScreen.permissionShort,
          textAlign: TextAlign.center,
          style: TText.small.copyWith(color: p.muted),
        ),
        Disclosure(
          title: InputScreen.helpTitle,
          centered: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(InputScreen.lead, style: TText.secondary.copyWith(color: p.muted)),
              Text(
                '${InputScreen.permissionLong} ${InputScreen.noUpload}',
                style: TText.secondary.copyWith(color: p.muted),
              ),
              const SizedBox(height: TSpace.x4),
              _lenses(context, row: true),
            ],
          ),
        ),
        if (_mock) Disclosure(title: '가상 결과 고르기', centered: true, child: _scenarios(context)),
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
