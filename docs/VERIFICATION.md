# 검증 결과

검증일: 2026-10-21. 이 결과는 가상 뉴스 프로토타입의 개발 동작을 확인한 것이며 실제 뉴스/모델의 품질 평가가 아닙니다.

**확인한 흐름:** 뉴스 목록 진입 → fetch → MSW 또는 FastAPI → 공통 fixture → TanStack Query → 카드/상세 렌더링.

| 경계/기능 | 결과 | 근거 |
|---|---|---|
| TypeScript/프로덕션 번들 | 통과 | `npm run build` |
| FastAPI 통합 테스트 | 7개 통과 | `python -m unittest discover -s backend/tests -v` |
| 프론트 계약/HTTP 테스트 | 32개 통과 | `npm test` |
| MSW/FastAPI 정렬·페이지 계약 | 28조건 비교 통과 | mode·diversity·category 조합, 커서·사건 ID·추천 이유·전체 수 |
| 데이터 전달 구조 | 통과 | `python scripts/validate_handoff.py` |
| UI HTTP 응답 | 200 | `http://127.0.0.1:5173/` |
| FastAPI 상태/목록 HTTP | 200 | `/health`, `/api/v1/stories?category=technology&limit=2` |
| UI→FastAPI→데이터→UI | 확인 | 브라우저 ‘FastAPI HTTP 모드’ 표시, 실제 API GET/OPTIONS 200 로그 |
| 검색/빈 결과 | 확인 | ‘반도체’ 검색 결과, 일치하지 않는 검색어의 빈 화면 |
| 카테고리/대기 상태 | 확인 | 기술 3개, story-009 상세의 요약 준비 중·출처 접근 |
| 더 보기 | 확인 | HTTP 모드에서 사건 카드 6개→12개 |
| 오류·복구 | 확인 | 503 시나리오의 오류·요청 ID, 정상 모드 복귀 |
| 북마크 | 확인 | 저장 후 카운트 변경, 새로고침 후 유지 |
| 요약/관점/출처 | 확인 | Radix 탭 이동과 근거 선택 시 출처 탭 이동·기사 강조 |
| 피드백 | 확인 | MSW/FastAPI POST 응답 테스트, UI에 영구 저장하지 않는 데모임을 표시 |
| PC 반응형 | 확인 | CSS viewport 1440×1000, 가로 넘침 없음 |
| 모바일 반응형 | 확인 | CSS viewport 390×844, 가로 넘침 없음, 상세 폭 390px |
| 브라우저 콘솔 | 확인 | 검사 시 비의도적 error/warn 없음 |
| npm 의존성 검사 | 통과 | Vitest 수정 버전으로 교체 후 npm audit 0 vulnerabilities |

브라우저 확인은 Codex in-app browser에서 수행했습니다. 실제 iOS/Android 기기, 스크린리더, 전체 접근성 인증, 모든 브라우저 호환성을 확인한 것은 아닙니다.

스크린샷: [PC](screenshots/desktop.jpg), [모바일](screenshots/mobile.jpg).

## 아직 검증/연결하지 않은 영역

- 실제 언론사 데이터의 수집·AI 이용·게시 권한.
- 실제 RSS/API 수집, 임베딩·군집, LLM 호출 및 요약 정확성.
- Supabase DB 연결, SQL 초안 실행, JWT 인증, RLS 계정 간 격리, 성능.
- 영구 피드백, 계정 동기화 북마크, 실제 작업 큐, 재시도·멱등성·게시 워크플로.
- 공개 호스팅·도메인·운영 배포.
- 인지적 필터 버블 감소 효과와 사용자 연구.

`database/schema.draft.sql`은 실행 검증된 마이그레이션이 아닙니다. 관리자 작업은 상태만 전환하는 시뮬레이션입니다. API 테스트 중 Starlette가 httpx TestClient 경로의 향후 변경에 대한 deprecation warning을 표시했으나 현재 고정한 직접 의존성 조합에서 테스트는 통과했습니다.

Windows 제한 환경에서 FastAPI 테스트가 asyncio 로컬 소켓 초기화에 대기하는 현상을 확인했고, localhost 접근이 허용된 실행 환경에서 동일 테스트를 통과시켰습니다. 일반 로컬 개발에서도 테스트가 멈춘다면 보안 정책의 localhost/loopback 접근을 먼저 확인하세요.

개발 서버는 검증용으로 실행했으며 전달 이후에는 README의 명령으로 다시 실행할 수 있습니다. 기본 설정은 서버 없는 브라우저 MSW 모드로 복원했습니다.
