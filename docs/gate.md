# 최소 발화 구간 Gate (백로그 6번)

README §14.1 백로그 6번의 기록이다. 작성일: 2026-11-12.

> Gate는 "분석할 수 있는 구간"을 고를 뿐이다. 모델 추론을 하지 않고, 진위에 대해 아무것도 말하지 않는다.
> 아래 임계값은 모두 **임시값**이며 검증된 운영 범위가 아니다.
> 실제 실행은 본인 촬영 영상 1개와 그 변형 3개로만 했다.

## 하는 일

`server.gate.run_gate(media_path)`가 허가 미디어 파일 하나를 받아 다음을 돌려준다.

- 적합 구간 목록(`eligible_segments`)과 구간별 품질 수치
- 제외 구간 목록(`excluded_segments`)과 원인 코드
- README §9 형식의 `coverage`
- 적합 구간이 하나도 없을 때의 대표 원인 코드(`reason_code`)

처리 순서:

1. **ffprobe** (`server/gate/probe.py`): 길이, 해상도, fps, 회전, 오디오 스트림 유무.
2. **VAD** (`server/gate/vad.py`): FFmpeg가 16kHz 모노 PCM을 표준 출력으로 넘기고, `webrtcvad`가 30ms 단위로 음성 여부를 판정한다. 오디오를 파일로 남기지 않는다.
3. **얼굴 검출** (`server/gate/faces.py`): MediaPipe Face Detector를 초당 약 5프레임에 돌린다. 박스·점수·선명도 숫자만 남기고, 프레임과 얼굴 crop은 저장하지 않는다.
4. **추적과 규칙** (`server/gate/segments.py`): 표본 사이에서 박스 겹침(IoU)으로 같은 얼굴을 잇고, 아래 규칙으로 구간을 나눈다. 순수 함수다.

Worker에는 연결하지 않았다(백로그 7번). API 서버는 Gate 의존성을 import하지 않는다(테스트로 확인).

## 1차 규칙

- 음성 구간 동안 **주된 얼굴이 정확히 하나**일 때만 발화 구간으로 인정한다.
- 주된 얼굴 = 높이가 프레임 짧은 변의 10% 이상인 검출 얼굴. 그보다 작은 얼굴은 배경으로 보고 세지 않는다.
- 주된 얼굴이 둘 이상이면 `speaker_unconfirmed`로 보류한다. 누가 말하는지는 고르지 않는다(SyncNet 기반 선택은 백로그 11번).
- 같은 얼굴 사이의 0.5초 이하 검출 누락은 메운다. 얼굴이 다른 사람으로 바뀌면(겹침 없음) 구간을 나눈다.
- 한계: 이 규칙은 "보이는 얼굴이 말하는 사람"이라고 **가정**한다. 화면 밖 사람이 말하고 얼굴 하나만 보이는 경우를 구분하지 못한다.

## 원인 코드

README §10에 추가했다.

| 상황 | 원인 코드 |
|---|---|
| 파일이 없거나, 읽을 수 없거나, 영상 스트림이 없음 | `media_unreadable` |
| 오디오 스트림 없음 | `audio_missing` |
| 오디오는 있으나 음성 구간 없음 (말하지 않는 구간) | `no_speech_detected` |
| 음성 구간에 주된 얼굴 없음 | `no_face_detected` |
| 음성 구간에 주된 얼굴 둘 이상 | `speaker_unconfirmed` |
| 프레임 짧은 변이 기준 미만 | `low_resolution` |
| 얼굴 높이(구간 중앙값)가 기준 미만 | `face_too_small` |
| 얼굴 선명도(구간 중앙값)가 기준 미만 | `too_blurry` |
| 구간 길이가 기준 미만 | `segment_too_short` |

대표 원인 코드는 음성 구간을 가장 길게 막은 원인이다. 음성이 아예 없으면 `no_speech_detected`다.
이 코드들을 `analysis_status`(`out_of_scope`, `insufficient_quality` 등)에 어떻게 대응시킬지는 정하지 않았다. Worker에 연결할 때(백로그 7번) 정한다.

## coverage

| 필드 | Gate가 채우는 값 |
|---|---|
| `video_duration_sec` | ffprobe 길이 |
| `eligible_duration_sec` | 적합 구간 길이의 합 |
| `analyzed_duration_sec`, `full_video_coverage`, `eligible_coverage`, `analyzed_segments` | `null` |

뒤의 네 필드는 실제로 추론한 양이다. Gate는 추론하지 않으므로 `0`이 아니라 `null`로 둔다. 백로그 7번에서 채운다.
`coverage`는 분석할 수 있는 양일 뿐이고 정확도나 신뢰도가 아니다.

## 임시 임계값 (`GateConfig`, 전부 미검증)

| 항목 | 값 | 비고 |
|---|---|---|
| 얼굴 검출 표본 | 초당 5프레임 | |
| 검출 최소 신뢰도 | 0.5 | |
| 주된 얼굴 최소 높이 | 짧은 변의 10% | |
| 추적 최소 IoU | 0.3 | |
| 메우는 검출 누락 | 0.5초 이하 | |
| VAD 민감도 | 2 (0~3) | `webrtcvad` |
| 버리는 음성 조각 | 0.25초 미만 | |
| 잇는 쉼 | 0.4초 이하 | |
| 최소 짧은 변 | 360px | |
| 최소 얼굴 높이 | 96px | |
| 최소 선명도 | 20 | 얼굴 영역을 256px로 맞춘 뒤의 Laplacian 분산 |
| 최소 구간 길이 | 1.0초 | |

이 값들은 동작을 확인하려고 둔 출발점이다. 데이터로 정한 값이 아니다. 각 모델이 실제로 필요로 하는 입력 조건(예: WaveRep 원본 전처리는 가운데 504×504 crop, `docs/waverep-spike.md`)과 맞추는 일은 하지 않았다. 선명도는 압축과 해상도에 따라 달라지므로 값의 의미가 영상마다 같다고 볼 수 없다.

## VAD 후보와 선택

조건: 서버 환경(conda `trinity`)에 torch를 넣지 않는다.

| 후보 | torch | 확인한 것 (2026-11-12) | 결정 |
|---|---|---|---|
| `webrtcvad-wheels` 2.0.14.post1 | 불필요 | arm64·Python 3.11 휠 있음(32KB), 추가 의존성 없음, 휠 메타데이터상 MIT | **선택** |
| `silero-vad` 6.2.3 (PyPI) | **필요** | 휠 메타데이터에 `Requires-Dist: torch>=1.12.0` | 제외 |
| Silero VAD ONNX 모델 + `onnxruntime` 1.31.1 | 불필요 | `onnxruntime` 휠 있음(20MB). 모델 파일만 따로 받는 경로와 이용 조건은 **확인 필요** | 보류 (대안) |
| FFmpeg `silencedetect` | 불필요 | 추가 의존성 없음. 음량 기준이라 말소리와 다른 소리를 구분하지 않는다 | 제외 |

선택 이유: torch가 필요 없고 가장 가볍다. **정확도를 비교해서 고른 것이 아니다.** 후보 간 비교 실험은 하지 않았다. `webrtcvad`가 음악·소음·한국어 발화에서 얼마나 정확한지는 **확인 필요**다. 문제가 보이면 ONNX 방식을 다음 후보로 검토한다.

## 얼굴 검출

- 패키지: `mediapipe` 1.2.3 (휠 메타데이터상 Apache 2.0). arm64·Python 3.11에서 설치와 실행을 확인했다.
- 모델 파일: `blaze_face_short_range.tflite` (229,746바이트). 패키지에 들어 있지 않아 따로 받는다. Git 밖 `data/models/gate/`에 두고, sha256을 `configs/gate_models.json`에 기록했다. 해시가 다르면 Gate는 실행을 거부한다.
- 모델 파일의 이용 조건과 이 모델이 잘 동작하는 조건(거리, 얼굴 크기, 각도)은 **확인 필요**다(모델 카드를 읽지 않았다).
- 회전 정보가 있는 영상(세로 촬영)에서 OpenCV가 돌려주는 프레임 방향과 ffprobe 기준 해상도가 일치하는지는 **미검증**이다.

## 실행 결과

입력: `data/research/samples/`의 본인 촬영 영상 1개(1920×1080, 30fps, 10.43초, 권한 근거는 `docs/media-access.md`)와 FFmpeg로 만든 변형. `scripts/run_gate.py`와 `pytest`로 확인했다.

| 입력 | 만드는 방법 | 대표 원인 코드 | 적합 구간 |
|---|---|---|---|
| 원본 (단일 발화) | — | 없음 (`null`) | 0.0~10.433초 1개 |
| 오디오 제거본 | `-c:v copy -an` | `audio_missing` | 없음 |
| 검은 화면본 | `drawbox` 검은색 채움, `libx264` | `no_face_detected` | 없음 |
| 무음 오디오본 | `anullsrc` 무음 트랙으로 교체 | `no_speech_detected` | 없음 |

원본의 구간 품질 수치: 얼굴 높이 중앙값 649px(짧은 변의 60%), 선명도 중앙값 101.58, 표본 53프레임 모두에서 얼굴 1개.

관찰:

- VAD가 영상 전체(0~10.43초)를 한 음성 구간으로 묶었다. 30ms 프레임 348개 중 282개가 음성으로 판정됐고(민감도 2), 0.4초 이하의 쉼을 이었기 때문이다. 실제로 영상 내내 말하고 있는지는 사람이 대조하지 않았다(**확인 필요**).
- 실행 시간: 원본 약 4초(같은 프로세스에서 두 번째 실행, 1회 측정). 첫 실행은 패키지 로딩 때문에 더 걸린다.
- 이 샘플은 카카오톡을 거친 파일로 보인다(`docs/media-access.md`). 휴대폰 원본에서의 값은 다를 수 있다.

## 검증하지 않은 것

- **여러 명이 말하는 영상: 미검증.** 동의받은 영상이 없다. `speaker_unconfirmed`는 합성한 얼굴 표본을 넣은 규칙 단위 테스트로만 확인했다. 실제 영상에서 MediaPipe가 두 얼굴을 안정적으로 검출하는지, 10% 기준이 적절한지는 모른다.
- 화면 밖 발화자, 얼굴이 가려진 경우, 옆얼굴, 빠른 움직임, 장면 전환이 있는 영상.
- 세로 영상, 저해상도, 낮은 fps, 긴 영상(메모리와 시간).
- 품질 원인 코드(`low_resolution`, `face_too_small`, `too_blurry`, `segment_too_short`)는 규칙 단위 테스트로만 확인했다. 실제 저품질 영상으로는 실행하지 않았다.
- 임계값 전부.
- 오디오 PCM을 한 번에 메모리로 읽는다(16kHz 모노 기준 1분에 약 1.9MB). 긴 영상의 상한은 정하지 않았다.

## 재현 방법

```bash
conda activate trinity
pip install -r requirements-gate.txt          # torch 없음. research/gate/requirements.lock.txt와 같은 버전

# 얼굴 검출 모델 (Git 제외 경로)
mkdir -p data/models/gate
curl -fL -o data/models/gate/blaze_face_short_range.tflite \
  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite
shasum -a 256 data/models/gate/blaze_face_short_range.tflite   # configs/gate_models.json의 값과 같아야 한다

python scripts/run_gate.py data/research/samples/<허가 영상>.mp4
pytest -q
```

URL이 `latest`를 가리키므로 나중에 받은 파일은 해시가 다를 수 있다. 그 경우 Gate가 실행을 거부한다. 새 파일을 확인한 뒤 `configs/gate_models.json`을 갱신한다.

샘플 영상, Gate 의존성, 모델 파일, ffmpeg 중 하나라도 없으면 `tests/test_gate_media.py`는 건너뛴다(`pytest -q -rs`로 사유 확인). `tests/test_gate_segments.py`는 항상 실행된다.
