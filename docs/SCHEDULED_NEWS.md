# 정기 수집 → DB → 군집 대표기사 → 웹

기존 RSS 원문 수집기와 E5 `multiview-anchor` 군집 모델을 별도 Python 작업자로 연결했습니다. 작업자가 실행되는 동안 한 주기 종료 후 900초(15분)를 기다린 뒤 다시 실행합니다. 웹은 DB의 마지막 성공 배치를 60초마다 확인합니다. 수집·분석·저장이 실패하면 화면은 이전 성공 결과를 유지합니다.

테스트 스냅샷에는 테스트용 허용 상태와 `publisher_permission_verified=false`가 함께 기록되어 있습니다. 새 수집 작업은 설정 파일의 출처별 이용 범위에 따라 실행합니다. 실제 언론사 허가를 확인했다는 의미는 아닙니다. 기존 `anchor92`의 unknown 권한과 원본은 수정하지 않았습니다. LLM은 호출하지 않으며 같은 사건 검증·요약 완료 표시를 만들지 않습니다.

## 실행 구성

```text
RSS 제목·ID·언론사·날짜 + 동일 기사 원문·사진 URL
    → private.prism_ingest_articles (먼저 커밋)
    → 최근 72시간 최신 버전을 DB에서 다시 읽음
    → 기존 E5 군집화 / 대표기사 1개 선택
    → private.prism_cluster_* 배치 저장
    → private.prism_cluster_heads 성공 포인터 변경
    → FastAPI /api/v1/stories
    → 반응형 웹 피드·상세·출처
```

기존 `public.stories`, `public.articles`에는 쓰지 않습니다. HTTP 조회가 크롤러·모델을 실행하지도 않습니다. 전용 테이블에는 RLS를 적용하고 브라우저·anon·authenticated·service_role의 직접 접근을 허용하지 않습니다.

## 설정과 실행

새 환경은 기존 `requirements-clustering.txt` 의존성을 설치하고 E5 `tokenizer.json`, `onnx/model_quantized.onnx`를 로컬에 준비합니다. 이 작업자는 모델을 자동 다운로드하지 않습니다. 서버용 DB 설정은 루트 `.env`를 사용하며 비밀번호를 웹 환경변수에 넣지 않습니다.

`config/scheduled-news.example.json`을 `data/private/scheduled-news/settings.json`으로 복사해 모델·작업 폴더와 출처 설정을 입력합니다. 상대 경로는 설정 파일이 있는 폴더를 기준으로 합니다. 예제 출처는 기본 비활성·unknown입니다. 이용 범위를 확인한 출처에 한해 비공개 설정을 작성합니다.

프로젝트 루트에서 실행합니다. 분석 패키지를 editable로 설치하지 않았다면 먼저 `PYTHONPATH`에 프로젝트의 `analysis`와 루트를 추가합니다.

```powershell
$env:PYTHONPATH="$PWD\analysis;$PWD"
python -B -m backend.app.scheduled_news check --config data/private/scheduled-news/settings.json
python -B -m backend.app.scheduled_news schema --config data/private/scheduled-news/settings.json

# 이미 설치돼 있으면 변경하지 않음. 기존 군집 저장 스키마가 먼저 필요합니다.
python -B -m backend.app.scheduled_news schema --config data/private/scheduled-news/settings.json --apply

# 1회 실행 / 계속 실행. --apply 없이는 수집과 저장 없이 설정만 출력합니다.
python -B -m backend.app.scheduled_news once --config data/private/scheduled-news/settings.json --apply
python -B -m backend.app.scheduled_news run --config data/private/scheduled-news/settings.json --apply
```

Windows에서는 `scripts/run-scheduled-news.ps1 -Python <python.exe> -Apply`도 사용할 수 있습니다. `-Once`는 한 번 실행합니다. Ctrl+C로 반복 실행을 종료합니다. PC나 프로세스가 종료되면 자동 실행도 끝납니다. OS 부팅 시 등록은 포함하지 않았습니다.

설정의 핵심 항목은 다음과 같습니다.

| 항목 | 기본값 / 동작 |
|---|---|
| namespace | 수집·분석·화면을 연결하는 독립 데이터 이름 |
| interval_seconds | 900, 작업 종료 후 대기 시간 |
| window_hours | 72, 최근 발행 기사 분석 범위 |
| limit_per_feed | 예제 100, 한 RSS의 한 주기 요청 상한 |
| max_articles | 500, 초과 시 결과 교체를 멈추고 오류로 기록 |
| refetch_seconds | 21600, 기존 기사 재확인 간격 |
| profile | multiview-anchor, 기존 고도화 모델 |
| analysis_revision | scheduled-v1, 알고리즘/설정 변경 시 새 값 사용 |
| sources | 기존 khan/sbs/mk 중 활성 여부와 다섯 이용 범위 |

아직 받지 못한 기사를 먼저 요청하고, 나머지 예산으로 오래전에 확인한 기사를 다시 받습니다. RSS에 미수집 기사가 요청 상한보다 많으면 원문은 DB에 보관하되 결과 교체를 보류하고 다음 주기에 나머지를 처리합니다. 이미 DB에 있는 기사의 재확인 예산 보류는 별도 건수로 기록합니다. 실패한 RSS가 있으면 성공한 수집 결과는 남기고 새 피드 교체는 보류합니다. robots 차단을 우회하지 않습니다.

## DB 결과를 웹에 표시

DB 미리보기를 실행할 때 다음 설정을 별도로 지정합니다. 파일 미리보기는 `scripts/run-cluster-preview.ps1`을 사용합니다.

```powershell
$env:PRISM_DATA_SOURCE='cluster-db'
$env:PRISM_CLUSTER_NAMESPACE='scheduled-local-test'
$env:PRISM_CHAT_ENABLED='0'
python -B -m uvicorn backend.app.api:app --host 127.0.0.1 --port 8004
```

다른 터미널에서 프론트를 실행합니다. 현재 `frontend/.env.local`은 HTTP·8004로 연결돼 있습니다.

```powershell
cd frontend
npm.cmd run dev -- --port 5183 --strictPort
```

[로컬 웹](http://127.0.0.1:5183/)은 DB의 성공 포인터만 읽습니다. 배치가 모두 저장되기 전에는 새 결과가 보이지 않습니다. 대표기사를 첫 출처로 유지하고 제목·원문 링크·관련 기사 수를 표시합니다. 기사 전문과 내부 권한/본문 해시는 API로 전달하지 않습니다. 사진은 입력의 `display_image=allowed`만 표시하며 파일 복제 없이 원문 이미지 URL을 연결합니다. AI 요약은 pending이고 화면에도 ‘동일 사건 검토 전’을 표시합니다. 기존 Story/Feed API 계약은 바뀌지 않았습니다.

## 중복·수정·실패 처리

원문은 namespace·기사 ID·내용/메타데이터 revision 해시로 보존합니다. 동일 입력 재수집은 관찰 시각만 갱신하고 원문을 추가하지 않습니다. 제목·본문·사진·권한이 바뀌면 새 revision을 저장합니다. A→B→A로 되돌아오면 마지막 관찰된 A가 다시 분석 입력이 됩니다. 기사 ID와 URL의 기존 연결이 충돌하면 저장을 중단합니다.

현재 분석 입력 해시는 기사·사진·권한·프로필·분석 revision·실제 모델/토크나이저 파일 해시를 포함합니다. 입력이 같으면 모델 실행과 결과 저장을 생략합니다. 모델 바이트를 교체하면 다시 분석합니다. 군집 ID는 배치의 사건 후보 식별자이며, 계속 보도되는 사건의 영구 ID나 교차 배치 병합을 보장하지 않습니다.

동일 namespace 작업은 PostgreSQL session advisory lock으로 중복 실행을 막습니다. 현재 Supabase session pooler를 사용하며 transaction pooler에는 적용하지 않습니다. 잠금 실패/대기 주기는 상태로 기록하고, 잠금 해제에 실패한 연결은 pool로 반환하지 않습니다. 잠금 방식은 [PostgreSQL 공식 설명](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)을 따릅니다.

`data/private/scheduled-news/status.json`에 마지막 주기 상태·건수·시각을 기록합니다. 원문·DB 접속 값·상세 예외는 로그에 쓰지 않습니다. 웹 무한 스크롤은 갱신 시 첫 페이지부터 순차로 읽어 새 커서를 받습니다. [TanStack Query의 무한 쿼리 갱신 동작](https://tanstack.com/query/latest/docs/framework/react/guides/infinite-queries)을 사용합니다.

## 이번 실제 테스트

처음 세 RSS를 요청했을 때 경향·매경은 `robots_disallowed`였고 SBS에서 29개 기사 전문과 사진 URL을 수집했습니다. 차단된 두 RSS는 로컬 설정에서 비활성화하고, SBS 기사 29개를 기존 모델로 분석해 20개 대표기사 후보를 DB와 화면에 연결했습니다. 이 수치는 정확도 평가 결과가 아닙니다. 원래 92개 입력과 공유 게시 테이블은 보존했습니다.
