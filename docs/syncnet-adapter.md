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


## 성능 기준선 (2026-11-17, 개선 시도 없음)

> **측정이다. 개선하지 않았고 설정·upstream·래퍼를 바꾸지 않았다.** 본인 촬영 영상 A·B·E 세 개, 한 사람, 한 기기(Apple M3 16GB), CPU(`device='cpu'`) 기준이다.
> 시간은 `time.monotonic`이고, 실행 한 건마다 새 프로세스다. 진위·동기화 정확도에 대한 해석은 하지 않는다.

### 측정 방법

- 도구: `research/syncnet/profile_run.py`(전용 venv에서 실행)와 `scripts/profile_syncnet_baseline.py`(실행 계획·표). `infer_segments.py`와 **같은 요청·같은 호출 순서**로 돌리되, upstream 객체(파이프라인 인스턴스의 `_track`·`_crop`·`inference`, S3FD의 `detect_faces`, SyncNet 평가·임베딩, `cv2.imread`, `subprocess.run`, ffmpeg-python의 `run`)를 **실행 중에 타이머로 감싼다.** 인자와 반환값은 그대로 전달한다. upstream 파일(고정 SHA `ab819ba`)과 `infer_segments.py`는 수정하지 않았다.
- 시간은 **배타적**이다. 한 단계의 시간에서 그 안에서 불린 다른 단계의 시간을 뺀다. 그래서 단계 합계는 프로세스 안 전체 시간과 0.0초 안에서 맞는다(`wrapper_other_sec`). 이름을 못 붙인 외부 호출도 없었다(`unlabeled_subprocess` 빈 목록).
- 프로세스 시작·종료는 부르는 쪽이 따로 쟀다(표의 "시작·종료 오버헤드").
- 입력: 원본 A·B·E.MOV(HEVC 1920×1080, 30fps)와 **로버스트니스 실측의 원본 Gate 적합 구간**(A 5개 37.0초, B 9개 33.5초, E 6개 24.9초). E의 해상도 비교는 같은 CRF 28의 H.264 변환본(1080·720·480p, `docs/compression-emulator.md`)이다.
- 실행 18건: 원본 A·B·E × {standalone(venv 파이썬 직접), supervised(서버의 `start_process` supervisor 경유)} × 2회 = 12건, 타이머 없는 **실제 어댑터 `run_syncnet`** 영상당 1건 = 3건, E 해상도 변환본 3건(standalone 1회). 같은 영상의 모드를 번갈아 돌렸다. 실패 0건.
- 설정(upstream 기본값 그대로): `facedet_scale=0.25`, `min_track=50`, `min_face_size=100`, `frame_rate=25`, `batch_size=20`, `vshift=15`, `device=cpu`.
- 최대 메모리는 측정 프로세스가 기다린 후손 프로세스 하나의 최대 RSS(`ru_maxrss`)다. 합계가 아니다.

### 요약 (standalone 2회 평균, 프로세스 안 시간)

| | A | B | E |
|---|---|---|---|
| 처리한 프레임(25fps 변환 후) / 구간 길이 | 944 / 37.0초 | 872 / 33.5초 | 645 / 24.9초 |
| 전체 | 285.5초 | 274.6초 | 243.5초 |
| **S3FD 얼굴 검출** | **204.0초 (71%)** | **190.0초 (69%)** | **161.6초 (66%)** |
| S3FD 프레임당 | 0.216초 | 0.218초 | 0.251초 |
| 영상 준비(구간 절단·AVI 변환·JPEG 추출·오디오·JPEG 읽기) | 55.4초 (19%) | 65.6초 (24%) | 62.7초 (26%) |
| 크롭(JPEG 읽기·리사이즈·FFmpeg, 구간 전체) | 6.7초 | 5.0초 | 5.5초 |
| SyncNet 평가(임베딩 등) | 15.4초 (5%) | 9.9초 (4%) | 10.1초 (4%) |
| 구간 길이당 처리 시간 | 7.7배 | 8.2배 | 9.8배 |

- **병목은 S3FD다.** 모든 영상에서 전체의 66~71%이고, 임베딩(SyncNet 평가)은 4~5%다. 트래킹·MFCC·오프셋 거리 계산은 0.1초 미만이다.
- 두 번째로 큰 것은 영상 준비다. 구간 절단(HEVC 1080p 디코딩 + FFV1 인코딩)이 A 29.9초, B 41.4초, E 41.3초이고 AVI 변환이 12.5~15.3초, JPEG 추출이 5.3~6.2초다.
- 같은 설정의 두 회 차이는 1~13%였다(A standalone 294.3/277.3초, B supervised 263.3/299.0초).

### 모드 비교: standalone, supervisor 경유, 실제 어댑터

| 영상 | standalone(2회 평균) | supervisor 경유(2회 평균) | 실제 어댑터(타이머 없음, 1회) |
|---|---|---|---|
| A | 285.8초 | 278.0초 | 274.0초 |
| B | 274.9초 | 281.1초 | 312.8초 |
| E | 243.8초 | 250.6초 | 254.1초 |

- supervisor 경유와 standalone의 단계별 시간은 같은 영상에서 거의 같았다(예: A `s3fd_detect` 204.0 대 201.9초). 시작·종료 오버헤드는 0.2~0.3초다. **supervisor가 시간을 늘린 증거는 없다.**
- 타이머 없는 어댑터는 A·E에서 타이머 있는 실행과 비슷했고(274.0, 254.1초), B는 312.8초로 더 느렸다. 같은 설정의 반복 사이에서도 최대 13%(B supervised 263.3/299.0초) 벗어난 적이 있어 타이머가 시간을 늘리지 않았다고 단정하지는 못하고, 늘렸다는 증거도 없다(1회 측정).
- **미해결:** `docs/motionphys-adapter.md`의 Worker 안 A 실행에서 SyncNet 단계는 약 400초였다. 이번 어댑터 단독은 274~294초다. 차이의 원인은 확인하지 않았다. 이번 측정은 Worker 밖이다.
- 결과 일치: 15건 모두 로버스트니스 실측의 트랙 지표(오프셋·LSE-C·LSE-D)와 같았다(구간별 완전 일치, A 5/5·B 9/9·E 6/6 구간).

**단계별 시간 (초, standalone 2회 평균 / 괄호는 두 회의 차이)**

| 단계 | A | B | E |
|---|---|---|---|
| torch·SyncNet import (`import_sec`) | 1.4 (±0.0) | 1.4 (±0.0) | 1.5 (±0.0) |
| 가중치 해시 확인 (`weights_verify`) | 0.1 (±0.0) | 0.1 (±0.0) | 0.1 (±0.0) |
| 모델 로드 (`model_load`) | 0.1 (±0.0) | 0.1 (±0.0) | 0.1 (±0.0) |
| 구간 절단(FFmpeg, FFV1+PCM, 원본 해상도) (`cut_ffv1`) | 29.9 (±2.4) | 41.4 (±2.3) | 41.3 (±1.6) |
| 25fps MJPEG AVI 변환(원본 해상도) (`avi_convert`) | 15.3 (±0.1) | 14.1 (±0.6) | 12.5 (±0.3) |
| 입력 오디오 추출(FFmpeg) (`audio_extract`) | 0.3 (±0.0) | 0.4 (±0.0) | 0.4 (±0.0) |
| 프레임 JPEG 추출(원본 해상도) (`frames_extract`) | 6.2 (±0.2) | 6.1 (±0.2) | 5.3 (±0.0) |
| 오디오 16kHz 변환 (`audio_resample`) | 0.2 (±0.0) | 0.4 (±0.0) | 0.3 (±0.0) |
| S3FD 입력 JPEG 읽기 (`detect_imread`) | 3.5 (±0.2) | 3.2 (±0.2) | 3.0 (±0.1) |
| S3FD 얼굴 검출(0.25배 축소) (`s3fd_detect`) | 204.0 (±3.0) | 190.0 (±5.6) | 161.6 (±3.0) |
| 검출 루프의 나머지(색 변환 등) (`infer_loop_other`) | 0.8 (±0.0) | 0.8 (±0.0) | 0.6 (±0.0) |
| 장면 검출(AVI 디코딩) (`scene_detect`) | 1.6 (±0.1) | 1.6 (±0.1) | 1.2 (±0.0) |
| 트래킹 (`track`) | 0.0 (±0.0) | 0.0 (±0.0) | 0.0 (±0.0) |
| 크롭: JPEG 읽기 (`crop_imread`) | 3.2 (±0.2) | 2.2 (±0.1) | 2.4 (±0.1) |
| 크롭: 패딩·리사이즈·쓰기 (`crop_other`) | 2.6 (±0.2) | 1.9 (±0.1) | 2.1 (±0.1) |
| 크롭: 오디오 자르기(FFmpeg) (`crop_audio_slice`) | 0.2 (±0.1) | 0.2 (±0.0) | 0.2 (±0.0) |
| 크롭: 합치기(FFmpeg) (`crop_mux`) | 0.2 (±0.0) | 0.2 (±0.0) | 0.2 (±0.0) |
| 크롭 프레임 JPEG 추출(224px) (`crop_frames_extract`) | 0.3 (±0.0) | 0.3 (±0.0) | 0.3 (±0.0) |
| 크롭 오디오 추출 (`crop_audio_extract`) | 0.2 (±0.0) | 0.2 (±0.0) | 0.2 (±0.0) |
| SyncNet 입력 JPEG 읽기(224px) (`eval_imread`) | 0.1 (±0.0) | 0.1 (±0.0) | 0.1 (±0.0) |
| MFCC (`eval_mfcc`) | 0.0 (±0.0) | 0.0 (±0.0) | 0.0 (±0.0) |
| 영상 임베딩 (`eval_forward_lip`) | 11.1 (±1.4) | 7.3 (±0.3) | 7.5 (±0.1) |
| 오디오 임베딩 (`eval_forward_aud`) | 2.3 (±0.4) | 1.5 (±0.1) | 1.6 (±0.0) |
| 오프셋 탐색(거리 계산) (`eval_pdist`) | 0.0 (±0.0) | 0.0 (±0.0) | 0.0 (±0.0) |
| SyncNet 평가의 나머지(텐서 변환 등) (`eval_other`) | 1.8 (±0.1) | 1.1 (±0.0) | 1.0 (±0.0) |
| 임시 폴더 삭제 (`tmpdir_cleanup`) | 0.1 (±0.0) | 0.1 (±0.0) | 0.1 (±0.0) |
| 래퍼의 나머지(구간 반복·JSON) (`wrapper_other_sec`) | 0.0 (±0.0) | 0.0 (±0.0) | 0.0 (±0.0) |
| **프로세스 안 합계** | 285.5 | 274.6 | 243.5 |

**E의 해상도별 단계 시간 (초, standalone 1회)**

| 단계 | 원본 HEVC 1080p (2회 평균) | CRF28 H.264 1080p | CRF28 720p | CRF28 480p |
|---|---|---|---|---|
| torch·SyncNet import (`import_sec`) | 1.5 | 1.5 | 1.7 | 2.3 |
| 가중치 해시 확인 (`weights_verify`) | 0.1 | 0.1 | 0.1 | 0.1 |
| 모델 로드 (`model_load`) | 0.1 | 0.1 | 0.1 | 0.2 |
| 구간 절단(FFmpeg, FFV1+PCM, 원본 해상도) (`cut_ffv1`) | 41.3 | 11.0 | 5.7 | 4.2 |
| 25fps MJPEG AVI 변환(원본 해상도) (`avi_convert`) | 12.5 | 5.2 | 2.9 | 2.2 |
| 입력 오디오 추출(FFmpeg) (`audio_extract`) | 0.4 | 0.4 | 0.4 | 0.5 |
| 프레임 JPEG 추출(원본 해상도) (`frames_extract`) | 5.3 | 5.5 | 3.0 | 2.3 |
| 오디오 16kHz 변환 (`audio_resample`) | 0.3 | 0.3 | 0.3 | 0.4 |
| S3FD 입력 JPEG 읽기 (`detect_imread`) | 3.0 | 3.1 | 1.7 | 1.1 |
| S3FD 얼굴 검출(0.25배 축소) (`s3fd_detect`) | 161.6 | 167.9 | 87.7 | 57.9 |
| 검출 루프의 나머지(색 변환 등) (`infer_loop_other`) | 0.6 | 0.6 | 0.4 | 0.2 |
| 장면 검출(AVI 디코딩) (`scene_detect`) | 1.2 | 1.2 | 1.1 | 1.1 |
| 트래킹 (`track`) | 0.0 | 0.0 | 0.0 | 0.0 |
| 크롭: JPEG 읽기 (`crop_imread`) | 2.4 | 2.5 | 1.8 | 0.9 |
| 크롭: 패딩·리사이즈·쓰기 (`crop_other`) | 2.1 | 2.3 | 1.3 | 0.9 |
| 크롭: 오디오 자르기(FFmpeg) (`crop_audio_slice`) | 0.2 | 0.2 | 0.4 | 0.5 |
| 크롭: 합치기(FFmpeg) (`crop_mux`) | 0.2 | 0.2 | 0.3 | 0.4 |
| 크롭 프레임 JPEG 추출(224px) (`crop_frames_extract`) | 0.3 | 0.3 | 0.4 | 0.7 |
| 크롭 오디오 추출 (`crop_audio_extract`) | 0.2 | 0.2 | 0.3 | 0.4 |
| SyncNet 입력 JPEG 읽기(224px) (`eval_imread`) | 0.1 | 0.1 | 0.1 | 0.2 |
| MFCC (`eval_mfcc`) | 0.0 | 0.0 | 0.0 | 0.0 |
| 영상 임베딩 (`eval_forward_lip`) | 7.5 | 8.1 | 8.7 | 10.8 |
| 오디오 임베딩 (`eval_forward_aud`) | 1.6 | 1.7 | 1.7 | 2.1 |
| 오프셋 탐색(거리 계산) (`eval_pdist`) | 0.0 | 0.0 | 0.0 | 0.0 |
| SyncNet 평가의 나머지(텐서 변환 등) (`eval_other`) | 1.0 | 1.0 | 1.1 | 2.0 |
| 임시 폴더 삭제 (`tmpdir_cleanup`) | 0.1 | 0.1 | 0.1 | 0.1 |
| 래퍼의 나머지(구간 반복·JSON) (`wrapper_other_sec`) | 0.0 | 0.0 | 0.0 | 0.0 |
| **프로세스 안 합계** | 243.5 | 213.6 | 121.4 | 91.6 |
| 추출한 프레임 크기(첫 구간) | 1920×1080 | 1920×1080 | 1280×720 | 854×480 |

### 해상도 영향이 몰리는 곳 (E, CRF 28 H.264, standalone 1회)

| 단계 | 1080p | 720p | 480p | 1080→480 차이 |
|---|---|---|---|---|
| S3FD 얼굴 검출 | 167.9 | 87.7 | 57.9 | **−110.0 (90%)** |
| 구간 절단 | 11.0 | 5.7 | 4.2 | −6.8 |
| 프레임 JPEG 추출 | 5.5 | 3.0 | 2.3 | −3.2 |
| AVI 변환 | 5.2 | 2.9 | 2.2 | −3.0 |
| S3FD 입력 JPEG 읽기 | 3.1 | 1.7 | 1.1 | −2.0 |
| 크롭(JPEG 읽기·리사이즈) | 4.8 | 3.1 | 1.8 | −3.0 |
| 영상·오디오 임베딩 | 9.8 | 10.4 | 12.9 | **+3.1** |
| SyncNet 평가의 나머지 | 1.0 | 1.1 | 2.0 | +1.0 |
| **프로세스 안 합계** | **213.6** | **121.4** | **91.6** | **−122.0** |

- 같은 프레임 645개를 처리한다(세 변환본 모두 구간별 결과도 같다: 5개 completed, 1개 `insufficient_input`). 줄어든 122.0초 중 **S3FD가 110.0초(90%)**다. 입력 해상도가 S3FD의 0.25배 축소 입력 크기를 정하므로 검출 비용이 해상도에 따라간다(1080p 대비 720p는 0.52배, 480p는 0.34배의 시간. 화소 수는 0.44배, 0.20배).
- 해상도가 낮아지면 **늘어나는** 단계도 있다: 영상 임베딩 7.5→8.1→8.7→10.8초(원본 포함 열), 크롭 후 FFmpeg 호출들과 `eval_other`. 224×224 크롭은 입력이 같은 크기인데도 늘었다. 원인은 확인하지 않았다(1회 측정이라 잡음일 수 있다).
- **코덱도 크다:** 같은 1080p인데 원본(HEVC)의 구간 절단은 41.3초, CRF 28 H.264 변환본은 11.0초다. 구간 절단은 입력 디코딩을 포함하므로 HEVC 디코딩 비용이 큰 것으로 보이나 이 측정은 디코딩과 FFV1 인코딩을 나누지 않았다. 전체도 243.5초 대 213.6초다(원본 HEVC는 2회 평균, 변환본은 1회).
- 원본(HEVC)과 H.264 1080p의 S3FD 시간은 비슷하다(161.6, 167.9초).

**B: 구간별 검출·트랙·결과 (standalone 1회)**

| # | 구간(초) | 프레임 | 검출된 프레임 | 상자 합계 | 장면(프레임 범위) | 후보 트랙 길이(상위) | min_track(50) 초과 후보 | 트랙 | 결과 | 구간 시간(초) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0.84–5.33 | 116 | 116 | 116 | – | [114] | 1 | 1 | completed | 29.7 |
| 1 | 5.87–15.93 | 255 | 255 | 255 | – | [253] | 1 | 1 | completed | 65.4 |
| 2 | 16.38–17.85 | 41 | 41 | 41 | – | – | 0 | 0 | insufficient_input/tracking_failed | 10.1 |
| 3 | 18.33–19.73 | 39 | 39 | 39 | – | – | 0 | 0 | insufficient_input/tracking_failed | 9.6 |
| 4 | 20.20–26.85 | 170 | 170 | 170 | – | [168] | 1 | 1 | completed | 44.2 |
| 5 | 27.36–29.13 | 49 | 49 | 49 | – | – | 0 | 0 | insufficient_input/tracking_failed | 12.2 |
| 6 | 29.80–32.16 | 63 | 63 | 63 | – | [61] | 1 | 1 | completed | 16.6 |
| 7 | 33.87–35.31 | 40 | 40 | 40 | – | – | 0 | 0 | insufficient_input/tracking_failed | 10.0 |
| 8 | 35.73–39.53 | 99 | 99 | 99 | – | [97] | 1 | 1 | completed | 26.3 |

**E: 구간별 검출·트랙·결과 (standalone 1회)**

| # | 구간(초) | 프레임 | 검출된 프레임 | 상자 합계 | 장면(프레임 범위) | 후보 트랙 길이(상위) | min_track(50) 초과 후보 | 트랙 | 결과 | 구간 시간(초) |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0.87–5.10 | 109 | 109 | 109 | – | [107] | 1 | 1 | completed | 32.9 |
| 1 | 5.79–9.73 | 103 | 103 | 103 | – | [101] | 1 | 1 | completed | 30.9 |
| 2 | 22.11–29.94 | 199 | 199 | 199 | – | [197] | 1 | 1 | completed | 61.1 |
| 3 | 40.65–42.34 | 46 | 46 | 46 | – | – | 0 | 0 | insufficient_input/tracking_failed | 13.2 |
| 4 | 42.94–47.67 | 123 | 123 | 123 | – | [121] | 1 | 1 | completed | 37.9 |
| 5 | 48.20–50.64 | 65 | 65 | 65 | – | [63] | 1 | 1 | completed | 20.5 |

- A의 구간 5개는 모두 `completed`(프레임 89~385개, 트랙 1개씩)다.
- **`tracking_failed` 구간(B 4개, E 1개)은 전부 프레임이 49개 이하이고 `_track`이 호출되지 않았다**(후보 트랙 없음). 완료된 구간의 프레임은 63개 이상이다. 실패한 구간에서도 모든 프레임에서 S3FD가 얼굴을 찾았다(검출된 프레임 = 프레임). 장면 컷은 어느 구간에서도 없었다(`get_scene_list`가 빈 목록이라 upstream이 구간 전체를 한 장면으로 쓴다).
- 이 관찰은 upstream이 장면 길이가 `min_track`(50프레임, 25fps 기준 2초) 미만이면 트래킹을 건너뛰는 코드(`if e - s >= cfg.min_track`)와 맞는다. 실패한 구간에 쓴 시간은 B 41.9초(구간 시간 합), E 13.2초이고 그 시간은 S3FD 검출이 대부분이다. 이것이 이 코드가 실제로 쓰는 경로라는 것은 코드를 읽어 확인했지만, 해당 분기를 계측으로 직접 잡지는 않았다.
- 같은 구간이 로버스트니스 실측에서 모든 해상도·CRF에 대해 `tracking_failed`였던 것과 일치한다(`docs/HANDOFF.md`의 요약).

### 한계

- 영상 3개, 한 사람, 한 기기, CPU만. MPS·배치 크기·다른 설정은 측정하지 않았다.
- 실행 한 건당 1~2회다. 같은 설정의 반복 사이에서 1~13% 차이가 있었다. 해상도 비교는 영상 E 하나, 1회 측정이다.
- 단계 경계의 이름은 이 측정의 분류다. S3FD 시간에는 모델 추론과 그 앞뒤의 텐서 변환이 함께 들어 있다(나누지 않았다).
- 시간이 줄어든다고 SyncNet의 정확도가 같다는 뜻이 아니다. 어떤 개선도 시도하지 않았다.

### 재현

```bash
conda activate trinity
python scripts/profile_syncnet_baseline.py            # 18건. 이미 된 건은 건너뛴다
python scripts/profile_syncnet_baseline.py --report   # data/research/syncnet-perf/tables.md
```

결과(Git 제외): `data/research/syncnet-perf/runs/*.json`, 표 `tables.md`. 로버스트니스 실측의 Gate 구간(`data/research/robustness-selfvideo/`)이 필요하다.

## 개선 1차: 짧은 구간 건너뛰기와 MPS 선택지 (2026-11-17)

> 기준선(`fb3fe51`)과 같은 입력·같은 구간으로 비교했다. upstream 파일과 `min_track` 값은 바꾸지 않았다.
> **기본값은 그대로 CPU다.** MPS는 설정(`TRINITY_SYNCNET_DEVICE=mps`, `SyncNetConfig.device`)으로 켤 수 있는 선택지이고, 기본값 변경은 저장소 소유자가 이 측정을 보고 정한다.
> 구간 상태 규칙(모든 적합 구간에 유효 트랙)은 바꾸지 않았다. 아래 "(가) 규칙 설계안"은 제안이다.

### 바꾼 것

| 파일 | 내용 |
|---|---|
| `research/syncnet/infer_segments.py` | `ShortSegmentGuard`: 구간마다 upstream이 만든 프레임 수(추출된 JPEG 수와 25fps AVI 프레임 수 중 큰 값)를 세어 `cfg.min_track`보다 적으면 S3FD 대신 빈 검출을 돌려준다. upstream은 장면 길이가 `min_track` 이상일 때만 트래킹하고(`if e - s >= cfg.min_track`) 장면은 구간보다 길 수 없으므로 결과가 같다. 프레임 수를 셀 수 없으면 건너뛰지 않는다. `resolve_device`: `cpu`·`mps`만 받고 MPS를 쓸 수 없으면 CPU로 대체, `PYTORCH_ENABLE_MPS_FALLBACK=1` 설정. 결과 JSON에 `device_used`(내부 기록) |
| `server/axes/alignment/syncnet.py`, `__init__.py`, `server/config.py` | `SyncNetConfig.device`(기본 `cpu`), `Settings.syncnet_device`(`TRINITY_SYNCNET_DEVICE`, 기본 `cpu`). 그 밖의 값은 실행 전에 `invalid_request`. API 필드 변경 없음 |
| `training/features/extract.py` | 특징 버전에 SyncNet 장치를 넣었다(장치가 다르면 캐시·묶음이 서로 다른 것으로 취급된다) |

테스트: 가짜 파이프라인으로 건너뛰기 전후의 구간 결과가 **완전히 같음**(0·30·49·50·51·200프레임, 여러 구간 혼합, 얼굴 없음), 경계는 upstream 설정값을 읽음(`min_track=60`으로 바꿔도 따라감), 프레임 수를 못 세면 건너뛰지 않음, 장치 기본값·대체·거부.

### 측정 (A·B·E 원본, 원본 Gate 구간)

같은 날 저녁에 12건을 돌렸다: 건너뛰기+CPU 1회, 건너뛰기+MPS 2회, 건너뛰기+MPS의 실제 어댑터(타이머 없음) 1회. 실패 0건.

**결과 일치**

| 영상 | 건너뛰기+CPU 대 기준선 | 건너뛰기+MPS 대 기준선 | MPS 1회 대 2회, 어댑터 |
|---|---|---|---|
| A | 구간 상태·트랙·지표 **완전히 같음** | 상태·트랙 수·**오프셋 같음**. \|ΔLSE-C\| 평균 0.001(최대 0.006), \|ΔLSE-D\| 평균 0.002(최대 0.011) | 완전히 같음 |
| B | 완전히 같음 | 상태·트랙 수·**오프셋 같음**. \|ΔLSE-C\| 평균 0.034(최대 0.122), \|ΔLSE-D\| 평균 0.027(최대 0.100) | 완전히 같음 |
| E | 완전히 같음 | 상태·트랙 수·**오프셋 같음**. \|ΔLSE\| 최대 5e-6 | 완전히 같음 |

- 채택 기준(오프셋 동일, 트랙 수 동일)은 MPS도 넘었다. B의 LSE-C 최대 차이 0.122는 한 트랙(값 약 4.8)의 2.5%로, `docs/robustness-selfvideo.md`의 CRF 20 재압축이 만든 변화(평균 ±0.05~0.2)와 같은 크기다. MPS는 같은 입력에 같은 값을 냈다(2회와 어댑터가 완전히 같음).

**짧은 구간 건너뛰기의 효과 (CPU, 구간별 시간)**

| 영상 | 짧은 구간 | 기준선 | 건너뛰기 | S3FD 호출 수 |
|---|---|---|---|---|
| B | 4개(41·39·49·40프레임) | 41.9초 | 7.4초 | 872 → 703 |
| E | 1개(46프레임) | 13.2초 | 2.0초 | 645 → 599 |
| A | 없음 | – | – | 944 → 944 |

남는 시간은 구간 절단·AVI 변환·JPEG 추출이다(upstream `inference`가 검출 전에 한다).

**시간 (프로세스 안, 초)**

| 영상 | 기준선 CPU(오후, 2회 평균) | 건너뛰기+CPU(저녁, 1회) | 건너뛰기+MPS(저녁, 2회 평균) | MPS 어댑터 단독 실행(저녁) |
|---|---|---|---|---|
| A | 285.5 | **576.9** | 231.8 | 231.6 |
| B | 274.6 | 313.7 | 199.4 | 197.3 |
| E | 243.5 | 252.7 | 164.1 | 166.0 |

| 단계(초) | A 기준선 / 저녁 CPU / 저녁 MPS | B | E |
|---|---|---|---|
| S3FD 검출 | 204.0 / 405.2 / **118.2** | 190.0 / 196.2 / **74.1** | 161.6 / 162.6 / **68.7** |
| 구간 절단(FFmpeg) | 29.9 / 63.6 / 44.2 | 41.4 / 59.7 / 65.4 | 41.3 / 46.1 / 50.7 |
| AVI 변환(FFmpeg) | 15.3 / 31.5 / 21.4 | 14.1 / 18.9 / 19.7 | 12.5 / 13.5 / 14.2 |
| SyncNet 평가 합계(임베딩·텐서 변환) | 15.2 / 36.7 / 18.5 | 9.9 / 12.8 / 12.8 | 10.1 / 10.3 / 9.1 |

- **기기 상태가 측정 사이에 달라졌다.** 저녁의 CPU 실행(A 576.9초)은 오후 기준선의 2배였고, 장치와 무관한 FFmpeg 단계도 함께 느려졌다(A 구간 절단 29.9 → 63.6초). A에는 짧은 구간이 없어 건너뛰기가 아무것도 하지 않는다. 그래서 이 차이는 건너뛰기 때문이 아니다. 원인(발열·전원·다른 프로세스)은 기록하지 않아 **확인하지 못했다.**
- 그래서 MPS의 효과는 **S3FD 단계로 보는 것이 가장 깨끗하다**: 기준선 대비 −42%(A), −61%(B), −58%(E). 같은 저녁 CPU 대비 전체 시간은 A −60%, B −36%, E −35%, 오후 기준선 대비 −19%, −27%, −33%다.
- MPS는 비동기라서 임베딩 시간이 `eval_forward_*`가 아니라 결과를 CPU로 옮기는 `eval_other`에 잡힌다. 평가 단계는 합계로만 본다.
- 최대 RSS는 2.5~2.6 → 1.3~1.7 GiB였다. MPS 할당은 RSS에 다 잡히지 않으므로 메모리가 줄었다고 말하지 않는다.

### 속도 후보의 우선순위 (구현한 것 1개 외에는 제안)

| 순위 | 후보 | 근거(측정) | 성격 | 상태 |
|---|---|---|---|---|
| 1 | **MPS** | S3FD −42~−61%, 오프셋·트랙 수 동일 | 알고리즘 그대로, 장치만 | **선택지로 구현**, 기본 CPU |
| 2 | 짧은 구간 건너뛰기 | 결과 동일, B·E에서 구간당 약 8~11초 절약 | 결과 동일 | **구현, 기본 켜짐** |
| 3 | S3FD 검출 프레임 간격(예: 2프레임마다) | S3FD가 66~71%. upstream이 `num_failed_det=25`프레임까지 끊긴 검출을 보간하므로 트랙은 이어질 수 있다 | **근사**(상자 → 크롭 → LSE가 바뀐다) | 미구현. 선택지로만, 기준선 대비 표가 필요 |
| 4 | S3FD 입력 해상도 축소(`facedet_scale` < 0.25) | E에서 입력 480p는 S3FD 0.34배 시간 | **근사**(작은 얼굴을 놓칠 수 있다) | 미구현. 선택지로만 |
| 5 | 영상 한 번만 디코딩 | 구간 절단·AVI 변환·JPEG 추출이 19~26%(HEVC는 1080p 구간 절단만 41초, H.264는 11초) | 근사가 아니라 **구조 변경**(래퍼가 upstream `inference`의 입력 경로를 바꿔야 한다) | **보류**. 구조 변경이라 이번 범위에서 뺐다 |

### (가) 짧은 구간 규칙 설계안 — 제안, 승인 전 코드 변경 없음

현재(README §15.3 결정 2·8 보완, 2026-11-15, Codex·GPT-6 Astra 제안, 사용자 승인): **모든** Gate 적합 구간에 유효 트랙이 있어야 `alignment.status=completed`다. upstream이 2초(50프레임@25fps) 미만 구간에서 트랙을 만들지 않으므로, 자연스럽게 쉬어 가며 말하는 영상(B: 9구간 중 4개, E: 6구간 중 1개)은 압축과 무관하게 항상 `insufficient_input`/`tracking_failed`다.

| 안 | 동작 | API·상태 의미에 주는 영향 | 장점 | 단점 |
|---|---|---|---|---|
| **1. 짧은 구간 제외 + 하나 이상이면 completed** (권장) | `min_track` 프레임 미만 구간은 SyncNet에 넘기지 않고 설명에 남긴다. 남은 구간이 하나 이상이고 그 **모두**에 유효 트랙이 있으면 `completed`. 남은 구간이 없으면 `insufficient_input`/`segment_too_short` | 필드·상태 값 변경 없음. `completed`의 뜻이 "모든 적합 구간"에서 "SyncNet 최소 길이 이상인 모든 적합 구간(하나 이상)"으로 좁아진다. `segment_too_short`는 §10에 있는 원인 코드를 축에도 쓴다 | B·E가 `completed`가 된다(B 5구간 27.4초, E 5구간 23.2초). 짧은 구간의 절단·변환 비용(구간당 약 2초)도 없어진다. 제외 사실이 설명에 남는다 | 일부 발화를 검사하지 않고도 `completed`가 된다(설명으로만 알린다). 최소 길이가 upstream 설정에 묶인다 |
| 2. 인접 구간 병합 | 간격이 짧은 적합 구간을 하나로 이어 SyncNet에 넘긴다 | 필드 변경 없음. 그러나 **Gate가 제외한 사이 구간(입 움직임 없음·발화 없음)이 SyncNet 입력에 들어간다** | 실패 구간이 줄어든다 | "Gate 적합 구간만 실행한다"는 현재 규칙(조각 3)과 충돌한다. B의 간격은 0.45~0.7초인데 그 사이가 왜 제외됐는지와 무관하게 섞인다. 권장하지 않는다 |
| 3. 현행 유지 | 그대로 | 없음 | 가장 보수적이다 | 말하다 쉬는 보통의 영상에서 정합 축이 거의 항상 보류된다. 결합 후보 W+M+S를 서버가 쓸 수 있는 경우가 드물어진다 |

- 어느 안이든 upstream `min_track`은 바꾸지 않는다.
- **함께 맞춰야 할 것:** 학습 파이프라인(`training/features/extract.py`)은 SyncNet 특징을 축 상태와 무관하게 성공한 트랙들의 중앙값으로 만든다. 서버는 `alignment=completed`일 때만 W+M+S를 쓴다. 1안을 채택하면 학습 쪽도 "1안 기준의 completed일 때만 S 특징을 쓴다"로 맞추는 후속 작업이 필요하다(지금은 서버보다 학습이 S를 더 자주 쓴다).

**§15.3 문안 (1안, 승인 대기)**

> **결정 2·8 보완 — 2026-11-17, Claude 제안, 사용자 승인.**
> 2026-11-15 SyncNet 정합 결과 보완을 다음과 같이 고친다. SyncNet upstream은 `min_track`(현재 50프레임, 25fps 기준 2초)보다 짧은 장면에서 트랙을 만들지 않는다. 그래서 Gate 적합 구간 가운데 SyncNet이 만든 프레임 수가 `min_track` 미만인 구간은 SyncNet에 넣지 않고, 그 개수와 길이를 기존 `explanations`에 적는다. 남은 구간이 하나 이상이고 **남은 구간 모두**에서 유효 트랙 지표가 하나 이상 계산됐을 때 `alignment.status=completed`다. 남은 구간이 없으면 `insufficient_input` / `segment_too_short`이고 SyncNet을 실행하지 않는다. 남은 구간 중 하나라도 트랙이 없으면 `insufficient_input` / `tracking_failed`, 실행 오류는 `error` / `inference_error`로 기존과 같다. 대표값 집계 보류, `lse_c`·`lse_d`=`null`, `included_in_fusion=false`는 그대로다(검증된 묶음이 있을 때는 결정 5·8 보완을 따른다). API 필드와 상태 값은 추가하지 않는다. upstream의 `min_track`은 바꾸지 않는다. 학습 파이프라인의 SyncNet 특징도 이 기준의 `completed`일 때만 쓴다.

### Worker 안 약 400초 대 단독 274~294초 — 측정 방법 제안 (원인 추정 없음)

1. **같은 세션에서 번갈아 잰다.** 오늘 같은 기기에서 CPU 실행 시간이 2배까지 달라졌다(A 285 → 577초). 다른 시간대의 숫자끼리 견주지 않는다. Worker 실행과 단독 실행을 A·B·A·B 순서로 3회씩 돌린다.
2. **Worker 안에서도 단계별로 잰다.** Worker의 `alignment.build_config`를 측정 스크립트에서만 `profile_run.py`를 가리키게 바꿔(복구 테스트의 부트스트랩과 같은 방식, 제품 코드 변경 없음) Worker 안 SyncNet의 단계별 시간을 단독 실행과 같은 표로 얻는다.
3. **앞 단계의 영향을 분리한다.** Worker는 SyncNet 전에 Gate·WaveRep(MPS)·MotionPhys를 돌린다. (a) Worker 전체 경로, (b) 앞 단계를 가짜로 바꾼 Worker(SyncNet만 실제), (c) 단독 실행을 같은 세션에서 비교한다.
4. **기기 상태를 함께 기록한다.** 각 실행 전후의 `pmset -g therm`(열 제한), `pmset -g batt`(전원), `vm_stat`(메모리 압박), `uptime`(부하)을 결과 JSON에 넣는다.
5. 판단 규칙: (b)와 (c)가 같고 (a)만 느리면 앞 단계의 영향, 셋이 같고 다른 세션과만 다르면 기기 상태, (b)가 느리면 Worker 경로(heartbeat·supervisor 포함) 자체를 의심한다.

### 작업 제한 정책 — 권장안 (제안만, 기본값 변경 없음)

실측 근거(1회~2회, CPU 기준. 적합 구간 길이 1초당 처리 시간):

| 단계 | 관측 | 1초당 |
|---|---|---|
| Gate(영상 전체 길이 기준) | 5.6~21.2초(40~52초 영상) | 0.1~0.5초 |
| WaveRep(MPS, 초당 2장) | 21.7~33.4초 | 0.7~1.0초 |
| MotionPhys(A·B·C) | 단독 37초, Worker 안 61초(A) | 1.0~1.7초 |
| SyncNet CPU 단독(1080p 입력) | 194~389초(로버스트니스 원본·1080p 12건), 기준선 238~294초 | **7.5~10.5초** |
| SyncNet CPU, 느린 세션 | A 577초 | **15.6초** |
| SyncNet CPU, Worker 안 | A 약 400초 | 10.8초 |
| SyncNet MPS(건너뛰기) | 164~232초 | **6.0~6.6초** |
| Worker 전체(A, CPU SyncNet) | 506초 | 13.7초 |

- **(c) 고정 상향**은 영상 길이에 상한이 없으면 결국 다시 모자라고, 짧은 영상에 필요 이상으로 긴 제한을 준다.
- **(b) 단계별 조정**만으로는 작업 전체 제한(600초)이 먼저 걸린다. 지금도 SyncNet 단계 제한은 `min(600, 남은 시간)`이라 사실상 전체 제한이 정한다.
- **권장: (a) 적합 구간 길이 비례 + 상한.** SyncNet 시간이 적합 구간 길이에 거의 비례하고(1초당 7.5~10.5초, 느린 세션 15.6초, CPU), 길이는 Gate가 끝난 뒤에 알 수 있다.
  - 제안식: Gate 전에는 지금처럼 Gate 제한 120초를 쓴다. Gate가 끝나면 작업 전체 제한을 `min(1800, 180 + 20 × 적합 구간 초)`로 다시 정한다(CPU SyncNet 기준).
  - 이 식이면 E(24.9초) 678초, B(33.5초) 850초, A(37.0초) 920초다. A의 Worker 실측 506초와 느린 세션의 SyncNet 577초(여기에 앞 단계 약 100초)를 모두 덮는다. 1,800초 상한은 적합 구간 약 81초까지다.
  - MPS를 기본으로 바꾸면 계수를 1초당 약 10초로 낮출 수 있다(MPS 6.0~6.6초 + 앞 단계 2~3초 + 여유).
  - 설정값 추가(계수·상한)는 API 계약에 영향이 없다. 시간이 넘으면 지금처럼 `failed`/`timeout`이다. 적합 구간이 81초를 넘는 입력은 상한에 걸릴 수 있으므로 운영 범위로 함께 적어야 한다.
- 계수 20과 상한 1,800초는 영상 3개·1~2회 측정에서 고른 값이다. 다른 길이·기기에서 다시 재야 한다.

### 재현

```bash
conda activate trinity
python scripts/profile_syncnet_baseline.py            # 기준선 18건 + 이번 비교 12건(된 것은 건너뜀)
TRINITY_SYNCNET_DEVICE=mps python -m server.jobs.worker   # 서버에서 MPS를 켜는 방법(기본은 cpu)
```

## 결정 반영 (2026-11-17, 사용자 승인)

- **짧은 구간 규칙(1안) 구현.** 실행기는 upstream이 만든 프레임 수가 `min_track` 미만인 구간을 `insufficient_input` / `segment_too_short`로 표시한다(S3FD를 돌리지 않는다). `report.aggregate_status`가 그 구간을 빼고 축 상태를 정한다. 남은 구간이 없으면 `segment_too_short`. 제외한 구간은 `SYNCNET_SHORT_SEGMENTS_EXCLUDED` 설명 항목(개수·길이)으로 남는다. 다른 실패 원인은 짧은 구간으로 바뀌지 않는다(오류는 오류). 프레임을 셀 수 없으면(실행기가 셀 기회가 없으면) 기존처럼 `tracking_failed`로 둔다.
- **서버와 학습의 같은 기준.** 결합 입력(`server/axes/alignment/__init__.py`)과 학습 특징(`training/features/extract.py`)이 같은 `report.fusion_features`를 부른다. 축이 `completed`일 때만 LSE-C·LSE-D·|오프셋| 중앙값을 내고 그 밖에는 null이다. `tests/test_syncnet_rule_consistency.py`가 여섯 경우(전부 완료, 짧은 구간 제외, 전부 짧음, 짧음+트랙 없음, 짧음+오류, 트랙 없음)에서 서버 상태와 학습 특징의 유무·값이 같은지 확인한다.
- **기본 장치 MPS.** `SyncNetConfig.device`와 `Settings.syncnet_device`의 기본이 `mps`다. 못 쓰면 CPU로 대체, `cuda` 거부. 실행기의 `load_pipeline` 기본 인자는 여전히 `cpu`이고 어댑터가 항상 장치를 넘긴다. 특징 버전에 장치가 들어가 CPU 특징 캐시와 섞이지 않는다.
- **실제 확인(B, 1회):** 기본 설정(MPS, 새 규칙)의 실제 어댑터로 B 원본 Gate 구간 9개를 돌렸다. 축 `completed`, 짧은 구간 4개가 `segment_too_short`로 제외됐고, 남은 5구간의 오프셋은 기준선과 같다(+4, +4, +4, +4, +3). `device_used=mps`, 135.5초. 결합용 값(내부)은 LSE-C 중앙값 5.18, LSE-D 7.92, |오프셋| 4. 진위 판정이 아니다. E는 이번에 다시 돌리지 않았다(짧은 구간 1개, 같은 경로).
- **저녁 CPU 실행이 2배 느렸던 것(A 285 → 577초)은 원인 미확인으로 남긴다.** 장치와 무관한 FFmpeg 단계도 같이 느려졌다는 것까지만 측정했다.

### A의 Worker 종단 재측정 방법 (2026-11-18 실행, 결과는 아래 절)

목적은 새 규칙·MPS 기본값으로 Worker 안 전체 시간과 단계 시간을 다시 보는 것이다. 원인 추정은 하지 않는다.

1. 측정 직전에 기기 상태를 남긴다: `pmset -g therm`, `pmset -g batt`, `vm_stat`, `uptime`을 파일로 저장한다. 전원을 연결하고 다른 무거운 작업을 띄우지 않는다.
2. "Flutter 실제 서버 모드 A 예행"(`docs/HANDOFF.md`)과 같은 임시 레지스트리·DB·runtime을 Git 밖에 만들고 Worker만 띄운다(`python -m server.jobs.worker --drain`, 기본 설정 그대로. 작업 제한만 측정용으로 `TRINITY_JOB_TIMEOUT_SECONDS=1800`).
3. 테스트 클라이언트로 테스트 ID를 한 번 요청하고, 0.5초마다 DB의 `stage`와 lease 만료 시각을 기록한다(2026-11-16의 `real_a.py`와 같은 방식). Worker 로그의 단계 진입 시각으로 단계별 시간을 구한다.
4. 바로 이어서 같은 세션에서 `python scripts/profile_syncnet_baseline.py`의 A 단독 실행(MPS) 1건을 돌려 SyncNet 단계와 견준다. 측정 뒤에 1번의 상태를 다시 남긴다.
5. 기록할 것: 작업 상태 세 개, 축 상태, 단계별 시간, SyncNet `device_used`, 단독 실행과의 차이, 측정 전후 기기 상태. 끝나면 임시 레지스트리·DB·로그·runtime을 지운다.

## A의 Worker 종단 재측정 결과 (2026-11-18, 1회, 브랜치 `research/worker-remeasure`)

위 방법대로 1회 쟀다. 기준 커밋은 `6c6ac57`(main). 제품 코드 변경 없음. 원인 추정은 하지 않는다.

**조건**

- 기본 설정 그대로: SyncNet 기본 장치 MPS, 짧은 구간 규칙 적용, WaveRep MPS. 측정용으로 `TRINITY_JOB_TIMEOUT_SECONDS=1800`만 바꿨다.
- 임시 레지스트리(`TRINITYtest` → `data/research/samples/A.MOV`)·DB·runtime을 `data/runtime/worker-remeasure/`(Git 밖)에 만들고, `TestClient`로 한 번 요청한 뒤 `python -m server.jobs.worker --drain`만 띄웠다(API 서버는 띄우지 않았다). DB를 0.5초마다 읽어 `stage`와 lease 만료 시각을 기록했다(415회, 최대 간격 0.51초).
- **방법과 다른 점: 전원을 연결하지 못했다.** 측정 내내 배터리 전원이었다(100% → 96%). 다른 무거운 작업은 띄우지 않았다.

**작업 결과**

| 항목 | 값 |
|---|---|
| `job_status` / `analysis_status` / `verdict_status` | finished / completed / abstained |
| `overall_score` / `verdict_label` | null / null |
| 축 상태 | signal completed, physics completed, alignment completed(`included_in_fusion=false`, LSE 값 null) |
| 분석량 | 적합 구간 5개, 37.021초 / 영상 41.002초 |
| 시도 횟수, 실패 원인 | 1회, 없음 |
| lease 남은 시간(처리 중) | 20.0~30.0초(heartbeat 10초 간격대로) |

**단계별 시간 (Worker 로그의 단계 진입 시각 차이, 초)**

| 단계 | 시간 |
|---|---|
| validating + access_check + preprocessing(Gate) | 13.1 |
| waverep | 19.8 |
| motionphys | 36.7 |
| syncnet | **139.0** |
| fusion + finalizing | 0.002 |
| **전체**(DB `finished_at − started_at`) | **208.5** |

Worker 프로세스 트리 최대 RSS 1.55 GiB(`/usr/bin/time -l`, 후손 중 하나의 최대값).

**SyncNet `device_used`: 기록되지 않아 직접 확인하지 못했다.** 어댑터가 `device_used`를 내부 결과에만 두고 API 결과·Worker 로그·DB에 남기지 않으며, 작업 폴더는 끝나면 지워진다. 간접 근거만 있다: 요청 장치는 기본값 `mps`, SyncNet venv에서 `torch.backends.mps.is_available()=True`(torch 2.15.0), 단계 시간이 바로 뒤 MPS 단독 실행과 1% 차이. 그래서 MPS였을 것으로 보지만 **확인 필요**다. 다음에 Worker 안 장치를 확인하려면 측정 스크립트에서 어댑터 반환값을 남기는 부트스트랩이 필요하다(제품 코드 변경 없이).

**같은 세션의 A 단독 실행(MPS) 1건과 비교** — `profile_syncnet_baseline.py --one A original standalone 3 guard-mps`, Worker 종료 15초 뒤 시작.

| | Worker 안 SyncNet 단계 | 단독 실행(바깥 시간) | 단독 실행(프로세스 안) |
|---|---|---|---|
| 시간(초) | 139.0 | 137.7 | 137.4 |
| 차이 | – | **+1.3초(+0.9%)** | +1.6초 |

- 단독 실행 단계: S3FD 76.1, 구간 절단 20.6, AVI 변환 12.5, 평가 합계 9.8, 프레임 추출 5.6초. 5구간 모두 트랙 1개, 오프셋 +4. 최대 RSS 1.57 GiB.
- 이 세션에서는 **Worker 안과 단독 실행의 SyncNet 시간이 같았다.** 2026-11-16의 "Worker 안 약 400초 대 단독 274~294초"는 CPU였고 이번은 MPS라 같은 조건의 재현이 아니다. 그 차이의 원인은 여전히 확인하지 못했다.
- **세션 사이 차이는 다시 컸다.** 같은 MPS 단독 실행이 2026-11-17 저녁 229.96·234.3초, 이번 137.7초다(S3FD 117.7~118.7 → 76.1, 장치와 무관한 구간 절단 44.1~44.4 → 20.6). 다른 세션의 숫자끼리 견주지 않는다.

**기기 상태** (원본은 지웠다. 요약만 남긴다. `vm_stat` 페이지 16 KiB)

| 시점 | 시각(AEST) | `pmset -g therm` | 전원 | free / compressor 페이지 | swapouts | load average(1·5·15분) |
|---|---|---|---|---|---|---|
| 측정 전 | 17:38:20 | 열·성능 경고 기록 없음 | 배터리 100% | 16,978 / 264,484 | 1,424,685 | 2.50 3.23 3.23 |
| Worker 뒤·단독 전 | 17:42:09 | 경고 기록 없음 | 배터리 98% | 243,039 / 316,209 | 1,424,685 | 4.20 4.69 3.94 |
| 단독 뒤 | 17:44:27 | 경고 기록 없음 | 배터리 96% | 252,765 / 316,348 | 1,424,685 | 4.25 4.71 4.06 |

- 측정 중 새 swapout은 없었다. 가동 14일 22시간.

### 작업 제한 식 재계산 — 제안만 (기본값 600초 유지)

1초당(적합 구간 1초당) 시간:

| 근거 | 1초당 |
|---|---|
| 이번 Worker 전체(MPS) | 208.5 / 37.0 = **5.6초** |
| 이번 SyncNet 단계(MPS) | 139.0 / 37.0 = 3.8초 |
| 이번 SyncNet 앞 단계(Gate·WaveRep·MotionPhys) | 69.5 / 37.0 = 1.9초 |
| MPS SyncNet 관측 최대(2026-11-17 저녁, A·B·E) | 6.0~6.6초 |
| 앞 단계 이전 관측 상한(위 표의 Gate·WaveRep·MotionPhys 합) | 약 3.2초 |
| CPU SyncNet(MPS를 못 써서 CPU로 대체될 때) | 7.5~10.5초, 느린 세션 15.6초 |

- **제안(MPS 기준): `min(1800, 180 + 12 × 적합 구간 초)`.** 계수 12 = MPS SyncNet 관측 최대 6.6 + 앞 단계 이전 상한 3.2(합 9.8) + 약 20% 여유. 상수 180초는 모델 로드·프로세스 시작 같은 고정 비용과 짧은 입력의 여유다.
  - E(24.9초) 479초, B(33.5초) 582초, A(37.0초) 624초. 이번 A 실측 208.5초의 3.0배다. 2026-11-17 저녁 MPS 단독 A 231.8초에 앞 단계 이전 상한(약 118초)을 더한 약 350초도 덮는다.
  - 상한 1,800초는 적합 구간 135초까지다(이전 식은 81초).
- **덮지 못하는 것:** (1) MPS를 못 써서 CPU로 대체되면 계수 20이 필요하다(Worker는 Gate 뒤 제한을 정할 때 실제 장치를 아직 모른다). CPU 대체까지 덮으려면 지금의 20을 유지하는 것이 안전하다. (2) 같은 기기에서 세션에 따라 시간이 약 1.7~2배 달라졌다. MPS 최대값 자체가 2배가 되면 A에서 약 725초로 624초를 넘는다.
- 그래서 선택지는 둘이다: **12**(MPS가 쓰일 때 운영 범위를 넓힘, CPU 대체·느린 세션은 `failed`/`timeout` 가능) 또는 **20 유지**(CPU 대체까지 덮음). 계수를 장치별로 나누려면 Worker가 Gate 뒤에 SyncNet 장치를 미리 알아야 하므로 설계 변경이다(README §15.3 기록 필요).
- 근거는 Worker 종단 MPS 1회(A)와 단독 측정 몇 건이다. 다른 길이·기기·전원 상태에서 다시 재야 한다.
