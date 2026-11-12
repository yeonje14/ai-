# TRINITY

말하는 사람이 나오는 YouTube 영상의 AI 생성·조작 여부 판단을 돕는 서비스 (졸업작품).
설계 기준은 `README.md` v6.0이다. 이 파일은 매 세션 지켜야 할 규칙만 담는다.
대화와 설명은 한국어로 한다.

## 현재 단계

- 코드는 거의 없다. 작업 순서는 `README.md` §14.1 백로그(1→15)를 따른다.
- 코드로 만들 첫 기능: 백로그 4번, URL-only 최소 수직 슬라이스 (모델은 stub).
- 실제 추론으로 처음 검증할 모델: 백로그 5번, WaveRep.
- Flutter UI나 세 모델을 한꺼번에 만들지 않는다.

## 실행 환경

- macOS ARM64 (Apple Silicon), Python 3.11.
- CUDA가 없다. `.cuda()`를 쓰지 않는다. 장치는 인자로 받고 `mps` → `cpu` 순으로 대체한다.
- MPS 미지원 연산은 `PYTORCH_ENABLE_MPS_FALLBACK=1`로 CPU에 넘긴다.
- 모델별 의존성은 `research/<model>/`의 별도 `.venv`에서 먼저 재현한다. 버전은 스모크 테스트 후 lockfile로 고정한다.
- AVH-Align·Fairseq는 기본 의존성에 넣지 않는다.

## 명령

저장소 루트에서, conda 환경 `trinity`(Python 3.11)를 켠 뒤 실행한다. 자세한 내용은 `README.md` 하단 "서버 실행 방법".

- 환경: `conda activate trinity` (없으면 `conda create -n trinity python=3.11 -y && pip install -r requirements.txt`)
- 테스트: `pytest -q`
- API 서버: `uvicorn server.main:app --reload`
- Worker: `python -m server.jobs.worker` (`--drain`: 대기열이 비면 종료)
- 실행 확인: `python scripts/smoke_slice.py` (서버와 Worker가 떠 있을 때)

## 절대 규칙: 입력과 미디어

- 사용자 입력은 YouTube URL뿐이다. 파일 업로드 경로를 만들지 않는다.
- URL은 정규화, 허용 호스트 확인, video ID 추출만 한다. 내부망 IP, 임의 리디렉션, 로컬 파일 경로, 셸 인자를 입력으로 받지 않는다 (SSRF 방지).
- 분석할 미디어는 `AuthorizedMediaRegistry`에 등록된 허가 미디어만 쓴다. 없으면 `analysis_unavailable`로 끝내고 보류 원인을 남긴다.
- 임의 URL을 yt-dlp 등으로 내려받는 코드를 만들지 않는다. 권한 문제를 우회하는 구현은 하지 않는다.
- 일반 사용자가 요청한 영상은 학습 데이터에 넣지 않는다. 임시 클립·오디오·얼굴 crop은 작업이 끝나면 삭제한다.

## 절대 규칙: 상태와 결과

- 세 상태를 서로 다른 필드로 둔다. 작업 종료 ≠ 분석 완료 ≠ 진위 판정.
  - `job_status`: queued, processing, finished, failed, cancelled
  - `analysis_status`: completed, partial, out_of_scope, unsupported, insufficient_quality, analysis_unavailable
  - `verdict_status`: assessed, abstained, not_applicable
  - `axes.*.status`: completed, insufficient_input, unsupported_input, out_of_distribution, error
- 실패했거나 실행하지 않은 점수는 `null`이다. 진짜로 읽힐 수 있는 `0`을 쓰지 않는다.
- 검증된 결합 모델이 없으면 `overall_score`는 `null`이다.
- 한 축이 실패해도 나머지 축은 계속 처리한다.
- `coverage`는 분석한 양이다. 정확도나 신뢰도로 쓰지 않는다.
- 진행률은 숫자 % 대신 단계명으로만 보낸다: validating, access_check, preprocessing, waverep, motionphys, syncnet, fusion, finalizing.

## 절대 규칙: 서버 구조와 보안

- 추론은 FastAPI 핸들러나 `BackgroundTasks`에서 하지 않는다. 별도 Worker 프로세스가 한다.
- SQLite 큐: `queued → processing`을 트랜잭션으로 원자적으로 선점하고, lease/heartbeat, 재시작 복구, 중복 실행 방지, 취소·타임아웃을 둔다.
- 처음에는 동시 분석 1건, 대기 3건으로 시작하고 실측 후 조정한다.
- 서브프로세스는 인자 리스트로 실행한다. 셸 문자열을 이어 붙이지 않는다. 모델 프로세스에는 서버가 발급한 작업 경로만 넘긴다.
- `analysis_id`만으로 권한을 주지 않는다. 조회·취소·삭제 때 작업 소유권을 확인한다.
- 로그에 인증값, 영상 내용, 얼굴 이미지, URL 쿼리를 남기지 않는다.

## 데이터와 평가 규칙

- 데이터는 Git 밖에 둔다: 연구용 `data/research`, 서비스 임시 파일 `data/runtime`.
- 분할은 인물과 원본 녹화의 계보를 묶은 그룹 단위로 한다. 누수 검사를 통과하기 전에는 평가하지 않는다.
- 임계값은 개발 검증 분할에서 오탐률 5%를 목표로 정하고 고정한다. 테스트 분할로 조정하지 않는다.
- Deepfake-Eval-2024는 최종 평가 전용이다. 학습·튜닝·임계값 결정에 쓰지 않는다.
- 압축 에뮬레이터는 소프트웨어 인코더(libx264 등)를 쓴다. 하드웨어 인코더(VideoToolbox)는 쓰지 않는다. 실제 YouTube와 같다고 주장하지 않는다.
- 3축 결합을 강제로 채택하지 않는다. WaveRep 단일 모델과 비교해서 나을 때만 쓴다.
- SyncNet은 진위 분류기가 아니라 동기화 보조 지표다.

## 커밋하지 않는 것

`.venv/`, 원본·변환 영상과 오디오, 얼굴 crop, 데이터셋 파일, 사용자 요청 데이터, 비밀 키, 사용 제한이 있는 가중치.

## 작업 방식

- 백로그 한 줄이 한 작업이다. 해당 행의 완료 조건(DoD)을 수용 기준으로 쓴다.
- 테스트를 같이 만든다. 테스트와 실행 명령이 실제로 통과한 뒤에만 완료라고 보고한다. 실행하지 못했으면 "미검증"이라고 적는다.
- 설계와 다른 결정이 필요하면 코드를 바꾸기 전에 `README.md` §15.3 결정 기록 변경을 먼저 제안한다.
- 논문 수치, 라이선스, 외부 API 동작은 추측하지 않는다. 모르면 "확인 필요"로 적는다.
- 세션이 끝날 때 `docs/HANDOFF.md`를 갱신한다: 한 일, 남은 일, 실행 방법, 막힌 점.
- 코드를 줄이라는 규칙(플러그인 포함)이 있어도 README의 API 계약, 상태 규칙, 보안, 큐 신뢰성 요구사항은 줄이지 않는다.

## 필요할 때만 읽을 곳

`README.md`를 통째로 불러오지 않는다. 해당 절만 읽는다.

- §9 API 계약
- §10 상태·실패·보류
- §12 실행 환경·보안
- §13 최종 평가 프로토콜
- §14 백로그와 완료 조건
- §15 저장소 구조·위험·결정 기록
