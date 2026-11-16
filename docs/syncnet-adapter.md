# SyncNet 어댑터 — 조각 2/3

2026-11-15. `server/axes/alignment/syncnet.py`의 독립 어댑터다.
조각 3에서 Worker가 호출하는 `server/axes/alignment/__init__.py`를 실제 어댑터에 연결했다.
API 필드는 유지하며 completed/null의 의미는 README §9·§10·§15.3 승인 보완을 따른다. 모델 재현·공식 가중치 출처·라이선스는
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

## 조각 3: Worker 연결 (2026-11-15)

Gate 적합 구간만 실행하며 개발용 수동 구간 우회는 `insufficient_input/speaker_unconfirmed`로 미실행한다.
모든 구간에 유효 트랙이 있어야 completed이고 API 대표값은 null이다. 기존 explanations에 집계 보류를 적는다.
일부 또는 전체 트랙 없음은 insufficient_input/tracking_failed, 실행 오류는 error/inference_error다.
오류가 하나라도 있으면 error가 우선하며 성공한 다른 축 결과는 보존한다.
전체 작업의 남은 시간과 모델 600초 중 작은 제한을 적용한다. heartbeat는 lease 연장과 취소를 확인한다.
내부 트랙 지표는 호출 중 검증하고 API/로그에는 노출하지 않는다.

진단 도구는 `scripts/diagnose_syncnet_offset.py`다. 실제 영상 실행은 이번 조각에서 하지 않았다.
추후 승인된 발화 구간에 다음처럼 사용한다(지연 단위: 초, 양수는 오디오 지연).

```bash
python scripts/diagnose_syncnet_offset.py --registry <허가_레지스트리> --media-root <허가_폴더> --video-id <등록_ID> --start <시작_초> --end <끝_초> --delay 0.4
```

원본과 지연본의 같은 시간 구간에 대해 트랙별 지표를 JSON으로 출력한다. 자동 차이 집계·정답 판정은 하지 않는다.
A·B·E 발화 영상은 확보되어 있으나 실제 오프셋 실험과 해석, Gate 발화자/SyncNet 트랙 대응은 미검증이다.

## A.MOV 실제 오프셋 진단 (2026-11-15)

이번 진단은 A 하나에 한한다. 모델·Gate 임계값은 변경하지 않았다.
Git 밖 레지스트리 `data/research/syncnet-A-diagnostic/registry.json`에
`SyncNetTstA` → `A.MOV`를 등록했다(미디어 루트 `data/research/samples`).
기존 Gate 설정을 다시 실행한 적합 구간은 0.333–11.467, 12.800–16.620,
17.334–20.734, 21.201–24.601, 25.068–40.335초다.
가장 긴 마지막 적합 구간 안의 **26–34초(8초)**를 선택했다.
양끝에 최대 이동량 0.20초보다 큰 여유를 두며, 25fps에서 200프레임으로
원본 pipeline의 최소 트랙 기준 50프레임보다 길다. 품질 최적화로 고른 구간은 아니다.

원본 코드와 설치된 `PipelineConfig` 모두 분석 FPS=25를 확인했다(Python 3.11.18).
양수 이동은 `adelay`로 오디오 앞에 무음을 넣고, 음수는 `atrim`과 PTS 초기화로
앞당긴다. 0초는 `anull`로 같은 컨테이너/PCM 변환을 거치는 대조군이다.
원본 `offset = vshift - minidx`의 정의로 예상되는 변화는 **오디오 이동 프레임의 반대 부호**다.
원본 오프셋이 0이라고 가정하지 않고 원본 대비 차이를 비교한다.

기존 진단 도구에 음수·0초와 `--delays`를 추가했다. 원본은 한 번만 계산하고
각 이동 조건을 전용 venv CPU에서 순차 실행한다. 기존 단일 `--delay` 호출도 유지한다.

```bash
research/syncnet/.venv/bin/python scripts/diagnose_syncnet_offset.py \
  --registry data/research/syncnet-A-diagnostic/registry.json \
  --media-root data/research/samples --video-id SyncNetTstA \
  --start 26 --end 34 --delays -0.20 -0.08 0 0.08 0.20 \
  > data/research/syncnet-A-diagnostic/results.json
```

레지스트리 예시(파일과 미디어는 Git 제외):

```json
{"authorized_media":[{"youtube_video_id":"SyncNetTstA","local_path":"A.MOV","provenance":"registered_authorized_source"}]}
```

### 관찰 결과

모든 조건이 `completed`이며 유효 트랙은 각 1개(`track_index=0`)였다.
아래 수치는 소수점 여섯 자리로 표시한다. 전체 정밀도 JSON은 Git 밖 `results.json`에 있다.

| 조건(오디오 이동 초) | 성공 여부 | 트랙 | LSE-C | LSE-D | 오프셋(25fps 프레임) | 원본 대비 변화 | 기대 변화 |
|---|---|---:|---:|---:|---:|---:|---:|
| 원본 | 실행 성공 | 0 | 4.866789 | 9.063590 | +4 | +0 | +0 |
| -0.20 | 실행 성공 | 0 | 4.861182 | 9.267521 | +9 | +5 | +5 |
| -0.08 | 실행 성공 | 0 | 4.782339 | 9.132179 | +6 | +2 | +2 |
| +0.00 | 실행 성공 | 0 | 4.876541 | 9.063960 | +4 | +0 | +0 |
| +0.08 | 실행 성공 | 0 | 4.865307 | 9.031398 | +2 | -2 | -2 |
| +0.20 | 실행 성공 | 0 | 4.800707 | 9.037428 | -1 | -5 | -5 |

오디오를 앞당긴 조건에서는 오프셋이 증가하고, 늦춘 조건에서는 감소했다.
이번 구간의 원본 대비 변화는 기대 부호와 크기에 모두 일치한다. 원본은 +4프레임이며
원본이 반드시 0이어야 한다는 가정을 하지 않았다. 0초 변환 대조군도 +4프레임이다.
0초 대조군의 LSE-C/LSE-D는 원본과 완전히 같지는 않다. 오디오 변환 등의 영향을
분리한 실험은 하지 않았으며 이 차이를 품질이나 탐지 성능 차이로 해석하지 않는다.

**트랙 대응 근거와 한계:** 모든 조건에서 26–34초 영상의 25fps 디코딩 프레임 SHA-256이
동일했다(영상만 `fps=25` 후 FFmpeg hash muxer로 비교; `video_hashes.json`에 기록).
각 조건은 유효 트랙 하나를 반환했다. 따라서 같은 시각적 입력의 단일 트랙 비교라는 근거는 있으나,
현재 어댑터는 bounding box/트랙 프레임 목록/영속 인물 ID를 반환하지 않는다.
트랙의 정확한 프레임별 대응과 Gate 발화자 동일인 여부는 **미검증**이며,
`track_index=0` 자체를 동일인 증거로 사용하지 않는다.

**정리·검증:** 진단 및 프레임 해시 확인의 임시 폴더가 남지 않음을 확인했다.
원본 A.MOV와 Git 밖 레지스트리·Gate 결과·수치 JSON·프레임 해시만 보존했다.
관련 테스트 3 passed. 전체 `/opt/anaconda3/envs/trinity/bin/python -m pytest -q -rs`는
**509 passed, 1 skipped**, 기존 httpx 경고 1개. 건너뜀은 LightGBM 미설치다.
전체 테스트는 진단과 일부 시간 겹쳐 실행했으므로 처리 속도 측정으로 쓰지 않는다.

이번 결과는 **A의 한 구간에서 실제 실행과 인위적 오디오 이동 응답을 확인한 진단**이다.
원본의 실제 동기화 정답, 다른 영상·발화자·압축 조건, 진위 판정·탐지 정확도는 검증하지 않았다.
B·E의 SyncNet 진단은 실행하지 않았다. 임계값·모델·API 계약을 변경하지 않았다.
