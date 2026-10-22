> 보관된 승인 전 체크리스트입니다. 이후 사용자가 커밋·푸시를 승인했습니다. 현재 작업 기록은 [구조 정리 로그](worklogs/2026-10-22-personal-structure-and-push.md)를 확인하세요.

# 개인 Prism 첫 커밋·푸시 승인 전 검토

## 올릴 대상

- 원격: `https://github.com/chaechae001/Prism.git`
- 공개 레포이며 현재 빈 저장소. main의 첫 커밋으로 현재 소스를 올릴 예정.
- 예정 커밋 메시지: `feat: add social news UI and Elice article chat`
- 지금은 로컬 Git 초기화·origin 등록·변경 목록 준비까지만 진행. **커밋/푸시 승인 전**입니다.

## 포함

- 모바일/PC 뉴스 피드·테마·날짜 스토리·카테고리·사진 탐색·북마크·로컬 댓글·기사별 DM
- FastAPI v1 호환 기반과 엘리스 실제 호출 어댑터, 기존 계약·테스트·환경 예시
- 기존 설계/단계별 실험 소스와 마이그레이션 기록. 중단된 네이버 v2는 기본 실행 대상이 아님을 README에 명시
- 실행 README·협업 규칙·작업 로그·팀 통합 제안

## 제외

- 실제 키와 `.env.chat.local` 등 로컬 환경 파일
- node_modules, dist, 캐시, private/exports 분석 데이터
- 이전 전달 ZIP과 중복 handoff 패키지, 검증 스크린샷, 로컬 JSON 검증 산출물
- 팀 비공개 레포 파일. 아직 읽거나 합치지 않았음

업로드 후보의 실제 파일 목록·크기·SHA-256은 로컬 `docs/release/personal-upload-manifest.json`에 있습니다. 이 manifest는 환경별 검토 산출물이므로 Git에서 제외했습니다. `python scripts/preflight_personal_release.py`로 다시 생성합니다. 실제 로컬 키 값 일치 검사와 일반 키/JWT/개인키 패턴 검사를 수행하며 값은 출력하지 않습니다.

## 사용자 확인 후 할 일

1. 후보 파일과 원격 레포가 승인 내용과 같은지 재확인합니다.
2. 개인 레포 main에 첫 커밋·푸시합니다.
3. 원격에서 키 파일 제외·README·커밋 SHA를 다시 확인해 링크를 전달합니다.

## 팀 레포는 별도 단계

현재 팀은 비공개이며 연결 앱에서 404입니다. 사용자가 접근 권한을 확인 중입니다. [통합 계획](TEAM_INTEGRATION_PLAN.md)은 최신 팀 코드를 비교한 결과가 아닌 **접근 후 적용할 검토 절차와 구조 제안**입니다. 팀 원격 커밋·푸시·PR·병합은 아직 하지 않습니다.
