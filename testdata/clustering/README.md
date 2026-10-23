# 군집분석 테스트 데이터

사용자 요청에 따라 기사 원문을 포함한 두 테스트 스냅샷을 공유합니다. 수집 기사·군집 후보·대표기사·사진 URL·벡터를 포함하며 사전 학습 모델 가중치, DB 접속 정보, 환경 설정, 임베딩 캐시는 포함하지 않습니다. 파일별 바이트 수와 SHA-256은 `manifest.json`에 있습니다.

| 폴더 | 기사 | 군집 / 대표기사 | 사진 URL | 용도 |
|---|---:|---:|---:|---|
| anchor92 | 92 | 74 | 92 | 이전 고도화 모델의 분석·검토 스냅샷 |
| scheduled-sbs | 29 | 20 | 29 | 정기 수집·DB·웹 연결에 사용한 SBS 스냅샷 |

두 스냅샷 사이에 중복 기사가 있을 수 있으므로 121건을 독립 평가 표본 수로 해석하지 않습니다. 같은 사건 정답 라벨은 없으며 군집 수는 정확도가 아닙니다. `same_event_confirmed=false`, `automatic_publication=false`, `accuracy_measured=false`를 유지합니다. 생성된 LLM 요약은 없습니다.

`anchor92`의 원래 unknown 이용 상태는 그대로 보존했습니다. `scheduled-sbs`의 allowed는 사용자가 승인한 로컬 테스트 설정이며 입력에 `publisher_permission_verified=false`를 기록했습니다. 언론사 허가 확인이나 배포용 공개 데이터 선언을 의미하지 않습니다. 해당 데이터는 팀 테스트용입니다.

## 파일

- `input.json`: 원래 제목·본문·RSS 메타데이터·이용 상태.
- `articles.json`: 분석에 사용한 정규화 기사. 본문을 포함합니다.
- `clustering.json`: 군집·유사도·판별 진단.
- `representatives.json`: 군집별 대표기사 1개와 관련 기사.
- `vectors.npz`, `lead-vectors.npz`: 전체/도입부 임베딩. 모델 가중치가 아닙니다.
- `images.json`: 입력 해시에 연결된 기사 사진 URL. 사진 파일은 포함하지 않습니다.
- `report.html`: 저장된 결과를 살펴보는 검토 화면.
- `run.json`, `handoff.json`, `skipped.json`: 해당 분석 단계의 실행·전달·제외 내역.
- `scheduled-sbs/batch.json`: 원문·사진·군집 저장 envelope. 실제 DB 접속 값은 없습니다.

사진 manifest가 참조하는 `input.json`, `articles.json`, `representatives.json`은 원본 바이트를 보존했습니다. `run.json`의 로컬 경로와 소요 시간은 스냅샷의 실행 이력이며 다른 PC에서 실행할 경로가 아닙니다. `shared_database_writes=0`은 파일을 만든 분석 단계에 대한 기록이고, 별도 저장 작업자의 동작은 [정기 수집 안내](../../docs/SCHEDULED_NEWS.md)를 참고합니다.

## 모델 없이 저장 결과 보기

프로젝트 루트에서 backend 의존성만 설치한 환경으로 실행할 수 있습니다. DB 설정과 모델 파일을 읽지 않는 로컬 미리보기입니다.

```powershell
$env:PRISM_DATA_SOURCE='cluster-local'
$env:CLUSTER_RESULTS_DIR="$PWD\testdata\clustering\anchor92"
$env:CLUSTER_IMAGES_PATH="$PWD\testdata\clustering\anchor92\images.json"
$env:PRISM_CHAT_ENABLED='0'
python -B -m uvicorn backend.app.api:app --host 127.0.0.1 --port 8004
```

`CLUSTER_RESULTS_DIR`과 `CLUSTER_IMAGES_PATH`의 `anchor92`를 `scheduled-sbs`로 바꾸면 현재 연결 자료를 볼 수 있습니다. 프론트는 [실행 안내](../../docs/SCHEDULED_NEWS.md)의 HTTP 모드로 연결합니다.

## 같은 입력 다시 분석

[군집 분석 설치](../../docs/CLUSTERING_HANDOFF.md)와 [고정 모델 준비](../../docs/MODEL_SETUP.md)를 완료한 뒤 새 출력 폴더를 사용합니다.

```powershell
New-Item -ItemType Directory -Path clustering-output -Force | Out-Null
.\.venv\Scripts\python.exe -m backend.app.clustering `
  --input testdata/clustering/anchor92/input.json --input-format collector `
  --output-dir clustering-output/anchor92-rerun `
  --profile multiview-anchor --model-dir .models/multilingual-e5-small
```

벡터는 해당 스냅샷의 입력·정렬 순서·모델에 묶여 있습니다. 새 입력에 그대로 재사용하지 않습니다. 공유 DB에 스냅샷을 다시 적재하지 않아도 결과 조회와 재분석을 할 수 있습니다.
