# 학습 파이프라인·서버 관문 독립 감사 (2026-11-18)

브랜치 `audit/training-pipeline`(main `157125f`에서 분기). 감사자: Claude(이 코드를 처음 본 상태에서 시작).

> **실제 데이터로 확인한 것이 아니다.** 모든 재현은 합성 데이터(`training.synth`)와 가짜 축·가짜 프로세스로 했다.
> 표의 숫자는 어떤 모델의 성능도 아니다.

## 범위와 방법

- 읽은 것: `AGENTS.md`, `docs/training-pipeline.md`, `docs/HANDOFF.md` 상단, docs/DESIGN.md §10·§13·§15.3, `configs/training.json`, `configs/fusion_bundle.json`.
- 감사한 코드: `training/`, `research/training/train.py`, `server/fusion/`, `server/axes/alignment/report.py`, `server/jobs/worker.py`.
  서버·학습 불일치를 보려고 `server/axes/{signal,physics,alignment}`와 `research/motionphys/infer_axis.py`도 읽었다.
- 목표: (가) 검증되지 않았거나 부정하게 얻은 성능의 모델이 서버에서 판정을 내는 경로, (나) 나중에 성능 수치를 무효로 만들 결함.
- 방식: 발견마다 재현 테스트를 먼저 쓰고(`tests/test_audit_training_pipeline.py`, 테스트 이름의 `A<번호>`), 고칠 수 있으면 최소 수정 후 통과를 확인했다.
  설계 결정이 필요한 것은 고치지 않고 **지켜야 할 성질을 `xfail(strict=True)` 테스트로 남겼다**. 고치면 XPASS로 실패하므로 그때 표시를 지운다.
  A15는 어느 쪽으로 정할지가 결정 사항이라 성질 대신 지금 동작을 고정한 보통 테스트로 남겼다(결정하면 고친다).
- 고친 발견의 재현 테스트는 수정 전 코드에서 모두 실패했다(21개 실패 확인, 실패 이유가 의도한 것인지 하나씩 확인).

## 요약

| 심각도 | 고침 | 제안만(설계·결정 필요) |
|---|---|---|
| 높음 | A1 리포트 위조 수락, A2 사전 고정 설정 미확인 | A9 서빙 모집단 ≠ 검증 모집단 |
| 중간 | A3 1080p 쌍둥이, A4 장치 대체, A5 digest 밖 파일, A6 480p 혼입, A7 잠금 별칭, A8 같은 바이트 | A10 FPR 상한 퇴화, A11 묶을 수 없는 영상, A15 최종 평가 프로파일의 관문 포함(결정 대기), A16 숫자까지 고친 위조 |
| 낮음 | A12 숫자 ID 표기, A13 q75 서버 미지원, A14 SyncNet 규칙 판 | A17 서로 다른 집합의 TPR 차이 |

> **2026-11-18 결정 반영(브랜치 `audit/decisions`):** 제안만 했던 A9·A10·A11·A15·A16·A17을 사용자 결정대로 구현했다.
> A7의 남은 부분(MAVOS-DD 파일 해시)은 보류. 아래 표의 "결과" 칸과 "결정 반영" 절을 본다.

## 발견 표

재현: `conda activate trinity && pytest -q tests/test_audit_training_pipeline.py -k A<번호>` (학습이 필요한 것은 `research/training/.venv`가 있어야 돈다).

### 높음

| # | 발견 | 공격·재현 | 결과 |
|---|---|---|---|
| A1 | **검증 리포트를 고치면 서버가 받아들였다.** 묶음 생성(`bundle.create`)과 서버(`bundle.load`)는 리포트의 `decision` 문자열과 `servable_candidates` 목록만 믿었다. (1) 관문을 넘지 않은 `W+M+S`를 리포트 서빙 목록과 묶음에 끼워 넣고 파일 해시·digest를 다시 맞추면, 세 축이 모두 성공한 요청에 서버가 `assessed`를 냈다. (2) 신호 없는 데이터의 **보류** 리포트를 문자열만 "WaveRep 단독"으로 바꾸면 묶음이 만들어졌다 | `test_A1_report_listing_an_ungated_candidate_as_servable_is_rejected`, `test_A1_hold_report_forged_to_waverep_only_cannot_become_a_bundle` | **고침.** `decision.rederive`가 리포트에 적힌 dev·test 지표와 커밋된 채택 기준으로 선택·관문·판단을 다시 계산한다. `create`와 `load` 모두 결과가 리포트의 판단·서빙 후보·선택과 다르면 `report_inconsistent`로 거부한다 |
| A2 | **사전 고정 설정과 다른 설정으로 학습해도 통과했다.** `train.py --config`는 아무 파일이나 받고, 리포트는 run 폴더의 `train_meta.json`에 든 설정(채택 기준 포함)으로 판단했다. 묶음·서버는 이를 커밋된 `configs/training.json`과 견주지 않았다. 채택 기준을 느슨하게 바꾼 설정(AUC CI 하한 > 0, FPR CI 상한 ≤ 100%)으로 학습하면 리포트가 채택을 내고 묶음이 만들어졌다 | `test_A2_run_trained_with_uncommitted_config_cannot_become_a_bundle`, `test_A2_server_rejects_bundle_when_committed_training_config_changes` | **고침.** 리포트에 `training_config_matches_committed`를 싣고 다르면 Markdown 맨 위에 경고한다. 묶음은 학습 설정이 커밋된 설정과 같을 때만 만들고 본문에 `training_config`를 넣는다(묶음 형식 2). 서버는 `Settings.training_config_path`(기본 `configs/training.json`)를 읽어 묶음의 설정과 다르면 `config_not_committed`로 보류한다. **설정을 바꾸면 묶음을 다시 만들어야 한다** |
| A9 | **서버가 판정하는 영상 집단이 검증한 집단과 다르다.** 서버는 성공한 축 집합과 *정확히 같은* 후보만 쓴다(§15.3 결정 5·8 보완 (5)). 그런데 리포트는 각 후보를 "그 후보의 입력이 모두 있는 test 영상"에서 검증한다. 예: "WaveRep 단독" 묶음의 `W`는 test 전체(WaveRep 점수가 있는 영상)에서 FPR을 확인했지만, 서버에서는 **physics와 alignment가 모두 실패한 영상에서만** 판정한다. 결합 `W+M`도 alignment가 실패한 영상에서만 쓰인다. 추적 실패·짧은 구간처럼 다른 축이 실패하는 영상은 품질이 낮은 쪽으로 치우칠 수 있어, 고정 임계값의 FPR이 그 집단에서 유지된다는 근거가 없다 | `test_A9_*` 4개 | **결정 반영(2026-11-18).** 선택 후보는 축이 모두 성공하고 입력이 있으면 사용, 대체 후보는 자기 서빙 집단에서 따로 검증 + 최소 그룹 수. 아래 "결정 반영" |

### 중간

| # | 발견 | 공격·재현 | 결과 |
|---|---|---|---|
| A3 | **최종 평가 전용 압축과 같은 바이트가 train에 들어갈 수 있었다.** 문서는 짧은 변 1080px 원본의 `x264-crf34-1080p`·`x264-crf20-1080p`가 최종 평가 전용 `x264-crf34-source`·`x264-crf20-source`와 같은 파일이라 train에 쓰지 않는다고 적지만, `train.py`는 프로파일 ID만 비교했다. 1080p 원본으로 만든 `x264-crf34-1080p` 파생본이 train·dev에 있어도 학습했다 → 최종 평가의 "학습에 쓰지 않은 압축" 결과가 무효가 된다 | `test_A3_train_refuses_1080p_twin_of_held_out_profile[1080/None/1440]`, `test_A3_profile_equivalence_rule` | **고침.** `profiles.may_equal_output`(나머지 설정이 같고 실제 출력의 짧은 변이 같으면 같은 출력)과 `train.py`의 `_held_out_twins`. 부모 영상의 짧은 변은 Gate가 읽은 `media`로 판단하고, **모르면 같을 수 있다고 보고 거부**한다. 1440px 원본의 1080p 파생본은 허용된다 |
| A4 | **MPS→CPU 대체를 감지하지 않았다.** 결정 9 보완은 "CPU와 MPS 특징은 다른 것으로 취급한다"지만, 특징 버전은 *설정한* 장치만 담고 실제 장치(`device_used`)는 보지 않았다. MPS를 못 써 CPU로 대체되면 추출은 MPS 버전 특징으로 섞어 저장하고, 서버는 MPS로 학습한 묶음의 임계값을 CPU 점수에 적용했다(SyncNet은 `device_used`를 추출 결과에 남기지도 않았다) | `test_A4_server_withholds_waverep_input_when_device_fell_back`, `..._syncnet_...`, `test_A4_extract_does_not_label_fallback_features_with_requested_device` | **고침.** 서버: WaveRep·SyncNet의 `device_used`가 설정과 다르면 결합 입력을 넘기지 않는다(축 상태·API는 그대로, 판정은 보류). 추출: 같은 경우 `error`/`device_mismatch`로 남기고 캐시하지 않는다. 캐시에서 읽은 completed 결과도 장치가 설정과 다르면(장치 확인 전에 쓴 캐시 포함) 다시 계산한다(`test_A4_extract_recomputes_cached_result_from_another_device`) |
| A5 | **digest가 서버가 읽는 파일을 다 덮지 않았다.** `bundle.load`는 `files`에 적힌 파일만 해시를 확인하고, 실제로 읽는 `report.json`·`models/<후보>.json`·`thresholds/<후보>.json`·MotionPhys 모델이 `files`에 있는지는 확인하지 않았다. `files`에서 뺀 묶음을 한 번 고정하면 그 뒤 계수를 마음대로 바꿀 수 있었다. `motion_variant`에 경로(`../../..`)를 넣어도 받아들였다(MotionPhys 어댑터가 변형 이름을 다시 검사해 실제 실행은 막혔다) | `test_A5_every_file_the_server_reads_is_covered_by_the_digest[3종]` | **고침.** 읽는 파일이 `files`에 없으면 `file_not_pinned`. `motion_variant`는 세 변형 중 하나이고 모델 파일·축과 일치해야 한다. 후보의 축이 모델 파일과 다르면 거부 |
| A6 | **480p(운영 범위 밖)가 test 관문 지표에 섞였다.** 문서(“압축 조건”)는 480p를 탐지 지표에 섞지 않고 판정 제공 비율·실패율만 따로 보고한다고 정했지만, 리포트는 test 전체로 관문을 계산했다. WaveRep이 없는 단일 후보(`M-*`)는 480p에서도 점수를 내므로 "결합 − 단일 최강" TPR 비교와 판정 제공 비율이 다른 조건 위에서 계산됐다 | `test_A6_out_of_range_480p_is_excluded_from_test_gates_and_reported_separately`, `test_A6_config_requires_...` | **고침.** `configs/training.json`에 `out_of_range_compression_profiles`(480p 세 개, 2026-11-17 결정을 그대로 옮김). 리포트는 이 조건을 test 관문에서 빼고 후보별 `test_out_of_range`(영상 수, 판정 제공 비율, 보류 사유만)와 Markdown 절로 따로 적는다. `test_gate_compression_conditions`로 관문에 들어간 조건을 밝힌다. dev 조건·최종 평가용 목록과 겹치면 설정 검사가 거부 |
| A7 | **잠금 대상 외부 평가 자료를 다른 이름으로 넣으면 통과했다.** `hygiene`는 `dataset_id`가 잠금 키(`mavos-dd`)와 정확히 같을 때만 막았다. `mavos_dd`·`MAVOS-DD`로 train에 넣으면 통과했다 | `test_A7_locked_external_dataset_under_alias_id_is_a_leak` | **고침(일부).** 대소문자·기호를 무시한 이름이 잠금 대상과 같으면 `external_dataset_alias_in_internal_split` 오류. **남은 것:** 이름을 아예 바꾸면 막지 못한다. 외부 표본 목록에 파일 해시가 없어 내용 비교가 불가능하다(제안 A7) |
| A8 | **같은 바이트의 원본이 여러 분할에 있어도 몰랐다.** 어댑터는 영상을 열지 않아 원본 행의 `file_hash`가 비어 있고, 추출기는 sha256을 계산하지만 비교하지 않았다. 데이터셋 안의 중복 파일(이름만 다름)이 train과 test에 나뉘면 누수다 | `test_A8_extract_records_input_hash_for_rows_without_manifest_hash`, `test_A8_train_refuses_same_bytes_in_two_splits` | **고침.** 추출기가 `features.jsonl`에 `input_sha256`을 쓰고, `train.py`가 manifest의 `file_hash`와 함께 보아 여러 분할에 걸친 해시가 있으면 거부 |
| A10 | **오탐 0건이면 FPR 상한 관문이 표본 수와 무관하게 통과한다.** 그룹 백분위 bootstrap은 test 진짜 영상에서 오탐이 0건이면 모든 재표본의 FPR이 0이라 CI 상한이 0이 된다. 진짜 20개(20그룹)·오탐 0건도 "FPR CI 상한 ≤ 10%"를 통과한다. 정확(Clopper–Pearson) 95% 상한은 16.8%이고, 오탐 0건으로 10% 이하를 보이려면 서로 독립인 진짜 영상이 최소 36개 필요하다. 문서가 말한 "FPR 관문은 진짜 영상 수에 민감하다"는 오탐이 1건 이상일 때만 성립한다 | `test_A10_*` 10개 | **결정 반영(2026-11-18).** FPR 관문 = max(그룹 bootstrap 상한, Clopper–Pearson 정확 상한(n = 진짜 그룹 수, k = n × 영상 단위 FPR)) |
| A11 | **인물 ID도 확인된 원본 계보도 없는 영상은 혼자 그룹이 된다.** DeepSpeak 진짜 영상의 녹화 ID는 카드에 없어 `unknown:<경로>`가 되고 인물 ID로만 묶인다(문서에 적힌 한계). 그 행의 인물 ID까지 비면 어디에도 이어지지 않아 같은 인물의 가짜와 다른 분할에 갈 수 있는데, `identity_missing`·`source_unverified` 경고만 남는다 | `test_A11_video_without_identity_or_verified_source_is_an_error_before_training` | **결정 반영(2026-11-18).** 내부 분할의 그런 행은 `ungroupable_video` 오류 |
| A15 | **최종 평가 전용 압축 프로파일이 test 관문 계산에 들어간다(결정 대기).** test 분할의 `x264-crf34-source` 등 행이 채택 판단(G2·G3·FPR 관문)에 섞인다. 관문은 한 번만 쓰고 다시 고르지 않으므로 그 자체로 수치가 낙관적으로 치우치지는 않지만, 그 조건이 "모델 채택 판단에 쓰지 않은 최종 평가"인지는 정해야 한다 | `test_A15_held_out_profiles_are_reported_once_after_the_gate_not_used_for_adoption` | **결정 반영(2026-11-18).** test 관문에서 빼고 `test_held_out`에 탐지 지표·CI·판정 제공 비율을 관문 뒤 1회 보고("채택 판단에 사용하지 않음") |
| A16 | **지표 숫자까지 앞뒤가 맞게 고친 리포트는 A1의 재계산으로도 걸러지지 않는다.** 리포트·점수 파일·모델 JSON은 서명이 아니라 스스로 계산한 해시다. 보류 리포트의 W test AUC CI·FPR CI를 고치고 판단을 그 숫자로 다시 계산해 넣으면 묶음이 만들어진다 | `test_A16_report_with_consistently_forged_metrics_cannot_become_a_bundle`, `test_A16_tampered_run_folder_is_not_reproducible` | **결정 반영(2026-11-18).** 묶음 생성 전 재현 검증(`not_reproducible`). `features.jsonl` 위조는 못 잡는다 |

### 낮음

| # | 발견 | 공격·재현 | 결과 |
|---|---|---|---|
| A12 | 어댑터가 인물·녹화 ID를 `str()`로만 바꿔, 결측이 섞인 정수 열을 JSON Lines로 내보내면 생기는 `12.0`과 `12`가 다른 인물이 됐다(같은 인물의 진짜·가짜가 다른 그룹 → train/dev에 나뉠 수 있음). NaN은 `"nan"` 인물 하나로 모든 결측을 묶었다 | `test_A12_numeric_identity_written_as_float_still_links_real_and_fake` | **고침.** 정수인 float은 정수로, NaN·무한대는 결측으로 |
| A13 | 설정은 `waverep_score`로 `logit_q75`를 허용하지만 서버는 중앙값·평균만 계산해, q75 묶음은 서버에서 언제나 보류였다(안전한 쪽 실패). 서버와 학습이 집계를 각자 계산했다 | `test_A13_server_waverep_input_equals_training_feature_for_every_allowed_aggregate[3종]` | **고침.** `waverep.aggregate_logits`를 서버 결합 입력과 학습 특징이 함께 쓴다 |
| A14 | SyncNet 짧은 구간 규칙(2026-11-17)은 특징 버전·캐시 키에 들어가지 않았다. 규칙을 바꿔도 옛 규칙의 캐시·묶음이 "같은 버전"으로 통과한다(지금은 실제 SyncNet 캐시가 없어 영향 없음) | `test_A14_syncnet_status_rule_is_part_of_feature_version` | **고침.** `report.STATUS_RULE`을 특징 버전(`syncnet.status_rule`)과 캐시 키에 넣었다. **특징 버전이 바뀌었으므로 이전에 추출한 SyncNet 캐시는 다시 계산된다** |
| A17 | "결합 − 단일 최강" TPR 차이는 두 후보가 각자 점수를 낸 서로 다른 영상에서 계산되고, 판정 제공 비율 관문은 WaveRep 대비만 있다. 결합이 어려운 가짜에서 보류하면 함께 점수를 낸 영상에서 똑같아도 TPR 이득으로 보인다 | `test_A17_tpr_gain_is_not_produced_by_abstaining_on_hard_fakes` | **결정 반영(2026-11-18).** TPR 차이는 두 후보가 모두 점수를 낸 가짜에서 계산 |

## 결정 반영 (2026-11-18, 브랜치 `audit/decisions`)

| # | 결정 | 구현 |
|---|---|---|
| A9 | (나) 선택 후보는 "그 후보의 입력이 모두 있으면 사용". 대체 후보는 서버에서 실제로 쓰일 test 영상(축 성공 패턴이 정확히 같은 영상)에서만 검증하고, 진짜·가짜 그룹 수가 최소값보다 적으면 서빙하지 않음. 대체 후보 관문은 자기 관문 + 최소 그룹 수(TPR 이득 비교 없음). 최소값 36·36 | 공용 규칙 `training/serving.py`(`successful_axes`, `choose`)를 서버(`fusion.fuse`, `Bundle.choose`)·학습(`train.py`)·리포트가 함께 쓴다. 학습은 서버 축 상태 기준(MotionPhys `full`)으로 축 성공을 정해 성공하지 않은 축의 값을 입력·적합에 쓰지 않고, `availability.csv`에 남긴다. 리포트는 대체 후보마다 `serving`(서빙 집단 평가와 관문)을, 판단은 `primary`·`fallbacks_considered`를 싣는다. 묶음 형식 3은 후보마다 역할(primary/fallback)을 적고 로드할 때 리포트와 견준다. 설정 `adoption.fallback_min_real_groups`·`fallback_min_fake_groups` = 36 |
| A10 | (b) FPR 관문 = max(그룹 bootstrap 상한, Clopper–Pearson 상한), n = 진짜 그룹 수, k = n × 영상 단위 FPR. 리포트에 둘 다 | `metrics.clopper_pearson_upper`(표준 라이브러리, 정규화 불완전 베타 + 이분법. scipy 값과 상대 오차 1e-9 이내), `overall.fpr_exact_upper`, `decision.fpr_upper`. Markdown 표에 "FPR 정확 상한(진짜 그룹 수)" 열 |
| A11 | 인물 ID와 확인된 원본 계보가 둘 다 없는 행은 학습 전 오류 | `hygiene`의 `ungroupable_video`(train·dev·test만, external 제외) |
| A15 | (나) 최종 평가 전용 프로파일은 test 관문에서 빼고 관문 뒤 따로 1회 보고. 탐지 지표(AUC·TPR·FPR와 CI)까지 싣고 "관문 뒤 1회 보고, 채택 판단에 사용하지 않음"을 표에 명시. 480p는 판정 제공 비율만 | 리포트 후보별 `test_held_out`(`used_for_adoption: false`), 최상위 `held_out_compression_profiles`, Markdown 절 "최종 평가 전용 압축 조건 (test, 관문 뒤 1회 보고, 채택 판단에 사용하지 않음)" |
| A16 | (나) 묶음 생성 전 같은 manifest·features·커밋된 설정으로 새 폴더에서 학습·리포트를 다시 돌려 비교. features.jsonl 위조는 못 잡는다는 한계를 문서에 | `training.bundle.reproduce`. CLI에 `--manifest`·`--features` 필수. 학습 결과 폴더의 **모든 파일**과 리포트(`shortcut_diagnostic`·`training_config_matches_committed`만 빼고)를 비교, 다르면 `not_reproducible`. 묶음 본문에 `reproduction`(파일 수, 트리 해시) |
| A17 | TPR 차이를 두 후보가 모두 점수를 낸 영상에서 | `paired_difference`의 TPR(`basis: both_scored`). FPR·AUC·판정 제공 비율 차이는 그대로 |

**결정 전 확인한 것:**
- 학습·리포트는 결정적이다. 같은 입력으로 두 번 학습하면 산출물 28개가 바이트 단위로 같고 리포트도 같다(A16의 전제).
- A10의 처음 지시 공식(k = 오탐이 있는 *그룹* 수)은 그룹당 진짜 영상이 m개일 때 영상 FPR 5%에서 상한이 (m=2, 그룹 1,000개) 11.8%, (m=4) 21.0%라 관문이 사실상 통과 불가능했다. 그래서 (b)로 정했다.

**결정이 낳은 결과(알아 둘 것):**
- **FPR 관문은 test 진짜 *그룹* 수가 충분해야 넘는다.** 영상 FPR 5%면 그룹 약 150개, 2%면 약 70개에서 정확 상한이 10% 밑이 된다. 합성 테스트의 "채택에 도달" 시나리오는 인물 1,000명(test 진짜 그룹 약 100개)과 테스트 설정의 목표 FPR 2%로 바꿨다(커밋된 설정은 5% 그대로).
- **대체 후보는 드물게 서빙된다.** 결합 채택에는 "판정 제공 비율이 WaveRep보다 5%p 넘게 줄지 않음"이 필요하다. 그래서 결합의 축이 실패해 대체 후보가 쓰일 영상은 많아야 test의 5% 안팎이고, 최소 그룹 수 36과 FPR 정확 상한을 넘기 어렵다. 그런 영상은 보류된다. 묶음 테스트는 대체 후보 경로를 시험하려고 테스트 설정에서만 `max_coverage_drop`을 0.6으로 풀었다.
- 선택 후보가 다른 축이 더 성공한 영상에서도 쓰이므로, 예전 테스트 "세 축이 다 성공하면 2축 모델을 쓰지 않고 보류"는 "W+M으로 판정"으로 바뀌었다.
- 묶음 형식 3, 리포트 형식 3이다. 형식 2 묶음은 거부된다(아직 커밋된 묶음은 없다).

## 제안(감사 당시 기록. 2026-11-18 결정은 위 절)

- **A9 (높음) 서빙 모집단 검증.** 둘 중 하나를 §15.3에 정한다.
  (가) 지금 규칙(정확히 같은 축 집합) 유지 + 리포트가 서빙 후보마다 **그 후보가 실제로 쓰일 test 영상**(축 성공 패턴이 정확히 같은 영상)만으로 TPR·FPR·CI를 계산하고, 관문을 그 값으로 본다. 표본이 작으면 그 후보는 서빙하지 않는다.
  (나) 규칙을 "선택된 후보의 입력이 모두 있으면 그 후보"로 바꾼다. 그러면 선택 후보의 서빙 집단이 검증 집단과 같아진다. 대체 후보(W 등)는 (가)처럼 자기 서빙 집단에서 따로 검증한다.
  어느 쪽이든 학습 쪽 "축 성공"이 서버의 축 상태와 같은 기준이어야 한다(예: MotionPhys는 서버 축 상태가 `full` 변형을 따르는데 학습은 변형별 특징 유무만 본다).
- **A10 (중간) FPR 상한.** 오탐 0건이면 백분위 bootstrap이 쓸모없다. 정확(Clopper–Pearson) 상한을 함께 보고 둘 중 큰 값으로 관문을 보거나, 그룹 수 기준 최소 표본(오탐 0건이면 독립 진짜 ≥ 36)을 관문에 더한다. 결정 16(그룹 bootstrap)을 바꾸는 일이다.
- **A11 (중간)** 인물 ID와 확인된 원본 계보가 모두 없는 영상을 학습 전 오류로 하거나, 그 비율 상한을 둔다. DeepSpeak 승인 후 실제 행을 보고 정한다(`docs/training-pipeline.md` "DeepSpeak v2 승인 후 실행 순서" 2번).
- **A7 (중간, 남은 부분)** MAVOS-DD 표본 목록(`manifest-q20.csv`)에 파일별 sha256을 넣으면, 학습이 `input_sha256`(A8)과 교차해 이름을 바꾼 외부 자료도 막을 수 있다. 잠금 목록의 해시가 바뀌므로 잠금 절차를 따라야 한다.
- **A15 (결정 대기)** 최종 평가 전용 프로파일을 test 관문에서 뺄지. 빼면 관문은 학습·dev와 같은 압축 분포만 보고, 최종 평가 프로파일은 관문 뒤 한 번만 보고한다. 넣으면(지금) 관문이 보수적이 되지만 "채택 판단에 쓰지 않은 최종 평가"라고 부를 수 없다.
- **A16 (중간) 재현 검증.** 학습은 결정적이다(고정 시드, LightGBM `deterministic`). 묶음을 만들기 전에 같은 manifest·특징·커밋된 설정으로 학습·리포트를 다시 돌려 모델·임계값·리포트 해시가 같은지 확인하는 단계를 `training.bundle`에 넣는다. 서버는 데이터가 없으므로 이 확인은 묶음을 만드는 쪽에서만 할 수 있다.
- **A17 (낮음)** TPR 차이를 두 후보가 모두 점수를 낸 영상에서 계산하거나, 단일 최강 대비에도 판정 제공 비율 관문을 둔다.

## docs/DESIGN.md §15.3 문구 (2026-11-18 승인, README에 반영함)

결정 5·8 보완의 서버 조건 (1)~(5)에 이어 다음을 docs/DESIGN.md §15.3 "결정 5·6·7·8·12 보완(독립 감사 결정) — 2026-11-18"에 적었다. A9·A10·A11·A15 결정도 같은 항목에 있다.

> (6) 묶음의 학습 설정이 저장소에 커밋된 `configs/training.json`과 같다. 설정을 바꾸면 그 묶음은 쓰지 않고 다시 학습·검증한다.
> (7) 검증 리포트의 판단과 서빙 후보는 리포트에 적힌 dev·test 지표를 그 설정의 채택 기준으로 다시 계산한 결과와 같다.
> (8) 서버가 읽는 묶음 파일은 모두 digest가 덮는다.
> (9) WaveRep·SyncNet이 설정과 다른 장치로 대체되어 실행되면 그 값은 결합 입력으로 쓰지 않는다(결정 9 보완의 "장치가 다르면 다른 특징").

## 시도했지만 문제없던 공격

| 시나리오 | 공격 | 결과(근거) |
|---|---|---|
| 1 누수 | 파생본의 분할·라벨을 부모와 다르게 | `derived_not_inheriting_parent` 오류(`tests/test_training_datasets.py`) |
| 1 | 공식 분할이 그룹을 쪼갬 | 어댑터가 manifest를 쓰지 않음(재분할하지 않음) |
| 1 | train 두 그룹을 test 행 하나(얼굴 교체)로만 잇기 | 연결 성분 전체가 한 그룹 → `group_spans_splits` |
| 1 | 그룹 키 `unknown:` 원본 | 파일마다 고유 → 인물 ID로만 묶임(인물 ID까지 없으면 A11) |
| 1 | 부모 행이 없는 파생본 | 경고(`derived_parent_missing`). 같은 원본·인물 키로 다른 행과 이어져 있으면 그룹 검사가 잡는다 |
| 1 | 최종 평가 전용 프로파일 행을 train·dev에 | 학습 거부(기존) |
| 1 | 그룹 25% 초과 | 학습 거부(기존) |
| 2 오염 | test의 라벨·특징을 바꿈 | 모델·보정·임계값·선택이 같다(`tests/test_training_train.py`) |
| 2 | 임계값을 dev 밖에서 정하기, 임계값 파일 고치기 | `fit_threshold` 거부, digest 불일치 |
| 2 | 설정에 `threshold_split` 등 모르는 키 | 설정 검사 거부 |
| 2 | dev 조건 빈 목록·중복·오타(dev에 없는 조건)·최종 평가용 포함 | 모두 거부 |
| 2 | external 분할 | 추출·학습·리포트 모두 읽지 않음, 잠금 미등록·잠긴 상태의 평가는 거부 |
| 2 | 후보 선택에 test 사용 | `select_on_dev`는 dev AUC만 본다. 대체 서빙 후보(`W+M` 등)는 test 관문을 각자 넘은 것만이지만 dev에서 고른 결합보다 축이 많은 후보는 넣지 않는다(재선택 없음) |
| 3 우회 | digest 불일치, bundle.json·모델·임계값·MotionPhys 모델·리포트 변조, 합성 묶음, 특징 버전 불일치, 묶음 없음, `bundle_id` 경로(`../b1`, `/`, `.` 시작), 관문을 넘지 않은 후보를 묶음에만 추가 | 모두 보류(`tests/test_fusion_bundle.py` 11종) |
| 3 | 합성 플래그를 지운 묶음 | 합성 특징 버전이 `synthetic`이라 서버 특징 버전과 달라 보류 |
| 3 | 축 부분집합 불일치·입력 결측 | 정확히 같은 후보가 없거나 입력이 하나라도 없으면 보류(0·평균 대체 없음) |
| 3 | Gate 우회 결과 | 묶음을 쓰지 않음 |
| 4 불일치 | SyncNet 짧은 구간 규칙·`fusion_features` | 서버와 학습이 같은 함수(`test_OK4_...`, `tests/test_syncnet_rule_consistency.py`) |
| 4 | WaveRep 중앙값 | 양쪽 모두 `statistics.median`(이제 같은 함수, A13) |
| 4 | MotionPhys margin | 학습·추론 모두 LightGBM 4.7.0·numpy 2.4.6, `predict(raw_score=True)`, 변형이 `completed`일 때만 특징·margin(`test_OK4_motionphys_...`) |
| 5 통계 | 그룹 bootstrap이 행 단위인지 | 그룹 단위 복원 추출(`test_OK5_bootstrap_...`) |
| 5 | 짝지은 차이가 같은 재표본인지 | 같은 후보끼리 차이의 CI가 정확히 [0, 0](`test_OK5_paired_...`) |
| 5 | 한쪽 라벨만 있는 폴드 | 학습 거부. LightGBM 폴드는 건너뛰고 그 영상 점수는 null(0 아님) |
| 6 정직성 | NaN·무한대 점수 | 어댑터가 거부, `Candidate.score`가 None(`test_OK6_...`) |
| 6 | coverage를 정확도처럼 | API `coverage`는 분석량, 리포트는 `verdict_coverage`로 이름을 나누고 주의 문구를 싣는다 |
| 6 | dev 수치를 test처럼 | 리포트 표가 test와 "dev (선택에 쓴 값)"로 나뉜다. 임계값 파일의 `dev_fpr`·`dev_tpr`은 dev라고 적혀 있다 |

## 신호 없는 데이터에서 우연히 채택될 확률 (시나리오 5)

`scripts/audit_null_adoption.py`로 신호가 전혀 없는 합성 데이터(`signal={}`)를 시드마다 새로 만들어 학습 → 리포트 → 판단을 그대로 돌렸다.
설정은 커밋된 `configs/training.json`(n_boot 1,000)에서 dev 압축 조건만 `["original"]`로 바꿨다. 2026-11-18, 한 기기.

| 데이터 | 시드 | test 진짜 영상(그룹) | 결합 채택 | WaveRep 단독 | 보류 | 학습 거부 | W의 AUC CI 하한 > 0.5 | W의 FPR 관문 통과 |
|---|---|---|---|---|---|---|---|---|
| 인물 120명 | 200 | 48개(12그룹) | **0** | **3 (1.5%, 정확 95% CI 0.3~4.4%)** | 194 | 3(폴드에 한쪽 라벨) | 5/197 (2.5%) | 74/197(당시 관문 = bootstrap 상한) |
| 인물 800명 | 37(100 계획, 시간 때문에 중단) | 320개(80그룹) | **0** | **2 (5.4%, 0.7~18.2%)** | 35 | 0 | 2/37 | 미기록 |
| 인물 120명, **결정 반영 후(2026-11-18, main `f9cfcf4`)** | 200(같은 시드 1000~1199) | 48개(12그룹) | **0** | **0 (0%, 정확 95% 상한 1.9%)** | 197 | 3(같은 시드 1013·1143·1195) | 5/197 (2.5%) | 0/197(진짜 12그룹이라 구조적으로 불가) |
| 인물 1,000명, **결정 반영 후(2026-11-19, main `5aa7acf`)** | 100(시드 1000~1099) | 400개(100그룹) | **0 (0%, 정확 95% 상한 3.6%)** | **0 (0%, 정확 95% 상한 3.6%)** | 100 | 0 | 1/100 (1%) | **20/100 (20%, 정확 95% CI 12.7~29.2%)** |

- 결합 채택은 234회 중 0회(정확 95% 상한 1.6%). WaveRep과 단일 최강 **둘 다**에 대한 TPR 이득 CI 하한 > 0이라는 조건이 우연 채택을 막는다.
- "WaveRep 단독"은 신호가 없어도 일정 비율로 나온다. 이 관문은 사실상 W의 AUC에 대한 한쪽 2.5% 검정이고, FPR 상한 관문을 통과할 만큼 test가 크면 그 비율에 가까워진다(120명: FPR 관문 통과 74/197이라 1.5%). 설계대로의 동작이다. 다만 실제 결과 보고에 "신호가 없어도 약 2.5%는 WaveRep 단독이 나온다"를 함께 적는 것이 정직하다.
- 후보 6개 각각의 자기 관문(G2·FPR)만 보면 120명에서 197회 중 18회(9%)는 어떤 후보든 하나가 통과했다(여러 번 비교). 판단은 dev에서 고른 결합과 W만 보므로 판단에 새지는 않았다. 단일축 후보의 test 표를 "통과"처럼 읽지 않도록 주의.
- 800명은 시드당 시간이 길어(약 1분) 37회에서 멈췄다. 비율의 구간이 넓다.
- 위 첫 두 행은 2026-11-18 결정 반영 **전** 코드로 잰 값이다. 셋째 행은 반영 **후** main(`f9cfcf4`)에서 같은 명령(`python scripts/audit_null_adoption.py --identities 120 --seeds 200`, 커밋된 설정, dev 조건만 `["original"]`)으로 다시 잰 것이다. 시드·데이터가 같고(학습 거부 3건도 같은 시드) W의 AUC CI 하한도 197개 시드 모두 같다.
- **결정 반영 후: 결합 채택 0/200, WaveRep 단독 0/200(반영 전 3/197).** 후보 6개 중 자기 관문을 통과한 것이 있는 시드도 18/197에서 **0/197**로 줄었다.
- **이 0은 "우연 채택이 줄었다"는 증거가 아니다.** 120명 데이터의 test 진짜 그룹은 12개라, A10의 정확 상한이 오탐 0건이어도 약 26.5%(진짜 그룹이 36개 이상이어야 10% 이하)라서 FPR 관문을 **구조적으로 넘을 수 없다.** 반영 전 WaveRep 단독 3건은 AUC 검정(5/197 = 2.5%)을 우연히 넘고 bootstrap FPR 상한이 낮았던 경우인데, 지금은 같은 시드가 정확 상한에서 막힌다. 관문이 통과 가능한 크기(진짜 그룹 약 100개 이상)에서의 우연 채택률은 **미측정**이다. 800명 이상 데이터로 다시 재야 한다(이번에는 요청 범위 밖이라 돌리지 않았다). → 2026-11-19 인물 1,000명·시드 100회로 쟀다(아래 "결정 반영 후 1,000명").
- 스크립트가 남기는 `w_fpr_ci_high`는 bootstrap 상한뿐이다(정확 상한과의 max가 아니다). 위 74/197은 그 값 기준의 참고치다. 2026-11-19부터 스크립트는 관문 값(`w_fpr_gate_value` = max(bootstrap 상한, 정확 상한))과 후보별 관문 통과 여부도 남긴다.

**결정 반영 후 1,000명 (2026-11-19, 브랜치 `audit/null-rerun-1000`)**

- 명령: `python scripts/audit_null_adoption.py --identities 1000 --seeds 100 --out data/research/audit-null/identities1000-seeds100`(커밋된 설정, dev 조건만 `["original"]`, n_boot 1,000). 기준은 main `5aa7acf`에 기록 필드만 더한 스크립트다(판단 논리 변경 없음). 2026-11-19 02:04~02:30, 시드당 약 16초, 중간에 멈추지 않았다. 결과 `results.jsonl`은 Git 밖.
- **결합 채택 0/100, WaveRep 단독 0/100, 보류 100/100**(각 정확 95% 상한 3.6%). 학습 거부 0. test는 시드마다 진짜 400개(100그룹).
- **FPR 관문은 이 크기에서 통과할 수 있다.** W의 FPR 관문(고정 임계값의 FPR 상한 = max(bootstrap 상한, 정확 상한) ≤ 10%)은 **20/100** 통과했다. 100회 모두 정확 상한이 bootstrap 상한보다 커서 정확 상한이 관문을 정했다(bootstrap 상한만이면 92/100 통과). 진짜 그룹 100개에서는 test 영상 FPR이 4.0% 이하일 때만 정확 상한이 10% 아래다(통과한 시드의 FPR 최대 4.0%, 실패한 시드의 최소 4.25%). dev에서 5%로 잡은 임계값의 test 영상 FPR은 중앙값 5.1%(1.75~9.75%)였다.
- W의 AUC 관문(AUC CI 하한 > 0.5)은 **1/100**(시드 1098, 하한 0.505)이었고 그 시드는 FPR 관문 값 11.9%로 떨어졌다. 두 관문을 함께 넘은 시드는 0이라 WaveRep 단독도 0이다.
- 결합 쪽: dev에서 고른 결합은 W+M 50회, W+M+S 50회. 고른 결합의 자기 FPR 관문 26/100, 자기 AUC 관문 2/100, 둘 다 1/100. 결합 전용 관문 중 "결합 − WaveRep TPR 차이 CI 하한 > 0"은 3/100, "결합 − 단일 최강"은 1/75(단일 최강이 W여서 이 관문이 없는 25회 제외), 결합 전용 관문을 모두 넘은 시드 0.
- 후보 6개 중 하나라도 자기 관문 두 개를 다 넘은 시드는 7/100(M-full 4, M-face_roi 1, M-face_motion 1, W+M+S 1)이다. 여러 번 비교한 효과이고, 판단은 dev에서 고른 결합과 W만 보므로 판단에 새지 않았다(단일 MotionPhys는 서빙하지 않는다).
- 해석: 관문이 통과 가능한 크기에서도 우연 채택은 100회 중 0이었다. 다만 100회로는 1% 아래의 비율을 가를 수 없다(상한 3.6%). AUC 관문(약 2.5% 검정)과 FPR 관문(이번 20%)이 서로 독립이라고 치면 WaveRep 단독의 우연 비율은 약 0.5%로 예상되지만, **이는 추정이지 측정이 아니다.** 결정 반영 전(bootstrap 상한만, 120명 74/197 통과)과 비교하면 A10의 정확 상한이 FPR 관문을 넘기 어렵게 만든 것이 우연 채택을 줄이는 주된 차이다. 대신 신호가 있는 실제 데이터에서도 진짜 그룹이 약 100개면 test FPR이 4% 이하여야 채택될 수 있다는 뜻이기도 하다.
- 시드당 시간이 이전 기록(800명 약 1분)보다 짧았다. 원인(기기 상태 등)은 확인하지 않았다.


## 고친 파일

| 파일 | 바꾼 것 |
|---|---|
| `training/report/decision.py` | `rederive`, `same_decision`, `comparison_key` (A1) |
| `training/bundle.py` | 묶음 형식 2: `training_config`, 판단 재계산, 읽는 파일의 `files` 포함 확인, `motion_variant`·축 검사 (A1·A2·A5) |
| `server/fusion/__init__.py`, `server/config.py` | 커밋된 학습 설정(`training_config_path`)을 읽어 묶음과 견줌 (A2) |
| `training/report/build.py` | 커밋된 설정 일치 표시, 480p 관문 제외·따로 보고, 관문 조건 목록 (A2·A6) |
| `training/config.py`, `configs/training.json` | `out_of_range_compression_profiles` (A6) |
| `training/emulator/profiles.py`, `research/training/train.py` | 1080p 쌍둥이 거부, 같은 바이트 분할 간 거부 (A3·A8) |
| `training/features/extract.py` | `input_sha256`, 장치 대체 거부, 공통 WaveRep 집계, SyncNet 규칙 판 (A4·A8·A13·A14) |
| `server/axes/signal/__init__.py`, `server/axes/signal/waverep.py` | 장치 확인, 공통 집계 (A4·A13) |
| `server/axes/alignment/__init__.py`, `server/axes/alignment/report.py` | 장치 확인, `STATUS_RULE` (A4·A14) |
| `training/hygiene.py` | 잠금 별칭 (A7) |
| `training/datasets/adapters/__init__.py` | 숫자 ID 정규화 (A12) |
| `tests/test_fusion_bundle.py` | 묶음 고정 테스트가 테스트용 학습 설정을 "커밋된 설정"으로 넘기게 함(A2로 필요) |
| `tests/test_syncnet_rule_consistency.py`, `tests/test_feature_extract.py` | 가짜 SyncNet·WaveRep 결과에 실제 어댑터처럼 설정한 장치를 `device_used`로 넣음(A4로 필요) |
| `tests/test_training_train.py` | "dev에 없는 압축 조건" 예시를 480p에서 `x264-crf28-1080p`로 바꿈(480p는 이제 설정 검사가 먼저 거부, A6) |
| `tests/test_audit_training_pipeline.py`, `scripts/audit_null_adoption.py` | 감사 재현 테스트, 우연 채택률 시뮬레이션(새 파일) |

API 필드·상태 값은 바꾸지 않았다. 서버는 여전히 묶음이 없으면 항상 보류한다(`configs/fusion_bundle.json`은 비어 있다).

## 테스트

- 감사 전(main `157125f`): `pytest -q` **766 passed, 1 skipped**.
- 감사 후(이 브랜치): `pytest -q` **797 passed, 1 skipped, 5 xfailed** (2026-11-18, conda `trinity`, 200초).
  - 건너뜀 1: `tests/test_motionphys_train.py`(trinity에 LightGBM 없음, 감사 전과 같다). 학습이 필요한 테스트는 `research/training/.venv`로 돌았다.
  - xfail 5: A9·A10·A11·A16·A17(제안만 한 발견의 성질). 각각 의도한 단언에서 실패하는 것을 `--runxfail`로 확인했다.
- 감사 테스트 파일만: `pytest -q tests/test_audit_training_pipeline.py`.
- **결정 반영 후(브랜치 `audit/decisions`):** `pytest -q` **815 passed, 1 skipped**(xfail 0). xfail이던 A9·A10·A11·A16·A17은 결정대로 고쳐 보통 테스트가 됐다. 건너뜀은 같은 이유(LightGBM 없음).

## 감사의 한계

- 실제 데이터·실제 모델로 확인하지 않았다. 장치 대체(A4)는 가짜 어댑터 결과로만 확인했다.
- 감사 범위 밖: Gate 내부, 큐·API 보안, 압축 에뮬레이터의 인코딩 결정성, `training/evaluation/run.py`의 일반 평가 명령(`--final-external` 경로는 읽기만 했다).
- 위협 모형: 저장소에 digest를 커밋하는 사람은 믿는다. 그 사람이 보는 리포트가 사실과 다를 수 있는 경로(A1·A2·A16)와 실수로 생기는 누수를 주로 봤다.
