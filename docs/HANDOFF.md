# HANDOFF

## Seamless 분할 예약과 첫 쌍 확인 (2026-11-25, 브랜치 `research/seamless-pilot`)

- **한 일 — 분할 예약.** 계획 §2를 구현했다(`scripts/seamless_reserve.py`, 기록 `docs/seamless-reservation.md`).
  - 미디어를 받기 전에 커밋 `c6c67db`를 push했다.
  - 공식 filelist blob `e759e6d0`(공식 main `b61b032`과 같음), 시드 20261125, 기관 층화로 내부 test 200, dev 100, 파일럿 10쌍을 예약했다. 부족분은 없다. `reservation.csv` SHA-256은 `2cd2ddc8…`이다.
  - P 코드가 여러 기관에 나타나 신원을 구별할 수 없는 대화 21,907개, 공식 dev·test와 코드가 겹치는 대화 2,821개, 접미사 ID 154개는 예약에서 뺐다. 예약 후보는 23,003개다.
  - 예약된 참가자의 improvised train 행 2,120개는 앞으로 어떤 학습에도 넣지 않는다.
- **한 일 — 첫 쌍.** 계획 §3을 구현했다(`docs/seamless-first-pair.md`).
  - 공식 패키지를 별도 venv `data/research/seamless/.venv`에 설치하고, 공식 S3 방법으로 pilot#0 두 ID만 받았다. 보호 래퍼는 `research/seamless/fetch_pilot.py`, 잠금 파일은 `research/seamless/requirements.lock.txt`다.
  - 원본은 **2160×3840 세로 영상이고 MP4에 자체 AAC 오디오가 있다**. WAV는 MP4 오디오와 길이가 같고 +5~9ms 차이다.
  - A(얼굴 대상): Gate 117.6초(제한 120초), 적합 구간 68.7초, 얼굴 높이 약 500px.
    - WaveRep: `completed`
    - MotionPhys: `error` / `timeout`(300초)
    - SyncNet: `insufficient_input` / `tracking_failed`(959초). 13개 구간 중 1개에 트랙이 없었다. 오프셋 +4~5프레임은 본인 촬영 영상과 비슷하다.
  - B: Gate `gate_timeout`, 서비스 결과는 `analysis_unavailable`.
  - 실제 조건 MKV(영상 복사 + WAV 한 트랙)는 첫 쌍 확인용이다. 10쌍 단계에서는 실제와 합성을 같은 최종 인코딩으로 맞춘다.
- **디스크.** `data/research/seamless`는 2.3GB(venv 1.4GB, 미디어 895MB)이고, 작업 폴더는 최대 660MB였다가 지웠다. 여유 공간은 31GiB에서 27GiB로 줄었다.
- **실행 방법**(저장소 루트)
  - 예약: `conda activate trinity && python scripts/seamless_reserve.py`. 입력은 공식 저장소를 `data/research/seamless/src/seamless_interaction`에 clone한 것이다.
  - 다운로드: `data/research/seamless/.venv/bin/python -I research/seamless/fetch_pilot.py --order 0`
  - 확인: `python scripts/seamless_first_pair.py files`, `python scripts/seamless_first_pair.py run --who A|B`
- **남은 일 / 막힌 점**
  - 원본 재생 사람 확인: 육안으로 뚜렷한 입·소리 어긋남 없음, 정밀 판정 불가(2026-11-25 사용자).
  - 4K 세로 320초에서 Gate와 MotionPhys가 제한에 걸린다. 10쌍 전에 구간 자르기, 최종 인코딩 해상도, 측정 전용 제한 가운데 무엇을 할지 정해야 한다. 서비스 제한을 바꾸려면 §15.3 결정 기록이 먼저다.
  - MuseTalk 합성은 지도교수 확인 대기다.
  - §15.3 결정 6 변경은 PR 본문에 제안 문안만 두었다. DESIGN.md는 바꾸지 않았다.
  - `docs/deepspeak-fallback-review.md`는 여전히 커밋되지 않았다. 이번 작업에서 건드리지 않았다.

## Seamless 개발 파일럿 계획 확정 (2026-11-25, 코드 변경 없음)

- 배경: DeepSpeak v2·v1.1(2026-11-15 신청) 무응답. BabelFake는 공개 신청 창구가 없고 승인이 불확실해 핵심 경로에서 뺐다.
- 계획: `docs/seamless-pilot-plan.md`. 승인 없이 받을 수 있는 Meta Seamless Interaction(CC BY-NC 4.0) naturalistic 실제 대화와, 같은 영상으로 만든 MuseTalk 립싱크로 개발 파일럿을 한다.
- 결정:
  - 미디어를 열기 전에 공식 train에서 내부 test 200쌍·내부 dev 100쌍·파일럿 10쌍을 고정 시드·촬영기관 층화로 예약한다. 상세 ID는 `data/research/seamless/reservation/`(커밋 금지), 해시·시드·규칙은 `docs/seamless-reservation.md`로 커밋.
  - 공식 dev·test와 내부 test 미디어는 개발 중 내려받지 않는다.
  - 참가자 얼굴 합성은 지도교수 확인(비상업 범위, 학교 절차) 뒤에 시작한다.
  - DeepSpeak 승인 시 역할은 승인 시점 규칙(계획 §8)으로 정한다.
- 남은 일:
  - Hugging Face 로그인 후 승인 단계 유무 확인
  - 지도교수 메일
  - 예약 스크립트 구현과 첫 쌍 확인(브랜치 `research/seamless-pilot`)
  - 목표: 예약·첫 쌍 11-28, 10쌍 12-05, 확대 결정 12-08(제안)

## Seamless Interaction 기반 대체안 평가 (2026-11-24)

- v2 재검토: 내부 test 200·dev 100은 공식 train에서 메타데이터만으로 사전 예약하는 제안이다. 먼저 §15.3에 역할 변경을 제안하고 공식 dev/test 충돌·계보를 검사한 뒤, 전체 후보에서 시드·기관 층화·중복 없는 대화 선택을 적용한다. 1,130은 키 순서로 뽑은 결과라 새 추출의 모집단으로 고정하지 않는다. 같은 공식 인덱스에서 train과 dev/test의 P 코드 교집합은 각각 17/32개, 기관+P 코드 교집합은 0/0개였다. 신원 독립성을 단정하지 않는다. 예약 ID 목록은 Git 밖 연구 경로에 두고 규칙·소스 버전·시드·목록 해시만 기록한다. 현행 어댑터는 공식 train을 재분할하므로 예약 보존 검증이 필요하다.
- 공식 test의 53은 후보 수다(상한 56). FPR 0%라면 n=53의 CP 방식 상한은 6.72%, 5%라면 14.74%다. 파일럿 이전에 고정할 제외·결측·교체 규칙을 명시하고 첫 실제 다운로드는 예약 후 파일럿 ID 한 쌍으로 한정한다. 실측 전에는 예약 test를 처리하거나 모델을 고르지 않는다.
- 현재 권고는 Meta Seamless Interaction의 자연 대화 영상과 같은 녹화에서 만든 립싱크 쌍을 개발 파일럿으로 먼저 검증하는 것이다. 정식 교체는 §15.3 결정 6 변경 제안으로 남긴다. 승인 대기와 독립적으로 시작할 수 있다. 아래 HiDF·LipSync-A 검토는 보조 자료의 근거다.
- Meta 저장소 `assets/filelist.csv` Git blob `e759e6d00f152a4833df2b985de842ab642812cd`를 직접 집계했다. naturalistic의 `vendor/session/interaction`별로 두 참가자 파일을 짝지어, 키 순서대로 두 ID 모두 미사용일 때만 채택했다. 공식 test 823개 interaction, 서로 다른 P 코드 113개, 비중복 53쌍(이론 최대 56쌍). dev 748개, 91개 코드, 비중복 40쌍. train은 vendor 구분 없이 같은 P 코드를 재사용 금지하는 보수적인 계산으로도 1,130쌍. 실제 신원 오류·교차 분할 중복·발화 적합성은 별도 확인 대상이다. [공식 인덱스 안내](https://github.com/facebookresearch/seamless_interaction#assetsfilelistcsv)
- 따라서 공식 test 200그룹·dev 60그룹은 제안대로 배정할 수 없다. 공식 test 보존이 기본이다. train에서 프로젝트 내부 holdout을 별도로 떼려면 공식 test와 명칭·역할을 구분하고 어댑터/설계 변경을 먼저 제안한다. 150그룹, 영상 FPR 5%의 CP 방식 상한은 9.81%(k=7.5), 200그룹은 9.00%(k=10)다. 두 경우 모두 그룹 bootstrap과 큰 값으로 판정한다.
- 공식 카드의 약 10%는 대화·프롬프트의 수작업 주석 오류다. A/V 시간 정렬은 별도 측정한다. SyncNet 출력으로 test real을 사전 필터링하지 않는다. 같은 화자의 다른 발화와 상대방 발화를 개발에서 비교한다. HiDF·LipSync-A는 자료·그룹별로 개발 또는 별도 보조 평가 역할을 사전에 고정한다.
- 다음 작업은 공식 train의 naturalistic 대화 한 쌍(공식 S3 안내 약 200MB)으로 원본 식별, 파일·트랙·발화·얼굴·Gate를 확인한 뒤 개발 10쌍으로 확대하는 것이다. 자료 카드상 CC BY-NC 4.0. 파일 인덱스와 FPR 계산 확인, 로컬 HF 접속은 DNS 실패. 미디어·MuseTalk MLX·M3 처리량 미검증. 당시 남은 디스크 약 30GiB여서 DFDC와 복수 생성기 일괄 다운로드는 초기 범위에서 제외할 것을 권한다. [데이터 카드](https://huggingface.co/datasets/facebook/seamless-interaction)

## DeepSpeak 대체 후보 판단 (2026-11-24)

- HiDF는 얼굴 교체 원본·변형 쌍, LipSync-A는 오디오 구동 립싱크 표본의 개발 시험에 권한다. 정식 주 학습셋 채택은 보류한다. LipSync-A의 `0_real`은 생성 방식에 따라 신원 원천 영상 또는 구동 영상이다.
- [BabelFake 논문 §7·부록 E](https://arxiv.org/html/2610.06339v1)의 동의 웹캠 설계는 주 학습 후보에 맞지만 기관 검증·이용 계약이 필요하다. [MAVOS-DD의 미지 생성기](https://openreview.net/pdf?id=XHSKSNIjLf)를 유지하려면 LipSync-A의 Sonic과 BabelFake의 HiFiFace를 학습·개발에서 제외한다. HiDF의 [이전 공개 원고 §3.1](https://openreview.net/pdf?id=XhyCPEnlCa)에서 Reface 사용을 확인했다. 현재 배포 영상별 버전·가중치는 미확인이다.
- [최종 검토본](deepspeak-fallback-review.md)에 그룹 단위 분할, 오디오 단독 무음 제거 명령 정정, 공식 생성기 제외 범위, 코드로 재계산한 FPR 예시와 실제 실행 진입점을 기록했다.
- 다음 작업은 표본의 양쪽 영상에 `ffprobe`와 기존 Gate를 적용해 해상도·발화·축별 처리 가능 비율을 비교하고, 인물·원본·구동 자료를 묶은 뒤 독립 그룹 수를 세는 것이다. 이번 판단은 문서 검토이며 미디어 실측·학습은 미검증이다.

## DeepSpeak v2 미승인에 대비한 학습 데이터 후보 조사 (2026-11-23)

- 백로그 3번 후보 조사. 공개 배포 1순위는 [LipSync-A](https://huggingface.co/datasets/AnsonShe/LipSync-A)(립싱크·토킹헤드, CC BY-NC-SA 4.0, 18.9 GB)와 [HiDF](https://zenodo.org/records/16140829)(얼굴 교체, 영상 ZIP 합계 약 1.56 GB)다. [HiDF 연구진](https://github.com/DSAIL-SKKU/HiDF)은 CC BY-NC 4.0과 원본 영상·대상 이미지 ID 파일명 규칙을 명시한다. [DigiFakeAV](https://huggingface.co/datasets/cambrain/DigiFakeAV/tree/main)는 합성 음성이 포함된 디지털 휴먼 보완 후보이며 오디오 포함 묶음을 선별해야 한다.
- 신청형은 [Celeb-DF++](https://github.com/OUC-VAS/Celeb-DF-PP)(얼굴 교체·표정/동작 재현·음성 구동 합성), [FakeAVCeleb](https://github.com/DASH-Lab/FakeAVCeleb)(음성·영상 조작 조합), [KoDF](https://github.com/deepbrainai-research/kodf)(한국어 발화)를 검토했다. [LAV-DF](https://huggingface.co/datasets/ControlNet/LAV-DF)는 조건 동의가 필요하며 짧은 부분 조작 실험 후보다.
- 다음 검증은 LipSync-A의 `selection.json`·`_real_index.json`과 HiDF 파일명에서 인물·원본·구동 자료 계보를 확보하고, 소량 표본에 `ffprobe`와 기존 Gate를 실행해 해상도·발화·품질과 유형별 통과율을 확인하는 것이다. [MAVOS-DD 논문](https://openreview.net/pdf?id=XHSKSNIjLf)의 미지 생성기 Sonic·HifiFace·Roop와 겹치는 훈련 후보를 미리 표시한다.
- 공식 배포 목록·문서 조사만 수행했다. 접근 신청, 영상 다운로드, 실제 표본 검사 및 학습은 미실행이다. 채택 시 §15.3 결정 6 변경을 먼저 제안한다.

## PR #35 마감 · 리뷰 6·7·9 통합

- PR #32(`eddd0f0`), #33(`2ba4268`), #34(`63b07bf`)를 통합한 PR #35가 `76a455f`로 병합됐다. 세 리뷰 커밋 모두 `origin/main`의 조상임을 확인했다.
- 통합 커밋 `d1a3804`의 `app/`에서 `flutter analyze` 지적 없음, `flutter test` 220개 통과. 병합 커밋 `76a455f`에서는 재실행하지 않았다. Git으로 확인한 두 커밋의 루트 트리는 모두 `1ded8fde5fa9ca3687a34a994e40d70b4f1c0103`이다.
- 다음 작업 후보는 리뷰 10이다. 레거시 DB 거부 테스트가 파일 권한 검사를 통과한 뒤 의도한 `application_id` 검사에서 실패하는지 확인한다.

## PR #31 후속 리뷰 9 · Flutter API 오류 안내

- 작업 시작 시 리뷰 6 PR #32와 리뷰 7 PR #33은 모두 OPEN이었다. 최신 `origin/main`에서 `fix/flutter-api-error-messages` 브랜치를 만들었다.
- DESIGN §9와 서버의 오류 응답을 대조했다. Flutter는 422 중 `invalid_youtube_url`만 주소 오류로 안내한다. 요청 형식·접수 번호·목록 커서 오류, 409 접수 충돌, 410 삭제된 작업, 503 일시적 사용 불가에는 각각 다음 행동을 안내한다. 미등록 코드는 일반 오류 안내를 사용한다. 상태 조회 중 503은 서버 사용 중으로 표시하고 자동 조회를 계속한다.
- 수정 전 `flutter test test/api_test.dart`에서 기존 422 분류와 잘못된 안내로 8건 실패를 확인했다. 수정 후 `app/`에서 `flutter analyze` 지적 없음, `flutter test` 전체 218개 통과. 401 재인증, 429 Retry-After 대기, 503 이후 상태 조회 복구도 통과했다. `git diff --check` 통과.

## PR #31 후속 리뷰 7 · Uvicorn 접근 로그

- 확인 당시 리뷰 6 PR #32는 OPEN이었다. 깨끗한 `docs/disable-uvicorn-access-log` 브랜치에서 독립적으로 진행했다.
- README.md, app/README.md, AGENTS.md, DESIGN.md의 API 서버 실행 예시 5곳에 `--no-access-log`를 추가하고 기존 `--reload`와 `--port 8000` 옵션을 유지했다.
- `trinity` 환경에서 임시 계정 DB에 같은 소유자의 작업 2건을 준비하고 루프백 Uvicorn을 실행했다. 인증된 목록 GET에 `limit=1`을 주어 최신 작업과 다음 커서를 받았다. 반환된 커서로 다음 페이지를 요청해 이전 작업과 `next_cursor=null`을 확인했다. 두 응답 모두 HTTP 200이었다.
- 서버 종료 후 표준 출력·오류를 함께 검사했다. 시작·종료 로그가 기록됐고, 목록 경로·커서 쿼리·커서 값·인증 키는 발견되지 않았다. 임시 DB와 로그를 정리했다.

## PR #31 후속 리뷰 6 · Flutter 세션별 Retry-After

- PR #31 병합 커밋 `872a3e8`에서 `fix/flutter-retry-after-session`을 생성했다. `HttpAnalysisApi`는 전체 요청 대기와 제출 전용 대기 기한을 보관한다. 로그인은 `setCredential(key)`, 401 및 세션 화면 폐기는 `setCredential(null)`을 호출한다. 자격 값이 바뀔 때 두 기한을 함께 비우고 같은 자격에서는 유지하도록 수정했다.
- 수정 전 위젯 테스트에서 A가 429를 받으면 B의 제출 또는 첫 작업 목록 조회가 차단되는 두 경우를 재현했다. 수정 후 같은 A 세션의 재시도는 HTTP POST를 추가로 보내지 않고, B는 즉시 목록을 열고 제출한다. 서버 요청 제한 코드는 변경하지 않았다.
- `app/`에서 `flutter test test/session_flow_test.dart test/api_test.dart` 19개 통과, `flutter analyze` 지적 없음, `flutter test` 전체 208개 통과. 다음 단계는 변경 검토 후 커밋 여부 결정이다.

## PR #31 리뷰 3·14 승인 반영과 리뷰 4 실행 확인 (2026-11-23, 브리즈번)

- `design/auth-rate-limit`에서 §15.3에 승인 결정을 먼저 기록한 뒤 §9에 인증·목록 정렬과 페이지 응답·HTTP 오류·접수 재전송 계약을 반영했다. §14.1, 결정 요약표와 README에 계정 인증·요청 제한 구현 상태를 갱신했다.
- `trinity` 환경에서 임시 디렉터리(0700)와 새 DB(0600)를 사용해 실행 문서를 확인했다. 대화형 `python -m server.accounts --db "$TRINITY_DB_PATH" issue`로 키를 발급하고, 임시 루프백 포트에서 문서의 curl 명령으로 접수해 202/queued를 받았다. 같은 DB의 Worker를 `--drain`으로 실행해 종료 코드 0을 확인했다. 소유자 상태 GET은 200/finished, 결과 GET은 200/analysis_unavailable이었다.
- 완료 후 같은 키·영상 재전송은 최초 접수 응답과 일치했다. 작업 삭제 후 같은 키·다른 영상은 410/analysis_deleted였다. 임시 서버와 DB는 검증 후 정리했다.
- `python -m pytest -q tests/test_account_api.py tests/test_admission.py` 34개 통과, TestClient 의존성 경고 1개. 이번 단계에서 수정한 파일은 DESIGN.md, README.md, 이 인계 문서다. 리뷰 7은 후속 작업이며 운영 DB 전환과 커밋·푸시·병합은 수행하지 않았다.

## PR #31 승인 리뷰 1·2·4·8 검증 완료 (2026-11-23, 브리즈번)

- `design/auth-rate-limit`의 미스테이징 변경을 이어받았다. 1번은 읽기 전용 사전 인증, 쓰기 잠금 뒤 재인증·요청 집계, 작업 트랜잭션 안의 인증·소유권 검사를 유지한다. 2번은 실측·스모크 3개에서 임시 계정 DB와 부모 메모리의 Bearer 키를 사용한다. 접수 재시도는 같은 UUID를 사용하고 취소는 상태 GET의 ETag를 사용한다. 자식 관찰은 HTTP 요청 횟수와 독립적이다.
- 4번은 README, app/README와 DESIGN 하단에 계정 DB 준비(0700/0600), 키 발급과 실행 방법을 반영했다. 8번은 Worker 시작과 이후 큐 연결에서 기존 계정 DB만 허용한다. 전환 테스트는 레거시 완료 행을 준비한다. 이번 세션에서는 DB 소실 회귀 테스트를 Worker와 같은 시작 경로로 변경했다.
- trinity 환경에서 인증·접수·큐·실측 관련 회귀 79개 통과. `python scripts/smoke_slice.py --isolated`, `python scripts/smoke_gate_worker.py`, `python scripts/smoke_cancel_worker.py` 모두 종료 0. Gate 취소 시 이전 ETag로 삭제하면 412, 종료 작업 삭제는 204, 이후 조회는 404였다.
- `python scripts/verify_real_worker_lifecycle.py --new-run --only sigkill-gate --only sigkill-waverep --only sigkill-motionphys --only cancel-motionphys` 종료 0. 이번 기록은 `data/research/real-lifecycle/run-pqxbsy58/`이다. 세 SIGKILL 모두 2회차에서 finished/completed/abstained, MotionPhys 취소는 1회차에서 1.682초 후 cancelled. 네 건 모두 잔류 프로세스와 임시 작업 디렉터리가 없었다.
- 최종 `pytest -q` 결과 962 passed, 1 skipped, 1 warning (266.38초). MotionPhys 학습 테스트 모듈은 trinity 환경의 lightgbm 부재로 미검증. 경고는 Starlette TestClient 의존성 폐기 예고다. 이전 세션의 중단된 실행은 집계에서 제외했다.
- 다음 작업은 3·14번 §15.3 변경안 승인 여부 확인이다. 7번 access log 문서 변경은 후속 작업이다. 커밋·푸시·병합 없이 작업 트리에 보관했다.

## 백로그 14 4단계 · 시연 SyncNet 시간 초과 원인 조사 (2026-11-19, 코드 변경 없음)

- 대상: 이전 시도 `e51a8e3f-cc9a-462c-887d-bb0dfb05eb00`(finished / partial, SyncNet error / timeout)과 새 시도 `2985b7ed-ce29-444c-9b27-a2317ca992ee`(finished / completed).
- 자료 출처:
  - jobs.run_info_json과 시각 열: 이전 시도는 보존 DB에서 읽기 전용으로, 새 시도는 임시 DB를 삭제하기 전에 읽었다.
  - 새 시도 Worker 로그: 임시 파일을 삭제하기 전에 읽은 단계 시각.
  - 이전 시도: 제어 스크립트가 Worker 출력을 버려(DEVNULL) **Worker 로그가 없다**. 단계 시각은 로컬 Codex 세션 기록에 남은 DB 조회 출력(16:40:33, 16:42:03, 16:43:19, 16:43:52)으로만 확인했다.
  - macOS 통합 로그와 `pmset -g log`.
- SyncNet 단계 제한은 Worker 로그에 남지 않는다. 표의 단계 제한 값은 `server/axes/alignment/__init__.py`의 식 `min(60 + 16 × 37.021, 남은 작업 시간 − 10)`으로 계산한 값이다. 작업 제한은 새 시도에서만 로그로 확인했다("timeout set to 920s").

| 항목 | 오전 실행(오디오 트랙 절) | 새 시도 2985b7ed (21:01) | 이전 시도 e51a8e3f (16:40) |
|---|---|---|---|
| Gate(전처리) | 12.3초 | 13.5초 | 미기록. 7초 시점 진행 중, 97초 이전 종료 |
| WaveRep | 18.6초 | 19.7초 | 시작 7~97초, 206초 시점에도 진행 중 → **109초 이상**(5.5배 이상) |
| MotionPhys | 38.0초 | 38.9초 | 미관측(completed) |
| SyncNet | 149.1초 | 167.5초(completed) | error / timeout. 시작 시점 **약 254초 이상**(계산) |
| SyncNet 시작 시점 | 68.9초 | 72.1초 | 약 254초 이상 |
| 전체 | 219.1초 | 239.6초(대기 8.1초 별도) | 911.4초 |
| 작업 제한 | 기본값 | 920초(로그) | 920초(기본 규칙 계산) |
| SyncNet 단계 제한 | 계산 652.3초 | 계산 652.3초 | 계산 min(652.3, 910.4 − 시작) ≤ 약 656초 |
| 장치 signal / physics / alignment | mps / cpu / mps | mps / cpu / mps | mps / cpu / null |
| 열 상태(축 시작→끝) | 미기록 | signal·physics nominal→nominal, alignment nominal→fair | 세 축 모두 fair→fair |

- 이전 시도의 SyncNet 시작 시점 계산: 종료 911.4초 = min(시작 + 652.3, 910.4) + 마무리 지연. 마무리 지연은 새 시도에서 0.001초였고 상한은 SQLite 대기 5초다. 따라서 시작은 약 254초 이상이다. alignment device_used=null은 timeout 경로(`syncnet.py`가 결과 JSON 없이 `failure('error','timeout')` 반환)의 결과이며 장치 대체 증거가 아니다.
- 환경 변수: 두 시도의 제어 스크립트 모두 상속받은 `TRINITY_*`를 지우고 다섯 개만 설정했다(DB·runtime·허가 레지스트리·미디어 루트·CORS 출처). 작업·SyncNet·WaveRep·MotionPhys 제한과 장치는 기본값이다. Codex 데몬과 이번 셸에는 `TRINITY_`·`PYTORCH_`·`OMP_`·`MKL_` 변수가 없다(이름만 확인).
- Flutter 빌드와 Chrome:
  - 이전 시도: 웹 빌드는 16:38:28~16:39에 끝나 제출(16:40:12)과 분석에 겹치지 않았다. Chrome은 분석 내내 떠 있었다. 16:44:21 중단 전까지 Codex가 접근성 트리·새로고침과 약 50초의 900 ms 네트워크 지연 에뮬레이션(브라우저 탭 한정)으로 화면을 조작했다. 그 직전 16:32~16:39에는 flutter analyze, 위젯 테스트, `smoke_slice.py --isolated`, `flutter build web`이 연속으로 돌았다.
  - 새 시도: 웹 빌드는 21:00~21:01 제출 전에 끝나 겹치지 않았다. Chrome은 분석 내내 떠 있었고, 접근성 트리·새로고침·스크린샷으로 조작했다. 그 전 20:46~20:53에는 덮개를 닫은 잠자기 상태였고, 세션 시작 뒤 무거운 작업은 없었다.
- 시스템 기록:
  - 기기: MacBook Air(M3, 16 GB, 팬 없음). 두 시각 모두 AC 전원이었다. 저전력 모드는 현재 꺼져 있고, 이전 분석 중 잠자기·덮개 이벤트는 없었다.
  - OS 열 수준(통합 로그의 VCPowerManager "Thermal level changed", avconferenced 기준. 숫자의 정확한 정의는 확인 필요, 상대 비교만 함):
    - 이전 시도: 16:16~16:31은 0, 16:33에 1, 16:34에 2로 올랐다. 16:37~16:40에는 2를 유지했고, 분석 중인 16:41~16:56에는 1과 2를 약 39회 오갔다.
    - 새 시도: 20:40~21:03은 변화 없이 0이었다. 21:03에 1, 21:04에 2(SyncNet 중), 21:06에 0으로 돌아왔다.
  - 메모리 압박: Safari WebKit의 "memory pressure event 2"가 이전 창 18분에 21건(시스템 경고 수준 2건), 새 창 9분에 10건(1건)으로 빈도가 비슷했다.
  - 실행 우선순위: Codex 데몬·실행 호스트와 이번 셸 모두 PRI 31 / nice 0이었다. 현재 측정값이며 당시 값은 기록이 없다.
- 판단:
  - 설정: 배제(같은 기본값).
  - 장치: 배제(대체 증거 없음).
  - 열: 두 시도의 가장 큰 차이다. 이전 시도는 연속 빌드·테스트 직후, 팬 없는 기기가 이미 높은 열 수준에서 시작해 분석 내내 그 수준을 유지했다. 새 시도는 잠자기 뒤 낮은 열 수준에서 시작했다.
  - 동시 부하: 배제하지 못했다. 이전 시도 중 다른 프로세스의 CPU·GPU 사용량 기록이 없다(당시 ps 출력이 잘렸다).
  - **결론: 원인 미확인.** 열이 가장 유력한 차이지만 크기를 설명할 근거가 없다. 이전 측정("SyncNet Worker 안 대 단독")에서는 앞선 부하가 SyncNet을 12.8% 늦춘 정도였는데, 이번에는 WaveRep이 5.5배 이상 느려졌다. 동시 부하와 메모리 영향도 배제하지 못했다. 이전 시도의 partial을 정상 동작으로 보지 않는다.
- 재발 가능성: 연속 빌드·테스트 직후이거나 다른 앱이 많이 떠 있는 상태에서 시연하면 다시 날 수 있다(이전 시도는 작업 제한 920초 중 911초를 썼다). 낮은 열 상태에서 시작한 새 시도는 작업 제한의 26%(240초)만 썼다.
- 대책(제안만, 코드·timeout 정책 변경 없음):
  1. 시연 전에 웹 빌드와 테스트를 미리 끝낸다. 열 상태가 nominal로 돌아온 것을 확인한 뒤 제출한다(예: `pmset -g therm` 또는 Worker와 같은 열 상태 프로브).
  2. 시연 중에는 Safari·메신저 등 큰 앱을 닫고 Chrome에는 시연 탭만 둔다.
  3. 시연용 Worker의 출력을 파일로 남겨 단계별 시각을 확인할 수 있게 한다.
  4. (코드 변경, 별도 승인 필요) Worker 로그에 SyncNet 단계 제한값과 축별 소요 시간을 남긴다.
  5. (원인 확정 실험, 별도 작업) A를 차가운 상태와 빌드·테스트 직후 상태에서 각 3회 측정하고, `powermetrics`(sudo)와 `memory_pressure`를 함께 기록한다.
  6. 시연 대비용으로 완료된 작업 화면을 미리 준비한다.
- 남은 일: PR #31 리뷰 14건 처리 전(docs/review-pr31.md), merge 전 1·2·3·4·8 처리 예정.
- 정리(0단계): 이전 시도의 `verify.py`는 이번 확인 시점에 이미 외부에서 종료돼 있어 따로 종료할 프로세스가 없었다. 고아로 남은 API 1개는 아래 절에 적은 대로 종료했다. 이번 조사에서는 프로세스를 새로 만들지 않았다. 임시 추출 스크립트는 세션 scratchpad에만 두었다가 삭제한다.

## 백로그 14 4단계 · Chrome에서 허가 영상 A 검증 (2026-11-19)

- 기준 `4974828` 위의 4단계 Flutter 릴리스 빌드를 매번 새 프로필의 macOS Google Chrome(창 1200×900, 웹형 배치)에서 열었다. 임시 사용자 키는 제어 프로세스 메모리에서 CDP 입력 이벤트로만 입력란에 넣었다. 명령 인자·로그·문서·화면 기록에 키 원문을 남기지 않았고 인증·접수 요청의 헤더와 본문도 기록하지 않았다. 화면은 Chrome 접근성 트리와 스크린샷으로 확인했다.
- 재현 환경: trinity 환경에서 소유자 전용 임시 디렉터리에 `python -m server.accounts --db <임시 DB> init`과 `issue`로 계정을 준비한다(수동 발급 시 녹화 없는 터미널에서 개별 전달). `TRINITY_DB_PATH`, `TRINITY_RUNTIME_DIR`, `TRINITY_AUTHORIZED_MEDIA`는 임시 경로, `TRINITY_AUTHORIZED_MEDIA_ROOT`는 저장소의 data 절대 경로, `TRINITY_CORS_ORIGINS`는 선택한 Flutter 루프백 출처로 설정한다. 그 밖의 `TRINITY_*` 값은 넘기지 않는다(작업·SyncNet 제한은 기본값). 임시 registry의 authorized_media 한 항목에 youtube_video_id=TRINITYtest, provenance=registered_authorized_source, local_path=research/samples/A.MOV를 등록한다.
- 재현 명령: `python -m uvicorn server.main:app --host 127.0.0.1 --port <API포트> --no-access-log`. app에서 `flutter build web --no-pub --no-web-resources-cdn --output <임시웹디렉터리> --dart-define=TRINITY_API_MODE=server --dart-define=TRINITY_API_BASE_URL=http://127.0.0.1:<API포트>`. 웹 디렉터리를 `python -m http.server <웹포트> --bind 127.0.0.1 --directory <임시웹디렉터리>`로 제공한다. Worker는 같은 환경 변수로 `python -m server.jobs.worker --drain`.
- **이전 시도, 작업 `e51a8e3f-cc9a-462c-887d-bb0dfb05eb00`(16:40 접수).**
  - 브라우저에서 직접 확인한 범위: 키 입력 → 테스트 URL `https://youtu.be/TRINITYtest` 1회 제출 → 대기 화면 → 별도 Worker → 전처리 진행 화면 → 새로고침·로그인 화면 → 같은 키로 재인증 → 내 작업에서 같은 ID 선택 → 진행 화면 복원까지다. 이 시도의 제어 세션(Codex)이 중단돼 같은 세션에서는 완료 화면을 보지 못했다.
  - 중단 뒤 임시 DB를 읽기 전용으로 확인한 종료 상태: 작업 1건, attempts=1, **finished / partial / abstained**, overall_score=null, abstention_reason=no_valid_fusion_model. signal·physics completed. alignment는 **error / timeout**이었고 LSE-C·LSE-D null, included_in_fusion=false. 시작부터 종료까지 911.4초였다. 작업 제한은 기본 규칙에 따라 920초(180 + 20 × 적합 구간 37.021초)였다. run_info의 alignment device_used는 null, 세 축 열 상태는 fair였다. jobs 디렉터리에는 `.worker.lock`만 남았다. 종료 시각이 작업 제한 − 마무리 여유 10초 부근이라 SyncNet 남은 시간 제한에 걸린 것으로 보인다. 다만 이 시도의 Worker 로그를 남기지 않아 단계별 시간과 느려진 원인은 **확인 필요**다.
  - 이어 쓰기: 원래 제어 세션은 정상적으로 이어 쓸 수 없었다. Chrome이 이미 종료됐고 키는 중단된 제어 프로세스 메모리에만 있었다. 대신 원본 DB를 SQLite backup으로 읽기 전용 사본을 만들었다. 사본에서만 같은 사용자의 키를 교체하고 별도 API와 새 Chrome 프로필로 같은 작업을 열람했다. Worker를 실행하지 않았고 재분석도 하지 않았다. 원본 DB·WAL의 sha256은 열람 전후에 같았다.
  - 열람 결과는 API GET 결과(200)와 일치했다. 목록에는 '종료'로 나왔다. 결과 화면은 '판단 보류'와 '이번 요청의 상태. 작업 종료, 분석 부분 분석, 판정 보류'를 보였고, 이유는 '검증된 종합 판정 모델이 없습니다.'였다. 상세 화면의 SyncNet은 '오류 · 정해진 시간 안에 끝나지 않았습니다.'였고 LSE-C·LSE-D는 '값 없음', 종합 판정에 포함은 '아니오', 종합 점수는 '값 없음'이었다. 서버 상태 칸에는 finished / partial / abstained / no_valid_fusion_model이 나왔다.
- **새 시도, 작업 `2985b7ed-ce29-444c-9b27-a2317ca992ee`(21:01 접수).** 새 임시 계정 DB·runtime·Chrome 프로필로 허가 영상 A를 1회 제출했다.
  - 대기 화면이 나온 뒤 별도 Worker를 실행했다. MotionPhys 진행 중에 새로고침 → 로그인 → 같은 키로 재인증 → 내 작업에 같은 ID '진행 중' → 선택 → 진행 화면 복원을 다시 확인했다. 진행 화면은 단계명만 표시하고 % 숫자는 없었다.
  - 결과: 작업 1건, 접수 영수증 1건, attempts=1. 대기 8.1초, 실행 239.6초, Worker 종료 코드 0. 작업 제한 920초는 Gate 뒤 Worker 로그로 확인했다. **finished / completed / abstained**, overall_score=null, abstention_reason=no_valid_fusion_model. 세 축 모두 completed였고 SyncNet은 167.5초(mps), raw_score·LSE는 null, included_in_fusion=false였다. API의 상태·결과·목록 조회는 모두 200이었고 목록 ID는 1개였다.
  - 화면: '판단 보류', '작업 종료, 분석 완료, 판정 보류', 이유 '검증된 종합 판정 모델이 없습니다.'. 상세 화면은 세 축 '측정됨', 원시 점수·LSE '값 없음', 종합 점수 '값 없음'이었고 서버 상태 칸은 API 값과 같았다.
  - 같은 기본 설정에서도 이번에는 SyncNet이 제한 안에 끝나 partial이 재현되지 않았다. timeout 정책과 설정은 바꾸지 않았다. 부분 분석 표시는 위의 이전 작업 열람으로 확인했다.
- 점수 표시: 두 작업 모두 API overall_score가 null이었다. 결과·상세 화면도 숫자 점수나 확률을 만들지 않았다. 화면에 나온 숫자는 다음뿐이다.
  - coverage('41초 가운데 37초', 분석한 양이며 정확도·신뢰도가 아님)
  - 구간 시각
  - 서버 설명문의 Gate 품질 수치
  - MotionPhys 추적 성공률(%)
- 결함: 이 흐름에서 수정이 필요한 결함은 찾지 못했다. 코드·테스트 변경 없음.
- 정리:
  - 새 시도와 사본 열람: 각각의 API·Worker·웹 서버·Chrome과 임시 디렉터리(DB, runtime, 프로필, 웹 빌드, 스크린샷, Worker 로그)를 종료·삭제했다. 두 시도 모두 runtime jobs에는 `.worker.lock`만 남아 있었고, Worker 로그에 인증값·URL이 없음을 확인했다.
  - 이전 시도의 잔여물: 제어 프로세스는 이번 확인 중 이미 외부에서 종료돼 있었다. 고아로 남은 API 1개는 명령과 포트를 대조한 뒤 종료했다. 이전 임시 디렉터리의 Chrome 프로필·웹 빌드·`.worker.lock`·제어 스크립트는 지웠다.
  - 보존: 증거 DB(`accounts.sqlite`, `-wal`, `-shm`)와 `registry.json`만 `/private/tmp/trinity-web-review.SKikEp/tmpolm8khbw/`에 남겼다. 이 DB에는 임시 사용자 키 digest가 들어 있으므로 필요 없어지면 지운다. 원본 A·모델·기존 DB는 변경하지 않았다.

## 백로그 14 · Flutter 웹 연결

- 3단계 체크포인트는 `4974828`. 변경 없는 코드·테스트에 직전 943 통과, 1 건너뜀 기록을 사용했다. 이번 세션에서 전체 pytest를 다시 실행하지 않았다.

- API 스모크: `/opt/anaconda3/envs/trinity/bin/python scripts/smoke_slice.py --isolated` 통과. 임시 계정 DB·빈 레지스트리·전용 runtime 및 루프백 서버에서 미등록 ID POST 202, 별도 Worker attempts=1·종료 코드 0, 결과 GET 200 및 finished / analysis_unavailable / abstained, overall_score=null을 확인했다. 서버 종료·임시 디렉터리 정리 완료.

- Flutter 서버 모드: 발급 키를 가린 입력창에서 받아 메모리에만 보관하고 내 작업 목록을 읽는다. 새로고침·401 뒤에는 키를 다시 입력한다. 401에서 진행 화면을 내려 타이머와 이전 목록을 폐기한다. 이전 작업은 커서로 더 읽고 선택한 ID의 상태·결과를 기존 화면으로 연다. 응답 유실·타임아웃 뒤 같은 주소의 재제출에는 같은 UUID v4를 사용한다. 새 분석 동작은 새 키를 쓰며 24시간이 지난 재시도는 목록 확인을 안내한다. Retry-After 동안 HTTP 발송을 보류하고, 조건부 취소는 기존 If-Match와 412 후 재조회 경로를 쓴다.
- 앱 검증: `cd app && flutter test --no-pub --reporter expanded` **206 통과, 0 실패**. 모의 HTTP로 응답 유실 후 같은 키·다음 동작의 새 키, Retry-After 중 추가 HTTP 없음, 401 후 폴링 중단과 재인증·목록·결과 복원, 취소 202/412를 확인했다. `cd app && flutter analyze --no-pub` 문제 없음. 실제 Chrome 시연은 위 절에 따로 적었고 API 스모크와는 별개다. Chrome 검증 중 코드·테스트를 바꾸지 않아 206 통과·analyze 기록을 그대로 쓴다. 같은 코드의 `flutter build web` 릴리스 빌드는 두 번 성공했다.
- 최종 검증 범위: Flutter 단위·위젯 테스트 206개 통과, analyze 문제 없음, 격리 API 스모크 통과, Chrome에서 허가 영상 A 실제 시연을 했다(로그인 → 1회 제출 → 별도 Worker → 새로고침·재인증 → 내 작업에서 같은 ID 복원 → 완료·상세 화면과 API 결과 대조). 부분 분석 화면은 이전 작업의 읽기 전용 DB 사본에서 확인했다.
- 미검증: 모바일 공유 시트, 실기기와 좁은 화면(앱형 배치), 새 실행에서 SyncNet timeout이 실시간으로 나는 완료 화면, 외부 공개 전 폴링 부하·SQLite 잠금 지연, 나머지 실제 모델 스모크의 새 인증 전환. 운영 DB/runtime 전환도 하지 않았다. 4단계에서 서버 코드를 바꾸지 않아 전체 pytest는 다시 실행하지 않았다(직전 943 통과, 1 건너뜀).
- 상태: 4단계는 `design/auth-rate-limit`에 로컬 커밋했다. push·PR·main 병합·운영 DB 전환은 하지 않았다.

## 백로그 14 3단계 · 사용자별 제한과 중복 접수 방지

- `design/auth-rate-limit`, 기준 `ca1bed3`. `server/jobs/admission.py`와 분석 API에 계정별 접수·호출 제한을 연결했다. Worker 코드와 전체 대기 3건·실행 1건 정책은 그대로다.
- 인증된 분석 요청은 별도 BEGIN IMMEDIATE에서 키를 검증하고 (user_id, UTC 분) 호출 수를 먼저 커밋한다. 181번째부터 429 request_rate_limited와 다음 분까지의 Retry-After를 준다. 재전송·유효성 오류·타인 404·조건 불일치 412·접수 거절도 호출로 센다. health·CORS preflight와 인증 실패 요청은 제외한다. 이어서 조회는 읽기 스냅샷, POST·DELETE는 쓰기 잠금 획득 후 키를 다시 검증한다. 두 단계 사이에 키가 폐기되면 호출만 남고 작업은 생성되지 않는다.
- 분석 POST는 사용자 동작마다 Idempotency-Key(UUID v4)가 필요하다. 유효 영수증의 동일 영상 재전송은 최초 응답 202/queued와 같은 ID, 충돌은 409, 삭제 표식은 410이다. 신규 접수만 활성 1건 → 최근 600초 6건 → 전체 대기 상한 순서로 검사한다. 시간창 거절은 429 user_submission_limit과 Retry-After, 자리 거절은 429 user_active_limit 또는 queue_full로 응답한다. 작업 INSERT와 영수증 INSERT가 함께 커밋되며 실패하면 두 INSERT 모두 롤백한다.
- 스키마 준비: 전용 계정 DB에 대해 기존처럼 `python -m server.accounts --db <새-경로> init`으로 최초 초기화한다. 기존 **계정 DB**에는 init을 재실행하지 않는다. 같은 DB를 가리키는 3단계 API의 시작 시점에 쓰기 트랜잭션 하나로 영수증·분 버킷·인덱스·삭제 트리거를 설치한다. 이미 준비된 DB는 그대로 사용한다. 2단계에서 남아 있는 최근 작업은 기존 생성 시각으로 접수량에 반영한다. 전환 전에 이미 삭제된 2단계 작업 이력은 복원할 수 없으므로 첫 10분에 과거 접수량을 엄밀히 이어가려면 전환 직전 10분 동안 신규 접수를 중지한다. 24시간 재전송 복원은 3단계에서 키를 받아 접수한 작업부터 가능하다. 레거시 토큰 DB와 실제 운영 DB/runtime은 이번 작업에서 전환하지 않았다.
- 작업 삭제와 같은 트랜잭션에서 영수증의 작업·영상 식별자를 지우고 삭제 표식과 접수 시각을 남긴다. Worker 재시도와 취소 접수는 신규 접수가 아니다. 유효기간은 접수 후 24시간 미만이며 만료된 같은 키는 새 요청으로 평가한다. 인증된 호출 시 오래된 버킷과 만료 영수증을 각각 최대 32개씩 정리한다.
- 격리 검증: 같은 사용자·독립 API 두 곳에서 같은 키 동시 제출은 202/202와 동일 ID, 다른 키는 202/429. 두 경우 모두 작업 1건·영수증 1건·호출 2회. 재시작 및 키 재발급 후 재전송, 1분·10분·24시간 경계, 삭제 후 410, 영수증 저장 실패 시 원자적 롤백을 검사했다. 관련 명령 `python -m pytest -q tests/test_admission.py tests/test_account_api.py tests/test_api.py tests/test_analysis_delete.py tests/test_queue_worker.py tests/test_cors_and_label.py tests/test_run_info_record.py`는 92 통과했다.
- 최종 전체 검증은 저장소 루트에서 `/opt/anaconda3/envs/trinity/bin/python -m pytest -q -rs`로 실행했다. **943 통과, 0 실패, 1 건너뜀**(331.45초). LightGBM 미설치로 tests/test_motionphys_train.py 1건을 건너뛰었고 Starlette TestClient 사용 중단 경고 1건이 있었다.
- 다음 작업은 4단계 클라이언트 전환이다. 현재 Flutter·스모크의 구 헤더는 401이며 Bearer로 바꿔도 POST에 접수 키가 없으면 422다. 사용자 동작별 키 생성·재시도 시 재사용, 429 원인별 안내·Retry-After 대기, 재인증 후 본인 목록 복원이 필요하다. 실기기·브라우저 종단 동작과 외부 공개 전 폴링 부하·SQLite 잠금 지연 실측은 미검증이다.

## 백로그 14 2단계 · API 인증과 작업 소유권

- 기준은 `design/auth-rate-limit`의 `f3bfb11`. 분석 POST, 목록·상태·결과 GET, DELETE에 발급된 개인 Bearer 키를 적용했다. API 시작 시 1단계의 계정 DB인지 읽기 전용으로 확인한다. 누락된 DB를 만들거나 레거시 DB를 변경하지 않는다. Worker는 기존 코드로 새 DB 작업을 선점한다.
- 목록·상태·결과는 BEGIN 뒤 첫 자격 조회에서 정해진 읽기 스냅샷으로 사용자와 작업을 조회한다. POST와 DELETE는 BEGIN IMMEDIATE 성공 후 현재 시각으로 자격을 판정한다. 같은 연결에서 POST는 전체 대기 상한 확인·고정 user_id 저장, DELETE는 소유권 → If-Match → 취소 접수 또는 종료 기록 정리를 수행한다. 응답 전에 커밋한다. SQLite 잠금 시간 초과는 503, 인증 실패는 Bearer challenge가 있는 동일 401이며 사용자 소유권 불일치는 없는 작업과 같은 404다.
- 목록 응답은 `{items, next_cursor}`. 생성 시각·ID 내림차순, 기본/최대 20건. 다음 요청에 next_cursor를 cursor로 보내며 커서는 접근 권한을 부여하지 않는다. 모든 페이지에서 user_id를 다시 검사한다. 재발급 후 같은 목록을 복구한다.
- 격리 재현 명령은 trinity 환경에서 `python -m pytest -q tests/test_account_api.py::test_issued_key_to_separate_worker_result`. 테스트가 만든 전용 계정 DB·runtime·레지스트리에서 실제 발급 키로 TestClient를 통해 접수하고 별도 `python -m server.jobs.worker --drain` 프로세스를 실행했다. 미등록 합성 ID 한 건이 attempts=1, finished / analysis_unavailable / abstained, overall_score=null로 종료됐다. 실운영 경로나 데이터셋은 전환 리허설의 입력으로 쓰지 않았다.
- 회귀 명령은 `python -m pytest -q tests/test_account_api.py tests/test_api.py tests/test_analysis_delete.py tests/test_accounts.py tests/test_run_info_record.py tests/test_cors_and_label.py`(94 통과), `python -m pytest -q tests/test_job_lifecycle.py`(18 통과). 동일 시각 페이지 경계, 외부 사용자 커서, 삭제·재발급, 잠금 대기 중 만료/폐기, 읽는 도중 폐기, 기존 202/204/412 경합을 포함한다.
- 최종 검증: Gate 의존성 미로딩 테스트에 임시 계정 DB fixture를 연결하고 subprocess에 `TRINITY_DB_PATH`를 전달했다. 기존 5개 모듈 미로딩 단언과 서버의 계정 DB 사전 초기화 요구를 유지했다. `python -m pytest -q tests/test_gate_segments.py::test_api_server_does_not_import_gate_dependencies` 1 통과. 현재 작업 트리에서 `/opt/anaconda3/envs/trinity/bin/python -m pytest -q -rs` 실행 결과 **935 통과, 0 실패, 1 건너뜀**(255.35초). LightGBM 미설치로 tests/test_motionphys_train.py 1건 건너뜀, Starlette TestClient 의존성 사용 중단 경고 1건. ps 권한 오류 없음.
- 로컬 커밋 전 최종 리뷰에서 읽기 스냅샷과 쓰기 잠금 후 인증, 작업별 소유자 필터 및 커서 경계, 키 재발급, 동일 404, ETag와 취소·삭제 분기를 코드 및 회귀 테스트와 대조했다. Worker 선점·복구 로직과 Gate import 테스트의 기존 다섯 모듈 단언도 보존됐다. 2단계 범위에서 수정이 필요한 결함을 발견하지 않았다. 이번 리뷰는 코드·테스트를 변경하지 않아 pytest를 재실행하지 않았으며 위 935 통과는 직전 전체 실행 결과다.
- 호환 상태: 현행 Flutter 서버 모드와 smoke_slice 등 구 헤더 클라이언트는 새 분석 API에서 401이다. 임시 빈 DB로 직접 서버를 시작하는 smoke_gate_worker, smoke_cancel_worker, verify_real_worker_lifecycle도 DB 사전 초기화·별도 계정 발급이 필요하다. 4단계에서 클라이언트를 전환한다. 이번 범위에는 Flutter 브라우저/실기기 및 기존 실제 모델 스모크의 새 인증 종단 검증이 없다.
- 다음 3단계는 사용자별 API 호출 카운터와 접수 영수증부터 추가한다. 계정/쓰기 잠금 안에서 중복 키 확인 → 개인 활성·시간창 → 기존 전체 상한 → 작업·영수증 동시 저장을 연결한다. 현재 적용 중인 용량 제한은 기존 전체 대기 상한이다. 실운영 DB 전환과 구 DB 보존 종료일은 별도 결정이다.

## 백로그 14 계정·자격 증명 1단계 (2026-11-19)

- `design/auth-rate-limit`, 기준 커밋 `a19aa20`. 사용자 승인으로 DESIGN §9·12.2·14.1·15.3에 전환 후 계약, 인증·제한 초기값과 보존 결정을 반영했다. 아래 검토 대기 기록의 세 결정은 승인됐다.
- `server/accounts.py`는 지정한 새 DB에 users·credentials와 사용자 FK가 필수인 jobs를 만든다. 기존 큐와 새 DB는 작업 열 정의만 공유한다. 서비스 API와 Flutter는 기존 토큰을 사용한다. 새 DB를 현행 API나 Worker의 DB 환경 변수로 지정하지 않는다.
- 운영자 명령은 trinity 환경에서 `python -m server.accounts --db <별도-디렉터리>/accounts.sqlite init`이다. 신뢰하는 로컬 경로에 운영자 소유 전용 디렉터리(0700)를 만들고 심볼릭 링크를 거치지 않는 실제 경로를 사용한다. 도구 실행 중 같은 OS 계정의 다른 프로그램이 이 경로를 교체하지 않는 운영 환경을 전제한다. 기존 파일을 지정하면 실패한다. 같은 명령의 마지막 인자를 `issue`, `reissue <user_id>`, `revoke <user_id>`, `suspend <user_id>`로 바꿔 실행한다. issue/reissue의 isatty 검사는 표준 출력이 터미널인지 여부만 확인한다. 녹화·스크롤백·화면 공유로 키가 복사될 수 있으므로 기록이 없는 개인 터미널에서 발급하고 개별 전달한다. 노출되면 폐기·재발급한다. 폐기 후에는 같은 사용자에게 재발급할 수 있고 정지 후에는 발급할 수 없다.
- 초기화는 같은 전용 디렉터리의 임시 하위 폴더에서 DB를 완성하고 연결을 닫은 뒤 대상 이름으로 배타적 하드 링크를 만든다. 일반적인 SQL 오류에서는 임시 파일이 정리되어 같은 명령으로 재시도할 수 있다. 기존 대상이나 같은 이름의 -wal/-shm/-journal(끊어진 링크 포함)이 있으면 보존하고 중단한다. 사용 중인 DB의 보조 파일을 지워 재시도하지 않는다.
- 초기화 프로세스가 강제 종료되면 `.account-init-*` 폴더가 남을 수 있다. 게시 전이면 다른 init이 없는지 확인하고 같은 경로로 재시도할 수 있다. 게시 직후라면 대상 파일이 완성됐어도 임시 파일과 하드 링크를 공유할 수 있어 도구가 운영을 거부한다. 작업을 멈추고 소유자·inode를 대조해 해당 시도의 임시 링크만 분리한 뒤 완성된 DB를 사용한다. 상태가 불명확하면 파일을 보존하고 별도 전용 경로에 초기화한다.
- DB·WAL·SHM은 타 사용자 권한 비트가 없는지 실측했다. 운영 도구는 DB와 존재하는 보조 파일의 소유자·권한·일반 파일 및 단일 링크 여부를 확인한다. 구 DB는 SQLite 연결 전 헤더를 검사해 거절한다. 기준 커밋과 새 코드의 레거시 jobs 스키마는 메모리 DB에서 열·기본값·키·인덱스가 일치했다.
- 격리 리허설 명령은 `python -m pytest -q tests/test_accounts.py::test_transition_rehearsal`. 임시 레거시 DB에 합성 작업 등록 → 기존 Worker --drain 및 종료 → 임시 DB·sidecar·runtime 분리 → 빈 새 DB/runtime 생성 → 구 기록과 새 FK 검사. 실제 서비스의 DB/runtime과 보존기간은 건드리지 않았다.
- 최종 검증: 관련 테스트 `python -m pytest -q tests/test_accounts.py tests/test_queue_worker.py tests/test_api.py` 35 통과. 코드·테스트 확정 후 전체 `python -m pytest -q -rs` 1회 실행, 914 통과·0 실패·1 건너뜀(190.78초). LightGBM 미설치로 tests/test_motionphys_train.py 1건 건너뜀, Starlette TestClient 의존성 사용 중단 경고 1건. 기존 테스트 파일 변경 없음. 계정 테스트에는 초기화 실패·재시도, 동시 초기화, 파일·링크·권한, 만료·회전 롤백, 재발급·폐기·정지 경합 및 임시 전환 리허설이 포함된다.
- 다음은 제안서 §6의 2단계다. 인증 확인을 소유권 조회·변경 트랜잭션에 통합하고 계정별 목록 및 401/404·ETag 경합을 검증한다. 요청량 제한·접수 중복 방지는 3단계, Flutter 전환은 4단계다. 실운영 전환 시점과 구 DB 보존 종료일은 미정이다.

## 백로그 14 인증·사용자별 요청 제한 제안 (검토 대기)

- 기준 커밋 `a19aa20`에서 만든 `design/auth-rate-limit` 브랜치. [제안서](proposals/auth-rate-limit.md)에 현행 API·Flutter·큐 동작, 인증 대안, SQLite 제한과 중복 접수 처리, 경합별 수용 기준을 정리했다.
- 다음 작업은 제안서 §7의 인증 방식·초기 상한·구 DB 전환 방식 결정이다. 승인 뒤 §15.3과 API 계약을 반영하고 계정 발급·폐기 및 전환 도구부터 구현한다.
- 문서 작업만 진행했다. 이번 세션 테스트·실제 모델 실험은 미실행이다. 아래 896개 통과는 a19aa20의 리뷰 수정 전 전체 실행 기록이다.

## 백로그 14 실제 Worker 수명주기 (2026-11-19)

- 기준은 원격 main `8d093fbeb2a3b622c7635a58f47527ccd6c431a6`, 작업 브랜치는 `verify/worker-lifecycle-abcd`다.
- 허가 원본 `data/research/samples/A.MOV`, 기존 Gate·MotionPhys·SyncNet 가중치와 WaveRep 체크포인트, 모델별 기존 venv를 사용했다. 시나리오마다 로컬 API 포트·레지스트리·DB·runtime을 따로 생성했다.
- `scripts/verify_real_worker_lifecycle.py`를 확장했다. 목표 자식과 DB 단계를 확인한 뒤 개입하고, 복구 시 이전 시도 폴더에 남긴 표식 제거와 DB의 두 번째 시작 시각을 확인한다. ps 조회 오류는 검증 실패로 처리한다. 제품 코드와 정책 변경은 없다.
- 재현 명령은 trinity 환경에서 `python scripts/verify_real_worker_lifecycle.py --new-run --only cancel-motionphys --only sigkill-gate --only sigkill-waverep --only sigkill-motionphys`다. 두 번 실행하면 Git 밖 `data/research/real-lifecycle/run-*/`에 회차별 JSON이 남는다.
- 기존 테스트 기준선은 `python -m pytest -q` 895 통과, 0 실패, 1 건너뜀이다. 검증기 단위 테스트 `python -m pytest -q tests/test_verify_real_worker_lifecycle.py`는 기존 5건과 ps 실패 회귀 1건 모두 통과했다. 최종 전체 테스트 `python -m pytest -q -rs`는 896 통과, 0 실패, 1 건너뜀(LightGBM 미설치), 경고 1건이었다.
- 로컬 커밋 전 리뷰에서 실패한 저장 결과를 재실행 없이 성공으로 처리하는 경로를 수정했다. A~D 기록의 supervisor·목표 자식, 복구 Worker 종료 코드, 취소 관찰 시간도 확인한다. 수정 후 관련 테스트 7개 통과, 저장된 두 회차 JSON 8건 모두 재대조 통과. 위 전체 테스트 수치는 리뷰 수정 전 실행 로그 기준이다.
- 실제 결과 파일은 `data/research/real-lifecycle/{run-27rjrq6a,run-5cgifdde}/`에 있다. 두 회차 모두 A~D 완료 조건을 JSON과 대조했다.

| 시나리오 | 실제 결과 | 회차 1 / 2 실측 |
|---|---|---|
| A Gate 중 SIGKILL | 2/2 복구 | lease 만료 후 0.370 / 0.153초에 재선점 |
| B WaveRep 중 SIGKILL | 2/2 복구 | 0.004 / 0.026초에 재선점 |
| C MotionPhys 중 SIGKILL | 2/2 복구 | 0.477 / 0.079초에 재선점 |
| D MotionPhys 중 API 취소 | 2/2 취소 | DELETE 202 후 1.700 / 1.785초에 cancelled |

- A~C는 6건 모두 첫 시도 supervisor·목표 자식의 종료와 빈 프로세스 그룹을 확인했다. 두 번째 시도에서 이전 폴더 표식이 사라졌고 각각 finished / completed / abstained, 세 축 completed, signal·physics raw_score 및 overall_score·verdict_label은 null, 보류 원인은 no_valid_fusion_model이었다. D는 attempts=1, 축 결과와 점수 없이 cancelled였다.
- 개입 순간의 스냅샷에는 활성 FFmpeg가 없었다. 복구 시도에서는 실제 FFmpeg를 관찰했고 종료 후 관찰한 후손이 모두 사라졌다. 8건 모두 작업 종료 후 1초 재확인에서 작업 폴더·작업 프로세스가 없었고 실행기 종료 뒤 전용 runtime이 비었다. 실제 축 실패를 별도로 유발하는 사례는 이번 8건에 없었다.
- 다음 작업은 활성 FFmpeg 중 개입을 직접 확인할 필요가 있을 때 그 시점에 맞춘 별도 검증이다. 백로그 14의 정식 인증·rate limit은 별도 작업이다.

## 설계 문서 상태 갱신 (2026-11-19, 브랜치 `docs/design-status-refresh`)

- 한 일(문서만, 코드 변경 없음): `docs/DESIGN.md`
  1. 하단 "서버 실행 방법" 첫 문단을 지금 동작으로 고침. Gate가 구간을 찾으면 세 축을 실제 모델로 실행한다. 한 축이 없거나 실패하면 그 축만 `error`이고 `partial`이다. 묶음이 없어 판정은 항상 보류(`no_valid_fusion_model`)이고 점수·라벨은 `null`이다. 문장은 코드(`server/axes/*`, `server/jobs/worker.py`)와 2026-11-19 실제 Worker 실행 결과로 확인했다.
  2. §14.1 백로그 15행의 상태를 모두 "상태(2026-11-19)"로 새로 씀. 상태 칸이 없던 2·4·5·15번에도 넣었다. 칸 끝에 근거 문서 경로를 적었다.
  3. §15.3 결정 1~12 요약 표의 "검증 상태"를 같은 방식으로 새로 씀(날짜와 근거 경로).
  4. §15.4에 "워터마크·C2PA 등 출처 증명 신호는 초기 구현 외, 탐지 축과 별도 신호로 검토." 한 줄을 추가.
- 옛 상태 문구는 "(이전: …)"으로 남기지 않고 새 상태로 바꿨다. 옛 문구는 Git 이력에 있다. 지시 문장("옛 상태는 지우지 말고 '(이전: …)'으로 남기지 말고 그냥 날짜와 함께 새 상태로 바꿔")을 "이전 표기로 남기지 말고 새 상태로 바꾼다"로 읽었다. 다르게 뜻하셨으면 고친다.
- 근거를 못 찾은 칸은 없었다. 칸 안에서 확인하지 못한 부분은 "확인 필요"나 "미검증"으로 적었다(예: YouTube Studio 다운로드, TalkingHeadBench 접근 절차, CPU 대체 실제 상황, 다중 발화).
- 고치다 바로잡은 것: 결정 4(WaveRep)의 "점수 보정 미구현"은 틀린 문구였다. 학습 파이프라인이 후보마다 OOF sigmoid 보정을 한다(`docs/training-pipeline.md`). 그래서 "합성 데이터에서만 확인"으로 적었다.
- `pytest -q`(이 브랜치): **895 passed, 1 skipped**(문서만 바꿔 main과 같음, 건너뜀은 trinity에 LightGBM 없음).
- 막힌 점: 없음. PR은 이 브랜치로 생성, merge는 사용자 지시 후.

## 오디오 트랙 선택 통일 (2026-11-19, 브랜치 `fix/audio-track-select`)

- 한 일: Gate VAD·SyncNet 구간 절단·압축 에뮬레이터가 **같은 함수**(`server/gate/audio_track.py`)로 오디오 트랙을 고르고 `-map 0:<index>`로 명시해 쓴다. 규칙(사용자 지시): 디코딩 가능한 오디오 중 default 표시가 있는 것(여럿이면 index가 작은 것), 없으면 첫 번째 디코딩 가능한 것. 디코딩 가능 = ffprobe `codec_name`이 `ffmpeg -codecs`에서 D 표시인 오디오 코덱(태그로 판단하지 않음).
- 사용자 결정(D1~D4 모두 권장안): D1 세 경로가 같은 함수를 각자 부름(SyncNet 요청 형식·어댑터 그대로), D2 에뮬레이터는 고른 트랙이 AAC가 아니면 `error` / `audio_not_copyable`(2026-11-16 "첫 AAC" 결정 대체) + 에뮬레이션 요약에 개수·이유 집계, D3 Gate·SyncNet 특징 버전에 `audio_track_rule`, D4 docs/DESIGN.md §15.3 "결정 2·7 보완(오디오 트랙 선택)"(문안은 PR에서 확인 받기로 함).
- **바꾸지 않은 것:** `has_audio`, 원인 코드(고를 트랙이 없으면 Gate는 지금처럼 `media_unreadable`, SyncNet 구간은 `error` / `inference_error`), API 필드·상태 값, 연구용 스크립트(`scripts/diagnose_syncnet_offset.py`, `research/gate/compare_vad.py`).
- 동작 변화(합성 영상): c2(default가 두 번째)·c5에서 SyncNet이 1→2, c2에서 에뮬레이터 1→2, c3(default가 pcm)에서 에뮬레이터가 AAC 트랙 복사 → `error`, c6(MKV, default 없음)에서 Gate가 2(FFmpeg는 채널 수로 고름)→1. 이제 다섯 사례 모두 세 경로의 index가 같다. 표는 `docs/gate.md` "구현 (2026-11-19)".
- 원본 A~E: 고른 트랙이 예전과 같은 index 1이고 Gate PCM이 예전 명령과 바이트 단위로 같다(테스트). 에뮬레이터 출력 바이트도 같은 트랙이라 그대로다.
- **학습 특징 캐시 키:** 코드만 바꾸면 키가 안 바뀌어(키 = 입력 sha256·축·특징 버전·구간·schema) 선택이 바뀌는 다중 오디오 파일에서 옛 Gate·SyncNet 캐시를 잘못 다시 쓸 수 있었다. D3로 두 축의 키와 묶음 특징 버전이 한 번 바뀐다. WaveRep·MotionPhys 키는 그대로(오디오를 안 읽고, 키의 Gate 구간을 따라감). 변경 시점에 특징 캐시·묶음이 없어 다시 계산할 것은 없었다.
- 에뮬레이터 기록 `schema_version` 3(`audio.rule`, 트랙별 `default`·`decodable`, `reason_code`). 요약은 화면과 `<out-manifest 이름>.summary.json`(덮어쓰지 않음).
- 실제 확인(A, 실제 API 서버 + 별도 Worker, 기본 설정, 임시 레지스트리·DB): finished / completed / abstained, 세 축 completed, 적합 구간 37.021초, 설명 항목 목록이 2026-11-19 SIGKILL 확인 때(기본 설정)와 같다. 단계 Gate 12.3·WaveRep 18.6·MotionPhys 38.0·SyncNet 149.1초, 전체 219.1초. 장치 mps / cpu / mps. 남은 프로세스·작업 폴더 없음. SyncNet 실행기(research venv)가 새 공용 함수를 import해 정상 동작했다.
- 테스트: `tests/test_audio_track.py`(26개, 새 파일), `tests/test_syncnet_runner.py`(+3), `tests/test_emulator.py`(오디오 테스트를 새 규칙·요약으로 교체, 32개), `tests/test_feature_extract.py`(+1).
- `pytest -q`: **895 passed, 1 skipped**(main 864 + 새 테스트 31, 건너뜀은 trinity에 LightGBM 없음).
- 문서: docs/DESIGN.md §15.3, `docs/gate.md`, `docs/syncnet-adapter.md`, `docs/compression-emulator.md`, `docs/training-pipeline.md`.
- **남은 일:**
  1. 본인 영상 YouTube 일부 공개 업로드 → Studio 다운로드 처리본으로 축별 점수 변화 측정(시연 방식 (b)와 함께 결정).
  2. 실제 서비스 입력(허가 미디어)과 DeepSpeak의 오디오 트랙 구성 확인(다중 오디오가 있으면 이번 규칙이 실제로 갈리는 경우가 생긴다).
- 막힌 점: 없음. PR은 이 브랜치로 생성, merge는 사용자 지시 후.

## 작은 확인 3건 (2026-11-19, 브랜치 `chore/small-checks`)

**제품 코드 변경 없음.** 커밋 3개(확인별 하나씩).

1. **오디오 트랙**(`docs/gate.md`·`docs/syncnet-adapter.md` "오디오 트랙 선택 확인"): 원본 A~E는 오디오가 2개(index 1 AAC 2ch default, index 2 apac 4ch, FFmpeg 8.0.1에 apac 디코더 없음). Gate VAD(`-map` 없음 → FFmpeg 자동 선택), SyncNet(`cut_segment`의 `-map 0:a:0`), 압축 에뮬레이터(첫 AAC)가 **모두 index 1**을 읽는다(PCM sha256 일치, A·B·E 변형 36개의 AAC 패킷도 원본 index 1과 같음). 로컬 MAVOS-DD 표본 2,160개는 모두 AAC 1개.
   - 트랙 구성이 다르면 어긋난다(합성 사인파 영상): 첫 오디오가 default가 아니면 Gate만 다른 트랙(c2), 첫 오디오가 AAC가 아니면 에뮬레이터만 다른 트랙(c3), 둘 다면 SyncNet만 다른 트랙(c5). apac만 있는 파일은 `has_audio=True`인데 디코딩 실패로 `media_unreadable`.
   - **제안만(결정 필요):** 오디오 index를 한 함수로 한 번 정해 Gate·SyncNet 요청·에뮬레이터가 같이 쓴다. `has_audio`를 "디코딩 가능한 오디오"로 바꿀지(§10 원인 코드)도 결정 필요.
2. **MotionPhys margin**(`docs/motionphys-adapter.md` "LightGBM margin 일치 확인"): 합성 특징(504차원)으로 `research/training/train.py`를 그대로 학습하고, 서버 경로(`infer_axis._margin`, MotionPhys venv)가 낸 margin을 학습 쪽 `predict(raw_score=True)`(메모리 모델, `scores/M-*.csv`)와 비교했다. dev·test 255행(후보별 85) **모두 비트 단위로 같다**. 어댑터 프로세스 경로(후보 3개)와 실제 영상 A(full, 2.701591943937307)도 같다. 두 venv 모두 lightgbm 4.7.0·numpy 2.4.6. 새 테스트 `tests/test_motionphys_margin_parity.py`(5개, venv 없으면 건너뜀, 약 7초).
   - 여전히 미검증: 실제 데이터 모델, 실제 영상의 `face_motion`(1512차원), 실제 묶음으로 Worker가 판정까지 가는 종단.
3. **라이선스 표** `docs/licenses.md`(새 파일): 항목마다 라이선스·근거·상업 이용·확인 상태. 새로 확인: MediaPipe 모델 카드 3개 모두 Apache-2.0(전에는 확인 필요), FFmpeg 빌드 GPL v3 이상(`--enable-gpl --enable-version3`, nonfree 없음), webrtcvad 패키지 MIT, DeepSpeak v2·TalkingHeadBench 카드 문구. **결론: 지금 구성은 상업 이용 불가**(WaveRep 코드 비영리 전용, MAVOS-DD NC).
   - 확인 필요로 남김: WaveRep·DINOv2 가중치, 저장소 자체 라이선스(MotionPhys 재구현 포함, 루트 LICENSE 없음), SyncNet·S3FD 가중치의 상업 이용, webrtcvad에 포함된 WebRTC 코드, DeepSpeak 라이선스 본문, TalkingHeadBench 원본 데이터셋 조건, HiDF(공식 출처 못 찾음).
- 함께 고친 문서: `docs/motionphys-spec.md` §7·`docs/gate.md`·`docs/dataset-access.md`·`docs/training-pipeline.md`에 새 결과를 가리키는 줄(옛 기록은 지우지 않음), README 할 일 목록에서 끝난 3줄을 빼고 "결정 대기"에 2줄 추가.
- 임시 파일: 합성 영상·apac 클립·SyncNet 절단 클립은 확인 뒤 지웠다. 모델 카드 PDF는 세션 임시 폴더에만 있다.
- `pytest -q`: **864 passed, 1 skipped**(main 859 + 새 테스트 5, 건너뜀은 trinity에 LightGBM 없음).
- 막힌 점: 없음. PR은 이 브랜치로 생성, merge는 사용자 지시 후.

## Worker 장치·열 상태 기록 (2026-11-19, 브랜치 `feat/worker-device-log`)

- 한 일: WaveRep·MotionPhys·SyncNet 실행기마다 실제 장치(`device_used`)와 실행 시작·끝의 macOS thermalState를 Worker 로그 한 줄과 jobs 테이블의 내부 열 `run_info_json`에 남긴다. **API 필드·상태 값 변경 없음**(결과·축 키 집합이 스키마와 같은 것을 테스트·실제 실행으로 확인).
- 사용자 결정: 결과 JSON에는 API 계약을 바꾸지 않는 내부 자리가 없어 jobs 내부 열에 둔다(D1=B). 재선점 때 지우지 않고 **시도 번호별로 쌓는다.** 실행은 Native.
- 형식·근거: `docs/syncnet-adapter.md` "Worker 장치·열 상태 기록". 계획 `docs/superpowers/plans/2026-11-19-worker-device-log.md`. 요약: MotionPhys는 MediaPipe 기본 delegate(CPU)라 실행기가 `cpu`를 보고하고, thermalState는 Worker 밖의 짧은 프로세스(ctypes)로 읽는다(실패하면 `null`/`unknown`, 작업에 영향 없음).
- 실제 확인(A, 실제 API 서버 + Worker): 기본 설정 2회 `mps / cpu / mps`, `TRINITY_SYNCNET_DEVICE=cpu` 1회 `mps / cpu / cpu`. 리뷰 수정 뒤 코드로 기본 설정 1회 더(같은 결과). 세 번 모두 finished / completed / abstained, 로그와 기록 값 일치, thermalState 내내 `fair`(Swift로 직접 읽은 값과 같음), 작업 폴더·프로세스 남지 않음.
- 실제로 보지 못한 것: thermalState가 실행 중 바뀌는 경우, 실제 SIGKILL 뒤 2차 시도 기록(둘 다 테스트로만 확인).
- 최종 리뷰(작성자 자체 검토)에서 고친 것: 프로브·기록이 SyncNet 마무리 여유 10초를 최악의 경우 넘길 수 있었다(축 제한을 시작 프로브 전에 계산, 프로브 2초, 기록 잠금 대기 5초). 축 제한을 시작 프로브 뒤에 재고, 프로브 제한 1초, 기록 잠금 대기 1초로 줄였다(최악 약 7.1초 < 10초). 테스트 3개 추가.
- 바뀐 파일: `server/jobs/device_state.py`(새), `server/axes/device.py`(새), `server/axes/__init__.py`·`signal`·`physics`·`alignment`, `server/axes/physics/motionphys.py`, `research/motionphys/infer_axis.py`(`device_used: "cpu"`), `server/jobs/queue.py`(열·이전 DB에 열 추가·`save_run_info`), `server/jobs/worker.py`, `tests/conftest.py`(프로브 스텁), 새 테스트 4개 파일(29개).
- 실행 방법: 평소대로 `python -m server.jobs.worker`. 기록 읽기는 문서의 SQL 예시.
- `pytest -q`: **859 passed, 1 skipped**(main 830 + 새 테스트 29, 건너뜀은 LightGBM 없음).
- 막힌 점: 없음. PR은 이 브랜치로 생성, merge는 사용자 지시 후.

## 우연 채택률 1,000명 재측정 (2026-11-19, 브랜치 `audit/null-rerun-1000`)

- 한 일: `scripts/audit_null_adoption.py --identities 1000 --seeds 100`(커밋된 설정, dev 조건만 `["original"]`)을 main `5aa7acf` 기준으로 끝까지 돌렸다(02:04~02:30, 시드당 약 16초, 중단 없음). `docs/audit-training-pipeline.md` 표에 "결정 반영 후 1,000명" 행과 "W의 FPR 관문 통과" 열을 더했다.
- 결과: **결합 채택 0/100, WaveRep 단독 0/100, 보류 100/100**(각 정확 95% 상한 3.6%), 학습 거부 0. test 진짜 400개(100그룹).
- **FPR 관문 통과: W 20/100**(정확 95% CI 12.7~29.2%). 이 크기에서는 관문을 넘을 수 있다(120명은 구조적으로 0). 100회 모두 정확 상한이 관문을 정했다(bootstrap 상한만이면 92/100). 진짜 100그룹에서는 test 영상 FPR 4.0% 이하일 때만 통과한다.
- W의 AUC 관문은 1/100이었고 그 시드는 FPR 관문에서 떨어져 WaveRep 단독은 0. 고른 결합의 자기 FPR 관문 26/100, 결합 전용 관문을 모두 넘은 시드 0. 후보 6개 중 하나라도 자기 관문을 다 넘은 시드 7/100(여러 번 비교 효과, 판단에는 안 씀).
- 한계: 100회로는 1% 아래 비율을 가를 수 없다. WaveRep 단독의 우연 비율은 두 관문이 독립이면 약 0.5%로 **추정**될 뿐 측정이 아니다.
- 코드: `scripts/audit_null_adoption.py`가 시드별 관문 값(`w_fpr_gate_value` = max(bootstrap, 정확 상한))·정확 상한·test 영상 FPR·후보별 AUC/FPR 관문 통과·고른 결합과 결합 전용 관문 통과를 더 남기고, 요약에 관문 통과 횟수를 낸다. **판단 논리 변경 없음.** 테스트 `tests/test_audit_null_adoption_script.py`(3개, 학습·리포트는 가짜).
- `pytest -q`: **818 passed, 1 skipped**(건너뜀은 LightGBM 없음).
- 결과(Git 밖): `data/research/audit-null/identities1000-seeds100/`(`results.jsonl`, 시드 폴더, 약 780MB), 로그 `data/research/audit-null/identities1000-seeds100.log`.
- 막힌 점: 없음. PR은 이 브랜치로 생성, merge는 사용자 지시 후.

## 실제 Worker 수명주기 확인 (2026-11-19, 브랜치 `research/real-timeout-verify`)

- 한 일: 실제 API 서버와 별도 Worker, 실제 영상 A(임시 레지스트리의 테스트 ID)로 세 가지를 확인했다. **제품 코드·기본값 변경 없음**(설정은 시나리오별 환경 변수만). 상세 표는 `docs/syncnet-adapter.md` "실제 Worker 수명주기 확인".
  - (가) SyncNet 단계 제한: 길이 규칙(`TRINITY_SYNCNET_TIMEOUT_BASE_SECONDS=30`, 계수 0)과 남은 시간 경로(`TRINITY_JOB_TIMEOUT_BASE_SECONDS=150`, 계수 0) 모두 작업 **finished / partial / abstained**, SyncNet만 **error / timeout**(30.05초, 37.71초), signal·physics completed. 남은 시간 경로는 작업 제한 150초보다 약 10초 먼저(140.05초) 끝났다.
  - (나) SyncNet(MPS) 실행 중 Worker SIGKILL 2회: supervisor·SyncNet 실행기가 0.074·0.075초 안에 종료. 작업 폴더는 남았다가 복구 때 정리. 새 Worker가 lease 만료(kill 때 남은 28.1초)에 맞춰 28.2초 뒤 재선점, 2차 시도 finished / completed, 시도 2.
  - (다) MPS 실행 중 API 취소: SyncNet 실행 중 8.24초(heartbeat 10초), WaveRep 실행 중 1.88초(heartbeat 2초로 낮춤) 만에 cancelled, 자식 종료, 작업 폴더 삭제, Worker 종료 코드 0. MPS 사용 근거는 1초 스택 표본의 Metal/MPS 프레임(148~539개).
- "미검증" 항목 갱신: 이 파일의 해당 줄(작업 제한 정책·SyncNet 단계 제한·실제 모델 취소·SIGKILL)과 `docs/syncnet-adapter.md`, `docs/waverep-adapter.md`, `docs/motionphys-adapter.md`에 결과를 덧붙였다. 옛 기록은 지우지 않았다.
- 여전히 미검증: MotionPhys·Gate·WaveRep 실행 중 Worker SIGKILL, MotionPhys 실행 중 취소, CPU 대체 상황, B·E, 반복 안정성(SIGKILL 2회, 나머지 1회). 실행기의 `device_used`는 Worker 결과·로그에 없어 직접 확인 못 함.
- 측정 실수: SIGKILL 1회차의 "kill 때 lease 남은 시간"을 작업이 끝난 뒤 계산해 잘못된 값이 나왔다. 스크립트를 고치고 2회차를 다시 쟀다(다른 항목은 1회차도 유효).
- 추가 파일: `scripts/verify_real_worker_lifecycle.py`(실제 서버·Worker 수명주기 확인), `tests/test_verify_real_worker_lifecycle.py`(5개, 프로세스 찾기·단계 시간). 결과 JSON은 Git 밖 `data/research/real-lifecycle/`. 임시 레지스트리·DB·로그·작업 폴더는 지웠다.
- 실행 방법: `conda activate trinity && python scripts/verify_real_worker_lifecycle.py`(약 15분, 된 시나리오는 건너뜀).
- `pytest -q`: **820 passed, 1 skipped**(건너뜀은 LightGBM 없음).
- 막힌 점: 없음. PR은 이 브랜치로 생성, merge는 사용자 지시 후.

## SyncNet Worker 안 대 단독 시간 차이 (2026-11-18~19, 브랜치 `research/syncnet-worker-gap`)

- 한 일: `docs/syncnet-adapter.md` 측정 방법의 (a) Worker 전체 경로, (b) 앞 단계 가짜 Worker, (c) 단독 실행을 같은 세션에서 라틴 방격 순서로 각 3회 이상(c는 5회) 쟀다. 원인을 가르려고 (d) Worker 없이 실제 앞 단계 직후 단독, (e) 모델 없이 순수 CPU 열 68초 직후 단독을 각 3회 더했다. 17회, 실패 0. SyncNet은 원래 차이가 난 조건인 CPU(측정용 환경 변수). **제품 코드·기본값 변경 없음.**
- 측정 전 기기 상태(`pmset -g batt`): 20W 충전기 연결·충전 중, 배터리 34%(끝날 때 73%). 기기는 팬 없는 MacBook Air M3(`Mac15,12`). 실행마다 쿨다운(최소 180초 + thermalState 0 + CPU 탐침 회복)을 맞췄다.
- 결과(SyncNet 초, 평균): a 281.1, b 241.0, c 253.3, d 289.0, e 276.2. mediaanalysisd가 돈 3회를 빼면 차게 시작한 b·c 244.7초 대 앞에 부하가 있던 a·d·e 275.9초(+12.8%). 17회 모두 트랙 결과가 완전히 같다.
- **판단:** Worker 경로 자체는 원인이 아니다(b ≈ c, 배제). 앞 단계가 남긴 것·파일 캐시·메모리·MPS 상태도 배제(d·e가 같은 만큼 느림, swapout 0). 이번 세션의 차이는 **앞 단계가 데운 기기의 열 제한**으로 설명된다(앞 부하 뒤 9회 모두 SyncNet 시작 19초 안에 thermalState 1, S3FD 프레임당 0.165 → 0.22~0.25초, FFmpeg도 약 25% 같이 느려짐). 다른 프로세스(mediaanalysisd) 부하가 +9~12% 더한다.
- **원래 차이(약 400초 대 274~294초)는 확정하지 못했다.** 확인한 두 요인으로 약 1.26배(약 345~370초)까지 설명되고, 나머지는 기록되지 않은 2026-11-16 세션 상태(남은 가설)다. CPU 주파수는 root 권한이 없어 직접 재지 못했다.
- 제안만(코드 변경 없음): Worker 수정 불필요, 작업·SyncNet 제한 계수는 그대로 충분(최댓값 305.3초 = 1초당 8.2초). Worker 로그에 SyncNet `device_used`·thermalState를 남기는 관측 개선은 결정 필요.
- 추가 파일: `scripts/measure_syncnet_worker_gap.py`(측정 하네스), `research/syncnet/profile_adapter_shim.py`(어댑터 자리의 프로파일 실행기, 측정 전용), `tests/test_measure_syncnet_worker_gap.py`(7개). 결과 JSON은 Git 밖 `data/research/syncnet-worker-gap/runs/`. 임시 레지스트리·DB·작업 폴더는 실행마다 지웠다.
- `pytest -q`: **822 passed, 1 skipped**(건너뜀은 LightGBM 없음).
- 실행 방법: `docs/syncnet-adapter.md` "Worker 안 대 단독 — 같은 세션 교차 측정"의 재현 절.
- 막힌 점: 없음. PR은 이 브랜치로 생성, merge는 사용자 지시 후.

## README 첫 화면 분리 (2026-11-18, 브랜치 `docs/readme-front`)

- 한 일: 기존 설계 README를 `docs/DESIGN.md`로 옮기고(내용 그대로, 머리말 "README v6.0"만 "설계 문서 v6.0"으로), 저장소 첫 화면용 `README.md`를 새로 썼다. `AGENTS.md`의 설계 기준·절 참조를 `docs/DESIGN.md`로 바꿨다.
- 참조 정리: 저장소 전체의 `README §N`·`` `README.md` §N`` 225곳(87개 파일, 코드는 주석·docstring·생성 문서 문구만)과 "README 하단 서버 실행 방법" 등 몇 곳을 `docs/DESIGN.md`로 바꿨다. `app/README.md`·`training/README.md`·외부 저장소 README 참조는 그대로다.
  - **그대로 둔 과거 기록:** 이 파일의 "바뀐 파일" 목록·git 명령·충돌 기록(PR #12·#13 통합 재현 명령, 취소·삭제, Gate→Worker 연결, PR #9·#10)과 `docs/superpowers/plans/`의 Files 목록에 나오는 `README.md`는 당시 파일 이름이라 고치지 않았다. **2026-11-18 이전 기록의 `README.md`는 지금의 `docs/DESIGN.md`다.**
- 새 README의 사실을 저장소 문서와 대조해 고쳤다(SyncNet 실측을 11-18 재측정으로, 우연 채택률, 채택 기준, 견고성 측정 영상 수, 데이터셋 상태 등). 저장소에 근거가 없어 확인하지 못한 문구는 PR 설명에 남겼다.
- 옮기는 일(`README.md => docs/DESIGN.md`, 내용 변경 없음)은 앞 세션에서 `audit/null-rerun` 커밋 `7cdbf6b`(PR #22)에 함께 들어갔다. #22는 고치지 않기로 했다(사용자 결정). PR #23을 main 기준으로 바꿔 그 커밋까지 함께 merge한다. merge commit으로 합치면 #22는 merge된 것으로 표시되고, squash로 합치면 #22를 직접 닫는다.
- 남은 일: `docs/DESIGN.md` 하단 "서버 실행 방법" 첫 문단("물리·정합 축은 stub")이 현재 동작보다 오래됐다(이번에는 고치지 않음).

## 우연 채택률 재측정 (2026-11-18, 브랜치 `audit/null-rerun`)

- main `f9cfcf4`(감사 결정 반영 후)에서 `scripts/audit_null_adoption.py --identities 120 --seeds 200`을 다시 돌려 `docs/audit-training-pipeline.md` 해당 절에 "결정 반영 후" 행을 추가했다. 코드 변경 없음.
- 결과: 결합 채택 0/200, WaveRep 단독 0/200(반영 전 3/197). 단 120명 데이터는 test 진짜 그룹이 12개라 A10 정확 상한 때문에 FPR 관문을 구조적으로 넘을 수 없어, 이 0은 우연 채택이 줄었다는 증거가 아니다.
- **남은 일:** 관문이 통과 가능한 크기(진짜 그룹 약 100개 이상, 인물 800~1,000명)에서 다시 재야 의미 있는 비율이 나온다(시드당 약 1분). `pytest`는 문서만 바꿔 다시 돌리지 않았다.
  → 2026-11-19 인물 1,000명·시드 100회로 측정(맨 위 "우연 채택률 1,000명" 절).
- PR: 이 브랜치로 생성. merge는 사용자 지시 후.

## 감사 결정 반영 (2026-11-18, 브랜치 `audit/decisions`)

- 사용자 결정(감사 제안 A9·A10·A11·A15·A16·A17)을 구현. docs/DESIGN.md §15.3 "결정 5·6·7·8·12 보완(독립 감사 결정) — 2026-11-18"에 서버 조건 (6)~(9)와 A9·A10·A11·A15를 적었다. 세부는 `docs/audit-training-pipeline.md` "결정 반영", `docs/training-pipeline.md`.
  - A9: 공용 서빙 규칙 `training/serving.py`. 선택 후보는 축이 모두 성공하고 입력이 있으면 사용, 대체 후보는 서버에서 쓰일 test 영상(축 성공 패턴이 정확히 같은 영상)에서 자기 관문 + 최소 그룹 수(진짜·가짜 각 36)를 넘어야 서빙. 학습의 축 성공은 서버와 같은 함수(MotionPhys `full` 기준), `availability.csv`. 묶음 형식 3(후보 역할).
  - A10: FPR 관문 = max(그룹 bootstrap 상한, Clopper–Pearson 상한(n = 진짜 그룹 수, k = n × 영상 FPR)). 처음 지시 공식(k = 오탐 있는 그룹 수)은 관문을 통과 불가능하게 만들어 계획 단계에서 (b)로 바꿔 승인받음.
  - A11 `ungroupable_video` 오류, A15 최종 평가 전용 압축은 관문 뒤 `test_held_out`에 1회 보고(탐지 지표 포함, 채택 판단에 사용하지 않음), A16 묶음 생성 전 재현 검증(`--manifest`·`--features` 필수, `features.jsonl` 위조는 못 잡음), A17 TPR 차이는 두 후보가 모두 점수를 낸 가짜에서.
  - A7 남은 부분(MAVOS-DD 파일 해시)은 보류.
- 바뀐 테스트 기대: "세 축이 다 성공하면 2축 모델로 보류"는 이제 W+M 판정. 합성 "채택 도달" 시나리오는 인물 1,000명·테스트 설정 목표 FPR 2%로 키웠다(커밋된 설정은 5%). 묶음 fixture는 대체 후보 경로를 시험하려고 테스트 설정에서만 `max_coverage_drop` 0.6.
- **알아 둘 것:** FPR 관문은 test 진짜 *그룹*이 충분해야 넘는다(영상 FPR 5%면 약 150그룹). 결합 채택의 판정 제공 비율 관문(5%p) 때문에 대체 후보가 쓰일 영상은 원래 적어, 실제로는 대체 후보가 서빙되지 않는 경우가 많을 것이다.
- `pytest -q`: 반영 전(main `7933fdc`) 797 passed, 1 skipped, 5 xfailed → **815 passed, 1 skipped**(xfail 0, 건너뜀은 같은 LightGBM 없음). 감사 xfail 5개는 모두 보통 테스트로 바꿨다.
- 우연 채택 시뮬레이션은 결정 반영 뒤 다시 재지 않았다(미측정).
- PR: 이 브랜치로 생성. merge는 사용자 지시 후.

## 학습 파이프라인 독립 감사 (2026-11-18, 브랜치 `audit/training-pipeline`)

- 한 일: 학습·평가·묶음·서버 관문을 공격 시나리오 6종(누수, 임계값·선택 오염, 관문 우회, 서버·학습 불일치, 통계 함정, 정직성)으로 감사. 결과는 `docs/audit-training-pipeline.md`.
- 재현 테스트: `tests/test_audit_training_pipeline.py`. 고친 것 11건(A1~A8, A12~A14. A7은 이름 표기만, 내용 비교는 제안), 제안만 6건(A9·A10·A11·A16·A17은 지켜야 할 성질을 `xfail(strict=True)`로 고정, A15는 결정 대기라 지금 동작을 고정한 테스트).
- **높음 3건:** A1 리포트의 판단·서빙 목록만 고쳐도 묶음·서버가 받아들였다 → 리포트 지표로 판단을 다시 계산해 확인(고침).
  A2 커밋된 `configs/training.json`과 다른 설정(느슨한 채택 기준)으로 학습해도 통과 → 묶음·서버가 설정 일치를 확인(고침). **설정을 바꾸면 묶음을 다시 만들어야 한다.**
  A9 서버는 성공한 축 집합과 정확히 같은 후보만 써서, W·W+M이 검증한 집단과 다른 집단(다른 축이 실패한 영상)에서만 판정한다(제안만, §15.3 결정 필요).
- 사용자 결정 반영: 480p는 test 관문에서 빼고 따로 보고(A6, `out_of_range_compression_profiles`). 최종 평가 전용 프로파일을 test 관문에 넣을지는 결정 대기(A15, 지금은 넣고 리포트에 적음).
- 바뀐 형식: 묶음 형식 2(`training_config` 포함), 리포트 형식 2, `features.jsonl`에 `input_sha256`, SyncNet 특징 버전에 `status_rule`(이전 SyncNet 캐시는 다시 계산된다). API 필드·상태 값은 그대로.
- `pytest -q`: 감사 전 766 passed, 1 skipped → **797 passed, 1 skipped, 5 xfailed**(건너뜀은 감사 전과 같은 LightGBM 없음).
- 신호 없는 합성 데이터의 우연 채택(`scripts/audit_null_adoption.py`): 결합 채택 0/234, WaveRep 단독 3/197(120명)·2/37(800명, 시간 때문에 중단). WaveRep 단독은 AUC 한쪽 2.5% 검정과 같아 신호가 없어도 그 정도 나온다(설계대로, 보고에 적을 것).
- **다음 할 일(사용자 결정):** A9 서빙 규칙/검증 방식, A10 FPR 상한 방법, A15 최종 평가 프로파일의 관문 포함 여부, A16 묶음 생성 전 재현 검증, A11 묶을 수 없는 영상 처리. docs/DESIGN.md §15.3 결정 5·8 보완에 감사로 더한 서버 확인 조건을 적을지(문안은 감사 문서).
- PR: 이 브랜치로 생성. merge는 사용자 지시 후.

## 작업 제한 정책 구현 (2026-11-18, 브랜치 `research/worker-remeasure`)

- 사용자 결정: `min(1800, 180 + 20 × 적합 구간 초)`. docs/DESIGN.md §15.3 "결정 9·11 보완(작업 제한) — 2026-11-18, Claude 제안, 사용자 승인". 이유(CPU 대체·기기 2배 지연을 덮음, 제한은 상한일 뿐)는 `docs/syncnet-adapter.md` "작업 제한 정책 결정".
- 구현: Worker가 Gate 직후 작업 전체 제한을 `시작 + 새 제한`으로 다시 정한다. 기존 600초는 Gate 전·Gate 실패(`gate_error`/`gate_timeout`/`media_unreadable`)·Gate 우회 때의 값. 설정 `TRINITY_JOB_TIMEOUT_BASE_SECONDS`(180)·`TRINITY_JOB_TIMEOUT_PER_ELIGIBLE_SECOND`(20)·`TRINITY_JOB_TIMEOUT_MAX_SECONDS`(1800). 초과는 `failed`/`timeout`. API 변경 없음.
- 테스트: `tests/test_job_timeout_policy.py` 24개. `pytest -q` **766 passed, 1 skipped**(LightGBM 없음, SyncNet 단계 제한 포함).
- 실제 미디어로 새 제한을 쓴 Worker 종단 실행은 하지 않았다(**미검증**). 가짜 Gate로 Worker 경로를 확인했다.
  → 2026-11-19 실제 A로 확인: Gate 뒤 작업 제한을 150초로 낮춘 실행에서 Worker가 제한을 다시 정했고(로그 "timeout set to 150s") 작업은 finished(실제 Worker 수명주기 확인(2026-11-19, 맨 위 절)).
- **SyncNet 단계 제한 보완(같은 날, 사용자 승인):** `min(60 + 16 × 적합 구간 초, 남은 작업 시간 − 마무리 여유 10초)`. 기존 `min(600, 남은 시간)` 대체. SyncNet이 느려져도 작업은 finished, SyncNet 축만 `error`/`timeout`, 다른 축 결과 보존.
  여유 10초 근거: 실제 A로 SyncNet을 일부러 timeout시킨 4건의 반환 지연 0.03~0.07초 + fusion 단계 SQLite 잠금 대기 상한 5초 + fusion·마무리 0.002초(문서 "SyncNet 단계 제한 보완"). WaveRep·MotionPhys 300초는 그대로.
  설정 `TRINITY_SYNCNET_TIMEOUT_BASE_SECONDS`(60)·`TRINITY_SYNCNET_TIMEOUT_PER_ELIGIBLE_SECOND`(16)·`TRINITY_JOB_FINALIZE_MARGIN_SECONDS`(10). 테스트 `tests/test_syncnet_stage_timeout.py` 15개.
- 측정 실수: SyncNet 실행기가 `server.config`를 import한다. 측정 중 `server/config.py`를 고치면 실행기가 실패한다(이번에 2건 무효, 다시 잼).
- ~~**미검증:** 실제 Worker에서 SyncNet 단계 제한에 걸리는 종단 실행.~~ → 2026-11-19 확인: 길이 규칙 30초·남은 시간 경로 모두 작업 finished, SyncNet만 `error`/`timeout`, 다른 축 completed(실제 Worker 수명주기 확인(2026-11-19, 맨 위 절)).
- PR: 이 브랜치로 생성, merge는 사용자 지시 후.

## A의 Worker 종단 재측정 (2026-11-18, 브랜치 `research/worker-remeasure`)

- 한 일: `docs/syncnet-adapter.md` "A의 Worker 종단 재측정 방법"대로 1회 측정. 기본 설정(SyncNet MPS, 짧은 구간 규칙), `TRINITY_JOB_TIMEOUT_SECONDS=1800`만 측정용. 제품 코드·기본값 변경 없음.
- 결과: finished / completed / abstained, 세 축 completed, `overall_score`·`verdict_label` null.
  단계: Gate 13.1, WaveRep 19.8, MotionPhys 36.7, **SyncNet 139.0초**, 전체 **208.5초**(적합 구간 37.0초).
- 같은 세션 A 단독 실행(MPS) 137.7초 → Worker 안 SyncNet과 **+1.3초(+0.9%)**. 이 세션에서는 Worker 안·단독 차이가 없었다.
- SyncNet `device_used`는 API 결과·로그·DB에 남지 않아 **직접 확인 못 함**(간접 근거로 MPS 추정, 확인 필요).
- 기기 상태: 열·성능 경고 기록 없음, 새 swapout 없음. **전원 미연결(배터리 100→96%)** — 방법 문서와 다른 점.
- 세션 간 차이가 다시 큼: MPS 단독 A가 11-17 저녁 230~234초, 이번 137.7초. 원인 미확인.
- 작업 제한 재계산(제안만): MPS 기준 `min(1800, 180 + 12 × 적합 구간 초)`(A 624초), 단 CPU 대체·느린 세션은 못 덮음 → 그 경우 계수 20 유지. 상세는 문서 "작업 제한 식 재계산".
- 테스트: 문서만 바꿔 `pytest`는 다시 돌리지 않았다. 임시 레지스트리·DB·runtime·기기 상태 원본은 삭제. 단독 실행 기록은 `data/research/syncnet-perf/runs/A__original__standalone__3__guard-mps.json`(Git 밖)에 남음.
- **다음 할 일:** ~~작업 제한 계수 결정~~(2026-11-18 계수 20으로 결정·구현, 위 절). Worker 안 SyncNet 장치를 확인하려면 측정용 부트스트랩으로 어댑터 반환값을 남겨 다시 잰다. PR은 사용자 지시 후.

## SyncNet 결정 반영 (2026-11-17, 브랜치 `feat/syncnet-perf`)

- 사용자 승인: (가) 짧은 구간 규칙 1안, SyncNet 기본 장치 MPS, dev 압축 조건 2안. docs/DESIGN.md §15.3에 "결정 2·8 보완 — 2026-11-17", "결정 9 보완 — 2026-11-17"(Claude 제안, 사용자 승인) 기록.
- 구현:
  - 실행기가 `min_track` 미만 구간을 `segment_too_short`로 표시(S3FD 생략). `report.aggregate_status`가 그 구간을 빼고 축 상태를 정함. 설명 `SYNCNET_SHORT_SEGMENTS_EXCLUDED`.
  - 서버 결합 입력과 학습 특징이 같은 `report.fusion_features` 사용(축 completed일 때만 값). 일치 테스트 `tests/test_syncnet_rule_consistency.py`.
  - `SyncNetConfig.device`·`Settings.syncnet_device` 기본 `mps`(못 쓰면 cpu, cuda 거부). 특징 버전에 장치 포함.
  - `configs/training.json`: `dev_compression_conditions = ["original", "x264-crf28-720p"]`, `held_out_compression_profiles = [crf34-source, crf34-720p, crf20-source]`(train·dev에 있으면 학습 거부). 480p는 운영 범위 밖으로 따로 보고. `docs/training-pipeline.md` "압축 조건", `docs/compression-emulator.md` §2.
- 실제 확인(1회): B가 MPS·새 규칙으로 `completed`, 짧은 구간 4개 제외, 남은 5구간 오프셋이 기준선과 같음, 135.5초.
- `pytest -q` **727 passed, 1 skipped**(LightGBM 없음).
- 원인 미확인으로 남김: 저녁 CPU 실행 2배 지연(A 285 → 577초).
- **다음 할 일:**
  1. ~~A를 Worker 종단으로 1회 재측정~~ — 2026-11-18 완료(위 절).
  2. ~~작업 제한 정책 결정~~(2026-11-18 결정·구현) (권장 (a) `min(1800, 180 + 20 × 적합 구간 초)`, MPS 기본이면 계수 약 10으로 낮출 수 있음 — 재측정 뒤 다시 계산). 기본값 변경 없음.
  3. ~~Worker 400초 대 단독 270~290초: 같은 세션 교차 측정 + Worker 안 단계 프로파일 + 앞 단계 가짜 Worker 비교~~ — 2026-11-18~19 측정(맨 위 절). Worker 경로는 배제, 앞 단계 열 제한이 세션 안 차이를 설명, 원래 400초 전체는 미확정.
  4. `feat/motionphys-axis`·`feat/training-pipeline`은 main에 병합됨. 이 브랜치와 `research/robustness-run`의 PR은 사용자 지시 후.

## SyncNet 개선 1차 (2026-11-17, 브랜치 `feat/syncnet-perf`)

- 구현: 짧은 구간 건너뛰기(`min_track` 미만 프레임이면 S3FD 생략, 결과 동일 — 가짜 파이프라인 테스트와 A·B·E 실측으로 확인),
  MPS 선택지(`TRINITY_SYNCNET_DEVICE`, **기본 cpu 유지**). upstream·`min_track`·구간 상태 규칙은 그대로.
- 실측(12건, 실패 0): 건너뛰기+CPU는 기준선과 구간 결과가 완전히 같음. MPS는 오프셋·트랙 수 동일, |ΔLSE-C| 최대 0.006(A)·0.122(B)·5e-6(E), 반복 실행 동일.
  S3FD −42~−61%. 저녁 세션의 CPU 실행이 오후 기준선보다 최대 2배 느렸다(A 285 → 577초, 장치와 무관한 FFmpeg 단계도 같이 느려짐, 원인 미확인).
- `pytest -q` **710 passed, 1 skipped**(LightGBM 없음). 측정 뒤에는 문서만 바꿨다.
- 상세·표: `docs/syncnet-adapter.md` "개선 1차".
- **사용자 결정 대기:**
  1. (가) 짧은 구간 규칙: 권장 1안(짧은 구간 제외 + 남은 구간이 하나 이상이고 모두 트랙이 있으면 completed). §15.3 문안은 문서에 있다. 승인 전 규칙 코드 변경 없음.
     승인되면 학습 파이프라인의 SyncNet 특징도 같은 기준의 completed일 때만 쓰도록 맞춘다.
  2. SyncNet 기본 장치를 MPS로 바꿀지.
  3. 작업 제한: 권장 (a) `min(1800, 180 + 20 × 적합 구간 초)`(CPU 기준, Gate 뒤에 다시 정함). 기본값 변경 없음.
- 다음 측정 제안: Worker 400초 대 단독 270~290초는 같은 세션에서 번갈아, Worker 안 단계별 프로파일과 기기 상태(`pmset -g therm` 등)를 함께 잰다(문서에 절차).
- 보류: 영상 한 번만 디코딩(구조 변경), S3FD 검출 간격·해상도 축소(근사, 선택지로만).

## SyncNet 성능 기준선 (2026-11-17, 브랜치 `feat/syncnet-perf`)

- 개선 시도 없음. 승인한 계획의 1번(기준선 측정)만 했다. 상세와 표는 `docs/syncnet-adapter.md` "성능 기준선".
- 추가: `research/syncnet/profile_run.py`(upstream을 감싸는 타이머, upstream·`infer_segments.py` 미수정), `scripts/profile_syncnet_baseline.py`(18건 계획·표).
  결과(Git 밖): `data/research/syncnet-perf/runs/*.json`, `tables.md`.
- 숫자: 프로세스 안 전체 A 285.5초 / B 274.6초 / E 243.5초(standalone 2회 평균). **S3FD 검출이 66~71%**, 영상 준비 19~26%, SyncNet 평가 4~5%.
  supervisor 경유는 standalone과 같음(오버헤드 0.3초). 타이머 없는 어댑터 274.0/312.8/254.1초. 15건 모두 로버스트니스 실측과 트랙 지표 일치.
- E 해상도(CRF 28, 1회): 213.6 → 121.4 → 91.6초(1080→720→480p). 줄어든 122.0초 중 S3FD가 110.0초(90%).
- `tracking_failed` 구간(B 4개, E 1개)은 모두 프레임 49개 이하(`min_track` 50 미만)이고 `_track` 미호출. 완료 구간은 63프레임 이상.
- **미해결:** Worker 안 A의 SyncNet 약 400초 대 어댑터 단독 274~294초 — 원인 미확인.
- 다음(사용자 결정 대기): 개선 시도는 계획의 2번부터. S3FD가 병목이므로 검출 간격·해상도(정확도 영향을 표로 비교)나 장치가 첫 후보다. 작업 제한 정책(계획 3번)은 개선 뒤에 제안.

## 학습·평가 파이프라인 진행 (2026-11-16~, 브랜치 `feat/training-pipeline`, `feat/motionphys-axis`에서 분기)

목표: DeepSpeak v2 승인일에 "데이터 경로만 넣고 실행"하면 단일축 기준선 → 결합 비교 → 채택 판단 → 서버 적용까지 되는 상태.
실제 데이터가 없어 합성 데이터로 검증한다. main 병합·PR 없음. 조각마다 테스트 → 커밋 → push → 이 절 갱신.

**승인된 설계 결정(2026-11-16, Claude 제안, 사용자 승인)**

1. 공식 `test`는 내부 test. 공식 `train`만 그룹 단위로 train/dev. 공식 분할이 그룹을 쪼개면 재분할하지 않고 누수 실패로 멈춘다.
2. 그룹 키: 진짜 `identity`, 가짜 `identity-source|target` + 녹화 ID. 진짜의 녹화 ID는 카드에 없어 `unknown:`(확인 필요).
3. 최대 그룹 비중 상한 기본 25%. 넘으면 학습 거부, 리포트에 그룹 크기 분포.
4. shortcut 진단(코덱·해상도·fps·길이만으로 라벨 예측)은 경고로만.
5. WaveRep 영상 점수 = 프레임 logit 중앙값(주 지표, 사전 고정). 평균·q75는 dev에서만 보조 비교.
6. MotionPhys A/B/C: LightGBM 고정 설정, train 그룹 5-fold OOF, 전체 train 재적합으로 dev·test 점수. 탐색 없음.
7. SyncNet 연구 내부 집계: 전 구간·전 트랙의 LSE-C, LSE-D, |오프셋| 중앙값. API의 집계 보류는 그대로.
8. 결합: 표준화 + L2 로지스틱 회귀(C=1), 입력은 train OOF 점수만, 그룹 해시 5-fold.
9. 후보(사전 고정): W, M-A, M-B, M-C, W+M(dev에서 고른 M), W+M+S. 단순 평균 없음.
10. 보정: 결합 모델을 같은 폴드로 교차 적합한 OOF 예측에만 sigmoid. Brier·ECE 보고.
11. 임계값: dev 진짜 점수에서 FPR 5%, 잠금. test·external로 정하는 경로 없음(시도하면 실패하는 테스트).
12. **dev 압축 조건은 기본값이 없다.** 설정에 명시하지 않으면 학습 진입점이 오류로 멈춘다. 리포트 맨 위에 표시. 사용자가 실측을 보고 정한다.
13. 부분 축 실패: 사용 가능한 축 집합과 정확히 일치하는, 따로 검증된 모델만. 없으면 보류. 결측 대체 없음.
14. 후보 선택은 dev에서만. test는 선택이 끝난 뒤 한 번의 확인 관문. 실패하면 다시 고르지 않고 "WaveRep 단독" 또는 "보류".
15. 채택 조건(설정에 사전 고정): G2 WaveRep AUC 95% CI 하한 > 0.5 / G3 결합 − 기준의 TPR 차이(대응 그룹 bootstrap) 95% CI 하한 > 0 /
    결합의 실제 FPR이 2%p 넘게 나쁘지 않을 것 / 판정 제공 비율이 5%p 넘게 줄지 않을 것 /
    **"WaveRep 단독"이든 "채택 가능"이든 고정 임계값의 test FPR 95% CI 상한 ≤ 10%**(못 넘으면 보류).
    docs/DESIGN.md §13.3에는 숫자 기준이 없다(차이: §13.3 G3은 "단일 최강 모델 대비"라서 결합은 WaveRep과 단일 최강 둘 다 이겨야 하게 구현한다).
16. 신뢰구간: 그룹 bootstrap 1,000회, 고정 시드, 차이는 같은 재표본으로 짝지음.
17. 묶음: `data/models/fusion/<id>/`(Git 제외). 서버는 순수 파이썬으로 계산.
18. `configs/fusion_bundle.json`에 묶음 digest만 커밋(기본 비어 있음).
19. 묶음이 통과했을 때 기존 필드에 값이 채워진다(새 필드·상태 없음). **조각 4 코드 전에 §15.3 문안을 보여 주고 멈춘다.**
20. 학습 환경 `research/training/.venv`(numpy, scikit-learn, lightgbm). trinity에는 추가 없음.

| 조각 | 내용 | 상태 |
|---|---|---|
| 1 | 데이터셋 어댑터, 일괄 특징 추출, 파생본 split 상속 | **완료** (아래) |
| 2 | 단일축·OOF 결합·보정·임계값 잠금 | **완료** (아래) |
| 3 | 비교 리포트(JSON+Markdown)와 채택 판단 | **완료** (아래) |
| 4 | 묶음과 서버 관문 | **완료** (아래) |
| 검증·마무리 | 합성 종단 4종, §15.3, docs/DESIGN.md §14.1 8·12번, `docs/training-pipeline.md` | **완료** |

**조각 1 (완료)**

- `configs/datasets/deepspeak_v2.json`: HF 카드(2026-11-16 확인)에 적힌 필드만 `evidence: card`. 카드에 없는 것(행 안의 분할 열, 영상 ID,
  진짜의 녹화 ID, 메타데이터가 중첩인지)은 `unconfirmed`. `configs/datasets/hidf.json`은 필드가 비어 있고 변환을 거부한다.
- `training/datasets/adapters/`: JSON Lines 메타데이터 → 공통 manifest. 필드 이름은 설정에만 있다. 누수 검사 실패면 manifest를 쓰지 않는다.
  **HF 데이터셋을 JSON Lines로 내보내는 단계는 만들지 않았다**(행 구조를 모른다. 승인 후 첫 행을 열어 설정을 고치는 것이 첫 작업).
- `training/datasets/groups.size_summary`(상한 25%), `training/hygiene`에 `derived_not_inheriting_parent` 오류와 `derived_parent_missing` 경고.
- `training/features/extract.py`: Gate → WaveRep·MotionPhys·SyncNet. 서버의 Gate 실행기와 세 어댑터를 그대로 부른다.
  캐시 키 = 입력 sha256 + 축 버전·설정 + 구간. 실행 오류는 캐시하지 않고 재시도. `progress.jsonl`, 영상 단위 `features.jsonl`, `features.meta.json`.
  external 영상은 추출하지 않는다. MotionPhys 어댑터에 연구 전용 `include_features` 인자를 더했다(서버 Worker는 쓰지 않는다).
- 테스트: `tests/test_training_datasets.py`, `tests/test_feature_extract.py`. `pytest -q` **633 passed, 1 skipped**(LightGBM 없음).
- 실제 스모크(1회): A.MOV 한 개, Gate 13.8초 → WaveRep 20.6초(76프레임, 중앙값 6.568 — Worker 실행 값과 같다) → MotionPhys 45.3초
  (A 504, B 504, C 1,512차원). 재실행 시 세 축 모두 캐시 사용. SyncNet은 스모크에서 돌리지 않았다. 산출물은 지웠다.
- **미검증:** 실제 DeepSpeak 행, 대량 추출의 소요 시간·디스크, HiDF.

**조각 2 (완료)**

- 환경: `research/training/.venv`(numpy 2.4.6, scikit-learn 1.9.1, lightgbm 4.7.0, `requirements.lock.txt`). trinity 변경 없음.
- `configs/training.json` + `training/config.py`: 사전 고정 설정. 모르는 키 거부(`threshold_split` 등은 표현할 수 없다).
  `dev_compression_conditions`는 커밋된 값이 `null`이고 그대로면 학습이 오류로 멈춘다.
- `training/synth.py`: 합성 manifest·특징 생성기(그룹, 축별 신호·결측, 압축 파생본, 누수 주입).
- `research/training/train.py`: 누수·그룹 비중(25%)·특징–manifest 해시 확인 → WaveRep 점수(중앙값) → MotionPhys A/B/C LightGBM 그룹 5-fold OOF
  → 결합용 M은 dev AUC로 선택 → 후보 W, M-*, W+M, W+M+S → 결합 모델 교차 적합 OOF에 sigmoid 보정 → dev(지정 압축 조건만) 임계값 잠금.
  산출: `scores/`(dev·test), `oof/`(train), `thresholds/`(읽기 전용), `models/<후보>.json`(계수·표준화·보정), `models/motionphys-*.txt`, `train_meta.json`.
- 테스트 `tests/test_training_train.py` 18개: 설정 검사(항상 실행), 학습 종단(venv 서브프로세스), 결측 축은 빈칸,
  **test 분할의 특징·라벨을 바꿔도 모델·보정·임계값이 같음**, 누수·거대 그룹·dev 조건 미지정·해시 불일치·기존 폴더 거부.
- 한계: 스태킹은 같은 폴드를 재사용한다(완전 중첩 CV 아님, `train_meta.json`에 기록). 하이퍼파라미터 탐색 없음.

**조각 3 (완료)**

- `training/report/decision.py`: 짝지은 그룹 bootstrap 차이, Brier·ECE, dev AUC로만 하는 선택, 관문, 판단(`fusion_adoptable`/`waverep_only`/`hold`),
  shortcut 진단(해상도·fps·길이·오디오 유무; 코덱은 수집하지 않음, 경고만).
- `training/report/build.py`: 학습 결과 폴더 → `report.json` + `report.md`. 맨 위에 dev 압축 조건과 합성 여부. 후보별 test 지표,
  dev 값, 기준 대비 차이, 관문 표, 압축 조건별, 보류 현황, 그룹 크기 분포. 점수·임계값 파일이 학습 뒤 바뀌면 거부.
- 구현한 판단: 결합은 자기 AUC CI 하한 > 0.5, FPR CI 상한 ≤ 10%, WaveRep과 단일 최강 각각 대비 TPR 차이 CI 하한 > 0,
  FPR 악화 ≤ 2%p(점 추정), 판정 제공 비율 감소 ≤ 5%p. WaveRep 단독은 AUC CI 하한 > 0.5와 FPR CI 상한 ≤ 10%.
  `servable_candidates`에는 자기 축 조합으로 따로 관문을 넘은 후보만 들어간다(조각 4가 읽는다).
- 합성 종단 테스트(`tests/test_training_report.py`, venv 필요): 신호 없음(시드 4개) → 전부 보류 / WaveRep에만 신호 → WaveRep 단독 /
  MotionPhys 한 후보에만 신호 → 그 단일축이 최강이고 결합 미채택 / 두 축에 신호 → 채택 가능 / 누수·변조 → 거부.
- `pytest -q` **668 passed, 1 skipped**(LightGBM 없음, trinity).
- 관찰(합성): test의 진짜 영상이 적으면 FPR CI 상한 ≤ 10% 관문 때문에 신호가 있어도 보류가 된다
  (진짜 약 128개에서 보류, 약 480개에서 통과). 실제 데이터의 test 진짜 영상 수를 먼저 확인할 것.
- 한계: TPR·FPR은 점수가 나온 영상만으로 계산한다(결측은 판정 제공 비율로 따로 본다). latency·메모리 집계 없음.

**조각 4 (완료, 2026-11-16 사용자 승인)**

- docs/DESIGN.md §15.3 "결정 5·8 보완 — 2026-11-16, Claude 제안, 사용자 승인"에 승인 문안을 넣었다.
- `training/bundle.py`: 묶음 생성(`python -m training.bundle --run … --report … --out data/models/fusion/<id>`), digest, 불러올 때의 검증, 순수 파이썬 점수 계산.
  판단이 보류인 리포트로는 묶음을 만들지 않는다. `configs/fusion_bundle.json`은 `bundle_id`·`digest`가 null(묶음 없음)이다.
- 서버: `server/fusion.load_active`(digest·파일 해시·리포트 판단·합성 여부·특징 버전 확인, 실패 이유는 코드만 로그) → Worker가 작업마다 불러
  `AxisContext.bundle`로 축에 전달 → 축이 결합 입력을 `ctx.fusion_inputs`에 넣음(signal: logit 중앙값, alignment: 트랙 중앙값,
  physics: 실행기가 묶음의 LightGBM 모델로 계산한 margin) → `fusion.fuse`가 성공한 축 집합과 정확히 일치하는 후보로만 판정.
  `build_result`는 바꾸지 않았고, 판정했을 때만 Worker가 `verdict_label`과 첫 설명 항목(`FUSION_ASSESSED`)을 채운다.
  `Settings.allow_synthetic_bundle`은 테스트 전용(환경 변수 없음).
- 테스트 `tests/test_fusion_bundle.py` 22개: 묶음 없음(저장소 기본) → 기존과 동일 / 유효 묶음 → assessed·라벨·기존 필드만 /
  축 일부 실패 → 따로 검증된 부분집합 후보 또는 보류 / 입력 결측 → 보류 / Gate 우회 → 미적용 /
  **거부 11종**(digest 불일치, bundle.json 변조, 계수·임계값·모델 파일 변조, 리포트를 보류로 바꾸고 해시까지 다시 맞춤, 합성 묶음,
  특징 버전 불일치, 폴더 없음, 경로 벗어난 ID, 관문을 넘지 않은 후보 끼워 넣기) → 전부 null/abstained/no_valid_fusion_model.
- `pytest -q` **690 passed, 1 skipped**(LightGBM 없음). `flutter test` 203개 통과(앱 변경 없음).
- **미검증:** 실제 MotionPhys venv에서 묶음 모델로 margin을 계산하는 경로(`infer_axis.py`의 `_margin`)는 대역 프로세스로만 확인했다.
  → 2026-11-19 실제 두 venv로 확인: 학습 쪽 `predict(raw_score=True)`와 비트 단위로 같다(`docs/motionphys-adapter.md` "LightGBM margin 일치 확인"). 실제 데이터 모델·실제 묶음 종단은 여전히 미검증.
  실제 영상 + 실제 LightGBM 모델의 종단 실행, 서버 Worker의 signal·alignment 입력 전달(가짜 축으로만 확인), 실제 데이터의 묶음.
- 앱은 실제 서버 모드에서 라벨을 숨기는 현재 동작 그대로다(G4 뒤 별도 결정).

**문서 (완료):** `docs/training-pipeline.md`(DeepSpeak 승인 후 체크리스트 포함), docs/DESIGN.md §14.1 8·12번, `training/README.md`.
PR은 만들지 않았다(사용자 지시). main 병합 없음.

**남은 일**

1. DeepSpeak v2 승인 후 `docs/training-pipeline.md`의 체크리스트 1번부터.
2. 실제 MotionPhys venv + 실제 LightGBM 모델로 margin 경로 종단 확인(지금은 대역 프로세스로만 확인).
   → 2026-11-19 합성 특징으로 학습한 실제 LightGBM 모델로 확인(위 줄). 실제 데이터 모델은 승인 뒤.
3. 이전 브랜치에서 넘어온 일: 압축 견고성 실측 재개(실패 캐시 삭제 후), `docs/robustness-selfvideo.md`, SyncNet 성능(`feat/syncnet-perf`, 보류).

## MotionPhys 축·견고성 진행 (2026-11-16~, 브랜치 `feat/motionphys-axis`)

크레딧이 끊겨도 이어갈 수 있게 단계마다 갱신한다. main에는 병합하지 않는다. 마지막에 PR 하나를 만든다.

**사용자 승인 사항(2026-11-16, Claude 제안)**

- physics에 새 API 필드를 추가하지 않는다. `raw_score=null`, "종합 판정에 포함하지 않음"은 `explanations`에 적는다.
- physics 추출 성공은 `completed` + `raw_score=null`. 축 상태의 기준은 후보 A, B·C는 `explanations` 요약에만.
- `analysis_status` 규칙과 `build_result`는 바꾸지 않는다. 세 축이 모두 돌면 기존 규칙대로 `completed`다.
  A 실제 확인의 기대값: finished / completed(축이 하나라도 completed가 아니면 partial) / abstained, `overall_score`·`verdict_label` null.
- 견고성 측정: Gate는 조건마다 재실행, 세 모델은 원본의 Gate 구간으로 고정. WaveRep은 Worker 기본값.
  측정 스크립트에서만 SyncNet 제한 1,800초. 1080p 프로파일은 원본 해상도 출력과 해시가 같으면 "원본과 동일(해시)"로 적고 재측정하지 않는다.
  A 원본 실측에서 SyncNet이 조건당 10분을 넘으면 SyncNet은 원본 + CRF 20/34 × 원본/720만 돌리고 나머지는 "미측정".
  480p의 WaveRep `unsupported_input`은 그대로 기록.

| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 앱 실제 서버 모드 문구, app/README 현행화 | **완료** (아래) |
| 1 | MotionPhys를 physics 축으로 연결, 테스트, A 실제 Worker 확인 | **완료** (아래) |
| 2 | A·B·E × 범용 프로파일 12개 3축 압축 견고성 실측 (`scripts/robustness_selfvideo.py`, `docs/robustness-selfvideo.md`) | 남음 |
| 3 | B·E SyncNet 오디오 밀기 실험, M3 16GB 축별 시간·메모리 표 | 남음 |
| 마무리 | docs/DESIGN.md §14.1 10번, §15.3 기록, 전체 테스트, PR | 남음 |

**1단계 (완료)**

- 추가: `server/axes/physics/motionphys.py`(어댑터), `research/motionphys/infer_axis.py`(A→B→C 실행기).
  `server/axes/physics/__init__.py`의 stub을 실제 진입점으로 바꿨다. `AxisContext.explanations`를 추가해
  축 설명을 결과의 `explanations` 인덱스 1에 넣는다(`build_result` 변경 없음). `Settings.motionphys_timeout_seconds`
  (`TRINITY_MOTIONPHYS_TIMEOUT_SECONDS`, 기본 300초 임시값). 상태 표와 세부는 `docs/motionphys-adapter.md`.
- docs/DESIGN.md §14.1 10번 상태, §15.3 "결정 3·8 보완 — 2026-11-16, Claude 제안, 사용자 승인", 환경 변수 목록을 갱신했다.
- 테스트: `pytest -q` **603 passed, 1 skipped**(2단계 스크립트 테스트 4개 제외)(LightGBM 없음), 기존 httpx 경고 1개. A·B·E 실제 미디어 테스트 3개가 이 기기에서 실행됐다.
  기존 기대값 2곳(`tests/test_queue_worker.py`, `tests/test_waverep_worker.py`의 "physics는 insufficient_input")은
  stub 전제여서 `error`/`model_unavailable`로 바꿨다. conftest가 테스트에서 실제 MotionPhys venv 실행을 막는다.
- 실제 확인(1회): A를 임시 레지스트리 + 별도 Worker로 처리. finished / completed / abstained,
  `overall_score`·`verdict_label` null, 세 축 completed. Gate 약 18초, WaveRep(MPS) 약 26초, MotionPhys 약 61초,
  SyncNet(CPU) 약 400초, 전체 506초. 임시 레지스트리·DB·로그는 삭제했다.
- SyncNet이 A에서 조건당 10분 미만(약 6.7분)이라 2단계는 SyncNet도 30조건 전부 돌린다.
- MotionPhys 단독 37.1초 대 Worker 안 약 61초: 원인 미확인. 2단계 시간표에 측정 근거와 함께 적는다.
- **미검증:** B·E의 Worker 종단 실행, 실제 모델 실행 중 취소·SIGKILL, 앱 화면에서의 새 설명 표시.
  → 2026-11-19: 실제 모델 실행 중 취소(SyncNet·WaveRep MPS)와 SyncNet 실행 중 Worker SIGKILL은 확인(실제 Worker 수명주기 확인(2026-11-19, 맨 위 절)). MotionPhys 실행 중 취소·SIGKILL, B·E, 앱 화면은 여전히 미검증.

**2단계 실측 진행 (Sonnet 5.5 감시, 코드·설계 변경 금지)**

- **막힌 점 1 — 변환본 12개 전부 인코딩 실패(A 확인, B·E도 같은 형식).** 원인: 프로파일이 `-map 0:a? -c:a copy`로
  오디오를 복사하는데, 샘플 .MOV의 오디오 스트림 2개 중 하나가 ffprobe에서 코덱 `unknown`(추정: iPhone 공간 오디오 — 미확인)이라
  mp4에 복사할 수 없다. `reason`: "codec not currently supported in container … Could not write header". `docs/compression-emulator.md` §8에
  "mp4에 복사할 수 없는 오디오 코덱은 확인하지 않았다(미검증)"로 적어 둔 경우가 실제로 발생한 것이다. 수정하지 않았다.
  로그: `data/research/robustness-selfvideo/pilot.log`, 조건별 사유 `variants/*.index.json`(`reason`).
  **이 인덱스에 error가 캐시돼 있어 코드를 고친 뒤에는 `variants/<영상>.index.json`의 해당 조건 항목과 `*.mp4.json`을 지우고 다시 실행해야 한다.**
  결과: 변환본 측정은 0건. 원본 3개의 측정만 진행한다. 사용자 결정 필요(오디오 매핑·재인코딩 방식).
- **막힌 점 2 — 작업 제한 600초 위험.** A 실제 Worker 실행이 506초(SyncNet 약 400초)였다. 서비스 기본
  `TRINITY_JOB_TIMEOUT_SECONDS=600`에서 여유가 약 94초이고, 52초 영상 E는 SyncNet이 더 길어 600초를 넘길 가능성이 있다(미측정).
  넘기면 `failed`/`timeout`이다. 측정 스크립트는 SyncNet 단계만 1,800초로 늘려 이 제한과 무관하다.
- 실행: `data/research/robustness-selfvideo/full.log`. 파일럿(A 원본 Gate·MotionPhys·WaveRep) 정상: Gate 13.1초, MotionPhys 110.3초(프로세스 2회 포함), WaveRep 31.4초.

**오디오 트랙 수정 (2026-11-16, 사용자 결정 A안, 완료)**

- `training/emulator/video.py`: 첫 번째 AAC 트랙 하나만 `-c:a copy`. 다른 오디오 트랙은 버린다. 재인코딩 없음.
  오디오가 있는데 AAC가 없으면 `error`로 기록하고 넘어간다. 오디오가 아예 없는 입력은 전과 같이 영상만(기존 테스트의 전제).
  기록 `audio`에 입력 트랙 목록과 선택 트랙을 남긴다(`schema_version` 2). `docs/compression-emulator.md` §2·§3·§8 갱신.
- A·B·E의 두 번째 트랙은 ffprobe 그대로 `codec_name=unknown`, `codec_tag_string=apac`, 4채널이다. 정체는 확인 필요.
- **측정은 다시 돌리지 않았다(사용자가 멈춤).** 재개 전에 실패 캐시를 지워야 한다:
  `data/research/robustness-selfvideo/variants/{A,B,E}.index.json`의 프로파일 항목(또는 파일 전체)과 `variants/*.mp4.json`.
  그 뒤 `python scripts/robustness_selfvideo.py`를 다시 실행하면 된 조건은 건너뛴다.
  `run_all`은 `status`가 error인 조건을 건너뛰므로 캐시를 지우지 않으면 변환본이 계속 빠진다.
- **원본 3개 측정은 끝났다(2026-11-16 감시 확인).** 프로세스 종료, 실패한 측정 0건, 결과 JSON 12개
  (`data/research/robustness-selfvideo/results/{A,B,E}/original/{gate,waverep,motionphys,syncnet}.json`),
  모음 `summary.json`, 로그 `full.log`. 변환본 측정은 0건(위 실패 캐시 삭제 후 재실행 필요).
  결과 해석과 `docs/robustness-selfvideo.md`는 아직 쓰지 않았다.

**견고성 실측 완료 (2026-11-17, 브랜치 `research/robustness-run`, 숫자만 기록 — 해석·`docs/robustness-selfvideo.md`는 아직 없음)**

- 위치(Git 밖): `data/research/robustness-selfvideo/` — `results/<영상>/<조건>/<축>.json` 120개, `summary.json`, `variants/`(변환본 36개와 `*.mp4.json`, `<영상>.index.json`), 로그 `full.log`(위쪽 variant error는 오디오 수정 전 기록), `run_config.json`.
- 조건: 영상 3개(A·B·E) × (원본 + 프로파일 12개). 1080p 프로파일 9건은 해당 CRF의 원본 해상도 출력과 해시가 같아 재측정하지 않음(`duplicate_of`).
  측정한 조건은 영상당 10개(원본 + 변환본 9개) × 축 4개 = 120건. 변환본 인코딩 36건 모두 completed(오디오는 첫 AAC 트랙만 복사).
- 성공/실패: 측정 120건 중 실행 실패 0(`full.log`에 `exit=` 0이 아닌 줄 없음). 축별 결과 값:
  - Gate 30건: 모두 `reason_code=null`(적합 구간 있음). 적합 구간 수는 A 5~8개, B 8~9개, E 4~7개.
  - WaveRep 30건: `completed` 21, `unsupported_input` 9(480p 전부).
  - MotionPhys 30건: 후보 A·B·C 모두 `completed` 30/30.
  - SyncNet 30건: A `completed` 10/10, B·E는 `insufficient_input`/`tracking_failed` 10/10씩(일부 또는 전체 구간에 유효 트랙 없음).
- 축별 처리 시간(`elapsed_sec`, 단조 시계, 조건 1건당 / 30건): Gate 중앙값 8.1초(5.6~21.2), WaveRep 26.4초(2.3~33.4; 480p 9건은 2.3~2.9),
  MotionPhys 15.6초(7.6~215.4), SyncNet 147.8초(53.9~389.0). 합계 약 1.92시간. 후손 프로세스 하나의 최대 RSS(`ru_maxrss`): Gate 0.58, WaveRep 1.10, MotionPhys 0.83, SyncNet 2.63 GiB.
  - MotionPhys 원본 3건(110.2/215.4/141.4초)은 샘플 오프셋 대조군 실행을 포함한 시간이라 변환본과 직접 비교하지 않는다. 같은 입력의 Worker 안 61초 대 단독 37초 차이는 이번에도 원인을 확인하지 않았다.
  - SyncNet 중앙값(초), 영상별 원본/1080(source)/720/480: A 276/361/179/96, B 261/254/129/73, E 194/191/95/54.
- **해석 문서 완료(2026-11-17):** `docs/robustness-selfvideo.md`(축별 변화 표, 시간표, 한계, dev 압축 조건 후보 3안 — 제안만).
  요지: WaveRep logit이 재압축만으로 중앙값 5.8~13.6 이동(영상 내 IQR 2.3~3.6), SyncNet 오프셋은 133/135 동일, MotionPhys A·B 곡률은 CRF 28부터 대조군의 3배 이상, C는 대조군 수준.
- **사용자 결정 대기:** `configs/training.json`의 `dev_compression_conditions`(권장 제안은 2안 `["original", "x264-crf28-720p"]`)와 최종 평가용 프로파일 고정.

**0단계 (완료)**

- `TrinityNav.serverMode`로 모드를 화면에 전달한다. mock 모드는 기존 "모델 미연결 · 가상 데이터"와
  "아래는 가상 데이터입니다…"를 유지하고, 실제 서버 모드는 "연구용 시제품 · 결과는 참고 정보"와
  "아래는 연구용 시제품의 계산 결과이며 참고 정보입니다…"를 보인다. 서버·API 변경 없음.
- `app/README.md`를 현재 동작(실제 모델 연결, 취소 버튼, Chrome 예행)으로 고쳤다. `docs/design-system.md`의 띠 설명도 맞췄다.
- docs/DESIGN.md §15.3 SyncNet 보완 기록의 "Codex, GPT-6 Astra 제안, 사용자 승인" 표기는 main에 이미 있어(결정 2·8 보완 머리말) 바꾸지 않았다.
- 검증: `flutter analyze` 문제 없음, `flutter test` 203개 통과(새 테스트 1개 포함). 실제 서버 모드 문구를 Chrome에서 눈으로 본 것은 아니다(**미검증**).

## Flutter 실제 서버 모드 A 예행 (2026-11-16)

- 기준: `codex/pr12-pr13-integration`, `c8fc7b75789bd9b6e871eeb88d24a95714bc3191`.
  제품 코드 변경 없이 Chrome에서 한 건만 요청했다. 실제 A YouTube URL이 제공되지 않아
  `https://www.youtube.com/watch?v=TRINITYtest`를 사용했다. 실제 YouTube ID 시연은 미검증.
- Git 밖 `data/runtime/web-demo-A/registry.json`에서 TRINITYtest를
  `/Users/iyeonje/ai-/data/research/samples/A.MOV`에 연결했다. 서버와 Worker에 같은
  레지스트리·DB·runtime을 적용했다. WaveRep·SyncNet 기존 venv/upstream/가중치를
  임시 심볼릭 링크로 연결했고 CPU를 사용했다. 다운로드·Gate 우회·임계값 변경 없음.
- Flutter web-server를 띄우고 실제 Chrome으로 `http://127.0.0.1:8080`을 열었다.
  접근성 버튼을 켜서 화면 문구와 컨트롤을 확인했다. 서비스 모드는 server다.

**화면별 관찰과 서버 대조**

| 화면 | 관찰 |
|---|---|
| 입력 | 테스트 URL을 붙여넣고 분석 요청 클릭 |
| 접수 | 대기 중 / 분석 순서를 기다리고 있어요 표시; DB 작업 1건 생성 |
| 진행 | 분석 구간 준비 → 영상 신호 확인 → 입술·음성 확인 진행 표시; 서버 preprocessing → waverep → syncnet과 일치 |
| 결과 | 판단 보류 / 판단을 보류했어요; 검증된 종합 판정 모델 없음. 작업 종료·부분 분석·판정 보류 표시 |
| 근거 | WaveRep 측정됨, MotionPhys 입력 부족, SyncNet 측정됨. LSE-C/D 값 없음, 종합 판정 포함 아니오. 서버 상태 finished/partial/abstained 및 테스트 ID 표시 |

- 작업 ID `58edf304-aa9f-4970-b159-6c74fdb7b160`.
  임시 서버 DB의 저장 결과는 `job_status=finished`, `analysis_status=partial`,
  `verdict_status=abstained`, `overall_score=null`, `verdict_label=null`이었다.
  화면의 서버 상태·분석 ID와 대조했다. 토큰을 추출하거나 별도 분석 요청을 만들지 않았다.
- 실제 WaveRep은 CPU 76프레임 completed(모델 보고 total_sec 40.5411), SyncNet도 completed.
  alignment.lse_c/lse_d=null, included_in_fusion=false이며 모든 Gate 적합 구간의
  트랙별 계산 완료·대표값 집계 보류 설명이 결과 화면에 표시됐다.
  physics는 insufficient_input/stub_not_executed다. 분석량은 화면에서 41초 중 37초로 표시됐다.
- 로그상 시작 06:26:08, SyncNet 진입 06:27:06, finalizing 06:41:52(+10:00).
  이 시각 차이를 순수 추론 시간이나 기본 제한 준수의 증거로 해석하지 않는다.
  중간 시스템 시간 경과·일시 중단 여부와 제한 시간의 실제 경과는 별도 계측하지 않아 확인 필요다.

**확인된 표시 문제(수정하지 않음)**

- 실제 서버·모델 결과인데도 전 화면 상단에 "모델 미연결 · 가상 데이터"가 표시된다.
- 근거 화면에도 "아래는 가상 데이터입니다"가 표시된다.
  코드의 고정 문구 위치는 app/lib/design/widgets.dart와 app/lib/screens/detail_screen.dart다.
- app/README.md의 모델 미연결·취소 없음 등 일부 설명도 현재 동작보다 오래된 내용이다.
  실제 상태와 판단 보류 표시는 일치했지만 위 문구까지 올바른 시연이라고 보고하지 않는다.

**재현 명령** (먼저 모델별 기존 환경·upstream 및 data/models/gate·syncnet 준비):

```bash
cd /Users/iyeonje/.codex/worktrees/3603/ai-
conda activate trinity
mkdir -p data/runtime/web-demo-A
# registry.json:
# {"authorized_media":[{"youtube_video_id":"TRINITYtest","local_path":"A.MOV"}]}
export TRINITY_AUTHORIZED_MEDIA="$PWD/data/runtime/web-demo-A/registry.json"
export TRINITY_AUTHORIZED_MEDIA_ROOT=/Users/iyeonje/ai-/data/research/samples
export TRINITY_DB_PATH="$PWD/data/runtime/web-demo-A/queue.sqlite3"
export TRINITY_RUNTIME_DIR="$PWD/data/runtime/web-demo-A/jobs"
export TRINITY_WAVEREP_DEVICE=cpu
# 위 환경을 동일하게 적용한 별도 터미널에서 각각 실행
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --no-access-log
python -m server.jobs.worker
# 앱 터미널
cd app
flutter run -d web-server --web-hostname 127.0.0.1 --web-port 8080 --no-web-resources-cdn \
  --dart-define=TRINITY_API_MODE=server --dart-define=TRINITY_API_BASE_URL=http://127.0.0.1:8000
# Chrome: http://127.0.0.1:8080 → 테스트 URL 입력 → 분석 요청 → 결과 → 판단 근거
```

- 실행기 `/private/tmp/trinity-web-demo.py`는 위 환경·서비스·임시 모델 링크를 구성한
  세션용 스크립트다. 같은 포트가 비어 있어야 하며 재실행 후 종료·정리가 필요하다.
- **정리:** Worker가 UUID 작업 폴더를 삭제한 것을 먼저 확인했다.
  이번 서버·Worker·Flutter에 SIGTERM을 보내 종료를 확인했다. 이후 추가 SIGKILL 시도에서
  권한 오류가 있어 개별 PID 상태를 재조회했고 모두 Z(실행 종료)임을 확인한 뒤 실행기도 종료했다.
  임시 레지스트리·DB·로그·runtime, 이번 환경 링크, Flutter .dart_tool/build를 삭제했다.
  Chrome 시연 탭도 닫았다. 원본 A와 모델 환경·가중치, 기존 Gate/sample 연결은 보존했다.
- 변경은 이 HANDOFF뿐이다. 문서만 변경하여 전체 테스트는 다시 실행하지 않았고
  git diff --check를 확인했다. 커밋·push·main 병합 없음.
- **미검증:** 실제 YouTube ID·YouTube 처리본, B/E 앱 시연, 앱에서 취소 버튼 실행,
  실제 모델 SIGKILL 복구, 연구 성능·진위 정확도. 다음은 실제 URL 확보와 위 표시 문구 정비다.


## 로컬 통합 브랜치 저장 (2026-11-16)

- 사용자 승인에 따라 기존 충돌 해결, SyncNet supervisor 수정, 새 복구 회귀 테스트,
  통합·검증 기록을 하나의 로컬 병합 커밋에 저장한다.
- 부모 순서: #12 `bd0e2c849e04661cd26df4436d21d58f057d4483`,
  #13 `0eafb3be61fd7f973fe46ba131e66a4619fb3e89`.
  저장 브랜치: `codex/pr12-pr13-integration`.
- 기존 전체 실행 로그·JUnit 및 파일 수정 시각을 대조했다. 539 passed, 5 skipped,
  경고 1개 이후 변경은 HANDOFF뿐이며 코드·테스트 변경은 없다. 전체 테스트 재실행 없음.
  새 복구 테스트의 retry/exhausted/cancel 세 사례도 JUnit에서 통과를 확인했다.
- 영상·가중치·가상환경은 저장하지 않는다. 아래 미커밋 표기는 이전 세션 당시 상태다.
  GitHub push 및 main 병합은 사용자에게 남긴다. 실제 모델 SIGKILL 검증은 여전히 미검증이다.
  (2026-11-19: 실제 SyncNet 실행 중 Worker SIGKILL·재시작 복구 확인 — 실제 Worker 수명주기 확인(2026-11-19, 맨 위 절).)


## SyncNet Worker 강제 종료·복구 보완 (2026-11-16)

- 기존 아래 "PR #12 → #13 통합 검증"과 충돌 해결 내용을 보존했다.
  같은 통합 worktree에서 HEAD `bd0e2c8`, MERGE_HEAD `0eafb3b`를 유지했다.
  새 merge commit·GitHub 병합·push는 하지 않았다. 원래 feat/syncnet도 변경하지 않았다.
- **재현:** 실제 별도 Worker·SQLite·SyncNet 어댑터를 사용하고 계산 프로세스만
  대역으로 바꿨다. 대역 SyncNet은 FFmpeg 역할의 후손을 띄우고 임시 crop 표시 파일을
  계속 작성한다. `processing/syncnet`과 두 PID 생존을 확인한 뒤 Worker에 SIGKILL을 보냈다.
  수정 전 재시도/상한/취소 3개 사례 모두 5초 후에도 두 프로세스가 생존해 실패했다.
  재현 로그: `/private/tmp/syncnet-recovery-red.log` (3 failed).
  테스트 finally에서 고아 대역 프로세스를 정리했다.
- **원인:** SyncNet의 직접 Popen + finally killpg 경로는 Worker SIGKILL 때 실행되지 않는다.
  Gate·WaveRep과 달리 독립 supervisor의 생존 파이프 감시를 거치지 않았다.
- **최소 수정:** `server/axes/alignment/syncnet.py`가 기존
  `server/jobs/child_process.py`의 start_process/stop_process를 사용하도록 변경했다.
  supervisor 코드 자체는 수정하지 않았다. Worker 사망 시 pipe EOF로 모델 그룹을 종료하고,
  정리까지 runtime 잠금을 유지하는 기존 동작을 재사용한다.
  정상 종료·취소·타임아웃도 같은 정리 경로를 거친다. API·상태·원인 코드 변경 없음.
- **새 회귀 테스트:** `tests/test_syncnet_recovery.py`의 3개 매개변수 사례.
  두 자식의 종료를 먼저 확인하고 lease를 자연 만료시킨 뒤 별도 Worker를 재시작한다.
  재시도는 attempts=2 및 정합 completed/작업 finished, 재시도 상한은
  failed/max_attempts_exceeded, 취소 요청이 있던 작업은 cancelled를 확인했다.
  재시도 전에 이전 crop이 제거되고 종료 뒤 UUID 폴더가 사라져 다시 생성되지 않는지도 확인했다.
- **관련 검증:** 60 passed, 기존 경고 1개, 9.55초.
  강제 종료 복구 3개와 기존 Gate·WaveRep 복구, SyncNet 정상 취소·타임아웃·
  callback 오류·후손 정리 및 Worker heartbeat/lease 연장이 포함된다.
  첫 수정 후 실행에서는 테스트가 큐의 failure_reason 대신 result를 읽어 1개 실패했다.
  기존 저장 계약에 맞게 테스트를 바로잡은 뒤 모두 통과했다(제품 계약 변경 없음).
- **전체 검증:** 539 passed, 5 skipped, 기존 httpx 경고 1개, 72.26초, 종료 코드 0.
  skip은 LightGBM 없음 1개, MAVOS 표본 목록 미연결 1개,
  MotionPhys 모델 미연결 2개, WaveRep venv·가중치 미연결 1개로 이전 통합 검증과 같다.
  로그 `/private/tmp/syncnet-recovery-full.log`, XML `/private/tmp/syncnet-recovery-full.xml`.
  git diff --check 및 git diff --cached --check 통과, 미해결 충돌 없음.

**재현·회귀 명령** (이 통합 worktree, conda trinity):

```bash
cd /Users/iyeonje/.codex/worktrees/3603/ai-
python -m pytest -q -rs tests/test_syncnet_recovery.py
python -m pytest -q -rs tests/test_syncnet_recovery.py tests/test_syncnet_adapter.py tests/test_syncnet_worker.py tests/test_job_lifecycle.py
python -m pytest -q -rs --junitxml=/private/tmp/syncnet-recovery-full.xml
```

실행에는 `/opt/anaconda3/envs/trinity/bin/python`을 명시적으로 사용했다.
수정 전 증상은 제품 어댑터가 기존 직접 Popen 경로일 때 첫 명령으로 재현된다.
이번 추가/수정 파일은 어댑터·새 회귀 테스트·이 HANDOFF 세 개이며 기존 통합 staged 변경은 보존했다.

**범위와 다음:** 이번 SIGKILL은 대역 SyncNet과 FFmpeg 역할의 Python 후손으로 검증했다.
실제 SyncNet 모델·실제 FFmpeg를 사용한 강제 종료 및 복구는 **미검증**이다.
(2026-11-19: 실제 SyncNet(MPS) 실행 중 Worker SIGKILL 2회 — 자식 0.075초 안 종료, 새 Worker가 lease 만료 뒤 재선점해 finished. 실제 Worker 수명주기 확인(2026-11-19, 맨 위 절).)
이전 실제 A 영상 취소·오프셋 결과를 이번 검증과 혼동하지 않는다.
아래 통합 기록의 SyncNet SIGKILL 미검증은 당시 상태이며, 대역 검증에 한해서 이번에 보완했다.
사용자가 통합 변경 검토·병합·push 여부를 결정한다. 막힌 점 없음.


## PR #12 → #13 통합 검증 (2026-11-16)

- 원격 확인: 두 PR 모두 OPEN, mergedAt/mergeCommit 없음. 최신 main은
  `3f0f2b4bba37154e977e6bd48626ede570f555ec`.
  #12 head `bd0e2c849e04661cd26df4436d21d58f057d4483`,
  #13 head `0eafb3be61fd7f973fe46ba131e66a4619fb3e89`.
  #12 원격 HANDOFF의 A 실제 WaveRep 취소 기록과 #13 원격 HANDOFF 및
  docs/syncnet-adapter.md의 A 오프셋 진단 수치·한계를 확인했다.
  아래 과거 기록의 커밋·push 보류 문구는 당시 상태이며 지금은 두 기록 모두 원격에 있다.
- 격리 worktree: `/Users/iyeonje/.codex/worktrees/3603/ai-`.
  main에서 #12를 fast-forward하고 #13을 `--no-commit --no-ff`로 통합했다.
  docs/DESIGN.md §15.3 승인 결정 추가와 HANDOFF의 앞부분 기록에 충돌이 있었다.
  두 승인 결정 및 두 PR의 기록을 모두 보존해 해결했다. API·동작 변경 판단은 필요 없었다.
  server/jobs/worker.py는 자동 병합됐다. 제품 코드의 수동 수정은 없다.
  원래 feat/syncnet 작업 공간과 별도 #12 작업 공간은 보존했다.
- 검증 대상은 새 커밋이 아니라 위 두 head의 로컬 통합 트리다.
  기록 추가 전 트리 OID: `8b1354295f5c6c1a23e5870fa807a6dc43b1b65a`.
  HEAD는 #12이며 MERGE_HEAD는 #13인 미커밋 통합 상태를 남겼다.
  GitHub merge·push 및 로컬 merge commit은 하지 않았다.

**재현 명령** (새 격리 worktree에서 위 main을 checkout한 뒤):

```bash
git merge --ff-only bd0e2c849e04661cd26df4436d21d58f057d4483
git merge --no-commit --no-ff 0eafb3be61fd7f973fe46ba131e66a4619fb3e89
# README §15.3 및 HANDOFF 충돌에서 양쪽 추가 기록을 모두 보존
git add README.md docs/HANDOFF.md
# data/research/samples와 data/models/gate에 기존 허가 샘플·Gate 모델 연결
/opt/anaconda3/envs/trinity/bin/python -m pytest -q -rs --junitxml=/private/tmp/trinity-pr12-pr13-integration.xml
git diff --cached --check
git diff --check
```

**이번 통합 테스트:** 536 passed, 5 skipped, 1 warning, 68.10초, 종료 코드 0.
로그 `/private/tmp/trinity-pr12-pr13-integration.log`, JUnit XML은 위 경로.
DELETE 13개, 취소·복구·정리(test_job_lifecycle) 18개, SyncNet Worker 7개,
SyncNet 어댑터 32개·runner 17개, 실제 Gate 미디어 11개 모두 통과했다.
Gate 미디어에는 로컬 A·B·E가 포함된다. 기존 httpx 폐기 예정 경고 1개가 남았다.

건너뜀 5개:

- LightGBM 미설치: test_motionphys_train 1개.
- 이 worktree에 MAVOS-DD 실제 표본 목록 미연결: test_mavos_external 1개.
- MotionPhys 모델 파일 미연결로 실제 얼굴 특징 전제 미충족: test_motionphys_extract 2개.
- WaveRep 전용 .venv·가중치 미연결: 실제 CPU 2프레임 추론 1개.

**실제 모델 검증과의 구분:** 이전 #12의 A CPU 추론 중 취소(202 → cancelled,
자식 종료·폴더 삭제)와 #13의 A 26–34초 SyncNet 이동 진단은 각각의 브랜치에서 수행한
기존 결과다. 이번에는 통합 상태의 자동 테스트를 수행했고 실제 WaveRep 취소 및 SyncNet
오프셋 실험을 다시 실행하지 않았다. 대역 모델 테스트 통과를 실제 모델 통합 실행으로
해석하지 않는다. 진위 판정·연구 성능 검증도 아니다.

**남은 통합 확인:** SyncNet의 정상 heartbeat 취소·타임아웃은 테스트되지만,
Worker SIGKILL 중 SyncNet 자식 종료·재시작 복구는 미검증이다.
(2026-11-19: 실제 모델로 확인 — 실제 Worker 수명주기 확인(2026-11-19, 맨 위 절).)
코드상 SyncNet `_run`은 직접 Popen과 finally의 killpg를 사용하며,
#12의 Gate·WaveRep용 생존 파이프 supervisor를 사용하지 않는다.
따라서 Worker 강제 종료 시 SyncNet 고아 자식 방지까지 보장된다고 볼 수 없다.
기존 Worker 사망 테스트는 Gate·WaveRep 경로만 대상으로 한다.
이는 코드 검토로 확인한 적용 범위 차이이며 실제 SIGKILL 증상 재현은 하지 않았다.
필요하면 후속 작업에서 재현·공통 supervisor 적용 여부를 판단한다. 이번에는 변경하지 않았다.

**실제 YouTube URL 시연 준비:**

1. 본인 촬영 A·B·E 중 시연 영상의 실제 YouTube ID와 허가 로컬 원본을 대응시킨다.
   Git 밖 AuthorizedMediaRegistry의 youtube_video_id 및 local_path를 설정한다.
   서버·Worker에 같은 TRINITY_AUTHORIZED_MEDIA, TRINITY_AUTHORIZED_MEDIA_ROOT,
   DB·runtime 환경을 적용한다. 임의 URL 다운로드는 하지 않는다.
2. conda trinity의 Gate 의존성·모델, WaveRep와 SyncNet 각각의 격리 .venv·고정 upstream·
   공식 가중치를 준비한다. trinity에는 torch를 설치하지 않는다. 수동 Gate 우회는 끈다.
   전체 작업 기본 600초 안에 처리되는지는 실제 통합 모델 실행으로 확인 필요하다.
3. `uvicorn server.main:app --port 8000`과 `python -m server.jobs.worker`를 실행한다.
   앱은 app 폴더에서 다음 명령으로 실제 서버 모드를 사용한다.

```bash
flutter run -d chrome --web-port 8080 --no-web-resources-cdn \
  --dart-define=TRINITY_API_MODE=server --dart-define=TRINITY_API_BASE_URL=http://localhost:8000
```

- 브라우저 출처·CORS와 소유자 토큰 유지, 등록 URL 접수·결과·취소를 시연 전에 확인해야 한다.
  실제 YouTube ID 등록과 앱 종단 시연은 이번 작업에서 미검증이다.
  SyncNet 대표 지표 null·fusion false, 전체 점수 null 및 판단 보류 의미를 유지한다.
- DeepSpeak v2는 사용자 확인 기준 심사 대기다. 본인 촬영 허가 영상 시연과 별개이며
  접근 승인을 우회하지 않는다. 모델 라이선스의 기존 확인 필요 항목도 유지한다.
- 다음: 사용자가 두 PR 병합·push 여부를 결정한다. 이 worktree의 통합 결과만 검증했고
  기존 브랜치 및 원격에 반영하지 않았다.


마지막 갱신: 2026-11-15 · 브랜치 `codex/cancel-recovery-security` (최신 origin/main `3f0f2b4`에서 생성)

## A 영상 실제 WaveRep 추론 중 취소 검증 (2026-11-15)

- 범위: PR #12 `codex/cancel-recovery-security`, 커밋
  `3fe99f01715cb07f2c57b9ec6de57b9368846f46`에서 A.MOV 한 건만 검증했다.
  별도 worktree `/private/tmp/trinity-pr12-cancel-A`를 사용했고 원래
  `/Users/iyeonje/ai-`의 `feat/syncnet` 작업 공간은 변경하지 않았다.
- 독립 실제 uvicorn·Worker·SQLite·runtime을 사용했다. 임시 AuthorizedMediaRegistry에
  `/Users/iyeonje/ai-/data/research/samples/A.MOV`를 연결했다.
  기존 Gate 설정·임계값을 그대로 사용하고 WaveRep 장치만 `cpu`로 지정했다.
  기존 모델별 `.venv`·upstream·가중치를 재사용했으며 설치·다운로드·모델 코드 수정은 없었다.
- 작업 `fe18425a-2b54-43c3-99a8-e483397b5f56`은 `preprocessing`을 거쳐
  `waverep`에 진입했다. 실제 `infer_frames.py` 자식 PID `99588`이 실행되는 동안
  `/usr/bin/sample`로 `libtorch_cpu`의 `linear`, `addmm`, `cpublas::gemm` 스택을 확인했다.
  DELETE 직전에 `processing/waverep`, 자식 생존, 추론 결과 파일 미생성을 다시 확인했다.
  따라서 모델 프로세스 시작만 확인하거나 추론이 끝난 뒤 취소한 검증이 아니다.
- 진행 중 GET에서 받은 ETag를 `If-Match`로 보낸 DELETE 응답:
  HTTP **202**, `job_status=processing`, `stage=waverep`.
- 최종 GET 및 결과 조회: **`job_status=cancelled`**, `overall_score=null`.
  실제 추론 자식 종료와 해당 UUID 임시 작업 폴더 삭제를 각각 확인했다.
  취소 요청부터 확인까지 약 **0.39초**(이번 1회 관찰값)였으며 Worker 종료 코드는 0이었다.
  종료 작업을 삭제하는 두 번째 DELETE는 보내지 않았다.
- 실행 후 검증용 서버·Worker를 종료하고 임시 레지스트리·DB·runtime을 정리했다.
  원본 영상·가중치·환경은 보존했다. 검증용 환경 연결 심볼릭 링크도 제거했다.

**로컬 재현 명령** (이 세션의 검증 스크립트는 Git 밖 `/private/tmp/pr12_cancel_a.py`에 보존):

```bash
cd /private/tmp/trinity-pr12-cancel-A
ln -s /Users/iyeonje/ai-/research/waverep/.venv research/waverep/.venv
ln -s /Users/iyeonje/ai-/research/waverep/upstream research/waverep/upstream
/opt/anaconda3/envs/trinity/bin/python /private/tmp/pr12_cancel_a.py
# 실행 후 위에서 만든 심볼릭 링크 두 개만 제거한다(원본 환경·upstream 보존).
unlink research/waverep/.venv
unlink research/waverep/upstream
git diff --check
```

스크립트는 기존 `scripts/smoke_cancel_worker.py`를 기반으로 A와 실제 WaveRep 자식을
관찰하도록 만든 세션 전용 실행기다. Gate 제한 120초, 전체 작업 제한 300초,
heartbeat 1초·lease 4초, WaveRep CPU를 사용한다. 자식 관찰 후 15초 대기와 1초 스택
샘플링을 수행하며, 실제 연산·진행 상태가 확인되지 않으면 성공으로 처리하지 않는다.
재현에는 이 로컬 스크립트·허가 원본·기존 모델 환경이 필요하다(`/private/tmp` 정리 시 스크립트 소실 가능).
스택 원본은 `/private/tmp/pr12-A-stack.txt`에 있으며 미디어 내용은 포함하지 않는다.

**검증 범위·남은 일:** 이번 A 한 건의 CPU 추론 중 취소 성공만 확인했다.
MPS 추론 취소·다른 영상·반복 안정성은 미검증이다(2026-11-19: A의 WaveRep MPS 추론 중 취소 1회 확인 — 실제 Worker 수명주기 확인(2026-11-19, 맨 위 절)). 코드 변경이 없어 전체 pytest는
다시 실행하지 않았다. API·Gate 판정·임계값을 변경하지 않았고 커밋·push는 하지 않았다.
막힌 점 없음.

## 현재 작업: 백로그 14번 중 취소·삭제·Worker 복구·정리

**결과:** 요청한 부분의 구현·테스트·실제 서버 취소 확인을 마쳤다. 백로그 14번 전체 완료는 아니다.
도구·모델: **Codex, GPT-6 Astra**. docs/DESIGN.md §9·§15.3에 날짜와 **“Codex, GPT-6 Astra 제안, 사용자 승인”**을 기록했다.
구현 커밋 `be08650`을 push했고 [PR #12](https://github.com/yeonje14/ai-/pull/12)를 생성했다.
PR은 열림·미병합 상태이며 main에는 merge하지 않았다. 이 인계 기록은 후속 문서 커밋으로 반영한다.

**한 일**:

- `DELETE /api/v1/analyses/{id}`: 소유권 확인 후 진행 중 취소 접수 `202`, 반복도 `202`;
  종료(`finished`·`failed`·`cancelled`) 작업은 결과·기록·폴더 삭제 후 본문 없는 `204`.
  토큰 없음 `401`, 다른 소유자·삭제 후 조회(`/result` 포함)·재삭제 `404`.
  큐의 `cancel_requested`를 재사용하고 새 상태나 JSON API 필드를 만들지 않았다.
- 상태 GET의 ETag는 `queued`·`processing` 동안 단계·heartbeat·재시도와 무관하게 불변이며 종료 때 변경한다.
  `If-Match`와 현재 ETag 비교를 DELETE 상태 분기와 같은 트랜잭션에서 수행한다.
  불일치 `412`는 기록·결과·폴더를 건드리지 않는다. 일반 DELETE 계약은 유지한다.
- 앱의 “분석 취소”는 진행 중 상태의 ETag로 조건부 DELETE만 보낸다. 중복 클릭을 막고,
  `202` 후 polling으로 기존 “취소됨” 화면을 표시한다. `412`는 오류로 보이지 않고
  상태·결과를 다시 조회한다. ETag가 없으면 일반 DELETE로 대체하지 않는다.
  CORS에 DELETE·If-Match 허용과 ETag 노출을 추가했고 기존 출처 제한은 유지했다.
- Worker가 프로세스와 임시 파일을 정리한 후 종료 상태를 기록한다. 완료 쓰기와 취소 접수가
  겹쳐도 먼저 접수된 취소를 완료 결과로 덮지 않는다. 정리 실패는 성공으로 숨기지 않는다.
- lease 만료 후 이전 시도의 폴더를 정리하고 재시도하거나 `failed/max_attempts_exceeded`로 끝낸다.
  종료·기록 없는 UUID 폴더도 Worker 반복 실행에서 정리한다. 무관한 잔여 폴더의 권한 오류는
  경고하고 다음 작업을 계속한다. 실패 폴더는 다음 반복에서 정리를 재시도한다.
- 단일 호스트 `flock`으로 살아 있는 이전 Worker와 새 Worker의 파일 처리 겹침을 막는다.
  Gate/모델 supervisor가 Worker 생존 파이프를 감시해 Worker SIGKILL에도 자식·후손 그룹을 종료한다.
  supervisor도 잠금 FD를 상속하므로 자식 그룹 정리 전 복구가 선행하지 않는다.
  모델별 Python 환경 분리, MPS/CPU 정책은 유지하며 새 의존성은 설치하지 않았다.
- 독립 GPT-6 Astra 검토에서 고아 자식과 무관한 정리 실패의 큐 차단을 실제 재현했다.
  두 지적을 회귀 테스트 3개 RED→GREEN으로 수정했다. 새 API 계약 변경은 없었다.

**바꾼 파일**:

- API: `server/api/analyses.py`, `server/api/__init__.py`.
- Worker·큐·정리: `server/jobs/queue.py`, `server/jobs/worker.py`,
  새 `server/jobs/runtime.py`, `server/jobs/child_process.py`, `server/jobs/supervisor.py`.
- 자식 실행기: `server/gate/runner.py`, `server/axes/signal/waverep.py`.
- 앱: `app/lib/api/analysis_api.dart`, `app/lib/api/models.dart`, `app/lib/api/mock_api.dart`,
  `app/lib/app.dart`, `app/lib/screens/progress_screen.dart`.
- 테스트: 새 `tests/test_analysis_delete.py`, `tests/test_job_lifecycle.py`,
  `app/test/cancel_flow_test.dart`; 갱신 `tests/test_queue_worker.py`,
  `tests/test_cors_and_label.py`, `app/test/flow_test.dart`.
- 실제 실행 확인: 새 `scripts/smoke_cancel_worker.py`.
- 문서: `README.md`, `docs/HANDOFF.md`, `docs/superpowers/plans/2026-11-15-cancel-recovery.md`.

**실행한 명령·테스트 결과**:

```bash
git fetch origin main
git switch -c codex/cancel-recovery-security origin/main
# 아래 python은 /opt/anaconda3/envs/trinity/bin/python (Python 3.11.18)
python -m pytest -q tests/test_analysis_delete.py
python -m pytest -q tests/test_job_lifecycle.py tests/test_analysis_delete.py tests/test_queue_worker.py
python -m pytest -q tests/test_job_lifecycle.py -k 'unrelated or death'
python -m pytest -q tests/test_job_lifecycle.py tests/test_gate_runner.py tests/test_waverep_adapter.py tests/test_waverep_worker.py
python -m pytest -q
python scripts/smoke_cancel_worker.py
cd app
flutter test test/cancel_flow_test.dart --reporter expanded
flutter test --reporter expanded
flutter analyze
```

- 기준 전체: Python **437 passed, 2 skipped**, Flutter **198개 통과**.
- 최종 전체: Python **468 passed, 2 skipped**, 33.33초. 기존 LightGBM 없음·말하는 영상 없음으로 건너뜀.
  `starlette.testclient`의 기존 httpx 폐기 예정 경고 1개는 유지했다.
- 최종 앱: **202개 통과**, `flutter analyze` 문제 없음.
- API 13개 신규 계약 테스트: 401/404/202/반복202/204/삭제 후404,
  ETag의 선점·단계·heartbeat·재시도 중 불변, 종료 시 변경, 412 비파괴, CORS, 취소/finish 경합.
- Worker 테스트: 정상·실패·취소·타임아웃의 정리 선행, 재시도/상한 복구,
  실제 Worker SIGKILL 후 재시작, Gate·모델의 가짜 장기 실행 자식·후손 종료,
  Worker만 SIGKILL 시 자식 종료·폴더 재생성 방지, 정리 권한 오류 격리.
- 실제 스모크 최종: 독립 uvicorn·Worker와 기존 발화 없는 허가 샘플 사용.
  **실제 Gate 자식 실행 확인 → 조건부 DELETE 202 → 반복202 → cancelled**,
  약 **0.99초**에 자식 종료·폴더 삭제 확인. 종료 후 이전 ETag DELETE는 `412`이며
  조회 `200`; 일반 DELETE `204`, 이후 조회·재삭제 `404`.
  스모크의 서버·Worker·임시 DB·복사본은 종료 후 정리했다.
- 초기에 샌드박스 `ps` 실행과 Flutter SDK 캐시 쓰기가 차단됐다. 허용한 환경에서 재실행해 통과했다.
  기존 CORS 테스트의 DELETE 금지 기대값은 승인된 계약에 맞춰 갱신했다.

**실행 방법**:

```bash
conda activate trinity
uvicorn server.main:app --reload
# 같은 DB/runtime/허가 레지스트리 설정을 쓰는 다른 터미널
python -m server.jobs.worker
# 독립 테스트 서버와 Worker를 직접 띄우는 실제 취소 점검
python scripts/smoke_cancel_worker.py
# 앱
cd app
flutter test
```

스모크에는 기존 `data/research/samples/KakaoTalk_Video_2026-11-12-14-34-16.mp4`와
설치된 Gate 의존성/모델이 필요하다. 없으면 미검증으로 종료하며 내려받지 않는다.
`data/runtime/jobs/.worker.lock`은 작업 미디어가 아닌 공통 잠금 파일이므로 유지한다.
운영 중 삭제하면 중복 잠금이 생길 수 있다. Worker가 실행 중인 동안에는 지우지 않는다.

**남은 일·미검증·운영 판단**:

- 정식 인증과 사용자별 rate limit은 이번 범위 밖이며 백로그 14번에 남아 있다.
- 실제 WaveRep 추론 중 취소·강제 종료는 **미검증**(2026-11-19: MPS 추론 중 취소는 확인, 강제 종료는 여전히 미검증 — 실제 Worker 수명주기 확인(2026-11-19, 맨 위 절)). 실제 프로세스 경계는 가짜 모델로 검증했고,
  실제 미디어 취소는 Gate 실행 중에 검증했다. 말하는 허가 영상의 Gate→WaveRep 통과도 기존대로 미검증.
- 실제 브라우저·모바일 기기 터치 조작은 **미검증**. 앱은 HTTP 모의 응답 기반 위젯 테스트로 확인했다.
- ETag는 승인된 수명주기 조건 값이고 단계별 응답 캐시 검증용이 아니다(`no-store`).
- 살아 있으나 멈춘 이전 Worker는 종료해야 새 Worker가 복구한다. 같은 폴더에서 중복 실행/삭제하는
  위험을 막기 위한 결정이다. 자식은 supervisor가 종료하며 새 Worker는 lease 만료 후 복구한다.
- 파일시스템 자체가 삭제를 거부하면 폴더가 즉시 사라진다고 보장할 수 없다. 활성 작업은
  `processing`으로 남아 복구에서 정리를 재시도하고, 종료 작업 DELETE는 `500` 및 기록 보존으로 재시도 가능하다.
- 24시간 정책은 Worker가 계속 실행되고 파일시스템 접근이 가능한 조건에서 반복 정리한다.
  별도 운영 스케줄러·알림은 추가하지 않았다. 기존 서버를 교체할 때는 이전 Worker/자식을 먼저 종료한다.

**막힘:** 요청 범위의 구현·검증에 남은 막힘 없음. 아래는 이전 작업 기록이다.

마지막 갱신: 2026-11-15 · 브랜치 `feat/syncnet` (기준 커밋 `3f0f2b4`)


## Gate 실제 영상 자동 테스트 마무리 (2026-11-15)

- 직전 세션의 `tests/test_gate_media.py` 변경을 이어서 확인했다. 실내 허가 영상
  `data/research/samples/A.MOV`, `B.MOV`, `E.MOV`를 기존 발화 테스트의 개별 사례로 포함한다.
  `samples/speaking/`의 기존 MP4 및 MOV 수집도 유지한다. 현재 그 폴더의 추가 샘플은 없어 별도 실행은 미검증이다.
- 발화 테스트는 무발화 샘플 fixture에 의존하지 않는다. 각 파일이 없으면 해당 사례를 skip하며,
  Gate 의존성·모델·ffmpeg/ffprobe가 없으면 실제 미디어 테스트를 skip한다.
  테스트용 AuthorizedMediaRegistry로 허가 샘플 경로를 확인한다.
- Gate 판정 로직과 임계값은 변경하지 않았다. 기존 기준으로 적합 구간과 입 움직임 구간 존재,
  보류 원인 없음이 A·B·E 각각에서 확인됐다. 정확도나 모든 발화 조건의 검증을 뜻하지 않는다.
- 시작 시 실행 중인 pytest 프로세스가 없었고, 직전 실행의 최종 결과를 확인할 수 없어
  conda trinity Python으로 전체 테스트를 다시 실행했다.
- 결과: **507 passed, 1 skipped, 기존 httpx 경고 1개**, 84.63초.
  건너뜀은 `tests/test_motionphys_train.py`의 LightGBM 미설치다.
  결과 XML에서 `test_speaking_video_has_eligible_segment[A.MOV]`, `[B.MOV]`, `[E.MOV]` 모두
  실패·오류·skip 없이 **PASS**임을 확인했다.
- 재실행(저장소 루트):

```bash
conda activate trinity
python -m pytest -q -rs
# 이번 실행: 개별 영상 통과 증거도 기록
/opt/anaconda3/envs/trinity/bin/python -m pytest -q -rs --junitxml=/private/tmp/trinity-gate-media-final.xml
```

- 변경 파일: `tests/test_gate_media.py`, `docs/HANDOFF.md`만. 영상·가중치·가상환경은 Git 제외 확인.
  사용자 지시에 따라 스테이징·커밋·push하지 않았다. 이 작업에서 멈춘다.

## 최신 작업: 실내 영상 Gate·WaveRep 검증 (2026-11-15)

- **Gate:** 촬영자가 옮긴 허가 샘플 A–E를 Git 밖의 임시 레지스트리에 등록했다.
  A(가로)·B(세로)·E(교대 발화)는 통과했고 C·D는 `no_mouth_movement`로 제외됐다.
  D는 촬영자가 본인 음성만 사용했다고 확인했다. E의 촬영자 기준 발화 30초와
  적합 구간이 24.224초 겹쳤고, 10–20초와 30–40초 침묵 구간은 모두 제외됐다.
  마지막 적합 구간은 기록의 50초 경계를 0.640초 넘었다. 상세 구간은 `docs/gate.md`.
- **WaveRep:** A의 테스트 URL을 FastAPI 테스트 클라이언트에 보내고 별도 Worker로 처리했다.
  Gate 우회 없이 37.021초에서 CPU로 76프레임을 분석했다. 기본 heartbeat 간격 10초에서
  WaveRep 단계의 서로 다른 lease 만료 시각 7개를 관찰했고 임시 작업 폴더 삭제를 확인했다.
  결과는 `finished` / `partial` / `abstained`, `raw_score`·`overall_score`·`verdict_label`은
  `null`이다. Worker 1회 실행 수치와 CPU 대체 근거는 `docs/waverep-adapter.md`.
- **실행 방법:** conda `trinity`에서 `python scripts/run_gate.py <등록한 허가 영상 경로>`.
  서버 연결 확인은 테스트 ID를 A에 연결한 임시 레지스트리·DB를 구성하고 분석 URL을 접수한 뒤
  `python -m server.jobs.worker --drain` 및 결과 조회로 확인했다.
  `python -m pytest -q -rs`는 447개 통과, 2개 건너뜀, 기존 경고 1개.
  건너뜀은 LightGBM 부재와 자동 테스트가 별도 `samples/speaking/*.mp4`만 찾는 경우다.
  A–E의 `.MOV` 검증은 위 Gate 도구로 따로 실행했다.
- **다음:** 실제 WaveRep 추론 중 취소를 PR #12 브랜치에서 재현하고, A의 실제 YouTube ID로
  앱 시연할 경로를 확인한다. 다중 발화, A의 MPS 추론, 실제 앱 시연은 미검증이다.
  SyncNet 1–3 조각의 진행 상태와 남은 검증은 아래 절을 참고한다.


## SyncNet 진행

### A.MOV 오프셋 진단 (2026-11-15, 커밋·push 보류)

- 현재 feat/syncnet에서 시작했고 작업 시작 시 미커밋 변경은 없었다.
  기존 기록을 보존하면서 A 한 개만 SyncNet 진단했다.
- Git 밖 `data/research/syncnet-A-diagnostic/registry.json`에 `SyncNetTstA` → A.MOV 등록.
  기존 Gate 적합 구간 중 최장 25.068–40.335초 내부의 26–34초(8초)를 선택했다.
  경계 여유와 원본 최소 트랙 길이(50프레임)를 고려했다. Gate 설정·임계값은 그대로다.
- 분석 FPS 25 확인. 도구에 음수·0초 및 여러 이동 조건 순차 실행을 추가했다.
  원본 오프셋 +4, 오디오 이동 −0.20/−0.08/0/+0.08/+0.20초에서
  오프셋 +9/+6/+4/+2/−1을 관찰했다. 원본 대비 +5/+2/0/−2/−5로 기대 변화와 일치.
  전 조건 실행 성공, 각각 유효 트랙 1개. 트랙별 LSE-C/LSE-D 전체 표는 docs/syncnet-adapter.md.
- 모든 조건의 분석 구간 영상 프레임 해시는 동일했다. 다만 영속 트랙 ID/프레임별 box를
  반환하지 않으므로 정확한 트랙 대응과 Gate 발화자 동일인 여부는 미검증이다.
  실제 실행·이동 반응 진단이며 진위 판정·탐지 정확도 검증이 아니다. B·E 진단은 하지 않았다.
- 임시 영상·오디오·얼굴 crop 및 진단/프레임 확인 폴더 삭제 확인.
  관련 테스트 3 passed; 전체 pytest **509 passed, 1 skipped**, 기존 경고 1개(LightGBM 없음으로 skip).
- 재실행 명령:

```bash
research/syncnet/.venv/bin/python scripts/diagnose_syncnet_offset.py --registry data/research/syncnet-A-diagnostic/registry.json --media-root data/research/samples --video-id SyncNetTstA --start 26 --end 34 --delays -0.20 -0.08 0 0.08 0.20 > data/research/syncnet-A-diagnostic/results.json
/opt/anaconda3/envs/trinity/bin/python -m pytest -q -rs
```

- 다음 작업: 필요 시 트랙 대응 근거 보강 및 별도 승인된 표본 확대. 이번 작업은 A 진단에서 종료.
  가중치 이용 조건은 기존 확인 필요를 유지한다. 코드·문서만 변경, 커밋·push하지 않는다.
- 아래 조각 1–3 기록의 미검증 표기는 당시 기준이다. 이번 진단은 위 A 구간에 한해 추가 검증했다.


- **현재 조각:** 3/3 Worker 연결 구현 (2026-11-15), feat/syncnet. 조각 1 ffab166·조각 2 9664d3a 기반.
- **한 일:** Gate 적합 구간만 CPU 어댑터에 전달. 수동 Gate 우회는 미실행.
  heartbeat lease 연장·취소·남은 작업 시간 제한 연결. 트랙별 LSE-C/LSE-D/오프셋 내부 계산 결과를 대역 프로세스로 확인.
  모든 구간에 유효 트랙이 있어야 completed. API 대표값은 null, fusion false, explanations에 대표값 집계 보류 표시.
  일부/전체 트랙 없음은 insufficient_input/tracking_failed, 실행 오류는 error/inference_error이며 다른 축 결과를 보존한다.
  docs/DESIGN.md §9·§10·§15.3에 승인된 의미를 기록하고 §14.1 11번 진행 상태를 갱신했다.
  진단 도구 scripts/diagnose_syncnet_offset.py 작성·테스트, 실제 영상 실행 없음.
- **검증:** 최종 전체 `pytest -q -rs`: **504 passed, 2 skipped**, 기존 httpx 경고 1개. 건너뜀은 LightGBM 없음과 자동 Gate 테스트의 speaking/*.mp4 샘플 없음. 독립 코드 리뷰에서 중요 수정 사항 없음.
- **실행 방법:** conda trinity의 `python -m pytest -q -rs`. 진단 도구 사용법은 docs/syncnet-adapter.md.
- **다음 작업:** 실제 발화 A·B·E의 오프셋 실험과 해석, Gate 발화자와 SyncNet 트랙 대응 검증.
- **막힌 점/미검증:** 발화 영상은 확보됐으나 실제 영상 실험·정확도·탐지 추가 기여·실제 모델 Worker 취소는 미검증.
  Worker 강제 종료 후 재시작 복구는 이번 조각에서 검증하지 않았다(2026-11-19: 실제 SyncNet 실행 중 취소·SIGKILL 복구 확인 — 실제 Worker 수명주기 확인(2026-11-19, 맨 위 절)).
  가중치 상업 이용·재배포 및 S3FD 라이선스 범위는 확인 필요. trinity에 torch 설치 없음.
- **커밋:** Worker 연결은 `802a7e0`에 기록했다.
  실내 Gate·WaveRep 검증과 docs/DESIGN.md §14.1 6·7번 갱신은 별도 문서 커밋으로 기록한다.
- **기록:** docs/syncnet-spike.md, docs/syncnet-adapter.md. 조각 1 무발화 샘플은 실행 성공만 기록했다.

## 이전 작업: 백로그 7번 Gate → Worker 연결 (2026-11-15)

**결과:** Gate 연결 구현과 요청한 검증을 마쳤다. 말하는 영상의 실제 통과 경로는 **미검증**이다.
docs/DESIGN.md §15.3에 날짜와 **“Codex, GPT-6 Astra 제안, 사용자 승인”**을 기록했다.
PR 대상은 main이며 merge하지 않는다. 아래 과거 기록의 “Gate 미연결”·“PR #10 열림”은 당시 상태다.
구현 커밋: `f39d203`. push 완료, [PR #11](https://github.com/yeonje14/ai-/pull/11) 생성(열림, 미병합).

**한 일**:

- 최신 main(PR #9·#10 포함)에서 새 브랜치를 만들었다.
- Worker `preprocessing`에서 작업 폴더에 복사한 허가 미디어에 Gate를 실행한다.
  같은 conda `trinity` Python의 별도 프로세스를 쓰고 모델 환경 분리를 유지한다.
  설치된 Gate 패키지와 torch가 없음을 확인했고, trinity에 패키지를 설치하지 않았다.
- Gate가 고른 구간만 WaveRep에 전달한다. 구간이 없으면 모델 단계를 실행하지 않고
  대표 원인·분석 상태·판정 상태를 docs/DESIGN.md §15.3 승인 표대로 기록한다.
  표의 12개 원인 코드 각각을 Worker 결과 테스트로 고정했다.
- Gate 실패/타임아웃은 `gate_error`/`gate_timeout`, `analysis_unavailable`/`abstained`,
  모든 축 점수 `null`. heartbeat로 lease를 연장하고 취소·lease 상실·작업 전체 타임아웃에는
  자식 프로세스 그룹을 종료한다. 작업 전체 타임아웃은 기존 `failed`/`timeout`이다.
- 기존 API 필드와 상태 목록을 유지한다. 적합/제외 구간·원인·품질 숫자는 기존
  `explanations`, 원본/적합/성공 분석량은 기존 `coverage`에 기록한다.
  미실행·실패 분석 길이/비율은 `null`, 분석 구간은 `[]`. coverage는 정확도가 아니다.
- 개발·테스트 전용 수동 구간은 기본 꺼짐. 켰을 때만 Gate 우회,
  `gate_bypassed=true`, `partial`/`abstained`. `raw_score`/`overall_score`/판정 라벨은 계속 `null`.
- 앱은 `access_not_authorized`·`video_access_unavailable`을 “영상 접근 불가”,
  `media_unreadable`·`gate_error`·`gate_timeout`을 “분석하지 못함”으로 구분한다.
  원인 코드를 보류 원인보다 우선해 표시하고, `unsupported`/`insufficient_quality`의
  `abstained`를 “해당 없음”으로 잘못 표시하던 요약도 “보류”로 고쳤다.
- 독립 코드 검토에서 얼굴·입 경계 반올림으로 0초 제외 조각이 생겨 정상 적합 구간까지
  `gate_error`가 되는 결함을 재현했다. Gate 산출 단계에서 빈 조각을 제거하고
  실제 `build_result → parse_result` 회귀 테스트의 실패→통과를 확인했다.

**바꾼 파일**:

- 서버: `server/jobs/worker.py`, `server/config.py`, `server/axes/signal/__init__.py`,
  `server/gate/__init__.py`, `server/gate/segments.py`.
- 새 Gate 실행/결과 처리: `server/gate/runner.py`, `server/gate/process.py`, `server/gate/report.py`.
- 앱: `app/lib/view_state.dart`, `app/lib/screens/result_screen.dart`, `app/lib/screens/detail_screen.dart`.
- 테스트: `tests/test_gate_worker.py`, `tests/test_gate_runner.py`(새 파일), `tests/test_api.py`,
  `tests/test_queue_worker.py`, `tests/test_waverep_worker.py`, `app/test/screens_test.dart`.
- 실제 실행 확인 도구: `scripts/smoke_gate_worker.py`(새 파일).
- 문서: `README.md`, `docs/gate.md`, `docs/waverep-adapter.md`, `docs/HANDOFF.md`,
  `docs/superpowers/plans/2026-11-15-gate-worker.md`.

**실행한 명령과 결과** (Python은 `/opt/anaconda3/envs/trinity/bin/python` 사용):

```bash
python -m pytest -q tests/test_gate_worker.py
python -m pytest -q tests/test_gate_runner.py
python -m pytest -q tests/test_gate_runner.py::test_rounded_face_and_mouth_boundary_keeps_eligible_segment tests/test_gate_segments.py tests/test_gate_mouth.py
python -m pytest -q
python scripts/smoke_gate_worker.py
cd app
flutter test
flutter analyze
```

- 변경 전 전체: 394 passed, 2 skipped.
- 변경 후 최종 전체: **437 passed, 2 skipped**, 30.70초. 건너뜀은 기존 LightGBM 없음과 말하는 영상 없음.
  `starlette.testclient`의 기존 httpx 폐기 예정 경고 1개는 남아 있다.
- 최초 제한 환경 실행은 후손 프로세스 확인용 `ps` 권한 거부로 1개 실패했다.
  권한 허용 후 해당 테스트와 전체 테스트가 통과했다. 제품 오류로 처리하지 않았다.
- 앱: **198개 통과**, `flutter analyze` 문제 없음.
- 실제 서버·Worker 스모크(수정 후 최종): 기존 발화 없는 허가 샘플 10.433초,
  `finished`/`out_of_scope`/`not_applicable`, 원인 `no_mouth_movement`, 적합 길이 0초,
  분석 길이/비율 `null`, 분석 구간 `[]`, `gate_bypassed=false`.
  `raw_score`, `raw_metrics`, `overall_score` 모두 `null`.
  완료 단계는 `validating → access_check → preprocessing → finalizing`이며 WaveRep 단계/실행 로그가 없다.
  임시 작업 폴더 삭제 확인. 약 2.77초. 스모크 설정 heartbeat 0.2초/lease 2초로
  preprocessing의 서로 다른 lease 만료 시각 13개를 관찰했다(기본 10초 간격은 아님).
- 가짜 프로세스로 Gate 비정상 종료·깨진 JSON·오래된 결과·타임아웃·heartbeat·취소·lease 상실,
  작업 전체 제한시간·후손 종료를 검증했다. 실제 미디어 검증은 위 샘플에 한한다.

**실행 방법**:

```bash
conda activate trinity
# 기존 Gate 의존성·모델과 WaveRep 별도 환경은 docs/gate.md, docs/waverep-adapter.md 참고
uvicorn server.main:app --reload
# 다른 터미널, local_path가 있는 Git 밖 레지스트리를 지정한 상태에서
python -m server.jobs.worker
# 독립 임시 서버·Worker로 기존 발화 없는 샘플 확인
python scripts/smoke_gate_worker.py
```

Gate 제한시간은 `TRINITY_GATE_TIMEOUT_SECONDS`(기본 120초), 수동 우회는
`TRINITY_DEV_MANUAL_SEGMENTS`(기본 빈 값). 저장소의 기본 레지스트리는 파일 연결이 없으므로
일반 실행에서는 Git 밖 레지스트리에 허가 샘플의 상대 `local_path`를 지정해야 한다.
스모크 도구는 이를 임시로 구성하고 끝나면 서버·Worker·임시 DB·복사본을 정리한다.

**남은 일·미검증**:

- 실제 말하는 허가 영상의 Gate 통과 → WaveRep 실행. 영상이 아직 없다.
- Gate의 발화/입 움직임 임계값, 다중 발화, 장시간·저품질·회전·가변 프레임률 영상.
- 실제 미디어가 오래 걸리거나 멈춘 상황의 취소·타임아웃(가짜 프로세스로 검증).
- 큰 미디어 파일 복사 중 heartbeat는 기존대로 없음. 이번 변경은 Gate 실행 구간을 포함한다.
- 실제 앱 브라우저·모바일 기기 조작은 미검증(Flutter 위젯 테스트·정적 검사만 실행).
- 다음 작업은 말하는 허가 영상 확인과 백로그 8번 데이터/평가 준비를 따른다.
  프레임 logit 집계/임계값·판정은 이번 작업 범위가 아니다. physics/alignment는 기존 stub 유지.
- Gate 모델 파일 이용 조건의 기존 “확인 필요”는 그대로이며 새 다운로드는 없다.

**막힘:** 이번 연결 작업의 구현·테스트에 막힘 없음. 실제 발화 영상 검증은 자료가 필요하다.

## 이전 세션 기록


## 오늘 밤 결과 요약 (2026-11-15, 무인 작업)

밤사이 작업 1과 작업 2만 했다. 작업 3·4는 시작하지 않았다. 중간에 사용량 한도로 멈춰서 작업 2의 커밋은 모델을 바꿔 이어서 했다. 아침에 저장소 소유자의 지시로 PR #9를 먼저 main에 합쳤고, PR #10 브랜치를 그 위로 옮겨 README·HANDOFF 충돌을 두 작업 내용이 모두 남도록 해결했다.

| 작업 | 상태 | 브랜치 | PR |
|---|---|---|---|
| 1. WaveRep을 Worker에 연결 (백로그 7번) | **완료.** 코드, 테스트, 실제 실행 확인, 커밋, push, PR까지 | `feat/waverep-worker` (`1c1c47a`) | #9 (**main에 합침**, `0e207cf`) |
| 2. Gate 보완 (입 움직임, VAD 비교) | **완료(말하는 영상은 미검증).** 코드, 테스트, 커밋, push, PR까지 | `feat/gate-mouth-motion` | #10 (열림) |

**작업 1이 된 것** (자세한 내용은 아래 "백로그 7번: WaveRep을 Worker에 연결" 절):

- signal 축 stub을 WaveRep 어댑터 호출로 바꿨다. 기본값은 MPS, 배치 1, 초당 2장이다.
- 레지스트리 `local_path`의 허가 미디어를 작업 폴더로 복사해 모델에 넘긴다.
- 개발 전용 수동 구간 `TRINITY_DEV_MANUAL_SEGMENTS`를 추가했다. 기본은 꺼짐이다. 켜면 `gate_bypassed=true`, `partial`, `abstained`가 된다.
- 추론 중에 주기적 heartbeat로 lease를 연장한다. 타임아웃과 실패는 점수 `null`로 격리한다.
- 결과에는 프레임 logit 요약만 둔다. `raw_score`와 `overall_score`는 `null`이다.
- `pytest -q` 352개 통과, 1개 건너뜀(lightgbm).
- 서버와 Worker를 띄워 등록 테스트 ID와 샘플 영상으로 실제 WaveRep을 실행했다. 프레임 21장, mps, 추론 6.07초였다.
- 미검증: 실제 추론이 heartbeat 간격(10초)보다 짧게 끝나서, 실제 모델 실행 중 lease가 연장되는 것은 관찰하지 못했다. 가짜 추론 프로세스 테스트로만 확인했다.

**작업 2가 된 것**: 아래 "Gate 보완" 절.

**아침에 확인할 것**:

1. **PR #9의 동작 변화.** 등록 ID라도 `local_path`(미디어 파일)가 없으면 이제 `analysis_unavailable` / `video_access_unavailable`로 끝난다. 아무 설정 없이 `smoke_slice.py`를 돌리면 `TRINITYtest`가 접근 불가로 나온다.
2. **PR #9의 docs/DESIGN.md §15.3 변경 제안 4개.** `gate_bypassed`, `raw_metrics`, `video_access_unavailable`, 축 원인 코드에 관한 것이다. docs/DESIGN.md §9·§10 본문은 바꾸지 않았다. 승인 여부를 정해야 한다.
3. **샘플 영상의 오디오에 사람 목소리가 들어 있는지 들어 볼 것.** webrtcvad, Silero, YAMNet 세 방식이 모두 대부분을 음성으로 판정했다. 목소리가 있다면 VAD의 오판이 아니다.
4. **말하는 영상으로 Gate 검증.** 찍은 영상을 `data/research/samples/speaking/`에 넣고 `pytest -q tests/test_gate_media.py`를 돌린다. 지금은 이 테스트를 건너뛴다.
5. **두 PR을 합치는 순서.** 두 브랜치가 모두 `server/config.py`, `README.md`, `docs/HANDOFF.md`를 고쳐서 나중에 합치는 쪽에서 충돌이 난다. Gate를 Worker에 연결하는 일(수동 구간 대신 Gate 구간 사용, `gate_not_connected` 제거)은 두 PR이 모두 합쳐진 뒤에 한다.
6. 받은 모델 파일 3개(`face_landmarker.task`, Silero VAD v6.0 ONNX, YAMNet)의 이용 조건. 아직 확인하지 않았다.
7. 원래 Gate 브랜치 `feat/gate-speech-segments`는 그대로 남겨 두었다. 정리할지는 저장소 소유자가 정한다.


## Gate 보완: 입 움직임 확인, VAD 비교 (2026-11-15 밤, 무인 작업)

**계획** (작업 전 기록):

- `feat/gate-speech-segments`의 커밋 2개를 최신 main 위의 새 브랜치 `feat/gate-mouth-motion`으로 옮긴다(원래 브랜치는 건드리지 않는다). CLAUDE.md 충돌은 Gate 의존성 줄을 AGENTS.md "명령"으로 옮겨 해결한다.
- MediaPipe Face Landmarker(공식 배포 모델, sha256 기록)로 입 벌림(안쪽 입술 거리 / 두 눈 바깥꼬리 거리)을 초당 약 15장에서 잰다. 음성 구간 안에서 입 벌림이 변하는 부분만 발화로 인정한다.
- webrtcvad 민감도 0~3과 torch 없는 VAD 후보를 `research/gate/.venv`에서 비교한다. trinity 환경에는 아무것도 설치하지 않는다.
- 샘플(야외, 발화 없음)이 발화 없음 계열 원인 코드로 걸러지는지 확인하고, 기대값이 틀린 테스트를 고친다.
- 말하는 영상 검증은 하지 않는다("미검증").

**결과**:

- **브랜치**: `feat/gate-speech-segments`의 커밋 2개를 최신 main(`283c4d1`) 위로 옮겼다(새 커밋 `9f8fcb2`, `77df736`). 충돌은 세 군데에서 났다.
  - CLAUDE.md: main 쪽(`@AGENTS.md` 한 줄)을 남기고, Gate 의존성 줄은 AGENTS.md "명령"으로 옮겼다.
  - docs/DESIGN.md §14.1: main 쪽 표에 Gate의 6번 행만 넣었다.
  - HANDOFF: 두 쪽을 다 남겼다.
- **새 파일과 바꾼 파일**:
  - `server/gate/mouth.py`: 입 벌림 측정(Face Landmarker).
  - `server/gate/mouth_activity.py`: 반전 세기와 움직인 구간을 찾는 순수 함수.
  - `segments.py`: 음성 구간을 입이 움직인 조각과 아닌 조각으로 나눈다.
  - `types.py`: `no_mouth_movement`, `NO_SPEECH_FAMILY`, 임시 임계값, 결과 필드를 추가했다.
  - `faces.py`: 모델 해시 확인을 공통 함수로 바꿨다.
  - `configs/gate_models.json`: `face_landmarker` 항목과 해시를 넣었다.
  - `research/gate/compare_vad.py`, `research/gate/requirements-compare.txt`.
  - `tests/test_gate_mouth.py`(새 파일), `tests/test_gate_media.py`(기대값 수정).
- **규칙**: 음성과 입 움직임이 함께 있을 때만 발화로 인정한다. 입 움직임은 입 벌림이 0.02 이상 되돌아간 반전을 세서 정한다. 0.75초 안에 반전이 3번 이상 이어지면 움직인 것으로 본다. 한 번 벌렸다 닫는 것(샘플 0.3~1.0초)은 발화로 세지 않는다. 임계값은 전부 임시값이다.
- **샘플(야외, 발화 없음)**: 이제 `no_mouth_movement`(발화 없음 계열)로 끝나고 적합 구간은 0초다. webrtcvad 민감도 0~3 모두 같은 결과다.
- **고친 테스트**: `test_single_speaker_video_has_eligible_segment`가 이 영상에 적합 구간이 있다고 기대했는데, 그 기대가 틀렸다. `test_sample_without_speech_has_no_eligible_segment`로 바꿨다. 원인 코드 분리 테스트는 변형본 3개(오디오 없음, 검은 화면, 무음)로만 비교한다.
- **VAD 비교** (표는 `docs/gate.md`):
  - 샘플 오디오를 음성으로 판정한 비율: webrtcvad 0.99/0.94/0.81/0.81(민감도 0~3), Silero VAD(ONNX) 0.74, YAMNet 0.91.
  - 합성 음성에 샘플 오디오를 섞은 조건의 오경보율은 Silero가 가장 낮았다.
  - 결정: **VAD는 webrtcvad 민감도 2를 그대로 쓴다.** Silero는 교체 후보로 남긴다.
  - 합성 음성은 실제 발화가 아니다. 이 비교로 정확도를 주장하지 않는다.
- **설치와 다운로드**:
  - `research/gate/.venv`에만 `onnxruntime` 1.32.0과 `protobuf` 7.36.2를 설치했다. dry-run으로 torch가 딸려 오지 않는 것을 먼저 확인했다. conda `trinity`에는 아무것도 설치하지 않았다.
  - 모델은 공식 출처(MediaPipe 모델 저장소, Silero 공식 GitHub 태그 v6.0)에서만 받았다. sha256은 `docs/gate.md`에 적었다.

**검증** (2026-11-15):

- `pytest -q`: 357개 통과, 2개 건너뜀. 건너뛴 것은 lightgbm 테스트(전부터 그랬다)와 말하는 영상 테스트(영상 없음)다.
- `python scripts/run_gate.py`로 샘플 영상을 돌렸다. `no_mouth_movement`, 입 벌림 표본 157개를 모두 쟀고 반전은 1번, 실행 약 2.3초였다.

**미검증**: 말하는 영상(내일 저장소 소유자가 찍은 영상으로 확인), 입 움직임 임계값, 다중 발화, 긴 영상의 실행 시간, 씹기·웃음처럼 말하지 않고 입이 움직이는 경우.

**남은 일**: 말하는 영상으로 임계값을 확인한다. 그다음 Gate를 Worker에 연결한다(PR #9가 합쳐진 뒤, 백로그 7번의 남은 일). Silero VAD 교체는 실제 발화 영상으로 다시 비교한 뒤 정한다.

**막힘**: 없음.

## 백로그 7번: WaveRep을 Worker에 연결 (2026-11-15 밤, 무인 작업)

**계획** (작업 전 기록):

- 레지스트리 항목에 서버 쪽 `local_path`(허가 미디어 파일, 미디어 루트 안의 상대 경로)를 둔다. 등록됐지만 파일이 없으면 `analysis_unavailable` / `video_access_unavailable`.
- `preprocessing`에서 허가 미디어를 작업 폴더로 복사하고, 모델 프로세스에는 작업 폴더 경로만 넘긴다.
- signal 축 stub을 `run_waverep` 호출로 바꾼다. 기본 MPS, 배치 1, 초당 2장.
- 개발 전용 수동 구간 설정 `TRINITY_DEV_MANUAL_SEGMENTS`(기본 꺼짐). 켜면 `gate_bypassed=true`, `partial`, `abstained`. 끄면 구간이 없으므로 signal 축은 실행하지 않는다.
- 큐에 `heartbeat()`를 추가하고 추론 프로세스를 기다리는 동안 주기적으로 lease를 연장한다. 취소·lease 상실·작업 타임아웃이면 추론 프로세스를 끝낸다.
- 축 타임아웃·실패는 `status=error`, 점수 `null`. 결과에는 프레임 logit 요약만 둔다.

**결과**:

- **바꾼 파일**: `server/jobs/worker.py`, `server/jobs/queue.py`(`heartbeat()`), `server/axes/__init__.py`(`AxisContext`), `server/axes/signal/__init__.py`(stub → 어댑터 호출), `server/axes/signal/waverep.py`(`on_tick`), `server/ingest/media_resolver.py`(`local_path`), `server/config.py`, `server/schemas/__init__.py`, `scripts/smoke_slice.py`(대기 시간), `tests/test_waverep_worker.py`(새 파일) 외 기존 테스트 3개.
- **허가 미디어 파일**: 레지스트리 항목의 `local_path`. 절대 경로, `..`, 루트 밖을 가리키는 심볼릭 링크는 설정을 읽을 때 거부한다. 저장소의 `configs/authorized_media.json`에는 `local_path`가 없다.
- **동작이 달라진 점**: 등록 ID라도 미디어 파일이 없으면 이제 `analysis_unavailable` / `video_access_unavailable`이다. 그래서 **아무 설정 없이 `smoke_slice.py`를 돌리면 등록 ID `TRINITYtest`는 접근 불가로 나온다**(전에는 stub으로 `partial`). 미디어를 연결한 레지스트리를 `TRINITY_AUTHORIZED_MEDIA`로 줘야 `partial`이 된다.
- **수동 구간 꺼짐(기본)**: signal 축은 `insufficient_input` / `gate_not_connected`, 모델 실행 안 함. `gate_bypassed=false`.
- **수동 구간 켬**: 모델 실행. `gate_bypassed=true`, `partial`, `abstained`, `overall_score=null`, 설명에 `GATE_BYPASSED_DEV`. 스키마가 `gate_bypassed`인데 `assessed`·`completed`·점수 있는 결과를 거부한다.
- **결과에 남는 것**: `axes.signal.raw_metrics.frame_logit`(프레임 수, 평균, 중앙값, 최소, 최대, 표준편차)뿐이다. 프레임별 값·실행 시간·stderr는 결과에 넣지 않는다. `raw_score`는 `null`.
- **coverage**: 영상 길이와, signal 축이 끝낸 구간(영상 길이로 자르고 겹침을 합침). `eligible_*`는 Gate가 없어 `null`.
- **heartbeat**: 추론 프로세스를 기다리는 동안 `TRINITY_HEARTBEAT_INTERVAL_SECONDS`(기본 10초)마다 lease를 연장한다. 추론 중 취소 → 프로세스 종료 후 `cancelled`, lease 상실 → 종료 후 아무것도 쓰지 않음, 작업 타임아웃 → 종료 후 `failed`/`timeout`.
- **격리**: 축 타임아웃(`TRINITY_WAVEREP_TIMEOUT_SECONDS`, 기본 300초)과 추론 실패는 `status=error`, 점수 `null`이고 나머지 축과 작업은 계속된다.
- **남긴 stub**: physics·alignment 축은 그대로 `stub_not_executed` / `model_version=stub`이다.

**검증** (2026-11-15):

- `pytest -q`: 352개 통과, 1개 건너뜀(`test_motionphys_train.py`, trinity 환경에 lightgbm이 없어서. 전부터 그랬다). 새 테스트는 가짜 추론 프로세스를 쓴다.
- 실제 실행: uvicorn + Worker를 띄우고 `smoke_slice.py`로 등록 ID `TRINITYtest` + 본인 촬영 샘플(`data/research/samples/`, 10.43초)을 요청했다.
  - `TRINITY_DEV_MANUAL_SEGMENTS=0-10.5`: `queued → processing/waverep → finished`. `gate_bypassed=true`, `partial`, `abstained`, `overall_score=null`, signal `completed`, `raw_score=null`, 프레임 21장, 장치 mps, 추론 프로세스 6.07초. logit 평균 -0.675, 중앙값 -0.900, 최소 -5.217, 최대 4.670. coverage 10.433초 / 10.433초. 작업 폴더는 남지 않았다.
  - 수동 구간 없음: signal `insufficient_input` / `gate_not_connected`, `gate_bypassed=false`, `partial`, `abstained`.
  - 미등록 ID `analysis_unavailable` / `access_not_authorized`, 잘못된 URL 422, 없는 작업 404.
- 가중치는 새로 받지 않았다. 기존 `weights_dinov2_G4.ckpt`의 md5는 `8bf19e6f68a92bed600dd97fbed3f2cd`로 기록값과 같다.

**미검증**:

- 실제 추론이 약 7초로 heartbeat 간격(10초)보다 짧았다. **실제 모델 실행 중의 lease 연장은 관찰하지 못했고**, 가짜 추론 프로세스 테스트(lease 1초, 추론 2.5초)로만 확인했다.
- 발화가 있는 영상, 합성 영상, 긴 영상, 504px 미만 영상에서의 Worker 실행.
- 큰 미디어 파일을 작업 폴더로 복사하는 동안에는 heartbeat가 없다(3.6MB 샘플에서는 문제없음).
- Flutter 앱의 실제 서버 모드에서 새 필드가 있는 결과를 여는 것(앱 코드는 바꾸지 않았다).

**§15.3 변경 제안 (docs/DESIGN.md §9·§10은 바꾸지 않았다. 승인하면 문서에 반영)**:

1. §9 결과에 `gate_bypassed`(bool, 기본 `false`)를 적는다. `true`면 개발용 결과이며 항상 `partial` / `abstained` / `overall_score=null`.
2. §9 `axes.signal`에 `raw_metrics.frame_logit` 요약을 적는다. `raw_score`는 집계 방법이 정해질 때까지 `null`.
3. §9 "접근 불가 결과"에 "등록됐지만 미디어 파일이 없는 ID는 `video_access_unavailable`"을 적는다. 백로그 4번 완료 조건의 "등록된 허가 ID는 작업→결과 완료"는 미디어 파일이 연결된 ID에만 해당하게 된다.
4. §10 축별 원인 코드에 `gate_not_connected`(임시, Gate 연결 시 제거), `timeout`, `aborted`, `media_unreadable`, `model_unavailable`을 적는다. 설명 원인 코드 `gate_bypassed`도 같다.

**7번에서 남은 일**: Gate 연결(수동 구간 설정과 `gate_not_connected` 제거), 프레임 logit을 `raw_score`로 집계하는 방법 결정(백로그 8번 이후), physics·alignment stub 교체.

**실행**: docs/DESIGN.md 하단 "서버 실행 방법"의 "실제 WaveRep 실행(개발 전용)".

## 앱 디자인 개정: 밝은 테마, 웹형·앱형 홈 (백로그 13번, 2026-11-14)

시안(`trinity-web-preview.html`, `trinity-app-preview.html`)의 방향을 Flutter 앱에 옮겼다. 모델 미연결 · 가상 데이터는 그대로다. API, 서버, 상태 대응, `verdict_label` 규칙은 바꾸지 않았다. 자세한 내용과 변경 이유는 `docs/design-system.md` "변경 기록".

- **먼저 한 일**: PR #7(Flutter 앱 뼈대)을 main에 합친 뒤 최신 main에서 브랜치를 만들었다.
- **테마**: 밝은 테마가 기본, 시스템이 어두운 모드면 어두운 테마(시안의 어두운 값). 이전의 `#0A0A0A` 팔레트는 없앴다. 모서리 반경 0 → 카드 14, 버튼·입력란 8, 라벨 6.
- **상태 색(밝은 테마)**: 발견 `#B63A13`, 보류 `#805B05`, 낮음은 무채색 `#2B2B2B` / 바탕 `#E8E8E8`. 이전 `#FF3D00`(흰 배경 3.55:1)과 `#FACC15`(1.53:1)는 밝은 배경에서 기준에 못 미쳐 쓰지 않는다. 두 테마의 모든 글자·배경 조합의 대비 계산이 테스트에 들어 있다(상태 색 최소 5.24:1).
- **홈**: 768 이하면 앱 배치(왼쪽 정렬 두 줄 제목, 설명, 주소 입력 카드, 폭을 채우는 버튼), 넓으면 웹 배치(가운데 워드마크, 한 줄 소개, 폭 680 캡슐 입력창, "분석 요청"과 mock 전용 "예시로 둘러보기", 접힌 "무엇을 분석하나요?", 오른쪽 위 작은 "이용 안내").
- **그 밖의 화면**: 결과에 "이번 요청의 상태"(작업·분석·판정)와 범위 카드 "어디까지 살펴봤나요?"를 넣었다. 접근 불가와 대상 아님도 같은 결과 화면 틀을 쓴다. 이용 안내 화면을 추가했고 어느 화면에서든 열 수 있다(닫으면 보던 화면으로 돌아온다).
- **가져오지 않은 것**: 시안 전용 문구, 원형 장식, 시안의 "아직은 판단할 근거가 부족해요" 제목(보류 이유와 맞지 않을 수 있다), Lucide 아이콘(Material 아이콘으로 대신), 600·650·750 굵기.
- **design-for-ai**: 지침을 읽고 참고했다. `build` 흐름(자동 커밋, 검토 에이전트)과 `research` 명령은 실행하지 않았고 `DESIGN.md`는 만들지 않았다. 지침과 다른 결정 두 가지(768 고정 전환, 가운데 정렬 웹 홈)는 문서에 적었다.
- **실행**: 이전과 같다(`app/README.md`). 브라우저 창 너비로 웹형·앱형이 바뀐다.
- **검증**: `flutter analyze` 문제 없음, `flutter test` 193개 통과(모든 화면이 너비 320·360·768·769·1280과 글자 크기 2배에서 넘치지 않음). `flutter build web --no-web-resources-cdn` 성공, headless Chrome 1280×800에서 웹 홈 확인. 모든 화면을 실제 글꼴로 렌더링해 앱 너비·웹 너비·어두운 테마를 눈으로 봤다. `pytest -q`는 서버를 바꾸지 않아 다시 돌리지 않았다(직전 315개 통과).
- **미검증·확인 필요**: 실제 서버 모드를 Chrome에서 손으로 끝까지 가 본 것, 어두운 테마를 브라우저에서 본 것, iOS·Android 기기, 화면 낭독기, 노년층 가독성, 시안과의 픽셀 단위 비교.
- **남은 일**: 저장소 소유자의 화면 검토와 피드백 반영, 공유 시트(iOS·Android), 플랫폼 빌드 설정, 미디어 확인 화면, 취소·삭제.


## Claude Code 디자인 플러그인 설치 확인

- `ryanthedev/design-for-ai` 저장소와 Claude Code 공식 설치 문서를 확인했다. 저장소는 `rtd` 마켓플레이스의 `design-for-ai` 설치와 research → plan → mock → build 흐름을 안내한다.
- 사용자의 `/reload-plugins`가 성공했다. 프로젝트 루트에서 `claude plugin list --json`을 실행해 `design-for-ai@rtd` 4.2.0이 `local` 범위로 설치되고 활성화된 상태를 확인했다.
- 다음 작업: Claude Code에서 `/design-for-ai:research`를 실행해 기존 웹·앱 시안을 디자인 브리프로 정리한다. research 명령 실행은 아직 확인하지 않았다.
- 사용 시: 이미 정한 웹 검색형·앱 세로형 방향과 docs/DESIGN.md의 판정/입력 규칙을 유지하도록 전달한다. 플러그인의 기본 build 흐름에 검토 에이전트와 단계별 커밋이 포함되므로 자동 커밋·푸시를 원하지 않는 경우 사용자 지시로 명확히 제한한다.

## 웹 앱 디자인 시안 (검토용 · 제품 미반영)

- **후속 시안(2026-11-14)**: 사용자 요청에 따라 웹은 중앙 로고·주소 입력·접힌 설명의 검색형 홈, 앱은 390px 기준 세로형 홈으로 나눴다. 색·글꼴·버튼·결과의 의미는 공유하고 화면 구성을 달리한다. Claude Code에서 기존 Flutter 앱에 반영하도록 전달할 구현 프롬프트도 대화에 제공했다.
- **최신 시안 경로**: 웹 `/Users/iyeonje/.codex/visualizations/2026/11/01/01a1964d-85b8-7920-b247-cf9cb86a6c5d/trinity-web-preview.html`, 앱 `/Users/iyeonje/.codex/visualizations/2026/11/01/01a1964d-85b8-7920-b247-cf9cb86a6c5d/trinity-app-preview.html`. 아래의 `trinity-calm-preview.html`은 최초 통합 시안이다.
- **후속 확인**: 두 파일의 HTML 중첩·ID 참조·JavaScript 구문 점검 통과. 브라우저에서 웹·앱 첫 화면과 예시 시작 → 진행 → 판단 보류 전환을 확인했다. 앱 시안은 320px 뷰포트(내부 288px)에서 입력·결과의 가로 넘침 없음. 모바일 네이티브 앱을 빌드하거나 테스트한 것은 아니다.
- **한 일**: 밝고 차분한 화면 구성을 제안하는 클릭 가능한 시안을 만들었다. URL 입력 → 분석 중 → 결과 → 판단 근거와 이용 안내를 포함한다. 결과 예시는 판단 보류·의심 신호 발견·의심 신호 낮음·영상 접근 불가로 바꿀 수 있다. 가상 데이터 고지, URL-only, 상태 분리, 값 없음, 분석 범위의 의미를 유지했다.
- **위치/보는 방법**: Codex 대화의 시안에서 “예시로 둘러보기”를 누른다. 원본은 `/Users/iyeonje/.codex/visualizations/2026/11/01/01a1964d-85b8-7920-b247-cf9cb86a6c5d/trinity-calm-preview.html`에 있다. 서버·모델 연결 없이 화면만 전환한다.
- **확인**: 브라우저에서 예시 시작, 분석 중 → 판단 보류, 의심 신호 발견으로 전환, 판단 근거 화면을 확인했다. 320px 뷰포트에서 입력·결과 영역의 가로 넘침이 없음을 확인했다. 미리보기의 폼 제출 제한을 확인하고 로컬 버튼/Enter 동작으로 처리했다. 수정 후 빈 입력 안내와 올바른 URL 입력의 화면 전환을 다시 확인했다.
- **남은 일/막힌 점**: (2026-11-14 갱신) Flutter 반영을 마쳤고 밝은 테마·둥근 모서리를 채택했다. 위 "앱 디자인 개정" 절을 본다. 아래는 시안을 만들 때의 기록이다. 앱 코드와 API 계약은 바꾸지 않았다. 앱 테스트를 다시 실행한 것은 아니며, 모든 기기·화면 낭독기 검증은 미검증이다.

## 백로그 13번: Flutter 앱 (진행 중, 앞부분만. 웹에서만 확인)

모델 미연결이다. 화면의 결과는 가상 데이터이며 모든 화면 상단에 "모델 미연결 · 가상 데이터" 띠가 있다. 자세한 내용은 `docs/design-system.md`, `app/README.md`.

- **API 계약 변경(docs/DESIGN.md §9, 결정 8)**: 결과에 `verdict_label`(`suspicious_signals` / `low_suspicion` / `null`)을 추가했다. 요약 화면이 숫자 없이 발견과 낮음을 구분하기 위한 필드다. `verdict_status=assessed`일 때만 값을 가질 수 있고(스키마가 거부), 검증된 결합 모델이 없어 **서버는 항상 `null`을 보낸다.**
- **서버 CORS**: `TRINITY_CORS_ORIGINS`(기본 `http://localhost:8080,http://127.0.0.1:8080`). localhost·127.0.0.1만 받고 `*`와 다른 호스트는 시작할 때 거부한다. 메서드는 GET·POST, 헤더는 `Content-Type`·`X-Client-Token`만 연다. 빈 값이면 끈다.
- **만든 파일**: `app/`(Flutter 웹 프로젝트), `docs/design-system.md`, `tests/test_cors_and_label.py`. 바꾼 파일: `server/{config.py,api/__init__.py,schemas/__init__.py,jobs/worker.py}`, `tests/test_api.py`(계약 키 목록).
- **디자인 시스템**: 색 토큰 8개(초록 없음, 강조색은 "의심 신호 발견"에만), Inter Tight + JetBrains Mono + Noto Sans KR, 모서리 반경 0, 8pt 그리드, 좌우 여백 20. 공통 위젯 8종. 본문 16, 보조 13, 줄간격 1.5, 글자 대비 5.2:1 이상, 터치 영역 48.
- **글꼴**: 쓰는 굵기 5개만 `app/assets/fonts/`에 넣었다(약 4.9MB). OFL 원문은 `app/assets/fonts/licenses/`. Fontsource 배포본을 받았고 파일 해시를 문서에 적었다.
- **화면 8개**: 입력, 분석 중(단계명만, 숫자 % 없음), 결과 3종(발견 / 낮음 / 판단 보류, 숫자 점수 없음), 판단 근거 상세(원시 지표에 "확률 아님", `null`은 "값 없음"), 영상 접근 불가, 분석 대상 아님. 작업 실패·취소는 분석 중 화면의 "끝내지 못함" 상태로 보여 준다.
- **모드**: `--dart-define=TRINITY_API_MODE=mock|server`, `TRINITY_API_BASE_URL`. mock은 입력 화면에서 가상 결과 6종을 고른다. **실제 서버 모드에서는 라벨이 와도 발견·낮음을 보여 주지 않는다**(판단 보류로 표시).
- **실행**:
  ```bash
  cd app && flutter pub get
  flutter run -d chrome --web-port 8080 --no-web-resources-cdn                      # mock
  flutter run -d chrome --web-port 8080 --no-web-resources-cdn \
    --dart-define=TRINITY_API_MODE=server --dart-define=TRINITY_API_BASE_URL=http://localhost:8000   # 서버와 Worker가 떠 있을 때
  flutter analyze && flutter test
  dart run tool/smoke_server.dart http://localhost:8000 'https://www.youtube.com/watch?v=TRINITYtest'
  ```
- **검증**:
  - `flutter analyze` 문제 없음, `flutter test` 122개 통과(Flutter 3.41.6). 화면마다 글자 크기 1.3배·2배(360×640, 320×568)에서 넘침 없음.
  - `pytest -q` 315개 통과, 1개 건너뜀(conda `trinity`).
  - `flutter build web --no-web-resources-cdn` 성공. Chrome(headless)에서 mock 모드 입력 화면이 번들 글꼴로 뜨는 것을 확인했다.
  - 실제 서버 + Worker에 앱의 API 클라이언트로 요청: 등록 ID는 8단계를 거쳐 `partial / abstained / verdict_label=null`(판단 보류 화면), 미등록 ID는 `analysis_unavailable`(접근 불가 화면), YouTube가 아닌 주소는 422. `localhost:8080` 출처의 CORS 사전 요청은 200, 다른 출처는 400.
- **미검증·확인 필요**:
  - 실제 서버 모드를 Chrome에서 손으로 눌러 끝까지 가 본 것은 아니다.
  - iOS·Android 기기, 화면 낭독기, 실제 노년층 사용자 가독성.
  - Fontsource 패키지의 정확한 버전(`@latest`로 받음), Noto Sans KR OFL의 Reserved Font Name 조항과 부분집합 파일의 관계.
- **남은 일 (13번)**: YouTube 공유 시트 수신(iOS·Android), 플랫폼 빌드 설정, 미디어 확인 화면(제목·썸네일), 취소·삭제, 새로고침 뒤 작업 복원(토큰 저장은 백로그 14번의 인증과 함께), 모델 연결 뒤 고지 띠 제거 조건 정하기.


## 백로그 9번: 압축 에뮬레이터 (범용 프로파일까지. 플랫폼 파라미터 추정은 하지 않음)

실제 YouTube의 재인코딩과 같다고 주장하지 않는다. 어떤 영상도 YouTube에 올리지 않았다. 성능 결과가 아니다. 자세한 내용은 `docs/compression-emulator.md`.

- **공개 코드**: `truebees-ai/social_emulator`가 있다(커밋 `3e1a39a`, `LICENSE`는 CC BY 4.0). `research/emulator/upstream/`에 clone(Git 제외)하고 수정 없이 `research/emulator/.venv`에서 두 단계를 실행했다. `breakpoint()`가 남아 있어 `PYTHONBREAKPOINT=0`으로 껐다.
- **저자 방식의 에뮬레이션은 못 했다**: 원본과 플랫폼 처리본의 쌍이 필요한데 저장소에 파라미터 파일과 샘플이 없고 우리에게 처리본이 없다. 플랫폼 처리본 자리에 로컬 파일(`x264-crf28-720p`)을 넣어 동작만 확인했다. 해상도는 되찾았고 CRF는 28이 아니라 29로 나왔다(비트레이트가 처음 낮아지는 값을 고르는 규칙). 원본 코드의 출력에는 오디오가 없다.
- **만든 파일**: `training/emulator/{profiles,video,pipeline}.py`, `research/emulator/{run_upstream_smoke.py,requirements.lock.txt}`, `scripts/compression_profile_report.py`, `tests/test_emulator.py`, `docs/compression-emulator.md`. 표준 라이브러리만 쓴다(trinity에 새 의존성 없음).
- **범용 프로파일**: libx264 CRF 20/28/34 × 원본/1080/720/480(짧은 변) = 12개. 하드웨어 인코더 거부, 업스케일은 `skipped_upscale`, 오디오는 복사.
- **`emulate(입력, 프로파일 ID, 출력 폴더)`**: 스레드 고정 + bitexact + 메타데이터 제거로 같은 입력이면 같은 바이트. 설정·FFmpeg 버전·입출력 sha256·계보·상태를 출력 옆 `.json`에 기록. 원본과 기존 출력을 덮어쓰지 않는다.
- **manifest·평가 연결**: 선택 열 `compression_profile_id`(빈칸은 원본, 예전 manifest도 읽힘). 파생 행은 부모의 분할과 계보를 물려받는다. 리포트에 `by_compression`(조건별 AUC·TPR·실제 FPR, 그룹 bootstrap). 리포트 `schema_version` 2.
- **출력 비교** (본인 촬영 영상 1개, 1080p 10.4초): 12개 모두 두 번 실행한 sha256이 같다. 영상 비트레이트는 CRF 20 원본 해상도 5,768 kbps에서 CRF 34 480p 218 kbps까지. 표는 문서 §5.
- **규칙(저장소 소유자 결정, 2026-11-14)**: 최종 평가에 남겨 둘 프로파일은 학습을 시작하기 전에 고정한다. 어떤 프로파일을 남길지는 아직 정하지 않았다.
- **실행**:
  ```bash
  conda activate trinity
  pytest -q
  python scripts/compression_profile_report.py --video data/research/samples/<허가 영상>.mp4
  python -m training.emulator.pipeline --manifest <m.csv> --media-root <dir> --profile x264-crf28-720p --out-dir <dir> --out-manifest <m2.csv>
  research/emulator/.venv/bin/python research/emulator/run_upstream_smoke.py --video data/research/samples/<허가 영상>.mp4
  ```
  환경 준비는 문서 §7. 두 스크립트는 출력 폴더가 이미 있으면 멈춘다(`data/research/emulator/` 아래, Git 제외).
- **검증**: `pytest -q` 290개 통과, 1개 건너뜀(conda `trinity`, LightGBM이 없는 `tests/test_motionphys_train.py`).
- **미검증·확인 필요**: 다른 기기·다른 FFmpeg/x264 버전에서의 출력 동일성, 가변 프레임률·회전 메타데이터·복사할 수 없는 오디오 코덱, 코드에 적용된 CC BY 4.0의 세부 해석, 원본 코드의 `h264` 인코더 이름이 다른 빌드에서 하드웨어 인코더로 풀리는지, YouTube Studio에서 받은 파일이 플랫폼 처리본인지.
- **남은 일 (9번)**:
  - 최종 평가용 프로파일 고정(학습 시작 전), dev에 넣을 압축 조건 결정.
  - 모델 점수의 압축 민감도(docs/DESIGN.md §13.2 C1~C3), 원본과 압축본을 짝지은 점수 차이 지표. 데이터와 영상 단위 점수가 생긴 뒤.
  - 향후 경로: 저장소 소유자가 직접 찍은 영상을 본인 채널에 올려 YouTube Studio에서 받은 파일과 쌍으로 실제 파라미터를 추정(받은 파일이 처리본인지 확인 필요). **지금은 업로드하지 않는다.**
  - 오디오 재인코딩·프레임률·반복 인코딩·화질 지표.


## 백로그 10번: MotionPhys 기본·얼굴 영역·Face Motion (진행 중, 앞부분만)

특징 추출기와 데이터 없이 할 수 있는 검증까지다. 분류기를 학습하지 않았고 점수를 내지 않았다. 진위를 해석하지 않는다. 자세한 내용은 `docs/motionphys-spec.md`(정의), `docs/motionphys-spike.md`(측정).

- **재구현**: 공개 코드가 없어 논문(arXiv:2608.20770v1) 본문만 보고 만들었다. 식 (3)~(19)는 그대로, 논문에 없는 숫자(코너 수, 격자 간격, LK 설정, 처리 해상도, ε, 유효 궤적 기준 등)는 "우리 선택"으로 정해 문서에 구분해 적었다. 논문의 수치를 재현했다고 주장하지 않는다.
- **만든 파일**: `research/motionphys/{kinematics,tracking,faces,extract,train_lgbm}.py`, `research/motionphys/requirements.lock.txt`, `configs/motionphys_models.json`, `scripts/motionphys_compression_spike.py`, `tests/test_motionphys_{kinematics,extract,train}.py`.
- **환경**: `research/motionphys/.venv`(Python 3.11.18). opencv-contrib-python 5.0.0.93, numpy 2.4.6, lightgbm 4.7.0, mediapipe 1.2.3. torch 없음(설치 전후 확인). trinity 환경은 바꾸지 않았다.
- **세 후보** (같은 인터페이스: 영상 + 구간 → 특징 벡터, 유효 궤적 수, 상태): A 전체 화면 504차원, B 얼굴 영역 504차원, C Face Motion 1,512차원(머리·눈썹·입술). 움직임이 부족하면 `insufficient_motion`, 추적이 안 되면 `tracking_failed`, 특징은 `null`. 기준값은 임시값이다.
- **모델 파일**: Face Landmarker를 새로 받았다(`data/models/motionphys/face_landmarker.task`, Git 제외). 출처 URL과 sha256은 `configs/motionphys_models.json`과 `docs/motionphys-spec.md` §7. **모델 파일의 이용 조건은 확인 필요**(코드는 Apache 2.0, 안내 페이지는 CC BY 4.0까지만 확인. 모델 카드는 읽지 않았다).
- **압축 측정 결과** (본인 촬영 영상 1개, libx264 CRF 20/28/34, 10.4초 구간):
  - 같은 입력 두 번의 차이는 0.
  - 압축보다 표본 프레임의 위치가 특징을 더 크게 움직였다. jerk 특징 변화의 중앙값: CRF 34에서 A 2.8%, B 3.3%, C 8.5%. 압축 없이 표본을 한 프레임 민 대조군에서 A 6.4%, B 8.4%, C 9.5%.
  - jerk가 가장 민감하지는 않았다. 곡률 특징이 더 많이 움직였다.
  - 24프레임 스케일(클립 2개)은 불안정하다. A의 jerk 대표값이 CRF 34에서 −53%, 대조군에서 +71%.
  - C는 CRF 20에서도 곡률 특징이 17% 움직였다(입술 영역 대표값 +52% ~ +77%).
  - 유효 궤적 수와 추적 성공률은 압축에 거의 영향받지 않았다.
- **이 측정으로 말할 수 없는 것**: 압축이 진짜를 가짜로 판정하게 만드는지. 분류기와 가짜 영상이 없다. 프레임 간격이 0.22초라 짧은 구간(연속 프레임)에서는 결과가 다를 수 있다.
- **실행**:
  ```bash
  research/motionphys/.venv/bin/python -m pytest -q --noconftest tests/test_motionphys_kinematics.py tests/test_motionphys_extract.py tests/test_motionphys_train.py
  research/motionphys/.venv/bin/python scripts/motionphys_compression_spike.py --video data/research/samples/<허가 영상>.mp4
  ```
  환경과 모델 파일 준비는 `docs/motionphys-spec.md` §8. `--noconftest`는 motionphys 환경에 fastapi가 없어서 필요하다.
- **검증**: `research/motionphys/.venv`에서 49개 통과. conda `trinity`에서 전체 265개 통과, 1개 건너뜀(LightGBM이 없어 `tests/test_motionphys_train.py`).
- **미검증·확인 필요**: 논문에 없는 설정 전부(`docs/motionphys-spec.md` §9), 구간 길이에 따른 프레임 간격 차이의 영향, 짧은 구간·원본 해상도·다른 영상에서의 압축 민감도, 24프레임 스케일이 불안정한 원인, C의 불안정이 특징점 떨림 때문인지, MediaPipe 모델 파일의 이용 조건.
- **남은 일 (10번)**: DeepSpeak v2 승인 뒤 특징 추출 → `train_lgbm.py`로 학습 → 평가 파이프라인으로 A·B·C 비교(유효 궤적 비율, AUC, TPR@5%FPR, 추론 시간) → 축 유지/제거 결정. A+C, B+C 결합. 원본과 압축본의 점수 차이 측정(docs/DESIGN.md §13.2 C1~C5). 서버 어댑터와 Worker 연결.
- **의존성 메모**: 10번은 6번(Gate)·8번·9번에 의존한다. Gate 브랜치는 main에 없어서 얼굴 검출은 `research/motionphys` 안에서 MediaPipe를 직접 부른다. 압축은 9번의 `social_emulator`가 아니라 FFmpeg CRF만 썼다.


## 백로그 8번: 데이터 위생·고정 평가 파이프라인 (진행 중, 뼈대만)

실제 데이터 없이 합성 manifest와 합성 점수로 끝까지 도는 뼈대다. 성능 결과가 아니다. 자세한 내용은 `docs/evaluation-pipeline.md`.

- **만든 파일**: `training/datasets/{manifest,groups,mavos}.py`, `training/hygiene.py`, `training/evaluation/{metrics,thresholds,lock,run}.py`, `configs/external_eval_lock.json`, `tests/test_eval_pipeline.py`, `tests/test_mavos_external.py`. 표준 라이브러리만 쓴다(trinity에 새 의존성 없음).
- **공통 manifest**: 영상 경로, 라벨, 위조 유형, 생성기, 인물 ID, 원본 계보 ID, 데이터셋, 분할(`train`/`dev`/`test`/`external`) 등. 원본 계보 ID는 필수, 인물 ID는 선택(없으면 경고).
- **누수 검사**: 인물·원본 계보로 이은 그룹이 여러 분할에 걸치면 실패. 외부 세트와 내부 분할 사이의 원본·인물·해시 겹침을 따로 보고. 실패한 manifest로는 임계값도 평가도 거부한다. 경고 개수는 평가 리포트에 항상 싣는다.
- **지표**: ROC-AUC, dev 임계값을 적용한 TPR·실제 FPR, 생성기별(기본)·유형별(보조, 잠정), 보류율과 coverage, 그룹 단위 bootstrap 신뢰구간.
- **임계값**: dev에서만 정한다. 파일은 새로만 만들 수 있고 내용이 바뀌면 불러올 때 거부한다. `evaluate`는 임계값을 숫자로 받지 않는다.
- **외부 평가 잠금**: MAVOS-DD, TalkingHeadBench, Deepfake-Eval-2024를 `locked`로 등록했다. 풀려면 `configs/external_eval_lock.json`을 고쳐 커밋하고 `--final-external`을 줘야 한다. **아직 풀지 않는다.**
- **MAVOS-DD 메타데이터 검사 (추론 없음)**: 표본 목록 sha256이 잠금 값과 일치, 2,160개 모두 있고 크기 일치, 층 규칙 위반 없음. 경고: 인물 ID 없음 2,160, 원본 식별자 없음 448(21%), 파일 해시 없음 2,160. 공통 manifest는 `data/research/mavos-dd/common-manifest.csv`(Git 제외)에 썼다.
- **실행**:
  ```bash
  conda activate trinity
  pytest -q
  python -m training.hygiene <manifest.csv>
  python -m training.evaluation.run fit-threshold --manifest <m> --scores <s> --model-id <id> --out <threshold.json>
  python -m training.evaluation.run evaluate --manifest <m> --scores <s> --threshold <threshold.json> --split test --out <report.json>
  python -m training.datasets.mavos check
  ```
- **검증**: `pytest -q` 225개 통과(conda `trinity`, 건너뛴 테스트 없음). 실제 MAVOS-DD 표본 목록 검사 포함.
- **미검증·확인 필요**:
  - 실제 데이터로 실행한 적이 없다. 단일축 기초 평가 리포트는 없다(8번 완료 조건의 나머지).
  - MAVOS-DD와 학습 데이터 사이의 원본 겹침. 비교할 내부 데이터가 없다. 두 데이터셋의 원본 ID 체계가 달라도 같은 영상일 수 있는지.
  - 큰 데이터에서의 bootstrap 실행 시간.
- **남은 일**:
  - DeepSpeak v2 승인 뒤: 필드를 공통 manifest로 바꾸는 변환기, 그룹 분할, 누수 검사, WaveRep 단일축 평가 리포트.
  - 프레임 logit을 영상 점수로 집계하는 방법을 dev에서 정하기(지금 WaveRep 어댑터의 `raw_score`는 `null`).
  - docs/DESIGN.md §6.4의 나머지 점검(영상 유사도, 무음 편향, 코덱·해상도 shortcut), 압축 조건별 지표, 보정 지표.
  - 백로그 7번의 남은 일(Gate·Worker 연결)은 아래 절에 그대로 있다.


## 백로그 7번: WaveRep 어댑터 (어댑터만 구현함. Gate·Worker 미연결)

속도·재현성 확인이다. 성능 검증이 아니며 점수를 판정에 쓰지 않는다. 테스트 영상에는 발화가 없다. 자세한 수치는 `docs/waverep-adapter.md`.

- **만든 파일**: `server/axes/signal/waverep.py`(`run_waverep`, torch 없음), `research/waverep/infer_frames.py`(추론 프로세스), `research/waverep/frame_sampling.py`(프레임 선택), `scripts/bench_waverep_adapter.py`, `tests/test_waverep_adapter.py`. 원본 코드(`research/waverep/upstream/`)는 수정하지 않았다. trinity 환경에 torch를 넣지 않았다.
- **동작**: 영상과 `[(start, end), ...]` 구간을 받아 프레임별 원시 logit을 돌려준다. 샘플링(`sample_fps` 1·2·4 등, `None`이면 모든 프레임)과 배치(`batch_size`)를 지원한다. `research/waverep/.venv`의 Python을 인자 리스트로 실행하고 결과를 JSON으로 받는다. 실패는 `status=error`와 점수 `null`로 돌려준다. `raw_score`는 `null`(집계 방법 미정), `overall_score`는 다루지 않는다.
- **벤치마크**: 2026-11-12에 CPU 3건을 잰 뒤 배터리 부족으로 중단했고, 2026-11-13에 전원을 연결하고 `--force` 없이 재개해 남은 11건을 끝냈다(저장된 3건은 건너뜀). 14건 모두 `completed`.
- **결과** (본인 촬영 영상 1개, 1080p 313프레임, 10.43초):
  - 어댑터 점수는 스파이크 `cpu-1`과 완전히 같다(최대 절대차 0.0).
  - `pretrained=False`와 `True`의 점수가 완전히 같다(0.0). 빈 HF 캐시 + `HF_HUB_OFFLINE=1`에서 `False`는 동작, `True`는 실패. **기본값을 `pretrained=False`로 했다.**
  - 반복 실행은 완전히 같다(CPU 배치 8, MPS 배치 8). 배치 1 대 8은 CPU 최대 0.000037, MPS 최대 0.00000095. CPU 대 MPS는 최대 0.00019.
  - 샘플링한 프레임의 점수는 모든 프레임 실행의 같은 프레임과 같다(CPU 초당 4장에서만 최대 0.0000062).
  - MPS 모든 프레임: 배치 1이 56.5초(6.2장/초, 드라이버 할당 0.70 GiB, peak footprint 1.10 GiB), 배치 8·16이 86~90초(3.8~4.0장/초, 드라이버 1.70 GiB, footprint 약 2.3 GiB). **기본 배치 크기를 1로 했다**(배치 1은 1회 측정).
  - MPS 샘플링(배치 8) 전체 시간: 초당 1장 8.8초(11프레임), 2장 12.5초(21), 4장 18.0초(42). CPU는 9.0초, 14.7초, 28.6초.
  - CPU 모든 프레임 배치 8(전원 연결): 126.6초, 최대 RSS 1.63 GiB.
- **주의할 점**:
  - 2026-11-12의 CPU 3건(`cpu-all-b1-pretrained` 305.6초, `cpu-all-b1` 223.6초, `cpu-all-b8` 388.8초)은 배터리 부족 상태의 값이다. 같은 설정의 재실행이 126.6초였다. 이 3건의 시간은 다른 실행과 비교하지 않는다(점수 비교에는 썼다). 전원 연결 상태의 CPU 배치 1 시간은 없다. 다시 재려면 `--only cpu-all-b1 --force`.
  - 샘플링 설정에 따라 평균 logit이 -0.67 ~ -1.67로 달라진다. 고른 프레임이 달라서다. 샘플링 간격과 집계 방법은 영상 하나로 정하지 않는다(백로그 8번 이후).
- **실행**:
  ```bash
  conda activate trinity
  pytest -q
  python scripts/bench_waverep_adapter.py --video data/research/samples/<허가 영상>.mp4   # 결과가 있는 실행은 건너뛴다
  ```
  출력은 `data/research/waverep-adapter/`(Git 제외).
- **검증**: `pytest -q` 124개 통과(conda `trinity`, 2026-11-13, 실제 CPU 추론 1건 포함).
- **미검증·확인 필요**: MPS에서 배치 8·16이 배치 1보다 느린 원인, 전원 상태가 CPU 시간에 준 영향, 가변 프레임률 영상의 프레임 시각, 504px 미만 영상의 `unsupported_input` 경로(실제 영상으로 실행 안 함), 발화가 있는 영상·합성 영상에서의 실행.
- **7번에서 남은 일**: Gate 연결(Gate 브랜치 `feat/gate-speech-segments`는 알려진 문제로 main에 합치지 않은 상태), Worker의 `waverep` 단계에 연결, 추론 중 주기적 heartbeat(어댑터는 지금 끝날 때까지 막는다), `analyzed_*` coverage 채우기, stub 값(`stub_not_executed`) 제거, 프레임 logit을 `raw_score`로 집계하는 방법 결정.

## 데이터셋 접근 상태 갱신 (2026-11-13, 저장소 소유자 확인)

- **DeepSpeak v2**: 심사 대기.
- **Deepfake-Eval-2024**: 접근 요청이 **거절됐다.** 거절 사유·통보 날짜·재신청 가능 여부는 확인 필요.
- `docs/dataset-access.md`, docs/DESIGN.md §6.1 표, §14.1 백로그 3번 행에 반영했다.
- 대체 방안은 아래 "결정 6 변경"에서 정했다.

## 결정 6 변경: 최종 외부 평가 자료 (2026-11-13, 브랜치 `docs/decision-6-external-eval`)

설계 문서(지금 `docs/DESIGN.md`) 문구와 접근 기록을 바꾸고, MAVOS-DD 표본 목록을 만드는 스크립트를 추가했다. 서버 코드는 바꾸지 않았다.

- **결정**: 최종 외부 평가를 MAVOS-DD open-set model 분할과 TalkingHeadBench로 대체한다. Deepfake-Eval-2024는 재신청을 검토하고 승인되면 실전 유통본 평가로 추가한다. 실제 SNS 유통본으로 평가하지 못하면 결과 보고에 한계를 명시한다.
- **바꾼 곳**: docs/DESIGN.md §6.1(역할 표, 우선 접근 원칙), §6.3, §6.5, §13.1, §14.1 3번 행, §15.3 결정 6, §16, `AGENTS.md`의 최종 평가 전용 줄, `docs/dataset-access.md`(MAVOS-DD 절 추가).
- **MAVOS-DD 확인한 것**: CC BY-NC-SA 4.0, 자동 승인 방식 접근 제한, 전체 약 308.4 GB(mp4 87,038개), 폴더(언어·생성기) 단위로 일부만 받을 수 있는 구조. 폴더별 파일 수·용량 표를 `docs/dataset-access.md`에 넣었다(전체 기준, 분할 구분 없음).
- **표본 추출 규칙**: 구조(층화, 고정 시드, 진짜·가짜 비율, 생성기당 상한, 교체 금지)를 `docs/dataset-access.md`에 먼저 고정했다. 숫자는 미정이다.
- **MAVOS-DD 메타데이터 (2026-11-13)**: 접근이 승인돼 메타데이터만 받았다(`data/research/mavos-dd/`, 영상 없음). open-set model 분할은 43,959개, 155.3 GB(진짜 15,547, 가짜 28,412). 생성기별·언어별 표와 원본 영상 묶음 추정을 `docs/dataset-access.md`에 넣었다.
- **표본 규칙 고정 (2026-11-13, 저장소 소유자 승인)**: 층당 20개(생성기당 120), 원본 묶음당 2개, 진짜:가짜 1:1, 시드 20261113. 표본 2,160개, 6.77 GB. `manifest-q20.csv`의 sha256과 확장용 `manifest-q25.csv`(8.45 GB, q20을 포함)의 sha256을 `docs/dataset-access.md`에 적었다. 만든 파일: `scripts/mavos_sample.py`, `research/mavos/export_metadata.py`, `research/mavos/download_sample.py`, `research/mavos/requirements.lock.txt`, `tests/test_mavos_sample.py`.
- **표본 수신 (2026-11-13)**: 규칙 커밋(`dee503f`) 뒤에 2,160개를 받았다. 6,766,772,622바이트로 목록과 일치. 받은 뒤 디스크 여유는 약 50.5 GiB(`df` 기준, 받기 전 59 GiB). 표본은 모델에 넣지 않았다. 모델과 임계값을 고정하기 전에는 이 표본으로 추론 결과를 보지 않는다.
- **남은 일**: DeepSpeak v2 승인 뒤 생성기가 MAVOS-DD와 겹치는지 확인, TalkingHeadBench 접근 절차 확인, Deepfake-Eval-2024 재신청 검토. PR #3은 main에 합쳤다.
- **정정**: 지난 갱신에서 `docs/dataset-access.md`의 TalkingHeadBench "확인 필요" 표에 잘못 넣은 Deepfake-Eval-2024 거절 관련 두 줄을 Deepfake-Eval-2024 절로 옮겼다.
- **검증**: `pytest -q` 124개 통과(conda `trinity`). 문서 변경이라 새 테스트는 없다.

## 백로그 6번: 최소 발화 구간 Gate (구현함, 알려진 문제 있음, main에 합치지 않음)

**알려진 문제 (2026-11-12, 저장소 소유자 확인):**

- 샘플 영상은 실제로 발화가 없다(야외, 주변 소음). 그런데 VAD가 대부분을 음성으로 판정했다.
- 단일 발화 테스트의 기대값이 틀렸을 수 있다(`tests/test_gate_media.py::test_single_speaker_video_has_eligible_segment`).
- 입 움직임 확인 추가와 VAD 비교가 필요하다.
- 발화가 있는 영상은 아직 없다.
- Gate 수정은 미뤘다. 코드는 고치지 않았다. **이 브랜치(`feat/gate-speech-segments`)는 `main`에 합치지 않는다.**
- 아래의 "원본 `null`(적합 구간 0~10.433초)"과 docs/DESIGN.md §14.1 6번 행의 "단일 발화 ... 확인"은 이 문제의 영향을 받는다. 그대로 믿지 않는다.
- `docs/waverep-spike.md`의 입력 설명을 "본인 얼굴, 주변 소리, 발화 없음"으로 정정했다. `docs/media-access.md` §3의 "본인 얼굴과 본인 음성만"은 허가 미디어의 범위 규칙이라 고치지 않았다. 현재 샘플에 본인 음성(발화)이 없다는 점은 거기에 적혀 있지 않다.

허가 미디어 파일 하나를 받아 적합 발화 구간과 원인 코드를 돌려주는 `server/gate` 모듈이다. 모델 추론은 하지 않는다. Worker에는 연결하지 않았다. 자세한 내용은 `docs/gate.md`.

- **구성**: `probe.py`(ffprobe), `vad.py`(FFmpeg PCM 파이프 + `webrtcvad`), `faces.py`(MediaPipe Face Detector), `segments.py`(추적과 규칙, 순수 함수), `types.py`(자료형·원인 코드·임시 임계값). 진입점은 `server.gate.run_gate(media_path)`.
- **규칙**: 음성 구간 동안 주된 얼굴이 정확히 하나일 때만 적합 구간이다. 둘 이상이면 `speaker_unconfirmed`.
- **원인 코드**: `media_unreadable`, `audio_missing`, `no_speech_detected`, `no_face_detected`, `speaker_unconfirmed`, `low_resolution`, `face_too_small`, `too_blurry`, `segment_too_short`. docs/DESIGN.md §10에 추가했다.
- **coverage**: `video_duration_sec`와 `eligible_duration_sec`만 채운다. `analyzed_*`와 비율은 `null`(백로그 7번에서 채운다).
- **의존성**: `requirements-gate.txt`(버전 고정)를 conda `trinity`에 설치했다. `mediapipe` 1.2.3, `webrtcvad-wheels` 2.0.14.post1, `opencv-contrib-python` 5.0.0.93, `numpy` 2.4.6 등. **torch는 없다**(설치 전 dry-run과 설치 후 모두 확인). 먼저 `research/gate/.venv`에서 스모크했고 lockfile은 `research/gate/requirements.lock.txt`.
- **모델 파일**: `data/models/gate/blaze_face_short_range.tflite`(Git 제외). sha256은 `configs/gate_models.json`. 해시가 다르면 실행을 거부한다.
- **실행**:
  ```bash
  conda activate trinity
  pip install -r requirements-gate.txt
  python scripts/run_gate.py data/research/samples/<허가 영상>.mp4
  pytest -q
  ```
  모델 파일을 받는 방법은 `docs/gate.md` "재현 방법".
- **검증**: `pytest -q` 96개 통과(conda `trinity`, 건너뛴 테스트 없음). 실제 영상 4종의 대표 원인 코드: 원본 `null`(적합 구간 0~10.433초), 오디오 제거본 `audio_missing`, 검은 화면본 `no_face_detected`, 무음 오디오본 `no_speech_detected`. 변형은 테스트 중 임시 폴더에 만들고 끝나면 지운다.
- **미검증·확인 필요**:
  - 여러 명이 말하는 영상(동의받은 영상 없음). `speaker_unconfirmed`는 합성 표본을 넣은 규칙 단위 테스트로만 확인했다.
  - 임계값 전부(임시값). 품질 원인 코드는 실제 저품질 영상으로 실행하지 않았다.
  - 화면 밖 발화자는 구분하지 못한다(보이는 얼굴이 말한다고 가정).
  - VAD가 샘플 전체를 한 음성 구간으로 묶었다. 실제 발화와 맞는지 사람이 대조하지 않았다. `webrtcvad`의 정확도는 비교하지 않았다.
  - MediaPipe 얼굴 검출 모델 파일의 이용 조건, 세로(회전) 영상에서의 프레임 방향.
- **백로그 7번에서 할 일**: Gate를 Worker의 `preprocessing` 단계에 연결, 원인 코드를 `analysis_status`에 대응, `analyzed_*` coverage 채우기, Gate 실행 중 heartbeat, 서버가 발급한 작업 경로만 넘기기.

## 백로그 1·3번: 접근 기록 문서화 (둘 다 진행 중)

문서만 만들었다. 코드는 바꾸지 않았다.

- **`docs/media-access.md` (백로그 1번)**: 영상 ID·메타데이터 접근과 분석용 미디어 접근의 차이(docs/DESIGN.md §3.1 기준), 임의 YouTube URL은 `analysis_unavailable`로 처리한다는 결정, 허가 미디어 범위(저장소 소유자가 직접 촬영한 본인 영상, 본인 얼굴·음성만, 제3자 없음), 압축 실험에는 휴대폰 원본을 쓴다는 메모.
- **`docs/dataset-access.md` (백로그 3번)**: (2026-11-12 기준. 최신 상태는 위 "데이터셋 접근 상태 갱신") DeepSpeak v2와 Deepfake-Eval-2024는 접근 요청 후 승인 대기, TalkingHeadBench는 접근 방법 확인 필요. 데이터셋별 역할, 확인된 이용 조건, 확인 필요 항목을 나눠 적었다. Hugging Face 공개 API 메타데이터(접근 제한 여부, 라이선스 태그, Deepfake-Eval-2024 이용 조건 문구)를 2026-11-12에 조회해 근거로 썼다. 데이터셋 파일은 받지 않았다.
- **설계 문서(지금 `docs/DESIGN.md`)**: §14.1 백로그 1·3번 행에 상태를 적었다. §6.1 표의 DeepSpeak v2·Deepfake-Eval-2024 상태 칸을 "접근 요청함, 승인 대기"로 바꿨다.
- **검증**: `pytest -q` 72개 통과(conda `trinity`). 문서 변경이라 새 테스트는 없다.
- **확인 필요로 남긴 것**:
  - 두 데이터셋의 신청 날짜(저장소 소유자가 알려 주면 반영), 승인 결과.
  - DeepSpeak v2 라이선스 문서 본문(링크만 확인), TalkingHeadBench의 실제 접근 절차·분할·상위 영상 권리.
  - 본인 채널 영상을 YouTube Studio에서 받을 수 있는지, 받은 파일이 플랫폼 처리본인지.
  - 현재 샘플(`KakaoTalk_Video_…`)의 재압축 여부. 압축 실험(백로그 9번)에는 휴대폰 원본을 새로 옮겨 쓴다.
- **백로그 1번에서 남은 것**: YouTube ID와 연결된 시연용 허가 미디어 등록. 레지스트리에는 여전히 가짜 ID `TRINITYtest`만 있다.
- **백로그 3번에서 남은 것**: 최소 테스트 샘플, 공통 manifest/분할 규칙. 8번은 3번이 끝나야 시작할 수 있다.

## 백로그 5번: WaveRep 단독 추론 스파이크 (완료)

실행 가능성 확인이다. 성능 검증이 아니며, 점수를 진위로 해석하지 않는다. 자세한 수치는 `docs/waverep-spike.md`.

- **환경**: `research/waverep/.venv`(Python 3.11.18), torch 2.15.0 · timm 1.0.31 · opencv-python 5.0.0.93. 버전은 `research/waverep/requirements.lock.txt`에 고정.
- **원본 코드·가중치**: `research/waverep/upstream/`에 clone(커밋 `0fd6010`, 수정하지 않음, Git 제외). `weights_dinov2_G4.ckpt`는 md5가 공개값과 일치.
- **결과** (본인 촬영 영상 1개, 1080p 313프레임): CPU 성공(142초·190초, 최대 RSS 약 1.0 GiB), MPS 성공(122초, peak footprint 1.31 GiB). CPU 2회 점수 완전 일치, CPU↔MPS 프레임 점수 최대 차 0.00019. CUDA 전용 연산과 MPS fallback 경고 없음.
- **가중치 키 대조**: missing 0, unexpected 0, 모양 불일치 0 (177개 키).
- **이용 조건**: `docs/waverep-license.md`. GRIP-UNINA 자체 라이선스로 비영리·정보 목적만 허용, 원 고지 유지, 결과 공개 시 인용.
- **만든 파일**: `research/waverep/run_spike.py`(데모를 서브프로세스로 실행하고 시간·메모리·점수 요약 기록), `research/waverep/check_state_dict.py`(키 대조), `tests/test_waverep_spike.py`. `.gitignore`에 `research/*/upstream/` 추가.
- **실행**:
  ```bash
  research/waverep/.venv/bin/python research/waverep/check_state_dict.py
  research/waverep/.venv/bin/python research/waverep/run_spike.py --video data/research/samples/<파일>.mp4 --device cpu --tag cpu-1
  research/waverep/.venv/bin/python research/waverep/run_spike.py --video data/research/samples/<파일>.mp4 --device mps --tag mps-1
  ```
  환경을 새로 만드는 방법은 `docs/waverep-spike.md` "재현 방법". 출력은 `data/research/waverep-spike/`(Git 제외).
- **검증**: `pytest -q` 72개 통과(conda `trinity`). 추론 4회(cpu-smoke, cpu-1, cpu-2, mps-1) 모두 종료 코드 0.
- **확인 필요로 남긴 것**:
  - 가중치 전용 이용 조건(저장소에 명시 없음), timm DINOv2 기반 가중치와 PyPI 의존성의 라이선스.
  - MPS 최대 메모리: `/usr/bin/time -l` 값이 GPU 할당 전부를 포함하는지 미확인. 백로그 7번 어댑터에서 `torch.mps.driver_allocated_memory()`로 측정.
  - MPS가 CPU보다 크게 빠르지 않은 원인, CPU 2회 실행 시간 차이의 원인(각 1회 측정).
  - 원본 전처리는 가운데 504×504 crop뿐이다. 세로 영상·저해상도 입력에서의 동작은 실행하지 않았다.
  - 원본 데모는 `pretrained=True`라 첫 실행 때 Hugging Face Hub에서 346MB를 받는다. 오프라인 서비스 실행을 위해 어댑터에서 `pretrained=False`로 바꿔도 결과가 같은지.
- **백로그 의존성 메모**: 5번은 원래 3번(데이터셋 접근)에 의존한다. 이번에는 데이터셋 대신 본인 촬영 영상 1개로 실행 가능성만 확인했다.

## 백로그 2번: 환경 스모크 점검 (완료)

- `scripts/check_env.py`를 만들었다. Python·아키텍처·Rosetta, ffmpeg/ffprobe/libx264, PyTorch CPU/MPS(실제 행렬곱), OpenCV, LightGBM을 점검한다. 아무것도 설치하지 않는다. 없으면 `없음`, 있지만 동작하지 않으면 `실패`.
- 실행: `conda activate trinity && python scripts/check_env.py`. 다른 환경은 그 환경의 Python과 `--output`으로 따로 기록한다. 테스트는 `tests/test_check_env.py`.
- conda `trinity`(서버 환경) 결과는 `docs/env-check.md`: Python 3.11.18 / arm64 / ffmpeg·ffprobe 8.0.1 / libx264 정상. PyTorch·OpenCV·LightGBM은 이 환경에 없다(의도한 상태).
- `research/waverep/.venv` 결과는 `docs/env-check-waverep.md`: PyTorch 2.15.0, **CPU·MPS 행렬곱 스모크 정상**, OpenCV 5.0.0 정상. LightGBM은 없음(WaveRep 환경의 설치 대상이 아니다. MotionPhys 환경을 만들 때 확인한다).
- "저장소/가중치 이용 조건 점검"은 WaveRep에 대해서만 했다(`docs/waverep-license.md`). MotionPhys·SyncNet·`social_emulator`는 각 스파이크에서 점검한다.

## 한 일 (백로그 4번)

백로그 4번, URL-only 최소 수직 슬라이스를 만들었다. 모델과 다운로드는 stub이다.

- **API** (`server/api/`): `POST /api/v1/analyses`(202), `GET /api/v1/analyses/{id}`, `GET /api/v1/analyses/{id}/result`, `GET /api/v1/health`. 핸들러는 큐에 넣고 읽기만 한다.
- **URL 검사** (`server/ingest/youtube_url.py`): 정규화, 허용 호스트(`youtube.com`, `www.`, `m.`, `youtu.be`), 11자 video ID 추출. 네트워크 요청 없음. IP·포트·사용자 정보·다른 호스트는 거부한다.
- **AuthorizedMediaRegistry** (`server/ingest/media_resolver.py`): `configs/authorized_media.json`에 등록된 ID만 허가한다. 파일이 없으면 모든 ID가 미허가다.
- **SQLite 큐** (`server/jobs/queue.py`): `BEGIN IMMEDIATE` 원자적 선점, 동시 1건, 대기 3건 초과 시 429, lease와 단계 경계 heartbeat, 만료 lease 복구, 재시도 상한(기본 2회), 취소, lease 소유자 불일치 쓰기 거부.
- **Worker** (`server/jobs/worker.py`): 별도 프로세스. 단계명만 기록하고, 한 축이 예외를 내도 나머지 축을 계속한다. 타임아웃과 취소는 단계 경계에서 확인한다. 임시 작업 폴더는 끝나면 지운다.
- **작업 소유권**: `X-Client-Token` 헤더의 해시를 작업에 저장한다. 토큰이 다르면 404, 없으면 401.
- **그 외**: `requirements.txt`(버전 고정), `.gitignore`, `pytest.ini`, `scripts/smoke_slice.py`, 설계 문서(지금 `docs/DESIGN.md`) 하단 실행 방법, CLAUDE.md "명령" 절.

## 검증 결과

- `pytest -q`: 52개 통과 (Python 3.11.18, conda 환경 `trinity`). 종단 간 테스트는 worker를 실제 별도 프로세스로 띄운다.
- 실제 서버(uvicorn)와 worker를 띄우고 `scripts/smoke_slice.py`로 확인했다.
  - 등록 ID: `queued → validating → … → finalizing → finished`, `analysis_status=partial`, `verdict_status=abstained`, `overall_score=null`, `abstention_reason=no_valid_fusion_model`.
  - 미등록 ID: `analysis_unavailable`, `reason_code=access_not_authorized`, 모든 축 점수 `null`.
  - 잘못된 URL 422, 없는 작업 404.

## 실행 방법

```bash
conda activate trinity                # 없으면: conda create -n trinity python=3.11 -y && pip install -r requirements.txt
pip install -r requirements-gate.txt  # Gate용(선택). torch 없음
pytest -q
uvicorn server.main:app --reload      # 터미널 1
python -m server.jobs.worker          # 터미널 2
python scripts/smoke_slice.py         # 터미널 3
```

## 남은 일

- 백로그 1·3번은 기록을 만들었고 둘 다 진행 중이다(`docs/media-access.md`, `docs/dataset-access.md`). 4번은 원래 1번에, 5번은 3번에 의존한다.
- 다음 순서: 6번 Gate의 알려진 문제(발화 없는 영상을 음성으로 판정)를 먼저 해결할지 정한다. 발화가 있는 허가 영상이 필요하다. 그 전에는 7번에서 Gate를 Worker에 연결하지 않는다. 1·3번의 확인 필요 항목은 병렬로 처리한다. 데이터셋 승인은 기다려야 한다.
- 백로그 14번으로 미룬 것: `DELETE /api/v1/analyses/{id}` 엔드포인트(큐의 `request_cancel`은 이미 있음), 정식 인증, rate limit, 비정상 종료 잔여 파일 24시간 정리.
- 실제 모델을 연결하면(백로그 7번) heartbeat를 단계 경계가 아니라 주기적으로 보내야 한다. 지금은 stub이 즉시 끝나서 단계 경계 heartbeat로 충분하다.

## 백로그 7번에서 제거할 임시 값

- **stub 축의 `status`**: 등록 ID의 세 축은 `status=insufficient_input`, `reason_code=stub_not_executed`, `model_version=stub`으로 답한다. §10의 축 상태에 "실행하지 않음"이 없어서 쓴 임시 값이다. 실제 WaveRep를 Worker에 연결할 때(백로그 7번) `stub_not_executed`와 `model_version=stub`을 제거한다. 위치: `server/axes/{signal,physics,alignment}/__init__.py`.

## 결정한 것 (2026-11-12)

- **미완료 작업의 `/result`**: `queued`·`processing`이면 HTTP 202와 함께 `job_status`·`stage`만 돌려준다. 실패·취소 작업은 200으로 `job_status`와 `reason_code`만 채운다. docs/DESIGN.md §9에 반영했다.
- **작업 실패 원인 코드**: `timeout`, `worker_error`, `max_attempts_exceeded`를 docs/DESIGN.md §10에 추가했다.
- **백로그 7번 완료 조건**: "추론 중 주기적 heartbeat로 lease 연장"을 docs/DESIGN.md §14.1에 추가했다.
- **docs/DESIGN.md §9 문구**: "미구현 명세"를 "백로그 4번 기준 stub으로 구현됨"으로 바꿨다.

## 막힌 점·확인이 필요한 것

- **테스트 경고**: `starlette.testclient`가 `httpx` 대신 `httpx2`를 쓰라는 경고를 낸다. 테스트는 통과한다. 교체 여부는 확인 필요.
- **허가 미디어**: 레지스트리에는 가짜 ID `TRINITYtest`만 있다. 권한 근거는 `docs/media-access.md`에 기록했다. 실제 ID는 본인 채널 업로드 여부와 YouTube Studio 관련 미확인 사항을 정한 뒤에 넣는다.
