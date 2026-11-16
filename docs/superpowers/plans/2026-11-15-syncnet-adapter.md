# SyncNet 조각 2 어댑터 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 승인된 계획을 직접 구현하며 테스트 실패→통과를 기록한다.

**Goal:** Gate 적합 구간의 SyncNet 원시 지표를 별도 CPU 프로세스에서 얻는 독립 어댑터.
**Architecture:** `run_syncnet(video, segments, work_dir, config, on_tick, tick_sec)`가 작업 하위 임시 폴더의 요청·결과 JSON을 주고받는다. 전용 Python의 실행기가 구간을 순차 절단하고 원본 pipeline의 트랙별 출력을 같은 인덱스로 묶는다. Worker가 부르는 기존 alignment stub은 그대로 유지한다.
**Tech Stack:** Python 3.11 표준 라이브러리, 별도 SyncNet venv, FFmpeg, 고정 upstream.
**Spec:** 사용자가 승인한 조각 2 요청 및 README §5.3·§9·§10·§12.1. HTTP API 변경 없음.

## Global Constraints

- `feat/syncnet`, 조각 1 `ffab166`에서 진행. 기존 Gate 검증 문서 수정 보존.
- CPU, 인자 리스트, 프로세스 그룹 종료, 타임아웃, 예외 격리, 임시 미디어 정리.
- trinity에 torch 설치/import 없음. upstream·가중치·venv Git 제외.
- 내부 JSON만 추가: 구간의 `tracks`에 `track_index`, `lse_c`, `lse_d`, `offset_frames`.
  전체 지표를 임의 집계하지 않는다. 실패/미실행은 null, `included_in_fusion=false`.
- Worker 연결·실제 발화 오프셋 실험·진위 판정은 하지 않는다. commit/push만, PR 없음.

## Review Focus

- 종료 코드가 실패인데 유효 JSON이 남음 → 성공으로 읽지 않는다.
- NaN/bool/누락/요청과 다른 구간·트랙 → 거부하고 지표 null.
- 취소·타임아웃 및 부모 선종료 → 후손 프로세스까지 종료, 임시 폴더 제거.
- 두 트랙의 최대 confidence/최소 distance가 다름 → 원본 리스트의 동일 인덱스만 묶는다.
- 한 구간 실패·다음 구간 성공 → 실패 구간 null, 성공 구간 보존, 불완전함 표시.

### Task 1: 프로세스 어댑터와 내부 결과 형식

**Files:** `server/axes/alignment/syncnet.py`, `server/axes/alignment/report.py`, `tests/test_syncnet_adapter.py`.
**Interfaces:** `SyncNetConfig`, `run_syncnet(video: Path, segments: Sequence[Sequence[float]], work_dir: Path, config=SyncNetConfig(), on_tick=None, tick_sec=10.0) -> dict`. report는 구간 입력 검증·트랙 지표 검증·실패 결과 생성을 제공한다.

- [x] 가짜 Python 프로세스의 성공/실패/잘못된 결과, 빈 구간, 경로 검증, timeout/취소/후손 종료 테스트 작성 후 실패 확인.
- [x] 위 함수를 구현. 실패 결과의 지표와 raw_score는 null, fusion false. 고유 하위 폴더를 사용하여 오래된 결과를 읽지 않는다.
- [x] 대상 테스트 통과 확인.

### Task 2: 구간별 모델 실행기 및 문서

**Files:** `research/syncnet/infer_segments.py`, `tests/test_syncnet_runner.py`, `docs/syncnet-adapter.md`, `docs/HANDOFF.md`의 SyncNet 절.
**Interfaces:** Task 1의 내부 JSON 스키마를 생성. 요청에는 작업 내 video/segments 및 운영자 설정 가중치 경로가 있다. 모델 import는 실행기에만 있다.

- [x] upstream 대역으로 동일 트랙 짝짓기·빈 트랙·불완전/비정상 수치·구간 실패 격리 테스트 실패 확인.
- [x] 가중치 해시 확인 후 CPU pipeline 생성, FFmpeg 리스트 인자로 구간 비디오/오디오를 함께 절단. 구간별 임시 폴더 삭제. 결과를 JSON으로 기록.
- [x] 대상 테스트와 전체 `/opt/anaconda3/envs/trinity/bin/python -m pytest -q` 통과 확인. 환경에 torch가 추가되지 않았는지 확인.
- [x] 독립 리뷰, 필요한 수정 및 검증. HANDOFF 한 일·다음 조각·막힌 점 기록.
- 완료 절차: 이번 파일 및 HANDOFF의 해당 절만 커밋·push. 원격 일치 확인 후 중단.
