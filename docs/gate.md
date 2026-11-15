# 최소 발화 구간 Gate (백로그 6번)

README §14.1 백로그 6번의 기록이다. 작성일: 2026-11-12.

> Gate는 "분석할 수 있는 구간"을 고를 뿐이다. 모델 추론을 하지 않고, 진위에 대해 아무것도 말하지 않는다.
> 아래 임계값은 모두 **임시값**이며 검증된 운영 범위가 아니다.
> 실제 실행은 본인 촬영 영상 1개와 그 변형 3개로만 했다.

## 2026-11-15 보완: 입 움직임 확인, VAD 비교

아래 "알려진 문제"에 대한 수정이다. **말하는 영상으로는 검증하지 않았다(미검증).** 임계값은 전부 임시값이다.

### 바뀐 규칙

음성(VAD)과 입 움직임이 **함께** 있을 때만 발화로 인정한다.

- **입 벌림 측정** (`server/gate/mouth.py`): MediaPipe Face Landmarker를 초당 약 15장에 돌려, 가장 큰 얼굴의 `안쪽 윗입술(13)–안쪽 아랫입술(14) 거리 ÷ 두 눈 바깥꼬리(33–263) 거리`를 잰다. 음성 구간(앞뒤 0.75초 여유) 안의 프레임만 본다. 특징점 좌표·프레임·crop은 저장하지 않는다. 특징점을 못 찾은 표본은 `None`이다.
- **움직임 규칙** (`server/gate/mouth_activity.py`, 순수 함수): 입 벌림 값이 0.02 이상 되돌아간 극점을 "반전"으로 센다. 반전이 0.75초 안에서 이어지는 묶음 가운데 **반전이 3번 이상**(입을 두 번 이상 연 것)인 묶음만 입이 움직인 구간으로 보고 앞뒤 0.2초를 붙인다. 한 번 벌렸다 닫는 동작은 반전 1번이라 발화로 보지 않는다. 측정이 0.3초 넘게 끊기거나 얼굴 박스가 바뀌면 시계열을 나눈다.
- **구간 규칙** (`segments.py`): 주된 얼굴이 하나인 음성 구간을 입이 움직인 조각과 아닌 조각으로 나눈다. 움직인 조각만 품질 검사를 거쳐 적합 구간이 되고, 아닌 조각은 새 원인 코드 `no_mouth_movement`로 제외한다.
- **원인 코드 묶음** `NO_SPEECH_FAMILY` = `audio_missing`, `no_speech_detected`, `no_mouth_movement`. "보이는 사람이 말하는 것을 확인하지 못했다"는 계열이다.
- 결과에 `mouth_active_segments`, `mouth_summary`(표본 수, 측정된 수, 입 벌림 중앙값·최댓값, 반전 수), `speaking_video_validated=false`가 추가됐다.

단순한 변화량(창 안의 최대–최소)을 쓰지 않은 이유: 샘플 영상 0.3~1.0초에 입을 한 번 벌렸다 닫는 동작(입 벌림 0.006 → 0.127 → 0.006)이 있어서, 변화량만 보면 그 부분이 발화로 잡힌다.

### 샘플 영상(야외, 발화 없음) 결과

| 항목 | 값 |
|---|---|
| 대표 원인 코드 | `no_mouth_movement` (발화 없음 계열) |
| 적합 구간 | 없음 (0.0초) |
| 제외 구간 | 0.0~10.433초 `no_mouth_movement` |
| 입 벌림 표본 | 157개 모두 측정됨. 중앙값 0.006, 최댓값 0.127, 반전 1번 |
| 실행 시간 | 약 2.3초 (`scripts/run_gate.py`, 1회) |

webrtcvad 민감도 0·1·2·3 어느 것으로도 결과는 같다(전체가 음성 구간 하나로 묶이고 `no_mouth_movement`).

### webrtcvad 민감도 비교 (샘플 영상의 오디오, 30ms 프레임 348개)

| 민감도 | 음성으로 판정한 프레임 | 비율 |
|---|---|---|
| 0 | 344 | 0.99 |
| 1 | 328 | 0.94 |
| 2 (지금 값) | 282 | 0.81 |
| 3 | 282 | 0.81 |

민감도를 올려도 이 오디오는 걸러지지 않는다.

### torch 없는 VAD 후보 비교

`research/gate/compare_vad.py`를 `research/gate/.venv`에서 실행했다(conda `trinity`에는 아무것도 설치하지 않았다). 결과 파일은 `data/research/gate-vad/compare_vad.json`(Git 제외).

- 입력: ① 샘플 영상의 오디오(발화 없음), ② macOS `say`로 만든 **합성 음성**(한국어 Eddy, 영어 Samantha), ③ ②에 ①을 SNR 20·10·0 dB로 섞은 것.
- ②·③의 기준(어느 30ms가 음성인가)은 깨끗한 합성 음성의 에너지로 정했다(최대 프레임 대비 -40 dB 이상).
- 표의 값: ①은 음성으로 판정한 비율(낮을수록 좋다). ②·③은 `재현율 / 오경보율`(음성 프레임 중 잡은 비율 / 비음성 프레임 중 음성이라 한 비율).

| 입력 | webrtcvad 0 | 1 | 2 | 3 | 에너지 기준선 | Silero VAD v6.0 (ONNX) | YAMNet "Speech" |
|---|---|---|---|---|---|---|---|
| ① 샘플 오디오 | 0.99 | 0.94 | 0.81 | 0.81 | 1.00 | 0.74 | 0.91 |
| 한국어 깨끗함 | 1.00 / 0.30 | 1.00 / 0.30 | 1.00 / 0.24 | 0.99 / 0.22 | 0.94 / 0.00 | 0.96 / 0.09 | 1.00 / 0.61 |
| 한국어 SNR 20 | 1.00 / 0.35 | 0.99 / 0.32 | 0.98 / 0.23 | 0.94 / 0.21 | 1.00 / 0.89 | 0.95 / 0.11 | 1.00 / 0.98 |
| 한국어 SNR 10 | 1.00 / 0.99 | 1.00 / 0.93 | 1.00 / 0.86 | 0.98 / 0.84 | 1.00 / 1.00 | 0.96 / 0.22 | 1.00 / 0.80 |
| 한국어 SNR 0 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.98 / 0.82 | 0.90 / 0.49 |
| 영어 깨끗함 | 1.00 / 0.39 | 1.00 / 0.39 | 1.00 / 0.26 | 0.99 / 0.18 | 1.00 / 0.00 | 0.97 / 0.07 | 1.00 / 0.62 |
| 영어 SNR 20 | 1.00 / 0.57 | 1.00 / 0.43 | 1.00 / 0.31 | 0.99 / 0.28 | 1.00 / 1.00 | 0.98 / 0.10 | 1.00 / 0.98 |
| 영어 SNR 10 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.98 / 0.13 | 1.00 / 0.98 |
| 영어 SNR 0 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.98 / 0.52 | 0.57 / 0.24 |

후보: webrtcvad(지금 쓰는 것), Silero VAD v6.0의 ONNX 모델을 `onnxruntime` 1.32.0으로 직접 실행(파이썬 패키지 `silero-vad`는 torch가 필요해 쓰지 않았다), MediaPipe Audio Classifier의 YAMNet "Speech" 점수(이미 설치된 mediapipe로 실행, 약 1초 창이라 시간 해상도가 낮다. 임계값 0.3은 임의로 정했다), 에너지 기준선(-45 dBFS). TEN VAD는 실행하지 않았다(이용 조건 확인 필요).

읽는 법과 한계:

- **서로 다른 세 방식이 모두 샘플 오디오 대부분을 음성으로 판정했다.** YAMNet의 창별 "Speech" 점수는 앞 5초에서 0.67~0.85, 평균 0.55이고 다음 순위(Music 0.04)와 차이가 크다. 이 오디오에 **사람 목소리(화면 밖이나 주변 사람)가 실제로 들어 있을 가능성**이 있다. 들어 보고 확인하지 않았다(**확인 필요**, 저장소 소유자). 그렇다면 VAD의 오판이 아니고, 어떤 VAD로 바꿔도 이 영상은 걸러지지 않는다. 걸러 내는 것은 입 움직임 확인이다.
- 같은 이유로 ③의 "소음"에는 음성처럼 들리는 소리가 섞여 있을 수 있다. ③의 오경보율은 그만큼 부풀려졌을 수 있다.
- 합성 음성은 실제 발화가 아니다. 녹음은 하나, 목소리는 둘이다. **이 표로 VAD의 정확도를 주장하지 않는다.**
- 이 표 안에서는 Silero VAD가 섞은 조건의 오경보율이 가장 낮았다(SNR 10 dB 이상에서 0.10~0.22, webrtcvad는 0.21~1.00). 재현율은 0.95 이상으로 비슷했다.

결정:

- **VAD는 webrtcvad 민감도 2 그대로 둔다.** 바꿔도 샘플 문제는 풀리지 않고, 실제 발화 영상이 없어 재현율을 확인할 수 없다.
- Silero VAD(ONNX)는 교체 후보로 남긴다. 서버 환경에 `onnxruntime`과 모델 파일이 추가로 필요하다. 이용 조건은 **확인 필요**. 실제 발화 영상으로 다시 비교한 뒤 정한다.

### 받은 모델 파일 (공식 출처, 2026-11-15)

| 파일 | 출처 | sha256 | 용도 |
|---|---|---|---|
| `data/models/gate/face_landmarker.task` | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` | Gate (해시는 `configs/gate_models.json`, 다르면 실행 거부) |
| `data/research/gate-vad/silero_vad_v6.0.onnx` | `https://github.com/snakers4/silero-vad/raw/v6.0/src/silero_vad/data/silero_vad.onnx` | `597d30b3ec076608d059477bb14cfeffdf951bf5cae370d38f65d33bbfe82004` | VAD 비교만 |
| `data/research/gate-vad/yamnet.tflite` | `https://storage.googleapis.com/mediapipe-models/audio_classifier/yamnet/float32/1/yamnet.tflite` | `4d8b4a53282dc83ef04e3e7dbc4fbc98082e34e44ed798e16c3a0cdd4c584faf` | VAD 비교만 |

세 파일 모두 Git 밖에 있다. 이용 조건은 **확인 필요**(이번에 확인하지 않았다).

### 검증하지 않은 것 (이번 보완)

- **말하는 영상**: 한 사람이 화면을 보고 말하는 영상에서 적합 구간이 나오는지. 허가 영상을 `data/research/samples/speaking/`에 넣으면 `tests/test_gate_media.py`의 `test_speaking_video_has_eligible_segment`가 돈다. 지금은 건너뛴다.
- 입 움직임 임계값 전부(반전 폭 0.02, 반전 3번, 간격 0.75초). 근거는 샘플 영상의 닫힌 입 잡음 수준(중앙값 0.006)과 합성 시계열뿐이다. 작게 말하는 사람, 옆얼굴, 마스크, 낮은 프레임률, 빠르게 한두 마디만 하는 경우에 발화를 놓칠 수 있다.
- 말하지 않고 입만 움직이는 경우(씹기, 웃음)에 음성으로 판정된 소리가 겹치면 발화로 잘못 인정할 수 있다.
- 화면 밖 목소리와 보이는 사람의 입 움직임이 우연히 겹치는 경우. 음성과 입 움직임의 시간 대응(동기)은 보지 않는다. 그것은 SyncNet(백로그 11번)의 일이다.
- 긴 영상에서의 실행 시간(특징점 검출은 음성 구간에서 초당 15장).

## 알려진 문제 (2026-11-12, 저장소 소유자 확인) — 위 보완으로 수정함

- 샘플 영상은 실제로 **발화가 없다**(야외, 주변 소음). 그런데 VAD가 대부분을 음성으로 판정했다(30ms 프레임 348개 중 282개).
- 따라서 단일 발화 테스트의 기대값이 틀렸을 수 있다. `tests/test_gate_media.py`의 `test_single_speaker_video_has_eligible_segment`는 이 영상에 적합 구간이 있다고 기대하지만, 발화가 없는 영상이라면 적합 구간이 없어야 맞다.
- 입 움직임 확인 추가와 VAD 비교가 필요하다.
- 발화가 있는 영상은 아직 없다.
- 영향을 받는 서술: 아래 "실행 결과"의 "원본 (단일 발화)" 행과 적합 구간 0~10.433초, README §14.1 6번 행의 "단일 발화 ... 확인". 실제로 확인된 것은 "소음을 음성으로 판정한 구간에 얼굴이 하나 있으면 적합 구간으로 낸다"는 동작뿐이다. 오디오 제거본·검은 화면본·무음 오디오본의 원인 코드 분리는 이 문제와 무관하다.
- (2026-11-12 당시) Gate 수정은 미뤘다. 2026-11-15에 새 브랜치 `feat/gate-mouth-motion`에서 위와 같이 고쳤다. 아래 본문의 "원본 (단일 발화)" 서술은 당시 기록이며 표에 정정을 달았다.

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

2026-11-15에 Worker의 `preprocessing`에 연결했다(백로그 7번). API 서버는 Gate 의존성을 import하지 않는다(테스트로 확인).

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
| 음성 구간에서 반복되는 입 움직임을 확인하지 못함 | `no_mouth_movement` |
| 음성 구간에 주된 얼굴 없음 | `no_face_detected` |
| 음성 구간에 주된 얼굴 둘 이상 | `speaker_unconfirmed` |
| 프레임 짧은 변이 기준 미만 | `low_resolution` |
| 얼굴 높이(구간 중앙값)가 기준 미만 | `face_too_small` |
| 얼굴 선명도(구간 중앙값)가 기준 미만 | `too_blurry` |
| 구간 길이가 기준 미만 | `segment_too_short` |

대표 원인 코드는 음성 구간을 가장 길게 막은 원인이다. 음성이 아예 없으면 `no_speech_detected`다.
원인별 `analysis_status`·`verdict_status` 대응은 README §15.3 결정 8 보완(2026-11-15 사용자 승인)을 따른다.

## coverage

| 필드 | Gate가 채우는 값 |
|---|---|
| `video_duration_sec` | ffprobe 길이 |
| `eligible_duration_sec` | 적합 구간 길이의 합 |
| `analyzed_duration_sec`, `full_video_coverage`, `eligible_coverage`, `analyzed_segments` | `null` |

뒤의 네 필드는 실제로 추론한 양이다. Gate 자체는 `null`로 두고, Worker가 WaveRep 성공 후 채운다. 미실행·실패의 분석 길이와 비율은 `null`, 분석 구간 목록은 `[]`이다. 적합 구간이 없음을 확인한 경우 적합 길이는 `0`이다. 숫자 0인 점수와 혼동하지 않는다.
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
| 원본 (**발화 없음**. 2026-11-12에는 "단일 발화"로 잘못 적었다) | — | `no_mouth_movement` (2026-11-15부터. 그 전에는 `null`) | 없음 (그 전에는 0.0~10.433초 1개로 잘못 나왔다) |
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

# 얼굴 검출·얼굴 특징점 모델 (Git 제외 경로)
mkdir -p data/models/gate
curl -fL -o data/models/gate/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
curl -fL -o data/models/gate/blaze_face_short_range.tflite \
  https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite
shasum -a 256 data/models/gate/blaze_face_short_range.tflite data/models/gate/face_landmarker.task   # configs/gate_models.json의 값과 같아야 한다

python scripts/run_gate.py data/research/samples/<허가 영상>.mp4
pytest -q
```

URL이 `latest`를 가리키므로 나중에 받은 파일은 해시가 다를 수 있다. 그 경우 Gate가 실행을 거부한다. 새 파일을 확인한 뒤 `configs/gate_models.json`을 갱신한다.

샘플 영상, Gate 의존성, 모델 파일, ffmpeg 중 하나라도 없으면 `tests/test_gate_media.py`는 건너뛴다(`pytest -q -rs`로 사유 확인). `tests/test_gate_segments.py`는 항상 실행된다.

VAD 비교를 다시 하려면(연구용, 서버 환경과 별개):

```bash
research/gate/.venv/bin/pip install -r research/gate/requirements.lock.txt -r research/gate/requirements-compare.txt
# 모델 두 개를 data/research/gate-vad/ 에 받는다(출처와 sha256은 위 "받은 모델 파일" 표)
research/gate/.venv/bin/python research/gate/compare_vad.py \
  --noise data/research/samples/<발화 없는 허가 영상>.mp4 --work data/research/gate-vad
```


## Worker 연결 (2026-11-15)

- 실행 환경: conda `trinity` Python 3.11.18. mediapipe 1.2.3,
  webrtcvad-wheels 2.0.14.post1, opencv-contrib-python 5.0.0.93, numpy 2.4.6.
  연결 전·실제 실행 시 torch가 없는 것을 확인했다. 패키지를 추가하거나 바꾸지 않았다.
  `research/gate/.venv`는 VAD 비교용, `research/waverep/.venv`는 WaveRep 추론용으로 유지한다.
- `server/gate/runner.py`는 같은 Python으로 `server.gate.process`를 실행한다.
  명령은 인자 리스트이고 작업 폴더의 요청 JSON 경로만 넘긴다. 미디어는 서버가 복사한 작업 폴더 안 파일이다.
- 자식 프로세스는 기존 `run_gate`를 그대로 실행한다. 결과 형식·원인·구간 범위를 검사하고,
  깨진 출력·비정상 종료·설정/의존성 오류는 `gate_error`, 전체 Gate 제한시간 초과는 `gate_timeout`이다.
- `TRINITY_GATE_TIMEOUT_SECONDS` 기본 120초. Worker는 기다리는 동안 heartbeat를 보낸다.
  취소·lease 상실·작업 제한시간에는 Gate와 같은 프로세스 그룹의 FFmpeg까지 종료한다.
  내부 요청·결과 JSON과 미디어 복사본은 끝나면 삭제한다. stderr는 결과/로그에 남기지 않는다.
- 적합 구간이 없으면 `waverep`·`motionphys`·`syncnet`·`fusion` 단계를 완료 목록에 넣지 않는다.
  `finalizing`으로 가서 대표 원인 코드와 승인된 분석·판정 상태를 기록한다.
- API 필드 변경 없음. 적합·제외 구간의 시각, 제외 원인과 품질(있는 경우)은
  기존 `explanations`의 `GATE_ELIGIBLE_SEGMENT` / `GATE_EXCLUDED_SEGMENT`에 담는다.
  해상도·fps·길이는 `GATE_MEDIA`, 미검증 고지는 `GATE_UNVALIDATED`에 기록한다.
  품질은 얼굴 높이/비율/선명도 중앙값, 영상 짧은 변, 표본 프레임 수다.
- `coverage.video_duration_sec`는 ffprobe 길이, `eligible_duration_sec`는 Gate 적합 길이다.
  WaveRep 성공 때만 분석 구간을 디코딩 길이로 자르고 합친 길이·비율을 채운다.
  수동 우회에서는 적합 길이·적합 coverage가 `null`이다. coverage는 정확도가 아니다.
- 수동 구간은 `TRINITY_DEV_MANUAL_SEGMENTS`를 명시한 개발·테스트에서만 Gate를 건너뛴다.
  기본은 꺼짐이다. 우회한 결과는 `gate_bypassed=true`, `partial` / `abstained`다.

실제 재현 명령:

```bash
conda activate trinity
python scripts/smoke_gate_worker.py
```

기존 발화 없는 샘플(10.433초) 1회: `finished`, `out_of_scope`, `not_applicable`,
`no_mouth_movement`, 적합 길이 0초, 분석 길이·비율 `null`, 분석 구간 `[]`.
WaveRep 단계·logit 없음, `raw_score`·`overall_score=null`, 작업 폴더 삭제 확인.
실행 약 2.79초. 스모크 전용 heartbeat 0.2초/lease 2초 설정에서 preprocessing의
서로 다른 lease 만료 시각 13개를 관찰했다. 기본 heartbeat 10초보다 짧은 영상이므로
이 설정은 실제 연장 관찰을 위한 것이다. 처리 속도나 정확도 평가가 아니다.

## 실내 촬영 샘플 확인 (2026-11-15)

사용자가 옮긴 본인 촬영 영상 A–E를 Git 밖의 임시 레지스트리에 등록해,
기존 Gate 설정으로 검사했다. 표의 길이는 초 단위다.

| 샘플 | 촬영 조건 | 영상 길이 | Gate 적합 길이 | 결과 |
|---|---|---:|---:|---|
| A | 가로 발화 | 41.002 | 37.021 | 통과, 5개 구간 |
| B | 세로 발화 | 40.535 | 33.460 | 통과, 9개 구간 |
| C | 발화 없음 | 40.468 | 0 | `no_mouth_movement` (VAD가 0.36초 구간 감지) |
| D | 화면 속 화자의 입 움직임 없이 본인 음성 사용 | 40.902 | 0 | `no_mouth_movement` |
| E | 발화·침묵 교대 | 52.037 | 24.864 | 통과, 6개 구간 |

E의 발화 기준은 촬영자 기록상 0–10초, 20–30초, 40–50초다.
Gate 적합 구간은 0.867–5.100, 5.790–9.734, 22.110–29.940,
40.650–42.336, 42.936–47.670, 48.203–50.640초였다.
10–20초와 30–40초는 모두 제외됐다. 기록상 발화 길이 30초 중 24.224초가 겹쳤고,
마지막 구간은 50초를 0.640초 넘었다. 20.668–21.660초 조각은
`segment_too_short`였다. 비교 기준은 촬영자가 알려 준 시각이며,
프레임 단위 주석은 없다. 이 샘플들로 확인한 결과이며 다중 발화는 미검증이다.

재현할 때는 위 파일을 Git 밖 레지스트리에 등록하고 확인된 경로를
`python scripts/run_gate.py <허가 영상 경로>`에 넘긴다.
