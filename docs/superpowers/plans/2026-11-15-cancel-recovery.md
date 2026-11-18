# 취소·삭제·복구 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 이 세션에서 직접 구현하고 마지막에 독립 코드 검토를 한다.

**Goal:** 백로그 14번 중 소유권이 적용된 DELETE, Worker 복구·정리, 앱 취소를 완성한다.
**Architecture:** 기존 SQLite 트랜잭션과 cancel_requested를 사용한다. API는 취소를 접수하고 Worker가 프로세스 종료·폴더 정리를 마친 뒤 종료 상태를 기록한다. 진행 수명주기 ETag로 취소 버튼과 완료의 경합을 막는다.
**Tech Stack:** Python 3.11, FastAPI, SQLite, macOS 프로세스 그룹, Flutter.
**Spec:** 사용자가 2026-11-15 대화에서 승인한 요구사항과 docs/DESIGN.md §8·9·10·12·14.1·15.3.

## Global Constraints

- 새 상태·JSON API 필드 없음. URL-only, AuthorizedMediaRegistry, 점수 null 유지.
- 진행 중 ETag는 단계·선점·heartbeat·재시도에 불변, 종료 때만 변경.
- 일반 DELETE: 진행 중 202, 종료 작업 204, 소유자 불일치/삭제 후 404, 토큰 없음 401.
- 앱은 활성 ETag를 If-Match로 보내며 412에는 재조회. 기록 삭제를 연속 호출하지 않음.
- 최신 origin/main에서 새 브랜치. main merge 금지. PR 도구·모델 명시.

## Review Focus

- 취소 접수와 정상 종료 경합: 접수된 취소가 완료 쓰기에 덮이지 않아야 한다.
- 정리 실패: 파일이 남았는데 종료/삭제 성공으로 보고하지 않아야 한다.
- lease 상실 후 오래된 Worker: 재시도 작업 폴더를 지우거나 결과를 덮지 않아야 한다.
- 브라우저 CORS: If-Match 허용 및 ETag 노출, 임의 출처 거부 유지.
- 앱 네트워크 실패·polling 경합: 일반 DELETE로 대체하거나 자동 재삭제하지 않아야 한다.

### Task 1: 계약·API·큐

**Files:** README.md, server/api/analyses.py, server/api/__init__.py, server/jobs/queue.py, tests/test_analysis_delete.py.
**Interfaces:** GET 상태의 ETag, DELETE If-Match 및 기존 AnalysisStatusResponse. 큐 안에서 소유권·ETag·상태 분기를 원자적으로 수행.
- [x] 승인된 보완을 §9·§15.3에 먼저 기록.
- [x] 토큰/소유권/202 반복/204/404/ETag 불변/412 비파괴/CORS 테스트 작성 및 실패 확인.
- [x] API·큐 구현 후 해당 테스트 통과 확인.

### Task 2: Worker 복구·정리

**Files:** server/jobs/worker.py, server/jobs/queue.py, server/jobs/runtime.py, tests/test_job_lifecycle.py, tests/test_queue_worker.py.
**Interfaces:** Worker 정리 함수를 큐 복구에 전달; 정리 후에만 종료 상태 노출.
- [x] 정상·실패·취소·타임아웃 정리 순서, 재시도 상한·재선점·실제 재시작·자식 종료 테스트 작성 및 실패 확인.
- [x] 폴더 정리와 Worker 중복 처리 방지 보완. 기존 프로세스 그룹 종료 재사용.
- [x] 대상 테스트와 pytest -q 전체 확인.

### Task 3: 앱 취소

**Files:** app/lib/api/{analysis_api,models,mock_api}.dart, app/lib/app.dart, app/lib/screens/progress_screen.dart, app/test/{api,flow}_test.dart.
**Interfaces:** JobState 내부 ETag(전송 JSON에는 없음), AnalysisApi.cancel(id), 412 정상 재조회.
- [x] 진행 중 취소·중복 클릭·412 결과 표시·조건부 헤더·재삭제 없음 테스트 실패 확인.
- [x] 실제/Mock API와 화면 연결, flutter test 전체와 flutter analyze 확인.

### Task 4: 통합 확인·PR

**Files:** scripts/smoke_cancel_worker.py, docs/HANDOFF.md.
- [x] 실제 uvicorn·Worker와 허가 미디어로 진행 중 DELETE → cancelled, 폴더 정리 확인.
- [x] 독립 코드 검토, 필요한 수정은 회귀 테스트로 검증.
- [x] 전체 pytest -q / flutter test 결과와 미검증 범위 기록.
- [x] HANDOFF 갱신, 커밋·push·PR 생성. main merge 없음.

## 진행 기록

- 2026-11-15: 사용자 계획 및 조건부 DELETE 승인. origin/main 3f0f2b4에서 codex/cancel-recovery-security 생성.
- 작업 위치: 사용자 요청대로 현재 체크아웃의 새 브랜치에서 실행. 별도 worktree 생성 없음.

- Task 1: 완료. 계약 테스트 13개 RED→GREEN. 취소 접수와 finish 경합은 같은 SQLite 트랜잭션에서 cancel_requested 우선으로 처리.
- Task 2: 주요 구현 완료. 정리 후 종료, lease 만료 재시도/상한, 살아 있는 이전 Worker 잠금, 실제 Worker SIGKILL 재시작 테스트 추가.
- Task 3: 완료. Flutter 취소/412/중복 클릭/mock 4개 RED→GREEN. 전체 202개 통과.
- Final review: GPT-6 Astra 독립 검토에서 P1 고아 자식, P2 무관한 폴더 정리 실패의 전체 큐 차단 발견.
- Final: P1/P2 재현 테스트 3개 RED 확인. supervisor가 Worker 생존 파이프 EOF에서 실제 프로세스 그룹을 종료하고 runtime 잠금을 함께 상속한다. 무관한 종료/고아 폴더 정리 실패는 경고 후 다음 폴더/작업을 처리한다.
- Ruling: 수명주기 ETag는 사용자 승인대로 진행 중 불변이며 Cache-Control no-store로 제공한다. 단계별 응답 캐시 검증용으로 사용하지 않는다.
- Ruling: flock + supervisor의 잠금 FD 상속으로 같은 호스트의 이전 실행과 복구를 격리한다. 살아 있으나 멈춘 Worker는 강제 종료해야 복구된다. lease만으로 동시 재실행해 파일을 훼손하는 위험을 막는다.
- 실제 스모크(첫 실행): Gate 자식 실행 중 조건부 DELETE 202, 반복202, cancelled·폴더정리, stale412 비파괴, 일반204, 조회/재삭제404. 약 1.02초. supervisor 보완 후 재검증도 성공: 약 0.99초.

- Final: fixed P1/P2 — 테스트 3개 RED→GREEN, Gate/WaveRep/복구 관련 134개 통과, 최종 전체 468 passed / 2 skipped / 1 기존 경고.
- 최종 Flutter 전체 202개 통과, flutter analyze 문제 없음. 테스트가 끝난 뒤 변경은 문서·docstring만이다.
- Task 4: 실제 스모크·검토·전체 테스트 완료. 커밋·push·PR 기록은 HANDOFF 및 Git 이력에서 확인한다.
