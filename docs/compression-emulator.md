# 압축 에뮬레이터: 범용 프로파일과 원본 코드 동작 확인

README §14.1 백로그 9번(P1-4). 작성일: 2026-11-14.

> **실제 YouTube의 재인코딩과 같다고 주장하지 않는다.**
> 여기서 만든 것은 FFmpeg 소프트웨어 인코더(libx264)의 범용 압축·리사이즈 변형이다(README §6.2의 1단계).
> 플랫폼 처리본에서 추정한 파라미터가 아니다. 어떤 영상도 YouTube에 올리지 않았다.
> 성능 결과도 아니다. 모델 점수를 내지 않았다.

## 결론

- Montibeller 등(arXiv:2508.08765)의 공개 코드 `truebees-ai/social_emulator`는 있다. 수정 없이 macOS ARM64에서 두 단계 모두 실행됐다.
- **저자 방식의 플랫폼 에뮬레이션은 하지 못했다.** 이 코드는 "원본 영상 + 플랫폼에서 받은 같은 영상" 쌍에서 파라미터를 추정하는데, 저장소에 추정된 파라미터 파일도 샘플 영상도 없고, 우리에게는 플랫폼 처리본이 없다.
- 그래서 **FFmpeg 범용 프로파일로 대신했다**: libx264 CRF 20/28/34 × 해상도 원본/1080/720/480 = 12개(`training/emulator/`).
- 본인 촬영 영상 1개에서 12개 프로파일 모두 두 번 실행한 출력의 sha256이 같았다.
- 공통 manifest에 `compression_profile_id` 열을 넣었고, 평가 리포트가 압축 조건별 지표(`by_compression`)를 낸다. 합성 점수로 동작만 확인했다.

## 1. 공개 코드 확인

| 항목 | 값 |
|---|---|
| 저장소 | <https://github.com/truebees-ai/social_emulator> (논문 각주가 가리키는 곳) |
| 확인한 커밋 | `3e1a39a46c17d0357c0c991663ba878cb25cf25f` (2025-10-29) |
| 라이선스 | 저장소의 `LICENSE` 파일은 Creative Commons Attribution 4.0 International(CC BY 4.0)이고 GitHub도 그렇게 표시한다. 코드에 CC BY를 적용했을 때의 세부 해석(특허·소스 재배포 등)은 **확인 필요** |
| 내용 | `SN_parameters_emulation.py`(추정), `SN_encoding_emulation.py`(인코딩), `video_utils.py`, `runner.sh`. 약 400줄 |
| 의존성 | `ffmpeg` 명령, `ffmpeg-python`, `numpy`, `pandas`, `tqdm` |
| 없는 것 | 추정된 파라미터 파일(`compression_models.json`), 샘플 영상(`sample_videos/`는 비어 있다) |

- 원본 코드는 `research/emulator/upstream/`에 clone했고 Git에 넣지 않는다(`.gitignore`의 `research/*/upstream/`). 재배포하지 않는다. 파일을 수정하지 않았다.
- `training/emulator/`는 원본 코드를 복사하거나 고친 것이 아니라 따로 쓴 코드다.
- README에 "Coming soon python library level support"라고 적혀 있다. 패키지로 설치하는 방법은 아직 없다.

### 원본 코드가 하는 일 (코드를 읽고 확인한 것)

1. **추정**: 플랫폼 처리본의 해상도와 비트레이트를 읽는다. 원본을 그 해상도로 줄여 CRF를 `--crf-min`부터 1씩 올리며 인코딩하고, 비트레이트가 처리본보다 **처음으로 낮아지는** CRF를 그 쌍의 값으로 적는다.
2. **인코딩**: 새 영상의 해상도와 가장 가까운 표본을 찾아 목표 해상도를 정하고, 그 목표 해상도를 가진 표본들의 CRF 평균(정수로 내림)으로 인코딩한다. 프로파일은 플랫폼 이름이 `Youtube`면 `high`, 아니면 `main`이다.

코드에서 본 주의점:

- `SN_parameters_emulation.py`에 `breakpoint()` 호출이 남아 있다. 그대로 실행하면 디버거에서 멈춘다. 파일을 고치지 않고 `PYTHONBREAKPOINT=0`으로 껐다.
- `--platform`은 추정 단계에서 `Youtube`, `Facebook`만 받는다.
- 인코딩 단계의 출력에는 **오디오가 없다**(영상 스트림만 내보낸다). 실제 출력에서 확인했다.
- 스레드 수와 메타데이터를 고정하지 않는다. 같은 입력에서 같은 바이트가 나오는지는 재지 않았다(**미검증**).
- 추정 단계는 처리본의 코덱 이름(`h264`)을 인코더 이름으로 넘긴다. 이 기기의 FFmpeg 8.0.1에서는 `h264`가 libx264로 풀렸다(로그로 확인). 다른 빌드에서 하드웨어 인코더로 풀릴 수 있는지는 **확인 필요**.

### 동작 확인 (플랫폼 추정이 아니다)

플랫폼 처리본 자리에 **로컬에서 만든, 답을 아는 파일**을 넣었다. 본인 촬영 영상을 `x264-crf28-720p`로 압축한 것이다. 원본 코드가 끝까지 도는지, 넣은 값을 되찾는지만 본다.

| 항목 | 값 |
|---|---|
| 환경 | `research/emulator/.venv`, Python 3.11.18, ffmpeg-python 0.2.0, numpy 2.4.6, pandas 3.1.1, tqdm 4.70.1 (`research/emulator/requirements.lock.txt`), FFmpeg 8.0.1 |
| 입력 | `data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4`(Git 제외). 저장소 소유자가 직접 촬영한 본인 영상, HEVC 1920×1080, 10.43초 (`docs/motionphys-spike.md` "입력") |
| 넣은 값 | CRF 28, 1280×720, 영상 965 kbps |
| 추정 결과 | 표본 1개: `1920x1080 → 1280x720`, **CRF 29**, 프로파일 High |
| 원본 코드의 출력 | H.264 High 1280×720, 313프레임, 영상 868 kbps, 1,136,293바이트, 오디오 없음 |

- 해상도는 되찾았다. CRF는 28이 아니라 29다. "비트레이트가 처음으로 낮아지는 값"을 고르는 규칙이라, 같은 설정으로 만든 파일을 넣으면 한 단계 높은 값이 나온다. 그 결과 출력의 영상 비트레이트가 넣은 파일보다 약 10% 낮다.
- `--platform Youtube`는 필수 인자를 채운 이름표일 뿐이다. 결과는 YouTube와 무관하고, 산출 파일 이름을 `NOT_PLATFORM_local_standin_models.json`으로 했다.
- 영상 1개, 쌍 1개다. 논문의 수치를 재현한 것이 아니다.

### 향후 경로: 실제 파라미터 추정 (지금은 하지 않는다)

- 저장소 소유자가 **직접 찍은 진짜 영상**을 **본인 채널**에 올리고, YouTube Studio에서 받은 파일을 원본과 쌍으로 쓰면 위 추정 단계를 실제 플랫폼 처리본으로 돌릴 수 있을 수 있다.
- **YouTube Studio에서 받은 파일이 플랫폼 처리본(재인코딩된 것)인지, 올린 원본에 가까운 것인지는 확인 필요다.** 처리본이 아니면 이 경로로는 추정할 수 없다. 받은 파일의 해상도·코덱·비트레이트가 시청자에게 전달되는 것과 같은지도 확인 필요다.
- 이 경로의 권한·약관 검토는 `docs/media-access.md`의 범위다. 데이터셋 영상이나 다른 사람의 영상은 올리지 않는다.
- **지금은 업로드하지 않는다.** 이 문서의 어떤 결과도 YouTube 처리본을 쓰지 않았다.
- 하게 되더라도 그 결과는 "그 시점, 그 영상들, 그 해상도에서 추정한 값"이다. YouTube 전체의 동작이라고 주장하지 않는다.

## 2. 범용 프로파일

| 항목 | 값 |
|---|---|
| 인코더 | `libx264`만. 하드웨어 인코더(VideoToolbox 등)는 프로파일을 만들 때와 실행 직전에 거부한다 |
| CRF | 20, 28, 34 |
| 해상도 | `source`(그대로), `1080p`, `720p`, `480p`. 숫자는 **짧은 변**의 픽셀 수(세로 영상은 너비) |
| ID | `x264-crf<CRF>-<source\|1080p\|720p\|480p>` 12개 |
| 그 밖의 설정 | preset `medium`, `yuv420p`, 축소 필터 bicubic, 스레드 4개 고정, 오디오는 복사 |

- 이 값들은 README §6.2의 초기 실험값이다. **YouTube 내부 설정이 아니다.**
- 업스케일은 하지 않는다. 목표가 원본의 짧은 변보다 크면 파일을 만들지 않고 `skipped_upscale`로 기록한다. 목표가 원본과 같으면 `source`와 같은 출력이 나온다.
- 긴 변은 비율을 지켜 짝수로 맞춘다. `source`에서 변이 홀수면 1px 내린다.
- 오디오 재인코딩, 프레임률 변경, 반복 인코딩은 다루지 않는다(README §6.2의 별도 실험 축). 이미 압축 파생본인 행은 다시 압축하지 않는다.
- 프로파일 정의는 `training/emulator/profiles.py`에 있다. README §6.2의 예정 경로는 `profiles/` 폴더였지만 12개가 규칙 하나로 만들어져 파일 하나로 뒀다.

### 최종 평가용 프로파일을 고정하는 규칙

- **최종 평가에 남겨 둘 프로파일은 학습을 시작하기 전에 고정한다.** 고정한 목록은 이 문서에 날짜와 함께 적고 커밋한다.
- 남겨 둔 프로파일은 학습, 압축 증강, 모델 선택, 임계값 결정에 쓰지 않는다. dev 분할에도 적용하지 않는다.
- 학습을 시작한 뒤에는 목록을 바꾸지 않는다. 바꿔야 하면 그 사실과 이유를 결과 보고에 적고, 바뀐 조건의 결과를 "미사용 압축 조건"이라고 부르지 않는다.
- **어떤 프로파일을 남길지는 아직 정하지 않았다.** 지금의 12개에는 학습용·평가용 구분이 없다.

## 3. 열화 영상을 만드는 함수

```python
from training.emulator.video import emulate
result = emulate(Path("in.mp4"), "x264-crf28-720p", Path("out_dir"),
                 lineage={"source_recording_id": "...", "split": "dev"})
```

실행하는 명령(인자 리스트로 넘긴다. 셸을 거치지 않는다):

```
ffmpeg -nostdin -hide_banner -loglevel error -n -i <입력>
  -map 0:v:0 -map 0:a? -sn -dn -map_metadata -1 -map_chapters -1
  -vf "scale=w='if(lt(iw,ih),720,-2)':h='if(lt(iw,ih),-2,720)':flags=bicubic" -filter_threads 1
  -c:v libx264 -preset medium -crf 28 -pix_fmt yuv420p -threads 4 -c:a copy
  -fflags +bitexact -flags:v +bitexact -flags:a +bitexact -movflags +faststart -f mp4 <출력>
```

- **출력**: `<out_dir>/<입력 이름>__<프로파일 ID>.mp4`와 그 옆의 `.json` 기록.
- **같은 입력이면 같은 출력**: 스레드 수 고정, bitexact, 컨테이너 메타데이터 제거. 기록에도 시각과 로컬 경로를 넣지 않아 기록 파일까지 같다. 같은 기기·같은 FFmpeg 빌드에서 확인한 것이다. **다른 기기나 다른 FFmpeg/x264 버전에서 같은 바이트가 나오는지는 미검증**이다. 그래서 기록에 FFmpeg 버전을 남긴다.
- **원본 보존**: 입력을 열어 읽기만 한다. 출력 이름이 입력과 달라 덮어쓸 수 없고, 이미 있는 출력도 덮어쓰지 않는다. 임시 파일(`.partial`)에 쓴 뒤 이름을 바꾼다.
- **기록**(README §6.2 "품질 및 재현성"): `profile_id`, 프로파일 설정 전체, `ffmpeg_version`, `ffmpeg_args`, 입력·출력의 sha256과 코덱·해상도·프레임 수·비트레이트·크기, `lineage`(`dataset_id`, `video_id`, `source_recording_id`, `derivation_group_id`, `split`), `status`, `reason`.
- **상태**: `completed`, `skipped_upscale`, `error`. 인코딩이 실패하면 출력 없이 `error`와 이유를 돌려준다. 모르는 값은 `null`이다.
- libx264의 버전은 따로 기록하지 않는다(FFmpeg 버전 줄만 남긴다). x264 빌드 번호 기록은 남은 일이다.

## 4. manifest와 평가 리포트 연결

- 공통 manifest에 선택 열 **`compression_profile_id`**를 넣었다. 빈칸은 다시 압축하지 않은 영상이고 리포트에서는 `original`로 부른다. 이 열이 없는 예전 manifest도 그대로 읽힌다.
- 값은 프로파일 ID다. 형식을 강제하지 않으므로 나중에 다른 출처의 조건 이름도 쓸 수 있다.
- **파생 행**(`training/emulator/pipeline.py`): `video_id`는 `<부모>@<프로파일>`, `parent_video_id`는 부모, `derivation_group_id`는 부모 것(없으면 부모의 `video_id`), `file_hash`는 출력의 sha256이다. 라벨·생성기·유형·인물·원본 계보·**분할**은 부모 것을 그대로 쓴다.
- **분할을 먼저 정하고 압축한다**(README §6.4). 분할이 빈 영상은 압축을 거부한다. 파생 행은 부모와 한 그룹으로 묶이므로, 누가 파생 행의 분할을 바꾸면 기존 누수 검사가 `group_spans_splits`로 막는다.
- **리포트의 `by_compression`**: 조건마다 영상 수, 그룹 수, 진짜·가짜 수, 점수가 있는 수, 그리고 **그 조건의 진짜와 가짜만으로** 계산한 ROC-AUC, TPR, 실제 FPR(그룹 bootstrap 신뢰구간 포함). 임계값은 dev에서 고정한 값을 그대로 쓴다. 조건별로 다시 고르지 않는다. 계산할 수 없는 값은 `null`이다.
- 조건이 둘 이상이면 `overall`과 `by_generator`는 조건을 섞은 값이다. 조건별 값을 기본으로 본다(리포트 `notes`에도 적힌다). 리포트 `schema_version`은 2가 됐다.

```bash
# 분할이 정해진 manifest의 영상에 프로파일을 적용하고, 원본 행 + 파생 행 manifest를 새로 쓴다
python -m training.emulator.pipeline --manifest <m.csv> --media-root <영상 폴더> \
  --profile x264-crf28-720p --profile x264-crf34-480p \
  --out-dir data/research/<파생 폴더> --out-manifest <m-compressed.csv>
```

**주의**: 임계값은 "dev 분할 전체"에서 정한다. dev에 압축 파생 행이 들어 있으면 그 행들도 임계값에 들어간다. dev에 어떤 조건을 넣을지는 학습·평가 설계에서 정해야 하고 아직 정하지 않았다.

## 5. 출력 비교 (본인 촬영 영상 1개)

입력: 위와 같은 파일. HEVC 1920×1080, 30fps, 313프레임, 3,631,959바이트, sha256 `61a0f0607f70…`. 메신저를 거친 파일이라 이미 한 번 다시 압축됐을 수 있다(확인 필요). FFmpeg 8.0.1, Apple M3, 2026-11-14, 1회 측정.

| 프로파일 | 해상도 | 영상 비트레이트 | 크기 | sha256 | 재실행 동일 | 인코딩 시간 |
|---|---|---|---|---|---|---|
| `x264-crf20-source` | 1920×1080 | 5,768 kbps | 7,701,629바이트 | `1f9293ed2a9b…` | 예 | 7.5초 |
| `x264-crf20-1080p` | 1920×1080 | 5,768 kbps | 7,701,629바이트 | `1f9293ed2a9b…` | 예 | 7.8초 |
| `x264-crf20-720p` | 1280×720 | 2,959 kbps | 4,038,703바이트 | `8ef0af70d086…` | 예 | 3.8초 |
| `x264-crf20-480p` | 854×480 | 1,582 kbps | 2,242,880바이트 | `d11d03c0a8e0…` | 예 | 1.9초 |
| `x264-crf28-source` | 1920×1080 | 1,983 kbps | 2,765,386바이트 | `c3fac3663ef5…` | 예 | 5.0초 |
| `x264-crf28-1080p` | 1920×1080 | 1,983 kbps | 2,765,386바이트 | `c3fac3663ef5…` | 예 | 5.0초 |
| `x264-crf28-720p` | 1280×720 | 965 kbps | 1,438,370바이트 | `89304cc7672f…` | 예 | 2.5초 |
| `x264-crf28-480p` | 854×480 | 495 kbps | 824,274바이트 | `1461964e94c3…` | 예 | 1.3초 |
| `x264-crf34-source` | 1920×1080 | 921 kbps | 1,380,682바이트 | `8567aa6bba18…` | 예 | 3.7초 |
| `x264-crf34-1080p` | 1920×1080 | 921 kbps | 1,380,682바이트 | `8567aa6bba18…` | 예 | 3.7초 |
| `x264-crf34-720p` | 1280×720 | 439 kbps | 751,345바이트 | `21b5605f4b90…` | 예 | 1.8초 |
| `x264-crf34-480p` | 854×480 | 218 kbps | 463,085바이트 | `9a196dfd0492…` | 예 | 1.1초 |

- 12개 모두 두 번 실행한 출력과 기록이 같았다.
- 이 영상은 1080p라서 `1080p` 프로파일의 출력이 `source`와 바이트까지 같다. 업스케일로 건너뛴 조합은 없다.
- CRF 20의 원본 해상도 출력은 입력보다 크다(입력이 이미 낮은 비트레이트다).
- `docs/motionphys-spike.md`의 CRF 20/28/34 파일과 크기가 조금 다르다. 그쪽은 오디오를 빼고 스레드와 bitexact를 고정하지 않은 명령이었다. 두 문서의 파일은 같은 파일이 아니다.
- 화질 지표(PSNR, SSIM), 주파수 특성, 모델 출력 변화는 재지 않았다.

결과 파일: `data/research/emulator/profile-report/report.json`, `data/research/emulator/upstream-smoke/summary.json`(Git 제외).

## 6. 테스트

`tests/test_emulator.py`(25개). 영상은 FFmpeg의 합성 무늬, 점수는 가짜 값이다. FFmpeg가 없으면 인코딩 테스트는 건너뛴다.

- 프로파일 12개, 없는 ID 거부, 하드웨어·다른 인코더 거부, 명령이 인자 리스트이고 libx264인지.
- 설정·해시·계보 기록, 로컬 경로가 기록에 없는지, 같은 입력의 출력과 기록이 같은지.
- 축소 비율, 세로 영상의 짧은 변, 업스케일 건너뛰기, 원본이 바뀌지 않는지, 기존 출력 덮어쓰기 거부, 인코딩 실패의 `error` 상태.
- manifest 열 왕복, 예전 manifest 읽기, 파생 행의 분할·계보 상속, 분할이 빈 영상과 반복 압축 거부, 파생 행을 다른 분할로 옮기면 누수 검사 실패.
- 압축 조건별 지표가 조건별로 따로 계산한 값과 같은지, 한쪽 라벨이 없으면 `null`인지, 명령 끝까지(임계값 고정 → 평가 → `by_compression`).

`pytest -q`: 290개 통과, 1개 건너뜀(2026-11-14, conda `trinity`. 건너뛴 것은 LightGBM이 없는 `tests/test_motionphys_train.py`).

## 7. 재현 방법

```bash
# 범용 프로파일 비교 (conda trinity, 저장소 루트)
python scripts/compression_profile_report.py --video data/research/samples/<허가 영상>.mp4

# 원본 코드 동작 확인
git clone https://github.com/truebees-ai/social_emulator research/emulator/upstream
git -C research/emulator/upstream checkout 3e1a39a46c17d0357c0c991663ba878cb25cf25f
python3.11 -m venv research/emulator/.venv
research/emulator/.venv/bin/pip install -r research/emulator/requirements.lock.txt
research/emulator/.venv/bin/python research/emulator/run_upstream_smoke.py --video data/research/samples/<허가 영상>.mp4
```

두 스크립트 모두 출력 폴더가 이미 있으면 덮어쓰지 않고 멈춘다.

## 8. 하지 않은 것과 한계

- 플랫폼 처리본으로 파라미터를 추정하지 않았다. README §13.2의 C4(`social_emulator`)와 C5(플랫폼 처리본)는 할 수 없는 상태다.
- 모델 점수의 변화를 재지 않았다(C1~C3). 학습 데이터와 영상 단위 점수가 생긴 뒤에 한다.
- 같은 영상의 원본과 압축본 점수를 짝지어 비교하는 지표는 넣지 않았다. `by_compression`은 조건별 집합 지표다.
- 오디오 재인코딩, 프레임률 변경, 반복 인코딩, 화질 지표(README §6.2의 `audio.py`, `quality.py`).
- 영상 1개에서만 실행했다. 가변 프레임률, 회전 메타데이터가 있는 영상, mp4에 복사할 수 없는 오디오 코덱은 실제 파일로 확인하지 않았다(**미검증**).
- 최종 평가용 프로파일을 정하지 않았다(위 규칙만 정했다).
