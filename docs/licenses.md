# 라이선스 표

TRINITY가 쓰는 코드·모델 가중치·도구·글꼴·데이터셋의 이용 조건을 한곳에 모은다. 확인일: 2026-11-19. **법률 자문이 아니다.**
근거를 찾지 못한 것은 추측하지 않고 "확인 필요"로 적었다. 항목별 세부 기록은 "자세한 기록" 열의 문서에 있다.

- **확인 상태**: "확인"은 근거 파일이나 공식 페이지의 문구를 직접 읽었다는 뜻이다. 한 칸에 확인한 부분과 확인하지 못한 부분이 섞이면 "확인 필요"로 적고 무엇이 남았는지 쓴다.
- **상업 이용**: 라이선스 문구가 허용·금지하는지만 적었다. TRINITY는 졸업작품(비영리 연구·교육)으로만 쓴다. 아래 "전체 결론"대로 지금 구성으로는 상업 이용을 할 수 없다.
- 로컬 경로 중 `research/*/upstream/`과 `data/`는 Git에서 제외된 곳이다(`.gitignore`). 이런 경로는 이 기기에서 읽었다는 뜻이고, 같은 파일을 공식 URL로도 적었다.

## 코드·가중치·도구

| 항목 | 라이선스 | 근거 | 상업 이용 | 확인 상태 | 자세한 기록 |
|---|---|---|---|---|---|
| WaveRep 코드 | GRIP-UNINA 자체 라이선스(SPDX 아님). "only for informational and nonprofit purposes; any unauthorized use of this software for industrial or profit-oriented activities is expressively prohibited", 원 고지 유지, 결과 공개 시 원저자 인용 | `research/waverep/upstream/LICENSE.md`(Git 제외, `demo/LICENSE.md`와 같은 파일), <https://github.com/grip-unina/WaveRep-SyntheticVideoDetection> 커밋 `0fd6010` | **불가**(영리·산업적 사용 금지) | 확인 | `docs/waverep-license.md` |
| WaveRep 가중치 `weights_dinov2_G4.ckpt` | 가중치에만 적용되는 라이선스를 찾지 못했다. 코드 라이선스가 가중치에도 적용되는지 명시 없음. 그때까지 코드와 같은 조건(비영리·인용)으로 취급 | 출처 <https://www.grip.unina.it/download/prog/WaveRep_SynthVideoDet/weights_dinov2_G4.ckpt>(저장소 `demo/README.md`의 주소), 로컬 `research/waverep/upstream/demo/weights/`(Git 제외) | 확인 필요(코드 조건으로 보면 불가) | 확인 필요 | `docs/waverep-license.md` |
| WaveRep이 첫 실행 때 받는 DINOv2 기반 가중치(timm `vit_base_patch14_reg4_dinov2.lvd142m`) | 모델 카드를 읽지 않았다. 추론 전에 WaveRep 체크포인트로 모두 덮어쓰여 결과에는 쓰이지 않는다 | `docs/waverep-license.md` "데모가 함께 내려받는 것" | 확인 필요 | 확인 필요 | `docs/waverep-license.md` |
| MotionPhys(재구현) | 공개 코드가 없어 논문(arXiv:2608.20770v1) 본문만 보고 `research/motionphys/`에 새로 쓴 코드다. 원저자 코드를 쓰지 않았다. **이 저장소 자체의 라이선스 파일이 없다**(루트에 LICENSE 없음) | `docs/motionphys-spec.md` 머리말("공개 코드가 없다"), 저장소 루트 | 해당 없음(저장소 라이선스 미정, 결정 필요) | 확인 필요(저장소 라이선스 결정) | `docs/motionphys-spec.md` |
| SyncNet 코드(`syncnet-python` 0.2.3) | `MIT AND Apache-2.0`. 원 SyncNet 코드와 저장소 자체 코드는 MIT, MoChaBench에서 온 파일(`syncnet_pipeline.py`, `SyncNetInstance.py`, `SyncNetModel.py`, `detectors/s3fd/*` 등)은 Apache-2.0. 파일별 범위는 NOTICE | `research/syncnet/upstream/LICENSE`·`LICENSE-APACHE`·`NOTICE`(Git 제외), <https://github.com/nawta/SyncNet_py309_313> 커밋 `ab819ba`, `research/syncnet/manifest.json` | 가능(MIT·Apache-2.0 고지 유지 조건) | 확인 | `docs/syncnet-spike.md` "코드·가중치 라이선스" |
| SyncNet 가중치 `syncnet_v2.model` | VGG 페이지 문구: "The model can be used for research purposes under Creative Commons Attribution License."(NOTICE가 인용). 링크 대상은 CC BY 4.0. 코드의 MIT·Apache-2.0은 적용되지 않는다(NOTICE) | <https://www.robots.ox.ac.uk/~vgg/software/lipsync/>, `research/syncnet/upstream/NOTICE` "Model weights", sha256은 `research/syncnet/manifest.json` | 확인 필요("research purposes" 문구와 CC BY의 관계가 불명확) | 확인 필요 | `docs/syncnet-spike.md` |
| S3FD 가중치 `sfd_face.pth` | 원 저자 다운로드 스크립트와 NOTICE가 같은 VGG 페이지의 파일을 가리킨다. VGG의 "model" 문구가 이 파일까지 덮는지, 파일별 라이선스는 찾지 못했다 | <https://www.robots.ox.ac.uk/~vgg/software/lipsync/>, <https://github.com/joonson/syncnet_python/blob/master/download_model.sh>, `research/syncnet/upstream/NOTICE` | 확인 필요 | 확인 필요 | `docs/syncnet-spike.md` |
| MediaPipe Face Landmarker 모델 `face_landmarker.task`(float16) | **Apache License, Version 2.0.** 이 묶음에 딸린 모델 카드 세 개(얼굴 검출 BlazeFace 단거리, Face Mesh V2, Blendshape V2)가 모두 "LICENSED UNDER Apache License, Version 2.0"이라고 적는다. 모델 카드의 사용 범위 밖 항목: "not intended for human life-critical decisions", 특징점은 얼굴 인식을 제공하지 않음 | 안내 페이지 <https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker>(→ developers.google.com 같은 경로로 이동)의 Models 표가 링크한 카드: <https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf>, <https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf>, <https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Short%20Range).pdf>. 파일 sha256은 `configs/gate_models.json`·`configs/motionphys_models.json` | 가능(Apache-2.0 조건) | 확인(모델 카드 문구). 안내 페이지 꼬리말은 이번에 읽지 못함 | `docs/motionphys-spec.md` §7, `docs/gate.md` "받은 모델 파일" |
| (참고) MediaPipe BlazeFace 단거리 `blaze_face_short_range.tflite` — Gate·MotionPhys 후보 B가 따로 쓰는 파일 | Apache License, Version 2.0(위 BlazeFace 모델 카드, 얼굴 검출 안내 페이지 <https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector>의 Models 표가 같은 카드를 링크) | 위 BlazeFace 카드 URL | 가능(Apache-2.0 조건) | 확인(모델 카드 문구) | `docs/motionphys-spec.md` §7 |
| webrtcvad(`webrtcvad-wheels` 2.0.14.post1) | 패키지는 MIT("Copyright (c) 2016 John Wiseman"). 패키지가 담고 있는 WebRTC VAD C 코드의 라이선스 문서는 설치된 패키지에 없다 | `requirements-gate.txt`(고정 버전), 설치된 `webrtcvad_wheels-2.0.14.post1.dist-info/licenses/LICENSE`·`METADATA`(`License: MIT`, conda `trinity`), <https://github.com/daanzu/py-webrtcvad-wheels> | 패키지는 가능(MIT). 포함된 WebRTC 코드는 확인 필요 | 확인 필요(포함된 WebRTC 코드) | 이 문서 |
| FFmpeg(쓰는 빌드: Homebrew 8.0.1, `ffmpeg`·`ffprobe`) | **GPL v3 이상.** `ffmpeg -L`: "under the terms of the GNU General Public License as published by the Free Software Foundation; either version 3 of the License, or (at your option) any later version." 빌드 플래그에 `--enable-gpl --enable-version3`, GPL 라이브러리 `--enable-libx264 --enable-libx265`. `--enable-nonfree`는 없다. 그 밖의 외부 라이브러리 플래그: `--enable-libsvtav1 --enable-libopus --enable-libmp3lame --enable-libdav1d --enable-libvpx --enable-openssl --enable-videotoolbox --enable-audiotoolbox`(VideoToolbox는 빌드에 있지만 TRINITY는 쓰지 않는다, AGENTS.md) | 이 기기에서 `ffmpeg -hide_banner -L`·`ffmpeg -version`(2026-11-19), <https://ffmpeg.org/legal.html> | 가능(GPL v3 조건. TRINITY는 별도 프로세스로 실행만 하고 배포하지 않는다. 배포하게 되면 GPL 의무 확인 필요) | 확인(빌드 라이선스). 개별 외부 라이브러리 라이선스는 확인 필요 | `docs/compression-emulator.md` |
| Montibeller `social_emulator` | CC BY 4.0(저장소 `LICENSE`, GitHub 표시도 같음). 코드에 CC BY를 적용했을 때의 세부 해석(특허·소스 재배포 등)은 확인 필요. **TRINITY 코드에는 들어 있지 않다**(`training/emulator/`는 따로 쓴 코드, 원본은 동작 확인에만 실행) | `research/emulator/upstream/LICENSE`(Git 제외), <https://github.com/truebees-ai/social_emulator> 커밋 `3e1a39a` | 가능(CC BY 4.0, 저작자 표시 조건) | 확인(라이선스 파일). 코드 적용 해석은 확인 필요 | `docs/compression-emulator.md` §1 |
| Flutter 앱 글꼴: Inter Tight(Regular·Bold), Noto Sans KR(Regular·Bold), JetBrains Mono(Regular) | 세 글꼴 모두 SIL Open Font License 1.1. 원문을 앱에 함께 넣었다 | `app/assets/fonts/licenses/OFL-InterTight.txt`·`OFL-NotoSansKR.txt`·`OFL-JetBrainsMono.txt`, `app/pubspec.yaml` `fonts:` | 가능(OFL 1.1: 앱에 넣어 쓰는 것은 허용, 글꼴만 따로 판매 불가, 라이선스 동봉) | 확인 | `docs/design-system.md` |

## 데이터셋

| 데이터셋 | 라이선스·이용 조건 | 근거 | 상업 이용 | 확인 상태 | 자세한 기록 |
|---|---|---|---|---|---|
| DeepSpeak v2 | 라이선스 이름 `deepspeak-v2-0-license`. 카드의 Licensing 절: "Licensing is provided to qualifying academic institutions at no cost.", "Licensing may be provided for a fee to non-academic institutions.", 사용 시 arXiv 2408.05366 인용. **라이선스 본문은 접근 동의 뒤에만 보여 읽지 못했다** | <https://huggingface.co/datasets/faridlab/deepspeak_v2>(2026-11-19 읽음), 접근 요청 양식 <https://forms.gle/4bQCRJdpVQPmgEY2A> | 확인 필요(카드에 허용·금지 문구 없음. 비학술 기관은 유료 라이선스일 수 있다고만 적음) | 확인 필요(본문) | `docs/dataset-access.md` |
| MAVOS-DD | CC BY-NC-SA 4.0. 접근 양식에서 "비상업 용도로만 사용"에 동의. TRINITY는 open-set model 분할만 최종 평가에 쓴다 | <https://huggingface.co/datasets/unibuc-cs/MAVOS-DD>, <https://github.com/CroitoruAlin/MAVOS-DD> README, 논문 arXiv:2505.11109v2 "Ethical considerations" | **불가**(NC) | 확인. 결과 공개 때 동일조건(SA) 의무 범위는 확인 필요 | `docs/dataset-access.md` |
| TalkingHeadBench | HF 라이선스 태그 `mit`. 카드에 MIT 본문은 없고 "Please ensure compliance with the original licenses:"라며 FFHQ·CelebV-HQ·FaceForensics++ 라이선스를 가리킨다(신원 이미지 FFHQ, 구동 신호·오디오 CelebV-HQ, 진짜 영상 CelebV-HQ·FaceForensics++). 원본 세 데이터셋의 라이선스는 읽지 않았다 | <https://huggingface.co/datasets/luchaoqi/TalkingHeadBench>(2026-11-19 읽음), 카드가 링크한 <https://github.com/NVlabs/ffhq-dataset#license>, <https://github.com/CelebV-HQ/CelebV-HQ#license>, <https://github.com/ondyari/FaceForensics#license> | 확인 필요(카드에 문구 없음, 원본 데이터셋 조건에 달림) | 확인 필요 | `docs/dataset-access.md` |
| HiDF | 공식 출처(논문·저장소·데이터셋 페이지)를 찾지 못했다. 웹 검색에서는 제3자 요약 글만 나왔다 | `configs/datasets/hidf.json`(`status: unconfirmed`, 변환 거부) | 확인 필요 | 확인 필요 | `docs/training-pipeline.md` |

## 전체 결론

- **지금 구성으로는 상업 이용을 할 수 없다.** WaveRep 코드가 영리·산업적 사용을 금지하고(확인), MAVOS-DD가 비상업 조건이다(확인). 이 둘만으로도 충분하고, SyncNet·S3FD 가중치와 DeepSpeak v2·TalkingHeadBench는 상업 이용 여부가 확인 필요다.
- 졸업작품 범위(비영리 연구·교육)에서 지켜야 할 것: WaveRep 원 고지 유지와 결과 공개 때 원저자 인용, SyncNet 가중치·데이터셋 출처 표기(CC BY·BY-NC-SA·DeepSpeak 인용), 앱 배포 때 OFL 원문 동봉(이미 함), 가중치·모델 파일·데이터셋 영상을 저장소에 넣거나 재배포하지 않음(AGENTS.md).
- 이번에 새로 확인한 것: MediaPipe 모델 카드의 Apache-2.0 문구(전에는 확인 필요), FFmpeg 빌드 라이선스, webrtcvad 패키지 라이선스, DeepSpeak v2·TalkingHeadBench 카드의 라이선스 문구.

## 남은 확인 (확인 필요 목록)

1. WaveRep 가중치와 DINOv2 기반 가중치의 별도 조건.
2. 이 저장소(MotionPhys 재구현 포함) 자체의 라이선스 결정.
3. SyncNet·S3FD 가중치: VGG "research purposes" 문구와 CC BY의 관계, S3FD 파일별 범위.
4. webrtcvad 패키지에 포함된 WebRTC C 코드의 라이선스(설치본에 문서 없음).
5. FFmpeg 빌드에 들어간 개별 외부 라이브러리의 라이선스(빌드 전체는 GPL v3 이상).
6. DeepSpeak v2 라이선스 본문(접근 승인 뒤), TalkingHeadBench가 가리키는 FFHQ·CelebV-HQ·FaceForensics++ 조건, HiDF 공식 출처.
7. MAVOS-DD 결과 공개 때 BY-NC-SA 동일조건 의무 범위.
8. 표에 없는 pip 의존성(torch, timm, opencv, lightgbm, mediapipe 패키지 등)의 개별 라이선스는 이번에 점검하지 않았다.
