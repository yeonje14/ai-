import 'package:flutter/material.dart';

import '../design/tokens.dart';
import '../design/widgets.dart';

/// 이용 안내. 결과를 읽는 법과 서비스가 하지 않는 일을 알린다.
class GuideScreen extends StatelessWidget {
  const GuideScreen({super.key, required this.onStart});

  final VoidCallback onStart;

  static const items = <(String, String)>[
    ('YouTube 주소로 시작해요', '말하는 사람이 나오는 영상을 대상으로 합니다. 영상 파일 업로드는 받지 않습니다.'),
    ('분석이 허가된 영상만 확인해요', '주소가 올바르더라도 허가된 미디어가 없으면 분석하지 않고 이유를 알려드립니다.'),
    ('의심 신호와 진위 확정은 달라요', '의심 신호가 낮아도 진짜 영상이라는 뜻은 아닙니다. 영상 내용의 사실 여부는 확인하지 않습니다.'),
    ('모르는 것은 모른다고 말해요', '분석할 수 없거나 근거가 충분하지 않으면 판단을 보류합니다. 없는 값을 점수로 채우지 않습니다.'),
  ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return TrinityScaffold(
      children: [
        const Overline('BEFORE YOU BEGIN'),
        const SizedBox(height: TSpace.x2),
        Semantics(header: true, child: Text('결과를 이해하는\n작은 안내서.', style: TText.display.copyWith(color: p.ink))),
        const SizedBox(height: TSpace.x3),
        Text('TRINITY는 영상의 의심 신호를 살펴보고, 판단할 수 없는 부분도 함께 알려드립니다.', style: TText.body.copyWith(color: p.muted)),
        const SizedBox(height: TSpace.x4),
        for (var i = 0; i < items.length; i++)
          Container(
            decoration: BoxDecoration(border: Border(top: BorderSide(color: p.line))),
            padding: const EdgeInsets.symmetric(vertical: TSpace.x4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ExcludeSemantics(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Text('0${i + 1}', style: TText.small.copyWith(color: p.muted, letterSpacing: 1)),
                  ),
                ),
                const SizedBox(width: TSpace.x3),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(items[i].$1, style: TText.h3.copyWith(color: p.ink)),
                      const SizedBox(height: TSpace.x1),
                      Text(items[i].$2, style: TText.body.copyWith(color: p.muted)),
                    ],
                  ),
                ),
              ],
            ),
          ),
        const SizedBox(height: TSpace.x2),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: PrimaryButton(label: '영상 확인하러 가기', icon: Icons.arrow_forward, onPressed: onStart),
        ),
      ],
    );
  }
}
