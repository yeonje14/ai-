# Worker 장치·열 상태 기록 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WaveRep·MotionPhys·SyncNet 실행기마다 실제 사용 장치(`device_used`)와 실행 시작·끝의 macOS thermalState를 Worker 로그와 API가 읽지 않는 내부 기록에 남긴다. API 필드·상태 값은 그대로다.

**Architecture:** 축 모듈이 실행기 출력의 장치를 `AxisContext.device_used`에 넣고, Worker가 축 호출 앞뒤로 thermalState를 읽어 로그 한 줄과 jobs 테이블의 내부 열(`run_info_json`)에 쓴다. thermalState는 Worker 밖의 짧은 프로세스(표준 라이브러리 ctypes)로 읽는다.

**Tech Stack:** Python 3.11 표준 라이브러리(ctypes, subprocess, sqlite3), 기존 FastAPI·Pydantic·pytest. 새 의존성 없음.

**Spec:** 사용자 요청(2026-11-19): "Worker 로그(그리고 결과 JSON의 축별 상세 중 API 계약을 바꾸지 않는 내부 기록 자리)에 WaveRep·SyncNet·MotionPhys 실행기의 device_used와 실행 시작·끝의 thermalState를 남겨. API 필드와 상태 값은 바꾸지 마." 출발점은 `docs/syncnet-adapter.md` "Worker 안 대 단독" 절의 제안 3.

## 결정 (2026-11-19 사용자 확인: D1=B, 실행 Native, 기록은 시도별 누적)

- **D1 내부 기록 자리.** 결과 JSON에는 API 계약을 바꾸지 않는 내부 자리가 없다. `server/schemas`의 축 모델은 Pydantic 기본(`extra` 무시)이라 축 dict의 추가 키는 `dump`에서 버려지고, DB `result_json`은 API 응답 본문 그대로다. 스키마에 필드를 더하면 API 변경이다. 그래서
  - **B(채택): jobs 테이블에 내부 열 `run_info_json` 추가.** 재선점 때 비우지 않고 시도 번호별로 쌓아 이전 시도 기록도 남긴다(사용자 지시). `_to_job`이 열을 골라 읽으므로 API로 나가지 않는다. 결과와 같은 행이라 작업 삭제(DELETE) 때 함께 지워진다. §8 "SQLite — 영속적 작업/상태/결과 메타데이터" 안이라 §15.3 결정 변경은 필요 없다고 판단한다(다르게 보면 Task 3 전에 문안 제안).
  - A: 로그만(채택 안 함).
  - C: 결과 스키마에 필드 추가 — API 변경이라 제외.
- **D2 thermalState 읽기:** Worker 프로세스 안에서 ObjC 런타임을 불러 네이티브 호출을 하지 않는다(잘못되면 Worker가 죽고 큐가 멈춘다). 짧은 별도 프로세스(`sys.executable -I -c`)에서 ctypes로 `NSProcessInfo.processInfo.thermalState`를 읽는다. 실측 20~90ms, 작업당 6회. 실패·시간 초과·macOS 아님 → `None`.
- **D3 MotionPhys 장치:** 실행기가 `"cpu"`를 보고한다. 근거: `research/motionphys/faces.py`의 두 `BaseOptions`가 delegate를 지정하지 않고, MediaPipe 1.2.3 `base_options.py`(103~104행)는 delegate가 없으면 CPU를 쓴다. OpenCV 광학 흐름·LightGBM도 CPU다. 이 근거가 깨지면(delegate 지정) 테스트가 실패하게 고정한다.
- Gate 실행기는 요청 범위 밖이라 기록하지 않는다.

## Global Constraints

- API 필드와 상태 값(`job_status`, `analysis_status`, `verdict_status`, `axes.*.status`)은 바꾸지 않는다. API 응답 JSON의 키 집합이 그대로여야 한다.
- 로그에 인증값·영상 내용·얼굴 이미지·민감한 URL 쿼리 출력 금지(docs/DESIGN.md §12.2). 새 로그 줄에는 analysis_id, 축 이름, 장치 이름, 열 상태 이름만.
- 서브프로세스는 인자 리스트로 실행한다. 셸 문자열을 이어 붙이지 않는다.
- 한 축이 실패해도 나머지 축은 계속 처리한다. 기록 실패(프로브·DB)가 작업을 실패시키지 않는다.
- 큐 신뢰성(원자적 선점, lease/heartbeat, 재시작 복구, 중복 실행 방지, 취소·타임아웃)을 약하게 하지 않는다.
- 서버 환경은 표준 라이브러리만(trinity에 의존성 추가 없음). `.cuda()` 없음.
- 장치 값은 `"cpu"`, `"mps"`, `"gpu"`만 기록하고 그 밖은 `None`. 열 상태는 `"nominal"`, `"fair"`, `"serious"`, `"critical"`(ProcessInfo 0~3)만, 그 밖은 `None`. 로그에서 `None`은 `unknown`.

## Review Focus

1. 프로브가 실패·지연(macOS 아님, ctypes 오류, 2초 초과, 이상한 출력) → `None`, 예외가 Worker로 새지 않고 작업은 그대로 진행 (Task 1 테스트).
2. 실행기가 이상한 장치 값을 냄(`"cuda"`, 경로 문자열, 숫자, 누락) → `None`으로 바뀌고 원문은 로그·DB에 남지 않음 (Task 2 테스트).
3. 축 실행 중 취소·작업 timeout·lease 상실 → 그 축의 로그 줄과 기록은 남고, lease를 잃은 Worker는 기록을 덮어쓰지 못함 (Task 3·4 테스트).
4. 열이 없는 기존 DB → `init_schema`가 열을 더하고 기존 행은 그대로, API 응답 키는 그대로 (Task 3 테스트).
5. SIGKILL 뒤 재시도 → 1차 시도 기록은 그대로 남고 2차 시도 기록이 따로 쌓임. 같은 시도 안에서는 축이 끝날 때마다 그 시도 항목만 갱신 (Task 3·4 테스트).

---

### Task 1: thermalState 프로브

**Files:**
- Create: `server/jobs/device_state.py`
- Modify: `tests/conftest.py` (autouse 픽스처 추가)
- Test: `tests/test_device_state.py`

**Interfaces:**
- Produces: `thermal_state(timeout: float = 2.0) -> Optional[str]`, 상수 `THERMAL_NAMES = ("nominal", "fair", "serious", "critical")`, `_PROBE: str`(자식 프로세스 코드).

- [ ] **Step 1: 실패하는 테스트**

```python
def test_maps_probe_output_to_names(monkeypatch):      # 자식 출력 "0".."3" → THERMAL_NAMES, "7"·"x"·"" → None
def test_probe_failure_or_timeout_is_none(monkeypatch):  # subprocess.run이 TimeoutExpired/OSError/returncode 1 → None
def test_non_darwin_is_none_without_spawning(monkeypatch):  # sys.platform="linux"이면 subprocess.run을 부르지 않음
def test_probe_runs_isolated_with_arg_list(monkeypatch):  # 인자 [sys.executable, "-I", "-c", _PROBE], shell 없음, timeout 전달
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS 전용")
def test_real_probe_returns_a_name():                   # 실제 호출 결과 in THERMAL_NAMES
```

- [ ] **Step 2:** `pytest -q tests/test_device_state.py` → 모듈 없음으로 FAIL
- [ ] **Step 3:** `thermal_state` 구현. `_PROBE`는 아래 그대로(arm64에서 `objc_msgSend`는 고정 인자 원형으로 불러야 한다):

```python
_PROBE = (
    "import ctypes, ctypes.util\n"
    "o = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))\n"
    "ctypes.cdll.LoadLibrary(ctypes.util.find_library('Foundation'))\n"
    "o.objc_getClass.restype = ctypes.c_void_p; o.objc_getClass.argtypes = [ctypes.c_char_p]\n"
    "o.sel_registerName.restype = ctypes.c_void_p; o.sel_registerName.argtypes = [ctypes.c_char_p]\n"
    "obj = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', o))\n"
    "num = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', o))\n"
    "info = obj(o.objc_getClass(b'NSProcessInfo'), o.sel_registerName(b'processInfo'))\n"
    "print(num(info, o.sel_registerName(b'thermalState')))\n"
)
```

- [ ] **Step 4:** `tests/conftest.py`에 autouse 픽스처 `_no_real_thermal_probe`: `monkeypatch.setattr("server.jobs.worker.thermal_state", lambda: None)` (Task 4에서 worker가 이 이름을 import한다. 그 전에는 `raising=False`). Worker 테스트마다 자식 프로세스 6개가 뜨지 않게 한다. `test_device_state.py`는 `server.jobs.device_state.thermal_state`를 직접 부르므로 영향 없음.
- [ ] **Step 5:** `pytest -q tests/test_device_state.py` → PASS(실제 프로브 포함 5개)
- [ ] **Step 6:** 커밋 `feat(worker): thermalState를 별도 프로세스로 읽는 프로브`

### Task 2: 축별 device_used 전달

**Files:**
- Modify: `server/axes/__init__.py` (`AxisContext.device_used: Optional[str] = None`)
- Modify: `server/axes/signal/__init__.py`, `server/axes/alignment/__init__.py`, `server/axes/physics/__init__.py`, `server/axes/physics/motionphys.py` (`parse_result`)
- Modify: `research/motionphys/infer_axis.py` (`run()` 출력 최상위 `"device_used": "cpu"`, 근거 주석)
- Create: `server/axes/device.py` — `clean_device(value: object) -> Optional[str]` (`"cpu"`/`"mps"`/`"gpu"`만)
- Test: `tests/test_axis_device_used.py`; 기존 실제 미디어 MotionPhys 테스트에 단언 1줄

**Interfaces:**
- Consumes: 실행기 출력 — WaveRep `out["model"]["device_used"]`, SyncNet 어댑터 반환 `raw["device_used"]`, MotionPhys 실행기 최상위 `device_used`.
- Produces: 각 축 `run(ctx)`가 실행기를 부른 경우 `ctx.device_used = clean_device(...)`. 실행기를 부르지 않은 경로(구간 없음, 개발용 수동 구간의 SyncNet, 시작 전 timeout 등)는 `None`. `motionphys.parse_result(...)` 반환에 `device_used` 키.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_clean_device_accepts_only_known_names():   # "cpu","mps","gpu" 그대로; "cuda","/tmp/x",1,None,"MPS " → None
def test_signal_axis_sets_device_from_runner(monkeypatch):     # 가짜 run_waverep 반환 model.device_used="mps" → ctx.device_used=="mps"
def test_alignment_axis_sets_device_from_runner(monkeypatch):  # 가짜 run_syncnet 반환 device_used="cpu" → "cpu"; "cuda" → None
def test_physics_axis_sets_device_from_runner(monkeypatch):    # 가짜 run_motionphys 반환 device_used="cpu" → "cpu"
def test_axes_without_runner_leave_device_none():   # 구간 없음 → 세 축 모두 None; dev_manual_segments면 alignment None
def test_motionphys_parse_passes_only_clean_device():  # parse_result(raw with device_used="cpu") → "cpu"; "x" → None; 누락 → None
def test_motionphys_runner_reports_cpu_and_mediapipe_uses_default_delegate():
    # ast로 research/motionphys/*.py의 모든 BaseOptions(...) 호출에 delegate 키워드가 없음을,
    # infer_axis.run이 만드는 dict에 "device_used": "cpu"가 있음을 확인(실행기 venv 없이 돈다)
def test_axis_api_payload_has_no_device_key():      # 세 축 run() 반환 dict에 "device_used" 키 없음(API 모델 필드 그대로)
```

기존 실제 영상 MotionPhys 테스트(`tests/test_motionphys_adapter.py`, venv·샘플 있을 때만)에 `assert result["device_used"] == "cpu"`.

- [ ] **Step 2:** `pytest -q tests/test_axis_device_used.py` → FAIL
- [ ] **Step 3:** 구현. 축 `run()`은 반환 dict를 바꾸지 않고 `ctx.device_used`만 쓴다.
- [ ] **Step 4:** `pytest -q tests/test_axis_device_used.py tests/test_motionphys_adapter.py tests/test_syncnet_worker.py tests/test_waverep_worker.py` → PASS
- [ ] **Step 5:** 커밋 `feat(axes): 실행기의 device_used를 내부 문맥으로 전달`

### Task 3: jobs 내부 열 `run_info_json`(시도별 누적)

**Files:**
- Modify: `server/jobs/queue.py` (`_SCHEMA`, `init_schema`, `claim`, 새 메서드)
- Test: `tests/test_run_info_record.py`

**Interfaces:**
- Produces: `JobQueue.save_run_info(analysis_id: str, worker_id: str, attempt: int, axes: dict[str, dict[str, Optional[str]]]) -> bool` — 한 트랜잭션에서 `lease_owner = worker_id AND job_status = 'processing'`일 때만, 기존 기록의 같은 `attempt` 항목을 `axes`로 바꾸거나 새로 더하고 쓴 경우 `True`. 형식 `{"attempts": [{"attempt": 1, "axes": {축: {"device_used", "thermal_state_start", "thermal_state_end"}}}, ...]}`(attempt 오름차순). 기존 값을 읽을 수 없으면 새 목록으로 시작한다.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_init_schema_adds_column_to_old_db(tmp_path):     # 열 없는 옛 스키마로 행 1개 → init_schema → 열 있음, 행 값 그대로
def test_save_requires_lease_owner(queue):                 # 다른 worker_id·종료된 작업 → False, 값 그대로
def test_records_accumulate_per_attempt(queue):           # 1차 기록 → lease 만료 → 재선점 → 2차 기록: attempts == [1차 그대로, 2차]
def test_same_attempt_entry_is_replaced_not_duplicated(queue):  # 같은 attempt로 두 번 저장 → 항목 1개, 나중 axes
def test_api_responses_never_include_run_info(client, queue):
    # 기록이 있는 finished 작업의 GET /analyses/{id}, /result 응답 키 집합이 기존과 같고
    # 본문 문자열에 "run_info", "thermal", "device_used"가 없음
```

- [ ] **Step 2:** `pytest -q tests/test_run_info_record.py` → FAIL
- [ ] **Step 3:** 구현. `init_schema`는 `PRAGMA table_info(jobs)`에 열이 없을 때만 `ALTER TABLE jobs ADD COLUMN run_info_json TEXT`. `claim`은 기록을 건드리지 않는다. `_to_job`·API는 바꾸지 않는다.
- [ ] **Step 4:** `pytest -q tests/test_run_info_record.py tests/test_job_lifecycle.py tests/test_api.py` → PASS
- [ ] **Step 5:** 커밋 `feat(queue): API가 읽지 않는 작업 실행 기록 열`

### Task 4: Worker 로그 한 줄과 기록

**Files:**
- Modify: `server/jobs/worker.py` (`from server.jobs.device_state import thermal_state`; 축 반복문)
- Test: `tests/test_worker_device_log.py`

**Interfaces:**
- Consumes: Task 1 `thermal_state()`, Task 2 `ctx.device_used`, Task 3 `queue.save_run_info(...)`.
- Produces: 축마다 로그 한 줄(logger `trinity.worker`, INFO): `job <analysis_id> axis <signal|physics|alignment> device=<값|unknown> thermal_start=<값|unknown> thermal_end=<값|unknown>`.

- [ ] **Step 1: 실패하는 테스트** (가짜 축·가짜 프로브 순서열, caplog)

```python
def test_logs_one_line_per_axis_with_device_and_thermal(...):
    # 프로브 순서 nominal,fair / fair,fair / fair,serious, 장치 mps/cpu/mps → 세 줄이 정확히 이 순서·값
def test_unknown_when_probe_or_device_missing(...):       # 프로브 None·장치 None → "unknown"
def test_record_saved_after_each_axis_with_attempt(...):  # 작업 끝 run_info_json == {"attempts": [{"attempt": 1, "axes": {세 축}}]}
def test_cancel_during_axis_still_logs_and_records_that_axis(...):  # alignment 실행 중 취소 → cancelled, 앞 두 축과 alignment 줄·기록 있음
def test_probe_or_record_failure_does_not_fail_job(...):  # 프로브 예외, save_run_info가 sqlite3.Error → 작업 finished, 축 결과 그대로
def test_log_line_has_no_url_or_token(...):               # 새 줄들에 요청 URL·토큰·미디어 경로 문자열이 없음
```

- [ ] **Step 2:** `pytest -q tests/test_worker_device_log.py` → FAIL
- [ ] **Step 3:** 구현. 시도 번호는 `job.attempts`. 축마다 `ctx.device_used = None` → `start = thermal_state()` → `run_axis(...)` → `end = thermal_state()` → 로그 → `save_run_info`를 **`interrupted` 확인 전에** 한다. 프로브·기록은 `try/except Exception`으로 감싸 실패해도 지나간다(기록 실패는 경고 로그 한 줄, 내용 없이).
- [ ] **Step 4:** `pytest -q` 전체 → PASS(기존 테스트 수 + 새 테스트, 건너뜀은 LightGBM 없음 1개)
- [ ] **Step 5:** 커밋 `feat(worker): 축별 장치와 열 상태를 로그와 내부 기록에 남김`

### Task 5: 실제 확인과 문서

**Files:**
- Modify: `docs/syncnet-adapter.md`("제안 3"에 구현됨 표시), `docs/HANDOFF.md`(새 절)

- [ ] **Step 1:** 실제 A로 Worker 1회(`scripts/verify_real_worker_lifecycle.py`와 같은 임시 레지스트리·DB, 기본 설정). 확인: 로그 세 줄(WaveRep `mps`, MotionPhys `cpu`, SyncNet `mps`, 열 상태 이름), DB `run_info_json` 같은 값, `GET /result` 키 집합이 기존과 같음, 작업 폴더·프로세스 남지 않음. 임시 자료 삭제.
- [ ] **Step 2:** `TRINITY_SYNCNET_DEVICE=cpu`로 1회 더 → SyncNet 줄이 `device=cpu`.
- [ ] **Step 3:** 문서 갱신(로그 형식, `run_info_json` 형식과 읽는 SQL 예시, 프로브 방식·비용, MotionPhys `cpu` 근거, 실제 확인 결과). `pytest -q` 결과 기록.
- [ ] **Step 4:** 커밋 `docs: Worker 장치·열 상태 기록`, push, PR(merge는 사용자 지시 후).
