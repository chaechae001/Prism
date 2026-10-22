# PostgreSQL · Supabase 연결

## 서버 설정

루트 `.env.example`의 DB 항목을 루트 `.env`에 입력합니다. Supabase Connect 화면에서 Session pooler 값을 확인합니다. 접속 정보와 키는 서버에서만 사용합니다.

```dotenv
DB_HOST=YOUR_SESSION_POOLER_HOST
DB_PORT=5432
DB_NAME=postgres
DB_USER=YOUR_DATABASE_USER
DB_PASSWORD=YOUR_DATABASE_PASSWORD
PRISM_DATA_SOURCE=supabase
CORS_ORIGINS=http://127.0.0.1:5183,http://localhost:5183
```

SSL은 기본 require이며 원격 DB의 비암호화 연결은 허용하지 않습니다. 접속 풀은 기본 3개와 추가 2개로 제한합니다. 프로세스 환경변수 → 루트 .env → backend/.env.chat.local 순서로 우선합니다. 동일 키를 여러 파일에 중복 정의하지 않습니다.

```powershell
python -m pip install -r backend/requirements.txt
python -m backend.app.worker check-db
python -m uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 8004
```

프론트는 `VITE_API_BASE_URL=http://127.0.0.1:8004`를 설정하고 `npm.cmd run dev:http -- --port 5183`으로 실행합니다. DB 설정이 없으면 자동으로 가상 자료로 대체하지 않습니다.

## 데이터 소스

| PRISM_DATA_SOURCE | 용도 |
|---|---|
| fixture | 기본 가상 뉴스 |
| supabase | DB에 게시된 사건·공개 가능한 기사 조회 |
| db-demo | DB의 story-001 한 건 연결 확인 |
| rss-reader | 공통 RSS JSON을 단일 기사 미리보기로 변환 |
| rss-fixture | 포함된 RSS 예시 변환 확인 |

공개 뉴스와 RSS 미리보기는 다른 단계입니다. RSS 저장만으로 사건·AI 요약·게시 상태를 자동 생성하지 않습니다. 현재 supabase 조회는 최대 500개 사건을 읽고 기존 API의 검색·정렬·커서를 적용합니다. 초과 시 오류로 중단하며 대규모 운영 전 SQL 페이지 조회로 전환해야 합니다.

## DB 파일

`database/schema.draft.sql`은 기본 테이블 참고이며, `database/migrations/20261022_001_add_rss_tables.sql`은 RSS 테이블의 기존 추가 SQL입니다. 새 빈 테스트 DB에만 순서대로 적용합니다. 이미 테이블이 있는 DB에 재실행하지 않습니다. `database/seed_demo.sql`은 가상 사건·기사용입니다.

현재 연결은 public.stories/articles/story_articles/publishers와 private.rss_items/rss_feeds/raw_articles/summary_versions를 사용합니다. 브라우저는 private 스키마를 직접 조회하지 않습니다. 서버 DB 계정은 필요한 최소 권한으로 운영하고 공개 API에서도 게시·출처 조건을 검사합니다.

## 본문과 기사 ID

`python -m backend.app.worker import-bodies --input <배치 JSON>`으로 기존 기사에 본문을 연결합니다. 형식은 contracts/analyst-batch.schema.json입니다. canonical_url과 publisher_id가 기존 기사와 일치해야 하며 입력 ID가 달라도 DB article_id로 매핑합니다. content_hash는 전달한 본문의 UTF-8 SHA-256이어야 합니다.

본문·이용 범위가 변경되면 연결된 사건 버전을 올리고 공개 요약을 pending으로 돌립니다. 같은 배치를 다시 넣어도 내용이 같으면 버전을 반복 변경하지 않습니다. 원문은 private.raw_articles에만 저장하며 피드 응답에 포함하지 않습니다.

## 요약 처리

```powershell
python -m backend.app.worker prepare-rss --record-id <RSS_RECORD_ID>
python -m backend.app.worker summarize --story-id <STORY_ID>
python -m backend.app.worker approve --version-id <SUMMARY_VERSION_ID>
```

prepare-rss는 허용 조건이 확인된 기사로 미게시 사건을 만듭니다. summarize는 본문을 모델에 전송하고 private.summary_versions에 pending 초안을 저장합니다. 각 기사 본문은 최대 30,000자, 한 실행은 최대 10기사입니다. 실제 생성은 사용량이 발생하며 자동 재시도하지 않습니다. 현재 CLI는 한 사건에 한 작업씩 실행합니다. 동시 실행의 중복 모델 호출 제어는 분산 작업 시스템 도입 시 보강해야 합니다.

approve는 검토한 초안에만 실행합니다. 기사 메타데이터의 publish_allowed, 본문 처리·요약 게시 조건, 사건 버전과 본문 해시를 다시 확인합니다. 성공 시 기존 Story.summary 형태로 저장해 카드에 표시합니다. 기사 메타데이터 공개 승인은 별도 관리하며 이 명령이 임의로 허용하지 않습니다.

여러 기사는 각각 요약한 결과를 묶고 '기사별 본문 요약 모음 · 사건 통합 요약 아님'으로 표시합니다. 다중 출처의 합의·정치 성향·관점은 생성하지 않습니다. 별도의 군집·사건 통합 요약은 후속 단계입니다.

## 검증

자동 테스트의 PostgreSQL은 Supabase와 분리된 새 로컬 prism_test DB입니다. 테스트는 루프백 주소와 해당 DB 이름만 허용하며 테스트 DB를 초기화합니다. 운영·개발 Supabase의 접속 주소를 테스트 변수에 넣지 않습니다. GitHub Actions는 별도 PostgreSQL 17 서비스에서 같은 검증을 실행합니다.

```powershell
python -m unittest backend.tests.test_api backend.tests.test_connection backend.tests.test_social_chat -q
python -m unittest discover -s backend/tests/rss -p 'test_*.py' -q
python -m unittest discover -s backend/tests/llm -p 'test_*.py' -q
# 새 전용 테스트 DB에 한해 PRISM_TEST_DATABASE_URL 설정 후 실행
python -m unittest backend.tests.test_database_integration -q
```
