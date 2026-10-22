# 분석가 ↔ 개발자 데이터 전달 계약

전체 스키마: `contracts/analyst-batch.schema.json`. 전달 예시: `contracts/analyst-batch.example.json`.
LLM 출력 스키마: `contracts/summary-output.schema.json`.

## 1. 분석가가 처음 전달할 것

처음부터 전체 수집 결과를 기다리지 않습니다. 팀이 파일 1개로 검증 가능한 작은 배치를 주고받으세요. 배치에는 안정적인 기사 ID, 정규화 URL, 출처/소유 그룹, 허용 본문, 작성/수집 시각, 카테고리, 중복 해시, 이용 권한을 포함합니다.

```json
{
  "schema_version":"1.0",
  "batch_id":"demo-batch-001",
  "articles":[
    {
      "id":"article-demo-001",
      "canonical_url":"https://example.com/demo/input-001",
      "publisher_id":"p-01",
      "publisher_group_id":"g-01",
      "title":"가상 뉴스 데이터 전달 예시",
      "text":"수집과 요약 및 게시가 허용된 본문을 여기에 전달합니다.",
      "published_at":"2026-10-21T09:00:00+09:00",
      "collected_at":"2026-10-21T09:10:00+09:00",
      "category":"technology",
      "content_hash":"demo-sha256-placeholder",
      "license_status":"allowed",
      "allowed_uses":["collect","store","summarize","publish_summary"]
    }
  ]
}
```

예시 해시는 자리표시자입니다. 실제 데이터에서는 **정규화한 본문의 SHA-256** 등 팀이 합의한 해시를 생성합니다. published_at을 알 수 없는 경우 임의로 현재 시각을 넣지 말고 전달 정책을 바꾸기 전에 개발자와 null/보류 규칙을 합의하세요. 현재 스키마는 출판 시각 필수입니다.

원문 제공/저장 가능 범위가 제한된 경우에는 본문을 무리하게 전달하지 않습니다. 권한 메타데이터와 허용된 발췌/요약 경로를 별도로 정하세요. RSS로 제목·URL을 받을 수 있다는 사실만으로 본문 수집·저장·LLM 처리·요약 게시 모두 허용된다고 가정하지 않습니다.

## 2. 필드의 의미

| 필드 | 합의할 의미 |
|---|---|
| id | 재수집에도 같은 기사를 가리키는 ID |
| canonical_url | 추적 파라미터 등을 정리한 대표 URL. 변경 규칙을 고정 |
| publisher_id | 실제 보도 주체 |
| publisher_group_id | 동일 소유/재전송 등 독립성 판단에 쓸 그룹의 첫 기준 |
| text | 파이프라인 입력으로 이용 가능한 본문. 공개 API로 전달하지 않음 |
| content_hash | 동일 본문 중복 발견용. 의미가 비슷한 기사는 임베딩으로 별도 비교 |
| license_status | allowed / unknown / denied. unknown은 처리/게시 보류 |
| allowed_uses | collect / store / summarize / publish_summary 중 허용된 작업 |

현재 `allowed_articles`는 네 가지 작업 모두 허용된 기사만 반환하고 URL/해시 중복을 제거합니다. 동일 본문의 재전송 기사도 각각의 출처 메타데이터는 운영 DB에 남겨야 하므로, 실제 저장 시에는 ‘중복 대표 본문’과 ‘원문 출처 관계’를 분리하세요. 데모 함수의 중복 제거만으로 운영 기사 이력을 대체하지 마세요.

권한 상태는 선언값을 검사할 뿐 권한의 법적 유효성을 자동 확인하지 않습니다. 확인 근거 URL·확인 날짜·정책 버전은 실제 수집 소스 레지스트리/비공개 저장소에 추가할 필드입니다.

## 3. 군집 결과의 별도 계약

학습용 라벨 번호와 서비스의 사건 ID를 구분하세요. 분석가는 다음 정보를 전달하는 것이 좋습니다. 아래는 **다음 통합 단계의 제안 형식**이며 이번 API가 수신하는 엔드포인트는 아닙니다.

```json
{
  "schema_version":"1.0",
  "batch_id":"batch-20261021-001",
  "model_version":"선정한-모델-버전",
  "event_candidates":[
    {
      "candidate_id":"candidate-01",
      "article_ids":["article-01","article-02"],
      "same_event_status":"needs_review",
      "reason":"동일 시간대, 동일 기관, 동일 발표를 다루는 후보",
      "nearest_story_id":null
    }
  ]
}
```

개발자는 사건 ID 생성·기존 사건에 기사 추가·사건 병합/분할·버전 관리를 담당합니다. 분석가는 후보의 근거와 오류 사례를 전달하고, 검증되지 않은 후보가 즉시 게시되지 않도록 합니다. 실제 도입 시 Pydantic 모델·JSON 스키마·멱등성 키를 먼저 추가하세요.

## 4. LLM 출력 규격

```json
{
  "title":"사건을 대표하는 제목",
  "bullets":[{"text":"제공 기사에 근거한 요약 문장","article_ids":["article-01","article-02"]}],
  "perspectives":[{"label":"강조하는 쟁점","text":"그 쟁점의 근거 있는 설명","article_ids":["article-02"]}],
  "unknowns":["기사만으로 확인할 수 없는 내용"]
}
```

`validate_summary`는 두 개 이상의 독립 소유 그룹 입력과 빈/잘못된 인용을 검사합니다. 스키마 통과는 내용의 사실성 검증이 아닙니다. 숫자·날짜·주체·단정 표현·충돌 정보를 별도로 검수하세요. 관점이 한 개밖에 없으면 억지로 세 개를 만들지 않습니다. 실제 검토 절차에서는 근거 부족 시 `insufficient_sources`, 생성 오류 시 `failed`, 검토 전 `pending`으로 두는 것이 좋습니다.

## 5. 평가 자료는 데이터 준비와 동시에 만들기

작은 정답 집합부터 만듭니다. 권장 출발 규모는 기사 쌍 100개 안팎이며 프로젝트 시간에 맞춰 조정하세요. 같은 사건/다른 사건, 같은 기관의 다른 날, 다른 기관의 같은 주제, 기사 정정, 통신사 재전송, 단독 보도, 관점 부족 사례를 포함합니다. 개발용/평가용 사건을 섞지 말고 이후 시간대의 사건으로도 확인하세요.

- 군집: 다른 사건을 합친 경우와 같은 사건을 나눈 경우를 구분해 사례 검토.
- 요약: 문장별 인용 존재, 인용 내용의 뒷받침, 숫자/날짜/주체 오류, 출처 간 충돌 누락.
- 출처: 서로 다른 도메인이라도 원문 재전송인지, 소유 그룹이 같은지 확인.
- 추천: 상위 목록의 주제/출처 구성이 넓어지는지, 관련성/품질이 떨어지지 않는지 확인.

데모의 숫자나 `public_interest` 값은 이 평가 결과가 아닙니다.

## 6. 재현·버전·작업 흐름

`batch_id`, 소스 레지스트리 버전, 전처리 버전, 임베딩 모델·차원, 군집 파라미터, 요약 모델·프롬프트 버전을 결과와 함께 기록합니다. 원문 변경·철회 시 해당 요약의 무효화/재검토가 가능해야 합니다.

워커는 단계마다 입력·출력·상태를 저장하고, `event_version + article_set_hash + model_version + prompt_version`을 중복 작업 키로 사용합니다. API는 저장된 결과를 조회합니다. 동일 배치 재처리는 덮어쓰기/무시/새 버전 중 정책을 정해 트랜잭션으로 처리하세요. 실패 시 전체 배치를 처음부터 무한 재실행하지 않고, 실패한 단계만 횟수를 제한해 재시도합니다.

구조 검증 실행:

```powershell
python scripts/validate_handoff.py contracts/analyst-batch.example.json
```

현재 예시는 기사 1건이므로 구조 검증은 통과해도 다중 출처 통합 요약 게시 조건에는 못 미칩니다. `validate_handoff.py`는 수집·모델 호출·DB 저장·게시를 실행하지 않습니다.
