# HANDOFF

마지막 갱신: 2026-11-13 · 브랜치 `feat/waverep-adapter` (커밋함, push 전)

## 백로그 7번: WaveRep 어댑터 (어댑터만 구현함. Gate·Worker 미연결)

속도·재현성 확인이다. 성능 검증이 아니며 점수를 판정에 쓰지 않는다. 테스트 영상에는 발화가 없다. 자세한 수치는 `docs/waverep-adapter.md`.

- **만든 파일**: `server/axes/signal/waverep.py`(`run_waverep`, torch 없음), `research/waverep/infer_frames.py`(추론 프로세스), `research/waverep/frame_sampling.py`(프레임 선택), `scripts/bench_waverep_adapter.py`, `tests/test_waverep_adapter.py`. 원본 코드(`research/waverep/upstream/`)는 수정하지 않았다. trinity 환경에 torch를 넣지 않았다.
- **동작**: 영상과 `[(start, end), ...]` 구간을 받아 프레임별 원시 logit을 돌려준다. 샘플링(`sample_fps` 1·2·4 등, `None`이면 모든 프레임)과 배치(`batch_size`)를 지원한다. `research/waverep/.venv`의 Python을 인자 리스트로 실행하고 결과를 JSON으로 받는다. 실패는 `status=error`와 점수 `null`로 돌려준다. `raw_score`는 `null`(집계 방법 미정), `overall_score`는 다루지 않는다.
- **벤치마크**: 2026-11-12에 CPU 3건을 잰 뒤 배터리 부족으로 중단했고, 2026-11-13에 전원을 연결하고 `--force` 없이 재개해 남은 11건을 끝냈다(저장된 3건은 건너뜀). 14건 모두 `completed`.
- **결과** (본인 촬영 영상 1개, 1080p 313프레임, 10.43초):
  - 어댑터 점수는 스파이크 `cpu-1`과 완전히 같다(최대 절대차 0.0).
  - `pretrained=False`와 `True`의 점수가 완전히 같다(0.0). 빈 HF 캐시 + `HF_HUB_OFFLINE=1`에서 `False`는 동작, `True`는 실패. **기본값을 `pretrained=False`로 했다.**
  - 반복 실행은 완전히 같다(CPU 배치 8, MPS 배치 8). 배치 1 대 8은 CPU 최대 0.000037, MPS 최대 0.00000095. CPU 대 MPS는 최대 0.00019.
  - 샘플링한 프레임의 점수는 모든 프레임 실행의 같은 프레임과 같다(CPU 초당 4장에서만 최대 0.0000062).
  - MPS 모든 프레임: 배치 1이 56.5초(6.2장/초, 드라이버 할당 0.70 GiB, peak footprint 1.10 GiB), 배치 8·16이 86~90초(3.8~4.0장/초, 드라이버 1.70 GiB, footprint 약 2.3 GiB). **기본 배치 크기를 1로 했다**(배치 1은 1회 측정).
  - MPS 샘플링(배치 8) 전체 시간: 초당 1장 8.8초(11프레임), 2장 12.5초(21), 4장 18.0초(42). CPU는 9.0초, 14.7초, 28.6초.
  - CPU 모든 프레임 배치 8(전원 연결): 126.6초, 최대 RSS 1.63 GiB.
- **주의할 점**:
  - 2026-11-12의 CPU 3건(`cpu-all-b1-pretrained` 305.6초, `cpu-all-b1` 223.6초, `cpu-all-b8` 388.8초)은 배터리 부족 상태의 값이다. 같은 설정의 재실행이 126.6초였다. 이 3건의 시간은 다른 실행과 비교하지 않는다(점수 비교에는 썼다). 전원 연결 상태의 CPU 배치 1 시간은 없다. 다시 재려면 `--only cpu-all-b1 --force`.
  - 샘플링 설정에 따라 평균 logit이 -0.67 ~ -1.67로 달라진다. 고른 프레임이 달라서다. 샘플링 간격과 집계 방법은 영상 하나로 정하지 않는다(백로그 8번 이후).
- **실행**:
  ```bash
  conda activate trinity
  pytest -q
  python scripts/bench_waverep_adapter.py --video data/research/samples/<허가 영상>.mp4   # 결과가 있는 실행은 건너뛴다
  ```
  출력은 `data/research/waverep-adapter/`(Git 제외).
- **검증**: `pytest -q` 124개 통과(conda `trinity`, 2026-11-13, 실제 CPU 추론 1건 포함).
- **미검증·확인 필요**: MPS에서 배치 8·16이 배치 1보다 느린 원인, 전원 상태가 CPU 시간에 준 영향, 가변 프레임률 영상의 프레임 시각, 504px 미만 영상의 `unsupported_input` 경로(실제 영상으로 실행 안 함), 발화가 있는 영상·합성 영상에서의 실행.
- **7번에서 남은 일**: Gate 연결(Gate 브랜치 `feat/gate-speech-segments`는 알려진 문제로 main에 합치지 않은 상태), Worker의 `waverep` 단계에 연결, 추론 중 주기적 heartbeat(어댑터는 지금 끝날 때까지 막는다), `analyzed_*` coverage 채우기, stub 값(`stub_not_executed`) 제거, 프레임 logit을 `raw_score`로 집계하는 방법 결정.

## 데이터셋 접근 상태 갱신 (2026-11-13, 저장소 소유자 확인)

- **DeepSpeak v2**: 심사 대기.
- **Deepfake-Eval-2024**: 접근 요청이 **거절됐다.** 거절 사유·통보 날짜·재신청 가능 여부는 확인 필요.
- `docs/dataset-access.md`, README §6.1 표, §14.1 백로그 3번 행에 반영했다.
- **막힌 점**: Deepfake-Eval-2024는 최종 외부 실전 평가 전용 자료였다(README §13.1, 백로그 15번). 지금은 그 자료가 없다. 다른 경로로 받지 않는다. 대체 자료를 정하거나 최종 평가 범위를 줄이려면 README §15.3 결정 6을 먼저 바꿔야 한다. 아직 결정하지 않았고 README의 설계 문구(§6.1 역할, §13)는 그대로 두었다.

## 백로그 1·3번: 접근 기록 문서화 (둘 다 진행 중)

문서만 만들었다. 코드는 바꾸지 않았다.

- **`docs/media-access.md` (백로그 1번)**: 영상 ID·메타데이터 접근과 분석용 미디어 접근의 차이(README §3.1 기준), 임의 YouTube URL은 `analysis_unavailable`로 처리한다는 결정, 허가 미디어 범위(저장소 소유자가 직접 촬영한 본인 영상, 본인 얼굴·음성만, 제3자 없음), 압축 실험에는 휴대폰 원본을 쓴다는 메모.
- **`docs/dataset-access.md` (백로그 3번)**: (2026-11-12 기준. 최신 상태는 위 "데이터셋 접근 상태 갱신") DeepSpeak v2와 Deepfake-Eval-2024는 접근 요청 후 승인 대기, TalkingHeadBench는 접근 방법 확인 필요. 데이터셋별 역할, 확인된 이용 조건, 확인 필요 항목을 나눠 적었다. Hugging Face 공개 API 메타데이터(접근 제한 여부, 라이선스 태그, Deepfake-Eval-2024 이용 조건 문구)를 2026-11-12에 조회해 근거로 썼다. 데이터셋 파일은 받지 않았다.
- **README**: §14.1 백로그 1·3번 행에 상태를 적었다. §6.1 표의 DeepSpeak v2·Deepfake-Eval-2024 상태 칸을 "접근 요청함, 승인 대기"로 바꿨다.
- **검증**: `pytest -q` 72개 통과(conda `trinity`). 문서 변경이라 새 테스트는 없다.
- **확인 필요로 남긴 것**:
  - 두 데이터셋의 신청 날짜(저장소 소유자가 알려 주면 반영), 승인 결과.
  - DeepSpeak v2 라이선스 문서 본문(링크만 확인), TalkingHeadBench의 실제 접근 절차·분할·상위 영상 권리.
  - 본인 채널 영상을 YouTube Studio에서 받을 수 있는지, 받은 파일이 플랫폼 처리본인지.
  - 현재 샘플(`KakaoTalk_Video_…`)의 재압축 여부. 압축 실험(백로그 9번)에는 휴대폰 원본을 새로 옮겨 쓴다.
- **백로그 1번에서 남은 것**: YouTube ID와 연결된 시연용 허가 미디어 등록. 레지스트리에는 여전히 가짜 ID `TRINITYtest`만 있다.
- **백로그 3번에서 남은 것**: 최소 테스트 샘플, 공통 manifest/분할 규칙. 8번은 3번이 끝나야 시작할 수 있다.

## 백로그 5번: WaveRep 단독 추론 스파이크 (완료)

실행 가능성 확인이다. 성능 검증이 아니며, 점수를 진위로 해석하지 않는다. 자세한 수치는 `docs/waverep-spike.md`.

- **환경**: `research/waverep/.venv`(Python 3.11.18), torch 2.15.0 · timm 1.0.31 · opencv-python 5.0.0.93. 버전은 `research/waverep/requirements.lock.txt`에 고정.
- **원본 코드·가중치**: `research/waverep/upstream/`에 clone(커밋 `0fd6010`, 수정하지 않음, Git 제외). `weights_dinov2_G4.ckpt`는 md5가 공개값과 일치.
- **결과** (본인 촬영 영상 1개, 1080p 313프레임): CPU 성공(142초·190초, 최대 RSS 약 1.0 GiB), MPS 성공(122초, peak footprint 1.31 GiB). CPU 2회 점수 완전 일치, CPU↔MPS 프레임 점수 최대 차 0.00019. CUDA 전용 연산과 MPS fallback 경고 없음.
- **가중치 키 대조**: missing 0, unexpected 0, 모양 불일치 0 (177개 키).
- **이용 조건**: `docs/waverep-license.md`. GRIP-UNINA 자체 라이선스로 비영리·정보 목적만 허용, 원 고지 유지, 결과 공개 시 인용.
- **만든 파일**: `research/waverep/run_spike.py`(데모를 서브프로세스로 실행하고 시간·메모리·점수 요약 기록), `research/waverep/check_state_dict.py`(키 대조), `tests/test_waverep_spike.py`. `.gitignore`에 `research/*/upstream/` 추가.
- **실행**:
  ```bash
  research/waverep/.venv/bin/python research/waverep/check_state_dict.py
  research/waverep/.venv/bin/python research/waverep/run_spike.py --video data/research/samples/<파일>.mp4 --device cpu --tag cpu-1
  research/waverep/.venv/bin/python research/waverep/run_spike.py --video data/research/samples/<파일>.mp4 --device mps --tag mps-1
  ```
  환경을 새로 만드는 방법은 `docs/waverep-spike.md` "재현 방법". 출력은 `data/research/waverep-spike/`(Git 제외).
- **검증**: `pytest -q` 72개 통과(conda `trinity`). 추론 4회(cpu-smoke, cpu-1, cpu-2, mps-1) 모두 종료 코드 0.
- **확인 필요로 남긴 것**:
  - 가중치 전용 이용 조건(저장소에 명시 없음), timm DINOv2 기반 가중치와 PyPI 의존성의 라이선스.
  - MPS 최대 메모리: `/usr/bin/time -l` 값이 GPU 할당 전부를 포함하는지 미확인. 백로그 7번 어댑터에서 `torch.mps.driver_allocated_memory()`로 측정.
  - MPS가 CPU보다 크게 빠르지 않은 원인, CPU 2회 실행 시간 차이의 원인(각 1회 측정).
  - 원본 전처리는 가운데 504×504 crop뿐이다. 세로 영상·저해상도 입력에서의 동작은 실행하지 않았다.
  - 원본 데모는 `pretrained=True`라 첫 실행 때 Hugging Face Hub에서 346MB를 받는다. 오프라인 서비스 실행을 위해 어댑터에서 `pretrained=False`로 바꿔도 결과가 같은지.
- **백로그 의존성 메모**: 5번은 원래 3번(데이터셋 접근)에 의존한다. 이번에는 데이터셋 대신 본인 촬영 영상 1개로 실행 가능성만 확인했다.

## 백로그 2번: 환경 스모크 점검 (완료)

- `scripts/check_env.py`를 만들었다. Python·아키텍처·Rosetta, ffmpeg/ffprobe/libx264, PyTorch CPU/MPS(실제 행렬곱), OpenCV, LightGBM을 점검한다. 아무것도 설치하지 않는다. 없으면 `없음`, 있지만 동작하지 않으면 `실패`.
- 실행: `conda activate trinity && python scripts/check_env.py`. 다른 환경은 그 환경의 Python과 `--output`으로 따로 기록한다. 테스트는 `tests/test_check_env.py`.
- conda `trinity`(서버 환경) 결과는 `docs/env-check.md`: Python 3.11.18 / arm64 / ffmpeg·ffprobe 8.0.1 / libx264 정상. PyTorch·OpenCV·LightGBM은 이 환경에 없다(의도한 상태).
- `research/waverep/.venv` 결과는 `docs/env-check-waverep.md`: PyTorch 2.15.0, **CPU·MPS 행렬곱 스모크 정상**, OpenCV 5.0.0 정상. LightGBM은 없음(WaveRep 환경의 설치 대상이 아니다. MotionPhys 환경을 만들 때 확인한다).
- "저장소/가중치 이용 조건 점검"은 WaveRep에 대해서만 했다(`docs/waverep-license.md`). MotionPhys·SyncNet·`social_emulator`는 각 스파이크에서 점검한다.

## 한 일 (백로그 4번)

백로그 4번, URL-only 최소 수직 슬라이스를 만들었다. 모델과 다운로드는 stub이다.

- **API** (`server/api/`): `POST /api/v1/analyses`(202), `GET /api/v1/analyses/{id}`, `GET /api/v1/analyses/{id}/result`, `GET /api/v1/health`. 핸들러는 큐에 넣고 읽기만 한다.
- **URL 검사** (`server/ingest/youtube_url.py`): 정규화, 허용 호스트(`youtube.com`, `www.`, `m.`, `youtu.be`), 11자 video ID 추출. 네트워크 요청 없음. IP·포트·사용자 정보·다른 호스트는 거부한다.
- **AuthorizedMediaRegistry** (`server/ingest/media_resolver.py`): `configs/authorized_media.json`에 등록된 ID만 허가한다. 파일이 없으면 모든 ID가 미허가다.
- **SQLite 큐** (`server/jobs/queue.py`): `BEGIN IMMEDIATE` 원자적 선점, 동시 1건, 대기 3건 초과 시 429, lease와 단계 경계 heartbeat, 만료 lease 복구, 재시도 상한(기본 2회), 취소, lease 소유자 불일치 쓰기 거부.
- **Worker** (`server/jobs/worker.py`): 별도 프로세스. 단계명만 기록하고, 한 축이 예외를 내도 나머지 축을 계속한다. 타임아웃과 취소는 단계 경계에서 확인한다. 임시 작업 폴더는 끝나면 지운다.
- **작업 소유권**: `X-Client-Token` 헤더의 해시를 작업에 저장한다. 토큰이 다르면 404, 없으면 401.
- **그 외**: `requirements.txt`(버전 고정), `.gitignore`, `pytest.ini`, `scripts/smoke_slice.py`, README 하단 실행 방법, CLAUDE.md "명령" 절.

## 검증 결과

- `pytest -q`: 52개 통과 (Python 3.11.18, conda 환경 `trinity`). 종단 간 테스트는 worker를 실제 별도 프로세스로 띄운다.
- 실제 서버(uvicorn)와 worker를 띄우고 `scripts/smoke_slice.py`로 확인했다.
  - 등록 ID: `queued → validating → … → finalizing → finished`, `analysis_status=partial`, `verdict_status=abstained`, `overall_score=null`, `abstention_reason=no_valid_fusion_model`.
  - 미등록 ID: `analysis_unavailable`, `reason_code=access_not_authorized`, 모든 축 점수 `null`.
  - 잘못된 URL 422, 없는 작업 404.

## 실행 방법

```bash
conda activate trinity                # 없으면: conda create -n trinity python=3.11 -y && pip install -r requirements.txt
pytest -q
uvicorn server.main:app --reload      # 터미널 1
python -m server.jobs.worker          # 터미널 2
python scripts/smoke_slice.py         # 터미널 3
```

## 남은 일

- 백로그 1·3번은 기록을 만들었고 둘 다 진행 중이다(`docs/media-access.md`, `docs/dataset-access.md`). 4번은 원래 1번에, 5번은 3번에 의존한다.
- 다음 순서: 백로그 6번(최소 발화 구간 Gate). 1·3번의 확인 필요 항목은 병렬로 처리한다. 데이터셋 승인은 기다려야 한다.
- 백로그 14번으로 미룬 것: `DELETE /api/v1/analyses/{id}` 엔드포인트(큐의 `request_cancel`은 이미 있음), 정식 인증, rate limit, 비정상 종료 잔여 파일 24시간 정리.
- 실제 모델을 연결하면(백로그 7번) heartbeat를 단계 경계가 아니라 주기적으로 보내야 한다. 지금은 stub이 즉시 끝나서 단계 경계 heartbeat로 충분하다.

## 백로그 7번에서 제거할 임시 값

- **stub 축의 `status`**: 등록 ID의 세 축은 `status=insufficient_input`, `reason_code=stub_not_executed`, `model_version=stub`으로 답한다. §10의 축 상태에 "실행하지 않음"이 없어서 쓴 임시 값이다. 실제 WaveRep를 Worker에 연결할 때(백로그 7번) `stub_not_executed`와 `model_version=stub`을 제거한다. 위치: `server/axes/{signal,physics,alignment}/__init__.py`.

## 결정한 것 (2026-11-12)

- **미완료 작업의 `/result`**: `queued`·`processing`이면 HTTP 202와 함께 `job_status`·`stage`만 돌려준다. 실패·취소 작업은 200으로 `job_status`와 `reason_code`만 채운다. README §9에 반영했다.
- **작업 실패 원인 코드**: `timeout`, `worker_error`, `max_attempts_exceeded`를 README §10에 추가했다.
- **백로그 7번 완료 조건**: "추론 중 주기적 heartbeat로 lease 연장"을 README §14.1에 추가했다.
- **README §9 문구**: "미구현 명세"를 "백로그 4번 기준 stub으로 구현됨"으로 바꿨다.

## 막힌 점·확인이 필요한 것

- **테스트 경고**: `starlette.testclient`가 `httpx` 대신 `httpx2`를 쓰라는 경고를 낸다. 테스트는 통과한다. 교체 여부는 확인 필요.
- **허가 미디어**: 레지스트리에는 가짜 ID `TRINITYtest`만 있다. 권한 근거는 `docs/media-access.md`에 기록했다. 실제 ID는 본인 채널 업로드 여부와 YouTube Studio 관련 미확인 사항을 정한 뒤에 넣는다.
