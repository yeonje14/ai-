# SyncNet 어댑터 — 조각 2/3

2026-11-15. `server/axes/alignment/syncnet.py`의 독립 어댑터다.
조각 3에서 Worker가 호출하는 `server/axes/alignment/__init__.py`를 실제 어댑터에 연결했다.
API 필드는 유지하며 completed/null의 의미는 docs/DESIGN.md §9·§10·§15.3 승인 보완을 따른다. 모델 재현·공식 가중치 출처·라이선스는
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
(이후 확인: 어댑터 경유 실제 추론·Worker 연결 2026-11-16, MPS 실행 2026-11-17, 실제 Worker에서 SyncNet 실행 중 취소·Worker SIGKILL 2026-11-19 — 맨 아래 "실제 Worker 수명주기 확인" 절.)
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
- **미해결:** `docs/motionphys-adapter.md`의 Worker 안 A 실행에서 SyncNet 단계는 약 400초였다. 이번 어댑터 단독은 274~294초다. 차이의 원인은 확인하지 않았다. 이번 측정은 Worker 밖이다. → 2026-11-18~19 같은 세션 교차 측정 결과는 아래 "Worker 안 대 단독 — 같은 세션 교차 측정" 절(Worker 경로 자체는 원인이 아니고, 앞 단계가 데운 기기의 열 제한이 이번 세션 차이를 설명했다).
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

현재(docs/DESIGN.md §15.3 결정 2·8 보완, 2026-11-15, Codex·GPT-6 Astra 제안, 사용자 승인): **모든** Gate 적합 구간에 유효 트랙이 있어야 `alignment.status=completed`다. upstream이 2초(50프레임@25fps) 미만 구간에서 트랙을 만들지 않으므로, 자연스럽게 쉬어 가며 말하는 영상(B: 9구간 중 4개, E: 6구간 중 1개)은 압축과 무관하게 항상 `insufficient_input`/`tracking_failed`다.

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

> 2026-11-18~19에 이 방법의 (a)(b)(c)와 진단 조건 (d)(e)로 쟀다. 결과는 맨 아래 "Worker 안 대 단독 — 같은 세션 교차 측정" 절.

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

**SyncNet `device_used`: 기록되지 않아 직접 확인하지 못했다.** 어댑터가 `device_used`를 내부 결과에만 두고 API 결과·Worker 로그·DB에 남기지 않으며, 작업 폴더는 끝나면 지워진다. 간접 근거만 있다: 요청 장치는 기본값 `mps`, SyncNet venv에서 `torch.backends.mps.is_available()=True`(torch 2.15.0), 단계 시간이 바로 뒤 MPS 단독 실행과 1% 차이. 그래서 MPS였을 것으로 보지만 **확인 필요**다. 다음에 Worker 안 장치를 확인하려면 측정 스크립트에서 어댑터 반환값을 남기는 부트스트랩이 필요하다(제품 코드 변경 없이). (2026-11-19부터 Worker 로그와 jobs의 내부 기록 `run_info_json`에 남는다 — 맨 아래 "Worker 장치·열 상태 기록" 절.)

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
- 그래서 선택지는 둘이다: **12**(MPS가 쓰일 때 운영 범위를 넓힘, CPU 대체·느린 세션은 `failed`/`timeout` 가능) 또는 **20 유지**(CPU 대체까지 덮음). 계수를 장치별로 나누려면 Worker가 Gate 뒤에 SyncNet 장치를 미리 알아야 하므로 설계 변경이다(docs/DESIGN.md §15.3 기록 필요).
- 근거는 Worker 종단 MPS 1회(A)와 단독 측정 몇 건이다. 다른 길이·기기·전원 상태에서 다시 재야 한다.

## 작업 제한 정책 결정 (2026-11-18, 사용자 승인, 구현)

**결정:** `min(1800, 180 + 20 × 적합 구간 초)`. 위 "재계산" 절의 두 선택지 가운데 계수 20을 골랐다. docs/DESIGN.md §15.3 "결정 9·11 보완(작업 제한) — 2026-11-18".

**계수 20을 쓰는 이유**

1. **MPS 실패 시 CPU 대체를 덮는다.** SyncNet은 MPS를 쓸 수 없으면 CPU로 대체한다. Worker는 Gate 뒤에 제한을 정할 때 SyncNet이 실제로 어느 장치에서 돌지 아직 모른다. CPU SyncNet은 적합 구간 1초당 7.5~10.5초였다. MPS 기준 계수 12로는 앞 단계(1초당 최대 약 3.2초)를 더하면 모자랄 수 있다.
2. **기기 2배 지연을 덮는다.** 같은 기기·같은 설정에서 세션에 따라 시간이 약 1.7~2배 달라졌다(CPU A 285 → 577초, MPS A 230~234 → 137.7초). 느린 세션의 CPU SyncNet은 1초당 15.6초였다. 계수 20이면 A(37.0초)의 제한이 920초로, 느린 세션의 CPU SyncNet 577초에 앞 단계 약 100초를 더해도 들어간다. 계수 12(624초)는 MPS 최대값이 2배가 되는 경우(약 725초)도 덮지 못한다.
3. **제한은 상한일 뿐이다.** 작업은 끝나는 즉시 끝난다. 제한을 길게 잡아도 정상 작업의 대기 시간은 늘지 않는다(2026-11-18 MPS Worker 실측 A 208.5초, 제한 920초). 긴 제한의 비용은 정말로 멈춘 작업이 대기열을 더 오래 잡는 것뿐이고, 그것도 lease·취소·재시작 복구는 그대로 동작한다.

**구현**

- `Settings.job_timeout_after_gate(eligible_sec)`가 식을 계산한다. 설정: `job_timeout_base_seconds`(180), `job_timeout_per_eligible_second`(20), `job_timeout_max_seconds`(1800). 환경 변수 `TRINITY_JOB_TIMEOUT_BASE_SECONDS`, `TRINITY_JOB_TIMEOUT_PER_ELIGIBLE_SECOND`, `TRINITY_JOB_TIMEOUT_MAX_SECONDS`. 기본항·상한은 유한한 양수, 계수는 0 이상의 유한한 수만 받는다.
- Worker(`server/jobs/worker.py` `process`)는 작업 시작 시각을 잡아 두고, Gate가 끝난 직후 `deadline = 시작 + 새 제한`으로 바꾼다. 적합 구간 초는 Gate 적합 구간 길이의 합이다. 이후 단계 진입·heartbeat·축의 남은 시간이 모두 새 deadline을 따른다.
- 기존 `job_timeout_seconds`(기본 600초)는 Gate 전 단계와 적합 구간 길이를 모를 때의 값으로 남는다: Gate 실행 중, Gate가 길이를 정하지 못한 경우(`gate_error`, `gate_timeout`, `media_unreadable`), 개발 전용 Gate 우회.
- 적합 구간이 0초(Gate가 구간 없이 끝남, 예: `no_speech_detected`)여도 Gate는 성공했으므로 180초로 다시 정해진다. 바로 보류 결과로 마무리하므로 실제로 쓰이는 시간은 거의 없다. Gate 단계 제한(기본 120초)이 180초보다 짧아 이 경우 마무리에서 timeout이 날 일은 없다. Gate 제한을 180초 넘게 늘리면 그럴 수 있다.
- 초과하면 지금처럼 `failed` / `timeout`, 결과 없음. API 필드·상태 값 변경 없음.
- 예: E(24.9초) 678초, B(33.5초) 850초, A(37.0초) 920초. 짧은 입력은 600초보다 짧아진다(적합 구간 21초 미만). 상한 1,800초는 적합 구간 81초부터 걸린다.

**테스트** `tests/test_job_timeout_policy.py`(24개): 식(0초 180, 짧음 2.5초 230, A 37초 920, 상한과 같음 81초, 상한 초과 120초 → 1800, 음수는 0), 환경 변수, 잘못된 설정 거부, Worker에서 Gate 뒤 축에 넘긴 남은 시간(짧음·길음·상한 초과), 새 제한 초과 시 `failed`/`timeout`, 적합 구간 0초는 기존 제한이 지났어도 새 제한으로 보류 결과까지 끝남, Gate 실패 세 원인은 기존 제한 유지(기존 제한이 지나면 timeout), Gate 우회는 기존 600초. Worker의 제한 재설정 줄을 빼면 Worker 테스트 5개가 실패하는 것을 확인했다.

**축별 단계 제한:** WaveRep·MotionPhys는 300초 그대로다. SyncNet은 아래 보완으로 바뀌었다.

## SyncNet 단계 제한 보완 (2026-11-18, 사용자 승인, 구현)

**규칙:** SyncNet 단계 제한 = `min(60 + 16 × 적합 구간 초, 남은 작업 시간 − 마무리 여유)`. 기존 `min(600, 남은 시간)`을 대신한다. docs/DESIGN.md §15.3 "결정 9·11 보완(작업 제한)"의 보완 문단.

- 계수 16은 가장 느린 CPU 실측(A 느린 세션, 적합 구간 1초당 15.6초)을 덮는다. 기본항 60초는 모델 로드·프로세스 시작 같은 고정 비용이다.
- 목적: SyncNet이 느려져도 작업 전체가 `failed` / `timeout`이 되지 않고, SyncNet 축만 `error` / `timeout`으로 끝나 WaveRep·MotionPhys 결과를 남긴다. 그래서 SyncNet 단계 제한은 작업 deadline보다 마무리 여유만큼 먼저 끝나야 한다.
- 남은 시간이 마무리 여유보다 짧으면 SyncNet을 시작하지 않고 축만 `error` / `timeout`이다.
- 작업 제한 식(`180 + 20x`)이 SyncNet 길이 규칙 + 여유(`70 + 16x`)보다 항상 110 + 4x초 크다. 그래서 앞 단계(Gate·WaveRep·MotionPhys)가 그 이상 걸리지 않으면 SyncNet은 길이 규칙만큼 쓸 수 있다. 예: A(37.0초) 652초(이전 고정값 600초보다 길다), B(33.5초) 596초, E(24.9초) 458초.

**마무리 여유 10초의 근거 (실측, 2026-11-18)**

SyncNet 단계 제한이 끝난 뒤 작업 deadline을 마지막으로 확인하는 곳은 `enter("finalizing")`이다. 그 사이에 걸리는 시간은 (1) SyncNet 프로세스 정리와 어댑터 반환, (2) `enter("fusion")`의 DB 기록, (3) fusion 계산·결과 조립이다.

| 항목 | 근거 | 값 |
|---|---|---|
| (1) 단계 제한 시각 → 어댑터 반환 | 실제 A로 SyncNet을 일부러 timeout시킨 4건(아래 표). 프로세스 그룹 SIGKILL·임시 폴더 삭제 포함, 작업 폴더에 남은 파일 없음 | 0.031~0.068초 |
| (2) fusion 단계 기록 | SQLite 연결의 잠금 대기 상한(`server/jobs/queue.py`, `timeout=5`). 평소에는 ms 단위 | 최대 5초 |
| (3) fusion·finalizing | 2026-11-18 A Worker 실측 로그(syncnet 끝 → finalizing 진입) | 0.002초 |
| 합 | | 약 5.1초 → **10초**(약 2배 여유) |

(2026-11-19 "Worker 장치·열 상태 기록"이 이 구간에 축 끝 thermalState 프로브(제한 1초)와 실행 기록 저장(DB 잠금 대기 1초)을 더한다. 합 약 7.1초로 여전히 10초 안이다.)

| 장치 | 단계 제한 | 결과 | 걸린 시간 | 초과분 |
|---|---|---|---|---|
| MPS | 20초 | error / timeout | 20.043초 | 0.043초 |
| MPS | 60초 | error / timeout | 60.037초 | 0.037초 |
| MPS | 120초 | error / timeout | 120.068초 | 0.068초 |
| CPU | 120초 | error / timeout | 120.031초 | 0.031초 |
| MPS | 180초 | completed(제한 전에 끝남) | 138.968초 | – |

- 측정: 어댑터 `run_syncnet`을 직접 불렀다(Worker 없이). 입력은 A 원본과 로버스트니스 실측의 Gate 적합 구간 5개. heartbeat 대역은 10초마다 True.
- 기기 상태: 측정 전후 열·성능 경고 기록 없음, 새 swapout 없음. **배터리 전원**(71% → 63%).
- 처음 측정 중 MPS 120초·CPU 120초 두 건은 0.1초 만에 `inference_error`로 끝났다. 측정 도중 `server/config.py`에 자리표시자를 넣어 SyncNet 실행기(서버의 `report`를 import한다)가 import에 실패했기 때문이다. 자리표시자를 고친 뒤 다시 잰 값만 표에 넣었다.
- SQLite 잠금 대기 5초는 측정값이 아니라 설정 상한이다. 다른 프로세스(API 서버)가 DB를 오래 잡지 않는 한 실제로는 ms 단위다.

**구현:** `server/axes/alignment/__init__.py`의 `stage_timeout(ctx)`. 설정 `syncnet_timeout_base_seconds`(60), `syncnet_timeout_per_eligible_second`(16), `job_finalize_margin_seconds`(10), 환경 변수 `TRINITY_SYNCNET_TIMEOUT_BASE_SECONDS`, `TRINITY_SYNCNET_TIMEOUT_PER_ELIGIBLE_SECOND`, `TRINITY_JOB_FINALIZE_MARGIN_SECONDS`.

**테스트** `tests/test_syncnet_stage_timeout.py`(15개): 길이 규칙(짧음 2.5초 → 100초, 길음 37초 → 652초, 150초 → 2,460초), 남은 시간 − 여유가 더 짧을 때, 기본 작업 제한 식이 SyncNet 규칙 + 여유보다 항상 큼, 환경 변수, 잘못된 설정 거부, 남은 시간이 여유보다 짧으면 SyncNet 미실행. Worker에서는 실제 별도 프로세스로 도는 느린 가짜 SyncNet으로 (a) 남은 시간 부족, (b) 길이 규칙, (c) 진입 때 시간 없음의 세 경우 모두 작업 `finished`, SyncNet 축만 `error` / `timeout`, WaveRep·MotionPhys 결과 유지, `analysis_status=partial`을 확인했다. 여유를 빼면 이 중 5개가 실패한다(작업이 `failed`가 됨).

~~**미검증:** 실제 Worker에서 SyncNet 단계 제한에 걸리는 종단 실행은 하지 않았다(가짜 SyncNet 프로세스로만 확인).~~ → 2026-11-19 실제 A로 확인했다(길이 규칙·남은 시간 두 경로). 아래 "실제 Worker 수명주기 확인" 절.

## Worker 안 대 단독 — 같은 세션 교차 측정 (2026-11-18~19, 브랜치 `research/syncnet-worker-gap`)

위 "Worker 안 약 400초 대 단독 274~294초 — 측정 방법 제안"의 (a)(b)(c)를 같은 세션에서 번갈아 각 3회 이상 쟀고, 원인을 가르려고 진단 조건 (d)(e)를 더했다. **제품 코드·설정 기본값은 바꾸지 않았다.** 기준 커밋은 main `5aa7acf`.

**조건 (모두 A 원본, SyncNet CPU, 같은 Gate 적합 구간 5개 37.021초)**

| 조건 | 내용 |
|---|---|
| a | Worker 전체 경로: 별도 Worker 프로세스, 임시 레지스트리·DB, 실제 Gate → WaveRep(MPS) → MotionPhys → SyncNet |
| b | Worker, 앞 단계 가짜: Gate는 로버스트니스 실측의 A 적합 구간을 바로 돌려주고 WaveRep·MotionPhys는 실행하지 않는다. SyncNet만 실제 |
| c | 단독: Worker·supervisor 없이 SyncNet 실행기만 `subprocess.run`으로 |
| d (진단) | Worker 없이 측정 프로세스가 실제 Gate·WaveRep·MotionPhys 어댑터를 차례로 부른 직후 c와 같은 단독 SyncNet |
| e (진단) | 모델·미디어·GPU 없이 8개 논리 코어 모두에 순수 계산 프로세스를 68초(a·d의 앞 단계 길이) 돌린 직후 c와 같은 단독 SyncNet |

- SyncNet 장치는 원래 차이가 관측된 조건인 **CPU**(`TRINITY_SYNCNET_DEVICE=cpu`, 측정용 환경 변수). 지금 기본값은 MPS이고, 2026-11-18의 MPS 1회 비교에서는 Worker 안과 단독의 차이가 +0.9%였다(위 "A의 Worker 종단 재측정 결과").
- 네 조건 모두 SyncNet 자식은 같은 프로파일 실행기(`research/syncnet/profile_adapter_shim.py` → `profile_run.py`)다. Worker 조건은 측정 프로세스 안에서만 `alignment.build_config`의 실행기 경로를 바꿨다(`tests/test_job_lifecycle.py` 부트스트랩과 같은 방식). 측정용으로 작업·SyncNet 제한만 환경 변수로 1,800초로 늘렸다.
- 순서는 라틴 방격(a1 b1 c1 d1 / b2 c2 d2 a2 / c3 d3 a3 b3), 뒤이어 e1 c4 e2 c5 e3. 실행마다 최소 180초 쉬고, thermalState가 0이고 쉬는 때 CPU 탐침(한 스레드 고정 계산)이 세션 최솟값의 5% 안에 들 때까지 더 쉬었다(최대 600초). 17회 모두 이 조건을 채운 뒤 시작했다.
- 기록: 실행 전후 `pmset -g batt`·`pmset -g therm`·`ProcessInfo.thermalState`·`vm_stat`·부하·충전기 정보, 실행 중 5초마다 시스템 전력(`AppleSmartBattery`의 SystemLoad, root 없이 읽힘)·thermalState·다른 프로세스 CPU(실행 파일 이름만). 결과 JSON은 Git 밖 `data/research/syncnet-worker-gap/runs/`.
- 기기: Apple M3 MacBook Air(`Mac15,12`, **팬 없음**) 16GB, macOS 27.0.1. **측정 내내 20W USB-C 충전기 연결·충전 중**(배터리 34% → 73%, `pmset -g batt` "AC Power; charging"). 저전력 모드 꺼짐. `pmset -g therm`은 측정 내내 "No thermal warning level has been recorded"였다(이 기기에서는 열 제한을 보여 주지 않는다). CPU 주파수는 root 권한(`powermetrics`)이 없어 **직접 재지 못했다.**

**결과 (17회, 실패 0, 측정 시각 2026-11-18 23:07 ~ 11-19 01:31 AEST)**

| 조건 | 회수 | SyncNet 시간 평균(최소–최대, 초) | S3FD 평균 | 구간 절단(FFmpeg) 평균 | SyncNet 시작 때 thermalState | 첫 구간 S3FD 프레임당(초) |
|---|---|---|---|---|---|---|
| a Worker 전체 | 3 | **281.1** (255.2–302.3) | 203.0 | 27.0 | 1(a1은 시작 19초 뒤 1) | 0.166~0.216 |
| b Worker, 앞 단계 가짜 | 3 | **241.0** (230.7–249.7) | 175.1 | 21.1 | 0 (66~116초 뒤 1) | 0.165 |
| c 단독 | 5 | **253.3** (243.7–276.4) | 184.3 | 22.6 | 0 (66~86초 뒤 1) | 0.162~0.175 |
| d Worker 밖, 실제 앞 단계 직후 | 3 | **289.0** (278.1–305.3) | 208.3 | 27.8 | 1 | 0.185~0.224 |
| e 순수 계산 열 68초 직후 | 3 | **276.2** (268.4–280.7) | 198.2 | 27.4 | 0~1(시작 4초 안에 1) | 0.169~0.192 |

실행별(SyncNet 초): a 255.2 / 302.3 / 285.8, b 242.4 / 249.7 / 230.7, c 243.7 / 246.2 / 276.4 / 248.5 / 251.6, d 278.1 / 305.3 / 283.5, e 268.4 / 280.7 / 279.5. Worker 안 SyncNet 시간은 어댑터 호출 시간, 단독은 자식 프로세스 바깥 시간이다(프로세스 안 시간과 0.3~0.4초 차이).

- **17회 모두 결과가 같다**: 5구간 모두 트랙 1개, 오프셋 +4, LSE-C·LSE-D가 실행 사이에 완전히 같았다. a의 작업은 3회 모두 finished / completed / abstained, 세 축 completed, `device_used=cpu`. 측정 뒤 남은 모델 프로세스·작업 폴더 없음.
- a의 앞 단계: Gate 12.1~12.5, WaveRep 18.1~18.7, MotionPhys 36.9~38.2초(2026-11-16 Worker 실측의 18·26·61초보다 짧다). d의 앞 단계도 같은 크기(Gate 12.2~12.6, WaveRep 18.3~18.7, MotionPhys 37.2~38.3초).
- **mediaanalysisd(macOS 사진·미디어 분석)가 60~80% CPU를 쓴 실행이 3회 있었다(a2, c3, d2).** 셋 다 자기 조건에서 가장 느렸다: a2 302.3(a의 나머지 평균 270.5, +31.8초), c3 276.4(c의 나머지 평균 247.5, +28.9초), d2 305.3(d의 나머지 평균 280.8, +24.5초). 나머지 14회의 다른 프로세스 CPU는 평균 81~108%(ecosystemd·mysqld·coreaudiod 등)로 비슷했다.
- 그 3회를 빼면: **차게 시작한 b·c 7회 평균 244.7초(230.7~251.6), 앞에 부하가 있었던 a·d·e 7회 평균 275.9초(255.2~285.8), 차이 +31.2초(+12.8%).**
- 메모리 압박: 17회 모두 실행 중 새 swapout 0. 최대 RSS 2.6~2.7GiB.

**판단 (위 측정 방법 절의 판단 규칙)**

- b ≈ c이고(오히려 b가 약간 빠르다) a만이 아니라 d·e도 느리다. 규칙대로면 "**앞 단계의 영향**"이고, Worker 경로 자체는 원인이 아니다.
- e는 모델·미디어·GPU 없이 CPU 열만 만들었는데 a·d와 같은 만큼 느려졌다. 그래서 앞 단계의 영향은 **기기 온도(열 제한)**로 설명된다. 근거: 앞 부하가 있었던 9회 모두 SyncNet 시작 19초 안에(8회는 4초 안에) thermalState 1이었고 차게 시작한 8회는 시작 뒤 66~116초 동안 0이었다. S3FD 프레임당 시간이 thermalState 0에서 약 0.163~0.17초, 1에서 0.22~0.25초다. 차게 시작한 실행도 thermalState가 1이 된 마지막 구간에서 0.22~0.23초로 올라간다. torch와 무관한 FFmpeg 구간 절단도 약 25% 같이 느려져 기기 전체가 느려진 것이다. 팬 없는 기기라 약 1분 전체 코어 부하로 열 상태가 바뀐다.

**가설 정리**

| 가설 | 판정 | 근거 |
|---|---|---|
| Worker 경로 자체(supervisor·새 세션, heartbeat의 SQLite 기록, Worker 프로세스 환경, 작업 폴더 복사) | **배제(이번 세션)** | b 241.0 ≈ c 253.3, b ≤ c |
| 앞 단계가 Worker에 남긴 것(남은 자식 프로세스, Worker가 쥔 자원) | **배제** | Worker 없는 d(289.0)도 a(281.1)만큼 느림. 모든 실행 뒤 남은 모델 프로세스 없음 |
| 앞 단계의 열이 아닌 부작용(파일 캐시, 메모리 압박, WaveRep MPS가 남긴 GPU 상태) | **배제** | 모델·미디어·GPU 없는 e(276.2)가 같은 만큼 느림. swapout 0 |
| 프로파일러 차이 | **해당 없음** | 모든 조건이 같은 프로파일 실행기를 쓴다(조건 사이 차이를 만들 수 없다) |
| **앞 단계가 데운 기기의 열 제한** | **이번 세션의 a > b·c를 설명** | 위 판단. CPU 주파수를 직접 재지 못해 thermalState·S3FD 속도·FFmpeg 동반 지연·순수 열 재현으로 본 것이다 |
| **다른 프로세스 부하**(mediaanalysisd 등) | **기여 확인** | 해당 3회가 각 조건에서 +24.5~31.8초(+9~12%) |
| **세션 단위 기기 상태**(주변·본체 온도, 충전 상태, 그때 떠 있던 앱) | **남음(확인 불가)** | 아래 |

**원래 차이(Worker 약 400초 대 단독 274~294초)에 대해 — 확정하지 못했다**

- 이번에 확인한 두 요인은 앞 단계의 열(+12.8%)과 다른 프로세스 부하(약 +9~12%)다. 둘을 곱해도 274~294초의 약 1.26배(약 345~370초)라 400초에 30~55초 모자란다.
- 2026-11-16 Worker 실측은 다른 날·다른 세션이고(단독 274~294초는 11-17 오후), 당시 "다른 프로세스가 떠 있는 상태"였으며 기기 상태를 기록하지 않았다. 그 실행의 앞 단계도 지금보다 1.5배 길었다(105초 대 68초, MotionPhys 61 대 37초). 그 세션 자체가 더 뜨겁거나 바빴을 가능성이 있지만 **확인할 수 없다**. 같은 기기의 CPU 단독 실행도 세션에 따라 2배까지 달랐다(11-17 오후 285 → 저녁 577초, 원인 미확인).
- 그래서 원래 차이는 "**Worker 경로 때문이 아니다(배제)**, 앞 단계 열과 다른 프로세스 부하가 일부를 설명한다(확인), 나머지는 기록되지 않은 세션 상태(남은 가설)"로 둔다. 2026-11-16의 MotionPhys 단독 37.1초 대 Worker 안 약 61초도 같은 기전(Gate·WaveRep 뒤라 기기가 데워짐)일 수 있으나 이번에는 따로 재지 않았다(미확인). 이번 세션의 Worker 안 MotionPhys는 36.9~38.2초였다.

**제안 (코드 변경 없음, 제안만)**

1. **Worker 코드 변경은 필요 없다.** 차이를 만든 것은 Worker 경로가 아니라 기기 상태다.
2. 작업 제한(`180 + 20 ×`)·SyncNet 단계 제한(`60 + 16 ×`)은 이 영향을 덮는다. 이번 CPU 최댓값 305.3초 = 적합 구간 1초당 8.2초로 SyncNet 계수 16 안이다. 바꿀 필요 없다.
3. (관측 개선, 결정 필요) 서버 Worker 로그에 SyncNet `device_used`와 작업 시작 때 thermalState를 남기면 느린 작업의 원인을 사후에 가를 수 있다. 로그 항목 추가라 API는 그대로지만 로그 규칙(§12)에 맞는지 확인이 필요하다. 이번에는 구현하지 않았다. → 2026-11-19 구현: 세 실행기의 `device_used`와 실행 시작·끝 thermalState를 Worker 로그와 jobs의 내부 기록에 남긴다(맨 아래 "Worker 장치·열 상태 기록" 절).
4. (측정 규칙) 이 기기에서 시간을 비교할 때는 같은 세션에서 번갈아 재고, 실행 전 열 상태를 맞추고(쿨다운 + thermalState), 다른 프로세스 CPU를 함께 기록한다. 앞 단계가 있는 측정과 없는 측정을 바로 견주지 않는다.

**재현**

```bash
conda activate trinity
python scripts/measure_syncnet_worker_gap.py --plan a1,b1,c1,d1,b2,c2,d2,a2,c3,d3,a3,b3 --cooldown 180 --cooldown-max 600
python scripts/measure_syncnet_worker_gap.py --plan e1,c4,e2,c5,e3 --cooldown 180 --cooldown-max 600
python scripts/measure_syncnet_worker_gap.py --report      # 실행별·조건별 표
python scripts/measure_syncnet_worker_gap.py --plan a1,b1,c1,d1,e1 --dry   # 하네스 점검(SyncNet 없이)
```

테스트: `tests/test_measure_syncnet_worker_gap.py`(7개: 계획 형식, 전력 값 부호, 프로세스 트리, 표본 시간 창, 쉬기 조건, 실행기 점검 모드의 결과 형식). 측정 뒤 `pytest -q` **822 passed, 1 skipped**(건너뜀은 LightGBM 없음, 기존과 같음).

## 실제 Worker 수명주기 확인: SyncNet 단계 제한·Worker SIGKILL·MPS 실행 중 취소 (2026-11-19, 브랜치 `research/real-timeout-verify`)

**조건.** 실제 API 서버(uvicorn)와 별도 Worker 프로세스(`python -m server.jobs.worker`)를 띄우고, 임시 레지스트리(테스트 ID → 허가 샘플 A)·DB·runtime(Git 밖, 끝나면 삭제)을 썼다. 요청은 API `POST /api/v1/analyses`, 취소는 `DELETE`(If-Match). **제품 코드·기본값은 바꾸지 않았고** 시나리오마다 아래 환경 변수만 바꿨다. 그 밖은 기본값이다: SyncNet·WaveRep MPS, heartbeat 10초, lease 30초, 재시도 상한 2. 기기는 같은 MacBook Air M3, 20W 충전기 연결·충전 중(배터리 75~78%), 열 경고 기록 없음. 기준 커밋 main `5aa7acf`. 스크립트 `scripts/verify_real_worker_lifecycle.py`, 결과 JSON은 Git 밖 `data/research/real-lifecycle/`.

### (가) SyncNet 단계 제한에 실제로 걸리게 하기 — 두 경로, 각 1회

| | 길이 규칙 경로 | 남은 시간 경로 |
|---|---|---|
| 측정용 환경 변수 | `TRINITY_SYNCNET_TIMEOUT_BASE_SECONDS=30`, `TRINITY_SYNCNET_TIMEOUT_PER_ELIGIBLE_SECOND=0` → SyncNet 제한 30초 | `TRINITY_JOB_TIMEOUT_BASE_SECONDS=150`, `TRINITY_JOB_TIMEOUT_PER_ELIGIBLE_SECOND=0` → Gate 뒤 작업 제한 150초, SyncNet 제한 = 남은 작업 시간 − 마무리 여유 10초 |
| Worker 로그의 작업 제한 | 920초(기본 식) | 150초 |
| 앞 단계 Gate·WaveRep·MotionPhys | 12.8 · 17.9 · 44.6초 | 21.2 · 29.0 · 52.1초(합 102.3초) |
| **SyncNet 단계** | **30.05초** | **37.71초**(150 − 102.3 − 10 ≈ 37.7) |
| **작업** | **finished**, 105.3초 | **finished**, 140.05초(작업 제한 150초보다 약 10초 먼저 끝남) |
| 상태 | `analysis_status=partial`, `verdict_status=abstained`, `overall_score`·`verdict_label` null | 같음 |
| 축 | signal completed, physics completed, **alignment error / timeout**(`lse_c`·`lse_d` null, `included_in_fusion=false`) | 같음 |
| 정리 | 관찰한 작업 프로세스 11개(Gate, WaveRep·MotionPhys·SyncNet 실행기, supervisor, FFmpeg) 모두 종료, 작업 폴더 삭제(runtime에 `.worker.lock`만), Worker 종료 코드 0 | 같음 |

- 다른 축의 결과와 설명(`MOTIONPHYS_FEATURES_ONLY`, Gate 설명 항목)이 남았다. SyncNet 축이 completed가 아니므로 `SYNCNET_UNAGGREGATED` 설명은 없다. coverage의 분석량(37.021초)은 signal 기준 그대로다.
- 남은 시간 경로가 "SyncNet이 느려져도 작업은 finished로 끝나고 SyncNet 축만 `error`/`timeout`"이라는 보완 규칙의 실제 확인이다. 이 실행은 앞 단계가 평소(약 68초)보다 느렸는데(앞 시나리오 직후라 기기가 데워진 상태, 위 "Worker 안 대 단독" 절과 같은 현상으로 보인다) SyncNet 제한이 그만큼 줄어 작업 제한 안에서 끝났다.

### (나) SyncNet(MPS) 실행 중 Worker SIGKILL — 2회

| | 1회 | 2회 |
|---|---|---|
| kill 시점 | SyncNet 실행기 확인 뒤 20초(단계 `syncnet`, 시도 1) | 같음 |
| MPS 근거(실행기 1초 스택 표본의 Metal/MPS 프레임 수) | 539 | 344 |
| kill 때 작업 프로세스 | supervisor 1, SyncNet 실행기 1 | 같음 |
| Worker 종료 | SIGKILL(-9) | 같음 |
| **자식 모두 종료까지** | **0.074초** | **0.075초** |
| kill 직후 DB | `processing` / `syncnet` / 시도 1 / lease 소유자는 죽은 Worker | 같음 |
| kill 직후 작업 폴더 | 남아 있음(복구 때 정리) | 같음 |
| kill 때 lease 남은 시간 | 기록 못 함(아래) | 28.1초 |
| **새 Worker 기동 → 재선점** | **28.2초** | **28.2초**(lease 만료 시각과 일치) |
| 2차 시도 | finished / completed / abstained, 세 축 completed, 시도 2, SyncNet 170.0초 | 같음, SyncNet 170.5초 |
| 끝난 뒤 | 작업 폴더 없음, 2차 시도에서 본 프로세스 모두 종료, 새 Worker는 SIGTERM으로 정상 종료(0) | 같음 |

- supervisor가 Worker 생존 파이프의 EOF를 보고 SyncNet 프로세스 그룹을 바로 끝냈다. 새 Worker는 lease가 만료될 때까지 기다렸다가 이전 작업 폴더를 지우고 작업을 다시 대기열에 넣은 뒤 2차로 끝까지 처리했다. 재시도 상한(2)에는 걸리지 않았다.
- 1회의 "kill 때 lease 남은 시간"은 측정 스크립트가 작업 종료 뒤에 계산하는 실수로 쓸 수 없는 값(-257.2초)이 나와, 고친 뒤 2회를 다시 쟀다. 다른 항목은 1회에도 유효하다.

### (다) MPS 실행 중 API 취소 — 각 1회

| | SyncNet(MPS) 실행 중 | WaveRep(MPS) 실행 중 |
|---|---|---|
| 측정용 환경 변수 | 없음(heartbeat 10초) | `TRINITY_HEARTBEAT_INTERVAL_SECONDS=2`(WaveRep이 약 20초라 취소가 반영되기 전에 끝나지 않게) |
| 취소 시점 | SyncNet 실행기 확인 뒤 20초 | WaveRep 실행기 확인 뒤 4초 |
| MPS 근거(Metal/MPS 프레임 수) | 431 | 148 |
| `DELETE` 응답 | 202, `processing` | 202, `processing` |
| **cancelled까지** | **8.24초**(heartbeat 10초 안) | **1.88초**(heartbeat 2초 안) |
| 취소 때 단계 / 완료 단계 | `syncnet` / validating~motionphys | `waverep` / validating~preprocessing(WaveRep은 끝나지 않음) |
| 자식(supervisor·모델 실행기) | cancelled 확인 때 모두 종료 | 같음. 축 로그 `waverep error reason=aborted` |
| 작업 폴더 | 삭제 | 삭제 |
| Worker(`--drain`) 종료 코드 | 0 | 0 |

**미검증으로 남는 것**

- MotionPhys·Gate·WaveRep 실행 중의 Worker SIGKILL(이번에는 SyncNet만). MotionPhys 실행 중 취소.
- MPS를 쓸 수 없어 CPU로 대체되는 경우의 같은 경로, B·E 영상, 반복 안정성(SIGKILL 2회, 나머지 1회).
- "MPS 근거"는 스택 표본의 Metal/MPS 프레임 수다. 실행기의 `device_used`는 Worker 결과·로그에 남지 않아 직접 보지 못했다(2026-11-18과 같은 한계). 2026-11-19부터는 기록된다(맨 아래 절).

**재현**

```bash
conda activate trinity
python scripts/verify_real_worker_lifecycle.py            # 다섯 시나리오(된 것은 건너뜀)
python scripts/verify_real_worker_lifecycle.py --report   # 요약
```

## Worker 장치·열 상태 기록 (2026-11-19, 브랜치 `feat/worker-device-log`)

위 "Worker 안 대 단독" 절의 제안 3을 구현했다. 사용자 결정: 결과 JSON에는 API 계약을 바꾸지 않는 내부 자리가 없어(축 모델은 Pydantic 기본이라 추가 키가 `dump`에서 버려지고, DB `result_json`은 API 응답 본문 그대로다) **jobs 테이블의 내부 열**에 남긴다(D1=B). 재선점 때 지우지 않고 **시도 번호별로 쌓는다.** API 필드·상태 값 변경 없음. 계획 `docs/superpowers/plans/2026-11-19-worker-device-log.md`.

**무엇을 남기나.** WaveRep·MotionPhys·SyncNet 실행기마다 실제로 쓴 장치(`device_used`)와 실행 시작·끝의 macOS `ProcessInfo.thermalState`.

- 장치: WaveRep·SyncNet은 실행기가 보고하는 실제 장치(MPS를 못 쓰면 `cpu`). MotionPhys는 실행기가 `cpu`를 보고한다. 근거는 `research/motionphys/faces.py`의 MediaPipe `BaseOptions`가 delegate를 지정하지 않고, mediapipe 1.2.3 `base_options.py`가 delegate가 없으면 CPU를 쓰는 것이다. 광학 흐름(OpenCV)·LightGBM도 CPU다. delegate를 지정하면 `tests/test_axis_device_used.py`가 실패한다. 값은 `cpu`·`mps`·`gpu`만 받고 그 밖은 `null`이다(로그·기록에 원문을 남기지 않는다). 실행기를 부르지 않은 축(구간 없음, 개발용 수동 구간의 SyncNet 등)은 `null`.
- 열 상태: `nominal`·`fair`·`serious`·`critical`(ProcessInfo 0~3). Worker 프로세스 안에서 Objective-C 런타임을 부르지 않고, 같은 Python의 짧은 격리 프로세스(`python -I -c`, 표준 라이브러리 ctypes)에서 읽는다(`server/jobs/device_state.py`). 잘못돼도 Worker가 죽지 않게 하려는 것이다. 한 번에 약 20~90ms, 작업당 6회. macOS가 아니거나 실패·1초 초과면 `null`(로그에는 `unknown`). 작업에는 영향이 없다.
- 마무리 여유: 축이 받는 남은 시간은 시작 프로브 **뒤에** 잰다. SyncNet이 끝난 뒤 `enter("fusion")` 전에 끼는 끝 프로브(제한 1초)와 기록 저장(DB 잠금 대기 1초)을 더해도, 위 "SyncNet 단계 제한 보완"의 근거 약 5.1초 + 2초 = 약 7.1초로 마무리 여유 10초 안이다(`tests/test_worker_device_log.py::test_axis_time_budget_is_taken_after_the_start_probe`, `tests/test_run_info_record.py::test_save_gives_up_on_a_locked_db_quickly`).

**Worker 로그** (logger `trinity.worker`, INFO, 축이 끝날 때마다 한 줄. 취소·timeout으로 멈춘 축도 남는다):

```text
job <analysis_id> axis <signal|physics|alignment> device=<cpu|mps|gpu|unknown> thermal_start=<nominal|fair|serious|critical|unknown> thermal_end=<…>
```

**내부 기록** `jobs.run_info_json`(API·`_to_job`은 읽지 않는다. 작업 삭제 때 행과 함께 지워진다):

```json
{"attempts": [{"attempt": 1, "axes": {"signal": {"device_used": "mps", "thermal_state_start": "fair", "thermal_state_end": "fair"},
                                      "physics": {...}, "alignment": {...}}},
              {"attempt": 2, "axes": {...}}]}
```

- 축이 끝날 때마다 그 시도의 항목만 갱신한다(`JobQueue.save_run_info`, lease를 가진 Worker가 처리 중일 때만 쓴다). 다른 시도의 기록은 그대로다. 기존 값을 읽을 수 없으면 새 목록으로 시작한다. 기록에 실패해도 작업은 계속된다(경고 로그 한 줄, 내용 없음).
- 이 열이 생기기 전의 DB는 Worker·API가 시작할 때(`init_schema`) 열만 더한다. 기존 행은 그대로다.
- 읽는 법(연구·운영용): `sqlite3 data/runtime/trinity.sqlite3 "SELECT analysis_id, attempts, run_info_json FROM jobs WHERE analysis_id = '<id>'"`.

**실제 확인 (2026-11-19, A, 실제 API 서버 + 별도 Worker, 임시 레지스트리·DB, 기본 설정 외 바꾼 것만 표시)**

| 설정 | 작업 | 로그·기록의 장치(signal / physics / alignment) | thermalState(시작·끝, 세 축) | API |
|---|---|---|---|---|
| 기본(SyncNet·WaveRep MPS) | finished / completed / abstained, 시도 1 | mps / cpu / mps | 모두 fair | 결과·축 키가 스키마와 같음, 응답에 `run_info`·`thermal`·`device_used` 문자열 없음 |
| `TRINITY_SYNCNET_DEVICE=cpu` | finished / completed / abstained, 시도 1 | mps / cpu / **cpu** | 모두 fair | 같음 |
| 기본(재실행) | 같음 | mps / cpu / mps | 모두 fair | 같음 |

- 위 세 실행 뒤 최종 리뷰에서 마무리 여유 수정(축 제한을 시작 프로브 뒤에 계산, 프로브·기록 저장 제한 1초)을 넣고, 고친 코드로 기본 설정을 한 번 더 돌렸다: finished / completed / abstained, `mps / cpu / mps`, 모두 `fair`, API 키 그대로, 남은 것 없음.
- 세 실행 모두 로그 세 줄과 `run_info_json`의 값이 같았다. 작업 폴더·모델 프로세스는 남지 않았다. 첫 실행은 출력 앞부분(작업 상태·로그 줄)을 잘라 저장하지 못해 같은 설정으로 다시 돌렸다(기록 값은 첫 실행도 같다).
- 이 시각 내내 기기는 `fair`였다(앞선 측정으로 데워진 상태, 전원 연결·충전 완료 100%). 같은 시각 Swift로 직접 읽은 `ProcessInfo.thermalState`도 1(`fair`)로 프로브와 같았다. 상태가 바뀌는 경우는 실제로 보지 못했고 가짜 프로브 테스트로만 확인했다.
- 시도별 누적(재선점 뒤 2차 기록)은 실제 SIGKILL로 확인하지 않았다. 테스트(`tests/test_run_info_record.py`)로 확인했다.

**테스트:** `tests/test_device_state.py`(6, 실제 프로브 1 포함), `tests/test_axis_device_used.py`(8), `tests/test_run_info_record.py`(7), `tests/test_worker_device_log.py`(8). 실제 영상 MotionPhys 테스트에 `device_used == "cpu"` 단언을 더했다. `tests/conftest.py`가 Worker 테스트에서 프로브 자식 프로세스를 띄우지 않게 바꾼다.

## 오디오 트랙 선택 확인 (2026-11-19, 브랜치 `chore/small-checks`)

상세 표와 합성 실험은 `docs/gate.md` "오디오 트랙 선택 확인". SyncNet 쪽 요약이다. **코드 변경 없음.**

- SyncNet은 `research/syncnet/infer_segments.py::cut_segment`에서 `-map 0:v:0 -map 0:a:0`으로 **첫 오디오 스트림**을 16kHz 모노 PCM으로 잘라 클립(ffv1 + pcm_s16le, 오디오 1개)을 만든다. upstream `syncnet_pipeline.py::_extract_audio_from_video`는 `-map` 없이 그 클립을 읽지만 오디오가 하나라 선택의 여지가 없다.
- A~E(트랙: index 1 aac 2ch default, index 2 apac 4ch): `0:a:0` = index 1. `cut_segment`를 SyncNet venv에서 그대로 불러 자른 10~14초 클립의 오디오가 원본 index 1의 같은 시간 창과 PCM sha256까지 같았다(다섯 파일). Gate(FFmpeg 자동 선택)와 압축 에뮬레이터(첫 AAC)도 index 1이라 **세 경로가 같은 트랙**이다.
- 다른 트랙 구성에서는 어긋날 수 있다: 첫 오디오가 default가 아니고 뒤 트랙이 default면 Gate는 뒤 트랙, SyncNet은 첫 트랙을 읽는다(합성 c2·c5). 그러면 Gate가 한 트랙의 발화로 고른 구간을 SyncNet이 다른 트랙으로 재서, 동기 지표가 원래 음성과 무관해진 채 `completed`가 될 수 있다.
- 고치는 방안(제안만): 오디오 index를 한 함수로 한 번 정해 Gate와 SyncNet 요청 JSON에 같이 넘기고 `cut_segment`가 `-map 0:<index>`를 쓴다. 세부는 `docs/gate.md` 해당 절.
