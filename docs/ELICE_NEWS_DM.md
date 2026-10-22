# 엘리스 GPT-5 mini 뉴스 DM 연결

## 현재 연결 방식

`뉴스 DM → FastAPI /api/social/stories/{id}/chat → 엘리스 전용 ML API → 응답·출처 검증 → 말풍선`으로 동작합니다. 프론트 API 형식과 RSS/DB는 변경하지 않았습니다.

사용자가 제공한 엘리스 모델은 **GPT-5 mini**입니다. 키는 엘리스에서 발급받은 값이며, OpenAI 직접 API 키와 구분합니다. 이전 OpenAI 주소의 401은 엘리스 키의 유효성을 판단하는 검사로 사용할 수 없습니다.

첨부 화면에는 기본 ML API 주소가 보입니다. 공식 문서의 `/v1/chat/completions` 경로를 붙여 연결했습니다. 입력 시 경로를 두 번 붙이지 않습니다. 이미지의 API ID를 잘못 읽어 발생했던 `api_not_found`는 사용자에게 텍스트 주소를 받아 수정했고, **엘리스의 실제 요약과 후속 설명 답변을 모두 확인했습니다.** 처음 확인한 404는 단순 경로 문제라고 단정할 수 없었으며 실제로 API ID 오독이 있었습니다.

## 서버 전용 설정

`backend/.env.chat.local`에 저장합니다. 파일은 Git 제외 대상이며 프론트 환경 변수로 복사하지 않습니다.

```dotenv
PRISM_CHAT_PROVIDER=elice
ELICE_API_KEY=엘리스에서_발급한_실제_키
ELICE_API_URL=https://mlapi.run/전용-엔드포인트-UUID/v1/chat/completions
ELICE_CHAT_MODEL=openai/gpt-5-mini
PRISM_CHAT_ENABLED=1
PRISM_DATA_SOURCE=fixture
CORS_ORIGINS=http://127.0.0.1:5183,http://localhost:5183
```

API 주소의 UUID는 **자신의 엘리스 API 화면에 표시된 값**을 사용합니다. 위 예시는 실제 호출 가능한 주소가 아닙니다. 실행 중인 프로젝트의 로컬 파일에는 사용자 첨부 화면의 주소를 반영했습니다. 기존에 `OPENAI_API_KEY`에 넣은 값은 엘리스 전용 키 변수로 옮겼고 값은 로그/채팅에 출력하지 않았습니다.

```powershell
python -m uvicorn app.api:app --app-dir backend --host 127.0.0.1 --port 8004
```

기존 서버가 실행 중이면 해당 터미널을 종료한 뒤 재시작합니다. 프론트는 기존 http://127.0.0.1:5183/ 를 사용합니다.

## 요청·응답 변환

- 제공자를 `PRISM_CHAT_PROVIDER`로 명시합니다. 엘리스 선택 시 OpenAI 주소로 자동 대체하거나 키를 보내지 않습니다.
- 엘리스 어댑터는 `messages`, `model`, `max_completion_tokens`, `reasoning_effort=minimal`, `response_format=json_schema`를 사용합니다.
- `choices[0].message.content`의 JSON을 읽어 기존 `answer`, `article_ids` 모델로 검증합니다.
- 다른 뉴스의 출처 ID, 중단/미완료 응답, 인증 실패는 답변으로 표시하지 않습니다.
- URL은 HTTPS `mlapi.run`의 엔드포인트 UUID 경로만 허용하고 리다이렉트를 따르지 않습니다. 키가 다른 호스트로 전달되지 않도록 합니다.
- 엘리스 요청에는 OpenAI 직접 API 전용 `store`를 전달하지 않습니다. 엘리스의 데이터 보존 조건이 OpenAI 직접 API와 같다고 가정하지 않습니다.

현재 문맥은 제목·제공된 요약·관련 기사 정보이며 원문 전문은 아직 연결되지 않았습니다. 분석가 본문을 연결할 때에는 기존 `context_for()`에서 허용된 본문만 추가합니다.

## 공식 문서와 확인 범위

- [사용자 제공 모델 API 페이지](https://yeardream2026.elice.io/cloud/mlapi/model-libraries/4a791550-53e9-422a-91d2-41a7f77b5bdf/api): 브라우저에서는 로그인 화면이 나와 인증된 API 스펙은 읽지 못했습니다. 사용자 첨부 화면의 기본 주소를 사용했습니다.
- [엘리스 공식 GPT-5 mini 문서](https://elice.io/en/ax/model-library/4a791550-53e9-422a-91d2-41a7f77b5bdf): 호환 채팅 경로·Bearer 인증·구조화 출력 형식을 확인했습니다. 문서 시점에 따라 모델 ID가 `gpt-5-mini` 또는 `openai/gpt-5-mini`로 표시되므로 실제 제공자의 반환 결과를 함께 확인합니다.

최종 백엔드 회귀 테스트 50개가 통과했습니다. 실제 브라우저에서 가상 뉴스의 요약·쉬운 설명 답변 2건과 출처 ID 검증 통과를 확인했습니다. 현재 사용한 모델 ID는 `openai/gpt-5-mini`입니다. 실서비스 본문이나 다양한 기사에 대한 모델 품질 평가까지 완료했다는 뜻은 아닙니다.
