# SyncNet CPU 재현 스파이크 — 조각 1/3

작성일: 2026-11-15. README §5.3·§12.1에 따른 실행 가능성 확인이다.
지금 샘플에는 발화가 없다. 동기화 품질이나 진위를 판단하지 않으며,
샘플의 오프셋·LSE-C·LSE-D·얼굴별 지표 숫자를 이 문서에 기록하지 않는다.
API·Worker·Flutter 통합이나 오프셋 실험은 이번 조각에 포함하지 않는다.

## 원본과 고정 환경

- 구현: [nawta/SyncNet_py309_313](https://github.com/nawta/SyncNet_py309_313).
- 고정 커밋: `ab819ba7114da3dbac1bf5f82bc0b776daf9acd3`.
- 패키지 버전: `syncnet-python 0.2.3`.
- 원본은 `research/syncnet/upstream/`에 sparse checkout했다. 설치 대상 `syncnet_python/`과
  루트의 라이선스/메타데이터를 받고, 제공 예제 영상과 가중치 디렉터리는 체크아웃하지 않았다.
  원본 코드는 수정하지 않았다. 원본 저장소의 Git diff로 다시 확인한다.
- 환경: `research/syncnet/.venv`, Python **3.11.18**, macOS **arm64**.
- CPU를 명시적으로 사용한다. 서버 `trinity` 환경에 torch나 SyncNet을 추가하지 않는다.
- 외부 실행 도구: FFmpeg **8.0.1**. upstream의 전처리를 그대로 사용한다.
- 출처·커밋·가중치 해시: `research/syncnet/manifest.json`.
- CPU 스모크 성공 후 버전 고정 파일: `research/syncnet/requirements.lock.txt`.

## 가중치 공식 출처와 해시

다운로드 전에 아래 경로를 대조했다.

1. [Oxford VGG의 원 저자 프로젝트 페이지](https://www.robots.ox.ac.uk/~vgg/software/lipsync/)가
   Chung·Zisserman의 SyncNet과 원 저자 Python 저장소를 연결한다.
2. [원 저자 download_model.sh](https://github.com/joonson/syncnet_python/blob/master/download_model.sh)가
   SyncNet과 S3FD 파일을 VGG 서버에서 받도록 지정한다.
3. [고정 후보 구현 README](https://github.com/nawta/SyncNet_py309_313/blob/ab819ba7114da3dbac1bf5f82bc0b776daf9acd3/README.md)도
   같은 HTTPS 주소를 안내한다. 두 URL의 HEAD 응답을 확인한 뒤 VGG에서 직접 받았다.
   원 저자 스크립트의 SyncNet URL은 HTTP였지만 같은 VGG 경로의 HTTPS를 사용했다.

| 파일 | 공식 다운로드 주소 | 받은 파일의 SHA-256 |
|---|---|---|
| `syncnet_v2.model` | [Oxford VGG](https://www.robots.ox.ac.uk/~vgg/software/lipsync/data/syncnet_v2.model) | `961e8696f888fce4f3f3a6c3d5b3267cf5b343100b238e79b2659bff2c605442` |
| `sfd_face.pth` | [Oxford VGG](https://www.robots.ox.ac.uk/~vgg/software/lipsync/data/sfd_face.pth) | `d54a87c2b7543b64729c9a25eafd188da15fd3f6e02f0ecec76ae1b30d86c491` |

저장 위치는 `data/models/syncnet/`이며 Git 제외다. 해시는 이 세션에서 받은 파일을 계산한 값이다.
후보 저장소 README의 축약 해시와 앞뒤가 일치한다. 실행기는 전체 해시 불일치 시 실행을 거부한다.

## 코드·가중치 라이선스

라이선스의 확인된 고지와 남은 확인 사항을 구분한다. 코드 라이선스를 가중치에 적용하지 않는다.

| 대상 | 확인한 고지 | 이번 조각의 취급 |
|---|---|---|
| 원 SyncNet 계열 및 후보 저장소 자체 코드 | [LICENSE](https://github.com/nawta/SyncNet_py309_313/blob/ab819ba7114da3dbac1bf5f82bc0b776daf9acd3/LICENSE): MIT | 원본을 수정·재배포하지 않고 로컬에서 설치했다. 저작권·라이선스 고지를 유지한다. |
| MoChaBench에서 가져온 pipeline/model/detector 파일 | [NOTICE](https://github.com/nawta/SyncNet_py309_313/blob/ab819ba7114da3dbac1bf5f82bc0b776daf9acd3/NOTICE), [LICENSE-APACHE](https://github.com/nawta/SyncNet_py309_313/blob/ab819ba7114da3dbac1bf5f82bc0b776daf9acd3/LICENSE-APACHE): Apache-2.0 | 파일별 적용 범위를 NOTICE로 확인했다. 코드 패키지 전체 표기는 `MIT AND Apache-2.0`이다. |
| SyncNet 가중치 | VGG 페이지는 연구 목적 사용과 Creative Commons Attribution을 안내한다. 링크 대상은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)이다. | 연구용 CPU 재현에만 사용했다. 코드의 MIT/Apache-2.0 고지는 가중치에 적용되지 않는다. |
| S3FD 가중치 | 원 저자 다운로드 스크립트와 후보 NOTICE가 같은 VGG 파일을 지목한다. 파일별 독립 라이선스 고지는 확인하지 못했다. | 공식 출처는 확인했다. VGG의 “model” 고지가 이 파일까지 포함하는 범위는 **확인 필요**다. |

**별도 확인 필요:** VGG 페이지의 연구 목적 문구와 링크된 CC BY 4.0 조건을 함께 고려할 때
가중치의 상업 이용·재배포에 적용되는 정확한 범위는 확인 필요다. 이 문서는 상업 이용이나
재배포 허용을 단정하지 않는다. 사용자의 승인에 따라 불명확성을 기록하고 연구 재현을 계속했다.
원본 코드·가중치·가상환경은 이 프로젝트 Git에 넣지 않는다.

연구에서 사용할 때 원 논문을 인용한다: Chung & Zisserman, *Out of time: automated lip sync in the wild*,
Workshop on Multi-view Lip-reading, ACCV, 2016. 후보 구현의 MoChaBench 출처는 NOTICE를 보존한다.

## 재현 방법

저장소 루트에서 실행한다. 가중치 다운로드 URL의 공식 출처가 달라지거나 확인되지 않으면
대체 미러에서 받지 말고 중단한다.

```bash
# Python 3.11로 별도 환경 생성
/opt/anaconda3/envs/trinity/bin/python -m venv research/syncnet/.venv

# 원본 소스는 Git 제외 경로에서 고정
# 이미 upstream이 있으면 clone을 반복하지 않고 SHA·diff부터 확인한다.
git clone --filter=blob:none --sparse https://github.com/nawta/SyncNet_py309_313.git research/syncnet/upstream
git -C research/syncnet/upstream sparse-checkout set syncnet_python
git -C research/syncnet/upstream checkout --detach ab819ba7114da3dbac1bf5f82bc0b776daf9acd3

# 버전 고정 의존성 설치. 아래 lockfile에는 SyncNet 소스의 고정 Git SHA도 포함한다.
research/syncnet/.venv/bin/python -m pip install -r research/syncnet/requirements.lock.txt
research/syncnet/.venv/bin/python -m pip check

mkdir -p data/models/syncnet
curl --fail --show-error --silent --proto '=https' --output data/models/syncnet/syncnet_v2.model https://www.robots.ox.ac.uk/~vgg/software/lipsync/data/syncnet_v2.model
curl --fail --show-error --silent --proto '=https' --output data/models/syncnet/sfd_face.pth https://www.robots.ox.ac.uk/~vgg/software/lipsync/data/sfd_face.pth
shasum -a 256 data/models/syncnet/syncnet_v2.model data/models/syncnet/sfd_face.pth
```

초기 설치는 위 고정 커밋의 로컬 checkout에서 `pip install ./research/syncnet/upstream`으로 했다.
lockfile의 Git 참조는 같은 커밋을 다른 컴퓨터에서도 설치하기 위한 것이다.
Python·FFmpeg는 pip lockfile 대상이 아니므로 위 버전과 별도로 맞춘다.

샘플의 권한 근거는 `docs/media-access.md` §3이다. 이번에는 본인 촬영의 기존 발화 없는 파일을
Git 밖 레지스트리에 연결했다. 다른 영상이나 upstream 예제 영상은 사용하지 않는다.

```bash
# 기존 허가 샘플만 연구 레지스트리에 등록한다. 서비스 설정을 바꾸지 않는다.
python - <<'PY'
import json
from pathlib import Path
sample = Path('data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4')
assert sample.is_file(), '허가 샘플 없음: 미검증'
folder = Path('data/research/syncnet-spike')
folder.mkdir(parents=True, exist_ok=True)
(folder / 'authorized_media.json').write_text(json.dumps({'authorized_media': [
    {'youtube_video_id': 'TRINITYtest', 'local_path': sample.name,
     'provenance': 'registered_authorized_source'},
]}))
PY

research/syncnet/.venv/bin/python research/syncnet/run_spike.py \
  --registry data/research/syncnet-spike/authorized_media.json \
  --media-root data/research/samples --video-id TRINITYtest
```

실행기는 `AuthorizedMediaRegistry` 확인과 가중치 해시 대조 후 허가 파일을 임시 작업 폴더에 복사한다.
원본 CLI에 인자 리스트와 `--device cpu`를 전달한다. 원본 stdout/stderr는 버리고,
CLI 반환 코드뿐 아니라 결과 JSON의 성공 상태·얼굴 트랙 존재·산출 형식도 확인한다.
빈 트랙의 기본 출력은 성공으로 세지 않는다. 지표 해석이나 임계값 판단은 하지 않는다.
최종 출력은 **“실행 성공” 또는 “실행 실패”**뿐이다.
처리 후 임시 영상·오디오·얼굴 crop·결과 JSON을 `data/runtime/`의 해당 임시 폴더와 함께 삭제한다.

## 실행 결과와 한계

- CPU 스모크: **실행 성공**. 임시 폴더 정리 확인. 출력 숫자는 기록하지 않았다.
- 실제 말하는 영상의 동기화 검증, 인위적 오프셋, 다중 발화자, 압축 영향, 정확도·위조 탐지 기여는 **미검증**.
- API/Worker 연결은 하지 않았다. SyncNet은 동기화 보조 지표이며 진위 분류기가 아니다.
- `.gitignore`의 `.venv/`, `research/*/upstream/`, `data/` 규칙으로 가상환경·원본·가중치를 제외한다.

검증 명령과 결과:

```bash
/opt/anaconda3/envs/trinity/bin/python -m pytest -q tests/test_syncnet_spike.py
/opt/anaconda3/envs/trinity/bin/python -m pytest -q
research/syncnet/.venv/bin/python -m pip check
research/syncnet/.venv/bin/python -m pip install --dry-run -r research/syncnet/requirements.lock.txt
git -C research/syncnet/upstream diff --exit-code
git check-ignore -v research/syncnet/.venv/pyvenv.cfg research/syncnet/upstream/README.md data/models/syncnet/syncnet_v2.model data/models/syncnet/sfd_face.pth
git diff --check
```

- 새 테스트 **10 passed**: 비정상/빈 결과 거부, 허가되지 않은 미디어 거부,
  성공·실패에서 출력 제한과 임시 파일 정리, 가중치 해시 불일치 거부.
- 전체 **447 passed, 2 skipped**. 기존 LightGBM 없음·발화 샘플 조건에 따른 건너뜀과
  기존 httpx 폐기 예정 경고가 남아 있다.
- `pip check` 통과. lockfile dry-run에서 고정 Git SHA와 설치된 버전의 일치를 확인했다.
  **새 가상환경에 lockfile 전체를 재설치하는 검증은 미실행**이다.
- upstream diff 없음, Git 제외 규칙 적용 확인, `git diff --check` 통과.
- Flutter 코드는 바꾸지 않았으며 이번 조각의 Flutter 테스트는 미실행이다.
- 독립 리뷰는 모델 사용량 제한으로 미완료다. 직접 코드 검토를 수행했다.
