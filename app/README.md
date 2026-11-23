# TRINITY 앱 (Flutter)

docs/DESIGN.md §14.1 백로그 13번의 앞부분. YouTube 주소 입력 → 분석 상태 → 결과를 보여 준다.

> **mock 모드(기본)는 "모델 미연결 · 가상 데이터"다.** 꾸며 낸 값을 보여 주며 실제 분석이 아니다.
> **실제 서버 모드는 "연구용 시제품 · 결과는 참고 정보"다.** 서버에 연결된 축의 실제 계산 상태를 보여 주지만, 검증된 결합 모델이 없어 항상 판단 보류이고 진위 판정이 아니다. 어느 축이 연결됐는지는 저장소 `docs/DESIGN.md` §14.1을 따른다.
> 파일 업로드 기능은 없다. 입력은 YouTube 주소뿐이다. iOS·Android 공유 시트는 아직 없다(웹만 확인했다).

디자인 규칙은 `docs/design-system.md`.

## 준비

Flutter 3.41.6(Dart 3.11.4)에서 확인했다.

```bash
cd app
flutter pub get
```

## 실행

### mock 모드 (기본, 서버 필요 없음)

```bash
flutter run -d chrome --web-port 8080 --no-web-resources-cdn
```

"예시로 둘러보기"를 누르거나, YouTube 주소를 넣고 "분석 요청"을 누른다. 홈의 "가상 결과 고르기"를 펴면 보여 줄 결과를 바꿀 수 있다.

브라우저 창이 768보다 넓으면 웹 배치(검색창 중심 홈), 그 이하면 앱 배치(세로형 홈)가 나온다. 시스템이 어두운 모드면 어두운 테마가 된다.

### 실제 서버 모드

[서버 실행 방법](../docs/DESIGN.md#서버-실행-방법-백로그-47번)의 3단계에 따라 운영자 전용 디렉터리(0700)에 새 계정 DB(0600)를 초기화하고 대화형 터미널에서 개인 키를 발급한다. 4단계대로 저장소 루트의 두 터미널에서 conda `trinity`를 활성화하고 같은 `TRINITY_DB_PATH`와 `TRINITY_RUNTIME_DIR`를 설정한 뒤 각각 실행한다.

```bash
uvicorn server.main:app --port 8000 --no-access-log
TRINITY_STUB_STAGE_DELAY_SECONDS=1 python -m server.jobs.worker   # 단계가 바뀌는 것을 보려면 지연을 준다
```

앱을 실행하고 세션 화면의 키 입력란에 발급받은 개인 키를 넣어 **인증**을 누른다.

```bash
cd app
flutter run -d chrome --web-port 8080 --no-web-resources-cdn \
  --dart-define=TRINITY_API_MODE=server --dart-define=TRINITY_API_BASE_URL=http://localhost:8000
```

- 서버는 기본으로 `http://localhost:8080`과 `http://127.0.0.1:8080`에서 온 브라우저 요청만 받는다. 그래서 `--web-port 8080`이 필요하다. 다른 포트를 쓰려면 서버의 `TRINITY_CORS_ORIGINS`를 바꾼다(localhost·127.0.0.1만 받고 `*`는 거부한다).
- 허가 미디어 레지스트리에 등록된 ID만 분석한다. 기본 레지스트리의 테스트 ID(`https://www.youtube.com/watch?v=TRINITYtest`)는 "판단 보류", 그 밖의 YouTube 주소는 "영상 접근 불가"가 나온다. 발화 구간 Gate가 거른 영상은 "분석 대상 아님" 등 원인별 화면이 나온다.
- 실제 모델까지 돌리려면 모델별 환경·가중치와 허가 미디어 등록이 필요하다. 절차는 `docs/HANDOFF.md`의 "Flutter 실제 서버 모드 A 예행" 재현 명령을 본다.
- 모든 화면 맨 위 띠와 판단 근거 화면의 안내는 이 모드에서 "가상 데이터" 대신 "연구용 시제품 · 결과는 참고 정보"로 나온다.
- **실제 서버 모드에서는 "의심 신호 발견"과 "의심 신호 낮음"이 나오지 않는다.** 검증된 결합 모델이 없어 서버가 `verdict_label`을 `null`로 보내고, 앱도 이 모드에서는 라벨을 보여 주지 않는다.

### 설정

| `--dart-define` | 값 | 기본 |
|---|---|---|
| `TRINITY_API_MODE` | `mock` 또는 `server` | `mock` |
| `TRINITY_API_BASE_URL` | 서버 주소 | `http://localhost:8000` |

`--no-web-resources-cdn`은 렌더링 엔진(CanvasKit)을 외부(gstatic)에서 받지 않고 앱에 넣는다. 빼도 동작하지만 실행할 때 외부 요청이 생긴다.

## 확인

```bash
flutter analyze
flutter test
flutter build web --no-web-resources-cdn
```

브라우저 없이 실행 중인 API와 Worker를 확인하려면 저장소 루트에서 `python scripts/smoke_slice.py`를 실행하고 개인 키를 숨김 입력한다.

## 구조

| 경로 | 내용 |
|---|---|
| `lib/design/` | 토큰(밝은·어두운 팔레트), 테마, 공통 위젯 |
| `lib/api/` | 응답 모델, HTTP 클라이언트, mock |
| `lib/view_state.dart` | 서버 상태 → 화면·문구 대응 |
| `lib/screens/` | 홈(웹형·앱형), 분석 중, 결과(발견·낮음·보류·접근 불가·대상 아님), 판단 근거 상세, 이용 안내 |
| `lib/app.dart` | 화면 흐름과 상태 조회 반복 |
| `assets/fonts/` | 글꼴 5개와 OFL 라이선스 |

## 서버와 주고받는 것

- `POST /api/v1/analyses` (`{"url": ...}`), `GET /api/v1/analyses/{id}`, `GET /api/v1/analyses/{id}/result`, `DELETE /api/v1/analyses/{id}`(취소).
- 분석 중 화면의 취소 버튼은 상태 조회에서 받은 `ETag`를 `If-Match`에 넣어 DELETE를 보낸다. `202`면 상태를 다시 조회해 "취소됨"을 보여 주고, 먼저 끝나 `412`가 오면 오류 없이 이미 나온 결과를 보여 준다(저장소 `docs/DESIGN.md` §9). 끝난 결과를 지우는 기능은 앱에 없다.
- 실제 서버 모드에서는 입력한 개인 키를 메모리에 보관한다. 새로고침 후에는 다시 인증해 본인 작업 목록을 연다. 앱이 접수용 UUID를 생성하므로 사용자가 직접 입력할 값은 개인 키와 YouTube 주소다.
- 주소 검증은 서버가 한다. 앱은 빈 입력만 막는다.
- 상태는 1초마다 다시 조회한다. 조회가 실패하면 알리고 계속 다시 조회한다.

## 알려진 한계

- 웹(Chrome)에서만 확인했다. iOS·Android 빌드 설정이 없다.
- 영상 제목·썸네일을 보여 주는 미디어 확인 화면, 끝난 결과의 삭제가 없다.
- 실제 서버 모드는 2026-11-16에 Chrome에서 테스트 ID 한 건(본인 촬영 영상 A, WaveRep·SyncNet 실제 실행)을 끝까지 눌러 확인했다(`docs/HANDOFF.md`). 실제 YouTube ID, 앱에서 누른 취소 버튼의 실제 서버 동작은 미검증이다.
