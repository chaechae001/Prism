# 군집분석 미리보기 테스트 데이터

저장된 기사 입력과 대표기사 결과를 API·화면 및 회귀 테스트에서 사용하는 고정 스냅샷입니다. 파일 크기와 SHA-256은 `manifest.json`으로 확인합니다. 분석 소스 기준은 `6a2eb2d`입니다.

| 폴더 | 기사 | 군집 / 대표기사 후보 | 용도 |
|---|---:|---:|---|
| anchor92 | 92 | 74 | 정치·경제·사회 미리보기 |
| scheduled-sbs | 29 | 20 | 경제 미리보기 |

두 묶음 모두 SBS 기사입니다. 중복 기사가 있을 수 있어 121건의 독립 표본으로 합산하지 않습니다. 같은 사건 정답 라벨은 없으며 군집 수는 정확도가 아닙니다. `automatic_publication=false`, `accuracy_measured=false`를 유지하고, 생성된 LLM 요약은 포함하지 않습니다.

원래 이용 상태를 보존합니다. `anchor92`는 unknown이며 `scheduled-sbs`의 allowed는 스냅샷 생성 당시 로컬 테스트용 선언입니다. `publisher_permission_verified=false`이므로 언론사 허가나 배포용 공개 데이터 선언을 뜻하지 않습니다. 이 자료는 내부 테스트용입니다.

## 포함 파일

- `input.json`: 제목·본문·RSS 메타데이터·이용 상태.
- `articles.json`: 분석에 사용한 정규화 기사.
- `representatives.json`: 군집별 대표기사와 관련 기사.
- `images.json`: 입력 해시에 연결된 사진 URL. 사진 파일은 포함하지 않습니다.

이미지 manifest가 참조하는 위 JSON의 원본 바이트를 보존했습니다. 모델 가중치·환경 파일·임베딩 캐시·벡터·HTML 보고서와 실행 이력은 포함하지 않습니다.

## 실행과 재분석

DB와 모델 없이 화면을 확인하려면 [미리보기 실행](../../docs/CLUSTER_PREVIEW.md)을 따릅니다. 새 입력 분석은 [분석 설치](../../docs/CLUSTERING_HANDOFF.md)와 [모델 준비](../../docs/MODEL_SETUP.md)를 참고합니다. 재분석 결과는 `clustering-output/` 아래 새 폴더에 생성합니다.
