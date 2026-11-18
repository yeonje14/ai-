# MotionPhys 어댑터: physics 축 연결

docs/DESIGN.md §14.1 백로그 10번의 서버 연결 부분. 작성일: 2026-11-16.

> **특징 추출까지만 한다. 점수도 판정도 없다.**
> 학습된 분류기가 없다(DeepSpeak v2 승인 대기). `axes.physics.raw_score`는 항상 `null`이고 종합 판정에 들어가지 않는다.
> 추출기는 논문을 보고 다시 구현한 것이며 숫자 설정은 임시값이다(`docs/motionphys-spec.md`).
> 유효 궤적 수와 추적 성공률은 "얼마나 계산됐는가"이지 진위의 근거가 아니다.

## 구조

| 파일 | 실행 환경 | 역할 |
|---|---|---|
| `server/axes/physics/__init__.py` | conda `trinity` | Worker가 부르는 `run(ctx)`. 축 결과 4개 필드와 설명 한 항목을 만든다 |
| `server/axes/physics/motionphys.py` | conda `trinity` (표준 라이브러리만) | `run_motionphys(video, segments, work_dir, config, on_tick, tick_sec)`. 입력 검사, 프로세스 실행, 타임아웃, 결과 검증, 실패 격리 |
| `research/motionphys/infer_axis.py` | `research/motionphys/.venv` | 기존 `extract.extract()`를 후보 A → B → C 순서로 부르고 요약 JSON을 쓴다 |

- SyncNet·WaveRep 어댑터와 같은 규칙이다. 별도 프로세스, 인자 리스트(`--request`, `--output` 두 경로뿐), `child_process.start_process`/`stop_process`와 supervisor, heartbeat로 lease 연장, 취소·타임아웃·Worker 사망 시 프로세스 그룹 종료, 호출별 임시 폴더 삭제.
- 미디어 경로가 작업 폴더 밖이거나 심볼릭 링크로 벗어나면 실행하지 않는다. stdout/stderr는 저장하지 않는다.
- 서버로 넘어오는 값은 후보별 상태, 원인 코드, 스케일별 유효 궤적 수·움직인 궤적 수, 추적 성공률, 얼굴 검출률뿐이다. **특징 벡터는 넘어오지 않는다.** 형식이 어긋나면(음수·bool·NaN·범위 밖 비율·빠진 후보) 전체를 `inference_error`로 버린다.
- 한 번 실행에 영상을 후보마다 다시 디코딩한다(3회). 줄이지 않았다.
- 단계 제한 시간은 `TRINITY_MOTIONPHYS_TIMEOUT_SECONDS`(기본 300초, 임시값)와 작업의 남은 시간 중 작은 값이다.

## 상태 (결정 3·8 보완, docs/DESIGN.md §15.3)

축 상태는 **후보 A(전체 화면)** 를 따른다. B·C의 실패는 축 상태를 바꾸지 않고 설명에만 적힌다.

| 경우 | `status` | `reason_code` | 프로세스 |
|---|---|---|---|
| A 추출 성공 | `completed` | `null` | 실행 |
| A의 움직인 궤적 부족 | `insufficient_input` | `insufficient_motion` | 실행 |
| A의 끝까지 추적된 궤적 부족 | `insufficient_input` | `tracking_failed` | 실행 |
| 8프레임 이상인 구간 없음 | `insufficient_input` | `segment_too_short` | 실행 |
| 구간 없음 | `insufficient_input` | `no_segments` | 실행 안 함 |
| A 추출 오류, 비정상 종료, 깨진 결과 | `error` | `inference_error` | 실행 |
| 단계 제한 시간 초과 | `error` | `timeout` | 그룹 종료 |
| venv·실행기 없음 | `error` | `model_unavailable` | 실행 안 함 |
| 취소·lease 상실 | (결과를 만들지 않는다. 작업이 `cancelled` 등으로 끝난다) | | 그룹 종료 |

- 모든 경우에 `raw_score = null`, `model_version = "motionphys-reimpl-features-v1"`. `axes.physics`의 필드는 기존 네 개 그대로다. **새 API 필드는 없다.**
- `completed`는 "특징을 계산했다"는 뜻이다. 세 축이 모두 `completed`면 기존 규칙대로 `analysis_status = completed`가 되고, 판정은 `verdict_status = abstained` / `no_valid_fusion_model`이 맡는다. `build_result`는 바꾸지 않았다.
- 분석 가능 기준(스케일마다 유효 궤적 20개, 움직인 궤적 10개)은 추출기의 임시값이다. 임계값을 새로 정하지 않았다.
- 개발용 수동 구간에서도 실행한다(SyncNet과 달리 발화자 확인이 필요 없다). 그 결과는 기존 규칙대로 `gate_bypassed`, `partial`, `abstained`다.

## 설명 항목

특징 요약은 기존 `explanations`에 한 항목으로 들어간다(키는 `template_id`, `reason_code`, `message` 세 개). 종합 보류 설명 바로 뒤에 놓인다. `coverage`는 기존 계산 그대로다.

| 경우 | `template_id` | `reason_code` |
|---|---|---|
| 성공 | `MOTIONPHYS_FEATURES_ONLY` | `unvalidated_condition` |
| 그 밖 | `MOTIONPHYS_NOT_ANALYZED` | 축의 원인 코드 |

문구에는 분석 구간 수와 길이, 후보별 유효 궤적 수(8·12·24프레임 스케일), 추적 성공률(A·B), 얼굴 검출률(C), "종합 판정에 포함하지 않습니다"가 들어간다. 실제 예는 아래에 있다.

## 실제 확인: A를 Worker에 넣기 (2026-11-16, 1회)

- 본인 촬영 영상 `A.MOV`(HEVC 1920×1080, 30fps, 41.0초, 말하는 영상)를 Git 밖 임시 레지스트리에 테스트 ID `TRINITYtest`로 등록했다. FastAPI 테스트 클라이언트로 URL을 요청하고 **별도 Worker 프로세스**(`python -m server.jobs.worker --drain`)가 처리했다. Gate 우회 없음. 모델·임계값 변경 없음.
- 작업 제한만 `TRINITY_JOB_TIMEOUT_SECONDS=1800`으로 늘렸다(SyncNet 소요를 몰랐기 때문). 실제 전체 시간은 506초로 기본 600초 안이었다.

| 단계 | 진입 시각(단조 시계, 요청 후) | 걸린 시간 | 결과 |
|---|---|---|---|
| preprocessing (Gate) | 0.5초 | 약 18초 | 적합 구간 5개, 37.021초 |
| waverep | 18.7초 | 약 26초 | `completed`, 76프레임, **MPS**, 모델 보고 24.7초 |
| motionphys | 44.5초 | 약 61초 | `completed` (A·B·C 모두) |
| syncnet | 105.6초 | 약 400초 | `completed` (CPU) |
| 종료 | 506.1초 | | |

- 결과: `job_status=finished`, `analysis_status=completed`, `verdict_status=abstained`, `abstention_reason=no_valid_fusion_model`, `overall_score=null`, `verdict_label=null`. 세 축 모두 `completed`이고 `raw_score`·`lse_c`·`lse_d`는 `null`이다.
- physics 설명: "MotionPhys 특징 추출을 마쳤습니다(분석 구간 5개, 37.0초). … 전체 화면(A): 유효 궤적 9304/6082/2955개, 추적 성공률 74%/72%/70%. 얼굴 영역(B): 유효 궤적 5500/3599/1746개, 추적 성공률 94%/92%/89%. Face Motion(C): 유효 궤적 2880/1920/960개, 얼굴 검출률 100%. 학습된 분류기가 없어 점수가 없고 종합 판정에 포함하지 않습니다. 진위 판정이 아닙니다."
- lease: motionphys 단계에서 서로 다른 만료 시각 7개, syncnet 단계에서 40개를 관찰했다(기본 heartbeat 10초). 끝난 뒤 작업 폴더가 없었다.
- 같은 요청을 Worker 밖에서 실행기만 돌리면 37.1초였다(`/usr/bin/time`, 1회). Worker 안에서는 약 61초였다. **차이의 원인은 확인하지 않았다.** 처리 시간은 `docs/robustness-selfvideo.md`의 시간표에서 측정 근거와 함께 다룬다.
- 걸린 시간은 1회 측정이고 다른 프로세스가 떠 있는 상태였다. 성능 검증이 아니다.

## 테스트

`tests/test_motionphys_adapter.py`, `tests/test_motionphys_worker.py` (conda `trinity`).

- 가짜 프로세스: 성공, 후보 A의 움직임 부족·추적 실패·짧은 구간, B·C만 실패, A 오류, 비정상 종료·깨진 JSON·잘못된 수치 17가지, 구간 없음·잘못된 구간(실행 안 함), 작업 폴더 밖 경로·심볼릭 링크, 실행 환경 없음, 인자 리스트, 타임아웃과 취소 시 후손 프로세스까지 종료, 시작 전 취소, 대기 중 tick 호출.
- Worker: 축 결과가 스키마의 네 필드뿐인지, 설명 항목의 키가 세 개뿐인지, 세 축 완료 시 `completed`/`abstained`, 실패 4종의 격리(`partial`), lease 연장, 실행 중 취소, **Worker SIGKILL 뒤 그룹 종료와 재시도·재시도 상한·취소 복구**.
- 실제 영상: `data/research/samples/`의 A·B·E와 venv·모델 파일이 있으면 2.0~6.0초 구간으로 세 후보를 실제로 돌린다. 없으면 건너뛴다.
- 다른 테스트가 이 기기의 `research/motionphys/.venv`를 몰래 실행하지 않도록 `tests/conftest.py`가 기본 실행 환경을 없는 경로로 바꾼다. 그래서 physics를 다루지 않는 Worker 테스트에서는 physics가 `error` / `model_unavailable`이다(예전에는 stub의 `insufficient_input`이었다).

## 하지 않은 것과 한계

- 분류기 학습, AUC·TPR 비교, 축 유지/제거 결정(백로그 10번의 완료 조건). 임계값 결정.
- B·E의 Worker 종단 실행, 실제 모델 실행 중의 취소와 Worker SIGKILL(대역 프로세스로만 확인했다), 실제 YouTube ID.
  (2026-11-19: 같은 Worker 경로의 SyncNet 실행 중 SIGKILL·취소와 WaveRep MPS 실행 중 취소는 실제 모델로 확인했다 —
  `docs/syncnet-adapter.md` "실제 Worker 수명주기 확인". **MotionPhys 실행 중의 취소·SIGKILL은 여전히 대역 프로세스로만 확인했다.**)
- 앱의 판단 근거 화면이 새 설명 항목을 어떻게 보여 주는지는 확인하지 않았다(앱 코드 변경 없음).
- MediaPipe 모델 파일의 이용 조건은 여전히 **확인 필요**다(`docs/motionphys-spec.md` §7).

## 재현 방법

환경과 모델 파일 준비는 `docs/motionphys-spec.md` §8.

```bash
conda activate trinity
pytest -q tests/test_motionphys_adapter.py tests/test_motionphys_worker.py
# 실행기만: 요청 JSON은 {"video": 경로, "segments": [[시작, 끝], ...]}
research/motionphys/.venv/bin/python research/motionphys/infer_axis.py --request req.json --output out.json
```

Worker 종단 실행은 `docs/HANDOFF.md`의 "Flutter 실제 서버 모드 A 예행" 재현 명령과 같은 환경 변수(임시 레지스트리, DB, runtime)로 서버 없이 Worker만 띄워도 된다.
