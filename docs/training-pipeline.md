# 학습·평가 파이프라인: 데이터 → 단일축 → 결합 비교 → 채택 판단 → 서버 적용

docs/DESIGN.md §14.1 백로그 8번·12번. 작성일: 2026-11-16. 브랜치 `feat/training-pipeline`.

> **실제 데이터로 돌린 적이 없다. 성능 결과가 아니다.**
> DeepSpeak v2는 접근 심사 대기 중이다. 이 문서의 모든 동작은 합성 데이터(난수)로 확인했고, 테스트의 수치는 어떤 모델의 성능과도 무관하다.
> 실제 영상은 본인 촬영 `A.MOV` 한 개로 추출기를 소량 스모크한 것이 전부다.
> 저장소에는 고정된 모델 묶음이 없다. 서버는 지금도 항상 판단을 보류한다.

## 흐름

| 단계 | 명령 | 환경 | 산출물 |
|---|---|---|---|
| 1. 메타데이터 → 공통 manifest | `python -m training.datasets.adapters --config configs/datasets/<이름>.json --rows <메타데이터.jsonl> --out <manifest.csv>` | trinity | manifest, 누수·그룹 요약 |
| 2. (선택) 압축 파생본 | `python -m training.emulator.pipeline …` (`docs/compression-emulator.md`) | trinity | 파생 행이 붙은 manifest |
| 3. 특징 추출 | `python -m training.features.extract --manifest … --media-root … --out <특징 폴더>` | trinity + 각 모델 venv | `features.jsonl`, `features.meta.json`, `cache/`, `progress.jsonl` |
| 4. 학습·결합·임계값 | `research/training/.venv/bin/python research/training/train.py --manifest … --features <특징 폴더> --config configs/training.json --out <새 폴더>` | 학습 venv | `scores/`, `oof/`, `thresholds/`, `models/`, `train_meta.json` |
| 5. 리포트·채택 판단 | `python -m training.report.build --manifest … --run <학습 폴더> --features <특징 폴더> --out <새 폴더>` | trinity | `report.json`, `report.md` |
| 6. 묶음 | `python -m training.bundle --run … --report …/report.json --out data/models/fusion/<id>` | trinity | 묶음 폴더와 digest |
| 7. 서버 적용 | `configs/fusion_bundle.json`에 `bundle_id`와 `digest`를 적어 커밋 | – | 서버가 그 묶음으로만 판정 |

합성 데이터로 4~6을 돌려 보려면 `python -m training.synth --out <폴더> --signal waverep=1.5 full=1.0`.

## 규칙과 강제하는 곳

| 규칙 | 어디서 막는가 |
|---|---|
| 그룹(인물·원본 계보)이 분할에 걸치면 안 된다 | `training/hygiene.py`. 어댑터는 manifest를 쓰지 않고, 추출·학습·리포트는 실행을 거부한다 |
| 인물 ID와 확인된 원본 계보가 둘 다 없는 내부 분할 영상은 받지 않는다 | `hygiene`의 `ungroupable_video` 오류(2026-11-18 결정, 감사 A11). 어디에도 묶이지 않아 누수를 잡을 수 없기 때문이다. external 행은 대상이 아니다 |
| 공식 분할이 그룹을 쪼개면 조용히 다시 나누지 않는다 | 어댑터가 공식 `test`를 그대로 두고 공식 `train`만 train/dev로 나눈 뒤 누수 검사에 맡긴다 |
| 압축 파생본은 부모의 분할과 라벨을 물려받는다 | `derived_not_inheriting_parent` 오류 |
| 같은 바이트의 영상이 여러 분할에 있으면 안 된다 | `hygiene`(manifest의 `file_hash`)과 `train.py`(추출기가 계산해 `features.jsonl`에 남긴 `input_sha256`). 어댑터는 영상을 열지 않아 원본 행의 `file_hash`가 비어 있으므로 추출기의 해시로도 본다(감사 A8) |
| 잠금 대상 외부 평가 자료는 이름 표기를 바꿔도 내부 분할에 넣지 못한다 | `hygiene`의 `external_dataset_alias_in_internal_split`(대소문자·기호를 무시하고 비교, 감사 A7). 내용(바이트) 비교는 외부 표본의 파일 해시가 없어 하지 못한다 |
| 한 그룹이 내부 영상의 25%를 넘으면 학습하지 않는다 | `groups.size_summary`, `train.py`. 리포트에 그룹 크기 분포 |
| dev 압축 조건에는 기본값이 없다 | `configs/training.json`의 값이 `null`이면 `training/config.py`가 거부. 리포트 맨 위에 표시 |
| 임계값은 dev에서만, FPR 5% 목표로 정해 잠근다 | `thresholds.fit_threshold`(dev가 아닌 분할 거부), 읽기 전용 파일과 digest. 설정에는 임계값 분할을 바꾸는 키가 없고 모르는 키는 거부된다. test의 특징·라벨을 바꿔도 모델·보정·임계값이 같다는 테스트가 있다 |
| 결합 모델의 입력은 OOF 점수다 | `train.py`: MotionPhys는 그룹 5-fold OOF, 결합 모델도 같은 폴드로 교차 적합. 보정은 그 OOF 예측에만 맞춘다 |
| 계산하지 못한 점수는 null이다 | 특징·점수 파일의 빈칸, `Candidate.score`가 입력 결측이면 None |
| 설정한 장치(특징 버전)와 다른 장치로 대체된 값은 쓰지 않는다 | 추출: WaveRep·SyncNet이 `device_used`가 설정과 다르면 `error`/`device_mismatch`(캐시하지 않음). 서버: 같은 경우 결합 입력을 넘기지 않아 보류(축 상태는 그대로, 감사 A4) |
| 서버와 학습은 같은 함수로 결합 입력을 만든다 | WaveRep 집계 `waverep.aggregate_logits`(중앙값·평균·q75), SyncNet `report.fusion_features`. SyncNet 상태 규칙의 판(`report.STATUS_RULE`)이 특징 버전·캐시 키에 들어간다(감사 A13·A14) |
| Gate·SyncNet·압축 에뮬레이터는 같은 오디오 트랙을 읽는다 | 공용 규칙 `server/gate/audio_track.py`. 규칙 이름(`audio_track.RULE`)이 Gate·SyncNet의 특징 버전(`audio_track_rule`)에 들어가 규칙이 바뀌면 그 두 축의 캐시 키와 묶음 특징 버전이 바뀐다. WaveRep·MotionPhys는 오디오를 읽지 않고, 키에 든 Gate 구간을 따라 바뀐다(2026-11-19, docs/DESIGN.md §15.3 "결정 2·7 보완(오디오 트랙 선택)") |
| 외부 평가 자료는 쓰지 않는다 | 추출·학습·리포트 모두 `external` 분할을 읽지 않는다. 잠금(`configs/external_eval_lock.json`)과 `--final-external` 절차는 그대로다(`docs/evaluation-pipeline.md`) |
| 사전 고정 설정으로 학습한 결과만 서버에 간다 | 리포트는 학습 설정이 커밋된 `configs/training.json`과 다르면 맨 위에 적는다(`training_config_matches_committed`). 묶음은 같을 때만 만들고, 서버도 묶음의 설정이 지금 커밋된 설정과 같을 때만 쓴다. 설정을 바꾸면 다시 학습·검증해야 한다(감사 A2) |
| 3축을 강제로 채택하지 않는다 | 아래 채택 판단 |

## 데이터셋 어댑터

- 필드 이름은 코드에 없고 `configs/datasets/<이름>.json`에 있다.
- **DeepSpeak v2**(`deepspeak_v2.json`): Hugging Face 카드 공개 본문(2026-11-16 확인)에 적힌 필드만 `evidence: card`다 — `video-file`, `type`, 가짜의 `kind`·`engine`·`identity-source`·`identity-target`·`recording-source`·`recording-target`·`gen-config`·`audio-config`, 진짜의 `identity`.
- **확인 필요**(`evidence: unconfirmed`, 접근 승인 후 실제 행으로 고친다): 행 안에 분할 열이 있는지, 영상 ID 필드, **진짜 영상의 녹화 ID**(없으면 `unknown:<경로>`가 되고 인물 ID로만 묶인다), 메타데이터가 `metadata-fake`/`metadata-real` 묶음 안에 있는지, `recording-source`/`recording-target` 중 어느 쪽이 화면의 원본인지, 공식 분할의 인물 분리 여부, 카드의 엔진 6개와 논문 초록의 14개의 차이.
- 위조 유형 대응(`avatar→A2`, `lip-sync→B2`, `face-swap→C1`, 복원이 붙은 설정은 `C2`)은 TRINITY의 잠정 대응이다. 보고는 생성기별을 기본으로 한다.
- **HiDF**(`hidf.json`): 공개 정보를 확인하지 않아 필드가 비어 있고 변환을 거부한다.
- HF 데이터셋을 JSON Lines로 내보내는 단계는 만들지 않았다(행 구조를 모른다).

## 특징 추출

- 서버와 같은 경로다: 서버의 Gate 실행기 → 적합 구간 → 서버의 WaveRep·MotionPhys·SyncNet 어댑터(각 venv 서브프로세스). 추론 코드를 다시 구현하지 않았다.
- 캐시 키는 입력 파일 sha256 + 축 버전·설정 + 구간이다. 실행 오류(`error`)는 캐시하지 않아 다음 실행에서 다시 시도한다.
- 영상 단위 요약(연구 내부 집계, API 결과가 아니다): WaveRep 프레임 logit의 **중앙값**(주 지표, 사전 고정)·평균·q75, MotionPhys A/B/C 특징 벡터, SyncNet 전 구간·전 트랙의 LSE-C·LSE-D·|오프셋| 중앙값.
- 스모크(1회): `A.MOV` 한 개, Gate 13.8초, WaveRep 20.6초(76프레임, 중앙값이 Worker 실행 값과 같음), MotionPhys 45.3초. SyncNet은 돌리지 않았다(영상당 3~5분 실측, `docs/HANDOFF.md`).

## 학습과 후보

- 환경: `research/training/.venv`(numpy 2.4.6, scikit-learn 1.9.1, lightgbm 4.7.0, `requirements.lock.txt`). conda `trinity`에는 아무것도 넣지 않았다.
- 후보(사전 고정): `W`(WaveRep 중앙값), `M-full`·`M-face_roi`·`M-face_motion`(LightGBM 고정 설정), `W+M`(dev AUC가 가장 높은 M), `W+M+S`(SyncNet 세 값 추가). 단순 평균은 넣지 않았다.
- 결합: 표준화 + L2 로지스틱 회귀(C=1). 하이퍼파라미터 탐색 없음.
- 보정: sigmoid. 리포트에 Brier와 ECE.
- 한계: MotionPhys의 OOF와 결합 모델의 교차 적합이 같은 폴드를 쓴다. 완전한 중첩 교차 검증은 아니다.

## 압축 조건 (2026-11-17 사용자 결정)

근거: 본인 촬영 영상 3개의 압축 견고성 실측(`docs/robustness-selfvideo.md`, 2안). 그 문서의 한계(진짜 3개, 가짜 없음)를 그대로 지닌 결정이다.

| 역할 | 조건 | 설정 |
|---|---|---|
| dev(임계값·후보 선택) | `original`, `x264-crf28-720p` | `configs/training.json`의 `dev_compression_conditions` |
| **최종 평가 전용**(학습·압축 증강·모델 선택·임계값·dev에 쓰지 않는다) | `x264-crf34-source`, `x264-crf34-720p`, `x264-crf20-source` | `held_out_compression_profiles`. train·dev에 이 프로파일의 행이 있으면 학습이 거부된다. 원본 짧은 변이 1080px(또는 모름)이라 같은 바이트가 될 수 있는 1080p 파생본(`x264-crf34-1080p`, `x264-crf20-1080p`)이 train·dev에 있어도 거부된다(감사 A3, Gate가 읽은 부모 영상 크기로 판단). dev 조건에 넣으면 설정 검사가 거부한다. **test 관문에 넣지 않는다**(2026-11-18 결정, 감사 A15). 리포트의 후보별 `test_held_out`에 탐지 지표(AUC·TPR·FPR와 CI)와 판정 제공 비율을 관문 뒤 1회 보고하고, 표에 "관문 뒤 1회 보고, 채택 판단에 사용하지 않음"을 적는다 |
| 운영 범위 밖(따로 보고) | 480p 세 개(`x264-crf20-480p`, `x264-crf28-480p`, `x264-crf34-480p`) | `out_of_range_compression_profiles`. 짧은 변 480px는 WaveRep의 최소 504px보다 작아 `unsupported_input`이다. WaveRep이 들어간 후보는 이 조건에서 전부 보류가 되므로 dev·test 관문의 탐지 지표에 섞지 않고, 리포트의 `test_out_of_range`에 판정 제공 비율·보류 사유만 따로 적는다(감사 A6에서 코드로 옮김). dev 조건·최종 평가용 목록과 겹치면 설정 검사가 거부한다 |

- 남은 프로파일(`x264-crf20-720p`, `x264-crf28-source`, `x264-crf28-720p`, `1080p` 세 개)은 train의 압축 증강에 쓸 수 있다. `1080p` 프로파일은 짧은 변이 1080px인 원본에서 `source`와 같은 출력을 낸다(`docs/compression-emulator.md` §5). 그런 원본에서 `x264-crf34-1080p`·`x264-crf20-1080p`는 최종 평가 전용과 같은 파일이 되므로 **train 증강에도 쓰지 않는다**(최종 평가와 같은 바이트를 학습에 넣지 않기 위해서다).
- dev는 두 조건을 합쳐 임계값을 **하나** 정한다. 조건별 실제 FPR은 5%가 아니며 리포트의 "압축 조건별" 표에서 따로 읽는다.
- 이 목록은 학습을 시작하기 전에 고정한 것이다. 바꾸면 그 사실과 이유를 결과 보고에 적고, 바뀐 조건을 "미사용 압축 조건"이라고 부르지 않는다.

## 채택 판단 (`configs/training.json`의 `adoption`, 2026-11-16 사용자 승인)

후보 선택은 dev AUC로만 한다. test는 선택이 끝난 뒤 한 번의 확인 관문이며, 실패해도 다른 후보로 다시 고르지 않는다.

| 판단 | 조건 (test, 그룹 bootstrap 95% CI) |
|---|---|
| **채택 가능** | 결합 후보의 AUC CI 하한 > 0.5, 고정 임계값의 FPR 상한 ≤ 10%, **WaveRep과 단일 최강 후보 각각**에 대한 TPR 차이(짝지은 bootstrap, 두 후보가 모두 점수를 낸 가짜에서)의 CI 하한 > 0, 실제 FPR이 WaveRep보다 2%p 넘게 나쁘지 않음, 판정 제공 비율이 5%p 넘게 줄지 않음 |
| **WaveRep 단독** | 위를 못 넘고, WaveRep의 AUC CI 하한 > 0.5이며 FPR 상한 ≤ 10% |
| **보류** | 그 밖 |

- docs/DESIGN.md §13.3에는 숫자 기준이 없다. G3이 "단일 최강 모델 대비"라서 결합은 WaveRep뿐 아니라 단일 최강도 이겨야 한다.
- TPR·FPR은 점수가 나온 영상만으로 계산한다. 점수가 없는 영상은 판정 제공 비율로 따로 본다.
- **FPR 상한 = 그룹 bootstrap 상한과 Clopper–Pearson 정확 상한 중 큰 값**(2026-11-18 결정, 감사 A10). 정확 상한은 n = test 진짜 그룹 수, k = n × 영상 단위 FPR이다. 리포트에 둘 다 적는다.
  오탐이 0건이어도 진짜 그룹이 36개 미만이면 10%를 넘는다. 영상 FPR이 5%면 진짜 그룹이 약 150개, 2%면 약 70개 있어야 10% 이하가 된다. **실제 데이터의 test 진짜 *그룹* 수를 먼저 확인한다.**
- **TPR 차이는 두 후보가 모두 점수를 낸 가짜에서만 센다**(감사 A17). 한쪽이 어려운 가짜에서 보류해 이득처럼 보이는 것을 막는다. FPR·AUC·판정 제공 비율 차이는 각 후보의 값 그대로다.
- **서빙 후보**(2026-11-18 결정, 감사 A9): 채택 가능이면 dev에서 고른 결합이 선택 후보(primary), WaveRep 단독이면 W다. 선택 후보보다 축이 적은 결합 후보와 W는 대체 후보(fallback)로 검토하며, 서버에서 실제로 쓰일 test 영상(축 성공 패턴이 정확히 그 후보의 축인 영상)에서 AUC CI 하한·FPR 상한과 최소 진짜·가짜 그룹 수(`fallback_min_real_groups`·`fallback_min_fake_groups`, 각 36)를 넘어야 서빙한다. TPR 이득 비교는 하지 않는다.
  판정 제공 비율 관문(결합이 WaveRep보다 5%p 넘게 줄지 않음) 때문에 대체 후보가 쓰일 영상은 많아야 test의 5% 안팎이다. test가 아주 크지 않으면 대체 후보는 최소 그룹 수를 넘지 못해 서빙되지 않는 것이 보통이다.
- shortcut 진단(해상도·fps·길이·오디오 유무만으로 계산한 라벨 AUC)은 경고만 낸다. 코덱은 수집하지 않는다.

## 묶음과 서버 관문 (docs/DESIGN.md §15.3 결정 5·8 보완)

- 묶음: 서버가 쓸 수 있는 후보(`servable_candidates`)의 계수·표준화·보정, 잠근 임계값, MotionPhys 모델, 특징 버전, 데이터 해시, 검증 리포트. `bundle.json`의 digest로 고정한다. 판단이 보류면 만들지 않는다.
- 서버는 digest, 파일 해시, 리포트 판단, 합성 여부, 특징 버전을 확인하고, `training/serving.py`의 규칙으로 고른 후보가 있을 때만 `overall_score`·`verdict_label`을 낸다(2026-11-18 결정, 감사 A9): **선택 후보는 그 축이 모두 성공하고 입력이 모두 있으면 쓴다(다른 축이 더 성공해도)**. 아니면 성공한 축 집합과 정확히 같은 대체 후보를 쓴다. 어긋나면 `null` / `abstained` / `no_valid_fusion_model`이다.
- 축 성공은 서버와 학습이 같은 함수(`serving.successful_axes`)로 정한다. MotionPhys는 서버 축 상태처럼 `full` 변형 기준이라, `full`이 실패한 영상의 다른 변형 특징은 학습·점수에 쓰지 않는다. 학습은 영상별 축 성공을 `availability.csv`에 남긴다.
- **재현 검증**(감사 A16): `python -m training.bundle --run … --report … --manifest … --features … --out …`. 묶음을 만들기 전에 같은 manifest·특징·커밋된 설정으로 새 임시 폴더에서 학습·리포트를 다시 돌려 학습 결과 폴더의 모든 파일과 리포트(`shortcut_diagnostic`·`training_config_matches_committed` 제외)가 같은지 확인한다. 다르면 `not_reproducible`. **한계: `features.jsonl` 자체를 고친 경우는 잡지 못한다**(같은 특징으로 다시 돌리기 때문이다). 그것은 추출을 다시 돌려야 확인된다. 학습 venv가 있어야 묶음을 만들 수 있다.
- 감사(2026-11-18)로 더한 확인(묶음 형식 2): 서버가 읽는 파일(리포트·모델·임계값·MotionPhys 모델)은 모두 digest가 덮는 `files`에 있어야 한다. 판단·서빙 후보는 리포트의 지표를 커밋된 채택 기준으로 다시 계산한 결과와 같아야 한다. 학습 설정이 커밋된 `configs/training.json`과 같아야 한다. 지표 숫자까지 앞뒤가 맞게 고친 위조는 막지 못한다(재현 검증 제안, `docs/audit-training-pipeline.md` A16).
- 새 API 필드와 상태 값은 없다. 판정할 때 채워지는 기존 필드는 §15.3에 적혀 있다.
- 앱은 실제 서버 모드에서 라벨을 숨기는 현재 동작 그대로다.

## 합성 종단 검증 (`tests/test_training_*.py`, `tests/test_fusion_bundle.py`)

| 시나리오 | 결과 |
|---|---|
| 신호 없음(시드 4개) | 전부 보류 |
| 누수 주입 | 학습 거부, 리포트 거부 |
| WaveRep에만 신호 | WaveRep 단독 |
| MotionPhys 한 후보에만 신호 | 그 단일축이 최강, 결합 미채택 |
| 두 축에 신호 | 채택 가능(판단이 도달 가능한지 확인) |
| 검증되지 않은 묶음 11종 | 서버가 거부하고 보류 |

`pytest -q`: 690 passed, 1 skipped(2026-11-16, conda `trinity`. 건너뜀은 LightGBM 없음). 학습 venv가 없으면 학습이 필요한 테스트는 건너뛴다.

## DeepSpeak v2 승인 후 실행 순서

1. [ ] 라이선스(`deepspeak-v2-0-license`) 조항을 읽고 `docs/dataset-access.md`에 요약한다(재배포·파생물·삭제 의무).
2. [ ] 한 행을 열어 `configs/datasets/deepspeak_v2.json`의 `unconfirmed` 필드를 확인·수정하고 `status`를 `verified`로 바꾼다.
3. [ ] 메타데이터를 JSON Lines로 내보낸다(공식 분할 이름을 `split` 열로 붙인다). 영상 바이트는 넣지 않는다.
4. [ ] 어댑터를 실행한다. 누수 검사 통과(인물 ID·원본 계보가 둘 다 없는 행이 있으면 `ungroupable_video`로 멈춘다), 가장 큰 그룹 비중 ≤ 25%, **test의 진짜 그룹 수**(FPR 정확 상한의 n, 위 표)를 확인한다. 실패하면 멈추고 결정한다(재분할하지 않는다).
5. [ ] dev 압축 조건을 정한다(사용자 결정). 필요하면 압축 파생본을 만든다. 최종 평가용 프로파일은 학습 전에 고정한다(`docs/compression-emulator.md`).
6. [ ] 영상 20개 정도로 추출 시간을 재고 전체 소요를 계산한 뒤 전체 추출을 돌린다(끊기면 같은 명령으로 재개).
7. [ ] `configs/training.json`의 `dev_compression_conditions`를 적어 커밋한다.
8. [ ] 학습 → 리포트. 리포트의 관문 표와 shortcut 경고를 읽는다. **test 결과를 보고 설정을 바꿔 다시 돌리지 않는다.**
9. [ ] 판단이 채택 가능 또는 WaveRep 단독이면 묶음을 만들고 `configs/fusion_bundle.json`에 digest를 커밋한다. 보류면 서버는 그대로 둔다.
10. [ ] 외부 평가는 모델·임계값을 고정한 뒤 잠금 해제 절차대로 한 번만 한다(`docs/evaluation-pipeline.md`).

## 하지 않은 것과 미검증

- 실제 데이터의 학습·평가, 실제 성능 수치, 임계값의 실제 FPR.
- 실제 MotionPhys venv에서 묶음의 LightGBM 모델로 margin을 계산하는 경로와, 실제 축이 결합 입력을 넘기는 경로(가짜 축·대역 프로세스로만 확인).
  → 2026-11-19 margin 경로는 실제 두 venv로 확인(학습 쪽 `predict(raw_score=True)`와 비트 단위로 같음, `docs/motionphys-adapter.md` "LightGBM margin 일치 확인"). 실제 축이 결합 입력을 넘기는 Worker 종단은 여전히 미검증.
- 대량 추출의 시간·디스크, HiDF, 유형별 표본이 적을 때의 보고 규칙, latency·메모리 집계(docs/DESIGN.md §13.1).
- 앱에서의 라벨 표시(G4 뒤 별도 결정).
