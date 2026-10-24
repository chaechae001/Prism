# Supabase에 원문·사진 URL·군집 결과 저장

이 작업자는 기존 수집·군집 결과를 검증한 뒤 `private.prism_cluster_*`에 배치 단위로 저장합니다. 기존 뉴스 테이블과 다른 작업자의 저장 영역을 덮어쓰지 않습니다. HTTP 수집, 모델 실행, LLM 호출과 뉴스 게시를 저장 명령에서 수행하지 않습니다.

## 접속 설정

프로젝트 루트 `.env`에 `.env.example`의 DB 항목을 설정합니다. 현재 Python 서버 방식은 Supabase **Session pooler**를 사용하며 SSL을 요구합니다. 연결 방식은 [Supabase 공식 안내](https://supabase.com/docs/guides/database/connecting-to-postgres)를 참고합니다. 비밀번호는 이 로컬 파일에만 보관하고 GitHub나 브라우저 환경변수에 넣지 않습니다. 기존 `.env`가 있으면 내용을 통째로 교체하지 않습니다.

기본 의존성은 `backend/requirements.txt`에 이미 포함되어 있습니다. 독립 환경은 `CLUSTERING_HANDOFF.md`의 설치 절차를 따릅니다. 아래 명령은 설치된 Python 환경에서 프로젝트 루트를 기준으로 실행합니다.

```powershell
python -m backend.app.cluster_store schema
```

기본 실행은 읽기 전용 검사입니다. 전용 저장 테이블이 없는 경우에 한해 다음 명령이 네 테이블을 하나의 트랜잭션으로 만듭니다. 동일 이름의 다른 구조·버전·권한이 발견되면 중단하며 기존 테이블을 고치지 않습니다.

```powershell
python -m backend.app.cluster_store schema --apply
```

## 입력 준비와 검토

```powershell
New-Item -ItemType Directory -Path data/private/cluster-storage -Force | Out-Null
python -m backend.app.cluster_store prepare `
  --results-dir <기존-군집-결과-폴더> `
  --images <해당-결과에-연결된-이미지-manifest.json> `
  --namespace <배치-구분자> `
  --output data/private/cluster-storage/<새-배치>.json
python -m backend.app.cluster_store plan --batch data/private/cluster-storage/<새-배치>.json
```

`prepare`는 네트워크와 DB 설정을 사용하지 않습니다. `--images`는 선택 항목입니다. 출력 파일은 기존 파일을 덮어쓰지 않습니다. 출력에는 기사 전문이 있으므로 `data/private`처럼 제외된 로컬 위치를 사용합니다.

원본 `articles.json`, `representatives.json`, 선택적 `input.json` 및 이미지 manifest를 해시로 묶습니다. 기사 ID·제목·본문·URL·원래 카테고리·대표기사·군집 멤버를 유지합니다. 본문의 SHA-256과 제목+본문 코어 해시를 구분합니다. 이미지 manifest가 다른 입력을 가리키면 사진을 생략한 채 계속하지 않고 준비를 중단합니다.

수집·저장 용도가 각각 `allowed`인 기사만 실제 DB에 저장합니다. 원본 `rights`, `rights_snapshot`, 또는 `license_status`+문자열 배열 `allowed_uses` 선언을 검사합니다. 명시적 거부가 우선이고, 상충하거나 비어 있는 허용 상태는 승격하지 않습니다. 배치에 `unknown`·`denied` 기사가 하나라도 있으면 전체 저장을 SQL 실행 전에 거부합니다. 검증된 출처의 이용 상태를 입력에 함께 전달해야 하며 이 검사는 실제 허가의 진위를 인증하지 않습니다.

사진은 URL만 저장합니다. 표시 거부가 명시된 사진 URL은 제외하며, 불명 상태를 공개 표시 허용으로 바꾸지 않습니다. 이미지 파일을 다운로드하거나 Supabase Storage에 복제하지 않습니다.

## 실제 저장

```powershell
# --apply가 없으면 읽기 전용 계획만 출력합니다.
python -m backend.app.cluster_store store --batch data/private/cluster-storage/<새-배치>.json
python -m backend.app.cluster_store store --batch data/private/cluster-storage/<새-배치>.json --apply
```

본문·사진·군집·멤버는 한 트랜잭션으로 저장합니다. 일부 실패는 전체 취소됩니다. 배치 ID는 전체 입력 payload의 SHA-256에서 만들어지고 동일 배치 재전송은 `already_stored`를 반환합니다. 기존 배치를 업데이트하지 않습니다. 전송 중 결과가 불명확하면 같은 변경되지 않은 배치에 `plan`을 실행해 확인합니다. 자동 재시도는 하지 않습니다.

| 테이블 | 저장 내용 |
|---|---|
| private.prism_cluster_batches | 배치 해시·원본 파일 해시·기사/군집 수·검토 상태 |
| private.prism_cluster_articles | 원래 기사 ID·제목·원문·출처·사진 URL·허용 상태 |
| private.prism_cluster_groups | 군집 ID·대표기사 ID·검토 사유 |
| private.prism_cluster_members | 군집에 속한 기사 ID |

모든 테이블은 RLS를 사용하며 브라우저 및 service_role의 직접 테이블 접근을 허용하지 않습니다. 필요한 서버 DB 역할로 작업합니다. 실행 시 버전·컬럼·실제 테이블·RLS·권한·사용자 트리거를 다시 확인한 뒤 저장합니다.

이 저장은 비공개 분석 후보 적재입니다. `same_event_verified=false`, `automatic_publication=false`, `accuracy_measured=false`, `requires_human_review=true`가 유지됩니다. 이 단독 명령은 게시용 `public.stories`나 성공 포인터를 변경하지 않습니다. 별도의 [정기 수집 작업자](SCHEDULED_NEWS.md)는 저장 완료 후 전용 포인터를 갱신하며 `cluster-db` 모드에서 검토 전 후보로 표시합니다. 기존 게시 뉴스 소스는 그대로 유지됩니다.

## 현재 92개 기사 결과

기존 `anchor92` 입력은 기사 92개·군집 74개·사진 URL 92개가 준비 검증을 통과했습니다. 수집·저장 허용 상태는 모두 `unknown`이므로 실제 기사 배치는 업로드하지 않습니다. 이 입력과 벡터·군집·이미지 원본은 수정하지 않습니다. 가상 기사 두 개와 한 군집으로 별도의 저장·재전송·롤백 검증을 수행합니다.
