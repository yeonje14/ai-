# Gate 작은 얼굴 입 측정 개선 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 얼굴이 프레임에 비해 작은 영상(세로 전신 구도 등)에서 입 벌림 측정이 실패하는 문제를 줄인다. 지금은 이 실패가 `no_mouth_movement`("말하지 않음")로 거부된다. 개선 후에도 남는 측정 실패는 별도 원인으로 드러낸다.

**Architecture:** 세 단계로 진행한다.
1. **측정.** 서버 코드는 바꾸지 않는다. 연구 스크립트로 후보 변형을 본인 영상 A~E와 Seamless A·B에 돌려 비교한다.
2. **승인.** 측정 수치를 넣은 §15.3 변경안을 사용자에게 제출하고 승인을 받는다.
3. **구현.** 승인된 안만 `server/gate`와 앱에 구현한다.

**Tech Stack:** Python 3.11, MediaPipe Tasks 1.2.3(FaceDetector, FaceLandmarker, CPU), OpenCV, pytest, Flutter(문구 1줄).

**Spec:**
- PR #39 `docs/seamless-preprocess.md` §4.4(원인 진단)·§4.5(사용자 결정)
- `docs/DESIGN.md` §10, §15.3 "결정 8 보완 — 2026-11-15" 표
- `docs/gate.md`
- 백로그 6번(Gate) 행

## Global Constraints

- **사용자 결정(2026-11-26):** 데이터를 얼굴 주변으로 잘라 넣는 방식(제안 1)은 쓰지 않는다. Gate는 서비스와 같은 전체 프레임 입력을 받는다.
- **로그·파일 기록:** 프레임, 얼굴 crop, 특징점 좌표를 저장하거나 로그에 남기지 않는다. 숫자(성공 여부, 박스 크기, 입 벌림 비율, 시간)만 남긴다.
- **측정 데이터:** 본인 촬영 A~E(`data/research/samples/`)와 Seamless pilot-00 전처리본(`data/research/seamless/pilot/pilot-00/pre/`)만 쓴다. 외부 평가 자료는 쓰지 않는다. 결과는 Git 밖 `data/research/gate-small-face/`에 둔다.
- **null 규칙:** 측정하지 못한 표본의 `opening`은 지금처럼 `None`이다. 0으로 채우지 않는다.
- **바꾸지 않는 것:** 서비스 제한(`gate_timeout` 120초), 입 벌림 정의(13–14 ÷ 33–263), 입 움직임 임계값(`mouth_min_swing` 0.02, 반전 3회 등).
- **API 계약 변경 범위:** 새 API 필드와 새 상태 값은 만들지 않는다. 다만 새 원인 코드 값을 하나 더하는 것((c))은 **API 계약 변경**이다. §15.3 승인 전에는 구현하지 않는다.
- **새 모델 파일((b)):** 다음 세 가지가 확인되기 전에는 채택하지 않는다.
  - 출처·SHA-256(`configs/gate_models.json`)
  - 이용 조건(`docs/licenses.md`)
  - MediaPipe 1.2.3 Tasks API에서 로드·추론되는지
- **Gate 동작이 바뀌면** `training/features/extract.py`의 `GATE_VERSION`을 `"gate-v2"`로 올린다(특징 캐시 키). 고정된 묶음은 아직 없다.

## 1. 원인 (PR #39 §4.4 요약)

Seamless B 전처리본(1080×1920)의 결과는 다음과 같다.
- Gate 입 벌림 측정은 49/375 표본만 성공했다. 음성 구간 전체가 `no_mouth_movement`로 거부됐다.
- 얼굴은 검출 높이 중앙값 286px로 A(251px)보다 크다.
- 검출기가 얼굴을 찾은 90개 표본에서 Face Landmarker의 특징점 성공 수:
  - 전체 프레임: 21개
  - 검출 박스 2–4배 정사각형 crop: 90개
  - 5배 crop: 87개, 6배 crop: 72개
  - A는 같은 비교에서 118 → 119–122로 거의 같았다.
- 특징점 모델이 전체 프레임에서 작은 비율의 얼굴을 놓친다.
- 측정이 없으면 시계열이 끊긴다. 그래서 "입을 잴 수 없음"이 "입이 움직이지 않음"으로 분류된다.
- 검출기 자체가 놓친 표본도 35/125개 있다(`no_face_detected` 4.8초).

## 2. 후보 비교

| | (a) 2단계: 검출 박스 주변 crop에 특징점 | (b) full-range 얼굴 검출 모델 | (c) 새 원인 코드 `mouth_unmeasurable` |
|---|---|---|---|
| 고치는 것 | 검출기는 얼굴을 찾았는데 특징점이 실패하는 경우(B의 69/90) | 검출기가 얼굴을 놓치는 경우(B의 35/125). Gate 검출기(`detect_faces`)만 바뀌고, Face Landmarker 번들 안의 검출기(short-range, 해시 같음)는 그대로다. **단독으로는 B의 `no_mouth_movement`를 고치지 못한다**. (a)와 함께 써야 새로 잡은 박스가 crop에 쓰인다 | 측정 수를 늘리지 않는다. 측정 실패를 "말하지 않음"이 아닌 품질 문제로 정직하게 내보낸다 |
| 정확도 근거 | 진단에서 B 21/90 → 90/90(2–4배), A 118 → 119–122. 영상 2개뿐이다. 배율 3은 B를 본 뒤 고른 임시값이다. crop하면 입 벌림 값 자체가 조금 달라질 수 있어 C·D(입 움직임 없음)가 통과될 위험이 있다. 측정으로 확인한다 | 미측정. 원거리용 모델이라 가까운 큰 얼굴(A~E)에서 나빠질 수 있다. 확인 필요 | 판정 정확도와 무관하다. 규칙: 움직임이 없는 조각의 측정률이 0.5 미만이면 `mouth_unmeasurable`, 이상이면 `no_mouth_movement`. D처럼 얼굴이 보이고 입이 멈춘 영상은 측정률이 높아 `no_mouth_movement`로 남아야 한다 |
| 속도 | 추가 검출 추론이 없다. 이미 있는 초당 5장 검출 박스를 다시 쓴다. 특징점 입력이 작아진다. 같거나 빠를 것으로 예상하지만 측정으로 확인한다 | 모델 파일이 1,083,786바이트로 지금(229,746바이트)의 약 4.7배다. 검출이 느려질 것으로 예상하며 크기는 미측정 | 영향 없음(구간 계산만) |
| API 영향 | 없음. 필드·상태·원인 코드가 그대로다. 결과만 달라진다(적합 구간 증가 예상) | 없음. 모델 파일·해시·문서·라이선스 기록이 바뀐다 | **API 계약 변경.** 내용은 아래와 같다 |
| 함께 바뀌는 것 | `GATE_VERSION` | `configs/gate_models.json`, `docs/gate.md`, `docs/licenses.md`, `GATE_VERSION` | `server/gate/runner.py`의 `GATE_REASONS`(빠뜨리면 `parse_result`가 거부해 `gate_error`), `report.py`의 대응·문구(빠뜨리면 KeyError), `app/lib/view_state.dart`, `GATE_VERSION` |
| 미확인 | 배율의 일반화 | Tasks API 호환, 이용 조건(모델 카드), 정확도, 속도 | 측정률 기준 0.5(임시값) |

**(c)의 API 계약 변경 내용.**
- `reason_code`에 새 값 `mouth_unmeasurable`이 나올 수 있다.
  - 최상위 `reason_code`: 적합 구간이 없을 때
  - `explanations[].reason_code`: 제외 구간마다
- 대응: `analysis_status=insufficient_quality`, `verdict_status=abstained`. 지금은 같은 경우가 `out_of_scope` / `not_applicable`로 나간다.
- 고쳐야 할 계약 문서:
  - §10 "발화 구간 Gate의 구간 제외 원인" 목록
  - §15.3 결정 8 보완 표
- 새 필드와 새 상태 값은 없다.
- 문구를 모르는 이전 앱은 `result_screen.dart:65`의 기본 문구(`noReason`)와 서버 설명 메시지를 보여 준다.

**권고.**
- (a)와 (c)를 함께 측정하고, 기준을 넘으면 함께 채택한다.
  - (a)는 이번 실패의 대부분을 고친다.
  - (c)는 (a)로도 남는 실패를 숨기지 않는다.
- (b)는 사전 조건(이용 조건, Tasks API)이 확인될 때만 측정한다. 기준을 넘으면 따로 채택한다(Task 5).

## 3. 비교 방법 (측정 전에 고정)

**측정 실행 결정 (2026-11-26 사용자).** 이 결정은 확인용 영상을 받기 전에 커밋한다.
- 실행 방식은 이 세션에서 직접 구현이다.
- crop 배율은 **3으로 고정**한다. B를 보고 정한 값이므로 아래 확인용 영상에서 다시 고르지 않는다.
- (c)는 API 계약 변경이므로 이번에는 §15.3 문안까지만 쓴다. 재라벨 수치는 비교 스크립트로 센다. 구현은 승인 뒤에 한다.
- (b)는 이번 측정에 넣지 않는다. 지시 범위가 V0 대 (a)이고, 사전 조건도 확인하지 않았다.

**영상 묶음.** 표를 묶음별로 나눈다.

| 묶음 | 영상 | 성격 |
|---|---|---|
| 개발용 | Seamless pilot#0 전처리본 A·B(1080×1920, 25초) | 원인 진단과 배율 결정에 이미 본 영상 |
| 확인용 | 예약 파일럿 1~3번 쌍의 A·B 6개. `fetch_pilot.py --order 1·2·3`으로 받아 `docs/seamless-preprocess.md` 규칙대로 전처리한다 | 측정 전에 열어 보지 않은 영상 |
| 회귀 | 본인 촬영 원본 A(가로 발화), B(세로 발화), C(발화 없음), D(입 움직임 없이 음성), E(발화·침묵 교대) | 현행 대비 나빠지지 않는지 확인 |

- 확인용에서 창을 만들 수 없는 영상(`window_unavailable`)은 바꾸지 않고 그대로 기록한다.
- 다운로드가 불완전한 쌍도 바꾸지 않고 그대로 기록한다.

**변형.**
- V0: 현행
- Va: (a). crop 배율 3, 박스 시각 차 0.1초 이내
- (c)는 각 변형 결과에 규칙을 적용해 라벨만 다시 센다.

**지표(영상 × 변형).** 숫자만 기록한다.

| # | 지표 | 정의 |
|---|---|---|
| 1 | 검출률 | 5fps 표본 중 얼굴 1개 이상, 주된 얼굴(짧은 변 × 0.10 이상) 1개 이상 |
| 2 | **입 벌림 측정률(주 지표)** | 음성 구간(±0.75초) 안 15fps 표본 중 `opening`이 있는 비율 |
| 3 | 입 벌림 일치 | V0와 변형이 같은 시각 표본을 둘 다 쟀을 때 \|Δopening\|의 중앙값·최대 |
| 4 | Gate 결과 | 대표 원인, 적합 구간 길이·개수, 제외 사유별 초. (c) 규칙 적용 전과 후 |
| 5 | E 기준 대조 | 촬영자 기록 발화(0–10, 20–30, 40–50초)와 적합 구간의 겹침과 밖으로 나간 길이. 현행 기준값: 겹침 24.224초, 밖 0.640초 |
| 6 | 시간 | Gate 전체와 검출·입 측정 단계. 3회 반복의 중앙값. 반복마다 변형 순서를 돌려 열 상태 영향을 줄인다 |

**채택 기준(2026-11-26 사용자 승인. 확인용 기준은 같은 날 확인용 영상을 받기 전에 고정).**
- **(a) 개발용**
  - Seamless pilot#0 B 측정률 80% 이상(현행 13%)
  - Seamless pilot#0 A 측정률이 V0보다 2%p 넘게 떨어지지 않음
- **(a) 회귀(본인 A~E)**
  - 측정률이 V0보다 2%p 넘게 떨어지지 않음
  - C·D는 적합 0초, `no_mouth_movement` 유지
  - A·B·E 적합 길이 변화 ±5% 이내. 넘으면 구간별 원인을 기록하고 사용자가 판단한다
  - E 겹침 감소 1초 이하
- **(a) 확인용(파일럿 1~3번, 영상마다)**
  - 측정률이 V0보다 2%p 넘게 떨어지지 않음
  - V0 측정률이 80% 미만인 영상은 Va 측정률 80% 이상. 그런 영상이 하나도 없으면 "개선 효과는 확인 불가, 비회귀만 확인"으로 적는다
  - V0에 적합 구간이 있으면, Va 적합 길이가 5% 넘게 줄지 않음
- **(a) 모든 묶음 공통(영상마다)**
  - \|Δopening\| 중앙값 0.01 이하(`mouth_min_swing` 0.02의 절반)
  - Gate 시간 증가 20% 이하(3회 중앙값)
- **판정.**
  - 개발용, 회귀, 확인용을 모두 통과하면 (a) 채택을 제안한다.
  - 하나라도 미달하면 미달 항목과 원인을 보고하고 사용자가 판단한다. 결과를 본 뒤 기준을 바꾸지 않는다.
- **(b)** (이번 측정에서는 하지 않음)
  - 사전 조건 둘을 확인한다.
  - Seamless B 검출 90/125 → 110/125 이상
  - A~E 검출률·적합 길이 하락 없음
  - 시간 증가 20% 이하
  - Vab가 Va보다 Seamless B 적합 길이를 늘림
- **(c)**
  - V0에서 Seamless B의 대표 원인이 `mouth_unmeasurable`
  - C·D는 모든 변형에서 `no_mouth_movement` 유지

**한계(보고서에 그대로 적는다).**
- 프레임 단위 정답이 없다. 측정률은 정확도가 아니다.
- 영상 13개(개발용 2, 확인용 최대 6, 회귀 5), 기기 1대다.
- 배율 3과 기준 0.5는 임시값이다.
- 다중 발화·옆얼굴은 여전히 미검증이다.

## 4. §15.3 변경 제안 문안 (측정 뒤 근거 수치를 채워 제출)

> **결정 8 보완(Gate 입 측정: 얼굴 주변 특징점, 입 측정 불가 원인) — 2026-11-2x, Claude 제안, 사용자 승인 대기.**
> 얼굴이 프레임에 비해 작으면 Face Landmarker가 전체 프레임에서 특징점을 내지 못한다. 그러면 측정이 없는 음성 구간이 `no_mouth_movement`(`out_of_scope` / `not_applicable`)로 분류됐다(Seamless pilot#0 B: 입 벌림 측정 49/375, `docs/seamless-preprocess.md` §4.4). 다음과 같이 정한다.
> - **입 벌림 측정(2단계).**
>   - 입 표본 프레임마다 Gate 얼굴 검출(초당 5장) 가운데 시각이 가장 가까운 표본(차이 0.1초 이하)을 고른다.
>   - 그 표본에서 가장 큰 얼굴 박스를 중심으로 정사각형을 잡는다. 한 변은 박스 긴 변의 3배이고, 프레임 밖은 잘라낸다.
>   - 이 정사각형에 Face Landmarker를 적용하고, 좌표는 원래 프레임 픽셀로 되돌린다.
>   - 가까운 검출이 없으면 지금처럼 전체 프레임에 적용한다.
>   - 입 벌림 정의와 입 움직임 임계값은 바꾸지 않는다. 배율 3은 임시값이다.
> - **새 Gate 구간 제외 원인 `mouth_unmeasurable`.**
>   - 대상: 주된 얼굴이 하나인 음성 구간에서 반복되는 입 움직임을 확인하지 못한 조각 가운데, 조각 안 입 표본의 절반 미만만 입 벌림을 잰 조각(임시값 0.5).
>   - 절반 이상을 쟀는데 움직임이 없으면 지금처럼 `no_mouth_movement`다. 조각 안에 표본이 하나도 없으면 지금처럼 `no_mouth_movement`다.
>   - 대응은 `insufficient_quality` / `abstained`다. 위 결정 8 보완 표에 행을 더한다.
>   - 발화 없음 계열(`NO_SPEECH_FAMILY`)에는 넣지 않는다.
> - **API 계약 변경.**
>   - §10 "발화 구간 Gate의 구간 제외 원인" 목록에 값 `mouth_unmeasurable`을 더한다.
>   - 이 값은 최상위 `reason_code`와 `explanations[].reason_code`에 나올 수 있다.
>   - 새 API 필드와 새 상태 값은 없다.
>   - 앱은 이 코드의 안내 문구를 추가한다. 문구가 없는 이전 앱은 기본 문구와 서버 설명 메시지를 보여 준다.
> - 학습 특징 버전의 Gate 버전을 `gate-v2`로 올리고 옛 캐시는 쓰지 않는다. 고정된 묶음은 아직 없다.
>
> 근거: 본인 영상 A~E와 Seamless pilot#0 A·B의 측정률·적합 길이·시간(`docs/gate.md` "작은 얼굴 입 측정 비교"). 수치는 측정 뒤 채운다.

(b)를 채택할 때만 다음 항목을 더한다.

> - **Gate 얼굴 검출 모델을 `blaze_face_full_range.tflite`로 바꾼다.**
>   - 출처·SHA-256·이용 조건을 `configs/gate_models.json`, `docs/gate.md`, `docs/licenses.md`에 기록한다.
>   - Face Landmarker 번들 안의 검출 모델은 바꾸지 않는다.
>   - 근거: (측정 수치)

## Review Focus

1. **두 사람 이상 얼굴.** crop은 가장 큰 박스를 기준으로 한다. 주된 얼굴이 여럿인 구간은 지금처럼 `speaker_unconfirmed`여야 한다. 테스트는 Task 3의 `test_nearest_box_picks_largest_face`.
2. **프레임 가장자리 얼굴.** 잘린 직사각형 crop에서도 입 벌림 비율이 같아야 한다. 테스트는 Task 3의 `test_crop_square_clips_at_frame_edge`, `test_sample_maps_crop_back_to_frame`.
3. **회전 메타데이터가 있는 세로 영상(본인 B.MOV).** 검출 박스와 입 측정이 같은 cv2 디코딩 좌표계를 써야 한다. 덮는 테스트는 Task 3의 실제 미디어 테스트(B.MOV 적합 구간 유지).
4. **측정률 경계와 표본 없는 조각.** 정확히 0.5면 `no_mouth_movement`, 표본이 0개여도 `no_mouth_movement`다. 테스트는 Task 4.
5. **새 코드를 모르는 클라이언트.** 서버 `parse_result`가 새 코드를 `gate_error`로 바꾸면 안 된다. 테스트는 Task 4의 `test_parse_result_accepts_mouth_unmeasurable`. 이전 앱은 기존 fallback 경로를 쓴다.

---

### Task 1: 비교 스크립트 (서버 동작 불변)

**Files:**
- Create: `scripts/gate_small_face_compare.py`
- Test: `tests/test_gate_small_face_compare.py`

**Interfaces:**
- Produces(Task 3·4가 서버로 옮긴다):
  - `crop_square(box: tuple[float, float, float, float], scale: float, width: int, height: int) -> tuple[int, int, int, int]`: (x0, y0, x1, y1), 프레임 안 정수
  - `nearest_box(frames: Sequence[FrameFaces], t: float, max_dt: float) -> Optional[tuple[float, float, float, float]]`: 가장 가까운 검출 표본의 가장 큰 얼굴
  - `measured_fraction(samples: Sequence[MouthSample], start: float, end: float) -> Optional[float]`: `start ≤ t ≤ end` 표본 중 `opening`이 있는 비율. 표본이 없으면 None
- Produces(스크립트 전용):
  - `overlap_sec(a: Sequence[Interval], b: Sequence[Interval]) -> float`
  - `run_variant(path: Path, variant: str, models: dict[str, Path], config: GateConfig) -> dict`: §3의 지표 1·2·4·6. 표본별 `(t, opening)` 목록은 지표 3 계산에만 쓰고 파일에 쓰지 않는다
- CLI:
  - `python scripts/gate_small_face_compare.py run [--repeat 3]` → `data/research/gate-small-face/results.json`(변형 V0·Va)
  - `... report` → 마크다운 표
- 입력 경로는 §3의 영상 묶음으로 고정한다. 인자로 임의 경로를 받지 않는다. 없는 파일은 "없음"으로 기록하고 건너뛴다.

- [ ] **Step 1:** 실패하는 테스트를 쓴다.
  - `test_crop_square_centers_box`: box (100, 100, 50, 80), scale 3, 1080×1920 → (5, 20, 245, 260)
  - `test_crop_square_clips_at_frame_edge`: box (0, 0, 50, 80) → x0 = 0, y0 = 0, x1 = 145, y1 = 160
  - `test_nearest_box_picks_largest_face`: t = 0.0에 높이 100·200 얼굴 → 질의 t = 0.067이면 높이 200 박스. t = 0.35, max_dt 0.1이면 None
  - `test_measured_fraction`: 표본 4개 중 1개 측정 → 0.25. 구간 안 표본 없음 → None
  - `test_overlap_sec`: [(0, 10)]와 [(5, 12)] → 5.0
  - `test_report_marks_missing_video`: 결과가 없는 영상은 표 칸이 "없음"
- [ ] **Step 2:** `pytest -q tests/test_gate_small_face_compare.py`를 실행해 실패(ImportError)를 확인한다.
- [ ] **Step 3:** 구현한다.
  - 변형 Va의 입 측정은 `server/gate/mouth.py`의 `_sample`을 crop 좌표로 호출한다(원점·크기 인자는 스크립트 안 래퍼에서 되돌린다).
  - Gate 순서(probe → vad → detect_faces → assign_tracks → 입 측정 → build_result)는 `server/gate/__init__.py`와 같게 한다.
- [ ] **Step 4:** 테스트 통과를 확인한다.
- [ ] **Step 5:** 커밋한다: `git add scripts/gate_small_face_compare.py tests/test_gate_small_face_compare.py`

### Task 2: 측정 실행과 §15.3 제출 — **여기서 멈추고 사용자 승인**

**Files:**
- Modify: `docs/gate.md`(새 절 "작은 얼굴 입 측정 비교")
- Modify: 이 계획 §4 문안의 근거 수치

- [ ] **Step 1: 확인용 영상 준비.**
  - `data/research/seamless/.venv/bin/python -I research/seamless/fetch_pilot.py --order N`(N = 1, 2, 3)
  - `python scripts/seamless_preprocess.py --order N`. 이를 위해 이 스크립트가 `--order`를 받게 한다. pilot#0 재실행 결과가 기존 SHA-256과 같은지 확인한다.
  - 전처리 결과는 열어 보지 않는다.
- [ ] **Step 2:** `python scripts/gate_small_face_compare.py run --repeat 3`를 실행한다. 종료 0이고, 있는 영상 × V0·Va가 모두 기록돼야 한다.
- [ ] **Step 3:** `... report`로 표를 만든다. `docs/gate.md`에 표와 §3 기준별 통과/미달, 한계를 적는다.
- [ ] **Step 4:** §4 문안에 수치를 채운다. 커밋·push하고 사용자에게 제출한다. **승인 전에는 Task 3 이후를 하지 않는다.**

### Task 3: (a) 서버 구현

**Files:**
- Modify: `server/gate/mouth.py`(`crop_square`, `nearest_box` 이동, `measure_mouth`에 `frames` 인자, `_sample`에 원점·crop 크기 인자)
- Modify: `server/gate/types.py`(`GateConfig.mouth_crop_scale: float = 3.0`)
- Modify: `server/gate/__init__.py`(`measure_mouth(..., frames=frames)`)
- Modify: `training/features/extract.py`(`GATE_VERSION = "gate-v2"`)
- Modify: `scripts/gate_small_face_compare.py`(서버 함수 import로 교체)
- Modify: `docs/DESIGN.md` §15.3(승인 문안), §14.1 6번 상태, `docs/gate.md` 입 벌림 측정 설명
- Test: `tests/test_gate_mouth.py`, `tests/test_gate_media.py`

**Interfaces:**
- `measure_mouth(path, media, model_path, config, within=None, frames: Optional[Sequence[FrameFaces]] = None) -> list[MouthSample]`
  - `frames=None`이면 현행(전체 프레임)과 같다.
  - 박스 시각 차 상한은 `0.5 / config.face_sample_fps`(기본 0.1초)다.
  - crop 크기는 `frame.shape`로 계산한다(`media.width`가 아니다).
- `MouthSample.box`는 계속 원래 프레임 픽셀 좌표다.

- [ ] **Step 1:** 실패하는 테스트를 쓴다.
  - Task 1의 crop·nearest 테스트를 서버 함수로 옮긴다.
  - `test_sample_maps_crop_back_to_frame`: 같은 픽셀 위치의 특징점을 crop 기준(원점 (200, 300), 크기 300×300)과 전체 프레임 기준으로 넣으면 `opening`과 `box`가 같다.
  - `test_measure_mouth_without_frames_is_unchanged`: `frames=None` 경로가 현행 호출과 같은 인자로 landmarker를 부른다(가짜 landmarker).
  - `test_gate_media.py`의 실제 미디어 테스트(파일 없으면 skip):
    - Seamless pilot-00 B 전처리본의 `mouth_summary.measured / samples ≥ 0.8`, 적합 구간 > 0
    - 기존 A·B·E 통과, C·D `no_mouth_movement`
- [ ] **Step 2:** 실패를 확인한다.
- [ ] **Step 3:** 구현한다.
- [ ] **Step 4:** 확인한다. `pytest -q tests/test_gate_mouth.py tests/test_gate_media.py tests/test_gate_small_face_compare.py`가 통과하고, 비교 스크립트의 Va 수치가 Task 2와 같아야 한다.
- [ ] **Step 5:** 커밋한다.

### Task 4: (c) `mouth_unmeasurable` — API 계약 변경

**Files:**
- Modify: `server/gate/types.py`(`MOUTH_UNMEASURABLE = "mouth_unmeasurable"`, `GateConfig.mouth_min_measured_ratio: float = 0.5`. `NO_SPEECH_FAMILY`는 그대로)
- Modify: `server/gate/mouth_activity.py`(`measured_fraction` 이동)
- Modify: `server/gate/segments.py`(`build_result(..., mouth_samples: Optional[Sequence[MouthSample]] = None)`. 움직임 없는 조각마다 측정률 < 0.5면 `MOUTH_UNMEASURABLE`. `None`이거나 표본이 없으면 `NO_MOUTH_MOVEMENT`)
- Modify: `server/gate/__init__.py`(`mouth_samples=samples`)
- Modify: `server/gate/runner.py`(`GATE_REASONS`)
- Modify: `server/gate/report.py`
  - `REJECTION_STATES["mouth_unmeasurable"] = ("insufficient_quality", "abstained")`
  - 문구: "음성 구간에서 입 모양을 측정하지 못해 말하는지 확인하지 못했습니다."
- Modify: `app/lib/view_state.dart`(같은 문구), `app/test/view_state_test.dart`
- Modify: `docs/DESIGN.md` §10 목록·§15.3 결정 8 보완 표, `docs/gate.md` 원인 코드 표
- Test: `tests/test_gate_segments.py`, `tests/test_gate_runner.py`, `tests/test_gate_worker.py`, `tests/test_gate_mouth.py`

- [ ] **Step 1:** 실패하는 테스트를 쓴다.
  - `test_unmeasured_piece_is_mouth_unmeasurable`: 얼굴 하나, 0–10초 음성, 활동 없음, 표본 150개 중 30개 측정 → 제외 원인 `mouth_unmeasurable`, 대표 원인도 같다
  - `test_half_measured_piece_stays_no_mouth_movement`: 정확히 0.5 → `no_mouth_movement`
  - `test_piece_without_samples_stays_no_mouth_movement`
  - `test_mouth_samples_none_keeps_old_behavior`
  - `test_mouth_unmeasurable_not_in_no_speech_family`
  - `test_parse_result_accepts_mouth_unmeasurable`. 기존 미지 코드 거부 테스트는 유지한다
  - `test_gate_worker.py` 매개변수에 `("mouth_unmeasurable", "insufficient_quality", "abstained")` 추가
  - Flutter: `expect(reasonText('mouth_unmeasurable'), isNotNull)`
- [ ] **Step 2:** 실패를 확인한다.
- [ ] **Step 3:** 구현하고, 승인된 문안대로 DESIGN·gate.md를 고친다.
- [ ] **Step 4:** 확인한다.
  - `pytest -q tests/test_gate_*.py` 통과
  - `app/`에서 `flutter analyze` 지적 없음, `flutter test` 통과
  - 비교 스크립트의 (c) 재라벨 수치가 Task 2와 같아야 한다
- [ ] **Step 5:** 커밋한다.

### Task 5: (b) full-range 검출 모델 — Task 2 기준 통과와 사용자 승인 시에만

**Files:**
- Modify: `configs/gate_models.json`(`face_detector` 항목: 파일, SHA-256, 출처, 받은 날짜)
- Modify: `docs/gate.md` 모델 표·내려받기 명령, `docs/licenses.md`

- [ ] **Step 1:** 실패하는 테스트를 쓴다. `test_gate_media.py`에서 Seamless B 검출률 ≥ 110/125(파일 없으면 skip). 기존 A~E 기대값은 유지한다.
- [ ] **Step 2:** 모델 교체 전에 실패를 확인한다.
- [ ] **Step 3:** 설정을 교체한다. 해시가 다르면 Gate가 실행을 거부하는 기존 동작은 유지한다.
- [ ] **Step 4:** `pytest -q tests/test_gate_*.py`를 실행해 통과를 확인한다.
- [ ] **Step 5:** 커밋한다. 채택하지 않으면 이 Task는 `docs/gate.md`에 "미채택(사유)"만 적는다.

### Task 6: 최종 확인과 PR (merge 금지)

- [ ] **Step 1:** 전체 테스트. `pytest -q`가 통과해야 한다(이전 기준 1002 passed, 1 skipped).
- [ ] **Step 2:** `python scripts/smoke_gate_worker.py`. 종료 0이고, 발화 없는 샘플은 여전히 `no_mouth_movement`여야 한다.
- [ ] **Step 3:** Seamless B 전처리본을 Worker 경로로 확인한다.
  - 명령: `python scripts/seamless_first_pair.py run --who B --input pre`(PR #39로 main에 있다).
  - Gate 결과와 축 상태를 `docs/gate.md`에 적는다.
- [ ] **Step 4:** `docs/HANDOFF.md`를 갱신하고 PR을 연다. 본문에 API 계약 변경((c))을 명시한다.
