# PRISM

**여러 시선이 만나는 뉴스.**

사건별 뉴스와 출처를 함께 살펴보고, 뉴스별 AI 대화로 내용을 이해하는 모바일 우선 웹앱입니다. 사진 중심 피드에 날짜별 스토리, 카테고리 탐색, 북마크를 결합했습니다.

## 주요 기능

| 기능 | 동작 |
|---|---|
| 뉴스 피드 | 제목·요약·관련 기사와 원문 링크를 카드로 표시 |
| 날짜별 스토리 | 불러온 뉴스를 한국 시간 기준 날짜별로 탐색 |
| 카테고리·사진 탐색 | 정치·경제·사회·기술 필터와 이미지 그리드 |
| 뉴스 DM | 게시물에서 연 대화방에 한해 요약·쉬운 설명·질의응답 제공 |
| 출처 확인 | AI 답변의 기사 ID를 서버에서 검증 |
| 개인화 UI | 라이트·다크 모드, 북마크와 댓글·대화 기록의 브라우저 저장 |

현재 피드는 가상 데이터 기반이며 AI 대화는 서버에 제공자 설정을 추가하면 실제 호출합니다. 뉴스 자동 수집·군집 분석·정치적 편향 평가는 연결되어 있지 않습니다. 댓글과 대화 기록은 같은 브라우저에서만 유지됩니다. 5W·쉬운 설명·감정 분석의 별도 탭은 준비 중이며, 요약과 쉬운 설명은 뉴스 DM에서 요청할 수 있습니다.

## 기술 구성

- **Frontend:** React 19, TypeScript, Vite, TanStack Query, Radix UI, Lucide
- **Backend:** FastAPI, Pydantic, HTTPX
- **AI:** Elice GPT-5 mini 어댑터, JSON Schema 응답과 출처 ID 검증
- **계약·검증:** OpenAPI 기반 타입, MSW, Vitest, Python unittest, GitHub Actions

## 빠른 시작

검증 환경은 Python 3.13과 Node.js 24입니다.

프로젝트 루트에서 API 서버를 실행합니다.

```powershell
python -m pip install -r backend/requirements.txt
$env:CORS_ORIGINS='http://127.0.0.1:5183,http://localhost:5183'
python -m uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 8004
```

다른 터미널에서 프론트를 실행합니다.

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --port 5183
```

[http://127.0.0.1:5183](http://127.0.0.1:5183)에서 확인합니다. 기본 피드는 MSW가 제공하므로 키 없이 실행할 수 있습니다. DM 요청은 Vite 프록시를 통해 API 서버로 전달됩니다.

FastAPI를 통한 뉴스 조회까지 확인하려면 프론트 실행 명령을 다음으로 바꿉니다.

```powershell
$env:VITE_API_BASE_URL='http://127.0.0.1:8004'
npm.cmd run dev:http -- --port 5183
```

AI 대화는 `backend/.env.chat.example`을 `backend/.env.chat.local`로 복사해 설정합니다. 기존 로컬 파일이 있으면 유지합니다. [AI 연결 안내](docs/AI_CHAT.md)에 설정과 API 흐름을 정리했습니다.

## 프로젝트 구조

```text
frontend/src/
  components/          피드·스토리·탐색·상세 화면
  features/            뉴스 DM·댓글
  hooks/               조회·브라우저 저장·테마 상태
  api/                 HTTP 클라이언트·생성 타입
  mocks/               가상 뉴스 API
backend/
  app/api.py           FastAPI 기본 진입점
  app/chat/            대화 경로·설정·제공자 어댑터
  app/connection_*      뉴스 API·데이터 조회 경계
  tests/               API·RSS 변환·AI 응답 검증
contracts/             OpenAPI·JSON Schema·가상 데이터
database/             DB 설계 초안
docs/                 구조·API·데이터 계약·실행 문서
scripts/              계약 생성·데이터 검증 도구
.github/workflows/     테스트·빌드 자동화
```

## 설계 포인트

- 화면과 데이터 소스를 분리해 가상 API와 실제 HTTP API를 같은 컴포넌트에서 사용합니다.
- `Story` 계약을 중심으로 목록·상세·출처를 일관되게 표현합니다.
- 뉴스 DM은 브라우저가 보낸 기사 본문을 신뢰하지 않고 서버에서 사건 ID를 조회합니다.
- 모델 응답의 JSON 형식과 출처 ID를 확인하고, 실패를 생성된 답변처럼 표시하지 않습니다.
- 가상 뉴스·AI 생성 결과·검토되지 않은 분석을 구분해 표시합니다.

[아키텍처](docs/ARCHITECTURE.md) · [API 계약](docs/API_CONTRACT.md) · [데이터 계약](docs/DATA_HANDOFF.md) · [기여 방법](CONTRIBUTING.md)

## 테스트

```powershell
python -m unittest backend.tests.test_api backend.tests.test_connection backend.tests.test_social_chat -q
cd frontend
npm.cmd test
npm.cmd run build
```

GitHub Actions는 `main`·`dev`의 push와 PR에서 백엔드 테스트, 프론트 테스트와 빌드를 실행합니다. CI에는 실제 AI 키나 DB 연결이 필요하지 않습니다.

## 실행 범위

AI 대화는 제목·제공된 요약·관련 기사 메타데이터를 참고하며 원문 전문은 아직 연결되지 않았습니다. 서버의 대화 API는 로컬 개발용 접근 제한과 간단한 요청 한도를 적용합니다. 공개 배포에는 사용자 인증, 사용자별 한도와 영속 저장이 필요합니다.

사진은 데모용 예시이며 실제 사건 사진을 의미하지 않습니다. Pretendard 폰트의 라이선스는 [폰트 라이선스](frontend/public/fonts/Pretendard-LICENSE.txt)에서 확인할 수 있습니다.
