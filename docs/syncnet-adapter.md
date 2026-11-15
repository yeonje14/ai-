# SyncNet 어댑터 — 조각 2/3

2026-11-15. `server/axes/alignment/syncnet.py`의 독립 어댑터다.
Worker가 호출하는 `server/axes/alignment/__init__.py`는 기존 stub을 유지한다.
HTTP API·앱·Fusion 계약은 변경하지 않았다. 모델 재현·공식 가중치 출처·라이선스는
[syncnet-spike.md](syncnet-spike.md)에 있다.

## 호출과 환경

```python
from pathlib import Path
from server.axes.alignment.syncnet import SyncNetConfig, run_syncnet

# 호출자가 AuthorizedMediaRegistry로 허가를 확인하고 서버 작업 폴더에 복사한 파일만 사용한다.
# gate는 기존 GateResult이며, 제외 구간은 넘기지 않는다.
result = run_syncnet(
    video=Path(job_dir) / 'media.mp4',
    segments=[(s.start_sec, s.end_sec) for s in gate.eligible_segments],
    work_dir=Path(job_dir),
    config=SyncNetConfig(timeout_sec=600),
    on_tick=heartbeat,  # False 또는 예외이면 중단한다.
    tick_sec=10,
)
```

- 서버 측 어댑터는 표준 라이브러리만 쓴다. trinity에 torch를 추가하지 않는다.
- 기본 실행기는 `research/syncnet/.venv/bin/python research/syncnet/infer_segments.py`다.
  인자 리스트에 작업 하위 폴더의 `--request`, `--output`만 전달한다.
- 요청에는 서버 작업 폴더 안 미디어 경로, Gate 적합 구간 목록, 운영자 설정 가중치 폴더가 있다.
  미디어 경로가 작업 폴더 밖이거나 심볼릭 링크로 벗어나면 실행하지 않는다.
  이것은 서버 내부 함수이며 사용자 파일 업로드 경로가 아니다.
- 전용 실행기는 manifest의 가중치 SHA-256을 먼저 확인하고 원본 `SyncNetPipeline(device='cpu')`를 생성한다.
  원본 코드·가중치·venv는 변경하거나 Git에 추가하지 않는다.
- FFmpeg 인자 리스트로 비디오·오디오에 동일한 시작 시각/길이를 적용해 구간을 순차 절단한다.
  영상은 소프트웨어 FFV1, 오디오는 PCM으로 저장하고 원본 pipeline으로 추론한다.
  이것은 동기화 정확도 검증을 마친 전처리라는 뜻이 아니다.

## 내부 JSON

이 결과는 HTTP API의 `axes.alignment`에 아직 연결하지 않은 내부 프로세스 결과다.
구간별 `segments`와 그 안의 `tracks`가 측정 지표를 보존한다.

| 위치 | 내용 |
|---|---|
| `status`, `reason_code` | 기존 축 상태와 실행 원인. 모든 구간이 성공해야 전체 `completed` |
| `segments[]` | 요청한 구간 순서의 `start_sec`, `end_sec`, `status`, `reason_code`, `tracks` |
| `segments[].tracks[]` | `track_index`, `lse_c`, `lse_d`, `offset_frames` |
| `offset_fps` | 원본 pipeline의 기준 프레임률 25. 원본 영상 FPS가 아님 |
| `included_in_fusion` | 항상 `false` |
| `raw_score` | 항상 `null`; 위조 확률이나 진위 판정 없음 |
| 전체/구간의 `lse_c`, `lse_d`, `offset_frames` | 집계하지 않으므로 `null`; 측정치는 해당 트랙에만 존재 |

트랙의 LSE-C는 원본 `confs[i]`, LSE-D는 `dists[i]`, 오프셋은 `offsets[i]`다.
최대 confidence와 최소 distance를 각각 고르면 서로 다른 트랙을 섞을 수 있으므로
원본의 영상 전체 요약은 사용하지 않는다. `track_index`는 해당 구간에서만 유효한 순번이며,
구간 사이의 동일 인물 ID나 Gate 발화자 트랙과의 일치 확인을 뜻하지 않는다.
오프셋의 부호는 원본 출력을 그대로 보존한다. 실제 발화 오프셋 실험은 조각 3에서 한다.

- 구간 없음: 프로세스를 띄우지 않고 `insufficient_input` / `no_segments`, 지표·`segments=null`.
- 트랙 없음: 해당 구간 `insufficient_input` / `tracking_failed`, 지표·`tracks=null`.
- 구간 추론 오류: 해당 구간 `error` / `inference_error`, 지표·`tracks=null`; 다음 구간은 계속 처리.
- 일부 구간 실패: 전체 상태는 `error`(또는 `unsupported_input`, `insufficient_input` 순서)로
  불완전함을 표시하되 성공한 구간의 트랙 지표를 보존한다. 새 `partial` 축 상태를 만들지 않는다.
- 프로세스 실패/깨진 JSON/다른 구간/잘못된 수치: `error` / `inference_error`, 모든 지표·`segments=null`.
- 실행 파일 없음/실행 불가: `error` / `model_unavailable`. timeout: `error` / `timeout`.
- 취소 콜백: `error` / `aborted`. 이 어댑터가 작업 상태를 `cancelled`로 변경하지는 않는다.
- 실패 결과에 지표가 섞여 와도 버린다. NaN·무한대·bool·누락·음수 거리·비정수 오프셋은 거부한다.

## 프로세스와 임시 파일

모델은 새 프로세스 그룹에서 실행한다. 타임아웃·취소·콜백 오류뿐 아니라
부모 프로세스가 먼저 종료된 경우에도 그룹 전체에 종료 신호를 보낸다.
직접 자식을 회수한 뒤 해당 호출의 고유 임시 폴더를 삭제한다.
구간 클립·오디오·얼굴 crop·원본 출력·요청/결과 JSON은 남기지 않고,
호출자가 소유한 작업 원본은 유지한다. 원본 stdout/stderr의 미디어 경로·지표는 저장/전달하지 않는다.
Worker 자체 강제 종료 복구는 이 조각의 독립 어댑터 테스트 범위가 아니며 조각 3 연결 때 확인한다.

## 검증과 남은 일

```bash
/opt/anaconda3/envs/trinity/bin/python -m pytest -q tests/test_syncnet_adapter.py tests/test_syncnet_runner.py
/opt/anaconda3/envs/trinity/bin/python -m pytest -q
research/syncnet/.venv/bin/python research/syncnet/infer_segments.py --help
```

대상 테스트: 49 passed. 실제 대역 프로세스로 성공·실패·타임아웃·취소·후손 종료·정리를 확인하고,
원본 pipeline 대역으로 같은 트랙의 지표 짝짓기·구간 실패 격리를 확인했다.
최종 전체 테스트: **496 passed, 2 skipped**, 기존 httpx 경고 1개. 건너뜀은 LightGBM 없음과
자동 Gate 테스트의 `samples/speaking/*.mp4` 샘플 없음이다. HANDOFF에도 기록했다.
trinity에서 torch 설치 없음·import 없음, 전용 Python의 실행기 CLI 진입을 확인했다.

**미검증:** 이 어댑터 경유 실제 모델 추론, 실제 발화 영상의 오프셋·정확도,
Gate 발화자와 SyncNet 트랙의 대응, Worker 연결 및 실제 취소, MPS 실행.
이번 조각에서는 실제 발화 영상 실험을 수행하지 않았다.
**확인 필요:** 가중치 상업 이용·재배포 조건과 S3FD의 파일별 라이선스 범위(조각 1에서 이어짐).

독립 리뷰의 중첩 JSON `RecursionError` 격리 문제를 회귀 테스트로 재현하고 수정했다.
매우 큰 정수의 `OverflowError`도 null 실패로 격리하도록 회귀 검증했다.
