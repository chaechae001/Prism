# 분석 입력 검증

## 입력 파일

본문 입력은 `contracts/analyst-batch.schema.json`과 기존 `AnalystBatch`를 유지합니다. `contracts/analyst-batch.example.json`은 가상 본문과 유효한 해시를 포함한 형식 예시입니다. 예시 URL은 DB에 등록돼 있지 않을 수 있습니다.

| 필드 | 입력 기준 |
|---|---|
| schema_version / batch_id | 1.0 / 재전달 배치를 추적할 식별자 |
| id | 배치 안에서 중복되지 않는 안정적인 기사 ID |
| canonical_url | DB 기사와 매핑할 원문 URL. ID가 달라도 URL·매체가 맞으면 연결 가능 |
| publisher_id / publisher_group_id | 백엔드의 매체·출처 그룹 식별자와 의미를 맞춤. 임의 정치 성향 라벨로 사용하지 않음 |
| title / text | 공백만 있는 값 금지. text는 RSS 설명이 아닌 확보한 본문 |
| published_at / collected_at | 시간대 필수. 발행 시각을 수집 시각으로 대체하지 않음 |
| category | politics / economy / society / technology |
| content_hash | 전달하는 text 문자열을 UTF-8로 인코딩한 SHA-256 소문자 16진수 |
| license_status / allowed_uses | 확인한 상태를 입력. collect·store 없으면 저장 보류, summarize·publish_summary는 별도 조건 |

허용 여부 필드는 입력의 선언을 검사할 뿐 원문 이용 조건의 유효성을 자동으로 판정하지 않습니다. 확인 근거는 수집 메타데이터와 함께 별도로 관리합니다. 계약에 없는 추가 필드를 배치에 임의로 넣지 않습니다.

## 검사 실행

프로젝트 최상위 폴더에서 실행합니다.

```powershell
# DB·API 키 없이 검사
python scripts/validate_handoff.py contracts/analyst-batch.example.json
# 동일한 worker 명령
python -m backend.app.worker validate-batch --input contracts/analyst-batch.example.json
# 기존 DB 기사가 있는지 읽기 전용 확인
python -m backend.app.worker validate-batch --input <배치JSON> --check-db
```

기본 검사는 네트워크·DB·LLM에 연결하지 않습니다. 성공은 종료 코드 0, 입력 오류 또는 매핑 불일치는 1입니다. DB 연결 자체가 실패하면 기존 worker의 일반 오류 형식으로 반환합니다. --check-db는 읽기 전용 트랜잭션과 매개변수 조회를 사용하며 기사를 생성하거나 본문·요약·게시 상태를 변경하지 않습니다.

```json
{
  "valid": true,
  "article_count": 1,
  "storage_eligible_count": 1,
  "errors": [],
  "warnings": [],
  "database_checked": false,
  "written": false
}
```

DB 검사 시 mapping에 matched_count, missing_article_indices, publisher_mismatch_indices와 ready_for_import가 추가됩니다. 기사 위치는 **0부터 시작하는 배열 인덱스**입니다. 원문·URL·입력 ID·비밀번호는 보고서에 출력하지 않습니다. ready_for_import는 메타데이터 매핑 검사 결과이며 저장 실행·성공을 의미하지 않습니다.

storage_eligible_count는 선언한 수집·저장 조건을 충족한 건수입니다. 본문 해시 등 다른 검사를 통과한 건수와 같다는 뜻은 아닙니다. 전체 입력 통과 여부는 valid와 errors를 확인합니다.

## 오류와 경고

| 구분 | 코드 | 처리 |
|---|---|---|
| 오류 | INVALID_STRUCTURE / BLANK_FIELD / EMPTY_BATCH_ID | 필수 필드·자료형·시간대·빈 값 수정 |
| 오류 | HASH_MISMATCH | 최종 text와 해시를 함께 수정 |
| 오류 | DUPLICATE_ID / DUPLICATE_URL | 배치를 정리한 후 재검사. 자동 덮어쓰기 금지 |
| 오류 | INVALID_TIME_ORDER | 수집 시각이 발행 시각보다 앞서는 원인 확인 |
| 오류 | STORAGE_NOT_ALLOWED | 수집·저장 조건이 확인되지 않은 항목을 분리·보류 |
| 오류 | URL_CREDENTIALS | URL에서 사용자명·비밀번호 제거 |
| 오류 | FILE_TOO_LARGE / BATCH_TOO_LARGE / BODY_TOO_LARGE | 파일 25MiB·배치 1,000건·본문 200,000자 이하로 분할 |
| 경고 | DUPLICATE_BODY | 서로 다른 URL의 같은 본문을 확인. 다른 출처를 자동으로 제거하지 않음 |
| 경고 | SUMMARY_NOT_ALLOWED | 저장 가능 여부와 요약·게시 가능 여부를 구분 |
| 경고 | SUMMARY_EXCERPT | 현재 요약기는 앞 30,000자를 사용. 후반부 사실 누락 가능성 검토 |

파일 크기와 배치 제한은 로컬 입력 도구의 안전한 처리 범위입니다. 기존 공개 뉴스 API의 JSON 응답과 필드는 변경하지 않습니다. 검증 실패한 배치는 본문 저장 함수에서도 DB 접근 전에 거부합니다.

## 실제 저장과의 관계

```text
JSON 파일 → 오프라인 검사 → 선택적 DB 매핑 검사
                             ↓
                 신규 기사라면 메타데이터 먼저 등록
                             ↓
                   import-bodies로 명시적 저장
                             ↓
                    군집·요약·검토·게시 연결
```

validate-batch는 신규 기사 메타데이터를 생성하지 않습니다. 기존 import-bodies는 URL과 publisher_id로 이미 등록된 기사를 찾습니다. 신규 기사 등록과 본문을 함께 저장하려면 [신규 기사·본문 입력](ARTICLE_INTAKE.md)의 intake-articles를 사용합니다. 매체는 먼저 등록돼 있어야 하며 실제 저장은 --apply를 명시한 경우에만 실행합니다.

```powershell
python -m backend.app.worker import-bodies --input <검증된배치JSON>
```

본문이 변경되면 기존 저장 로직에 따라 연결 사건의 버전이 올라가고 요약이 pending이 됩니다. 사전 검사는 요약·군집·게시를 실행하지 않습니다. 서로 다른 실행 사이에 DB 상태가 바뀔 수 있으므로 실제 저장 단계의 검증과 트랜잭션은 유지합니다.

## 분석 입력과 평가에 필요한 자료

1. **articles.json**: 기존 배치 계약에 맞는 기사 메타데이터와 본문. 먼저 같은 사건의 서로 다른 매체 기사와 다른 사건 기사가 포함된 작은 샘플을 사용합니다.
2. **publishers.csv 또는 JSON**: publisher_id, 매체명, publisher_group_id의 고정 매핑. 배치의 출처 그룹 의미와 DB 출처 그룹을 맞춥니다.
3. **event_labels.csv**: article_id, expected_event_id, review_status, reason. 동일 주제·다른 사건, 속보·후속 보도, 복제 기사, 판정 보류 사례를 포함합니다. 이는 평가용 제안 형식이며 아직 운영 군집 결과 입력 계약은 아닙니다.
4. **quality_report.csv 또는 JSON**: 수집·본문 확보·중복·날짜 누락·권한 미확인·실패 건수와 집계 기준. 원문 전체를 오류 로그에 남기지 않습니다.
5. **dataset README**: 수집 기간·시간대·수집기/정제 버전·소스·본문 확보 방식·이용 범위 확인 근거·결측 처리 규칙. 학습/평가를 나누면 중복 기사와 동일 사건의 누출 여부를 함께 기록합니다.

모델 코드가 준비되기 전에도 위 자료와 오류 샘플을 기준으로 입력·UI 상태를 검증할 수 있습니다. 평가용 정답과 실제 모델 출력은 구분합니다. 군집 결과 저장과 사건 통합 요약은 후속 연결 작업입니다.
