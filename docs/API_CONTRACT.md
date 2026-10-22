# API 계약 v1

기계가 읽는 완전한 명세: `contracts/openapi.json`. 원본: `backend/app/models.py`. 날짜 기준: 2026-10-21.
실행 서버의 `/docs`에서 직접 요청할 수 있습니다. 아래 응답 JSON은 읽기 쉬운 **필드 발췌**이며 완전한 유효 응답은 `contracts/examples/*.json`에 있습니다.

## 공통 규칙

- 기본 경로: `/api/v1`, JSON UTF-8, 필드 이름은 `snake_case`.
- 사건은 `story`, 원문 기사는 `article`. 카드 하나는 사건 하나입니다.
- ID는 불투명한 문자열입니다. 프론트에서 숫자 부분을 분해하지 않습니다. 데모만 `story-001` 형식입니다.
- 시간은 ISO 8601/RFC 3339, UTC `Z` 또는 명시적 오프셋입니다. UI는 `Asia/Seoul`로 표시합니다.
- 목록의 다음 페이지가 없으면 `next_cursor: null`, 요약 모델 미실행은 `model_version: null`, 문장·관점 미완성은 빈 배열입니다.
- 오류는 `{ "error": { "code", "message", "details", "request_id" } }`. 성공의 `request_id` 위치는 응답 스키마를 따릅니다. FastAPI는 모든 응답 헤더에 `X-Request-ID`를 넣습니다.
- 공개 조회·데모 피드백은 로그인 없이 사용합니다. 관리자 Mock만 `X-Admin-Token`을 요구합니다. 실제 사용자 데이터 API·인증은 아직 구현하지 않았습니다.
- `is_mock`, `is_demo`, `label_status: "demo"`로 가상 자료임을 알립니다.

## 엔드포인트

| 메서드 | 경로 | 요청 | 응답 | 성공 |
|---|---|---|---|---|
| GET | `/health` (v1 밖) | 없음 | `Health` | 200 |
| GET | `/api/v1/categories` | 없음 | `CategoriesResponse` | 200 |
| GET | `/api/v1/stories` | 검색·정렬·커서 쿼리 | `FeedResponse` | 200 |
| GET | `/api/v1/stories/{story_id}` | 사건 ID | `StoryResponse` | 200 |
| POST | `/api/v1/feedback` | `FeedbackRequest` JSON | `FeedbackResponse` | 201 |
| POST | `/api/v1/internal/jobs` | 관리자 헤더, `JobRequest` | `Job` | 202 |
| GET | `/api/v1/internal/jobs/{job_id}` | 관리자 헤더 | `Job` | 200 |

관리자 작업은 HTTP FastAPI에서만 시뮬레이션합니다. MSW에서는 관리자 경로에 401을 반환합니다. 실제 토큰을 브라우저 번들에 넣지 않기 위한 의도적인 차이입니다.

## 1. 카테고리 조회

```http
GET /api/v1/categories
```

```json
{
  "items": [
    {"id":"politics","label":"정치","count":3},
    {"id":"economy","label":"경제","count":3},
    {"id":"society","label":"사회","count":3},
    {"id":"technology","label":"기술","count":3}
  ]
}
```

카테고리 수는 fixture 전체 사건 수이며 현재 검색어/필터의 결과 수는 아닙니다.

## 2. 목록·검색·추천

```http
GET /api/v1/stories?q=AI&category=technology&mode=balanced&diversity=70&limit=6
```

GET 요청에는 JSON 본문이 없습니다. 프론트의 필터 상태 객체는 아래처럼 관리하고 URL 쿼리로 변환합니다.

```json
{"q":"AI","category":"technology","mode":"balanced","diversity":70,"limit":6,"cursor":null}
```

`category`와 `cursor`가 없으면 URL에서 생략하세요. `category=all`이나 `cursor=null` 문자열은 보내지 않습니다.

| 쿼리 | 형식/기본값 | 의미 |
|---|---|---|
| `q` | 문자열, 100자 이하, 기본 `""` | 제목·부제·키워드의 부분 문자열 검색. 앞뒤 공백 제거 |
| `category` | politics/economy/society/technology, 기본 생략 | 사건의 카테고리 |
| `mode` | balanced/latest/explore, 기본 balanced | 다양성 재정렬/최신순/발견 가점 |
| `diversity` | 정수 0~100, 기본 70 | 주제·출처 반복 감점 강도. latest에서는 정렬에 미적용 |
| `limit` | 정수 1~20, 기본 6 | 페이지 크기 |
| `cursor` | 최대 1000자 문자열, 기본 생략 | 이전 응답의 next_cursor를 그대로 전달 |

응답 필드 발췌:

```json
{
  "items": [
    {
      "story": {
        "id":"story-001",
        "title":"AI가 바꾸는 일터, 생산성 너머의 질문들",
        "category":"technology",
        "dek":"생산성의 기회와 일자리 전환의 과제를 함께 읽습니다.",
        "updated_at":"2026-10-21T13:50:00+09:00",
        "coverage":{"publisher_count":3,"article_count":3,"perspective_count":3,"label_status":"demo"},
        "is_demo":true
      },
      "reason":{"code":"source_diversity","label":"여러 출처를 비교할 수 있어요"}
    }
  ],
  "total":1,
  "next_cursor":null,
  "meta":{
    "request_id":"요청별 UUID",
    "generated_at":"응답 생성 시각",
    "dataset_version":"demo-2026-10-21-v1",
    "is_mock":true,
    "mode":"balanced",
    "diversity":70,
    "policy_version":"mock-v1",
    "returned_categories":["technology"],
    "source_cap_relaxed":false,
    "policy_notes":["개인화 없는 데모 순위입니다."]
  }
}
```

`total`은 필터 후 전체 사건 수, `items.length`는 이번 페이지 수입니다. 현재는 편리한 Mock 렌더링을 위해 목록에도 상세 `Story`를 모두 전달합니다. 데이터가 커지면 `StoryCard` DTO를 별도 버전/호환 전략으로 도입하세요. 목록의 `public_interest`는 실제 산정치가 아닌 fixture 순위 실험용 값입니다.

다음 페이지 요청은 기존 필터와 함께 `next_cursor`를 사용합니다. Mock 커서는 데이터 버전·정규화한 검색어·카테고리·mode·diversity와 묶여 있습니다. 조건을 바꾸면 기존 커서는 폐기하고 첫 페이지부터 시작합니다. 잘못되거나 다른 조건의 커서는 422입니다. Mock 커서는 인증 토큰이 아니며 위변조 방지 기능이 없습니다. 운영에서는 서버가 만든 snapshot/keyset 커서를 사용하고 유효기간과 데이터 변경 처리를 정하세요.

추천 이유 코드:

| code | 의미 |
|---|---|
| public_interest | 주요 이슈 예시 점수 기반 |
| source_diversity | 출처 비교를 고려한 데모 정렬 |
| discovery | 앞서 고른 사건들과 다른 카테고리 |
| latest | 사건 업데이트 시각 순 |

## 3. 사건 상세

```http
GET /api/v1/stories/story-001
```

응답 필드 발췌:

```json
{
  "story":{
    "id":"story-001",
    "title":"AI가 바꾸는 일터, 생산성 너머의 질문들",
    "category":"technology",
    "summary":{
      "status":"ready",
      "bullets":[
        {"text":"생산성의 기회와 일자리 전환의 과제를 함께 읽습니다.","article_ids":["story-001-a1","story-001-a2"]}
      ],
      "unknowns":["실제 보도가 아닌 UI 개발용 가상 자료입니다."],
      "model_version":"fixture-only",
      "prompt_version":"demo-v1"
    },
    "perspectives":[
      {"label":"기회와 기대","text":"도입으로 얻을 수 있는 편익과 새로운 가능성을 강조합니다.","article_ids":["story-001-a1"]}
    ],
    "articles":[
      {
        "id":"story-001-a1",
        "publisher_id":"p-01",
        "publisher_name":"데모 일보",
        "title":"[가상 기사] AI가 바꾸는 일터, 생산성 너머의 질문들 — 기회와 기대",
        "url":"https://example.com/demo/story-001/a1",
        "published_at":"2026-10-21T09:00:00+09:00",
        "framing":"기회와 기대",
        "is_demo":true
      }
    ]
  },
  "request_id":"요청별 UUID",
  "is_mock":true
}
```

인용 ID는 항상 해당 사건의 `articles` 안에 있어야 합니다. 원문 본문은 보내지 않습니다. 사용자에게 보이는 관점은 기사에서 강조하는 쟁점이며 언론사의 정치 성향이 아닙니다. `label_status`가 `unverified`면 확정 라벨처럼 표시하지 않아야 합니다.

| summary.status | UI 동작 |
|---|---|
| ready | 문장별 근거와 관점 비교 제공 |
| pending | ‘요약 준비 중’, 원문 목록 제공 |
| insufficient_sources | ‘추가 출처 확인 중’, 통합 요약 보류 |
| failed | ‘요약 생성 실패’, 원문 목록 제공 |

어떤 상태든 목록/상세 조회 자체는 200일 수 있습니다. **처리 상태와 HTTP 오류를 혼동하지 마세요.** 존재하지 않는 사건은 404입니다.

## 4. 피드백

```http
POST /api/v1/feedback
Content-Type: application/json
```

```json
{"story_id":"story-001","kind":"more_perspectives","comment":"현장 당사자의 시선도 보고 싶어요."}
```

```json
{"id":"응답별 UUID","status":"accepted","persisted":false,"request_id":"요청별 UUID"}
```

`kind`: `useful` / `more_perspectives` / `report_error`. `comment`: 생략/null 가능, 최대 500자. 알 수 없는 필드는 거절합니다.
`persisted:false`는 저장 완료를 의미하지 않습니다. 이 Mock에서는 추천 결과에 반영하지 않습니다. 운영 전 영구 저장·인증/익명 식별 정책·중복 전송·요청 제한을 구현하세요.

## 5. 내부 작업 시뮬레이션

FastAPI를 시작하는 터미널에 `MOCK_ADMIN_TOKEN` 환경변수를 설정해야 합니다. `.env.example`은 자동으로 읽지 않습니다. 서버 재시작이 필요합니다.

```powershell
$env:MOCK_ADMIN_TOKEN = '개발용으로직접만든임의토큰'
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```http
POST /api/v1/internal/jobs
X-Admin-Token: 개발용으로직접만든임의토큰
Content-Type: application/json
```

```json
{"stage":"summarize","dry_run":true}
```

```json
{"id":"작업별 UUID","stage":"summarize","status":"queued","dry_run":true,"note":"시뮬레이션 작업입니다. 실제 수집·AI 처리는 실행하지 않습니다."}
```

`stage`: collect/cluster/summarize. `dry_run:false`는 422로 거절합니다. GET `/api/v1/internal/jobs/{id}`를 조회하면 queued→running→succeeded로 바뀝니다. 실제 시간 기반 큐나 워커가 아닙니다. `failed`는 계약에 정의돼 있지만 이 시뮬레이션이 자동 생성하지 않습니다. 재시작 시 작업은 사라지고, 여러 프로세스 사이에서도 공유되지 않습니다.

## 6. 오류와 개발 시나리오

```json
{"error":{"code":"VALIDATION_ERROR","message":"요청 값을 확인해주세요.","details":[{"loc":["query","diversity"],"message":"Input should be less than or equal to 100","type":"less_than_equal"}],"request_id":"요청별 UUID"}}
```

| HTTP | code | 상황 |
|---|---|---|
| 401 | UNAUTHORIZED | 관리자 토큰 누락/불일치/미설정 |
| 404 | NOT_FOUND | 사건·작업 없음 |
| 422 | VALIDATION_ERROR | 카테고리/숫자 범위/본문/커서 오류 |
| 503 | MOCK_ERROR | 의도한 테스트 오류 |

계약은 409/500 공통 오류 모델도 예약합니다. 현재 엔드포인트에서 409를 사용하는 중복 제어는 구현하지 않았습니다. 내부 예외 처리·모니터링은 운영 전 보강해야 합니다. 프론트는 알 수 없는 오류도 일반 오류로 처리합니다.

`X-Mock-Scenario` 헤더를 목록 GET에 사용합니다. `normal`은 기본, `slow`는 약 2초 지연, `empty`는 빈 목록, `error`는 503입니다. 이 헤더는 실서비스 기능이 아니므로 운영 어댑터에 그대로 남기지 마세요.

## 7. 상태 관리와 계약 갱신

| 상태 | 저장 위치 | 이유 |
|---|---|---|
| q/category/mode/diversity/story/view | URL | 새로고침·공유·뒤로 가기 |
| 목록·상세·카테고리 응답 | TanStack Query | 서버 데이터 캐시·오류·취소 |
| 검색 입력·슬라이더 드래그 중 값 | React state | 확정 전 임시 값 |
| 북마크 ID 배열 | localStorage `prism:v1:saved` | 로그인 없는 브라우저 데모 |
| 오류/지연 시나리오 | React state | 개발 검증용 |

기존 목록 위에 다른 필터의 다음 페이지를 붙이지 않습니다. Query key에 모든 필터를 포함하고, 커서가 없는 첫 요청으로 시작합니다. 더 보기만 실패한 경우에는 기존 카드를 유지하고 추가 조회 실패 안내와 재시도 버튼을 제공합니다.

API 수정 시 실행 순서: `python scripts/export_contracts.py` → `python scripts/contract_cases.py` → `npm run types:api` → 양쪽 테스트. 기계 스키마가 개발 문서보다 우선하며, 의미 변경은 문서도 함께 고치세요.
