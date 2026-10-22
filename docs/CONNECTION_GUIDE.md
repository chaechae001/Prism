# 정채은 작업 실행·통합 가이드

기준일: 2026-10-22. 이번 변경은 로컬 파일에 반영되었습니다. Supabase 스키마·민준님 RSS 코드·GitHub 브랜치는 변경하지 않았습니다.

**디자인 v2 업데이트:** 최신 UI 기준은 `UI_EDITORIAL_V2.md`, 최신 전달 코드는 `docs/handoffs/2026-10-22-chaeeun-editorial-v2.zip`입니다. 아래 실행 명령은 그대로 사용합니다. 이전 connection.zip은 디자인 변경 전 기록으로 보존했습니다.

## 1. 지금 확인할 실행 방법

PowerShell 터미널 두 개를 엽니다. Python 의존성과 프론트 의존성이 설치되어 있지 않으면 먼저 각각 `python -m pip install -r backend/requirements.txt`, `cd frontend` 후 `npm.cmd ci`를 실행합니다.

**터미널 A — 프로젝트 루트에서 API 실행**

```powershell
$env:PRISM_DATA_SOURCE='fixture'
python -m uvicorn app.connection_api:app --app-dir backend --host 127.0.0.1 --port 8000
```

**터미널 B — 프로젝트 루트에서 프론트 실행**

```powershell
cd frontend
npm.cmd run dev:http
```

[화면 열기](http://127.0.0.1:5173/) · [Swagger](http://127.0.0.1:8000/docs).

이 명령은 `.env.local`을 덮어쓰지 않고 프론트를 실제 HTTP 모드로 실행합니다. `npm.cmd run dev`는 기존 브라우저 Mock 모드입니다. 별도 `.env.local`이 있다면 그 설정도 확인해주세요.

2026-10-21의 가상 사건 12개·기사 46개를 사용하는 화면입니다. 오늘 날짜를 가상 기사 날짜로 변경하지 않습니다. 처음에는 불러온 모든 날짜를 보여주고, 사용자가 날짜를 선택할 때 필터링합니다. 달력의 숫자는 **현재 불러온 자료**의 날짜별 수이므로 추가 로드하면 늘어날 수 있습니다.

## 2. RSS가 준비되기 전 미리보기

터미널 A를 Ctrl+C로 종료한 다음 아래처럼 다시 실행하고 브라우저를 새로고침합니다.

```powershell
$env:PRISM_DATA_SOURCE='rss-fixture'
python -m uvicorn app.connection_api:app --app-dir backend --host 127.0.0.1 --port 8000
```

내부 RSS 샘플 2건 중 발행시각이 있는 1건이 표시되고, 날짜가 없는 1건은 보류됩니다. 실제 기사·실제 RSS 수집 결과가 아닙니다.

- 원문 제목·RSS 설명과 AI가 만든 중립 제목·요약을 구분합니다.
- 한 기사를 표시하기 위한 임시 Story이며, 군집 결과가 아닙니다. 출처 1개, 관점 0개, 요약 pending입니다.
- HTML은 일반 텍스트로 정리하고 이미지는 표시하지 않습니다.
- 날짜 없음·미래 발행·이용 범위 미확인 항목은 보류하고 피드 하단 ‘개발 연결 상태’에서 사유를 확인할 수 있습니다.
- 현재 내부 rights에 별도 ‘제목/설명 재표시’ 필드가 없으므로 adapter는 collect/store/publish_summary가 모두 allowed일 때만 보수적으로 표시합니다. 이는 허용 범위 확인의 대체 수단이 아니며, unknown을 임의로 allowed로 바꾸지 않습니다. 실제 매체의 메타데이터 재표시만 허용되는 경우에는 근거를 검토해 내부 정책을 별도로 합의합니다.
- 미리보기 ID는 canonical URL 기반이며 최종 사건 ID가 아닙니다. 최종 군집으로 바뀐 뒤 임시 보관 항목이 그대로 연결된다고 보장하지 않습니다.

## 3. 민준님 코드와 합칠 때

이번 API는 **별도 `app.connection_api:app` 실행 진입점**입니다. 민준님이 수정 중인 `main.py`·`db.py`·`rss/`·migration을 덮어쓰지 않습니다. 공개 API의 기존 필드와 경로는 유지합니다.

| PRISM_DATA_SOURCE | 실제 읽는 것 | 현재 로컬 사용 가능 |
| --- | --- | --- |
| fixture | 기존 가상 사건 12개 | 가능 |
| rss-fixture | 내부 RSS 예시 JSON 2건 | 가능, 1건 표시·1건 보류 |
| db-demo | `news_repository.get_news_from_db('story-001')` | 민준님 DB 조회 코드와 설정을 합친 뒤 가능 |
| rss-reader | `rss.reader.list_rss_records(limit=100)` | 민준님 reader와 DB 설정을 합친 뒤 가능 |

DB/reader 오류를 가상 데이터로 조용히 바꾸지 않습니다. `/health`는 서버 생존 확인이며 DB 준비 확인이 아닙니다. `/api/v1/stories`가 성공해야 데이터 연결을 확인한 것입니다.

민준님 reader 조건:

```python
# 최민준 담당 backend/app/rss/reader.py
def list_rss_records(limit: int = 100) -> list[dict]:
    ...  # docs/architecture/rss-record-v1.schema.json에 맞는 배열
```

최대 100건을 읽는 현재 연결 코드는 개발용입니다. 피드의 total도 이 범위 안의 표시 가능한 건수입니다. 전체 운영 데이터의 검색·정렬·페이지 처리를 DB 쿼리로 이관하는 작업은 후속입니다.

**정채은 브랜치에 코드 반영 순서**

1. GitHub 저장소 최신 코드를 별도 정상 Git 체크아웃에서 받습니다. 변경 중인 파일이 있으면 먼저 보존합니다.
2. 정채은 작업 브랜치에서 `frontend/` 소스와 아래 연결 파일을 반영합니다. 확인한 원격 `feat/backend-api`에는 frontend/.gitkeep만 있어 실행 가능한 프론트 전체 소스를 ZIP에 포함했습니다. node_modules·dist·개인 환경변수는 제외했습니다. 이 로컬 폴더 전체를 공유 저장소 위에 복사하지 않습니다.
3. 연결 API 지원 모듈인 기존 `models.py`·`repository.py`·`recommendation.py`, `contracts/fixtures.json`, RSS 샘플 JSON도 필요합니다. 공유 저장소에 같은 파일이 이미 있다면 diff를 확인하고 필요한 부분만 반영합니다.
4. `docs/worklogs/2026-10-22-chaeeun-implementation.md`의 변경 목록과 테스트를 확인하고 PR/병합으로 공유합니다. 이 작업에서 원격 push/PR은 수행하지 않았습니다.
5. 실제 통합 때 `$env:PRISM_DATA_SOURCE='rss-reader'`로 API를 재시작하고 프론트를 새로고침합니다. 프론트는 `dev:http` 그대로입니다.

새 연결 코드 묶음: `docs/handoffs/2026-10-22-chaeeun-connection.zip`. **이미 보낸 민준님 RSS 요청 ZIP의 수정본이 아닙니다.** 정채은 작업을 공유 저장소에 옮길 때 쓰는 파일 묶음입니다. 압축 내 `TRANSFER.md`와 파일 목록을 먼저 확인해주세요.

## 4. API 연결 체크

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/stories?mode=balanced&diversity=70&limit=6'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/categories'
```

목록의 `items[0].story.id`를 사용해 `/api/v1/stories/{id}`를 조회합니다. 프론트는 ID 형식을 해석하지 않습니다. DB가 실패하면 서버 콘솔의 요청 ID와 화면 오류를 함께 확인합니다. 피드백은 응답하되 `persisted=false`이며 DB에 저장하지 않습니다.

다른 프론트 주소를 쓸 때는 API 실행 전 아래처럼 설정합니다. 기본값은 localhost와 127.0.0.1의 5173만 허용합니다.

```powershell
$env:CORS_ORIGINS='http://127.0.0.1:5173,http://localhost:5173'
```

API 주소가 다르면 프론트 실행 전 `VITE_API_BASE_URL`을 API Origin으로 설정합니다. `/api/v1` 경로를 붙이지 않습니다. Supabase 비밀 키는 프론트 설정에 넣지 않습니다.

## 5. 단계 완료 체크

- [x] 브라우저 Mock 없이 FastAPI HTTP로 피드 표시
- [x] 검색·페이지 추가 로드·상세·출처·기본 오류 응답 확인
- [x] 보라색 모바일 타임라인과 PC 반응형 확인
- [x] RSS 샘플의 요약 없음·날짜 없음 처리
- [ ] 공유 저장소 정채은 브랜치 반영·병합
- [ ] 실제 RSS DB reader로 같은 URL/제목/날짜가 화면까지 이어지는지 확인
- [ ] 실제 군집·LLM 요약·정렬 정책 검증
- [ ] 계정 동기화·배포 환경·운영 검증
