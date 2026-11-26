# 연구용 다운로드 어댑터 설계 계획 — **승인 대기, 코드 변경 없음**

> 사용자 결정(2026-11-26): 입력은 제품 절대 규칙 1번을 따른다. 졸업작품 시연·연구 전용(비상업, 공개 배포 없음)으로, 서버가 링크의 영상을 내려받아 분석한다.
> 기존 "yt-dlp 등 임의 URL 다운로드 금지" 규칙은 이 연구용 경로에 한해서만 대체한다.
> 이 경로는 **YouTube 약관에 어긋날 수 있다.** 이 위험을 기록하고 아래 조건으로 범위를 좁힌다.

## 1. 결정 기록 문안

### DESIGN §15.3 (제안)

> **결정 1 변경(연구용 다운로드 어댑터) — 2026-11-2x, Claude 제안, 사용자 승인 대기.**
> 졸업작품 시연·연구 전용(비상업, 공개 배포 없음)으로 다음을 허용한다. Worker가 사용자 YouTube 링크의 영상을 연구용 다운로드 어댑터(`server/ingest/research_download.py`, 기존 `ApprovedPlatformAccessAdapter` 자리)로 내려받아 분석한다.
> 이 경로는 YouTube 서비스 약관에 어긋날 수 있다. 그 위험을 알고 아래 조건으로 한정한다.
> - **실행 위치:** Worker 안에서만 실행한다. 별도 venv의 yt-dlp를 서브프로세스(인자 리스트)로 부른다.
> - **입력:** 사용자 문자열은 넘기지 않는다. 서버가 검증한 video ID로 만든 정규 URL만 넘긴다.
> - **하지 않는 것:** 브라우저 쿠키, YouTube 로그인, 권한·연령 제한 우회는 쓰지 않는다. 로그인을 요구하면 실패로 끝낸다.
> - **켜고 끄기:** 기본은 꺼짐이다. `TRINITY_RESEARCH_DOWNLOAD=1`일 때만 켜진다.
> - **등록부 우선:** `AuthorizedMediaRegistry`에 등록된 ID는 다운로드하지 않고, 등록된 로컬 파일을 먼저 쓴다(예비 경로).
> - **삭제:** 받은 영상은 작업 폴더에만 둔다. 분석이 끝나거나 실패하거나 취소되면 지운다.
> - **학습 제외:** 학습 데이터에 넣지 않는다(기존 규칙).
> - **금지 범위:** API 핸들러, 학습·평가 스크립트, 그 밖의 모듈에서 임의 URL을 내려받는 것은 여전히 금지한다.
> - **영향받는 기존 기록:** §1 최상위 원칙의 "권한이 없으면 Unavailable", §2 표의 "임의 URL 다운로더" 범위 밖 행, §8, `docs/media-access.md`. 이번 변경은 이 경로에 한해 이 기록들을 대체한다.
> - **API 계약 변경:** 새 원인 코드가 생긴다(아래 §6).

### AGENTS.md "절대 규칙: 입력과 미디어" 수정안

| 지금 | 바꾼 뒤 |
|---|---|
| 분석할 미디어는 `AuthorizedMediaRegistry`에 등록된 허가 미디어만 쓴다. 없으면 `analysis_unavailable`로 끝내고 보류 원인을 남긴다. | 분석할 미디어는 `AuthorizedMediaRegistry`(먼저 확인)나 연구용 다운로드 어댑터로만 확보한다. 둘 다 안 되면 `analysis_unavailable`로 끝내고 원인 코드를 남긴다. |
| 임의 URL을 yt-dlp 등으로 내려받는 코드를 만들지 않는다. 권한 문제를 우회하는 구현은 하지 않는다. | yt-dlp는 연구용 다운로드 어댑터(`server/ingest/research_download.py`) 안에서만 쓴다. Worker에서, 서버가 video ID로 다시 만든 정규 URL로만 실행한다. 그 밖의 곳에서는 여전히 금지한다. 쿠키·로그인·권한 우회는 하지 않는다. 졸업작품 시연·연구(비상업, 공개 배포 없음) 전용이며, YouTube 약관에 어긋날 수 있음을 기록해 둔다. |

그대로 두는 규칙: URL은 정규화·허용 호스트·ID 추출만 한다. 내부망·리디렉션·로컬 경로는 받지 않는다. 사용자 요청 영상은 학습에서 뺀다. 임시 파일은 삭제한다.

## 2. 구조

```
API: URL → parse_youtube_url → video_id 저장(지금과 같음)
Worker access_check 단계:
  1) registry.resolve(video_id)에 local_path가 있으면 → 작업 폴더로 복사(지금과 같음)
  2) 없고 TRINITY_RESEARCH_DOWNLOAD=1이면 → ResearchDownloadAdapter.fetch(video_id, job_dir, limits, on_tick)
       → (media_path, info) 또는 실패 원인 코드
  3) 둘 다 안 되면 → 지금처럼 access_not_authorized / video_access_unavailable
이후 Gate → 세 축은 지금과 같다
```

- **진행 단계 이름:** 다운로드는 기존 `access_check` 단계 안에서 한다. 새 단계 값을 만들면 API 계약이 바뀌기 때문이다. 앱에는 이 단계가 "영상 확인"으로 보인다. 별도 단계 `downloading`을 원하면 그때 계약 변경 문안을 따로 쓴다.
- **시간 제한:** 다운로드 시간은 Gate 전 작업 제한(`job_timeout_seconds` 600초)에 포함된다. 다운로드 자체의 상한은 `TRINITY_DOWNLOAD_TIMEOUT_SECONDS`(제안 180초)다.
- **취소:** heartbeat·취소·lease 상실 때는 기존 `start_process`/`stop_process`로 프로세스 그룹을 종료한다(Gate와 같은 방식).
- **설정:** venv 경로와 Deno 경로는 Settings에서 읽는다. 사용자 입력이 아니다.

## 3. 링크 형식

현재 `server/ingest/youtube_url.py`로 시험한 결과(2026-11-26):

| 형식 | 지금 | 조치 |
|---|---|---|
| `https://www.youtube.com/watch?v=ID`, `&t=42s`, `app=desktop&v=ID` | 받음 | — |
| `https://m.youtube.com/watch?v=ID&feature=share` | 받음 | — |
| `https://youtu.be/ID`, `?si=…`, `?t=10` | 받음 | — |
| `https://www.youtube.com/shorts/ID`, `?si=…`, 끝 `/`, `m.youtube.com/shorts/ID` | 받음 | — |
| `https://www.youtube.com/live/ID?si=…` | 받음 | 다운로드 단계에서 생방송이면 거부(§4) |
| 앞뒤 공백·줄바꿈 | 받음(strip) | — |
| **앞뒤 글자 포함**("영상 봐 https://youtu.be/ID?si=…", 링크 뒤 설명) | 거부(`forbidden_characters`) | 수정. 문자열에서 공백으로 나눈 토큰 중 허용 호스트 URL을 **하나만** 고른다. 두 개 이상이면 거부(어느 영상인지 모호) |
| **`https://` 없음**(`youtu.be/ID`, `www.youtube.com/watch?v=ID`) | 거부(`bad_scheme`) | 수정. 스킴이 없고 호스트가 허용 목록이면 `https://`를 붙인다 |
| `music.youtube.com`, `youtube-nocookie.com` | 거부 | 그대로 거부(범위 밖) |
| YouTube 아닌 주소, IP | 거부 | 그대로 거부 |

- 추적 인자(`si`, `feature`, `t` 등)는 지금처럼 버린다. 저장·전달하는 것은 video ID뿐이다.
- 수정은 함수 앞단 "텍스트에서 링크 하나 고르기" 한 곳뿐이다. 호스트·ID 검사는 그대로 둔다.
- 링크 길이 제한(2048)은 고른 토큰에 적용한다. 원문 전체에는 8KB 상한을 둔다.

## 4. 다운로드

**설치·고정**
- 공식 문서를 2026-11-26에 확인했다(yt-dlp wiki EJS, README, 최신 릴리스 `2026.11.23`).
  - YouTube에서는 외부 JS 런타임과 `yt-dlp-ejs`가 필요하다.
  - Deno는 권장 런타임이고 기본으로 켜져 있다. 최소 버전은 2.3.0이다.
  - Python 3.11 이상을 지원한다.
- 별도 venv: `research/download/.venv`(Git 제외)
  - `pip install "yt-dlp[default]==<구현 시점 버전>"`. default 묶음에 `yt-dlp-ejs`가 들어 있다.
  - `requirements.lock.txt`를 해시 포함으로 커밋한다.
  - `yt-dlp-ejs` 버전은 yt-dlp의 `pyproject.toml`과 같아야 한다.
- Deno: `brew install deno`. 버전을 lock 문서에 기록하고, 2.3.0 미만이면 실행 전에 거부한다.
  - 경로는 `--js-runtimes deno:<절대 경로>`로 명시한다. PATH에 의존하지 않는다.
  - `--remote-components`(GitHub/npm에서 스크립트를 받는 기능)는 쓰지 않는다.
- **구현 시점에 공식 문서를 다시 확인한다.** YouTube 쪽 변경으로 요구사항이 자주 바뀐다.

**실행 인자(초안, 인자 리스트)**
```
<venv>/bin/yt-dlp --ignore-config --no-cookies-from-browser --no-cache-dir --no-playlist
  --js-runtimes deno:<abs> --no-progress --socket-timeout 30 --retries 2
  --match-filter "!is_live & duration <= {L}"     # 방식 (i)일 때
  -S "res:1080" -f "bv*+ba/b" --merge-output-format mkv
  --max-filesize {SIZE} -o "{job_dir}/download.%(ext)s" -- "https://www.youtube.com/watch?v={id}"
```
- 화질: `-S res:1080`으로 해상도 1080 이하 가운데 가장 높은 것을 고른다(yt-dlp의 res는 짧은 변 기준). 짧은 변 504px 이상이 있으면 그것이 선택된다. 없으면 받을 수 있는 최고 화질을 받고, 기존 `low_resolution` 처리에 맡긴다. 반드시 오디오를 포함한다(영상만 있는 결과는 `no_suitable_format`). 정확한 정렬·필터 문법은 구현 시 문서로 확인한다.
- 받은 뒤 `probe.probe`로 길이·해상도·오디오를 다시 확인한다. yt-dlp 메타데이터를 믿지 않는다.
- stdout·stderr는 메모리에서 원인 분류에만 쓴다. 저장하거나 로그에 남기지 않는다.

**길이·크기·제한시간: 두 안 (사용자가 고른다)**

실측 처리 시간(이 기기, MPS):
- 본인 A(41초, 1080p, 적합 37초): Worker 전체 219~240초. 영상 1초당 약 5.3~5.9초
- Seamless 전처리본(25초, 1080×1920, 적합 16.3초): 114.8초. 영상 1초당 약 4.6초
- 4K 320초 원본: Gate가 117.6초로 제한 120초에 닿았고 MotionPhys는 timeout. 4K는 받지 않는다
- Gate는 1080p에서 영상 1초당 약 0.3~0.46초다. Gate 제한 120초면 약 260초 영상까지 들어간다
- 작업 제한은 `min(1800, 180 + 20 × 적합 초)`다

| | (i) 제한보다 긴 영상 거부 | (ii) 발화가 가장 많은 구간만 분석 |
|---|---|---|
| 동작 | 길이 L 초과는 받지 않고 `video_too_long`으로 끝낸다(`--match-filter`로 다운로드 전에 거른다) | 전체 길이 상한 D 안의 영상에서 오디오만 먼저 받는다. Gate와 같은 webrtcvad로 발화가 가장 많은 W초 창을 고른 뒤, 그 구간만 받는다(`--download-sections`, 키프레임 경계 처리 필요) |
| 제안 값 | L = 180초. 60초나 120초도 가능 | W = 60초, D = 30분 |
| 예상 처리 시간(다운로드 제외) | 60초 영상 약 5~6분. 180초 영상은 발화가 많으면 약 16~18분(작업 상한 1800초 안) | 길이와 상관없이 약 5~6분 |
| 다운로드 양 | 1080p 1분에 약 30~60MB, 180초면 약 0.1~0.2GB(추정, 미측정) | 오디오 전체(분당 약 1MB) + 영상 60초 |
| 장점 | 단순하고, 분석 범위가 영상 전체다. Shorts(최대 3분)는 모두 들어간다 | 긴 영상도 받는다. 대기 시간이 일정하다 |
| 단점 | 긴 영상은 아예 분석하지 않는다. 180초면 어르신이 15분 넘게 기다릴 수 있다 | 고른 창에 얼굴이 없으면(내레이션) 다른 구간에 얼굴이 있어도 Gate가 거부한다. 구간 다운로드는 요청이 두 번이고 실패 경우가 늘어난다. 결과에 "전체 N분 중 60초만 분석"을 설명해야 한다(기존 `coverage`와 `explanations`로 표현, 새 필드 없음) |

**실패 원인 구분.** yt-dlp 종료 코드와 메시지 패턴으로 나눈다. 패턴은 고정 문자열 목록으로 두고, 테스트로 고정한다. 맞는 패턴이 없으면 `download_failed`다.

| 경우 | 대표 메시지(구현 때 실제 문구로 확인) | 원인 코드 |
|---|---|---|
| 봇 확인·로그인 요구·지역 차단 | "Sign in to confirm you're not a bot", "not available in your country" | `download_blocked` |
| 삭제됨 | "Video unavailable … removed" | `video_removed` |
| 비공개 | "Private video" | `video_private` |
| 연령 제한 | "Sign in to confirm your age" | `age_restricted` |
| 길이 초과((i)) | match-filter 건너뜀 | `video_too_long` |
| 생방송 | `is_live` 건너뜀 | `live_not_supported` |
| 네트워크·시간 초과 | 연결 오류, 다운로드 제한시간 | `download_network_error` |
| 맞는 형식 없음 | "Requested format is not available", 오디오 없음 | `no_suitable_format` |
| 그 밖 | — | `download_failed` |

## 5. 개인정보

- 받은 파일은 작업 폴더(`data/runtime/...`, 서버가 발급한 경로)에만 쓴다. 분석 종료·실패·취소·Worker 재시작 복구 때 기존 정리 경로로 지운다. 중간 파일(`.part`, 분리된 영상·오디오)도 같은 폴더에 두므로 함께 지워진다.
- `--no-cache-dir`로 yt-dlp 캐시를 남기지 않는다. 쿠키 파일도 만들지 않는다.
- 로그에는 작업 ID, 단계, 원인 코드만 남긴다. URL, 쿼리, 영상 제목·설명·채널, yt-dlp 원문 출력은 남기지 않는다. 사용자가 보낸 URL 원문도 저장하지 않는다. 지금처럼 video ID만 저장한다.
- 사용자 요청 영상은 학습 데이터에 넣지 않는다.

## 6. API 영향 — **계약 변경**

- 새 원인 코드 9개를 §10 목록과 결정 8 보완 표에 더한다. 새 필드와 새 상태 값은 없다.

| 코드 | analysis_status / verdict_status | 앱 문구안 |
|---|---|---|
| `download_blocked` | `analysis_unavailable` / `abstained` | YouTube가 영상 받기를 막아서 분석하지 못했습니다. |
| `video_removed` | `analysis_unavailable` / `abstained` | 삭제된 영상이라 찾을 수 없습니다. |
| `video_private` | `analysis_unavailable` / `abstained` | 비공개 영상이라 분석할 수 없습니다. |
| `age_restricted` | `analysis_unavailable` / `abstained` | 나이 제한이 있는 영상은 로그인 없이 받을 수 없어 분석하지 못했습니다. |
| `video_too_long` | `unsupported` / `abstained` | 영상이 길어서 분석하지 않았습니다. {L/60}분 이하 영상만 분석합니다. |
| `live_not_supported` | `unsupported` / `abstained` | 실시간 방송은 분석하지 않습니다. 방송이 끝난 뒤 다시 보내 주세요. |
| `download_network_error` | `analysis_unavailable` / `abstained` | 인터넷 문제로 영상을 받지 못했습니다. 잠시 뒤 다시 시도해 주세요. |
| `no_suitable_format` | `analysis_unavailable` / `abstained` | 분석할 수 있는 형태의 영상(소리 포함)을 찾지 못했습니다. |
| `download_failed` | `analysis_unavailable` / `abstained` | 영상을 받는 중 문제가 생겨 분석하지 못했습니다. |

- `download_network_error`만 기존 재시도(`max_attempts` 2)를 탄다. 나머지는 다시 해도 같으므로 재시도하지 않는다.
- 방식 (ii)를 고르면 원인 코드는 같다. 분석 범위가 일부라는 사실은 `coverage`(전체 길이 대비 분석 길이)와 `explanations` 한 항목으로 알린다.

## 7. 시연 위험 대비

1. **전날 확인:** 시연할 공개 영상 1개와 Shorts 1개를 실제로 내려받아 끝까지 분석한다.
2. **당일 막혔을 때**(`download_blocked` 등):
   - `TRINITY_RESEARCH_DOWNLOAD=0`으로 Worker를 다시 시작한다.
   - 본인 촬영 영상을 등록한 테스트 링크로 시연한다. 등록부에 `local_path`가 연결된 ID라 다운로드하지 않는다.
   - 앱 화면 흐름은 같다.
3. **사전 준비:** 등록할 테스트 ID와 본인 영상 경로를 Git 밖 등록부에 미리 넣고, 그 흐름을 한 번 돌려 둔다. 등록부는 다운로드보다 먼저 확인되므로, 다운로드를 켜 둔 채로도 테스트 링크는 등록 파일로 간다.
4. **발표 문구:** 다운로드가 막힌 것은 플랫폼 정책 때문이고, 분석 기능의 실패가 아니라고 한 줄로 설명한다.

## 8. 테스트 계획

**네트워크 없는 단위 테스트(CI·pytest)**
- URL
  - 앞뒤 글자에서 링크 하나 고르기
  - 링크 두 개면 거부
  - 스킴 없는 링크 보정
  - `si`·`feature`·`t` 제거
  - Shorts·live·m. 형식
  - music·nocookie·다른 호스트·IP 거부
  - 8KB 상한
- 인자
  - 리스트에 정규 URL만 들어가고 사용자 문자열은 들어가지 않음
  - `--ignore-config`, `--no-cache-dir`, `--js-runtimes deno:<abs>` 포함
  - 쿠키 관련 인자 없음
  - 출력 경로가 작업 폴더 안
- 원인 분류: 위 표의 대표 메시지(합성 문자열)마다 코드, 알 수 없는 메시지는 `download_failed`
- Worker
  - 가짜 다운로드 프로세스로 성공 → Gate 진입
  - 실패 코드별 상태 대응
  - 취소·timeout 시 프로세스 그룹 종료와 작업 폴더 삭제
  - 등록부 우선
  - 기본 꺼짐(설정이 없으면 다운로드하지 않음)
- 로그 검사: 실패 경로 로그에 URL·쿼리·제목 문자열이 없음
- Deno 버전 검사(가짜 `deno --version` 출력): 2.3.0 미만이면 거부
- 방식 (ii)를 고르면 추가: 창 선택 순수 함수(webrtcvad 결과 → 창)

**사용자가 직접 돌릴 실제 다운로드 확인 절차(문서화, 네트워크 필요)**
1. `research/download/.venv` 설치, `deno --version`, `yt-dlp --version` 기록
2. 공개 영상 1개(말하는 사람, 1분 안팎): 접수 → `finished`. 받은 해상도·길이·오디오, 단계별 시간, 작업 폴더 삭제 확인
3. Shorts 1개: 같은 확인. 세로 1080×1920 여부 확인
4. 실패 사례: 존재하지 않는 ID(`video_removed` 또는 `download_failed`), 길이 초과 영상(`video_too_long`), 네트워크 차단 상태(`download_network_error`). 비공개·연령 제한 영상은 링크를 구할 수 있으면 확인한다
5. 로그와 DB에 URL 쿼리·제목이 없는지 `grep`으로 확인

## 9. 구현 순서(승인 뒤, 브랜치 `feat/research-download`)

1. §15.3·AGENTS 반영
2. URL 텍스트 처리(테스트 먼저)
3. 어댑터와 원인 분류(가짜 프로세스 테스트)
4. Worker 연결과 원인 코드·앱 문구(API 계약 변경)
5. 실제 확인 절차 문서

PR은 하나로 하고 merge는 하지 않는다.
