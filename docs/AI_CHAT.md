# 뉴스 AI 대화

## 설정

`backend/.env.chat.example`을 `backend/.env.chat.local`로 복사합니다. 실제 값은 로컬 파일에만 저장합니다.

```dotenv
PRISM_CHAT_PROVIDER=elice
ELICE_API_KEY=YOUR_API_KEY
ELICE_API_URL=https://mlapi.run/YOUR-ENDPOINT-UUID/v1/chat/completions
ELICE_CHAT_MODEL=openai/gpt-5-mini
PRISM_CHAT_ENABLED=1
PRISM_DATA_SOURCE=fixture
CORS_ORIGINS=http://127.0.0.1:5183,http://localhost:5183
```

URL의 UUID는 제공자 관리 화면의 실제 값으로 바꿉니다. 위 주소와 키는 자리표시자입니다. 프론트의 VITE_* 변수에는 키를 넣지 않습니다. 설정 변경 후 API 서버를 재시작합니다.

```powershell
python -m uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 8004
```

## API

- `GET /api/social/chat/status`: 설정 여부와 참고 데이터 범위를 반환합니다.
- `POST /api/social/stories/{story_id}/chat`: 선택 뉴스에 대한 답변을 생성합니다.

요청:

```json
{"question":"핵심 내용을 쉽게 요약해줘","history":[]}
```

응답은 `answer`, `article_ids`, `model`, `context_notice`를 포함합니다. 정확한 형식은 `contracts/social-v1/openapi.json`에 정의합니다.

## 동작과 오류

엘리스 어댑터는 Chat Completions 요청과 JSON Schema 응답을 사용합니다. 서버가 실제 참고한 사건의 기사 ID만 응답에 허용합니다. 원문 전문이나 외부 최신 정보를 확인했다고 주장하지 않도록 문맥을 제한합니다.

키·모델 미설정, 인증 실패, 요청 한도 초과, 시간 초과, 미완료 생성, JSON 형식·출처 검증 실패는 오류로 반환합니다. 실제 API 호출은 사용량이 발생할 수 있으며 자동 테스트는 제공자를 대체한 응답으로 검증합니다.

OpenAI 직접 연결도 제공자 어댑터에 포함되어 있습니다. 사용할 경우 `PRISM_CHAT_PROVIDER=openai`를 명시하고 `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL`을 설정합니다. 제공자별 키는 서로 교차 사용하지 않습니다.

공개 서비스에 연결하기 전 사용자 인증과 사용자별 한도를 적용해야 합니다. 현재 대화 기록은 브라우저에만 저장됩니다.
