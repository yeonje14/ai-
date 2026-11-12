# WaveRep 코드·가중치 이용 조건

README §14.1 백로그 2번("저장소/가중치 이용 조건 점검")과 5번을 위한 기록이다.
확인일: 2026-11-12. 법률 자문이 아니다. 아래 "확인 필요" 항목은 추측하지 않고 비워 두었다.

## 대상

| 항목 | 값 |
|---|---|
| 저장소 | `grip-unina/WaveRep-SyntheticVideoDetection` (GitHub) |
| 확인한 커밋 | `0fd6010759c14b572b7842a28fa9f85fe1ddd2fd` |
| 논문 | Corvi et al., *Seeing What Matters* (NeurIPS 2025, arXiv 2506.16802) |
| 로컬 위치 | `research/waverep/upstream/` (Git 제외, 수정하지 않음) |

## 코드 라이선스

- 저장소 루트 `LICENSE.md`와 `demo/LICENSE.md`는 바이트 단위로 같은 파일이다(`cmp` 확인).
- 표준(SPDX) 라이선스가 아니라 GRIP-UNINA(나폴리 페데리코 2세 대학 영상처리 연구 그룹) 자체 라이선스다.
- 핵심 조항 (원문 인용):
  - "Reproduction, modification, and usage of the software covered by this license is allowed free of charge provided that:"
  - "(i) this software should be used, reproduced and modified only for informational and nonprofit purposes; any unauthorized use of this software for industrial or profit-oriented activities is expressively prohibited; and"
  - "(ii) any reproduction or modification retains all original notices including proprietary or copyright notices; and"
  - "(iii) reference to the original authors is given whenever results, which arise from the use of this software or any modification of it, are made public."
  - "No other use of the materials and of any information incorporated thereto is hereby authorized."
  - "This software is provided 'as-is', without any express or implied warranty."

### TRINITY에 주는 의미

- 비영리·정보 목적만 허용된다. 영리·산업적 사용은 금지다. 졸업작품(비영리 연구·교육) 범위에서만 쓴다.
- 복제·수정본에는 원 고지를 유지해야 한다. 지금은 원본을 Git에 넣지 않고 clone만 한다. 나중에 코드를 저장소에 포함하거나 수정하면(백로그 7번 어댑터 등) 원 `LICENSE.md`와 고지를 함께 둔다.
- 결과를 공개(보고서·발표·시연)할 때 원저자를 인용한다.

## WaveRep 가중치

| 항목 | 값 |
|---|---|
| 파일 | `weights_dinov2_G4.ckpt` (4개 생성기로 학습한 모델, 데모 기본값) |
| 출처 | `https://www.grip.unina.it/download/prog/WaveRep_SynthVideoDet/weights_dinov2_G4.ckpt` (demo/README.md에 적힌 주소) |
| 크기 | 346,163,178 바이트 |
| md5 | `8bf19e6f68a92bed600dd97fbed3f2cd` — demo/README.md의 공개값과 일치 |
| sha256 | `50d639049d928986ba7d69861a4fe4f3e7afbba1843e3e089cdf6b4748f53d5b` |
| 로컬 위치 | `research/waverep/upstream/demo/weights/` (Git 제외) |

- `weights_dinov2_G1.ckpt`(단일 생성기 모델)는 받지 않았다.
- **확인 필요:** 가중치에만 적용되는 별도 라이선스·이용 조건은 저장소와 demo/README.md에서 찾지 못했다. 코드 라이선스가 가중치에도 적용되는지 명시돼 있지 않다. 확인 전까지 코드와 같은 조건(비영리, 인용)으로 취급하고, 가중치를 재배포하거나 Git에 넣지 않는다.
- **확인 필요:** 가중치 학습에 쓰인 데이터의 이용 조건이 가중치 사용에 제약을 주는지.

## 데모가 함께 내려받는 것: DINOv2 기반 가중치

- `demo/utils.py`의 `timm.create_model('vit_base_patch14_reg4_dinov2.lvd142m', pretrained=True, ...)` 때문에 첫 실행 때 Hugging Face Hub의 `timm/vit_base_patch14_reg4_dinov2.lvd142m`에서 `model.safetensors`(346,344,168 바이트, 리비전 `3b06466a5548c52b8b98822e1390987695fcbf82`)를 `~/.cache/huggingface/hub/`에 받는다. 저장소 밖이라 Git에 들어가지 않는다.
- 이 값들은 곧바로 WaveRep 체크포인트로 덮어쓰인다(177개 키 전부, `docs/waverep-spike.md` 참고). 즉 추론 결과에는 쓰이지 않지만 내려받기는 한다.
- **확인 필요:** 이 timm 모델과 원본 DINOv2 가중치의 라이선스. 모델 카드를 직접 확인하지 않았다.

## 그 밖의 의존성

`research/waverep/requirements.lock.txt`에 고정한 PyPI 패키지(torch, timm, opencv-python 등)의 개별 라이선스는 점검하지 않았다. **확인 필요.**

## 저장소에 포함된 다른 가중치

`demo/zang_1.th`(2.3MB)는 `denoiser.py`·`main_power_spectrum.py`(파워 스펙트럼 계산)용으로 보이며 이번 스파이크에서는 쓰지 않았다. 출처와 조건은 **확인 필요.**
