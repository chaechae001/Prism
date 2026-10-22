# 2026-10-22 개인 저장소 구조 정리와 업로드

사용자가 개인 Prism에 커밋·푸시를 승인했습니다. 팀 저장소에는 변경하지 않습니다.

## 변경 파일

- `frontend/src/features/news-chat/NewsInbox.tsx`, `features/comments/NewsComments.tsx`: 기존 components에서 기능별 이동. `frontend/src/App.tsx` import 수정.
- `backend/app/chat/router.py`, `providers.py`, `config.py`: 기존 social_* 모듈 이동. 상대 import와 환경 파일 위치 계산 수정.
- `backend/app/api.py`: 기본 실행 진입점 추가. `social_api.py`: 이전 명령 호환 유지.
- `backend/tests/test_social_chat.py`: 기본 진입점·이동한 모듈로 회귀 테스트 연결.
- `.github/workflows/checks.yml`: main/dev push와 PR에 백엔드 테스트·프론트 테스트·빌드 실행. 외부 API 키 미사용.
- `.gitignore`: 환경 파일·로컬 DB 관측·스크린샷·이전 작업 산출물 제외. 로컬 파일은 보존.
- `README.md`, `docs/REPOSITORY_STRUCTURE.md`, `TEAM_INTEGRATION_PLAN.md`, `PERSONAL_RELEASE_REVIEW.md`, `NEWS_DM_SETUP.md`, `ELICE_NEWS_DM.md`: 현재 실행 경로·브랜치·협업 설명 반영.
- `scripts/preflight_personal_release.py`: 업로드 후보 검사임을 명시. 실제 키·토큰 패턴 검출, 값 출력 없음.

## 검증과 범위

이동 후 검증: 백엔드 50개·프론트 46개 테스트와 TypeScript/Vite 빌드 통과. 업로드 후보 165개 파일의 비밀정보 검사 및 git diff --cached --check 통과. 기존 Starlette/httpx deprecation 경고 1건은 있으나 실패는 없습니다. main/dev를 같은 검증 기준으로 시작하며 origin은 개인 Prism만 사용합니다.

실제 RSS 본문·군집 자동화·운영용 인증/대화 저장은 이번 범위에 포함하지 않습니다. 댓글과 대화 기록은 브라우저 저장이며 DM API는 로컬 개발용입니다. 팀 비공개 코드는 접근 권한 확보 후 별도로 비교합니다.
