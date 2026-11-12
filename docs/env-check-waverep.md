# 개발 환경 점검 결과

README §14.1 백로그 2번(P0-1). `python scripts/check_env.py`가 만든 파일이다. 직접 고치지 않는다.

- 점검 시각: 2026-11-12 14:58:08 +1000
- 플랫폼: macOS-27.0.1-arm64-arm-64bit
- 사용 가능한 추론 장치(선택 순서): mps, cpu
- `PYTORCH_ENABLE_MPS_FALLBACK`: 설정 안 됨

상태 값: `정상` 동작 확인, `없음` 설치되지 않음(설치하지 않고 기록만 함), `실패` 있지만 동작하지 않거나 기대와 다름.

## 점검 표

| 항목 | 상태 | 내용 |
|---|---|---|
| Python | 정상 | 3.11.18 (/Users/iyeonje/ai-/research/waverep/.venv/bin/python) |
| 아키텍처 | 정상 | Darwin 27.0.0 / arm64 |
| Rosetta 변환 | 정상 | proc_translated=0 |
| ffmpeg | 정상 | ffmpeg version 8.0.1 Copyright (c) 2000-2025 the FFmpeg developers (/opt/homebrew/bin/ffmpeg) |
| ffprobe | 정상 | ffprobe version 8.0.1 Copyright (c) 2007-2025 the FFmpeg developers (/opt/homebrew/bin/ffprobe) |
| ffmpeg 인코더 libx264 | 정상 | 사용 가능 |
| PyTorch | 정상 | 2.15.0 |
| PyTorch CPU | 정상 | 행렬곱 스모크 통과 |
| PyTorch MPS | 정상 | is_built=True, is_available=True, 행렬곱 스모크 통과 |
| OpenCV (cv2) | 정상 | 5.0.0 |
| LightGBM | 없음 | 설치되지 않음 |

## 없음·실패 목록

- **LightGBM** — 없음: 설치되지 않음

## 콘솔 로그

```text
[정상] Python              3.11.18 (/Users/iyeonje/ai-/research/waverep/.venv/bin/python)
[정상] 아키텍처                Darwin 27.0.0 / arm64
[정상] Rosetta 변환          proc_translated=0
[정상] ffmpeg              ffmpeg version 8.0.1 Copyright (c) 2000-2025 the FFmpeg developers (/opt/homebrew/bin/ffmpeg)
[정상] ffprobe             ffprobe version 8.0.1 Copyright (c) 2007-2025 the FFmpeg developers (/opt/homebrew/bin/ffprobe)
[정상] ffmpeg 인코더 libx264  사용 가능
[정상] PyTorch             2.15.0
[정상] PyTorch CPU         행렬곱 스모크 통과
[정상] PyTorch MPS         is_built=True, is_available=True, 행렬곱 스모크 통과
[정상] OpenCV (cv2)        5.0.0
[없음] LightGBM            설치되지 않음
```
