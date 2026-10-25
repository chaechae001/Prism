# 신규 기사·본문 입력

`intake-articles`는 기존 AnalystBatch 형식의 기사 메타데이터를 등록하고, 본문을 private.raw_articles에 연결합니다. 공개 API 형식과 화면은 변경하지 않습니다.

## 실행

```powershell
# 오프라인 파일 검증: DB 없이 실행
python scripts/validate_handoff.py <배치JSON>
# DB를 읽어 등록 계획만 확인: 저장하지 않음
python -m backend.app.worker intake-articles --input <배치JSON>
# 검증한 계획을 실제 저장할 때만 --apply 지정
python -m backend.app.worker intake-articles --input <배치JSON> --apply
# 가상 데이터 입력은 --demo를 명시
python -m backend.app.worker intake-articles --input <가상배치JSON> --apply --demo
```

입력 대상은 서버 DB 환경 설정을 사용합니다. 기존 DB를 초기화하거나 스키마를 다시 적용하지 않습니다. 기본 실행도 계획을 위해 DB 연결은 필요합니다. DB 없는 검증은 validate_handoff.py를 사용합니다.

`examples/article-intake.demo.json`은 가상 기사 입력 예시입니다. 기본 가상 seed의 p-01 / demo-group-p-01 매핑을 전제로 하며, 매체가 없거나 출처 그룹이 다르면 보류됩니다. 이 예시도 실제 저장 시에는 --demo를 명시합니다.

## 처리 규칙

1. 본문 해시·배치 중복·빈 값·시간대·수집/저장 조건을 검사합니다.
2. publisher_id가 등록돼 있고 publisher_group_id가 DB와 같은지 확인합니다. 모르는 매체나 출처 그룹을 자동 생성하거나 덮어쓰지 않습니다.
3. 같은 원문 URL이 있으면 기존 DB 기사 ID를 사용합니다. 기존 기사 제목·발행시각·가상 여부·공개 허용 상태는 수정하지 않습니다.
4. 새 URL이면 정규화된 입력 URL의 SHA-256으로 내부 기사 ID를 만듭니다. 입력 기사 ID는 배치 추적용이며 기존 DB ID를 덮어쓰지 않습니다.
5. 새 기사는 publish_allowed=false로 등록합니다. 가상 여부는 --demo로 지정하며, --demo로 기존 실제 기사를 수정하는 것은 거부합니다.
6. 신규 메타데이터와 본문은 하나의 트랜잭션에서 저장합니다. 오류가 나면 신규 기사·본문·사건 버전 변경이 모두 취소됩니다.
7. 기존 본문이 바뀌면 기존 규칙대로 연결 사건의 버전과 요약 상태를 갱신합니다. 같은 본문·이용 범위의 재입력은 중복 기사나 반복 버전 변경을 만들지 않습니다.

등록 계획은 읽기 전용 트랜잭션입니다. ready_for_intake는 해당 시점의 검증 결과이며 동시 입력 사이의 상태 변화를 보증하지 않습니다. 실제 저장에서 DB 고유 제약이나 동시 변경 충돌이 나면 전체 취소하며 자동 재시도하지 않습니다.

## 결과와 오류

결과는 기존 입력 검사 정보에 plan.new_article_count, plan.existing_article_count, ready_for_intake, intake_errors, applied를 추가합니다. 실제 저장 성공 시 written=true, body_changed_count를 반환합니다. 계획·입력 충돌에서는 written=false입니다. 오류 항목 위치는 0부터 시작하며 원문 URL·본문·비밀번호는 출력하지 않습니다.

| 오류 | 의미 |
|---|---|
| UNKNOWN_PUBLISHER | 등록되지 않은 매체. 출처 정보를 먼저 확인·등록 |
| PUBLISHER_GROUP_MISMATCH | 입력과 DB의 출처 그룹이 다름 |
| PUBLISHER_MISMATCH | 같은 URL의 기존 기사와 입력 매체가 다름 |
| ARTICLE_ID_CONFLICT | 생성한 내부 기사 ID가 다른 기존 기사와 충돌 |
| DEMO_EXISTING_ARTICLE | 가상 입력 모드로 실제 기사를 수정하려고 함 |

## 현재 범위

기사·본문 입력만 수행하며 사건 군집·사건 생성·요약·공개 게시를 실행하지 않습니다. 새 기사가 저장돼도 피드에 바로 나타나지 않습니다. 군집·검토·게시 경로는 별도 단계입니다. 처리 조건은 입력의 선언을 검사하며 실제 이용 조건을 자동으로 확정하지 않습니다.

현 articles 테이블에는 기사별 category 열이 없습니다. 입력의 category는 원본 배치에 유지하고 사건 카테고리·군집 연계 시 별도 저장 설계를 확정해야 합니다. 기존 기사 메타데이터의 정정·매체 등록·출처 그룹 변경도 이 명령에서 자동 수행하지 않습니다.
