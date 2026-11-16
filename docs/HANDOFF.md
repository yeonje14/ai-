# HANDOFF

마지막 갱신: 2026-11-15 · 브랜치 `codex/cancel-recovery-security` (최신 origin/main `3f0f2b4`에서 생성)

## A 영상 실제 WaveRep 추론 중 취소 검증 (2026-11-15)

- 범위: PR #12 `codex/cancel-recovery-security`, 커밋
  `3fe99f01715cb07f2c57b9ec6de57b9368846f46`에서 A.MOV 한 건만 검증했다.
  별도 worktree `/private/tmp/trinity-pr12-cancel-A`를 사용했고 원래
  `/Users/iyeonje/ai-`의 `feat/syncnet` 작업 공간은 변경하지 않았다.
- 독립 실제 uvicorn·Worker·SQLite·runtime을 사용했다. 임시 AuthorizedMediaRegistry에
  `/Users/iyeonje/ai-/data/research/samples/A.MOV`를 연결했다.
  기존 Gate 설정·임계값을 그대로 사용하고 WaveRep 장치만 `cpu`로 지정했다.
  기존 모델별 `.venv`·upstream·가중치를 재사용했으며 설치·다운로드·모델 코드 수정은 없었다.
- 작업 `fe18425a-2b54-43c3-99a8-e483397b5f56`은 `preprocessing`을 거쳐
  `waverep`에 진입했다. 실제 `infer_frames.py` 자식 PID `99588`이 실행되는 동안
  `/usr/bin/sample`로 `libtorch_cpu`의 `linear`, `addmm`, `cpublas::gemm` 스택을 확인했다.
  DELETE 직전에 `processing/waverep`, 자식 생존, 추론 결과 파일 미생성을 다시 확인했다.
  따라서 모델 프로세스 시작만 확인하거나 추론이 끝난 뒤 취소한 검증이 아니다.
- 진행 중 GET에서 받은 ETag를 `If-Match`로 보낸 DELETE 응답:
  HTTP **202**, `job_status=processing`, `stage=waverep`.
- 최종 GET 및 결과 조회: **`job_status=cancelled`**, `overall_score=null`.
  실제 추론 자식 종료와 해당 UUID 임시 작업 폴더 삭제를 각각 확인했다.
  취소 요청부터 확인까지 약 **0.39초**(이번 1회 관찰값)였으며 Worker 종료 코드는 0이었다.
  종료 작업을 삭제하는 두 번째 DELETE는 보내지 않았다.
- 실행 후 검증용 서버·Worker를 종료하고 임시 레지스트리·DB·runtime을 정리했다.
  원본 영상·가중치·환경은 보존했다. 검증용 환경 연결 심볼릭 링크도 제거했다.

**로컬 재현 명령** (이 세션의 검증 스크립트는 Git 밖 `/private/tmp/pr12_cancel_a.py`에 보존):

```bash
cd /private/tmp/trinity-pr12-cancel-A
ln -s /Users/iyeonje/ai-/research/waverep/.venv research/waverep/.venv
ln -s /Users/iyeonje/ai-/research/waverep/upstream research/waverep/upstream
/opt/anaconda3/envs/trinity/bin/python /private/tmp/pr12_cancel_a.py
# 실행 후 위에서 만든 심볼릭 링크 두 개만 제거한다(원본 환경·upstream 보존).
unlink research/waverep/.venv
unlink research/waverep/upstream
git diff --check
```

스크립트는 기존 `scripts/smoke_cancel_worker.py`를 기반으로 A와 실제 WaveRep 자식을
관찰하도록 만든 세션 전용 실행기다. Gate 제한 120초, 전체 작업 제한 300초,
heartbeat 1초·lease 4초, WaveRep CPU를 사용한다. 자식 관찰 후 15초 대기와 1초 스택
샘플링을 수행하며, 실제 연산·진행 상태가 확인되지 않으면 성공으로 처리하지 않는다.
재현에는 이 로컬 스크립트·허가 원본·기존 모델 환경이 필요하다(`/private/tmp` 정리 시 스크립트 소실 가능).
스택 원본은 `/private/tmp/pr12-A-stack.txt`에 있으며 미디어 내용은 포함하지 않는다.

**검증 범위·남은 일:** 이번 A 한 건의 CPU 추론 중 취소 성공만 확인했다.
MPS 추론 취소·다른 영상·반복 안정성은 미검증이다. 코드 변경이 없어 전체 pytest는
다시 실행하지 않았다. API·Gate 판정·임계값을 변경하지 않았고 커밋·push는 하지 않았다.
막힌 점 없음.

## 현재 작업: 백로그 14번 중 취소·삭제·Worker 복구·정리

**결과:** 요청한 부분의 구현·테스트·실제 서버 취소 확인을 마쳤다. 백로그 14번 전체 완료는 아니다.
도구·모델: **Codex, GPT-6 Astra**. README §9·§15.3에 날짜와 **“Codex, GPT-6 Astra 제안, 사용자 승인”**을 기록했다.
구현 커밋 `be08650`을 push했고 [PR #12](https://github.com/yeonje14/ai-/pull/12)를 생성했다.
PR은 열림·미병합 상태이며 main에는 merge하지 않았다. 이 인계 기록은 후속 문서 커밋으로 반영한다.

**한 일**:

- `DELETE /api/v1/analyses/{id}`: 소유권 확인 후 진행 중 취소 접수 `202`, 반복도 `202`;
  종료(`finished`·`failed`·`cancelled`) 작업은 결과·기록·폴더 삭제 후 본문 없는 `204`.
  토큰 없음 `401`, 다른 소유자·삭제 후 조회(`/result` 포함)·재삭제 `404`.
  큐의 `cancel_requested`를 재사용하고 새 상태나 JSON API 필드를 만들지 않았다.
- 상태 GET의 ETag는 `queued`·`processing` 동안 단계·heartbeat·재시도와 무관하게 불변이며 종료 때 변경한다.
  `If-Match`와 현재 ETag 비교를 DELETE 상태 분기와 같은 트랜잭션에서 수행한다.
  불일치 `412`는 기록·결과·폴더를 건드리지 않는다. 일반 DELETE 계약은 유지한다.
- 앱의 “분석 취소”는 진행 중 상태의 ETag로 조건부 DELETE만 보낸다. 중복 클릭을 막고,
  `202` 후 polling으로 기존 “취소됨” 화면을 표시한다. `412`는 오류로 보이지 않고
  상태·결과를 다시 조회한다. ETag가 없으면 일반 DELETE로 대체하지 않는다.
  CORS에 DELETE·If-Match 허용과 ETag 노출을 추가했고 기존 출처 제한은 유지했다.
- Worker가 프로세스와 임시 파일을 정리한 후 종료 상태를 기록한다. 완료 쓰기와 취소 접수가
  겹쳐도 먼저 접수된 취소를 완료 결과로 덮지 않는다. 정리 실패는 성공으로 숨기지 않는다.
- lease 만료 후 이전 시도의 폴더를 정리하고 재시도하거나 `failed/max_attempts_exceeded`로 끝낸다.
  종료·기록 없는 UUID 폴더도 Worker 반복 실행에서 정리한다. 무관한 잔여 폴더의 권한 오류는
  경고하고 다음 작업을 계속한다. 실패 폴더는 다음 반복에서 정리를 재시도한다.
- 단일 호스트 `flock`으로 살아 있는 이전 Worker와 새 Worker의 파일 처리 겹침을 막는다.
  Gate/모델 supervisor가 Worker 생존 파이프를 감시해 Worker SIGKILL에도 자식·후손 그룹을 종료한다.
  supervisor도 잠금 FD를 상속하므로 자식 그룹 정리 전 복구가 선행하지 않는다.
  모델별 Python 환경 분리, MPS/CPU 정책은 유지하며 새 의존성은 설치하지 않았다.
- 독립 GPT-6 Astra 검토에서 고아 자식과 무관한 정리 실패의 큐 차단을 실제 재현했다.
  두 지적을 회귀 테스트 3개 RED→GREEN으로 수정했다. 새 API 계약 변경은 없었다.

**바꾼 파일**:

- API: `server/api/analyses.py`, `server/api/__init__.py`.
- Worker·큐·정리: `server/jobs/queue.py`, `server/jobs/worker.py`,
  새 `server/jobs/runtime.py`, `server/jobs/child_process.py`, `server/jobs/supervisor.py`.
- 자식 실행기: `server/gate/runner.py`, `server/axes/signal/waverep.py`.
- 앱: `app/lib/api/analysis_api.dart`, `app/lib/api/models.dart`, `app/lib/api/mock_api.dart`,
  `app/lib/app.dart`, `app/lib/screens/progress_screen.dart`.
- 테스트: 새 `tests/test_analysis_delete.py`, `tests/test_job_lifecycle.py`,
  `app/test/cancel_flow_test.dart`; 갱신 `tests/test_queue_worker.py`,
  `tests/test_cors_and_label.py`, `app/test/flow_test.dart`.
- 실제 실행 확인: 새 `scripts/smoke_cancel_worker.py`.
- 문서: `README.md`, `docs/HANDOFF.md`, `docs/superpowers/plans/2026-11-15-cancel-recovery.md`.

**실행한 명령·테스트 결과**:

```bash
git fetch origin main
git switch -c codex/cancel-recovery-security origin/main
# 아래 python은 /opt/anaconda3/envs/trinity/bin/python (Python 3.11.18)
python -m pytest -q tests/test_analysis_delete.py
python -m pytest -q tests/test_job_lifecycle.py tests/test_analysis_delete.py tests/test_queue_worker.py
python -m pytest -q tests/test_job_lifecycle.py -k 'unrelated or death'
python -m pytest -q tests/test_job_lifecycle.py tests/test_gate_runner.py tests/test_waverep_adapter.py tests/test_waverep_worker.py
python -m pytest -q
python scripts/smoke_cancel_worker.py
cd app
flutter test test/cancel_flow_test.dart --reporter expanded
flutter test --reporter expanded
flutter analyze
```

- 기준 전체: Python **437 passed, 2 skipped**, Flutter **198개 통과**.
- 최종 전체: Python **468 passed, 2 skipped**, 33.33초. 기존 LightGBM 없음·말하는 영상 없음으로 건너뜀.
  `starlette.testclient`의 기존 httpx 폐기 예정 경고 1개는 유지했다.
- 최종 앱: **202개 통과**, `flutter analyze` 문제 없음.
- API 13개 신규 계약 테스트: 401/404/202/반복202/204/삭제 후404,
  ETag의 선점·단계·heartbeat·재시도 중 불변, 종료 시 변경, 412 비파괴, CORS, 취소/finish 경합.
- Worker 테스트: 정상·실패·취소·타임아웃의 정리 선행, 재시도/상한 복구,
  실제 Worker SIGKILL 후 재시작, Gate·모델의 가짜 장기 실행 자식·후손 종료,
  Worker만 SIGKILL 시 자식 종료·폴더 재생성 방지, 정리 권한 오류 격리.
- 실제 스모크 최종: 독립 uvicorn·Worker와 기존 발화 없는 허가 샘플 사용.
  **실제 Gate 자식 실행 확인 → 조건부 DELETE 202 → 반복202 → cancelled**,
  약 **0.99초**에 자식 종료·폴더 삭제 확인. 종료 후 이전 ETag DELETE는 `412`이며
  조회 `200`; 일반 DELETE `204`, 이후 조회·재삭제 `404`.
  스모크의 서버·Worker·임시 DB·복사본은 종료 후 정리했다.
- 초기에 샌드박스 `ps` 실행과 Flutter SDK 캐시 쓰기가 차단됐다. 허용한 환경에서 재실행해 통과했다.
  기존 CORS 테스트의 DELETE 금지 기대값은 승인된 계약에 맞춰 갱신했다.

**실행 방법**:

```bash
conda activate trinity
uvicorn server.main:app --reload
# 같은 DB/runtime/허가 레지스트리 설정을 쓰는 다른 터미널
python -m server.jobs.worker
# 독립 테스트 서버와 Worker를 직접 띄우는 실제 취소 점검
python scripts/smoke_cancel_worker.py
# 앱
cd app
flutter test
```

스모크에는 기존 `data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4`와
설치된 Gate 의존성/모델이 필요하다. 없으면 미검증으로 종료하며 내려받지 않는다.
`data/runtime/jobs/.worker.lock`은 작업 미디어가 아닌 공통 잠금 파일이므로 유지한다.
운영 중 삭제하면 중복 잠금이 생길 수 있다. Worker가 실행 중인 동안에는 지우지 않는다.

**남은 일·미검증·운영 판단**:

- 정식 인증과 사용자별 rate limit은 이번 범위 밖이며 백로그 14번에 남아 있다.
- 실제 WaveRep 추론 중 취소·강제 종료는 **미검증**. 실제 프로세스 경계는 가짜 모델로 검증했고,
  실제 미디어 취소는 Gate 실행 중에 검증했다. 말하는 허가 영상의 Gate→WaveRep 통과도 기존대로 미검증.
- 실제 브라우저·모바일 기기 터치 조작은 **미검증**. 앱은 HTTP 모의 응답 기반 위젯 테스트로 확인했다.
- ETag는 승인된 수명주기 조건 값이고 단계별 응답 캐시 검증용이 아니다(`no-store`).
- 살아 있으나 멈춘 이전 Worker는 종료해야 새 Worker가 복구한다. 같은 폴더에서 중복 실행/삭제하는
  위험을 막기 위한 결정이다. 자식은 supervisor가 종료하며 새 Worker는 lease 만료 후 복구한다.
- 파일시스템 자체가 삭제를 거부하면 폴더가 즉시 사라진다고 보장할 수 없다. 활성 작업은
  `processing`으로 남아 복구에서 정리를 재시도하고, 종료 작업 DELETE는 `500` 및 기록 보존으로 재시도 가능하다.
- 24시간 정책은 Worker가 계속 실행되고 파일시스템 접근이 가능한 조건에서 반복 정리한다.
  별도 운영 스케줄러·알림은 추가하지 않았다. 기존 서버를 교체할 때는 이전 Worker/자식을 먼저 종료한다.

**막힘:** 요청 범위의 구현·검증에 남은 막힘 없음. 아래는 이전 작업 기록이다.

## 이전 작업: 백로그 7번 Gate → Worker 연결 (2026-11-15)

**결과:** Gate 연결 구현과 요청한 검증을 마쳤다. 말하는 영상의 실제 통과 경로는 **미검증**이다.
README §15.3에 날짜와 **“Codex, GPT-6 Astra 제안, 사용자 승인”**을 기록했다.
PR 대상은 main이며 merge하지 않는다. 아래 과거 기록의 “Gate 미연결”·“PR #10 열림”은 당시 상태다.
구현 커밋: `f39d203`. push 완료, [PR #11](https://github.com/yeonje14/ai-/pull/11) 생성(열림, 미병합).

**한 일**:

- 최신 main(PR #9·#10 포함)에서 새 브랜치를 만들었다.
- Worker `preprocessing`에서 작업 폴더에 복사한 허가 미디어에 Gate를 실행한다.
  같은 conda `trinity` Python의 별도 프로세스를 쓰고 모델 환경 분리를 유지한다.
  설치된 Gate 패키지와 torch가 없음을 확인했고, trinity에 패키지를 설치하지 않았다.
- Gate가 고른 구간만 WaveRep에 전달한다. 구간이 없으면 모델 단계를 실행하지 않고
  대표 원인·분석 상태·판정 상태를 README §15.3 승인 표대로 기록한다.
  표의 12개 원인 코드 각각을 Worker 결과 테스트로 고정했다.
- Gate 실패/타임아웃은 `gate_error`/`gate_timeout`, `analysis_unavailable`/`abstained`,
  모든 축 점수 `null`. heartbeat로 lease를 연장하고 취소·lease 상실·작업 전체 타임아웃에는
  자식 프로세스 그룹을 종료한다. 작업 전체 타임아웃은 기존 `failed`/`timeout`이다.
- 기존 API 필드와 상태 목록을 유지한다. 적합/제외 구간·원인·품질 숫자는 기존
  `explanations`, 원본/적합/성공 분석량은 기존 `coverage`에 기록한다.
  미실행·실패 분석 길이/비율은 `null`, 분석 구간은 `[]`. coverage는 정확도가 아니다.
- 개발·테스트 전용 수동 구간은 기본 꺼짐. 켰을 때만 Gate 우회,
  `gate_bypassed=true`, `partial`/`abstained`. `raw_score`/`overall_score`/판정 라벨은 계속 `null`.
- 앱은 `access_not_authorized`·`video_access_unavailable`을 “영상 접근 불가”,
  `media_unreadable`·`gate_error`·`gate_timeout`을 “분석하지 못함”으로 구분한다.
  원인 코드를 보류 원인보다 우선해 표시하고, `unsupported`/`insufficient_quality`의
  `abstained`를 “해당 없음”으로 잘못 표시하던 요약도 “보류”로 고쳤다.
- 독립 코드 검토에서 얼굴·입 경계 반올림으로 0초 제외 조각이 생겨 정상 적합 구간까지
  `gate_error`가 되는 결함을 재현했다. Gate 산출 단계에서 빈 조각을 제거하고
  실제 `build_result → parse_result` 회귀 테스트의 실패→통과를 확인했다.

**바꾼 파일**:

- 서버: `server/jobs/worker.py`, `server/config.py`, `server/axes/signal/__init__.py`,
  `server/gate/__init__.py`, `server/gate/segments.py`.
- 새 Gate 실행/결과 처리: `server/gate/runner.py`, `server/gate/process.py`, `server/gate/report.py`.
- 앱: `app/lib/view_state.dart`, `app/lib/screens/result_screen.dart`, `app/lib/screens/detail_screen.dart`.
- 테스트: `tests/test_gate_worker.py`, `tests/test_gate_runner.py`(새 파일), `tests/test_api.py`,
  `tests/test_queue_worker.py`, `tests/test_waverep_worker.py`, `app/test/screens_test.dart`.
- 실제 실행 확인 도구: `scripts/smoke_gate_worker.py`(새 파일).
- 문서: `README.md`, `docs/gate.md`, `docs/waverep-adapter.md`, `docs/HANDOFF.md`,
  `docs/superpowers/plans/2026-11-15-gate-worker.md`.

**실행한 명령과 결과** (Python은 `/opt/anaconda3/envs/trinity/bin/python` 사용):

```bash
python -m pytest -q tests/test_gate_worker.py
python -m pytest -q tests/test_gate_runner.py
python -m pytest -q tests/test_gate_runner.py::test_rounded_face_and_mouth_boundary_keeps_eligible_segment tests/test_gate_segments.py tests/test_gate_mouth.py
python -m pytest -q
python scripts/smoke_gate_worker.py
cd app
flutter test
flutter analyze
```

- 변경 전 전체: 394 passed, 2 skipped.
- 변경 후 최종 전체: **437 passed, 2 skipped**, 30.70초. 건너뜀은 기존 LightGBM 없음과 말하는 영상 없음.
  `starlette.testclient`의 기존 httpx 폐기 예정 경고 1개는 남아 있다.
- 최초 제한 환경 실행은 후손 프로세스 확인용 `ps` 권한 거부로 1개 실패했다.
  권한 허용 후 해당 테스트와 전체 테스트가 통과했다. 제품 오류로 처리하지 않았다.
- 앱: **198개 통과**, `flutter analyze` 문제 없음.
- 실제 서버·Worker 스모크(수정 후 최종): 기존 발화 없는 허가 샘플 10.433초,
  `finished`/`out_of_scope`/`not_applicable`, 원인 `no_mouth_movement`, 적합 길이 0초,
  분석 길이/비율 `null`, 분석 구간 `[]`, `gate_bypassed=false`.
  `raw_score`, `raw_metrics`, `overall_score` 모두 `null`.
  완료 단계는 `validating → access_check → preprocessing → finalizing`이며 WaveRep 단계/실행 로그가 없다.
  임시 작업 폴더 삭제 확인. 약 2.77초. 스모크 설정 heartbeat 0.2초/lease 2초로
  preprocessing의 서로 다른 lease 만료 시각 13개를 관찰했다(기본 10초 간격은 아님).
- 가짜 프로세스로 Gate 비정상 종료·깨진 JSON·오래된 결과·타임아웃·heartbeat·취소·lease 상실,
  작업 전체 제한시간·후손 종료를 검증했다. 실제 미디어 검증은 위 샘플에 한한다.

**실행 방법**:

```bash
conda activate trinity
# 기존 Gate 의존성·모델과 WaveRep 별도 환경은 docs/gate.md, docs/waverep-adapter.md 참고
uvicorn server.main:app --reload
# 다른 터미널, local_path가 있는 Git 밖 레지스트리를 지정한 상태에서
python -m server.jobs.worker
# 독립 임시 서버·Worker로 기존 발화 없는 샘플 확인
python scripts/smoke_gate_worker.py
```

Gate 제한시간은 `TRINITY_GATE_TIMEOUT_SECONDS`(기본 120초), 수동 우회는
`TRINITY_DEV_MANUAL_SEGMENTS`(기본 빈 값). 저장소의 기본 레지스트리는 파일 연결이 없으므로
일반 실행에서는 Git 밖 레지스트리에 허가 샘플의 상대 `local_path`를 지정해야 한다.
스모크 도구는 이를 임시로 구성하고 끝나면 서버·Worker·임시 DB·복사본을 정리한다.

**남은 일·미검증**:

- 실제 말하는 허가 영상의 Gate 통과 → WaveRep 실행. 영상이 아직 없다.
- Gate의 발화/입 움직임 임계값, 다중 발화, 장시간·저품질·회전·가변 프레임률 영상.
- 실제 미디어가 오래 걸리거나 멈춘 상황의 취소·타임아웃(가짜 프로세스로 검증).
- 큰 미디어 파일 복사 중 heartbeat는 기존대로 없음. 이번 변경은 Gate 실행 구간을 포함한다.
- 실제 앱 브라우저·모바일 기기 조작은 미검증(Flutter 위젯 테스트·정적 검사만 실행).
- 다음 작업은 말하는 허가 영상 확인과 백로그 8번 데이터/평가 준비를 따른다.
  프레임 logit 집계/임계값·판정은 이번 작업 범위가 아니다. physics/alignment는 기존 stub 유지.
- Gate 모델 파일 이용 조건의 기존 “확인 필요”는 그대로이며 새 다운로드는 없다.

**막힘:** 이번 연결 작업의 구현·테스트에 막힘 없음. 실제 발화 영상 검증은 자료가 필요하다.

## 이전 세션 기록


## 오늘 밤 결과 요약 (2026-11-15, 무인 작업)

밤사이 작업 1과 작업 2만 했다. 작업 3·4는 시작하지 않았다. 중간에 사용량 한도로 멈춰서 작업 2의 커밋은 모델을 바꿔 이어서 했다. 아침에 저장소 소유자의 지시로 PR #9를 먼저 main에 합쳤고, PR #10 브랜치를 그 위로 옮겨 README·HANDOFF 충돌을 두 작업 내용이 모두 남도록 해결했다.

| 작업 | 상태 | 브랜치 | PR |
|---|---|---|---|
| 1. WaveRep을 Worker에 연결 (백로그 7번) | **완료.** 코드, 테스트, 실제 실행 확인, 커밋, push, PR까지 | `feat/waverep-worker` (`1c1c47a`) | #9 (**main에 합침**, `0e207cf`) |
| 2. Gate 보완 (입 움직임, VAD 비교) | **완료(말하는 영상은 미검증).** 코드, 테스트, 커밋, push, PR까지 | `feat/gate-mouth-motion` | #10 (열림) |

**작업 1이 된 것** (자세한 내용은 아래 "백로그 7번: WaveRep을 Worker에 연결" 절):

- signal 축 stub을 WaveRep 어댑터 호출로 바꿨다. 기본값은 MPS, 배치 1, 초당 2장이다.
- 레지스트리 `local_path`의 허가 미디어를 작업 폴더로 복사해 모델에 넘긴다.
- 개발 전용 수동 구간 `TRINITY_DEV_MANUAL_SEGMENTS`를 추가했다. 기본은 꺼짐이다. 켜면 `gate_bypassed=true`, `partial`, `abstained`가 된다.
- 추론 중에 주기적 heartbeat로 lease를 연장한다. 타임아웃과 실패는 점수 `null`로 격리한다.
- 결과에는 프레임 logit 요약만 둔다. `raw_score`와 `overall_score`는 `null`이다.
- `pytest -q` 352개 통과, 1개 건너뜀(lightgbm).
- 서버와 Worker를 띄워 등록 테스트 ID와 샘플 영상으로 실제 WaveRep을 실행했다. 프레임 21장, mps, 추론 6.07초였다.
- 미검증: 실제 추론이 heartbeat 간격(10초)보다 짧게 끝나서, 실제 모델 실행 중 lease가 연장되는 것은 관찰하지 못했다. 가짜 추론 프로세스 테스트로만 확인했다.

**작업 2가 된 것**: 아래 "Gate 보완" 절.

**아침에 확인할 것**:

1. **PR #9의 동작 변화.** 등록 ID라도 `local_path`(미디어 파일)가 없으면 이제 `analysis_unavailable` / `video_access_unavailable`로 끝난다. 아무 설정 없이 `smoke_slice.py`를 돌리면 `TRINITYtest`가 접근 불가로 나온다.
2. **PR #9의 README §15.3 변경 제안 4개.** `gate_bypassed`, `raw_metrics`, `video_access_unavailable`, 축 원인 코드에 관한 것이다. README §9·§10 본문은 바꾸지 않았다. 승인 여부를 정해야 한다.
3. **샘플 영상의 오디오에 사람 목소리가 들어 있는지 들어 볼 것.** webrtcvad, Silero, YAMNet 세 방식이 모두 대부분을 음성으로 판정했다. 목소리가 있다면 VAD의 오판이 아니다.
4. **말하는 영상으로 Gate 검증.** 찍은 영상을 `data/research/samples/speaking/`에 넣고 `pytest -q tests/test_gate_media.py`를 돌린다. 지금은 이 테스트를 건너뛴다.
5. **두 PR을 합치는 순서.** 두 브랜치가 모두 `server/config.py`, `README.md`, `docs/HANDOFF.md`를 고쳐서 나중에 합치는 쪽에서 충돌이 난다. Gate를 Worker에 연결하는 일(수동 구간 대신 Gate 구간 사용, `gate_not_connected` 제거)은 두 PR이 모두 합쳐진 뒤에 한다.
6. 받은 모델 파일 3개(`face_landmarker.task`, Silero VAD v6.0 ONNX, YAMNet)의 이용 조건. 아직 확인하지 않았다.
7. 원래 Gate 브랜치 `feat/gate-speech-segments`는 그대로 남겨 두었다. 정리할지는 저장소 소유자가 정한다.


## Gate 보완: 입 움직임 확인, VAD 비교 (2026-11-15 밤, 무인 작업)

**계획** (작업 전 기록):

- `feat/gate-speech-segments`의 커밋 2개를 최신 main 위의 새 브랜치 `feat/gate-mouth-motion`으로 옮긴다(원래 브랜치는 건드리지 않는다). CLAUDE.md 충돌은 Gate 의존성 줄을 AGENTS.md "명령"으로 옮겨 해결한다.
- MediaPipe Face Landmarker(공식 배포 모델, sha256 기록)로 입 벌림(안쪽 입술 거리 / 두 눈 바깥꼬리 거리)을 초당 약 15장에서 잰다. 음성 구간 안에서 입 벌림이 변하는 부분만 발화로 인정한다.
- webrtcvad 민감도 0~3과 torch 없는 VAD 후보를 `research/gate/.venv`에서 비교한다. trinity 환경에는 아무것도 설치하지 않는다.
- 샘플(야외, 발화 없음)이 발화 없음 계열 원인 코드로 걸러지는지 확인하고, 기대값이 틀린 테스트를 고친다.
- 말하는 영상 검증은 하지 않는다("미검증").

**결과**:

- **브랜치**: `feat/gate-speech-segments`의 커밋 2개를 최신 main(`283c4d1`) 위로 옮겼다(새 커밋 `9f8fcb2`, `77df736`). 충돌은 세 군데에서 났다.
  - CLAUDE.md: main 쪽(`@AGENTS.md` 한 줄)을 남기고, Gate 의존성 줄은 AGENTS.md "명령"으로 옮겼다.
  - README §14.1: main 쪽 표에 Gate의 6번 행만 넣었다.
  - HANDOFF: 두 쪽을 다 남겼다.
- **새 파일과 바꾼 파일**:
  - `server/gate/mouth.py`: 입 벌림 측정(Face Landmarker).
  - `server/gate/mouth_activity.py`: 반전 세기와 움직인 구간을 찾는 순수 함수.
  - `segments.py`: 음성 구간을 입이 움직인 조각과 아닌 조각으로 나눈다.
  - `types.py`: `no_mouth_movement`, `NO_SPEECH_FAMILY`, 임시 임계값, 결과 필드를 추가했다.
  - `faces.py`: 모델 해시 확인을 공통 함수로 바꿨다.
  - `configs/gate_models.json`: `face_landmarker` 항목과 해시를 넣었다.
  - `research/gate/compare_vad.py`, `research/gate/requirements-compare.txt`.
  - `tests/test_gate_mouth.py`(새 파일), `tests/test_gate_media.py`(기대값 수정).
- **규칙**: 음성과 입 움직임이 함께 있을 때만 발화로 인정한다. 입 움직임은 입 벌림이 0.02 이상 되돌아간 반전을 세서 정한다. 0.75초 안에 반전이 3번 이상 이어지면 움직인 것으로 본다. 한 번 벌렸다 닫는 것(샘플 0.3~1.0초)은 발화로 세지 않는다. 임계값은 전부 임시값이다.
- **샘플(야외, 발화 없음)**: 이제 `no_mouth_movement`(발화 없음 계열)로 끝나고 적합 구간은 0초다. webrtcvad 민감도 0~3 모두 같은 결과다.
- **고친 테스트**: `test_single_speaker_video_has_eligible_segment`가 이 영상에 적합 구간이 있다고 기대했는데, 그 기대가 틀렸다. `test_sample_without_speech_has_no_eligible_segment`로 바꿨다. 원인 코드 분리 테스트는 변형본 3개(오디오 없음, 검은 화면, 무음)로만 비교한다.
- **VAD 비교** (표는 `docs/gate.md`):
  - 샘플 오디오를 음성으로 판정한 비율: webrtcvad 0.99/0.94/0.81/0.81(민감도 0~3), Silero VAD(ONNX) 0.74, YAMNet 0.91.
  - 합성 음성에 샘플 오디오를 섞은 조건의 오경보율은 Silero가 가장 낮았다.
  - 결정: **VAD는 webrtcvad 민감도 2를 그대로 쓴다.** Silero는 교체 후보로 남긴다.
  - 합성 음성은 실제 발화가 아니다. 이 비교로 정확도를 주장하지 않는다.
- **설치와 다운로드**:
  - `research/gate/.venv`에만 `onnxruntime` 1.32.0과 `protobuf` 7.36.2를 설치했다. dry-run으로 torch가 딸려 오지 않는 것을 먼저 확인했다. conda `trinity`에는 아무것도 설치하지 않았다.
  - 모델은 공식 출처(MediaPipe 모델 저장소, Silero 공식 GitHub 태그 v6.0)에서만 받았다. sha256은 `docs/gate.md`에 적었다.

**검증** (2026-11-15):

- `pytest -q`: 357개 통과, 2개 건너뜀. 건너뛴 것은 lightgbm 테스트(전부터 그랬다)와 말하는 영상 테스트(영상 없음)다.
- `python scripts/run_gate.py`로 샘플 영상을 돌렸다. `no_mouth_movement`, 입 벌림 표본 157개를 모두 쟀고 반전은 1번, 실행 약 2.3초였다.

**미검증**: 말하는 영상(내일 저장소 소유자가 찍은 영상으로 확인), 입 움직임 임계값, 다중 발화, 긴 영상의 실행 시간, 씹기·웃음처럼 말하지 않고 입이 움직이는 경우.

**남은 일**: 말하는 영상으로 임계값을 확인한다. 그다음 Gate를 Worker에 연결한다(PR #9가 합쳐진 뒤, 백로그 7번의 남은 일). Silero VAD 교체는 실제 발화 영상으로 다시 비교한 뒤 정한다.

**막힘**: 없음.

## 백로그 7번: WaveRep을 Worker에 연결 (2026-11-15 밤, 무인 작업)

**계획** (작업 전 기록):

- 레지스트리 항목에 서버 쪽 `local_path`(허가 미디어 파일, 미디어 루트 안의 상대 경로)를 둔다. 등록됐지만 파일이 없으면 `analysis_unavailable` / `video_access_unavailable`.
- `preprocessing`에서 허가 미디어를 작업 폴더로 복사하고, 모델 프로세스에는 작업 폴더 경로만 넘긴다.
- signal 축 stub을 `run_waverep` 호출로 바꾼다. 기본 MPS, 배치 1, 초당 2장.
- 개발 전용 수동 구간 설정 `TRINITY_DEV_MANUAL_SEGMENTS`(기본 꺼짐). 켜면 `gate_bypassed=true`, `partial`, `abstained`. 끄면 구간이 없으므로 signal 축은 실행하지 않는다.
- 큐에 `heartbeat()`를 추가하고 추론 프로세스를 기다리는 동안 주기적으로 lease를 연장한다. 취소·lease 상실·작업 타임아웃이면 추론 프로세스를 끝낸다.
- 축 타임아웃·실패는 `status=error`, 점수 `null`. 결과에는 프레임 logit 요약만 둔다.

**결과**:

- **바꾼 파일**: `server/jobs/worker.py`, `server/jobs/queue.py`(`heartbeat()`), `server/axes/__init__.py`(`AxisContext`), `server/axes/signal/__init__.py`(stub → 어댑터 호출), `server/axes/signal/waverep.py`(`on_tick`), `server/ingest/media_resolver.py`(`local_path`), `server/config.py`, `server/schemas/__init__.py`, `scripts/smoke_slice.py`(대기 시간), `tests/test_waverep_worker.py`(새 파일) 외 기존 테스트 3개.
- **허가 미디어 파일**: 레지스트리 항목의 `local_path`. 절대 경로, `..`, 루트 밖을 가리키는 심볼릭 링크는 설정을 읽을 때 거부한다. 저장소의 `configs/authorized_media.json`에는 `local_path`가 없다.
- **동작이 달라진 점**: 등록 ID라도 미디어 파일이 없으면 이제 `analysis_unavailable` / `video_access_unavailable`이다. 그래서 **아무 설정 없이 `smoke_slice.py`를 돌리면 등록 ID `TRINITYtest`는 접근 불가로 나온다**(전에는 stub으로 `partial`). 미디어를 연결한 레지스트리를 `TRINITY_AUTHORIZED_MEDIA`로 줘야 `partial`이 된다.
- **수동 구간 꺼짐(기본)**: signal 축은 `insufficient_input` / `gate_not_connected`, 모델 실행 안 함. `gate_bypassed=false`.
- **수동 구간 켬**: 모델 실행. `gate_bypassed=true`, `partial`, `abstained`, `overall_score=null`, 설명에 `GATE_BYPASSED_DEV`. 스키마가 `gate_bypassed`인데 `assessed`·`completed`·점수 있는 결과를 거부한다.
- **결과에 남는 것**: `axes.signal.raw_metrics.frame_logit`(프레임 수, 평균, 중앙값, 최소, 최대, 표준편차)뿐이다. 프레임별 값·실행 시간·stderr는 결과에 넣지 않는다. `raw_score`는 `null`.
- **coverage**: 영상 길이와, signal 축이 끝낸 구간(영상 길이로 자르고 겹침을 합침). `eligible_*`는 Gate가 없어 `null`.
- **heartbeat**: 추론 프로세스를 기다리는 동안 `TRINITY_HEARTBEAT_INTERVAL_SECONDS`(기본 10초)마다 lease를 연장한다. 추론 중 취소 → 프로세스 종료 후 `cancelled`, lease 상실 → 종료 후 아무것도 쓰지 않음, 작업 타임아웃 → 종료 후 `failed`/`timeout`.
- **격리**: 축 타임아웃(`TRINITY_WAVEREP_TIMEOUT_SECONDS`, 기본 300초)과 추론 실패는 `status=error`, 점수 `null`이고 나머지 축과 작업은 계속된다.
- **남긴 stub**: physics·alignment 축은 그대로 `stub_not_executed` / `model_version=stub`이다.

**검증** (2026-11-15):

- `pytest -q`: 352개 통과, 1개 건너뜀(`test_motionphys_train.py`, trinity 환경에 lightgbm이 없어서. 전부터 그랬다). 새 테스트는 가짜 추론 프로세스를 쓴다.
- 실제 실행: uvicorn + Worker를 띄우고 `smoke_slice.py`로 등록 ID `TRINITYtest` + 본인 촬영 샘플(`data/research/samples/`, 10.43초)을 요청했다.
  - `TRINITY_DEV_MANUAL_SEGMENTS=0-10.5`: `queued → processing/waverep → finished`. `gate_bypassed=true`, `partial`, `abstained`, `overall_score=null`, signal `completed`, `raw_score=null`, 프레임 21장, 장치 mps, 추론 프로세스 6.07초. logit 평균 -0.675, 중앙값 -0.900, 최소 -5.217, 최대 4.670. coverage 10.433초 / 10.433초. 작업 폴더는 남지 않았다.
  - 수동 구간 없음: signal `insufficient_input` / `gate_not_connected`, `gate_bypassed=false`, `partial`, `abstained`.
  - 미등록 ID `analysis_unavailable` / `access_not_authorized`, 잘못된 URL 422, 없는 작업 404.
- 가중치는 새로 받지 않았다. 기존 `weights_dinov2_G4.ckpt`의 md5는 `8bf19e6f68a92bed600dd97fbed3f2cd`로 기록값과 같다.

**미검증**:

- 실제 추론이 약 7초로 heartbeat 간격(10초)보다 짧았다. **실제 모델 실행 중의 lease 연장은 관찰하지 못했고**, 가짜 추론 프로세스 테스트(lease 1초, 추론 2.5초)로만 확인했다.
- 발화가 있는 영상, 합성 영상, 긴 영상, 504px 미만 영상에서의 Worker 실행.
- 큰 미디어 파일을 작업 폴더로 복사하는 동안에는 heartbeat가 없다(3.6MB 샘플에서는 문제없음).
- Flutter 앱의 실제 서버 모드에서 새 필드가 있는 결과를 여는 것(앱 코드는 바꾸지 않았다).

**§15.3 변경 제안 (README §9·§10은 바꾸지 않았다. 승인하면 문서에 반영)**:

1. §9 결과에 `gate_bypassed`(bool, 기본 `false`)를 적는다. `true`면 개발용 결과이며 항상 `partial` / `abstained` / `overall_score=null`.
2. §9 `axes.signal`에 `raw_metrics.frame_logit` 요약을 적는다. `raw_score`는 집계 방법이 정해질 때까지 `null`.
3. §9 "접근 불가 결과"에 "등록됐지만 미디어 파일이 없는 ID는 `video_access_unavailable`"을 적는다. 백로그 4번 완료 조건의 "등록된 허가 ID는 작업→결과 완료"는 미디어 파일이 연결된 ID에만 해당하게 된다.
4. §10 축별 원인 코드에 `gate_not_connected`(임시, Gate 연결 시 제거), `timeout`, `aborted`, `media_unreadable`, `model_unavailable`을 적는다. 설명 원인 코드 `gate_bypassed`도 같다.

**7번에서 남은 일**: Gate 연결(수동 구간 설정과 `gate_not_connected` 제거), 프레임 logit을 `raw_score`로 집계하는 방법 결정(백로그 8번 이후), physics·alignment stub 교체.

**실행**: README 하단 "서버 실행 방법"의 "실제 WaveRep 실행(개발 전용)".

## 앱 디자인 개정: 밝은 테마, 웹형·앱형 홈 (백로그 13번, 2026-11-14)

시안(`trinity-web-preview.html`, `trinity-app-preview.html`)의 방향을 Flutter 앱에 옮겼다. 모델 미연결 · 가상 데이터는 그대로다. API, 서버, 상태 대응, `verdict_label` 규칙은 바꾸지 않았다. 자세한 내용과 변경 이유는 `docs/design-system.md` "변경 기록".

- **먼저 한 일**: PR #7(Flutter 앱 뼈대)을 main에 합친 뒤 최신 main에서 브랜치를 만들었다.
- **테마**: 밝은 테마가 기본, 시스템이 어두운 모드면 어두운 테마(시안의 어두운 값). 이전의 `#0A0A0A` 팔레트는 없앴다. 모서리 반경 0 → 카드 14, 버튼·입력란 8, 라벨 6.
- **상태 색(밝은 테마)**: 발견 `#B63A13`, 보류 `#805B05`, 낮음은 무채색 `#2B2B2B` / 바탕 `#E8E8E8`. 이전 `#FF3D00`(흰 배경 3.55:1)과 `#FACC15`(1.53:1)는 밝은 배경에서 기준에 못 미쳐 쓰지 않는다. 두 테마의 모든 글자·배경 조합의 대비 계산이 테스트에 들어 있다(상태 색 최소 5.24:1).
- **홈**: 768 이하면 앱 배치(왼쪽 정렬 두 줄 제목, 설명, 주소 입력 카드, 폭을 채우는 버튼), 넓으면 웹 배치(가운데 워드마크, 한 줄 소개, 폭 680 캡슐 입력창, "분석 요청"과 mock 전용 "예시로 둘러보기", 접힌 "무엇을 분석하나요?", 오른쪽 위 작은 "이용 안내").
- **그 밖의 화면**: 결과에 "이번 요청의 상태"(작업·분석·판정)와 범위 카드 "어디까지 살펴봤나요?"를 넣었다. 접근 불가와 대상 아님도 같은 결과 화면 틀을 쓴다. 이용 안내 화면을 추가했고 어느 화면에서든 열 수 있다(닫으면 보던 화면으로 돌아온다).
- **가져오지 않은 것**: 시안 전용 문구, 원형 장식, 시안의 "아직은 판단할 근거가 부족해요" 제목(보류 이유와 맞지 않을 수 있다), Lucide 아이콘(Material 아이콘으로 대신), 600·650·750 굵기.
- **design-for-ai**: 지침을 읽고 참고했다. `build` 흐름(자동 커밋, 검토 에이전트)과 `research` 명령은 실행하지 않았고 `DESIGN.md`는 만들지 않았다. 지침과 다른 결정 두 가지(768 고정 전환, 가운데 정렬 웹 홈)는 문서에 적었다.
- **실행**: 이전과 같다(`app/README.md`). 브라우저 창 너비로 웹형·앱형이 바뀐다.
- **검증**: `flutter analyze` 문제 없음, `flutter test` 193개 통과(모든 화면이 너비 320·360·768·769·1280과 글자 크기 2배에서 넘치지 않음). `flutter build web --no-web-resources-cdn` 성공, headless Chrome 1280×800에서 웹 홈 확인. 모든 화면을 실제 글꼴로 렌더링해 앱 너비·웹 너비·어두운 테마를 눈으로 봤다. `pytest -q`는 서버를 바꾸지 않아 다시 돌리지 않았다(직전 315개 통과).
- **미검증·확인 필요**: 실제 서버 모드를 Chrome에서 손으로 끝까지 가 본 것, 어두운 테마를 브라우저에서 본 것, iOS·Android 기기, 화면 낭독기, 노년층 가독성, 시안과의 픽셀 단위 비교.
- **남은 일**: 저장소 소유자의 화면 검토와 피드백 반영, 공유 시트(iOS·Android), 플랫폼 빌드 설정, 미디어 확인 화면, 취소·삭제.


## Claude Code 디자인 플러그인 설치 확인

- `ryanthedev/design-for-ai` 저장소와 Claude Code 공식 설치 문서를 확인했다. 저장소는 `rtd` 마켓플레이스의 `design-for-ai` 설치와 research → plan → mock → build 흐름을 안내한다.
- 사용자의 `/reload-plugins`가 성공했다. 프로젝트 루트에서 `claude plugin list --json`을 실행해 `design-for-ai@rtd` 4.2.0이 `local` 범위로 설치되고 활성화된 상태를 확인했다.
- 다음 작업: Claude Code에서 `/design-for-ai:research`를 실행해 기존 웹·앱 시안을 디자인 브리프로 정리한다. research 명령 실행은 아직 확인하지 않았다.
- 사용 시: 이미 정한 웹 검색형·앱 세로형 방향과 README의 판정/입력 규칙을 유지하도록 전달한다. 플러그인의 기본 build 흐름에 검토 에이전트와 단계별 커밋이 포함되므로 자동 커밋·푸시를 원하지 않는 경우 사용자 지시로 명확히 제한한다.

## 웹 앱 디자인 시안 (검토용 · 제품 미반영)

- **후속 시안(2026-11-14)**: 사용자 요청에 따라 웹은 중앙 로고·주소 입력·접힌 설명의 검색형 홈, 앱은 390px 기준 세로형 홈으로 나눴다. 색·글꼴·버튼·결과의 의미는 공유하고 화면 구성을 달리한다. Claude Code에서 기존 Flutter 앱에 반영하도록 전달할 구현 프롬프트도 대화에 제공했다.
- **최신 시안 경로**: 웹 `/Users/iyeonje/.codex/visualizations/2026/11/01/01a1964d-85b8-7920-b247-cf9cb86a6c5d/trinity-web-preview.html`, 앱 `/Users/iyeonje/.codex/visualizations/2026/11/01/01a1964d-85b8-7920-b247-cf9cb86a6c5d/trinity-app-preview.html`. 아래의 `trinity-calm-preview.html`은 최초 통합 시안이다.
- **후속 확인**: 두 파일의 HTML 중첩·ID 참조·JavaScript 구문 점검 통과. 브라우저에서 웹·앱 첫 화면과 예시 시작 → 진행 → 판단 보류 전환을 확인했다. 앱 시안은 320px 뷰포트(내부 288px)에서 입력·결과의 가로 넘침 없음. 모바일 네이티브 앱을 빌드하거나 테스트한 것은 아니다.
- **한 일**: 밝고 차분한 화면 구성을 제안하는 클릭 가능한 시안을 만들었다. URL 입력 → 분석 중 → 결과 → 판단 근거와 이용 안내를 포함한다. 결과 예시는 판단 보류·의심 신호 발견·의심 신호 낮음·영상 접근 불가로 바꿀 수 있다. 가상 데이터 고지, URL-only, 상태 분리, 값 없음, 분석 범위의 의미를 유지했다.
- **위치/보는 방법**: Codex 대화의 시안에서 “예시로 둘러보기”를 누른다. 원본은 `/Users/iyeonje/.codex/visualizations/2026/11/01/01a1964d-85b8-7920-b247-cf9cb86a6c5d/trinity-calm-preview.html`에 있다. 서버·모델 연결 없이 화면만 전환한다.
- **확인**: 브라우저에서 예시 시작, 분석 중 → 판단 보류, 의심 신호 발견으로 전환, 판단 근거 화면을 확인했다. 320px 뷰포트에서 입력·결과 영역의 가로 넘침이 없음을 확인했다. 미리보기의 폼 제출 제한을 확인하고 로컬 버튼/Enter 동작으로 처리했다. 수정 후 빈 입력 안내와 올바른 URL 입력의 화면 전환을 다시 확인했다.
- **남은 일/막힌 점**: (2026-11-14 갱신) Flutter 반영을 마쳤고 밝은 테마·둥근 모서리를 채택했다. 위 "앱 디자인 개정" 절을 본다. 아래는 시안을 만들 때의 기록이다. 앱 코드와 API 계약은 바꾸지 않았다. 앱 테스트를 다시 실행한 것은 아니며, 모든 기기·화면 낭독기 검증은 미검증이다.

## 백로그 13번: Flutter 앱 (진행 중, 앞부분만. 웹에서만 확인)

모델 미연결이다. 화면의 결과는 가상 데이터이며 모든 화면 상단에 "모델 미연결 · 가상 데이터" 띠가 있다. 자세한 내용은 `docs/design-system.md`, `app/README.md`.

- **API 계약 변경(README §9, 결정 8)**: 결과에 `verdict_label`(`suspicious_signals` / `low_suspicion` / `null`)을 추가했다. 요약 화면이 숫자 없이 발견과 낮음을 구분하기 위한 필드다. `verdict_status=assessed`일 때만 값을 가질 수 있고(스키마가 거부), 검증된 결합 모델이 없어 **서버는 항상 `null`을 보낸다.**
- **서버 CORS**: `TRINITY_CORS_ORIGINS`(기본 `http://localhost:8080,http://127.0.0.1:8080`). localhost·127.0.0.1만 받고 `*`와 다른 호스트는 시작할 때 거부한다. 메서드는 GET·POST, 헤더는 `Content-Type`·`X-Client-Token`만 연다. 빈 값이면 끈다.
- **만든 파일**: `app/`(Flutter 웹 프로젝트), `docs/design-system.md`, `tests/test_cors_and_label.py`. 바꾼 파일: `server/{config.py,api/__init__.py,schemas/__init__.py,jobs/worker.py}`, `tests/test_api.py`(계약 키 목록).
- **디자인 시스템**: 색 토큰 8개(초록 없음, 강조색은 "의심 신호 발견"에만), Inter Tight + JetBrains Mono + Noto Sans KR, 모서리 반경 0, 8pt 그리드, 좌우 여백 20. 공통 위젯 8종. 본문 16, 보조 13, 줄간격 1.5, 글자 대비 5.2:1 이상, 터치 영역 48.
- **글꼴**: 쓰는 굵기 5개만 `app/assets/fonts/`에 넣었다(약 4.9MB). OFL 원문은 `app/assets/fonts/licenses/`. Fontsource 배포본을 받았고 파일 해시를 문서에 적었다.
- **화면 8개**: 입력, 분석 중(단계명만, 숫자 % 없음), 결과 3종(발견 / 낮음 / 판단 보류, 숫자 점수 없음), 판단 근거 상세(원시 지표에 "확률 아님", `null`은 "값 없음"), 영상 접근 불가, 분석 대상 아님. 작업 실패·취소는 분석 중 화면의 "끝내지 못함" 상태로 보여 준다.
- **모드**: `--dart-define=TRINITY_API_MODE=mock|server`, `TRINITY_API_BASE_URL`. mock은 입력 화면에서 가상 결과 6종을 고른다. **실제 서버 모드에서는 라벨이 와도 발견·낮음을 보여 주지 않는다**(판단 보류로 표시).
- **실행**:
  ```bash
  cd app && flutter pub get
  flutter run -d chrome --web-port 8080 --no-web-resources-cdn                      # mock
  flutter run -d chrome --web-port 8080 --no-web-resources-cdn \
    --dart-define=TRINITY_API_MODE=server --dart-define=TRINITY_API_BASE_URL=http://localhost:8000   # 서버와 Worker가 떠 있을 때
  flutter analyze && flutter test
  dart run tool/smoke_server.dart http://localhost:8000 'https://www.youtube.com/watch?v=TRINITYtest'
  ```
- **검증**:
  - `flutter analyze` 문제 없음, `flutter test` 122개 통과(Flutter 3.41.6). 화면마다 글자 크기 1.3배·2배(360×640, 320×568)에서 넘침 없음.
  - `pytest -q` 315개 통과, 1개 건너뜀(conda `trinity`).
  - `flutter build web --no-web-resources-cdn` 성공. Chrome(headless)에서 mock 모드 입력 화면이 번들 글꼴로 뜨는 것을 확인했다.
  - 실제 서버 + Worker에 앱의 API 클라이언트로 요청: 등록 ID는 8단계를 거쳐 `partial / abstained / verdict_label=null`(판단 보류 화면), 미등록 ID는 `analysis_unavailable`(접근 불가 화면), YouTube가 아닌 주소는 422. `localhost:8080` 출처의 CORS 사전 요청은 200, 다른 출처는 400.
- **미검증·확인 필요**:
  - 실제 서버 모드를 Chrome에서 손으로 눌러 끝까지 가 본 것은 아니다.
  - iOS·Android 기기, 화면 낭독기, 실제 노년층 사용자 가독성.
  - Fontsource 패키지의 정확한 버전(`@latest`로 받음), Noto Sans KR OFL의 Reserved Font Name 조항과 부분집합 파일의 관계.
- **남은 일 (13번)**: YouTube 공유 시트 수신(iOS·Android), 플랫폼 빌드 설정, 미디어 확인 화면(제목·썸네일), 취소·삭제, 새로고침 뒤 작업 복원(토큰 저장은 백로그 14번의 인증과 함께), 모델 연결 뒤 고지 띠 제거 조건 정하기.


## 백로그 9번: 압축 에뮬레이터 (범용 프로파일까지. 플랫폼 파라미터 추정은 하지 않음)

실제 YouTube의 재인코딩과 같다고 주장하지 않는다. 어떤 영상도 YouTube에 올리지 않았다. 성능 결과가 아니다. 자세한 내용은 `docs/compression-emulator.md`.

- **공개 코드**: `truebees-ai/social_emulator`가 있다(커밋 `3e1a39a`, `LICENSE`는 CC BY 4.0). `research/emulator/upstream/`에 clone(Git 제외)하고 수정 없이 `research/emulator/.venv`에서 두 단계를 실행했다. `breakpoint()`가 남아 있어 `PYTHONBREAKPOINT=0`으로 껐다.
- **저자 방식의 에뮬레이션은 못 했다**: 원본과 플랫폼 처리본의 쌍이 필요한데 저장소에 파라미터 파일과 샘플이 없고 우리에게 처리본이 없다. 플랫폼 처리본 자리에 로컬 파일(`x264-crf28-720p`)을 넣어 동작만 확인했다. 해상도는 되찾았고 CRF는 28이 아니라 29로 나왔다(비트레이트가 처음 낮아지는 값을 고르는 규칙). 원본 코드의 출력에는 오디오가 없다.
- **만든 파일**: `training/emulator/{profiles,video,pipeline}.py`, `research/emulator/{run_upstream_smoke.py,requirements.lock.txt}`, `scripts/compression_profile_report.py`, `tests/test_emulator.py`, `docs/compression-emulator.md`. 표준 라이브러리만 쓴다(trinity에 새 의존성 없음).
- **범용 프로파일**: libx264 CRF 20/28/34 × 원본/1080/720/480(짧은 변) = 12개. 하드웨어 인코더 거부, 업스케일은 `skipped_upscale`, 오디오는 복사.
- **`emulate(입력, 프로파일 ID, 출력 폴더)`**: 스레드 고정 + bitexact + 메타데이터 제거로 같은 입력이면 같은 바이트. 설정·FFmpeg 버전·입출력 sha256·계보·상태를 출력 옆 `.json`에 기록. 원본과 기존 출력을 덮어쓰지 않는다.
- **manifest·평가 연결**: 선택 열 `compression_profile_id`(빈칸은 원본, 예전 manifest도 읽힘). 파생 행은 부모의 분할과 계보를 물려받는다. 리포트에 `by_compression`(조건별 AUC·TPR·실제 FPR, 그룹 bootstrap). 리포트 `schema_version` 2.
- **출력 비교** (본인 촬영 영상 1개, 1080p 10.4초): 12개 모두 두 번 실행한 sha256이 같다. 영상 비트레이트는 CRF 20 원본 해상도 5,768 kbps에서 CRF 34 480p 218 kbps까지. 표는 문서 §5.
- **규칙(저장소 소유자 결정, 2026-11-14)**: 최종 평가에 남겨 둘 프로파일은 학습을 시작하기 전에 고정한다. 어떤 프로파일을 남길지는 아직 정하지 않았다.
- **실행**:
  ```bash
  conda activate trinity
  pytest -q
  python scripts/compression_profile_report.py --video data/research/samples/<허가 영상>.mp4
  python -m training.emulator.pipeline --manifest <m.csv> --media-root <dir> --profile x264-crf28-720p --out-dir <dir> --out-manifest <m2.csv>
  research/emulator/.venv/bin/python research/emulator/run_upstream_smoke.py --video data/research/samples/<허가 영상>.mp4
  ```
  환경 준비는 문서 §7. 두 스크립트는 출력 폴더가 이미 있으면 멈춘다(`data/research/emulator/` 아래, Git 제외).
- **검증**: `pytest -q` 290개 통과, 1개 건너뜀(conda `trinity`, LightGBM이 없는 `tests/test_motionphys_train.py`).
- **미검증·확인 필요**: 다른 기기·다른 FFmpeg/x264 버전에서의 출력 동일성, 가변 프레임률·회전 메타데이터·복사할 수 없는 오디오 코덱, 코드에 적용된 CC BY 4.0의 세부 해석, 원본 코드의 `h264` 인코더 이름이 다른 빌드에서 하드웨어 인코더로 풀리는지, YouTube Studio에서 받은 파일이 플랫폼 처리본인지.
- **남은 일 (9번)**:
  - 최종 평가용 프로파일 고정(학습 시작 전), dev에 넣을 압축 조건 결정.
  - 모델 점수의 압축 민감도(README §13.2 C1~C3), 원본과 압축본을 짝지은 점수 차이 지표. 데이터와 영상 단위 점수가 생긴 뒤.
  - 향후 경로: 저장소 소유자가 직접 찍은 영상을 본인 채널에 올려 YouTube Studio에서 받은 파일과 쌍으로 실제 파라미터를 추정(받은 파일이 처리본인지 확인 필요). **지금은 업로드하지 않는다.**
  - 오디오 재인코딩·프레임률·반복 인코딩·화질 지표.


## 백로그 10번: MotionPhys 기본·얼굴 영역·Face Motion (진행 중, 앞부분만)

특징 추출기와 데이터 없이 할 수 있는 검증까지다. 분류기를 학습하지 않았고 점수를 내지 않았다. 진위를 해석하지 않는다. 자세한 내용은 `docs/motionphys-spec.md`(정의), `docs/motionphys-spike.md`(측정).

- **재구현**: 공개 코드가 없어 논문(arXiv:2608.20770v1) 본문만 보고 만들었다. 식 (3)~(19)는 그대로, 논문에 없는 숫자(코너 수, 격자 간격, LK 설정, 처리 해상도, ε, 유효 궤적 기준 등)는 "우리 선택"으로 정해 문서에 구분해 적었다. 논문의 수치를 재현했다고 주장하지 않는다.
- **만든 파일**: `research/motionphys/{kinematics,tracking,faces,extract,train_lgbm}.py`, `research/motionphys/requirements.lock.txt`, `configs/motionphys_models.json`, `scripts/motionphys_compression_spike.py`, `tests/test_motionphys_{kinematics,extract,train}.py`.
- **환경**: `research/motionphys/.venv`(Python 3.11.18). opencv-contrib-python 5.0.0.93, numpy 2.4.6, lightgbm 4.7.0, mediapipe 1.2.3. torch 없음(설치 전후 확인). trinity 환경은 바꾸지 않았다.
- **세 후보** (같은 인터페이스: 영상 + 구간 → 특징 벡터, 유효 궤적 수, 상태): A 전체 화면 504차원, B 얼굴 영역 504차원, C Face Motion 1,512차원(머리·눈썹·입술). 움직임이 부족하면 `insufficient_motion`, 추적이 안 되면 `tracking_failed`, 특징은 `null`. 기준값은 임시값이다.
- **모델 파일**: Face Landmarker를 새로 받았다(`data/models/motionphys/face_landmarker.task`, Git 제외). 출처 URL과 sha256은 `configs/motionphys_models.json`과 `docs/motionphys-spec.md` §7. **모델 파일의 이용 조건은 확인 필요**(코드는 Apache 2.0, 안내 페이지는 CC BY 4.0까지만 확인. 모델 카드는 읽지 않았다).
- **압축 측정 결과** (본인 촬영 영상 1개, libx264 CRF 20/28/34, 10.4초 구간):
  - 같은 입력 두 번의 차이는 0.
  - 압축보다 표본 프레임의 위치가 특징을 더 크게 움직였다. jerk 특징 변화의 중앙값: CRF 34에서 A 2.8%, B 3.3%, C 8.5%. 압축 없이 표본을 한 프레임 민 대조군에서 A 6.4%, B 8.4%, C 9.5%.
  - jerk가 가장 민감하지는 않았다. 곡률 특징이 더 많이 움직였다.
  - 24프레임 스케일(클립 2개)은 불안정하다. A의 jerk 대표값이 CRF 34에서 −53%, 대조군에서 +71%.
  - C는 CRF 20에서도 곡률 특징이 17% 움직였다(입술 영역 대표값 +52% ~ +77%).
  - 유효 궤적 수와 추적 성공률은 압축에 거의 영향받지 않았다.
- **이 측정으로 말할 수 없는 것**: 압축이 진짜를 가짜로 판정하게 만드는지. 분류기와 가짜 영상이 없다. 프레임 간격이 0.22초라 짧은 구간(연속 프레임)에서는 결과가 다를 수 있다.
- **실행**:
  ```bash
  research/motionphys/.venv/bin/python -m pytest -q --noconftest tests/test_motionphys_kinematics.py tests/test_motionphys_extract.py tests/test_motionphys_train.py
  research/motionphys/.venv/bin/python scripts/motionphys_compression_spike.py --video data/research/samples/<허가 영상>.mp4
  ```
  환경과 모델 파일 준비는 `docs/motionphys-spec.md` §8. `--noconftest`는 motionphys 환경에 fastapi가 없어서 필요하다.
- **검증**: `research/motionphys/.venv`에서 49개 통과. conda `trinity`에서 전체 265개 통과, 1개 건너뜀(LightGBM이 없어 `tests/test_motionphys_train.py`).
- **미검증·확인 필요**: 논문에 없는 설정 전부(`docs/motionphys-spec.md` §9), 구간 길이에 따른 프레임 간격 차이의 영향, 짧은 구간·원본 해상도·다른 영상에서의 압축 민감도, 24프레임 스케일이 불안정한 원인, C의 불안정이 특징점 떨림 때문인지, MediaPipe 모델 파일의 이용 조건.
- **남은 일 (10번)**: DeepSpeak v2 승인 뒤 특징 추출 → `train_lgbm.py`로 학습 → 평가 파이프라인으로 A·B·C 비교(유효 궤적 비율, AUC, TPR@5%FPR, 추론 시간) → 축 유지/제거 결정. A+C, B+C 결합. 원본과 압축본의 점수 차이 측정(README §13.2 C1~C5). 서버 어댑터와 Worker 연결.
- **의존성 메모**: 10번은 6번(Gate)·8번·9번에 의존한다. Gate 브랜치는 main에 없어서 얼굴 검출은 `research/motionphys` 안에서 MediaPipe를 직접 부른다. 압축은 9번의 `social_emulator`가 아니라 FFmpeg CRF만 썼다.


## 백로그 8번: 데이터 위생·고정 평가 파이프라인 (진행 중, 뼈대만)

실제 데이터 없이 합성 manifest와 합성 점수로 끝까지 도는 뼈대다. 성능 결과가 아니다. 자세한 내용은 `docs/evaluation-pipeline.md`.

- **만든 파일**: `training/datasets/{manifest,groups,mavos}.py`, `training/hygiene.py`, `training/evaluation/{metrics,thresholds,lock,run}.py`, `configs/external_eval_lock.json`, `tests/test_eval_pipeline.py`, `tests/test_mavos_external.py`. 표준 라이브러리만 쓴다(trinity에 새 의존성 없음).
- **공통 manifest**: 영상 경로, 라벨, 위조 유형, 생성기, 인물 ID, 원본 계보 ID, 데이터셋, 분할(`train`/`dev`/`test`/`external`) 등. 원본 계보 ID는 필수, 인물 ID는 선택(없으면 경고).
- **누수 검사**: 인물·원본 계보로 이은 그룹이 여러 분할에 걸치면 실패. 외부 세트와 내부 분할 사이의 원본·인물·해시 겹침을 따로 보고. 실패한 manifest로는 임계값도 평가도 거부한다. 경고 개수는 평가 리포트에 항상 싣는다.
- **지표**: ROC-AUC, dev 임계값을 적용한 TPR·실제 FPR, 생성기별(기본)·유형별(보조, 잠정), 보류율과 coverage, 그룹 단위 bootstrap 신뢰구간.
- **임계값**: dev에서만 정한다. 파일은 새로만 만들 수 있고 내용이 바뀌면 불러올 때 거부한다. `evaluate`는 임계값을 숫자로 받지 않는다.
- **외부 평가 잠금**: MAVOS-DD, TalkingHeadBench, Deepfake-Eval-2024를 `locked`로 등록했다. 풀려면 `configs/external_eval_lock.json`을 고쳐 커밋하고 `--final-external`을 줘야 한다. **아직 풀지 않는다.**
- **MAVOS-DD 메타데이터 검사 (추론 없음)**: 표본 목록 sha256이 잠금 값과 일치, 2,160개 모두 있고 크기 일치, 층 규칙 위반 없음. 경고: 인물 ID 없음 2,160, 원본 식별자 없음 448(21%), 파일 해시 없음 2,160. 공통 manifest는 `data/research/mavos-dd/common-manifest.csv`(Git 제외)에 썼다.
- **실행**:
  ```bash
  conda activate trinity
  pytest -q
  python -m training.hygiene <manifest.csv>
  python -m training.evaluation.run fit-threshold --manifest <m> --scores <s> --model-id <id> --out <threshold.json>
  python -m training.evaluation.run evaluate --manifest <m> --scores <s> --threshold <threshold.json> --split test --out <report.json>
  python -m training.datasets.mavos check
  ```
- **검증**: `pytest -q` 225개 통과(conda `trinity`, 건너뛴 테스트 없음). 실제 MAVOS-DD 표본 목록 검사 포함.
- **미검증·확인 필요**:
  - 실제 데이터로 실행한 적이 없다. 단일축 기초 평가 리포트는 없다(8번 완료 조건의 나머지).
  - MAVOS-DD와 학습 데이터 사이의 원본 겹침. 비교할 내부 데이터가 없다. 두 데이터셋의 원본 ID 체계가 달라도 같은 영상일 수 있는지.
  - 큰 데이터에서의 bootstrap 실행 시간.
- **남은 일**:
  - DeepSpeak v2 승인 뒤: 필드를 공통 manifest로 바꾸는 변환기, 그룹 분할, 누수 검사, WaveRep 단일축 평가 리포트.
  - 프레임 logit을 영상 점수로 집계하는 방법을 dev에서 정하기(지금 WaveRep 어댑터의 `raw_score`는 `null`).
  - README §6.4의 나머지 점검(영상 유사도, 무음 편향, 코덱·해상도 shortcut), 압축 조건별 지표, 보정 지표.
  - 백로그 7번의 남은 일(Gate·Worker 연결)은 아래 절에 그대로 있다.


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
- 대체 방안은 아래 "결정 6 변경"에서 정했다.

## 결정 6 변경: 최종 외부 평가 자료 (2026-11-13, 브랜치 `docs/decision-6-external-eval`)

README 설계 문구와 접근 기록을 바꾸고, MAVOS-DD 표본 목록을 만드는 스크립트를 추가했다. 서버 코드는 바꾸지 않았다.

- **결정**: 최종 외부 평가를 MAVOS-DD open-set model 분할과 TalkingHeadBench로 대체한다. Deepfake-Eval-2024는 재신청을 검토하고 승인되면 실전 유통본 평가로 추가한다. 실제 SNS 유통본으로 평가하지 못하면 결과 보고에 한계를 명시한다.
- **바꾼 곳**: README §6.1(역할 표, 우선 접근 원칙), §6.3, §6.5, §13.1, §14.1 3번 행, §15.3 결정 6, §16, `AGENTS.md`의 최종 평가 전용 줄, `docs/dataset-access.md`(MAVOS-DD 절 추가).
- **MAVOS-DD 확인한 것**: CC BY-NC-SA 4.0, 자동 승인 방식 접근 제한, 전체 약 308.4 GB(mp4 87,038개), 폴더(언어·생성기) 단위로 일부만 받을 수 있는 구조. 폴더별 파일 수·용량 표를 `docs/dataset-access.md`에 넣었다(전체 기준, 분할 구분 없음).
- **표본 추출 규칙**: 구조(층화, 고정 시드, 진짜·가짜 비율, 생성기당 상한, 교체 금지)를 `docs/dataset-access.md`에 먼저 고정했다. 숫자는 미정이다.
- **MAVOS-DD 메타데이터 (2026-11-13)**: 접근이 승인돼 메타데이터만 받았다(`data/research/mavos-dd/`, 영상 없음). open-set model 분할은 43,959개, 155.3 GB(진짜 15,547, 가짜 28,412). 생성기별·언어별 표와 원본 영상 묶음 추정을 `docs/dataset-access.md`에 넣었다.
- **표본 규칙 고정 (2026-11-13, 저장소 소유자 승인)**: 층당 20개(생성기당 120), 원본 묶음당 2개, 진짜:가짜 1:1, 시드 20261113. 표본 2,160개, 6.77 GB. `manifest-q20.csv`의 sha256과 확장용 `manifest-q25.csv`(8.45 GB, q20을 포함)의 sha256을 `docs/dataset-access.md`에 적었다. 만든 파일: `scripts/mavos_sample.py`, `research/mavos/export_metadata.py`, `research/mavos/download_sample.py`, `research/mavos/requirements.lock.txt`, `tests/test_mavos_sample.py`.
- **표본 수신 (2026-11-13)**: 규칙 커밋(`dee503f`) 뒤에 2,160개를 받았다. 6,766,772,622바이트로 목록과 일치. 받은 뒤 디스크 여유는 약 50.5 GiB(`df` 기준, 받기 전 59 GiB). 표본은 모델에 넣지 않았다. 모델과 임계값을 고정하기 전에는 이 표본으로 추론 결과를 보지 않는다.
- **남은 일**: DeepSpeak v2 승인 뒤 생성기가 MAVOS-DD와 겹치는지 확인, TalkingHeadBench 접근 절차 확인, Deepfake-Eval-2024 재신청 검토. PR #3은 main에 합쳤다.
- **정정**: 지난 갱신에서 `docs/dataset-access.md`의 TalkingHeadBench "확인 필요" 표에 잘못 넣은 Deepfake-Eval-2024 거절 관련 두 줄을 Deepfake-Eval-2024 절로 옮겼다.
- **검증**: `pytest -q` 124개 통과(conda `trinity`). 문서 변경이라 새 테스트는 없다.

## 백로그 6번: 최소 발화 구간 Gate (구현함, 알려진 문제 있음, main에 합치지 않음)

**알려진 문제 (2026-11-12, 저장소 소유자 확인):**

- 샘플 영상은 실제로 발화가 없다(야외, 주변 소음). 그런데 VAD가 대부분을 음성으로 판정했다.
- 단일 발화 테스트의 기대값이 틀렸을 수 있다(`tests/test_gate_media.py::test_single_speaker_video_has_eligible_segment`).
- 입 움직임 확인 추가와 VAD 비교가 필요하다.
- 발화가 있는 영상은 아직 없다.
- Gate 수정은 미뤘다. 코드는 고치지 않았다. **이 브랜치(`feat/gate-speech-segments`)는 `main`에 합치지 않는다.**
- 아래의 "원본 `null`(적합 구간 0~10.433초)"과 README §14.1 6번 행의 "단일 발화 ... 확인"은 이 문제의 영향을 받는다. 그대로 믿지 않는다.
- `docs/waverep-spike.md`의 입력 설명을 "본인 얼굴, 주변 소리, 발화 없음"으로 정정했다. `docs/media-access.md` §3의 "본인 얼굴과 본인 음성만"은 허가 미디어의 범위 규칙이라 고치지 않았다. 현재 샘플에 본인 음성(발화)이 없다는 점은 거기에 적혀 있지 않다.

허가 미디어 파일 하나를 받아 적합 발화 구간과 원인 코드를 돌려주는 `server/gate` 모듈이다. 모델 추론은 하지 않는다. Worker에는 연결하지 않았다. 자세한 내용은 `docs/gate.md`.

- **구성**: `probe.py`(ffprobe), `vad.py`(FFmpeg PCM 파이프 + `webrtcvad`), `faces.py`(MediaPipe Face Detector), `segments.py`(추적과 규칙, 순수 함수), `types.py`(자료형·원인 코드·임시 임계값). 진입점은 `server.gate.run_gate(media_path)`.
- **규칙**: 음성 구간 동안 주된 얼굴이 정확히 하나일 때만 적합 구간이다. 둘 이상이면 `speaker_unconfirmed`.
- **원인 코드**: `media_unreadable`, `audio_missing`, `no_speech_detected`, `no_face_detected`, `speaker_unconfirmed`, `low_resolution`, `face_too_small`, `too_blurry`, `segment_too_short`. README §10에 추가했다.
- **coverage**: `video_duration_sec`와 `eligible_duration_sec`만 채운다. `analyzed_*`와 비율은 `null`(백로그 7번에서 채운다).
- **의존성**: `requirements-gate.txt`(버전 고정)를 conda `trinity`에 설치했다. `mediapipe` 1.2.3, `webrtcvad-wheels` 2.0.14.post1, `opencv-contrib-python` 5.0.0.93, `numpy` 2.4.6 등. **torch는 없다**(설치 전 dry-run과 설치 후 모두 확인). 먼저 `research/gate/.venv`에서 스모크했고 lockfile은 `research/gate/requirements.lock.txt`.
- **모델 파일**: `data/models/gate/blaze_face_short_range.tflite`(Git 제외). sha256은 `configs/gate_models.json`. 해시가 다르면 실행을 거부한다.
- **실행**:
  ```bash
  conda activate trinity
  pip install -r requirements-gate.txt
  python scripts/run_gate.py data/research/samples/<허가 영상>.mp4
  pytest -q
  ```
  모델 파일을 받는 방법은 `docs/gate.md` "재현 방법".
- **검증**: `pytest -q` 96개 통과(conda `trinity`, 건너뛴 테스트 없음). 실제 영상 4종의 대표 원인 코드: 원본 `null`(적합 구간 0~10.433초), 오디오 제거본 `audio_missing`, 검은 화면본 `no_face_detected`, 무음 오디오본 `no_speech_detected`. 변형은 테스트 중 임시 폴더에 만들고 끝나면 지운다.
- **미검증·확인 필요**:
  - 여러 명이 말하는 영상(동의받은 영상 없음). `speaker_unconfirmed`는 합성 표본을 넣은 규칙 단위 테스트로만 확인했다.
  - 임계값 전부(임시값). 품질 원인 코드는 실제 저품질 영상으로 실행하지 않았다.
  - 화면 밖 발화자는 구분하지 못한다(보이는 얼굴이 말한다고 가정).
  - VAD가 샘플 전체를 한 음성 구간으로 묶었다. 실제 발화와 맞는지 사람이 대조하지 않았다. `webrtcvad`의 정확도는 비교하지 않았다.
  - MediaPipe 얼굴 검출 모델 파일의 이용 조건, 세로(회전) 영상에서의 프레임 방향.
- **백로그 7번에서 할 일**: Gate를 Worker의 `preprocessing` 단계에 연결, 원인 코드를 `analysis_status`에 대응, `analyzed_*` coverage 채우기, Gate 실행 중 heartbeat, 서버가 발급한 작업 경로만 넘기기.

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
pip install -r requirements-gate.txt  # Gate용(선택). torch 없음
pytest -q
uvicorn server.main:app --reload      # 터미널 1
python -m server.jobs.worker          # 터미널 2
python scripts/smoke_slice.py         # 터미널 3
```

## 남은 일

- 백로그 1·3번은 기록을 만들었고 둘 다 진행 중이다(`docs/media-access.md`, `docs/dataset-access.md`). 4번은 원래 1번에, 5번은 3번에 의존한다.
- 다음 순서: 6번 Gate의 알려진 문제(발화 없는 영상을 음성으로 판정)를 먼저 해결할지 정한다. 발화가 있는 허가 영상이 필요하다. 그 전에는 7번에서 Gate를 Worker에 연결하지 않는다. 1·3번의 확인 필요 항목은 병렬로 처리한다. 데이터셋 승인은 기다려야 한다.
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
