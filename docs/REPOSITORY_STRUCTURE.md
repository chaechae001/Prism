# 개인 PRISM 저장소 구조

## 브랜치

- `main`: 테스트를 통과한 비교 기준. 팀 저장소와 비교할 버전입니다.
- `dev`: 다음 변경을 통합하고 화면을 확인하는 개발 브랜치입니다.
- `feat/ui-작업명`, `feat/api-작업명`: dev에서 생성하는 짧은 작업 브랜치입니다.

작업 브랜치 → dev로 PR → 기능 확인 → main으로 PR 순서로 진행합니다. 현재 첫 업로드의 main과 dev는 같은 코드로 시작합니다. 브랜치 보호 설정은 아직 적용하지 않았으며 자동 테스트가 배포를 수행하지는 않습니다.

```text
frontend/src/
  features/news-chat/   뉴스별 대화함·DM 화면
  features/comments/    게시물 댓글 화면
  components/           공통 피드·탐색·스토리 UI
  hooks/                브라우저 저장·공유 상태
  api/                  요청 함수·생성된 API 타입
backend/app/
  api.py                기본 실행 진입점
  chat/                 router.py, providers.py, config.py
  connection_api.py     기존 v1 뉴스 API
  connection_repository.py  fixture/DB 데이터 조회 경계
backend/tests/          API·실패 응답·제공자 회귀 검증
contracts/             합의한 JSON 계약·fixture
database/             스키마·마이그레이션 기록
docs/                 실행법·설계·협업 기록
scripts/              계약 생성·샘플·업로드 검사
.github/workflows/     프론트·백엔드 자동 검사
```

`social_api.py`는 기존 실행 명령 호환용입니다. 새 실행은 `app.api:app`을 사용합니다. `main.py`의 Mock와 `news_api.py`/`news/`의 중단된 v2 실험은 이력 비교를 위해 보존했습니다. 실제 운영 배포 전에 활성 경로만 정리하며 DB migration은 임의로 재실행하지 않습니다.

## 역할과 팀 통합

정채은은 frontend와 기사별 대화 UI를 관리합니다. 최민준의 수집·DB/API 작업은 팀 저장소에서 진행하며 계약 변경 전에 합의합니다. contracts의 기존 v1 필드는 이번 정리에서 변경하지 않았습니다.

개인 origin에는 Prism만 등록합니다. 팀 저장소 접근 권한을 확보한 뒤 별도 checkout에서 API 계약, 본문 필드, 인증, migration 이력을 비교하고 필요한 파일을 작은 PR로 이식합니다. 개인 저장소 전체를 팀 저장소에 덮어쓰지 않습니다.

## 새 작업 시작

```powershell
git switch dev
git pull --ff-only origin dev
git switch -c feat/ui-next-task
```

로컬 환경 파일, 키, 스크린샷, ZIP, DB 관측 산출물은 Git에서 제외합니다. 예시 환경 파일만 공유하며 실제 값을 채우지 않습니다. 작업 이력은 공개 가능한 요약만 남기고 세부 로컬 기록은 로컬에 보관합니다.
