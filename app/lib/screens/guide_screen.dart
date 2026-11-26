import 'package:flutter/material.dart';

import '../design/tokens.dart';
import '../design/widgets.dart';

/// 이용 안내. 결과를 읽는 법과 서비스가 하지 않는 일을 알린다.
class GuideScreen extends StatelessWidget {
  const GuideScreen({super.key, required this.onStart});

  final VoidCallback onStart;

  static const items = <(String, String)>[
    ('YouTube 주소로 시작해요', '말하는 사람이 나오는 영상을 대상으로 합니다. 영상 파일 업로드는 받지 않습니다.'),
    ('영상을 받을 수 있어야 해요', '연구용 서버에서 영상을 확인합니다. 비공개 영상처럼 접근할 수 없는 경우에는 그 이유를 알려드립니다.'),
    ('의심 신호와 진위 확정은 달라요', '의심 신호가 낮아도 진짜 영상이라는 뜻은 아닙니다. 영상 내용의 사실 여부는 확인하지 않습니다.'),
    ('모르는 것은 모른다고 말해요', '분석할 수 없거나 근거가 충분하지 않으면 판단을 보류합니다. 없는 값을 점수로 채우지 않습니다.'),
    ('숫자로 진위를 말하지 않는 이유', '흐릿한 얼굴이나 영상 압축도 신호를 바꿀 수 있어요. 어떤 구간에서 무엇을 관찰했는지 알려 드리고, 비교 근거가 부족하면 판단을 보류합니다.'),
  ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return TrinityScaffold(
      children: [
        Semantics(header: true, child: Text('결과를 이해하는\n작은 안내서.', style: TText.display.copyWith(color: p.ink))),
        const SizedBox(height: TSpace.x3),
        Text('TRINITY는 영상의 의심 신호를 살펴보고, 판단할 수 없는 부분도 함께 알려드립니다.', style: TText.body.copyWith(color: p.muted)),
        const SizedBox(height: TSpace.x4),
        for (final (title, body) in items) ...[
          Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Semantics(header: true, child: Text(title, style: TText.h3.copyWith(color: p.ink))),
            const SizedBox(height: TSpace.x1),
            Text(body, style: TText.body.copyWith(color: p.muted)),
          ])),
          const SizedBox(height: TSpace.x2),
        ],
        const SizedBox(height: TSpace.x2),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: PrimaryButton(label: '영상 확인하러 가기', icon: Icons.arrow_forward, onPressed: onStart),
        ),
      ],
    );
  }
}
