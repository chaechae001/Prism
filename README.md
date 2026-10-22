# PRISM · 여러 시선이 만나는 뉴스

뉴스를 사건별로 읽고 출처를 비교하는 모바일 우선 웹앱입니다. 인스타그램 방식의 사진 피드·날짜별 스토리·북마크와 기사별 AI 대화를 제공합니다.

현재는 **가상 뉴스로 UI·API를 검증하는 개인 개발 버전**입니다. 뉴스 전체가 실제 수집·군집·LLM 요약 자동화로 게시되는 운영 서비스는 아닙니다. 엘리스 GPT-5 mini를 이용한 기사별 DM의 실제 요약과 후속 질문 답변은 확인했습니다.

## 현재 기능

- 사진 피드, 기사 제목·제공된 요약/미리보기, 원문·관련 기사·관점 비교
- 날짜별 뉴스 스토리, 정치·경제·사회·기술 카테고리, 사진 검색
- 라이트/다크 전환, 브라우저 북마크·댓글·뉴스별 DM 기록
- 게시물의 DM을 눌러야 생성되는 뉴스 전용 대화방
- 기사 ID를 서버에서 다시 조회하고 선택 사건의 출처 ID를 검증하는 AI 답변

사진은 가상 뉴스의 예시이며 실제 사건 사진이 아닙니다. 현재 API에 전문이 없어 DM은 제목·제공된 요약·관련 기사 정보를 참고합니다. 댓글·대화 기록은 이 브라우저에만 저장됩니다.

## 로컬 실행

요구 사항: Python, Node.js/npm. 개발 검증 환경은 Python 3.13 / Node.js 24입니다.

프로젝트 루트의 터미널 1:

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 8004
```

터미널 2:

```powershell
cd frontend
npm.cmd ci
$env:VITE_API_MODE='mock'
$env:VITE_NEWS_API_VERSION='v1'
npm.cmd run dev -- --port 5183
```

http://127.0.0.1:5183/ 에 접속합니다. 키 없이도 뉴스 화면을 확인할 수 있고 AI 대화는 연결 안내가 표시됩니다. 기존 서버가 실행 중이면 같은 포트로 중복 실행하지 않습니다.

실제 AI 대화를 쓰려면 `backend/.env.chat.example`을 `backend/.env.chat.local`로 복사하고 엘리스 키·전용 URL을 입력한 뒤 `PRISM_CHAT_ENABLED=1`로 설정하고 API 서버를 재시작합니다. **기존 로컬 설정 파일이 있으면 덮어쓰지 않습니다.** [엘리스 연결 안내](docs/ELICE_NEWS_DM.md)를 확인하세요. 키는 브라우저·GitHub에 넣지 않습니다.

## 구조와 협업

개인 저장소의 `main`은 비교 기준, `dev`는 다음 개발 통합용입니다. 기능별 폴더와 작업 흐름은 [저장소 구조](docs/REPOSITORY_STRUCTURE.md)에 정리했습니다.

```text
frontend/          React + TypeScript + Vite, Radix UI, TanStack Query, Lucide
backend/app/       FastAPI, 뉴스 조회 경계, 엘리스/OpenAI 어댑터
backend/tests/     뉴스·API·제공자 검증
contracts/         뉴스 v1·DM 계약, 가상 데이터, 별도 v2 실험 계약
database/          설계/마이그레이션 기록 — 새 설치용 자동 실행 명령 아님
docs/              실행·협업·변경 이력
scripts/           검증·샘플 데이터 도구
```

활성 개발 API는 `app.api:app`입니다. 기존 `main.py`는 Mock, `connection_api.py`는 v1 연결 기반입니다. `news_api.py`와 `news/`는 **중단한 네이버 v2 실험 기록**으로 현재 기본 실행에 필요하지 않습니다. 기존 Supabase에 적용한 v2 migration을 다시 실행하지 않습니다.

개인 Prism과 팀 filter-bubble은 별도 저장소입니다. 팀의 비공개 최신 코드를 읽고 계약을 비교한 후 기능 브랜치로 이식할 계획이며, 아직 팀 원격에 반영하지 않았습니다. [팀 통합 계획](docs/TEAM_INTEGRATION_PLAN.md)에 브랜치·폴더 제안과 검토 항목을 정리했습니다.

## 검증

```powershell
python -m unittest backend.tests.test_api backend.tests.test_connection backend.tests.test_social_chat -q
cd frontend
npm.cmd test
npm.cmd run build
```

현재 백엔드 선택 회귀 테스트 50개, 프론트 테스트 46개가 통과했습니다. 브라우저에서 엘리스 실제 요약·후속 설명 답변 2건을 확인했습니다. DB가 필요한 별도 v2 테스트와 실제 수집·군집·자동 게시 전체를 검증했다는 뜻은 아닙니다.

DM API는 현재 로컬 개발용입니다. 공개 서비스로 배포할 때에는 사용자 인증, 사용자별 사용 한도, 댓글·대화 동기화를 추가해야 합니다.

## 문서

- [엘리스 뉴스 DM 연결](docs/ELICE_NEWS_DM.md)
- [DM·댓글·테마 구조와 실행](docs/NEWS_DM_SETUP.md)
- [팀 코드 비교·통합 계획](docs/TEAM_INTEGRATION_PLAN.md)
- [처음부터 배포까지 개발 지도](docs/PROJECT_ROADMAP.md) — 이전 단계 이력 포함
- [작업 로그](docs/worklogs/README.md)

이전 전달 ZIP·스크린샷·로컬 분석 데이터·환경 파일은 Git 대상에서 제외합니다. 사용 중인 Pretendard 폰트 라이선스는 `frontend/public/fonts/Pretendard-LICENSE.txt`에 있습니다.
