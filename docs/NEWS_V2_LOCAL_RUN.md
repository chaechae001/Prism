# 네이버 키 없이 새 구조와 분석 탭 실행하기

현재 구현을 VS Code에서 확인하는 로컬 전용 절차입니다. Docker Desktop이 실행되어 있어야 합니다. 외부 네이버 API나 Supabase 데이터에는 쓰지 않습니다.

## 터미널 A — 프로젝트 루트

```powershell
python -m pip install -r backend/requirements-news.txt
docker run --detach --rm --name prism-news-v2-local --env POSTGRES_PASSWORD=prism_local_test --publish 127.0.0.1:55439:5432 postgres:17-alpine
$env:NEWS_DATABASE_URL='postgresql://postgres:prism_local_test@127.0.0.1:55439/postgres'
```

위 비밀번호는 일회용 로컬 컨테이너 전용 예시입니다. 실제 Supabase 자격 증명으로 재사용하지 않습니다. 이미 같은 이름/포트로 컨테이너가 실행되어 있다면 다시 만들지 말고 해당 컨테이너 상태를 먼저 확인합니다. 다른 작업의 컨테이너를 종료하지 않습니다.

```powershell
docker exec prism-news-v2-local pg_isready -U postgres
```

`accepting connections`를 확인한 뒤 실행합니다.

```powershell
python scripts/prepare_news_v2_local.py
python -m backend.app.news.cli seed-demo
python -m uvicorn app.news_api:app --app-dir backend --host 127.0.0.1 --port 8000
```

마지막 명령은 API 서버이므로 터미널을 켜둡니다. prepare 스크립트와 seed-demo는 원격 주소를 거부합니다.

## 터미널 B — 프로젝트 루트에서 새 터미널

```powershell
cd frontend
$env:VITE_NEWS_API_VERSION='v2'
npm.cmd run dev:http
```

[화면](http://127.0.0.1:5173/)에서 10월 22일의 가상 사건 하나를 클릭하고 다음을 확인합니다.

1. 일반 요약과 기사 3개·매체 3개가 표시됩니다.
2. 팩트 5W, 쉽게 읽기, 감정·어조 탭이 각각 저장된 예시 결과를 표시합니다.
3. 출처 탭에서 `가상 뉴스 1 · 본문 확인`은 본문을 보여줍니다.
4. `가상 뉴스 2 · 본문 확인`은 본문을 반환하지 않고 원문 안내를 보여줍니다.
5. 날짜를 10월 21일로 바꾸면 서버에서 빈 결과를 반환합니다.

이는 모델 성능 시연이 아니라 DB·API·UI 연결 검증입니다. 모든 내용은 직접 작성한 가상 자료입니다. 실제 입력 연결은 `NAVER_NEWS_V2_GUIDE.md`를 사용합니다.

## 종료

서버 터미널에서 각각 Ctrl+C를 누른 뒤, 위에서 만든 컨테이너만 종료합니다.

```powershell
docker stop prism-news-v2-local
```

`--rm` 컨테이너이므로 이 로컬 가상 DB는 삭제됩니다. 개발 Supabase에는 영향을 주지 않습니다.
