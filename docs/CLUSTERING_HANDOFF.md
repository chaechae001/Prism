# 로컬 군집화와 대표기사 선택

수집 담당자의 제목·본문·메타데이터를 받아 사건별 대표기사 후보 1개와 관련 기사들을 로컬 파일로 만듭니다. `backend.app.pipeline.Clusterer`에는 `backend.app.clustering.NewsClusterer`를 주입할 수 있습니다. 군집화는 배치 작업이며 HTTP 조회에서 모델을 실행하지 않습니다. 공개 `Story` 규격과 프론트 타입은 유지했습니다.

이 기능은 [chaechae001/Prism](https://github.com/chaechae001/Prism)의 `dev`를 기준으로 군집화·기사 사진·정기 수집·DB 결과 피드를 통합한 것입니다. 원문 수집 코드는 `analysis/rss_fulltext_crawler`, 분석 코드는 `analysis/news_clustering`, 서버 연결은 `backend/app/clustering`, `cluster_store`, `scheduled_news`에서 관리합니다. 사용자 요청에 따라 원문을 포함한 테스트 자료는 `testdata/clustering`에 함께 제공합니다. `.env`, 비밀번호, 가상환경, 사전 학습 모델 가중치와 임베딩 캐시는 포함하지 않습니다.

## 설치

프로젝트 루트의 PowerShell에서 실행합니다. 검증한 Python은 3.12.13입니다. 기존 `.venv`가 있으면 생성은 생략합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-clustering-dev.txt
.\.venv\Scripts\python.exe -c "import news_clustering; print(news_clustering.__file__)"
.\.venv\Scripts\python.exe -m backend.app.clustering --help
```

임포트 위치는 이 프로젝트의 `analysis/news_clustering`여야 합니다. 기존 분석 폴더를 `PYTHONPATH`에 추가하지 않습니다. 재사용한 알고리즘과 크롤러의 출처·해시는 `analysis/SOURCE_ORIGIN.json`에 기록했습니다. 의미 모델은 multilingual-e5-small ONNX int8입니다. [모델 준비 안내](MODEL_SETUP.md)에 따라 고정 버전과 해시를 확인하고 `tokenizer.json`, `onnx/model_quantized.onnx`가 있는 폴더를 지정하세요. 누락 파일은 작업자가 자동 다운로드하지 않습니다.

## 팀 데이터 계약으로 실행

기존 `models.AnalystBatch`와 `ArticleInput`을 받습니다. `content_hash`는 제공한 **본문 text 그대로**의 UTF-8 SHA-256입니다. 제목+본문으로 계산하는 코어 해시와 구분하며, 원래 본문·입력 메타데이터를 보존합니다. 해시나 공백을 자동 수정하지 않습니다. 기존 `services.body_import`와 같은 본문 해시 규칙입니다.

배치는 1~2000기사입니다. 시간대가 있는 발행·수집 시각, 고유 ID/대표 URL, 비어 있지 않은 제목·출처·소유 그룹, 공백뿐이 아닌 본문, `license_status=allowed`와 기존 네 허용 작업을 검사합니다. 선언값 검사는 실제 이용 허가를 확인한 결과가 아닙니다. 모호한 권한을 자동으로 허용하지 않습니다. 기존 일반 전달 예시의 해시는 자리표시자이므로, 아래의 실제 해시를 가진 **가상 예시**를 사용하세요.

```powershell
New-Item -ItemType Directory -Path clustering-output -Force | Out-Null
.\.venv\Scripts\python.exe -m backend.app.clustering `
  --input examples/clustering-analyst.synthetic.json `
  --output-dir clustering-output/synthetic-v2 `
  --model-dir <기존-모델-폴더>
```

본문이 같아도 ID와 출처가 다르면 기사 두 건을 유지합니다. 기존 `pipeline.allowed_articles`는 본문 해시로 중복을 제거하므로, 출처를 보존하는 이 워커에 넘길 때는 그 함수를 먼저 적용하지 않습니다. 본문 입력에 `rss_description`을 전문인 것처럼 넣지 않습니다. 팀 계약의 `text`는 담당자가 제공한 본문이라는 선언으로 취급합니다.

## 기존 크롤러의 저장 파일 분석

`article_id`, `title`, `body`, `body_kind`, 발행 시각과 출처 메타데이터가 있는 기존 `articles.json`/`results.json`은 다음으로 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m backend.app.clustering `
  --input <기존-크롤러-articles.json> --input-format collector `
  --output-dir clustering-output/fulltext-anchor `
  --profile multiview-anchor --model-dir <기존-모델-폴더>
```

이 모드는 **기존 자료의 로컬 분석**입니다. 원본의 불명 권한을 그대로 보존하며 팀 권한 검사를 통과했다고 표시하지 않습니다. 수집 실패, 빈 본문, `rss_description`은 분석에서 제외하고 `skipped.json`에 남깁니다. 기사 전문 대신 RSS 설명을 채우지 않습니다. 제목·본문·원문 ID를 유지하고 임의의 DB 기사 ID로 바꾸지 않습니다.

RSS·본문 수집 기능 자체도 원본 코드로 포함했습니다. 수집이 필요할 때만 `python -m news_clustering.bot --source sbs --model-dir <기존-모델-폴더> --output <새-폴더>`를 명시적으로 실행합니다. robots 정책으로 막힌 출처는 건너뛰며 우회하지 않습니다. 저장 입력 분석은 HTTP를 사용하지 않습니다.

## 출력과 프로필

| 파일 | 용도 |
|---|---|
| `representatives.json` | 군집마다 대표기사 1개, 관련 기사, 원래 메타데이터 |
| `clustering.json` | 기사 소속과 유사도·검토 진단 |
| `report.html` | 로컬 검토 화면 |
| `input.json`, `articles.json` | 변환 입력과 분석 기사; 본문 포함 |
| `vectors.npz`, `lead-vectors.npz` | 전체/도입부 벡터; 도입부 파일은 multiview만 생성 |
| `skipped.json`, `run.json`, `handoff.json` | 제외 사유, 실행 출처, 팀 입력/로컬 분석 구분 |

`v2`가 기본입니다. `multiview`, `multiview-dev`, `multiview-group`, `multiview-anchor`는 명시적 비교 옵션이며 최대 500개 분석 기사를 받습니다. 마지막 옵션은 제한적인 한국은행 금리 결정 원문 근거와 반복 본문 검토 표시를 사용합니다. 보편적인 사건 판별기나 정확도 개선이 입증된 모델로 표현하지 않습니다.

대표기사는 최종 군집 안에서 전체 의미 벡터의 평균 유사도가 가장 큰 기사입니다. 이 점수는 신뢰도나 보도 품질 확률이 아닙니다. 동일 사건이 확인된 결과도 아니므로 항상 검토가 필요합니다. 단독 기사의 점수는 null입니다. 게시·요약·공용 DB 저장은 실행하지 않습니다. 출력은 DB 저장 envelope가 아니며 공개 `story_id`도 만들지 않습니다.

출력 폴더는 새 경로여야 하고 부모 폴더는 먼저 만들어야 합니다. 실패하면 완료 폴더를 게시하지 않습니다. 기존 결과를 덮어쓰지 않으며, 임베딩 캐시는 결과 폴더 밖의 `data/private/clustering/e5.sqlite3`에 보관합니다. `.env`나 요약 제공자 설정은 읽지 않습니다.

## 팀 웹앱에서 저장 결과 보기

`cluster-local`은 별도 로컬 데이터 소스입니다. 기본 가상 피드와 기존 DB 모드는 유지합니다. 저장된 `representatives.json`과 `articles.json`을 읽어 기존 Story/Article API 규격으로 변환합니다. API 조회에서는 군집화·수집·DB 저장을 실행하지 않습니다.

프로젝트 루트의 새 PowerShell에서 실행합니다. 8004 포트에서 이 프로젝트의 API를 실행 중이면 그 서버를 먼저 종료합니다.

```powershell
$env:PRISM_DATA_SOURCE='cluster-local'
$env:CLUSTER_RESULTS_DIR=(Resolve-Path .\clustering-output\anchor92).Path
$env:PRISM_CHAT_ENABLED='0'
$env:CORS_ORIGINS='http://127.0.0.1:5183,http://localhost:5183'
.\.venv\Scripts\python.exe -m uvicorn backend.app.api:app --host 127.0.0.1 --port 8004
```

다른 터미널에서 기존 HTTP 프론트를 실행합니다.

```powershell
cd frontend
$env:VITE_API_BASE_URL='http://127.0.0.1:8004'
npm.cmd run dev:http -- --port 5183
```

`http://127.0.0.1:5183/`에서 군집별 대표기사 제목·본문 앞부분, 관련 기사 수와 원문 링크를 확인합니다. 대표기사의 원래 기사 ID를 보존하고 출처 목록의 첫 항목에 둡니다. 한국어 카테고리 이름은 기존 영문 API 코드로 대응시킵니다. 같은 사건 여부는 검토 전이며 `summary.status=pending`, 요약 문장/관점 목록은 비워 둡니다. 이미지 정보를 추가로 수집하면 대표기사의 실제 사진을 표시하고, 사진이 없으면 기본 화면을 표시합니다. 실제 뉴스에 예시 사진을 붙이지 않습니다. 이 소스의 유료 AI 대화는 설정 유무와 관계없이 비활성화합니다.

명시적으로 `cluster-local`을 선택하면 서버의 환경 파일 로딩을 건너뛰고 위에서 지정한 프로세스 환경값만 사용합니다. 저장 목록이나 상세 주소를 직접 열어도 로컬 사건 ID를 통해 발췌·검토 안내를 유지합니다. AI 분석 탭에서는 현재 연결하지 않은 기능을 안내하고 원문 출처 확인을 제공합니다.

파일이 없거나 기사 수·소속·대표기사·본문 해시가 맞지 않으면 503을 반환합니다. 오류 때 가상 뉴스로 대체하지 않습니다. 원본 분석 결과를 수정하지 않고 API에는 전체 본문·권한 메타데이터·임베딩을 전달하지 않습니다. 본문 앞부분 240자 이내의 발췌는 명시적으로 표시합니다. 로컬 미리보기는 게시 승인이나 동일 사건 정답을 의미하지 않습니다.

## 대표기사 이미지 URL 연결

군집 결과를 만든 뒤 별도 명령으로 이미지 주소를 수집합니다. 기존 결과 폴더 밖의 새 파일에 저장하며, 같은 출력 파일로 반복 실행하면 HTTP 요청 전에 중단합니다. 아래 명령은 프로젝트 루트에서 실행합니다.

```powershell
$imageOutput = 'data/private/article-images/images-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'
.\.venv\Scripts\python.exe -B -m backend.app.article_images `
  --results-dir clustering-output/anchor92 --output $imageOutput
$env:CLUSTER_IMAGES_PATH=(Resolve-Path $imageOutput).Path
```

같은 터미널에서 앞의 `cluster-local` API 실행 명령을 사용합니다. API가 실행 중이면 종료한 뒤 새 환경값으로 다시 실행합니다. 이미 생성한 이미지 manifest를 재사용할 때는 해당 파일의 실제 경로를 `CLUSTER_IMAGES_PATH`에 지정합니다. 기사·이미지 manifest와 모델 파일은 별도 로컬 데이터이며 소스 이전 시 자동 복사하지 않습니다. 이미지 없이 실행하려면 `Remove-Item Env:CLUSTER_IMAGES_PATH -ErrorAction SilentlyContinue` 후 API를 재시작합니다.

원래 수집 정보의 RSS `media`를 우선 사용하고 없으면 원문 페이지의 `og:image`·`twitter:image`를 확인합니다. 정규화된 `articles.json`에서 빠진 원본 메타데이터는 `input.json`과 대표기사의 `metadata`에서 복원하며 ID·URL·본문 해시를 대조합니다. 명시된 이미지 표시 거부는 우선 적용하고, 불명 상태를 허용으로 바꾸지 않습니다. 본문 페이지 조회에는 기존 크롤러의 robots 정책·요청 간격·기사 ID 검증을 적용합니다. 광고 이미지나 임의의 본문 `<img>`를 대신 선택하지 않습니다.

수집기는 이미지 URL만 저장하며 이미지 파일을 내려받거나 재호스팅하지 않습니다. 웹 조회에서는 저장 파일만 읽고 수집을 실행하지 않습니다. 원본 기사·군집·입력 파일 해시로 연결을 확인하므로 입력의 권한이나 메타데이터가 바뀌면 오래된 사진 연결을 사용하지 않습니다. 이미지 파일이 없거나 잘못됐을 때도 정상 기사 피드는 유지합니다.

공개 Article 응답에는 선택 항목 `image_url: string | null`만 추가했습니다. 기존 입력은 이 값 없이도 유효하고 기존 필드는 유지됩니다. Pydantic에서 OpenAPI와 프론트 타입을 다시 생성했습니다. 뉴스 카드·스토리·탐색·대표기사 상세는 첫 출처인 대표기사의 사진만 사용하고 언론사 출처를 표시합니다. 관련 기사의 사진으로 대체하지 않으며, 이미지 로딩 실패 시 기본 화면을 표시합니다.

이는 로컬 미리보기입니다. 이미지 주소를 찾았다는 사실을 외부 게시 허가로 해석하지 않습니다. 원래 이용 상태와 자동 게시 금지를 유지하며 공용 DB·공개 배포 기능은 변경하지 않습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests analysis/tests -q
cd frontend
npm.cmd ci
npm.cmd test
npm.cmd run build
```

DB 통합 테스트는 별도 루프백 테스트 DB를 명시한 경우만 실행하며, 공용 Supabase 설정으로 실행하지 않습니다. 사람의 정답이 없어 뉴스 분류 정확도·재현율은 미측정입니다. 테스트 통과, 군집 수 감소와 정확도 향상을 구분합니다. 로컬 분석과 웹 피드 연결의 검증 기록은 각각 `docs/worklogs/2026-10-23-local-clustering.md`, `docs/worklogs/2026-10-23-cluster-web-feed.md`에 있습니다.
