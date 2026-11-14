# TRINITY 앱 (Flutter)

README §14.1 백로그 13번의 앞부분. YouTube 주소 입력 → 분석 상태 → 결과를 보여 준다.

> **모델 미연결 · 가상 데이터.** 화면의 결과는 실제 분석이 아니다. mock 모드는 꾸며 낸 값을, 실제 서버 모드는 stub 서버의 값을 보여 준다.
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

입력 화면의 "가상 결과 고르기"에서 결과를 고른 뒤 YouTube 주소를 넣고 "분석 요청"을 누른다.

### 실제 서버 모드

터미널 두 개에서 서버와 Worker를 띄운다(저장소 루트, conda `trinity`).

```bash
uvicorn server.main:app --port 8000
TRINITY_STUB_STAGE_DELAY_SECONDS=1 python -m server.jobs.worker   # 단계가 바뀌는 것을 보려면 지연을 준다
```

앱을 실행한다.

```bash
cd app
flutter run -d chrome --web-port 8080 --no-web-resources-cdn \
  --dart-define=TRINITY_API_MODE=server --dart-define=TRINITY_API_BASE_URL=http://localhost:8000
```

- 서버는 기본으로 `http://localhost:8080`과 `http://127.0.0.1:8080`에서 온 브라우저 요청만 받는다. 그래서 `--web-port 8080`이 필요하다. 다른 포트를 쓰려면 서버의 `TRINITY_CORS_ORIGINS`를 바꾼다(localhost·127.0.0.1만 받고 `*`는 거부한다).
- 등록된 가짜 ID(`https://www.youtube.com/watch?v=TRINITYtest`)는 "판단 보류", 그 밖의 YouTube 주소는 "영상 접근 불가"가 나온다.
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

# 브라우저 없이 앱의 API 클라이언트로 실제 서버를 불러 본다 (서버와 Worker가 떠 있어야 한다)
dart run tool/smoke_server.dart http://localhost:8000 'https://www.youtube.com/watch?v=TRINITYtest'
```

## 구조

| 경로 | 내용 |
|---|---|
| `lib/design/` | 토큰, 테마, 공통 위젯 |
| `lib/api/` | 응답 모델, HTTP 클라이언트, mock |
| `lib/view_state.dart` | 서버 상태 → 화면·문구 대응 |
| `lib/screens/` | 입력, 분석 중, 결과 3종, 판단 근거 상세, 영상 접근 불가, 분석 대상 아님 |
| `lib/app.dart` | 화면 흐름과 상태 조회 반복 |
| `assets/fonts/` | 글꼴 5개와 OFL 라이선스 |
| `tool/smoke_server.dart` | 실제 서버 연결 확인 |

## 서버와 주고받는 것

- `POST /api/v1/analyses` (`{"url": ...}`), `GET /api/v1/analyses/{id}`, `GET /api/v1/analyses/{id}/result`.
- `X-Client-Token`: 앱을 열 때 무작위로 만들어 메모리에만 둔다. 새로고침하면 진행 중이던 분석을 다시 볼 수 없다(정식 인증은 백로그 14번).
- 주소 검증은 서버가 한다. 앱은 빈 입력만 막는다.
- 상태는 1초마다 다시 조회한다. 조회가 실패하면 알리고 계속 다시 조회한다.

## 알려진 한계

- 웹(Chrome)에서만 확인했다. iOS·Android 빌드 설정이 없다.
- 영상 제목·썸네일을 보여 주는 미디어 확인 화면, 취소·삭제가 없다.
- 실제 서버 모드를 Chrome에서 손으로 눌러 끝까지 가 본 것은 아니다. 서버 연결은 `tool/smoke_server.dart`와 CORS 사전 요청으로 확인했다.
