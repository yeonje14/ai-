# WaveRep 단독 추론 스파이크 결과

README §14.1 백로그 5번(P0-4). 실행일: 2026-11-12.

> **이 문서는 실행 가능성 확인이다. 성능 검증이 아니다.**
> 아래 점수는 모델의 원시 logit이며 AI 생성 확률도, 진위 판정도 아니다.
> 영상 1개로는 정확도·임계값·오탐률에 대해 아무것도 말할 수 없다.
> 원본 데모는 "LLR>0이면 합성"이라는 기준과 `prob` 값을 출력하지만, TRINITY는 검증된 임계값이 없으므로 이 기준을 쓰지 않는다.

## 결론

- 공개 체크포인트(G4)로 **CPU 추론 성공**, 같은 입력으로 **MPS 추론 성공**. 원본 코드를 수정하지 않았다.
- CPU 2회 실행의 프레임 점수는 **완전히 같다**(313프레임 최대 절대차 0.0). 반복 가능하다.
- CPU와 MPS의 프레임 점수 차이는 최대 0.00019, 평균 0.000037이다.
- 원본 코드에서 CUDA 전용 연산은 발견되지 않았다. `--device` 기본값이 `cuda:0`이라 장치를 반드시 넘겨야 할 뿐이다.
- MPS에서 CPU fallback 경고는 나오지 않았다(4프레임 실행의 전체 stderr 확인).

## 입력

| 항목 | 값 |
|---|---|
| 파일 | `data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4` (Git 제외) |
| 권한 근거 | 저장소 소유자가 **직접 촬영한 본인 영상**이다. 본인 얼굴과 음성만 있고 제3자는 없다 (2026-11-12 본인 확인). |
| 형식 | HEVC 1920×1080, 30fps, 313프레임, 10.43초, 3,631,959바이트 (ffprobe) |

영상 내용과 프레임 이미지는 이 문서에 넣지 않는다. 이 영상은 학습 데이터로 쓰지 않는다.

## 환경

| 항목 | 값 |
|---|---|
| 기기 | Apple M3, 메모리 16GB, macOS 27.0.1 arm64 |
| Python | 3.11.18 (`research/waverep/.venv`) |
| 주요 패키지 | torch 2.15.0, torchvision 0.29.2, timm 1.0.31, opencv-python 5.0.0.93, numpy 2.4.6, pandas 3.1.1, scipy 1.17.1, pillow 13.0.0 |
| lockfile | `research/waverep/requirements.lock.txt` (`pip freeze`) |
| 원본 코드 | `grip-unina/WaveRep-SyntheticVideoDetection` 커밋 `0fd6010`, `demo/main_avideo.py` |
| 가중치 | `weights_dinov2_G4.ckpt`, md5 `8bf19e6f68a92bed600dd97fbed3f2cd` (공개값과 일치) |
| 장치 점검 | `docs/env-check-waverep.md` (PyTorch CPU·MPS 행렬곱 스모크 정상) |

데모의 처리 방식(원본 그대로): 프레임마다 가운데 504×504 crop → ImageNet 정규화 → `vit_base_patch14_reg4_dinov2` (출력 1개) → 프레임별 logit. 리사이즈는 없다. 배치 크기 1.

## 가중치 키 대조 (missing / unexpected keys)

`research/waverep/check_state_dict.py`로 확인했다. 데모와 같은 아키텍처·같은 키 필터를 쓰고 `strict=False`로 불러 결과를 본다.

| 항목 | 결과 |
|---|---|
| 모델 state_dict 키 수 | 177 |
| 체크포인트에서 쓰는 키 수 | 177 |
| missing keys (모델에 있는데 체크포인트에 없음) | **0개** |
| unexpected keys (체크포인트에 있는데 모델에 없음) | **0개** |
| 모양(shape) 불일치 | **0개** |
| 데모의 `model` 접두사 필터로 버려지는 키 | 0개 |
| 체크포인트 구조 | `state_dict` 래퍼 없이 평평한 state_dict |

- 원본 데모는 `load_state_dict`를 `strict=True`(기본값)로 호출하므로, 데모가 예외 없이 끝난 것도 같은 사실을 뒷받침한다.
- 177개 키가 모두 체크포인트 값으로 채워지므로, `pretrained=True`로 받은 DINOv2 기반 값은 추론에 남지 않는다.
- PyTorch 2.15의 `torch.load` 기본값(`weights_only=True`)에서도 문제없이 열렸다.

## 실행 결과

명령 (저장소 루트에서):

```bash
research/waverep/.venv/bin/python research/waverep/run_spike.py \
  --video data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4 --device cpu --tag cpu-1
# --device mps 는 PYTORCH_ENABLE_MPS_FALLBACK=1 을 자동으로 설정한다. --limit N 으로 앞 N프레임만.
```

| 실행 | 장치 | 프레임 | 전체 시간(초) | 추론 루프 속도 | 최대 RSS | peak memory footprint | 종료 코드 |
|---|---|---|---|---|---|---|---|
| cpu-smoke | cpu | 8 (`--limit 8`) | 227.75 ※ | 2.30 it/s | 1,128,185,856 B (1.05 GiB) | 1,027,491,976 B (0.96 GiB) | 0 |
| cpu-1 | cpu | 313 | 142.04 | 2.28 it/s | 1,087,111,168 B (1.01 GiB) | 1,011,156,768 B (0.94 GiB) | 0 |
| cpu-2 | cpu | 313 | 190.22 | 1.69 it/s | 1,087,782,912 B (1.01 GiB) | 1,007,814,456 B (0.94 GiB) | 0 |
| mps-1 | mps | 313 | 121.67 | 2.69 it/s | 1,087,815,680 B (1.01 GiB) | 1,406,224,304 B (1.31 GiB) | 0 |

- 전체 시간은 프로세스 시작부터 종료까지다(모델 생성·가중치 로드·디코딩 포함). 추론 루프 속도는 tqdm의 마지막 평균값이다.
- ※ cpu-smoke의 227초는 대부분 첫 실행 때 DINOv2 기반 가중치(346MB)를 Hugging Face Hub에서 받은 시간이다. 추론 자체는 약 3초였다.
- cpu-1과 cpu-2의 시간 차이(142초 대 190초)의 원인은 확인하지 않았다. 다른 프로세스의 부하나 발열 영향일 수 있으나 **확인 필요.** 실행 시간은 이 정도 편차가 있는 값으로 읽어야 한다.
- MPS가 CPU보다 크게 빠르지 않았다. 원인은 측정하지 않았다(**확인 필요**). 배치 크기 1, 프레임마다 HEVC 1080p 디코딩과 PIL 변환을 CPU에서 하는 구조가 병목일 가능성이 있다. 1회 측정이므로 속도 비교의 근거로 쓰지 않는다.

### 프레임 점수 (원시 logit, 해석하지 않음)

| 실행 | 프레임 | 평균 | 중앙값 | 최소 | 최대 | 표준편차 |
|---|---|---|---|---|---|---|
| cpu-smoke | 8 | -3.832551 | -3.999351 | -5.001529 | -1.828578 | 0.977564 |
| cpu-1 | 313 | -1.185915 | -1.437580 | -7.278983 | 8.076391 | 3.074181 |
| cpu-2 | 313 | -1.185915 | -1.437580 | -7.278983 | 8.076391 | 3.074181 |
| mps-1 | 313 | -1.185885 | -1.437563 | -7.278990 | 8.076406 | 3.074192 |

- 프레임별 점수 CSV는 `data/research/waverep-spike/<tag>.csv`, 실행 요약은 `<tag>.json`에 있다(Git 제외).
- cpu-1 대 cpu-2: 313프레임 최대 절대차 **0.0**.
- cpu-1 대 mps-1: 최대 절대차 **0.000187**, 평균 절대차 **0.0000372**, 0을 기준으로 부호가 달라진 프레임 0개.
- 관찰(해석 아님): 프레임 간 점수 폭이 넓다(-7.28 ~ 8.08). 본인이 촬영한 영상 하나에서도 프레임별 값이 0의 양쪽에 걸쳐 있으므로, 프레임 하나나 영상 하나의 값으로 무언가를 판단할 수 없다는 점만 기록한다. 집계 방법과 임계값은 백로그 8번(고정 평가 파이프라인) 이후에 개발 검증 분할로 정한다.

## 메모리 측정 방법과 한계

- `/usr/bin/time -l`로 추론 프로세스 하나를 감싸 두 값을 읽었다: `maximum resident set size`(최대 RSS)와 `peak memory footprint`.
- CPU 실행은 두 값이 비슷하다(약 1.0 GiB).
- MPS 실행은 최대 RSS는 CPU와 같고 peak memory footprint만 약 0.37 GiB 더 크다. footprint가 RSS에 잡히지 않는 GPU(Metal) 쪽 할당을 일부 반영하는 것으로 보이지만, **GPU 할당 전부를 포함하는지는 확인 필요**다. 따라서 MPS의 실제 최대 메모리는 1.31 GiB **이상**이라고만 말할 수 있다.
- 확인하려면 프로세스 안에서 `torch.mps.driver_allocated_memory()`를 주기적으로 읽어 비교해야 한다. 원본 코드를 수정하지 않는 범위를 벗어나므로 이번에는 하지 않았다(백로그 7번 어댑터에서 측정 가능).
- 모두 1회(또는 2회) 측정이고, 다른 프로세스가 떠 있는 상태였다.

## 실패와 대안

이번 실행에서 실패는 없었다. 확인한 것과, 앞으로 실패할 때의 대안은 다음과 같다.

| 상황 | 이번 결과 | 대안 |
|---|---|---|
| `--device` 미지정 | 원본 기본값이 `cuda:0`이라 이 기기에서는 실패한다(실행하지 않음, 코드로 확인) | 항상 `--device cpu` 또는 `mps`를 넘긴다. `run_spike.py`는 `cpu`·`mps`만 받는다 |
| MPS 미지원 연산 | 경고·오류 없음 | `PYTORCH_ENABLE_MPS_FALLBACK=1`(이미 설정), 그래도 실패하면 CPU로 대체 |
| MPS 사용 불가 | 해당 없음 | CPU로 대체. 이 영상 기준 CPU도 약 2 it/s로 동작한다 |
| `torch.load` `weights_only` 오류 | 발생하지 않음 | 발생하면 torch 버전을 낮추는 방안을 먼저 검토한다(`torch>=2.0.1`이 원본 요구사항). 출처가 확인된 파일(md5 일치)에 한해서만 `weights_only=False`를 검토한다 |
| 의존성 충돌 | 없음. 최신 버전 조합으로 동작 | `requirements.lock.txt`의 버전으로 재설치 |
| Hugging Face Hub 접근 불가 | 첫 실행 때 받음. 이후는 캐시 사용 | 캐시(`~/.cache/huggingface/hub/`)가 있으면 오프라인으로 동작한다. 캐시 없이 오프라인이면 원본 데모는 실패한다(`pretrained=True`). 어댑터에서는 `pretrained=False`로 바꿀 수 있다(키 177개가 모두 덮어쓰이므로 결과는 같아야 하나 **확인 필요**) |
| 가중치 다운로드 속도 | `grip.unina.it`에서 346MB에 약 57분 걸림 | 기다린다. 미러를 찾아 우회하지 않는다 |

## 실행하지 않은 것

- `weights_dinov2_G1.ckpt`, `main_directory.py`, `main_power_spectrum.py`.
- 얼굴 ROI crop, 발화 구간 선택, 압축 조건, 다른 해상도·세로 영상·504px보다 작은 영상. 가운데 crop만 쓰는 원본 전처리가 이런 입력에서 어떻게 동작하는지는 **확인 필요.**
- 합성·조작 영상에 대한 실행. 따라서 점수가 진짜와 가짜를 구분하는지는 전혀 확인하지 않았다.

## 재현 방법

```bash
# 1) 환경 (저장소 루트)
/opt/anaconda3/envs/trinity/bin/python3.11 -m venv research/waverep/.venv
research/waverep/.venv/bin/python -m pip install -r research/waverep/requirements.lock.txt

# 2) 원본 코드와 가중치 (Git 제외 경로)
git clone https://github.com/grip-unina/WaveRep-SyntheticVideoDetection research/waverep/upstream
git -C research/waverep/upstream checkout 0fd6010759c14b572b7842a28fa9f85fe1ddd2fd
mkdir -p research/waverep/upstream/demo/weights
curl -fL -o research/waverep/upstream/demo/weights/weights_dinov2_G4.ckpt \
  https://www.grip.unina.it/download/prog/WaveRep_SynthVideoDet/weights_dinov2_G4.ckpt
md5 research/waverep/upstream/demo/weights/weights_dinov2_G4.ckpt   # 8bf19e6f68a92bed600dd97fbed3f2cd

# 3) 점검과 실행
research/waverep/.venv/bin/python scripts/check_env.py --output docs/env-check-waverep.md
research/waverep/.venv/bin/python research/waverep/check_state_dict.py
research/waverep/.venv/bin/python research/waverep/run_spike.py --video <허가 영상> --device cpu --tag cpu-1
research/waverep/.venv/bin/python research/waverep/run_spike.py --video <허가 영상> --device mps --tag mps-1
```

이용 조건은 `docs/waverep-license.md`를 본다.
