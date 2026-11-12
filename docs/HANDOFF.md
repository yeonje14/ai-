# HANDOFF

마지막 갱신: 2026-11-12 · 브랜치 `feat/waverep-adapter`

## 백로그 7번: WaveRep 어댑터 (진행 중)

- 프레임 샘플링, WaveRep 추론 어댑터, 벤치마크 및 테스트를 작성했다. 전체 테스트 124개 통과(실제 CPU 추론 포함).
- 배터리 부족으로 벤치마크를 일시 중단했다. 중단 전 완료를 확인한 케이스: `cpu-all-b1-pretrained`, `cpu-all-b1`, `cpu-all-b8`. 결과는 `data/research/waverep-adapter/`에 있다(Git 제외).
- 다음: 같은 영상으로 벤치마크를 재개하고 남은 결과와 오프라인 재현성을 확인한다. Gate와 Worker 통합은 남아 있다.

## 백로그 1·3번: 접근 기록 문서화 (둘 다 진행 중)

문서만 만들었다. 코드는 바꾸지 않았다.

- **`docs/media-access.md` (백로그 1번)**: 영상 ID·메타데이터 접근과 분석용 미디어 접근의 차이(README §3.1 기준), 임의 YouTube URL은 `analysis_unavailable`로 처리한다는 결정, 허가 미디어 범위(저장소 소유자가 직접 촬영한 본인 영상, 본인 얼굴·음성만, 제3자 없음), 압축 실험에는 휴대폰 원본을 쓴다는 메모.
- **`docs/dataset-access.md` (백로그 3번)**: DeepSpeak v2와 Deepfake-Eval-2024는 접근 요청 후 승인 대기, TalkingHeadBench는 접근 방법 확인 필요. 데이터셋별 역할, 확인된 이용 조건, 확인 필요 항목을 나눠 적었다. Hugging Face 공개 API 메타데이터(접근 제한 여부, 라이선스 태그, Deepfake-Eval-2024 이용 조건 문구)를 2026-11-12에 조회해 근거로 썼다. 데이터셋 파일은 받지 않았다.
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
