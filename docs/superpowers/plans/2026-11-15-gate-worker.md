# Gate → Worker 연결 계획

> 실행: 이 세션에서 직접 구현하고 전체 변경을 독립 검토한다.

**승인:** 2026-11-15, Codex, GPT-6 Astra 제안, 사용자 승인.
**목표:** 허가 미디어의 Gate 적합 구간만 WaveRep에 전달한다.
**구조:** Gate는 기존 trinity Python의 자식 프로세스에서 실행한다. Worker는
heartbeat·취소·lease 상실·작업 제한시간을 관리한다. WaveRep 환경은 그대로 둔다.
**수용 기준:** 사용자 요청과 README §8·9·10·14.1. 새 상태·API 필드는 만들지 않는다.
품질·적합/제외 구간 설명은 기존 explanations, 분석량은 기존 coverage에 기록한다.

## 작업 1: Gate 실행과 Worker 연결

- [x] tests/test_gate_worker.py: 12개 원인 코드별 상태, 구간 전달, 호출 차단,
  실패·시간 제한·heartbeat·취소·lease 상실·파일 정리를 먼저 테스트한다.
- [x] 실패를 확인한 뒤 server/gate의 프로세스 어댑터와 실행 진입점을 추가한다.
  입력은 작업 폴더의 요청 JSON 경로이며 명령은 인자 리스트다.
- [x] server/jobs/worker.py와 server/config.py를 연결한다. 수동 구간만 우회한다.
- [x] coverage는 Gate의 원본/적합 길이와 성공한 WaveRep 구간을 구별한다.
  미실행/실패 analyzed 값은 null, 빈 분석 구간 목록은 []이다.
- [x] 기존 Worker/API 테스트의 Gate 미연결 기대값을 실제 동작으로 갱신한다.

## 작업 2: 앱의 원인별 안내

- [x] app/test/screens_test.dart: 접근 실패와 media_unreadable/gate_error/gate_timeout
  안내 차이를 테스트하고 실패를 확인한다.
- [x] app/lib/screens/result_screen.dart, app/lib/view_state.dart: API 변경 없이 문구 분리.
  unsupported/insufficient_quality 결과의 abstained를 해당 없음으로 오표시하지 않는다.
- [x] flutter test, flutter analyze.

## 작업 3: 실제 확인과 전달

- [x] pytest -q 전체, 실제 서버·Worker·기존 발화 없는 샘플로 Gate 차단 확인.
- [x] docs/HANDOFF.md, docs/gate.md, docs/waverep-adapter.md, README 갱신.
- [x] 독립 검토, 필요한 수정과 재검증.
- [ ] 커밋·push·PR. main에는 merge하지 않는다.

## 검토 집중 항목

- 깨진 Gate 출력·범위 밖 구간이 모델 실행으로 이어지지 않는가.
- 프로세스의 자식 FFmpeg까지 종료되고 lease 상실 후 결과를 쓰지 않는가.
- Gate 실패를 미디어 접근 권한 실패로 설명하지 않는가.
- Gate 적합 구간과 WaveRep 실패를 성공 분석량으로 세지 않는가.
- 수동 우회에서 Gate가 실행되거나 적합 coverage가 만들어지지 않는가.

## 진행 기록

- 최신 origin/main e324a8b에서 codex/connect-gate-worker 생성. 작업 폴더 변경 없음 확인.
- trinity에 Gate 패키지가 있고 torch가 없는 것을 확인. 패키지 설치 없음.

- Worker 상태 대응·호출 차단 테스트는 최초 15 실패/1 통과 후 16 통과.
- 앱 신규 실패 안내 테스트 3개 실패를 확인한 뒤 수정, 전체 198 통과·정적 검사 정상.
- 독립 검토 P2 1건: 반올림 후 빈 제외 구간으로 정상 Gate 결과를 잃음.
  회귀 테스트 실패→빈 조각 제거→통과. 최종 전체 437 passed, 2 skipped.
- 실제 서버/Worker 스모크: no_mouth_movement 차단, 모델 단계 없음, lease 갱신 13개 관찰,
  임시 작업 폴더 삭제. 말하는 영상 미검증.
- 결정: API 필드 추가 금지 조건에 따라 품질과 제외 구간은 기존 explanations에 기록한다.
  별도 구조화 품질 필드를 요구하는 후속 클라이언트는 향후 계약 검토가 필요하다.
