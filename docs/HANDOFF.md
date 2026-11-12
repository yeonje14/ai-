# HANDOFF

마지막 갱신: 2026-11-12 · 브랜치 `feat/url-only-slice` (커밋함, push 전)

## 한 일

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

- 백로그 1·2·3번(권한 근거, 환경 스모크 테스트, 데이터셋 접근)은 기록이 없다. 4번은 원래 1·2번에 의존한다.
- 백로그 5번: WaveRep 단독 추론 스파이크(`research/waverep/` 별도 환경).
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
- **허가 미디어**: 레지스트리에는 가짜 ID `TRINITYtest`만 있다. 실제 ID는 권한 근거(백로그 1번)를 기록한 뒤에만 넣는다.
