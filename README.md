# TRINITY

> 사람이 나와서 말하는 영상이 AI로 생성·조작됐는지 판독하는 앱 (졸업작품)
>
> README v5.1 · 3축 재설계 · 학습·평가 데이터 확정(접근 신청 중) · 구현 전 검증 단계
>
> **v5.1 변경:** 학습·평가 데이터셋 확정(§6.1) · 평가에서 가짜 영상의 YouTube 업로드 제거(§6.3) · (a) 유형에 영상+음성 동시 생성 포함, 소량 자체 생성(§6.1) · 축3의 립싱크 취약성 반영(§4 ④)

---

## 목차

1. [문제 정의](#1-문제-정의)
2. [시스템 개요](#2-시스템-개요)
3. [판독 파이프라인](#3-판독-파이프라인)
4. [왜 3축인가](#4-왜-3축인가)
5. [각 축 상세](#5-각-축-상세)
6. [학습 데이터와 데이터 위생](#6-학습-데이터와-데이터-위생)
7. [앱 (Flutter)](#7-앱-flutter)
8. [API (초안)](#8-api-초안)
9. [레포 구조 (초안)](#9-레포-구조-초안)
10. [실행 방법](#10-실행-방법)
11. [진행 현황과 검증 계획](#11-진행-현황과-검증-계획)
12. [한계](#12-한계)
13. [로드맵](#13-로드맵)
14. [참고문헌](#14-참고문헌)

---

## 1. 문제 정의

TRINITY는 **"사람이 속는 문제"**에서 출발했습니다. 동물이나 풍경이 가짜여도 사람이 그것 때문에 속을 이유는 크지 않습니다. 실제 피해는 **사람이 나와서 말하는 영상**이 가짜일 때 생깁니다.

**탐지 대상:** YouTube 영상 중 사람이 등장해 말하는 구간

**위조 유형:**

| 유형 | 설명 | 예 |
|---|---|---|
| (a) 인물 전체 생성 | 인물과 음성을 AI가 처음부터 생성 | 영상+음성 동시 생성 모델(Veo·Sora류), AI 아바타, 사진 한 장 기반 토킹헤드 |
| (b) 음성 교체 + 립싱크 | 실제 인물 영상에 합성 음성을 넣고 입 모양을 맞춤 | TTS + 립싱크 모델 |
| (c) 얼굴 교체 | 실제 음성은 두고 얼굴만 교체 | face swap |

**범위 밖:** 사람이나 음성이 없는 영상(“분석 대상 아님”으로 응답), 이미지, YouTube 외 플랫폼

---

## 2. 시스템 개요

**Thin Client, Fat Server** 구조입니다.

| 구성 | 내용 |
|---|---|
| 클라이언트 | Flutter 단일 코드베이스로 iOS · Android · Web 지원 |
| 입력 | 모바일: YouTube 앱 공유 시트로 링크 전달 / 웹: URL 붙여넣기 |
| 서버 | FastAPI, 맥북 셀프호스팅 (데모 시 ngrok 터널링) |
| 판단 주체 | 서버 AI 분석만 사용 (커뮤니티 투표 없음) |
| 결과 | 종합 점수 + 축별 점수 + 판단 근거 + 의심 구간 |

---

## 3. 판독 파이프라인

### 3.1 실행 단계 (영상 1개 판독)

```mermaid
flowchart TD
    A["YouTube URL 입력"] --> B["yt-dlp 다운로드<br/>영상 + 음성 + 화질 정보"]
    B --> C{"대상 확인<br/>얼굴 검출 + 음성 구간"}
    C -- 없음 --> X["분석 대상 아님"]
    C -- 있음 --> D["말하는 구간 추출"]
    D --> E1["축1 · WaveRep<br/>프레임 주파수 흔적"]
    D --> E2["축2 · MotionPhys<br/>궤적 물리 통계"]
    D --> E3["축3 · AVH-Align<br/>소리-입 정합"]
    E1 --> F["점수 결합"]
    E2 --> F
    E3 --> F
    F --> G["판독 결과<br/>점수 + 근거 + 의심 구간"]
```

| 단계 | 하는 일 | 도구 |
|---|---|---|
| 다운로드 | 재인코딩된 영상·음성과 해상도·비트레이트 확보 | yt-dlp, ffprobe |
| 대상 확인 | 말하는 사람이 없으면 점수를 내지 않고 종료 | 얼굴 검출, 음성 구간 검출(VAD) — 모델 미정 |
| 구간 추출 | 말하는 구간만 짧은 클립으로 분할 | ffmpeg |
| 3축 판독 | 축별 점수와 근거 산출 | §5 참고 |
| 점수 결합 | 축 점수를 종합 점수로 결합 | 방식 미정 (§5.4) |

> “분석 대상 아님”을 따로 두는 이유: 풍경 영상에 낮은 점수를 주면 사용자가 “진짜로 판정됐다”고 오해할 수 있기 때문입니다.

### 3.2 학습 단계

```mermaid
flowchart TD
    S1["학습 데이터<br/>DeepSpeak · TalkingHeadBench · 자체 생성(a)"] --> EM["열화 에뮬레이터<br/>YouTube식 압축·리사이즈"]
    S2["파라미터 추정<br/>직접 촬영한 진짜 영상만 업로드"] --> EM
    EM --> DS["열화된 데이터셋<br/>학습용 + 평가용"]
    DS --> T1["축1 학습<br/>WaveRep 증강"]
    DS --> T2["축2 학습<br/>궤적 특징 + LightGBM"]
    DS --> T3["축3 학습<br/>진짜 영상만 사용"]
```

실제 입력은 YouTube가 재인코딩한 영상이므로, 학습 데이터에도 같은 열화를 입혀 학습 조건을 실전과 맞춥니다. 평가는 학습과 다른 조건으로 따로 구성합니다(§6.3).

---

## 4. 왜 3축인가

### ① 출발점: 저수준 / 고수준 이분법

패시브(콘텐츠 기반) 탐지는 크게 두 계층으로 나뉩니다. 딥페이크 이미지 탐지 종합 리뷰(ScienceDirect, 2026.3)는 공간·주파수 단서(저수준)와 의미·생리학 단서(고수준)로 분류하고, [TriDF](https://arxiv.org/abs/2512.10652)도 Quality Artifacts와 Semantic Artifacts로 같은 경계를 긋습니다. 경계의 조작적 정의는 [Alpha Blending Hypothesis](https://arxiv.org/abs/2605.10334)를 따릅니다. 저수준 아티팩트는 영상 내용과 무관하게 생기고, 고수준 오류는 장면 내용을 봐야 드러납니다.

| | 저수준 | 고수준 |
|---|---|---|
| 무엇의 흔적인가 | 생성·처리 과정 | 묘사된 세계의 규칙 위반 |
| 내용과의 관계 | 무엇을 찍었든 발생 | 장면 속 내용이 있어야 드러남 |

### ② 고수준을 둘로 나누는 기준: 증거가 어디에 있는가

- **영상 안의 시간 흐름:** 움직임이 물리 법칙(관성, 연속적인 힘)을 따르는가. 영상만으로 판단합니다.
- **영상과 소리 사이:** 입 모양과 발화가 맞물리는가. 영상과 음성을 함께 봐야 판단할 수 있습니다.

두 단서는 입력이 다르고 잡아내는 위조 유형도 다릅니다. 하나의 축으로 합치면 한쪽이 다른 쪽을 대신할 수 없는 영역이 생깁니다.

### ③ 결과: 3축

| 축 | 계층 | 증거 위치 | 방법 | 보는 것 |
|---|---|---|---|---|
| 축1 신호 | 저수준 | 프레임 내부 | WaveRep | 압축 후에도 남는 생성기 주파수 흔적 |
| 축2 물리 | 고수준 | 시간 흐름 | MotionPhys | 궤적의 곡률 · 각속도 · jerk |
| 축3 정합 | 고수준 | 영상 ↔ 음성 | AVH-Align | 입 모양과 발화의 정렬 |

축2는 물체가 무엇인지 인식하지 않지만, 판단 근거가 “장면 속 물체가 어떻게 움직였는가”라는 내용 자체에 있습니다. 내용과 무관하게 생기는 흔적이 아니므로 고수준으로 분류합니다.

### ④ 왜 2축이 아닌가

대상이 “말하는 사람 영상”이면 위조는 세 유형(§1)이고, 고수준 축 하나로는 모두 덮을 수 없습니다. 아래 역할 분담은 **설계 가설**이며 §11의 실험으로 검증합니다.

| 위조 유형 | 축1 | 축2 | 축3 |
|---|---|---|---|
| (a) 인물 전체 생성 | 주력 | 주력 | 검증 필요 |
| (b) 음성 교체 + 립싱크 | 보조 | 검증 필요 | 주력¹ |
| (c) 얼굴 교체, 음성은 진짜 | 주력 | 보조 | 약함 |

축3만 있으면 진짜 음성을 쓴 얼굴 교체(c)를 놓치고, 축2만 있으면 음성 조작(b)을 볼 수 없습니다.

¹ 오디오-영상 정렬 방식은 학습에 없던 데이터로 옮겨 갔을 때 가장 강하지만, 고도화된 립싱크 최적화에는 유독 취약하다는 보고가 있습니다([TFDBench](https://neurips.cc/virtual/2026/163771), NeurIPS 2026). 최신 립싱크 생성기로 만든 (b) 유형에서 따로 검증합니다(§11).

### ⑤ 왜 4축이 아닌가

언어 모델이 장면을 서술하며 추론하는 계열은 계산 비용이 커서 셀프호스팅 서버에 맞지 않고, 판단 근거가 모델의 서술에 의존해 검증하기 어렵습니다. 향후 과제로 둡니다(§13). 출처증명(액티브)은 패시브 3축과 성격이 달라 별도 계층으로 다룹니다.

---

## 5. 각 축 상세

### 5.1 축1 · 신호 — WaveRep

| 항목 | 내용 |
|---|---|
| 근거 논문 | Corvi et al., [*Seeing What Matters*](https://arxiv.org/abs/2506.16802) (arXiv:2506.16802) |
| 입력 | 말하는 구간에서 추출한 프레임 |
| 방법 | 프레임 단위 탐지기(논문 기준 DINOv2) + 학습 시 포렌식 증강 — 진짜 영상을 오토인코더로 재구성한 가짜 추가, 웨이블릿 대역 중 기저·가로·세로 대역을 진짜 영상 것으로 교체(대각선 중~고주파 대역은 유지) |
| 출력 | 구간별 점수 |
| 결정 필요 | 공개 코드 fine-tune vs 직접 학습 (라이선스·학습 자원 확인 필요) |
| 주의 | 강한 압축(H.264 CRF 32)에서 성능 저하 보고. 다른 벤치마크(AIGVDBench, [TRACE 논문](https://arxiv.org/abs/2609.25775)의 재현 결과)에서 무작위 수준 결과가 보고되어 원인 확인 필요 |

### 5.2 축2 · 물리 — MotionPhys

| 항목 | 내용 |
|---|---|
| 근거 논문 | He et al., [*MotionPhys*](https://arxiv.org/abs/2608.20770) (arXiv:2608.20770) |
| 입력 | 말하는 구간 클립 |
| 방법 | Shi-Tomasi 코너 + 격자점 → 피라미드 Lucas-Kanade 추적 → 8·12·24프레임 스케일 궤적 → 곡률·각속도·jerk 통계 504차원 → LightGBM |
| 출력 | 클립별 점수 + 이상이 큰 특징군(곡률/각속도/jerk) |
| 장점 | 가벼움(대형 영상 모델 불필요), 물리량 기반이라 근거 설명이 쉬움 |
| 주의 | 논문은 압축 실험 없음. 움직임이 적은 토킹헤드 영상에서의 성능은 검증 필요 |

### 5.3 축3 · 정합 — AVH-Align

| 항목 | 내용 |
|---|---|
| 근거 논문 | Smeu et al., [*Circumventing Shortcuts in Audio-visual Deepfake Detection Datasets with Unsupervised Learning*](https://arxiv.org/abs/2412.00175), CVPR 2025 ([CVPR 페이지](https://openaccess.thecvf.com/content/CVPR2025/html/Smeu_Circumventing_Shortcuts_in_Audio-visual_Deepfake_Detection_Datasets_with_Unsupervised_Learning_CVPR_2025_paper.html), [코드](https://github.com/bit-ml/AVH-Align)) |
| 입력 | 입 영역 crop + 음성 |
| 방법 | AV-HuBERT 특징 위에서 프레임 단위 오디오-영상 정렬 점수 학습. **진짜 영상만으로 학습** |
| 출력 | 시간축 정렬 점수 → 의심 구간 |
| 장점 | 특정 생성기의 가짜 데이터 불필요, 데이터셋 지름길(앞부분 무음 등)에 덜 의존 |
| 주의 | 영상과 음성을 함께 생성한 (a) 유형에서의 성능, YouTube 오디오 재인코딩 내성, AV-HuBERT 라이선스·추론 속도 확인 필요 |

### 5.4 점수 결합

- 방식 미정. 후보: 축별 로짓을 이어 붙인 선형 결합
- 화질(해상도·비트레이트)이 낮을수록 축1 가중치를 낮추는 방식 검토(제안 단계)
- 종합 점수와 별개로 **축별 점수를 항상 함께 표시**해 근거를 추적할 수 있게 함

---

## 6. 학습 데이터와 데이터 위생

### 6.1 데이터셋

| 용도 | 데이터 | 다루는 유형 | 접근 | 상태 |
|---|---|---|---|---|
| 주 학습 | [DeepSpeak v2](https://huggingface.co/datasets/faridlab/deepspeak_v2) — 동의한 참여자의 웹캠 토킹헤드 영상, 진짜 + 가짜(얼굴 교체·립싱크·아바타) | (a) 아바타 · (b) · (c) · 진짜 | 외부 양식 작성 후 Hugging Face 조건 동의 | 신청 예정 |
| (a) 보강 | [TalkingHeadBench](https://arxiv.org/abs/2505.24866) — 사진 한 장을 음성·영상으로 구동한 토킹헤드 | (a) 사진 기반 | 공개 범위·조건 확인 필요 | 확인 필요 |
| (a) 보강 | 자체 생성 — 영상+음성 동시 생성 모델(Veo·Sora류)로 만든 가상 인물 발화 영상 소량(20~50개) | (a) 동시 생성 | 생성 서비스 약관·비용 확인 | 미정 |
| 축3 학습(진짜만) | DeepSpeak의 진짜 영상, 또는 AVH-Align 공개 코드의 사전학습 가중치(제공 여부 확인 필요) | 진짜 | 위와 동일 | — |
| 점수 결합 학습 | DeepSpeak 검증 분할(학습에 쓰지 않은 사람) | 전부 | 위와 동일 | — |
| 실전 평가 | [Deepfake-Eval-2024](https://arxiv.org/abs/2503.02857) — 2024년 SNS에서 실제 유통된 영상 중 말하는 사람 구간만 선별 | 혼합(유형 라벨 여부 확인 필요) | 기관 이메일 + 관련 작업 링크 제출(2027년 5월까지 심사) | 신청 예정 |
| 압축 설정 추정 | 직접 촬영한 진짜 영상만 비공개 업로드(해상도당 50개 미만) | 진짜 | — | 미정 |
| 참조 | [AV-Deepfake1M++](https://arxiv.org/abs/2507.20579) — 진짜 영상의 일부 구간을 조작한 데이터 중심 | (b) 중심 | 연구 전용 EULA | 참조만 |

**도메인 차이 주의:** DeepSpeak은 웹캠 화상회의 환경이라 YouTube의 촬영·편집 환경과 다릅니다. 이 차이는 Deepfake-Eval-2024 평가로 따로 확인합니다(§11).

### 6.2 YouTube 열화 에뮬레이터

Montibeller et al.([arXiv:2508.08765](https://arxiv.org/abs/2508.08765))의 방식을 따릅니다. 영상을 실제로 업로드했다가 다시 받아 플랫폼의 압축·리사이즈 파라미터를 추정하고, 그 값으로 대량의 학습 데이터에 같은 열화를 로컬에서 재현합니다. 원 논문은 해상도당 50개 미만의 업로드로 정확한 재현이 가능하다고 보고합니다.

**업로드에는 직접 촬영한 진짜 영상만 비공개로 사용하고, 데이터셋 영상이나 가짜 영상은 올리지 않습니다.**

### 6.3 평가 설계

학습에 쓴 열화와 **다른 조건**으로 평가합니다([AV-Deepfake1M++](https://arxiv.org/abs/2507.20579)의 학습/테스트 열화 분리 방식 참고). 평가 세트는 세 가지입니다.

1. **실전 유통본:** Deepfake-Eval-2024의 말하는 사람 구간 — 실제 플랫폼 압축을 이미 거친 영상
2. **조건 분리:** DeepSpeak 테스트 분할에, 학습 때 쓰지 않은 에뮬레이터 설정(해상도·비트레이트)을 적용
3. **(a) 동시 생성:** 자체 생성 영상 중 학습에 쓰지 않은 부분

지표: AUC, ACC@5% FPR, 위조 유형(a·b·c)별 성능, 압축 조건별 성능

### 6.4 데이터 위생 (`training/hygiene.py`)

| 점검 항목 | 이유 |
|---|---|
| 사람(ID) 단위로 학습·검증·테스트 분할 | 같은 사람이 학습과 평가에 동시에 나오면 위조 흔적 대신 얼굴을 외우는 지름길이 생김 |
| 앞부분 무음 제거·무작위화 | 기존 오디오-비주얼 데이터셋에서 가짜 영상 앞부분 무음만으로 진짜/가짜가 거의 구분되는 편향이 보고됨([AVH-Align 논문](https://arxiv.org/abs/2412.00175)) |
| 진짜/가짜의 인코딩·해상도·길이 맞추기 | 형식 차이를 탐지 단서로 학습하는 지름길 방지 |
| 같은 내용끼리 짝짓기 | 내용 차이로 구분하는 지름길 방지(WaveRep의 프롬프트 짝짓기 방식) |
| 도메인 편향 점검 | 특정 인물·촬영 환경·언어에 과적합 방지 |

### 6.5 라이선스·약관·윤리

- 이 레포에는 어떤 데이터셋의 영상이나 파생물도 포함하지 않습니다. 데이터 로더와 사람(ID) 분할 목록만 둡니다.
- DeepSpeak: 접근 양식과 이용 조건을 따르고, 사용 시 출처를 표기합니다(정확한 라이선스 조건 확인 필요).
- Deepfake-Eval-2024: 연구 목적 접근 심사를 거치며(2027년 5월까지), 라이선스는 CC-BY-SA-4.0입니다.
- AV-Deepfake1M++: 연구 전용 EULA를 따릅니다.
- 자체 생성 (a): 실존 인물의 얼굴·목소리는 쓰지 않고 가상 인물만 만들며, 생성 서비스 약관을 따르고 공개 게시하지 않습니다.
- YouTube 영상 다운로드는 서비스 약관 허용 범위 확인 필요

---

## 7. 앱 (Flutter)

| 항목 | 내용 |
|---|---|
| 플랫폼 | iOS · Android · Web (단일 코드베이스) |
| 입력 | 모바일: YouTube 공유 시트 / 웹: URL 붙여넣기 (웹은 공유 시트 수신 불가) |
| 네비게이션 | 탭바 없는 스택 네비게이션 |
| 디자인 | Bold Typography 다크 스타일 · 배경 `#0A0A0A` · 액센트 `#FF3D00` · Inter Tight + JetBrains Mono |

**화면 흐름**

```mermaid
flowchart LR
    H["홈"] --> L["분석 중"]
    L --> R["결과 요약"]
    L --> N["분석 대상 아님"]
    R -- 탭 --> E["결과 해설"]
    R --> C["채널 상세"]
```

| 화면 | 내용 |
|---|---|
| 홈 | URL 입력, 최근 분석 |
| 분석 중 | 단계별 진행 상태(다운로드 → 대상 확인 → 3축 판독) |
| 결과 요약 | 종합 점수, 축별 점수 3개, 화질 경고 |
| 결과 해설 | 축별 판단 근거, 의심 구간 타임라인 (요약 화면과 별도 화면) |
| 채널 상세 | 채널 단위 분석 이력 (Phase 2) |

> 웹 빌드에서는 서버에 CORS 설정이 필요합니다.

---

## 8. API (초안)

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/analyze` | `{ "url": "..." }` → 작업 ID 반환 |
| `GET` | `/jobs/{job_id}` | 진행 상태와 결과 조회 |
| `GET` | `/channels/{channel_id}` | 채널 단위 분석 이력 집계 (Phase 2) |

**결과 응답 예시 (초안)**

```json
{
  "status": "done",
  "in_scope": true,
  "overall_score": 0.82,
  "axes": {
    "signal":    { "score": 0.71, "evidence": "..." },
    "physics":   { "score": 0.88, "evidence": "jerk 통계 이상" },
    "alignment": { "score": 0.90, "segments": [[12.4, 14.1]] }
  },
  "quality": { "height": 720, "bitrate_kbps": 1800, "warning": null }
}
```

말하는 사람이 없으면 `"in_scope": false`로 점수 없이 응답합니다.

---

## 9. 레포 구조 (초안)

```
TRINITY/
├── app/                    # Flutter (iOS · Android · Web)
├── server/
│   ├── main.py             # FastAPI 진입점
│   ├── ingest/             # yt-dlp, ffprobe
│   ├── gate/               # 얼굴·음성 확인, 말하는 구간 추출
│   ├── axes/
│   │   ├── signal/         # 축1 WaveRep
│   │   ├── physics/        # 축2 MotionPhys
│   │   └── alignment/      # 축3 AVH-Align
│   └── fusion/             # 점수 결합
├── training/
│   ├── datasets/           # 데이터 로더 · 사람(ID) 단위 분할 목록 (데이터 자체는 미포함)
│   ├── emulator/           # YouTube 열화 에뮬레이터
│   └── hygiene.py          # 데이터 위생 점검
└── docs/
```

---

## 10. 실행 방법

> 구현 진행에 따라 갱신합니다.

**서버**

```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
ngrok http 8000        # 데모 시 외부 접속용
```

**앱**

```bash
cd app
flutter pub get
flutter run -d chrome  # Web
flutter run -d ios     # iOS
flutter run -d android # Android
```

---

## 11. 진행 현황과 검증 계획

| 항목 | 상태 |
|---|---|
| 문제 정의·범위(말하는 사람 영상) | 확정 |
| 3축 구성(WaveRep · MotionPhys · AVH-Align) | 확정 |
| 열화 에뮬레이터 기반 학습 구조 | 확정 |
| 학습·평가 데이터 구성(§6.1) | 확정 · 접근 신청 중 |
| (a) 동시 생성 영상 자체 제작 | 미정 (도구·비용·약관 확인) |
| 위조 유형 (a)(b)(c) 우선순위 | 미정 |
| 점수 결합 방식·가중치 | 미정 |
| 얼굴 검출·VAD 모델 선택 | 미정 |

**구현 전 검증 항목**

1. MotionPhys가 움직임이 적은 토킹헤드 영상에서도 작동하는가
2. WaveRep이 다른 벤치마크에서 무작위 수준이었던 원인은 무엇인가
3. AVH-Align이 영상과 음성을 함께 생성한 인물(a 유형)도 잡는가
4. 에뮬레이터를 재현할 수 있는가, AV-HuBERT 라이선스는 사용 가능한가
5. 오디오-영상 정렬(축3)이 최신 립싱크 생성기로 만든 (b) 유형에서도 버티는가
6. 웹캠 환경 데이터(DeepSpeak)로 학습한 모델이 실제 유통 영상(Deepfake-Eval-2024)에서도 성능을 유지하는가

---

## 12. 한계

- 판독 결과는 확률적 추정이며, 단독으로 진위를 확정하는 근거로 쓰면 안 됩니다.
- 말하는 사람이 없는 영상은 분석하지 않습니다.
- 진짜 음성을 쓴 얼굴 교체(c)는 축3이 약하므로 축1·2에 의존합니다.
- 강한 압축에서는 축1 성능이 떨어질 수 있습니다.
- 축별 성능 수치는 원 논문의 보고치이며, 이 프로젝트의 조건(YouTube 열화, 말하는 사람 영상)에서는 아직 측정 전입니다.
- 주 학습 데이터(DeepSpeak)는 웹캠 화상회의 환경이라 YouTube 촬영·편집 환경과 차이가 있습니다.
- 영상+음성 동시 생성(a) 데이터는 소량 자체 생성에 의존하므로, 이 유형의 성능 추정은 불확실성이 큽니다.

---

## 13. 로드맵

| 단계 | 내용 |
|---|---|
| Phase 1 | 단일 영상 분석 — 대상 확인 + 3축 판독 + 결과·해설 화면 |
| Phase 2 | YouTube 채널 ID 기준 분석 이력 누적·집계 |
| 향후 | 출처 확인 계층(C2PA, 플랫폼 AI 라벨)과 패시브 판독과의 무결성 충돌 처리 |
| 향후 | 시각적 증거(스펙트럼 잔차 히트맵, 구간별 물리 불일치 히트맵) |
| 향후 | 언어 모델 기반 세계 추론 계층 |
| 향후 | YouTube 외 플랫폼 |

---

## 14. 참고문헌

**탐지 축**

- Corvi et al. [*Seeing What Matters: Generalizable AI-generated Video Detection with Forensic-Oriented Augmentation.*](https://arxiv.org/abs/2506.16802) arXiv:2506.16802 (NeurIPS 2025) — 축1 · [코드](https://github.com/grip-unina/WaveRep-SyntheticVideoDetection)
- He et al. [*MotionPhys: Detecting AI-Generated Videos via Physical Consistency of Optical-Flow Trajectories.*](https://arxiv.org/abs/2608.20770) arXiv:2608.20770 — 축2
- Smeu et al. [*Circumventing Shortcuts in Audio-visual Deepfake Detection Datasets with Unsupervised Learning.*](https://arxiv.org/abs/2412.00175) CVPR 2025, arXiv:2412.00175 — 축3 · [CVPR 페이지](https://openaccess.thecvf.com/content/CVPR2025/html/Smeu_Circumventing_Shortcuts_in_Audio-visual_Deepfake_Detection_Datasets_with_Unsupervised_Learning_CVPR_2025_paper.html) · [코드](https://github.com/bit-ml/AVH-Align)

**학습·평가**

- Montibeller et al. [*Bridging the Gap: A Framework for Real-World Video Deepfake Detection via Social Network Compression Emulation.*](https://arxiv.org/abs/2508.08765) arXiv:2508.08765 · [DOI:10.1145/3746265.3759670](https://doi.org/10.1145/3746265.3759670) — 열화 에뮬레이터
- Cai et al. [*AV-Deepfake1M++: A Large-Scale Audio-Visual Deepfake Benchmark with Real-World Perturbations.*](https://arxiv.org/abs/2507.20579) ACM MM 2025, arXiv:2507.20579 — 평가 설계 참고

**데이터셋**

- Barrington, Bohacek, Farid. [*The DeepSpeak Dataset.*](https://arxiv.org/abs/2408.05366) arXiv:2408.05366 — 주 학습 데이터 · [Hugging Face](https://huggingface.co/datasets/faridlab/deepspeak_v2)
- Chandra et al. [*Deepfake-Eval-2024: A Multi-Modal In-the-Wild Benchmark of Deepfakes Circulated in 2024.*](https://arxiv.org/abs/2503.02857) arXiv:2503.02857 — 실전 평가
- [*TalkingHeadBench: A Multi-Modal Benchmark & Analysis of Talking-Head DeepFake Detection.*](https://arxiv.org/abs/2505.24866) arXiv:2505.24866 — (a) 보강
- [*TFDBench: A Comprehensive Benchmark and Codebase for Talking-Face Deepfake Detection.*](https://neurips.cc/virtual/2026/163771) NeurIPS 2026 (arXiv 번호 확인 필요) — 축3 립싱크 취약성 근거

**분류 체계 (§4)**

- [*Alpha Blending Hypothesis.*](https://arxiv.org/abs/2605.10334) arXiv:2605.10334 — 저수준/고수준 경계의 조작적 정의
- [*TriDF.*](https://arxiv.org/abs/2512.10652) arXiv:2512.10652 — Quality Artifacts vs Semantic Artifacts
- [*Countering synthetic realities: Advances, challenges, and future directions in deepfake image detection.*](https://www.sciencedirect.com/science/article/pii/S2772941926000396) ScienceDirect, 2026.3 — 공간·주파수 vs 의미·생리학 분류

**비교·참고**

- Chang et al. [*What Matters in Detecting AI-Generated Videos like Sora?*](https://arxiv.org/abs/2406.19568) arXiv:2406.19568
- Cao et al. [*TRACE: Trajectory Representation and Consistency Estimation for AI-Generated Video Detection.*](https://arxiv.org/abs/2609.25775) arXiv:2609.25775
