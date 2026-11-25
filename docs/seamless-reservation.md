# Seamless Interaction 분할 예약 기록

2026-11-25 · `docs/seamless-pilot-plan.md` §2 구현. 규칙은 같은 날 사용자 승인.

**이 문서의 커밋은 미디어를 하나도 받기 전에 만들었다.** 예약 이후 첫 미디어 다운로드는 파일럿 0번 한 쌍뿐이다(`docs/seamless-first-pair.md`).
상세 ID 목록은 Git 밖 `data/research/seamless/reservation/`에 있다. 아래 해시로 그 목록이 바뀌지 않았음을 확인한다.

## 재현 정보

| 항목 | 값 |
|---|---|
| 공식 저장소 | `facebookresearch/seamless_interaction` main, 커밋 `b61b0324461f05221659cc38a1130f854fdd2855` (2025-12-13) |
| 인덱스 | `assets/filelist.csv`, Git blob `e759e6d00f152a4833df2b985de842ab642812cd` (계획서 기준과 같음), SHA-256 `e8ecdfd690286502193489b638208b70d1834dc3e25e2145050618e14dd568dc` |
| 스크립트 | `scripts/seamless_reserve.py` (이 문서와 같은 커밋), SHA-256 `43b301f9e7b57121ee6317a892f6fe4978d6901df24c925f7d43d09edd3a867b` |
| 시드 | `20261125` |
| `reservation.csv` (test·dev·pilot 310행, 역할·순번 정렬) | SHA-256 **`2cd2ddc8ff89e85abf03c3ea2a1b84f0b03119d16bc02e01203d180dbf6538c0`** |
| `assignment.csv` (naturalistic 46,810개 interaction 전체의 역할) | SHA-256 `af08c93fa9673ec81cd5f5ecb0311a5bfe57965b718b6367225b5517f056bca5` |

재현: 공식 저장소를 위 커밋으로 `data/research/seamless/src/seamless_interaction`에 두고 `python scripts/seamless_reserve.py`(conda `trinity`).
인덱스 blob이 다르면 스크립트가 멈춘다. 같은 입력이면 두 CSV가 바이트 단위로 같다. 시험: `tests/test_seamless_reservation.py`.

## 규칙

1. **단위.** naturalistic interaction 하나(`V<기관>_S<세션>_I<interaction>`)가 한 쌍이다. interaction 번호는 세션 사이에서 재사용되므로(1,427건) 키에 세션을 넣는다. 모든 naturalistic interaction은 파일 2개였고 분할이 섞인 것은 없었다.
2. **신원 키.** P 숫자 코드다. 기관 번호와 끝 글자(`A`)를 무시하고 앞의 0을 뗀다. 같은 코드가 다른 사람일 수도 있지만, 메타데이터로 구별할 수 없으므로 같은 사람일 수 있는 것으로 본다.
3. **예약 후보에서 제외** (공식 train 45,239개 중. 한 interaction에 사유가 여럿일 수 있다)

   | 사유 | 건수 | 뜻 |
   |---|---:|---|
   | `pcode_multi_vendor` | 21,907 | 참가자 코드가 둘 이상의 기관 행에 나온다(label 무관). 같은 사람인지 알 수 없다 |
   | `pcode_in_official_dev_test` | 2,821 | 참가자 코드가 공식 dev·test 행(label 무관)에 나온다 |
   | `participant_suffix_id` | 154 | 끝 글자가 붙은 ID. 의미가 공식 문서에 없다 |
   | `file_count_not_2` · `same_participant_twice` · `split_mixed` · 형식 오류 | 0 | |

   제외된 interaction은 22,236개, 예약 후보는 **23,003개**다(기관 00: 6,395 / 01: 677 / 02: 5,174 / 03: 10,757).
   기관 사이 코드 재사용이 많아 절반 가까이 빠졌다. 기준을 완화하지 않았다.
4. **층화 추출.**
   - 역할은 test → dev → pilot 순서로 뽑는다.
   - 각 역할의 목표 수(200·100·10)를 후보의 기관별 비율로 나눈다. 최대 잔여법을 쓰고, 나머지가 같으면 기관 번호 순으로 정한다.
   - 기관 안에서는 `sha256(시드|역할|키)` 순서로 보고, 이미 어느 역할에 쓰인 참가자나 세션이 있으면 건너뛴다.
   - **부족하면 다른 기관으로 넘기지 않고 부족분을 보고한다.** 이번에는 부족이 없었다.
5. **얼굴 대상 A와 순번.**
   - A는 `sha256(시드|A-select|키)`가 짝수면 사전순으로 앞선 파일 ID, 홀수면 뒤 파일 ID로 정했다. 결과를 보기 전에 고정했다.
   - 역할 안 순번은 `sha256(시드|order|역할|키)` 순서다. **파일럿 0번이 첫 쌍**이다.
6. **나머지 분류**(`assignment.csv`의 `role`)
   - `quarantined_linked`: 예약된 참가자나 세션과 닿는 공식 train interaction. 제외 사유가 있어도 이 표시가 먼저다.
   - `excluded`: 3의 사유가 있고 예약 인물과는 닿지 않는 interaction.
   - `train_candidate`: 위 어디에도 해당하지 않는 interaction.
   - `official_dev`·`official_test`: 공식 분할 그대로다.
   - 공식 dev·test는 어떤 역할로도 예약하지 않는다.

## 결과

| 역할 | 목표 | 예약 | 기관 00 | 01 | 02 | 03 |
|---|---:|---:|---:|---:|---:|---:|
| 내부 test | 200 | 200 | 56 | 6 | 45 | 93 |
| 내부 dev | 100 | 100 | 28 | 3 | 22 | 47 |
| 파일럿 | 10 | 10 | 3 | 0 | 2 | 5 |

- 예약 310쌍은 참가자 620명을 쓴다. 쌍마다 참가자와 세션이 다른 쌍과 겹치지 않으므로 **한 쌍이 하나의 독립 그룹**이다. 내부 test는 n = 200그룹이다(실제 점수가 나온 그룹으로 나중에 다시 센다).
- 전체 분류는 다음과 같다. `train_candidate` 9,044 / `quarantined_linked` 20,086 / `excluded` 15,799 / `official_dev` 748 / `official_test` 823.
- `train_candidate`의 참가자는 1,115명이다. 참가자를 대화로 연결한 성분은 438개다.
- 예약된 참가자가 나오는 **improvised train 행이 2,120개** 있다. 이후 어떤 학습 manifest에도 넣지 않는다.
- 위 수치는 메타데이터 집계다. 영상 품질, 발화량, 실제 신원 일치는 확인하지 않았다.

## 지킬 것

- 내부 test·dev와 공식 dev·test 미디어는 개발 중 내려받지 않는다. 이번 작업에서 받는 것은 파일럿 0번 두 파일 ID뿐이다.
- 파일럿 10쌍은 이후 평가에서 뺀다. 실패한 쌍도 예약 분모에 남기고 몰래 교체하지 않는다.
- 내부 분할을 학습 manifest에 적용하는 일은 DESIGN §15.3 결정 6 변경이 승인된 뒤에 한다. 그때 `assignment.csv`와 행 단위로 대조한다(계획 §2의 5).
- 출처: Meta Seamless Interaction, CC BY-NC 4.0. 비상업 연구 기록용이다.
