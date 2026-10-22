# 데이터 계약

## 기사 입력

전체 형식은 `contracts/analyst-batch.schema.json`, 예시는 `contracts/analyst-batch.example.json`에 있습니다. `backend/app/models.py`의 AnalystBatch와 ArticleInput이 입력을 검증합니다.

| 필드 | 의미 |
|---|---|
| schema_version, batch_id | 계약 버전·배치 식별자 |
| articles[].id | 재수집에도 유지하는 기사 식별자 |
| canonical_url | 정규화한 원문 URL |
| publisher_id, publisher_group_id | 출처·출처 그룹 |
| title, text | 제목·처리 가능한 본문 |
| published_at, collected_at | 시간대를 포함한 발행·수집 시각 |
| category | politics / economy / society / technology |
| content_hash | 본문 중복 확인용 해시 |
| license_status, allowed_uses | 처리 가능 여부·허용된 작업 |

현재 스키마의 발행 시각은 필수입니다. 누락된 시각을 수집 시각으로 대체하지 않습니다. 예시 해시는 자리표시자이며 실제 입력에는 정규화한 본문의 해시를 사용합니다.

`pipeline.allowed_articles`는 collect·store·summarize·publish_summary가 모두 허용된 입력을 선별하고 URL·본문 해시 중복을 제거합니다. 이 함수는 실제 수집·군집·생성을 실행하지 않습니다.

```powershell
python scripts/validate_handoff.py contracts/analyst-batch.example.json
```

## 요약 출력

형식은 `contracts/summary-output.schema.json`에 정의합니다. 제목, 출처 ID를 포함한 핵심 문장, 관점, 확인되지 않은 내용을 구분합니다. `pipeline.validate_summary`는 독립 출처 그룹과 인용 ID를 확인하지만 내용의 사실성을 자동 보증하지 않습니다.

## 공개 뉴스

화면에는 `Story`의 제목·카테고리·제공된 요약·출처를 전달합니다. 입력 본문과 비공개 메타데이터는 기본 피드 응답에 포함하지 않습니다. 요약 상태는 pending / ready / insufficient_sources / failed로 구분합니다.

## RSS 미리보기

공통 RSS JSON 예시와 스키마는 `docs/architecture/rss-record-v1.*`에 있습니다. RSS 설명은 원문 제공 문구이며 생성된 요약과 구분합니다. 화면 변환은 발행 시각과 공개 조건을 확인하며 실제 수집과 군집을 수행하지 않습니다.
