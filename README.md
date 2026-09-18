# 🥬 제철밥상 플래너 · AI 비서

> 내가 기록한 **제철 식재료 가격 시계열**을 이해하고, 그 데이터를 근거로 "지금 사도 되는지"까지 판정해 주는 AI 웹 서비스


[참고] file:///C:/Users/yello/Downloads/%EA%B8%B0%EB%8A%A5%EB%AA%85%EC%84%B8%EC%84%9C_%EC%9D%B8%ED%8F%AC%EA%B7%B8%EB%9E%98%ED%94%BD.html

---

## 1. 서비스 소개 — 무엇을 해결하는가

제철 식재료는 **가격 변동 폭이 크고 시기를 놓치면 비싸집니다.** 그런데 일반 ChatGPT에게 "이번 달 장바구니 값이 어때?"라고 물어도 내 기록을 모르니 일반론만 돌아옵니다.

이 서비스는 사용자가 기록한 제철 식재료 장바구니 가격(원/kg) 시계열을 Firestore에 저장하고, 그 **요약과 판정을 GPT의 시스템 프롬프트에 주입**해서 "내 데이터를 아는 비서"를 만듭니다.

```
사용자: "요즘 값이 어때?"
AI:     "최근 7일 평균은 4,807원/kg입니다. 평년보다 4.8% 높지만
         직전 주(5,127원/kg) 대비로는 6.2% 내리는 중이에요.
         지금은 대하·표고버섯·배추가 평균가가 낮으니 그쪽으로 밥상을 짜보세요."
```

### 이 서비스의 핵심 — 축이 두 개인 이유

| 축 | 무엇을 알려주나 | 이것만 보면 |
|---|---|---|
| **전주 대비** (단기) | 지금 오르는 중인가 내리는 중인가 | 이 시기치고 비싼지를 모름 |
| **평년 대비** (장기) | 예년 같은 시기보다 비싼가 | 지금 오르는 중인지를 모름 |

두 축이 있어야 아래 구분이 가능합니다. **축이 하나면 이 판단은 절대 나오지 않습니다.**

```
평년보다 싼데 오르는 중  →  지금 사는 게 낫다
평년보다 싼데 내리는 중  →  조금 더 기다려도 된다
```

### 데이터 정의

| 필드 | 의미 |
|---|---|
| `date` | 측정 날짜 (YYYY-MM-DD) |
| `value` | 그날 '제철 밥상 한 상' 기준 식재료 장바구니의 kg당 평균 소매가 (원) |
| `memo` | 그 시기의 대표 제철 품목 (예: 전어, 밤, 배추) |

**730개** 데이터 포인트 (2024-09-08 ~ 2026-09-07, 2년치).

> 📌 **왜 2년치인가** — "평년 대비"는 *작년 같은 시기*와 비교하는 값입니다. 1년 미만이면 비교 대상 자체가 없습니다. 그래서 자매 프로젝트 `jecheol-planner` 의 `collect --years 2` 기본값과 같은 기준으로 맞췄습니다.

---

## 2. 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 백엔드 | Python 3.14(로컬) / 3.11(배포), FastAPI, Uvicorn, Pydantic v2 |
| 데이터베이스 | Firebase Firestore (`firebase-admin`) |
| AI | OpenAI GPT (`gpt-4o-mini`) + Function Calling |
| 프론트엔드 | HTML / CSS / Vanilla JavaScript (**프레임워크·차트 라이브러리 미사용**) |
| 배포 | 백엔드 → Render / 프론트엔드 → Vercel |
| 보너스 ① | Function Calling 도구 11종 + MCP Server (`mcp` SDK, stdio) |
| 보너스 ② | SVG 차트(직접 구현), 확장 통계 API, CSV/JSON 내보내기, 다크 모드 |

---

## 3. 배포 URL

| 구분 | URL |
|---|---|
| 프론트엔드 | https://jecheol-ai-secretary.vercel.app |
| 백엔드 API | https://seasonal-ai-backend.onrender.com |
| Swagger UI | https://seasonal-ai-backend.onrender.com/docs |
| 소스 저장소 | https://github.com/80gina/jecheol-ai-secretary |

배포일: 2026-09-14 · 백엔드 Render(Blueprint, `render.yaml`) · 프론트엔드 Vercel(Root Directory `frontend`)

서버 상태는 <https://seasonal-ai-backend.onrender.com/health> 에서 한눈에 확인할 수 있습니다.

```json
{"status":"ok","env":"production","db_backend":"firestore",
 "openai_configured":true,
 "allowed_origins":["https://jecheol-ai-secretary.vercel.app"]}
```

> ⚠️ **외부 서비스 사용량 안내**: OpenAI 크레딧이나 Firebase 무료 할당량(하루 읽기 5만 건)이 소진되면 해당 기능이 `429`로 응답합니다. 배포나 인증 문제가 아니며, 화면에는 오류 사유가 그대로 표시됩니다. Firebase 할당량은 매일 태평양시 자정(한국시간 오후 4시경)에 초기화됩니다. 할당량과 무관하게 시연해야 할 때는 Render 환경 변수 `USE_MEMORY_DB`를 `true`로 두면 저장 계층이 `backend/data/seed_data.json` 기반 메모리 DB로 전환되어 외부 호출 없이 동작합니다.

### 실제로 살아 있는지 확인하기 — 실행 검증

주소만 적어두면 "배포했다"는 주장일 뿐입니다. **실제 HTTP 응답을 받아 기록**해 두었습니다.

| 무엇 | 어디에 |
|---|---|
| 프론트·백엔드 접속 응답, `/health` 본문, `/docs` 응답 스니펫, 대표 엔드포인트 6종 왕복 | **[`문서/실행검증.md`](문서/실행검증.md)** |
| 백엔드 OpenAPI 명세 원문 (엔드포인트 전체) | **[`docs/openapi.json`](docs/openapi.json)** |
| 위 두 파일을 만드는 스크립트 | **[`scripts/verify_deploy.ps1`](scripts/verify_deploy.ps1)** |

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_deploy.ps1
```

이 명령 한 줄로 누구든 같은 검증을 다시 돌려 확인할 수 있습니다.
스크린샷과 달리 **텍스트라서 검색되고, 스크립트가 있어 재현됩니다.**

> 💡 **콜드스타트 안내**: Render 무료 티어는 15분간 요청이 없으면 절전 상태가 됩니다. 첫 접속 시 응답까지 **최대 60초**가 걸릴 수 있습니다. 프론트엔드는 페이지 로드 직후 `/health`를 호출해 서버를 미리 깨우고, 2.5초 이상 걸리면 상단에 안내 배너를 띄웁니다.

---

## 4. 프로젝트 구조

```
.
├── 시작하기.ps1                     # 클릭 한 번으로 로컬 실행 (Windows)
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 초기화, CORS, 헬스체크, 자동 시드
│   │   ├── config.py                # 환경 변수 로딩 (키 하드코딩 금지)
│   │   ├── db.py                    # Firestore 연결 + 개발용 메모리 대체 저장소
│   │   ├── models/schemas.py        # Pydantic 요청/응답 스키마
│   │   ├── routers/                 # HTTP 관심사만 담당
│   │   │   ├── data.py              #   /api/data/*
│   │   │   ├── conversations.py     #   /api/conversations/*
│   │   │   ├── chat.py              #   /api/chat, /api/tools
│   │   │   └── recommend.py         #   [보너스②] /api/recommend
│   │   └── services/                # 도메인 로직
│   │       ├── data_service.py      #   Firestore CRUD + TTL 읽기 캐시
│   │       ├── summary_service.py   #   ★ 평년/전주 두 축 + 판정 + 프롬프트 생성
│   │       ├── catalog.py           #   ★ 도메인 지식 — 분류(대·중·소)·제철·민감도
│   │       ├── dishes.py            #   ★ 음식 82종 ↔ 재료 (추천과 대화가 공유)
│   │       ├── mentions.py          #   대화에서 필요한 재료 뽑아내기
│   │       ├── scoring_service.py   #   [보너스②] 여섯 축 평가 + SWOT
│   │       ├── forecast_service.py  #   [보너스②] 향후 추이선 (가정값 반영)
│   │       ├── recommend_service.py #   [보너스②] 조건 → 음식 → 장바구니
│   │       ├── statistics_service.py#   [보너스②] 이동평균·요일별·분포
│   │       ├── alternatives.py      #   [보너스①] 대체 식재료 표 (49품목)
│   │       ├── tools.py             #   [보너스①] 도구 스키마 & 실행기 (11종)
│   │       ├── conversation_service.py
│   │       └── chat_service.py      #   ★ 컨텍스트 주입 + GPT + 도구 호출 루프
│   ├── mcp_server/server.py         # [보너스①] MCP Server (같은 도구를 외부 채널에)
│   ├── scripts/
│   │   ├── generate_data.py         # 품목별 시계열 생성 (--profile 로 규모 선택)
│   │   ├── import_kamis.py          # KAMIS 실측 데이터 → seed_data.json 변환
│   │   └── seed_firestore.py        # Firestore 일괄 업로드
│   ├── smoke_test.py                # Firebase/OpenAI 없이 120개 항목 검증
│   ├── requirements.txt
│   ├── render.yaml
│   └── .env.example
└── frontend/
    ├── index.html                   # 채팅 / 조건 / 장바구니 / 시세판 / 그래프 / 시각화
    ├── style.css                    # 색 토큰 + 다크 모드 3단 정의
    ├── app.js                       # 주고받기 + 시세판 + SVG 차트 + 오류 한국어 매핑
    ├── viz.js                       # 분류 필터 · 조건 추천 · 시각화 4종 · 예측선
    ├── config.js                    # API 주소 (빌드 시 자동 생성)
    ├── build.js                     # 환경 변수 → config.js
    └── vercel.json
```

### 라우터 / 서비스를 나눈 기준

- **라우터**는 HTTP 관심사만 안다 — 경로, 상태 코드, Pydantic 검증, 예외를 HTTP 응답으로 바꾸기.
- **서비스**는 도메인 로직만 안다 — Firestore 접근, 통계 계산, GPT 호출.
- 판별법: **라우터가 `firebase_admin`이나 `openai`를 import 하면 잘못 나뉜 것.**

---

## 5. API 명세

Swagger UI: `/docs` · 전체 25개 엔드포인트

### 데이터

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/data` | 새 데이터 추가 → 201 |
| `GET` | `/api/data` | 목록 조회 (`limit`, `start`, `end` 필터) |
| `GET` | `/api/data/summary` | **요약 + 판정 (프롬프트 주입용)** |
| `GET` | `/api/data/statistics` | [보너스②] 이동평균·요일별·분포 |
| `GET` | `/api/data/export` | [보너스②] CSV / JSON 내보내기 |
| `GET` | `/api/data/{id}` | 단건 조회 |
| `PUT` | `/api/data/{id}` | 수정 |
| `DELETE` | `/api/data/{id}` | 삭제 |
| `POST` | `/api/data/bulk` | 시드 일괄 업로드 |

> ⚠️ **경로 순서 주의** — `/summary`, `/statistics`, `/export` 는 코드상 `/{data_id}` **위에** 선언되어 있습니다. 순서를 바꾸면 FastAPI가 `summary`를 `data_id`로 인식해 404가 됩니다. 스모크 테스트에 이 셋의 순서 검사가 들어 있습니다.

**`GET /api/data/summary` 응답 예시**

```json
{
  "period": "2024-09-08 ~ 2026-09-07",
  "count": 730,
  "metrics": {
    "average": 4624.0,
    "max": 6150.0,
    "min": 3470.0,
    "latest": 4510.0,
    "recent_avg_7d": 4807.1,
    "prev_avg_7d": 5127.1,
    "change_rate_pct": -6.24,
    "normal_avg_7d": 4585.3,
    "vs_normal_pct": 4.85,
    "std_dev": 491.0
  },
  "trend": "하락 (최근 7일 평균 -6.2%)",
  "verdict": "평년 수준",
  "verdict_tone": "mid",
  "verdict_reason": "평년과 비슷합니다. 급하면 사고, 아니면 다음 장을 봐도 손해가 크지 않습니다. 전주 대비로는 -6.2%로 내리는 중입니다.",
  "normal_basis": "2024, 2025, 2026년 자료에서, 최근 7일 각각의 같은 달력 시기 ±7일에 해당하는 다른 해 기록 133건을 평균",
  "peak_date": "2026-02-24",
  "trough_date": "2024-10-18",
  "top_items": [{"item": "대하", "avg": 3893.0, "count": 15}]
}
```

### 대화 기록

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/conversations` | 대화 저장 |
| `GET` | `/api/conversations` | 대화 목록 (**messages 미포함** — 가볍게) |
| `GET` | `/api/conversations/{id}` | 특정 대화의 **전체 messages** (요구사항 6-A) |
| `DELETE` | `/api/conversations/{id}` | 대화 삭제 |

### AI 챗

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/chat` | 데이터 기반 AI 대화 (대화 자동 저장) |
| `GET` | `/api/tools` | [보너스①] GPT에 노출된 도구 스키마 조회 |

---

## 6. 핵심 원리 — 컨텍스트 주입

GPT는 **상태가 없습니다.** 이전에 내 데이터를 보여줬어도 다음 요청에서는 기억하지 못합니다. 그래서 매 요청마다 요약을 `system` 메시지로 **다시** 넣어줍니다.

```
[POST /api/chat]
      │
      ├─ 1. build_summary()          Firestore 전체 조회
      │      ├ 단기 축: 최근 7일 vs 직전 7일        → 전주 대비 %
      │      ├ 장기 축: 최근 7일 vs 같은 시기 평년   → 평년 대비 %
      │      └ 판정  : 평년 대비를 5단계로 자름     → verdict + 이유 문장
      │
      ├─ 2. build_system_prompt()    요약과 판정을 사람이 읽는 문장으로 변환
      │        ↓
      │      "[서버가 내린 판정]  ※ 아래 판정과 이유를 그대로 근거로 쓰세요
      │       - 판정: 평년 수준
      │       - 이유: 평년과 비슷합니다. ... 전주 대비로는 -6.2%로 내리는 중입니다."
      │
      ├─ 3. GPT 호출                 [system: 요약+판정] + [최근 8턴] + [user: 질문]
      │        └ 필요하면 도구 호출 (최대 3라운드)
      │
      └─ 4. conversations 컬렉션에 자동 저장
```

### 컨텍스트 주입의 장점과 단점 — 무엇을 주고 무엇을 포기했나

주입은 공짜가 아닙니다. 얻는 것과 잃는 것을 나란히 적습니다.

| | 내용 |
|---|---|
| **장점 1 — 답이 데이터에 묶인다** | GPT가 아는 일반 상식이 아니라 **이 서비스에 저장된 값**으로 답합니다. "배추가 비싸대요" 같은 출처 불명의 문장이 나오지 않습니다 |
| **장점 2 — 매 요청이 독립적이다** | GPT는 상태가 없으므로 세션이 끊겨도, 서버가 재시작돼도 같은 답이 나옵니다. 대화 순서에 따라 답이 달라지는 일이 없습니다 |
| **장점 3 — 판정이 일관된다** | 5단계 판정을 서버가 결정적으로 내리므로, 같은 데이터면 **항상 같은 판정**입니다 |

| | 내용 | 이 서비스의 대응 |
|---|---|---|
| **단점 1 — 프롬프트가 매 요청 길어진다** | 요약·판정·도구 스키마 11종이 **모든 요청에** 다시 실립니다. 도구 호출이 일어나면 GPT를 2회 부르므로 그만큼 또 실립니다 | 원본 레코드는 **한 건도 넣지 않고 요약 문장만** 넣습니다. 데이터가 19,710건에서 열 배가 되어도 프롬프트 길이는 거의 그대로입니다. 대화 기록은 최근 **8턴**만(`HISTORY_TURNS`), 응답은 **600토큰**까지(`OPENAI_MAX_TOKENS`) |
| **단점 2 — 넣은 것은 외부로 나간다** | 프롬프트에 담긴 내용은 OpenAI 서버로 전송됩니다. 민감정보를 요약에 담으면 그대로 나갑니다 | 요약에는 **집계값만** 담습니다 — 평균가·증감률·판정·품목명. 개인 식별정보, 인증키, 서비스 계정 자격증명은 **요약 생성 경로에 들어가지 않습니다**(`summary_service.build_summary` 는 가격 컬렉션만 읽습니다). 키는 전부 환경 변수이며 프롬프트에 실리지 않습니다 |
| **단점 3 — 요약이 틀리면 전부 틀린다** | GPT는 주입된 요약을 의심하지 않습니다. 요약 계산이 틀리면 **그럴듯한 문장으로 포장된 오답**이 나옵니다 | 판정 경계값(`VERDICT_BANDS`)과 요약 계산을 스모크 테스트에서 검사합니다. 요약 API(`/api/data/summary`)를 **따로 열어 둔 것도** 사람이 눈으로 대조할 수 있게 하려는 것입니다 |
| **단점 4 — 최신성은 조회 시점에 묶인다** | 요약은 요청 순간의 Firestore 상태입니다. 대화 중에 데이터가 바뀌어도 이미 보낸 프롬프트는 갱신되지 않습니다 | 요약을 **매 요청마다 다시 계산**합니다(캐시하지 않음). 대화 도중의 변경은 다음 질문부터 반영됩니다 |

**요약하면** — 컨텍스트 주입은 *정확성*을 사고 *토큰*과 *전송 범위*를 지불하는 거래입니다. 이 서비스는 **원본 대신 요약만 보내는 방식**으로 토큰을 줄이고, **집계값만 담는 방식**으로 전송 범위를 좁혔습니다.

### 판정을 GPT가 아니라 서버가 내리는 이유

GPT에게 "평균 4,624원"이라는 **날숫자만** 주면 "비싼 편이네요" 같은 근거 없는 말을 지어냅니다. 판정은 **결정적(deterministic)으로 서버가** 내리고, GPT는 그 문장에 말투만 입히게 하면 틀릴 구멍이 막힙니다.

판정 밴드는 `summary_service.VERDICT_BANDS` 한 곳에만 정의되어 있고, 프롬프트·프론트·문서가 모두 이 값을 씁니다.

| 평년 대비 | 판정 |
|---|---|
| ≤ −12% | 지금 사세요 |
| ≤ −4% | 사도 좋습니다 |
| < +5% | 평년 수준 |
| < +12% | 조금 비쌉니다 |
| ≥ +12% | 미루는 편이 낫습니다 |

### 평년은 어떻게 계산하나

> 평년값 = **같은 달력 시기(월-일 기준 ±7일)의 '다른 해' 값들의 평균**

같은 해의 값은 제외합니다 — 자기 자신과 비교하면 항상 0%가 나오기 때문입니다. 이 계산 근거는 응답의 `normal_basis` 필드로 **화면에도 그대로 표시**됩니다.

### Pydantic 검증을 넣은 이유

Firestore는 스키마가 없는 NoSQL이라 `value: "비쌈"` 같은 값도 그대로 저장됩니다. 잘못된 값이 DB까지 내려가면 요약 계산이 통째로 깨집니다. 그래서 **앱 경계에서** 막습니다 — 타입·필수값·범위(`0 ≤ value ≤ 10,000,000`)·날짜 형식을 스키마에 선언하면 FastAPI가 자동으로 `422`를 돌려주고, Swagger 문서도 같은 선언에서 생성됩니다.

---

## 7. [보너스 ①] Function Calling + MCP 멀티채널 연동

### 왜 필요한가

컨텍스트 주입은 **요약에 담긴 것만** 답할 수 있습니다. 개별 레코드를 봐야 하는 질문은 GPT가 직접 데이터를 조회해야 합니다.

### 도구 11종 — 어떤 근거로 어떤 도구를 호출하는가

| 도구 | 호출 근거 | 예시 질문 |
|---|---|---|
| `get_data_summary` | 요약 통계만으로 충분함 | "전반적으로 어때?" |
| `query_data` | 특정 기간의 **개별 레코드**가 필요함 | "지난주 기록 보여줘" |
| `find_extreme` | 기간 내 **극값 탐색**이 필요함 | "제일 쌌던 날은?" |
| `get_item_verdict` | **한 품목**의 두 축 판정이 필요함 | "배추 지금 사도 돼?" |
| `browse_by_category` | **갈래**로 훑어야 함 | "수산물 중에 살 만한 거 있어?" |
| `get_item_scores` | 값 말고 **전반적인 평가**를 물음 | "지금 시금치 어때?" |
| `get_swot_analysis` | **장보기 계획**의 판단이 필요함 | "이번 주 뭘 미루고 뭘 사?" |
| `get_price_forecast` | **앞으로**를 물음 | "김장철 배추값 어떻게 될까?" |
| `recommend_dishes` | **뭘 만들지**부터 정해야 함 | "도시락 반찬 추천해줘" |
| `suggest_alternative` | 판정이 나빠서 **대안**이 필요함 | "배추가 비싼데 뭘 대신 쓰지?" |
| `list_past_conversations` | **대화 기록** 조회가 필요함 | "전에 무슨 얘기 했지?" |

전부 조회 도구였다면 GPT는 그냥 첫 번째 것만 부릅니다. 판단이 필요한 도구
(`suggest_alternative`, `get_swot_analysis`, `recommend_dishes`)가 섞여 있어야
GPT가 도구를 "고르는" 행동이 실제로 나타납니다.

`TOOL_SPECS` 와 `TOOL_IMPLS` 는 스모크 테스트에서 **키가 정확히 일치하는지** 검사합니다.
스키마만 늘리고 구현을 빠뜨리면 GPT가 부른 뒤에야 실패하는데, 그때는 이미 토큰을 쓴 뒤입니다.

### 계산인 것을 예언처럼 말하지 않게 하기

`get_price_forecast` 는 GPT가 가장 단정하기 쉬운 도구입니다. 그래서 시스템 프롬프트에
규칙을 못 박았습니다 (`summary_service.build_system_prompt` 9~11번).

> "~할 것입니다" 대신 "지금까지의 패턴대로라면 ~쯤으로 계산됩니다"처럼 말하고,
> caveat(작황 급변·명절 수요는 반영 안 됨)를 반드시 함께 전하세요.
> 환율·날씨·운송비는 관측치가 아니라 사용자가 넣은 **가정**입니다.

`get_item_scores` 도 마찬가지로, 응답의 각 축에 `source: measured | reference` 를 실어
보내고 "참고값을 데이터인 것처럼 말하지 말라"고 지시합니다.

### 호출 흐름

```
사용자: "6월 중에 제일 쌌던 날이 언제야?"
   │
   ▼
[POST /api/chat]  system 프롬프트(요약+판정) + tools 스키마 11개 첨부
   │
   ▼
GPT 1차 응답: finish_reason = "tool_calls"
   └ 판단 근거: 요약에는 '전체 최저가'만 있고 '6월 한정 최저가'는 없다
   └ 호출: find_extreme({ mode: "min", start: "2026-06-01", end: "2026-06-30" })
   │
   ▼
서버가 도구 실행 → { found: true, date: "2026-06-10", value: 4090, memo: "매실" }
   └ 결과를 role:"tool" 메시지로 대화에 추가
   │
   ▼
GPT 2차 응답: "6월에는 10일이 4,090원/kg으로 가장 저렴했어요. 매실 제철이었네요."
   │
   ▼
프론트엔드 하단에 호출 추적 표시: 🔧 find_extreme({"mode":"min",...})
대화는 conversations 컬렉션에 자동 저장
```

무한 호출을 막기 위해 도구 라운드는 **최대 3회**로 제한합니다 (`MAX_TOOL_ROUNDS`).

### 대체재 추천 — 도메인 지식과 사실을 섞지 않는다

`suggest_alternative` 는 두 가지를 **따로** 가져와 합칩니다.

| | 어디서 | 예 |
|---|---|---|
| 조리에서 대신할 수 있나 | `alternatives.py` 표 (사람이 적은 지식) | "국거리로 거의 같게 씁니다" |
| 그래서 얼마나 싼가 | 실제 저장된 데이터의 품목별 평균 | "평균 5,029원, 배추보다 26% 비쌈" |

표에 가격을 적어두면 데이터가 바뀌어도 표는 안 바뀌어 **거짓말을 하게 됩니다.** 스모크 테스트에 "표에 숫자+원 형태가 없는지" 검사가 들어 있습니다.

### MCP Server (외부 채널 검증)

동일한 11개 도구를 MCP 프로토콜로도 노출해서, Claude Desktop 같은 **외부 클라이언트에서도** 조회할 수 있음을 확인했습니다.

```bash
cd backend
pip install "mcp[cli]"
python mcp_server/server.py
```

Claude Desktop 설정 (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "seasonal-table": {
      "command": "python",
      "args": ["/절대경로/backend/mcp_server/server.py"],
      "env": { "GOOGLE_APPLICATION_CREDENTIALS": "/절대경로/serviceAccountKey.json" }
    }
  }
}
```

```
   OpenAI Function Calling ──┐
                             ├──► TOOL_SPECS / run_tool ──► Firestore
   MCP Server (stdio) ───────┘        (tools.py 한 곳)
```

**정의를 한 곳에만 둔 이유** — 두 벌이 되면 반드시 어긋납니다. 실제로 도구를 4개→5개로 늘렸을 때 MCP 서버 코드는 **한 줄도 고치지 않았고**, 그대로 5개가 노출됐습니다.

---

## 8. [보너스 ②] 인사이트·UX 고도화

### 확장 통계 — `/api/data/statistics`

`/summary` 와 **일부러 분리했습니다.** 목적이 다르기 때문입니다.

| | 목적 | 지표를 늘리면 |
|---|---|---|
| `/summary` | AI 프롬프트에 넣을 **짧은** 요약 | 토큰만 먹고 답변 품질이 떨어짐 |
| `/statistics` | 화면에 그릴 **자세한** 지표 | 길어도 됨 |

제공 지표 — 이동평균 7·30일, 요일별 평균, 사분위수(q1/중앙/q3), 표준편차, 최장 연속 상승·하락 일수, 품목별 평균.

### 품목 분류 — 대 · 중 · 소 3단

`catalog.py` 에 94품목의 분류·제철 달·조리 성격·민감도를 적어 두고, 화면의 분류 막대와
시세판·그래프 필터가 전부 이 한 표에서 나옵니다.

```
채소 18 │ 엽경채류(6) 과채류(4) 근채류(4) 조미채소(3) 버섯류(1)
수산  7 │ 생선류(3) 패류(2) 연체류(1) 해조류(1)
과일  2 │ 과일류(2)
```

두 가지를 지켰습니다.

- **데이터에 있는 품목만** 나무를 만듭니다. 카탈로그 전체를 내려주면 가격이 없는 가지를
  눌렀을 때 빈 화면이 나오고, 그건 고장으로 보입니다.
- **대분류를 고르기 전에는 아랫줄을 만들지 않습니다.** 3단을 처음부터 다 펼치면
  버튼이 60개가 넘어 오히려 못 찾습니다.

### 조건으로 고르기 — `/api/recommend`

조리법·식사 목적(칩)과 계절감·신선도·난이도·편의성(슬라이더)을 받아, 음식 82종
(`dishes.py`) 중에서 고르고 **그 재료를 지금 값으로 판정해서** 함께 돌려줍니다.
비싼 재료에는 대체재가 붙습니다.

점수는 가중합이지만 **조리법·목적만 곱셈 관문**으로 뒀습니다.

```python
gate  = parts["조리법"] * parts["목적"]          # 안 맞으면 0.25배
score = (계절감*1.6 + 난이도*0.9 + 편의성*0.9 + 가격*1.4) * coverage * gate
```

가중합에 섞었더니 "국물 요리"를 골랐는데 계절감·가격 점수가 높은 **호박전**이 1위로
올라왔습니다. 조리법은 취향이 아니라 사용자가 **직접 고른 조건**이므로 관문이 맞습니다.

`dishes.py` 의 표는 대화에서 재료를 뽑는 `mentions.py` 와 **같은 것을 씁니다.**
따로 들고 있으면 한쪽만 고쳐져서 "추천은 되는데 대화에서는 못 알아듣는" 어긋남이 생깁니다.

### 서버 추천 / AI 추천을 사용자가 고르게

같은 조건 손잡이로 두 가지를 할 수 있습니다.

| | 무엇이 좋은가 | 무엇이 아쉬운가 |
|---|---|---|
| **서버 추천** | 같은 조건이면 항상 같은 결과. 재료값 판정이 정확히 붙음 | 말투가 딱딱함 |
| **AI에게 묻기** | 사람 말투의 제안, 이유 설명이 자연스러움 | 같은 조건이라도 답이 조금씩 달라짐 |

AI 모드일 때는 조건을 문장으로 바꿔 `/api/chat` 의 `conditions` 로 함께 보내고,
서버가 그것을 시스템 프롬프트에 얹습니다. **값과 판정은 여전히 서버 것을 씁니다** —
GPT는 그 조건에 맞는 음식을 고르는 말투만 담당합니다.

### 시각화 4종 — `/api/data/scores`, `/swot`, `/monthly`

| 그림 | 답하는 질문 | 근거 |
|---|---|---|
| 평가 지표 레이더 | "이 품목, 값 말고 전반적으로 어때?" | 6축 (측정 3 + 참고 3) |
| SWOT 4칸 | "뭘 지금 사고 뭘 미룰까?" | 지금 값 + 월별 평균 + 변동성 |
| 분류별 히트맵 | "어느 갈래가 언제 싼가?" | 분류 × 12개월 |
| 가격 분포 | "지금이 이 품목의 1년 범위에서 어디쯤?" | 최저~최고 막대 + 현재 점 |

**측정값과 참고값을 섞지 않았습니다.** 레이더의 여섯 축 중 계절성·가격·신선도는 실제
가격에서 계산한 값이고, 기호도·편의성·쉬움은 카탈로그에 적어 둔 사람의 판단입니다.
하나로 합친 종합점수만 보여주면 틀렸을 때 어디가 틀렸는지 알 수 없어서, 응답에
`source: measured | reference` 를 실어 보내고 화면에서 초록 실점과 흰 점으로 나눠 그립니다.

**히트맵은 절대 가격이 아니라 '연평균 대비 그 달 평균'을 칠합니다.** 절대값으로 칠했더니
대하(3만원)가 표 전체를 덮어 채소가 한 칸도 보이지 않았습니다.

**SWOT은 GPT가 아니라 서버가 만듭니다.** 강점·위협은 전부 계산으로 나오는 것이기
때문입니다 — 평년보다 싸면 강점, 다음 달 평균이 더 비싸면 위협. 그래서 각 줄에
근거가 붙습니다: `배추 다음 달 평균이 13% 더 쌉니다 — 미룰수록 유리`.

### 향후 가격 추이선 — `/api/data/forecast`

세 가지를 곱해 앞으로 60일을 계산합니다.

```
① 계절 곡선   같은 달력 날짜(±3일)의 다른 해 평균     ← 뼈대
② 수준 보정   최근 14일 실제 ÷ 같은 기간 계절 곡선    ← 올해가 평년보다 비쌌으면 그 수준에서 출발
③ 추세 감쇠   최근 30일 기울기를 절반만, 갈수록 약하게 ← 그대로 늘리면 60일 뒤가 터무니없어진다
```

**환율·날씨·운송비 데이터는 우리에게 없습니다.** 없는 것을 있는 척하지 않았습니다.
대신 **가정값 손잡이**로 뒀습니다 — "환율이 5% 오르면?"을 밀면, 품목별 민감도
(수산물은 환율 0.30, 산나물은 날씨 0.95)를 곱해 선이 움직입니다. 예언이 아니라
**조건을 넣었을 때의 계산**이고, 화면에도 그렇게 적습니다.

선 하나만 그리면 사용자가 그것을 정답으로 읽습니다. 그래서 **평년의 흩어짐으로 만든 띠**를
함께 그리고 점선으로 표시했습니다. 띠가 넓은 품목은 그만큼 못 믿을 품목이라는 뜻이고,
그 사실이 값 자체만큼 중요합니다.

### 시각화 — SVG를 직접 그림

차트 라이브러리 없이 SVG로 구현했습니다. canvas가 아닌 SVG를 고른 이유:

1. 확대해도 선명하다
2. **색을 CSS 변수로 줄 수 있어 다크 모드가 저절로 따라온다**
3. 각 점이 요소라 마우스 위치를 찾기 쉽다

일별 / 7일 평균 / 30일 평균 3개 선, 체크박스 토글, 기간 전환(1개월·3개월·1년·전체), 마우스 툴팁.

### 내보내기 — CSV / JSON

```
GET /api/data/export?format=csv   →  jecheol_20260907.csv
GET /api/data/export?format=json  →  jecheol_20260907.json
```

**CSV 앞에 BOM(`﻿`)을 붙였습니다.** 이게 없으면 엑셀이 한글을 CP949로 읽어 `memo` 칸이 전부 깨집니다.

### 다크 모드

색을 **3단으로** 정의했습니다. 셋 다 있어야 제대로 동작합니다.

```css
:root                                /* 1) 기본 (밝은 화면) */
@media (prefers-color-scheme: dark)  /* 2) OS를 어둡게 써둔 경우 */
:root[data-theme="dark"]             /* 3) 화면에서 직접 고른 경우 */
```

2번만 있으면 토글이 안 먹고, 3번만 있으면 OS 설정을 무시합니다. 선택은 `localStorage`에 기억됩니다.

---

### 모바일 반응형

브레이크포인트 4개(1100 / 1000 / 760 / 700px)에서 무엇이 어떻게 접히는지,
그리고 그 폭에서 **기능이 실제로 동작하는지**를 따로 문서화했습니다.

**[`문서/반응형-검증.md`](문서/반응형-검증.md)** — 브레이크포인트 명세, 측정 스니펫, 해상도별 실측값, 조작 확인 7항목

핵심 원칙은 세 가지입니다. **가로 스크롤을 만들지 않고**(줄이는 게 아니라 접는다),
**먼저 볼 것을 위로 올리고**(1단으로 접힐 때 판정 카드가 `order:-1`),
**정보를 지우는 것은 마지막 수단**입니다(실제로 숨기는 것은 시세판 머리행과 분포 최고값 열 둘뿐).

---

## 9. 예외 처리

프론트엔드는 상태 코드마다 **무엇을 하면 되는지**를 한국어로 안내합니다 (`app.js` 의 `ERR_BY_STATUS`).

| 상태 | 화면에 보이는 문구 |
|---|---|
| 연결 실패 | 서버에 연결하지 못했습니다. 셋 중 하나입니다 — ① 백엔드가 꺼져 있음 ② 무료 서버가 절전에서 깨는 중 ③ 백엔드의 ALLOWED_ORIGINS 에 이 주소가 빠짐(CORS). |
| 422 | 입력값이 올바르지 않습니다. 날짜 형식(YYYY-MM-DD)과 0 이상의 숫자인지 확인해 주세요. |
| 404 | 해당 항목을 찾을 수 없습니다. 다른 창에서 이미 지워졌을 수 있습니다. |
| 503 | AI 기능이 아직 준비되지 않았습니다. 서버에 OPENAI_API_KEY 를 설정해 주세요. |

> ⚠️ **한 가지 함정** — FastAPI의 검증 실패(422)는 `detail` 이 **문자열이 아니라 배열**로 옵니다. 그걸 그대로 화면에 띄우면 `[{"type":"date_from_datetime_parsing",...}]` 같은 내부 구조가 노출됩니다. 그래서 **문자열일 때만** 서버 메시지를 신뢰하고, 그 외에는 위 표의 안내로 대체합니다.

---

## 10. 로컬 실행 방법

### 10-0. 가장 빠른 방법 (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File ".\시작하기.ps1"
```

`.env` 생성 → 가상환경 → 패키지 설치 → 서버 두 개 실행 → 브라우저 열기까지 자동입니다.

### 10-1. 백엔드 (수동)

```bash
cd backend

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # Windows: copy .env.example .env
# .env 를 열어 OPENAI_API_KEY 와 Firebase 키 경로를 채운다

# Firebase 없이 API 흐름만 먼저 확인 (120개 항목)
USE_MEMORY_DB=true python smoke_test.py

# 데이터 준비 — 규모를 골라야 한다 (아래 표 참고)
python scripts/generate_data.py            # 기본 lite = 27품목 × 730일 = 19,710건
python scripts/seed_firestore.py --wipe    # Firestore 에 업로드

uvicorn app.main:app --reload

uvicorn app.main:app --reload
```

→ http://127.0.0.1:8000/docs

> 💡 `USE_MEMORY_DB=true` 로 띄우면 **서버가 뜰 때 seed_data.json 을 자동으로 넣습니다.** 메모리 저장소는 끌 때마다 비워지기 때문입니다. Firestore를 쓸 때는 자동으로 넣지 않습니다(`SEED_ON_START` 참고).

### 10-2. 프론트엔드

정적 파일이므로 아무 정적 서버로 열면 됩니다. **`file://` 로 직접 열면 CORS 때문에 동작하지 않습니다.**

```bash
cd frontend
python -m http.server 5500
```

→ http://127.0.0.1:5500

### 10-3. Firebase 준비

1. [Firebase 콘솔](https://console.firebase.google.com) → 프로젝트 생성
2. **빌드 → Firestore Database → 데이터베이스 만들기** (프로덕션 모드)
3. **⚙️ 프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성** → JSON 다운로드
4. 받은 파일을 `backend/serviceAccountKey.json` 으로 저장 (이미 `.gitignore`에 포함)

### 10-4. KAMIS 실측 데이터로 바꾸려면 (선택)

자매 프로젝트 `jecheol-planner` 가 KAMIS 오픈API로 실제 소매 시세를 수집합니다.

```bash
cd ../jecheol-planner
# .env 에 KAMIS_CERT_KEY / KAMIS_CERT_ID 를 채운 뒤
python main.py codes
python main.py collect --years 2

cd ../jecheol-ai-secretary/backend
python scripts/import_kamis.py     # prices_clean.csv → seed_data.json
python scripts/seed_firestore.py --wipe
```

`import_kamis.py` 는 품목별 여러 줄을 하루 한 줄로 합치고, **3일 이하 결측은 선형 보간**하며(`analyze.py` 의 `GAP_FILL_MAX` 와 같은 기준), 4일 이상은 메우지 않고 제외하며 그 사실을 보고합니다.

---

## 11. 환경 변수 목록

### 백엔드 (Render)

| 변수 | 필수 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API 키 |
| `FIREBASE_SERVICE_ACCOUNT_B64` | ✅ | 서비스 계정 JSON을 **base64로 인코딩**한 한 줄 문자열 |
| `ALLOWED_ORIGINS` | ✅ | CORS 허용 도메인 (콤마 구분). 예: `https://myapp.vercel.app` |
| `OPENAI_MODEL` | | 기본 `gpt-4o-mini` |
| `OPENAI_MAX_TOKENS` | | 기본 `600` — **과금 방지용 상한** |
| `USE_MEMORY_DB` | | 개발용. 배포 시 반드시 `false` |
| `SEED_ON_START` | | `auto`(기본, 메모리 모드만) / `true`(항상) / `false`(절대 안 함) |
| `APP_ENV` | | `local` / `production` |

> 로컬에서는 `FIREBASE_SERVICE_ACCOUNT_B64` 대신 `GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json` 을 써도 됩니다.

### 프론트엔드 (Vercel)

| 변수 | 필수 | 설명 |
|---|---|---|
| `API_BASE_URL` | ✅ | 백엔드 주소. 예: `https://myapi.onrender.com` |

빌드 시 `build.js`가 이 값을 읽어 `config.js`를 생성하므로, API 주소가 코드에 하드코딩되지 않습니다.

### 왜 환경 변수여야 하는가

- **API 키**: 저장소에 커밋되는 순간 유출입니다. GitHub은 공개 저장소의 키를 자동 스캔하고, 유출된 OpenAI 키로는 남이 내 돈으로 요청을 보낼 수 있습니다.
- **CORS**: 프론트(`*.vercel.app`)와 백엔드(`*.onrender.com`)는 **출처가 다릅니다.** 브라우저의 동일 출처 정책이 기본적으로 요청을 차단하므로, 서버가 "이 출처는 허용한다"고 응답 헤더로 알려줘야 합니다. 허용 목록을 코드에 박으면 배포 주소가 바뀔 때마다 재배포해야 하므로 환경 변수로 둡니다.

### 패키지 버전을 고정한 이유

`requirements.txt` 맨 위에 근거를 주석으로 적어뒀습니다. 요약하면 — **개발 PC는 Python 3.14, Render는 3.11**이고, `pydantic-core` 는 **2.35.0부터** 3.14용 미리 빌드된 wheel을 제공합니다. 그보다 낮은 버전을 쓰면 pip이 Rust로 직접 컴파일하려다 실패합니다. 아래 명령으로 **두 환경 모두 wheel만으로 설치됨을 확인**했습니다.

```bash
pip install --dry-run --python-version 314 --platform win_amd64 --only-binary=:all: -r requirements.txt
pip install --dry-run --python-version 311 --platform manylinux2014_x86_64 --only-binary=:all: -r requirements.txt
```

`uvicorn` 에 `[standard]` 를 붙이지 않은 것도 같은 이유입니다 — `uvloop` 에 3.14용 wheel이 아직 없고, 성능 옵션일 뿐 기능 차이는 없습니다.

---

## 12. 배포

### 12-1. 백엔드 → Render

1. GitHub에 코드 푸시 (`.env`와 `serviceAccountKey.json`이 포함되지 않았는지 반드시 확인)
2. Render → **New → Web Service** → 저장소 연결
3. 설정
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. **Environment** 탭에서 위 환경 변수 입력

   서비스 계정 키를 base64로 만드는 법:
   ```bash
   # macOS / Linux
   base64 -w0 serviceAccountKey.json
   # Windows PowerShell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("serviceAccountKey.json"))
   ```
   > JSON 원문을 그대로 붙이면 개행 문자가 깨져 `Invalid JSON` 오류가 납니다.

5. 배포 후 `https://<서비스명>.onrender.com/docs` 접속 확인

### 12-2. 프론트엔드 → Vercel

1. Vercel → **Add New → Project** → 같은 저장소 연결
2. **Root Directory**: `frontend`
3. **Settings → Environment Variables** → `API_BASE_URL` = Render 주소 등록
4. 배포 후, **Render의 `ALLOWED_ORIGINS`에 Vercel 주소를 추가**하고 백엔드를 재배포

   > 이 단계를 빠뜨리면 화면은 뜨는데 모든 요청이 CORS로 막힙니다 — 가장 흔한 실수입니다.

---

## 13. 검증

`backend/smoke_test.py` 는 Firebase도 OpenAI 키도 없이 메모리 저장소만으로 **120개 항목**을 검증합니다.

```bash
cd backend && USE_MEMORY_DB=true python smoke_test.py
```

주요 검증 항목:

| 분류 | 내용 |
|---|---|
| 기본 | 헬스체크 / 19,710건 일괄 업로드 / 목록·정렬 / 100개 이상 요건 |
| 두 축 | 평년 대비·전주 대비 계산, 두 값이 실제로 다른지 |
| 판정 | 5단계 밴드, **경계값 11개 케이스**(−12.0 vs −11.9 등) |
| 프롬프트 | 판정·평년 대비·"판정 뒤집기 금지" 규칙이 실제로 실리는지 |
| CRUD | 생성·수정·삭제, 잘못된 입력 422, 삭제 후 404 |
| 대화 | 저장·목록·불러오기·삭제, 목록에 messages 미포함 |
| 도구 | 11종 실행, 스키마↔구현 일치, 알 수 없는 도구 처리, **데이터의 품목이 모두 대체재 표에 있는지** |
| 통계 | 이동평균 시작 위치, 사분위 순서, 요일별 7개 |
| 내보내기 | CSV의 BOM, 헤더, 줄 수, 잘못된 format 422 |
| 경로 | `summary`·`statistics`·`export` 가 `{data_id}` 에 먹히지 않는지 |

---

## 14. 개발 중 실제로 겪고 고친 문제

구술 평가에서 쓸 수 있도록, **테스트가 잡아낸 것**만 적습니다.

| # | 증상 | 원인 | 조치 |
|---|---|---|---|
| 1 | 8/31 5,270원 → 9/1 4,180원 (하루 −21%) | 월별 계수를 **계단식**으로 적용 | 달 중간값 기준 **선형 보간** |
| 2 | 평년 대비가 `+0.1%` 라는 이상한 값 | 위 절벽이 ±7일 창에 걸려 평년값 오염 | 1번을 고치자 `+4.8%` 로 정상화 |
| 3 | 평년 근거가 "7건"으로 표시 | 날짜 수를 세고 있었음 | 실제 비교값 개수(133건)로 수정 |
| 4 | `pip install` 이 Rust 컴파일에서 실패 | `pydantic-core` 에 3.14용 wheel 없음 | 버전 상향 + **설치 전 dry-run 검증** |
| 5 | 422 오류에 파이썬 내부 구조가 노출 | "한글이 있으면 신뢰" 규칙이 **입력값의 한글**에 걸림 | `detail` 이 **문자열일 때만** 신뢰 |
| 6 | 데이터가 1,460건 (두 배) | 편의로 넣은 **자동 시드가 테스트에서도 실행** | `SEED_ON_START` 3상태로 분리 + 첫 줄에 검사 추가 |
| 7 | 대체재 표 검사가 오탐 2건 | `"시원하다"` 의 '원'을 가격으로 오인 | `숫자+원` 형태만 잡도록 정규식 수정 |
| 8 | PowerShell 한글이 `?쳥 콘` 으로 깨짐 | `.ps1` 에 UTF-8 BOM이 없어 CP949로 읽힘 | BOM 추가 (CSV의 BOM과 같은 문제) |

> 6번과 7번이 특히 의미 있습니다. **6번은 "켤 수 있게 만들었으면 끌 수 있게도 만들어야 한다"**는 교훈이고, **7번은 테스트 자체가 틀릴 수 있다**는 사례입니다. 빨간 줄이 떴을 때 원인을 확인했기에 그중 하나(바지락 누락)가 진짜 구멍이었음을 발견했습니다.

---

## 15. 제출 스크린샷 체크리스트

> ⚠️ **이미지는 평가에 쓰이지 않습니다.** 자동 평가는 코드·문서(.md/.json/.py 등) 파일만 읽습니다.
> 그래서 아래 화면 증빙과 **같은 사실을 텍스트로도** 남겨 두었습니다 —
> [`문서/실행검증.md`](문서/실행검증.md) · [`문서/반응형-검증.md`](문서/반응형-검증.md) · [`docs/openapi.json`](docs/openapi.json).

- [ ] **데이터 요약이 보이는 채팅 화면** — 왼쪽 판정 카드 + 질문/답변이 한 화면에
- [ ] **데이터 관리 화면** — 추가 또는 수정이 동작한 직후 (목록이 갱신된 상태)
- [ ] **대화 기록 화면** — 이전 대화를 클릭해 불러온 직후 (선택된 대화가 하이라이트)
- [ ] Swagger UI (`/docs`) 전체 엔드포인트 25개
- [ ] (보너스①) **도구 호출 추적** — 채팅 하단 `🔧 find_extreme({...})` 표시
- [ ] (보너스②) **그래프 + 다크 모드** — 밝은 화면과 어두운 화면 각각
- [ ] (검증) 스모크 테스트 `🎉 전체 통과`

---

## 16. 비용 주의

- 개인 OpenAI 키 사용 시 과금이 발생합니다.
- `OPENAI_MAX_TOKENS=600` 상한이 걸려 있고, 대화 기록은 최근 8턴만 프롬프트에 실립니다.
- 도구 호출이 일어나면 GPT를 2회 호출하므로 비용이 약 2배가 됩니다. 화면의 **"도구 호출 사용" 체크를 끄면** 1회만 호출합니다.
- 요약은 전체 레코드를 조회하지만 **프롬프트에는 요약 문장만** 들어가므로, 데이터가 19,710건에서 열 배가 되어도 토큰은 거의 늘지 않습니다.
