# 고정 평가 파이프라인 뼈대

README §14.1 백로그 8번(P1-3)의 첫 단계. 작성일: 2026-11-13.

> **뼈대다. 성능 결과가 아니다.**
> 실제 학습 데이터(DeepSpeak v2)가 아직 없어서 합성 manifest와 합성 점수로만 동작을 확인했다.
> 이 문서와 테스트에 나오는 수치는 파이프라인이 도는지 보기 위한 가짜 값이며 모델 성능과 무관하다.
> MAVOS-DD 표본으로는 추론하지 않았다. 메타데이터 검사만 했다.

## 무엇을 강제하는가

| 규칙 (출처) | 어디서 막는가 |
|---|---|
| 같은 인물·원본 계보 그룹이 여러 분할에 걸치면 평가하지 않는다 (AGENTS.md, README §6.4) | `training/hygiene.py`가 실패로 판정. `fit-threshold`와 `evaluate`는 실패한 manifest를 거부한다 |
| 임계값은 dev 분할에서만 정한다 (README §13.3) | `thresholds.fit_threshold`가 dev가 아닌 영상이 섞이면 예외 |
| 고정한 임계값은 바꿀 수 없다 | 파일을 새로만 만들 수 있고(덮어쓰기 거부, 읽기 전용), 내용 해시가 다르면 불러올 때 거부. `evaluate`는 임계값을 숫자로 받는 옵션이 없다 |
| 외부 최종 평가 자료는 학습·임계값·분할 배정에 쓰지 않는다 (README §6.4, 결정 6) | `configs/external_eval_lock.json`에 등록. 내부 분할에 들어가면 누수 검사 실패 |
| 외부 평가는 모델과 임계값을 고정한 뒤 한 번 한다 (README §6.3) | 잠금이 `locked`면 `evaluate --split external`을 거부. `unlocked`로 고쳐 커밋하고 `--final-external`을 줘야 실행 |
| 실패하거나 실행하지 않은 점수는 `null`이다 | 점수가 빈칸인 영상과 점수 행이 없는 영상은 지표에서 빼지 않고 보류로 센다. 계산할 수 없는 지표는 `null` |

## 구성

| 파일 | 역할 |
|---|---|
| `training/datasets/manifest.py` | 공통 manifest 레코드, CSV 읽기·쓰기, 형식 검사 |
| `training/datasets/groups.py` | 연결 그룹 계산, 그룹 단위 분할 배정 |
| `training/hygiene.py` | 누수 검사와 경고 집계 |
| `training/evaluation/metrics.py` | ROC-AUC, 고정 임계값의 TPR·FPR, 생성기별·유형별, 보류, 그룹 bootstrap |
| `training/evaluation/thresholds.py` | 임계값 고정과 무결성 확인 |
| `training/evaluation/lock.py`, `configs/external_eval_lock.json` | 외부 평가 자료 잠금 |
| `training/evaluation/run.py` | `fit-threshold`, `evaluate` 명령 |
| `training/datasets/mavos.py` | MAVOS-DD 표본의 공통 manifest 변환과 메타데이터 검사 |

모두 표준 라이브러리만 쓴다. conda `trinity`에 새 의존성을 넣지 않았다.

## 공통 manifest

CSV 한 줄이 영상 하나다. README §6.4의 공통 레코드에 경로와 라벨을 더했다.

| 열 | 뜻 | 필수 |
|---|---|---|
| `dataset_id`, `video_id` | 데이터셋과 그 안의 영상. 둘을 합친 값이 유일해야 한다 | 예 |
| `video_path` | 영상 경로 | 예 |
| `label` | `real` 또는 `fake` | 예 |
| `source_recording_id` | **원본 계보 ID.** 같은 원본 녹화에서 나온 영상은 같은 값 | 예 |
| `identity_ids` | 인물 ID. 여럿이면 `\|`로 구분(얼굴 교체의 출처와 대상 모두) | 아니오 (없으면 경고) |
| `manipulation_type` | A1~C2 (README §6.1). 진짜는 빈칸 | 아니오 |
| `generator_id` | 생성기. 진짜는 빈칸 | 아니오 |
| `parent_video_id`, `derivation_group_id` | 파생 관계(압축·crop·재인코딩 등) | 아니오 |
| `split` | `train`, `dev`, `test`, `external` | 평가 전에는 예 |
| `file_hash` | 파일 해시 | 아니오 (없으면 경고) |

- 모르는 값은 빈칸이다. 원본을 알 수 없으면 `source_recording_id`를 `unknown:<경로>`로 적어 "묶을 수 없는 영상"임을 드러낸다. 이런 영상은 `source_unverified` 경고로 센다.
- `dev`가 README의 "개발 검증 분할"이다.

## 그룹과 누수 검사

- **그룹**: 원본 계보 ID, 인물 ID, 파생 계보 ID, 부모 영상 중 하나라도 같으면 같은 그룹으로 잇는다(연결 요소). 인물 A의 영상과 "A의 얼굴을 B에게 교체한 영상", B의 영상은 모두 한 그룹이 된다.
- **분할 배정**: `groups.assign_splits`가 그룹을 고정 시드의 해시 순서로 놓고 비율대로 `train`/`dev`/`test`에 통째로 넣는다. `external`은 건드리지 않는다. 압축·증강은 분할을 정한 뒤에 적용한다.

실패로 처리하는 것:

| 코드 | 뜻 |
|---|---|
| `group_spans_splits` | 같은 그룹이 둘 이상의 분할에 있다 |
| `source_overlap_external_internal` | 외부 평가 세트와 `train`/`dev`/`test` 사이에 원본 계보 ID가 겹친다 |
| `identity_overlap_external_internal` | 외부 평가 세트와 내부 분할 사이에 인물 ID가 겹친다 |
| `file_hash_overlap_external_internal`, `file_hash_spans_splits` | 같은 파일 해시가 서로 다른 분할에 있다 |
| `external_dataset_in_internal_split` | 잠금에 등록된 데이터셋이 `train`/`dev`/`test`에 있다 |
| `external_dataset_not_registered` | `external`인데 잠금 파일에 없는 데이터셋이다 |
| `split_missing` | 분할이 비어 있다 |

경고(실패는 아니지만 **평가 리포트에 항상 개수를 싣는다**. 0이어도 항목을 남긴다):

| 항목 | 뜻 |
|---|---|
| `identity_missing` | 인물 ID가 없는 영상 수. 같은 인물이 다른 원본에 나와도 잡지 못한다 |
| `source_unverified` | 원본 식별자가 없어 파일 하나를 묶음 하나로 둔 영상 수 |
| `fake_generator_missing`, `fake_manipulation_type_missing` | 생성기·유형이 빈 가짜 영상 수 |
| `file_hash_missing` | 파일 해시가 없는 영상 수 |

하지 않은 것: 영상 유사도, 오디오 무음 편향, 코덱·해상도·FPS·길이 shortcut 진단(README §6.4의 나머지 항목). 실제 파일이 있어야 해서 이번 범위에서 뺐다.

## 지표

판정 규칙은 `점수 >= 임계값 → 가짜`다. 점수는 클수록 가짜 방향인 원시 점수로 가정한다.

- **ROC-AUC**: 진짜와 가짜가 모두 있을 때만. 동점은 0.5로 센다. 한쪽이 없으면 `null`.
- **TPR, 실제 FPR**: dev에서 고정한 임계값을 그대로 적용한 값. 평가 분할의 ROC에서 5% 지점을 다시 고르지 않는다. 그래서 실제 FPR은 5%와 다를 수 있고, 그 값을 그대로 보고한다.
- **임계값 선택**: dev의 진짜 점수에서 허용 오탐 수를 `floor(0.05 × n)`개로 잡고, 그보다 하나 더 큰 순위의 점수 바로 위를 임계값으로 한다. 동점이 있어도 dev FPR이 5%를 넘지 않는다.
- **생성기별(기본)과 유형별(보조)**: 그 범주의 가짜에 대한 TPR, 그리고 그 범주의 가짜와 전체 진짜로 계산한 AUC. 영상 수, 점수가 있는 수, 그룹 수를 함께 적는다. 유형별은 데이터셋의 생성기를 A1~C2에 대응시킨 결과라 잠정이다.
- **보류와 coverage**: `verdict_coverage`(점수가 나온 영상의 비율), `abstention_rate`, 사유별 보류 수. 점수 파일에 길이 열이 있으면 분석 시간 coverage도 합산한다. 이 값들은 분석한 양이며 정확도가 아니다.
- **신뢰구간**: 그룹을 복원 추출하는 bootstrap(기본 1,000회, 고정 시드, 95% 백분위). 한 회차에서 계산할 수 없는 지표는 그 회차만 빼고 `n_boot_valid`에 유효 회차 수를 적는다.

AUC 구현은 무작위 점수 200쌍에서 `scipy.stats.mannwhitneyu` 기반 값과 차이 0임을 한 번 확인했다(2026-11-13, `research/waverep/.venv`에서 일회성 실행. 테스트에는 넣지 않았다. trinity에 scipy가 없다).

## 사용법

저장소 루트, conda `trinity`.

```bash
# 1) 누수 검사 (종료 코드 0 통과, 1 실패)
python -m training.hygiene data/research/<manifest>.csv

# 2) dev에서 임계값 고정. 이미 있는 파일은 덮어쓰지 않는다
python -m training.evaluation.run fit-threshold \
  --manifest data/research/<manifest>.csv --scores data/research/<scores>.csv \
  --model-id <모델 이름> --out data/research/<threshold>.json

# 3) test 평가
python -m training.evaluation.run evaluate \
  --manifest data/research/<manifest>.csv --scores data/research/<scores>.csv \
  --threshold data/research/<threshold>.json --split test --out data/research/<report>.json

# 4) 최종 외부 평가 (잠금을 풀어 커밋한 뒤에만). dev manifest도 함께 줘야 누수 검사를 한다
python -m training.evaluation.run evaluate \
  --manifest data/research/<manifest>.csv --manifest data/research/mavos-dd/common-manifest.csv \
  --scores data/research/<external-scores>.csv --threshold data/research/<threshold>.json \
  --split external --final-external --out data/research/<external-report>.json
```

점수 파일(CSV)의 열: `dataset_id`, `video_id`, `score`, `status`, `reason_code`, 그리고 선택 열 `video_duration_sec`, `eligible_duration_sec`, `analyzed_duration_sec`. `score`가 빈칸이면 판정을 내지 못한 영상이다. manifest에 없는 영상의 점수가 있으면 오류다. 외부 평가의 점수는 내부 점수와 다른 파일에 둔다.

종료 코드: 0 성공, 1 누수·입력 오류, 3 임계값·잠금 규칙 위반.

## MAVOS-DD 표본 (잠금, 메타데이터 검사만)

```bash
python -m training.datasets.mavos check --write-common data/research/mavos-dd/common-manifest.csv
python -m training.hygiene data/research/mavos-dd/common-manifest.csv
```

2026-11-13 실행 결과(영상을 열지 않았고 추론하지 않았다):

| 항목 | 값 |
|---|---|
| 표본 목록 sha256 | `c7df5967…e1aba`, 잠금 파일의 값과 일치 |
| 영상 | 2,160개 (진짜 1,080, 가짜 1,080), 6,766,772,622바이트 |
| 층 | 60개. 층당 개수와 원본 묶음당 2개 상한을 넘는 층 없음 |
| 파일 | 2,160개 모두 있고 크기가 목록과 일치 |
| 원본 묶음 | 1,176개 |
| 잠금 상태 | `locked` |
| 누수 검사 | 통과(분할이 `external` 하나뿐) |
| 경고 `identity_missing` | **2,160** (MAVOS-DD에는 인물 ID가 없다) |
| 경고 `source_unverified` | **448** (21%. 파일 이름에 원본 식별자가 없다) |
| 경고 `file_hash_missing` | 2,160 (영상을 읽지 않아 계산하지 않았다) |

- 원본 식별자가 없는 448개는 서로 독립으로 취급된다. 같은 원본에서 나왔더라도 묶이지 않으므로, 이 표본의 신뢰구간은 실제보다 좁게 나올 수 있다. 외부 평가 보고에 이 한계를 적는다.
- 학습 데이터(DeepSpeak v2)가 들어오면 그 manifest와 함께 검사해야 원본 계보 겹침(`source_overlap_external_internal`)을 확인할 수 있다. 지금은 비교할 내부 데이터가 없어 **미검증**이다. 두 데이터셋의 원본 ID 체계가 달라 문자열이 겹치지 않더라도 같은 영상일 수 있는지는 **확인 필요**다.
- 위조 유형 대응(잠정): `echomimic`·`memo`·`sonic`·`liveportrait` → A1, `hififace`·`roop` → C1, `inswapper` → C2, `freevc`·`knnvc` → B1. TRINITY의 판단이며 게시자의 분류가 아니다. 보고는 생성기별을 기본으로 한다.
- 잠금 파일에는 TalkingHeadBench와 Deepfake-Eval-2024도 `locked`로 등록했다(파일 없음).

## 테스트

`tests/test_eval_pipeline.py`, `tests/test_mavos_external.py`. 모두 합성 데이터다.

- manifest 형식과 필수 열(원본 계보 ID 필수, 인물 ID 선택).
- 그룹 연결(원본·인물·부모·파생), 입력 순서와 무관함, 분할이 그룹을 쪼개지 않음.
- 누수 사례별 실패 코드, 외부와 내부의 원본·인물·해시 겹침, 경고 집계.
- AUC를 손 계산·쌍별 정의와 대조, 동점, 임계값의 실제 FPR, `null` 처리, 그룹 단위 bootstrap과 재현성.
- test·external·train으로 임계값을 정하려는 시도 차단, 덮어쓰기 거부, 변조 감지.
- 명령 끝까지: 임계값 고정 → test 평가 → 리포트, 누수 manifest 거부, 외부 평가 잠금과 해제 절차.
- 실제 MAVOS-DD 표본 목록 검사(파일이 없으면 건너뜀).

`pytest -q`: 225개 통과(2026-11-13, conda `trinity`, 건너뛴 테스트 없음).

## 남은 일과 한계

- 실제 데이터로 돌린 적이 없다. DeepSpeak v2가 들어오면 그 필드를 공통 manifest에 대응시키는 변환기를 만들고, 누수 검사와 단일축(WaveRep) 기초 평가 리포트를 낸다. 그때 백로그 8번의 완료 조건을 다시 본다.
- 영상 단위 점수가 필요하다. WaveRep 어댑터는 프레임별 logit을 내고 `raw_score`는 `null`이다. 프레임 logit을 영상 점수로 집계하는 방법은 dev에서 정해야 하며 아직 정하지 않았다.
- 압축 조건별 성능, 보정 지표(Brier, ECE), latency·메모리 집계는 넣지 않았다(README §13.1의 나머지 지표).
- 층화 표본에 대한 가중 추정은 넣지 않았다. MAVOS-DD 표본은 층별 추출 비율이 달라서 전체 값은 "표본의 값"으로만 읽고, 생성기별 값을 기본으로 본다.
- 임계값 파일의 보호는 실수와 조용한 변경을 막는 수준이다. 파일을 지우고 다른 이름으로 다시 만드는 것까지 막지는 못한다. 리포트에 임계값 digest와 입력 해시를 남겨 추적할 수 있게 했다.
- bootstrap은 순수 파이썬이다. 영상 수천 개에서는 몇 초에서 수십 초로 예상하지만 큰 데이터에서는 재지 않았다(**미검증**).
