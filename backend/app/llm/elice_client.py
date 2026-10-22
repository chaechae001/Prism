"""엘리스의 OpenAI 호환 Chat Completions API에 연결합니다."""

import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .elice_settings import EliceSettings
from .schemas import ArticleBody, SummaryDraft
from .summarizer import LLMSummaryError, summarize_article


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 키와 본문이 다른 주소로 재전송되지 않도록 리다이렉트를 따르지 않습니다.
        return None


def safe_error_hint(raw: bytes) -> str:
    """서버 원문을 출력하지 않고 미리 정한 오류 분류·매개변수명만 반환합니다."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return "서버 진단: 상세 분류 없음"
    if not isinstance(data, dict):
        return "서버 진단: 상세 분류 없음"
    # 오류 내용은 메모리에서 분류할 때만 사용합니다. 원문이나 임의 필드 값은 반환하지 않습니다.
    error = data.get("error")
    if not isinstance(error, dict):
        error = data
    text = json.dumps(error, ensure_ascii=False).lower()
    known_params = ("reasoning_effort", "response_format", "max_completion_tokens", "max_tokens",
                    "temperature", "top_p", "messages", "model", "stream")
    params = [param for param in known_params if re.search(r"\b" + param + r"\b", text)]
    # 한 오류 메시지에 전체 요청이 들어 있을 수 있어 관련 항목도 고정 이름으로만 표시합니다.
    if "invalid_json_schema" in text or ("schema" in text and "invalid" in text):
        category = "JSON_SCHEMA_INVALID"
    elif any(marker in text for marker in ("unsupported_parameter", "unsupported parameter", "extra_forbidden", "extra inputs are not permitted")):
        category = "UNSUPPORTED_PARAMETER"
    elif any(marker in text for marker in ("unsupported_value", "unsupported value", "invalid_value")):
        category = "UNSUPPORTED_VALUE"
    elif any(marker in text for marker in ("model_not_found", "invalid model", "unknown model", "model does not exist")):
        category = "MODEL_NAME_INVALID"
    elif "not supported" in text or "does not support" in text:
        category = "UNSUPPORTED_FEATURE"
    elif "invalid_request_error" in text:
        category = "INVALID_REQUEST"
    elif "missing" in text and ("field" in text or "required" in text):
        category = "REQUIRED_FIELD_MISSING"
    else:
        category = "UNCLASSIFIED"
    related = ", ".join(params) if params else "확인 불가"
    return f"서버 진단: {category}; 관련 항목: {related}"


def redacted_error_detail(raw: bytes, *, api_key: str, payload=None) -> str:
    """명시적 진단 실행에서만 쓰는 오류 문구. 키·입력 값은 출력 전에 제거합니다."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        return "JSON 오류 메시지가 제공되지 않았습니다."
    if not isinstance(data, dict):
        return "문자열 오류 메시지가 제공되지 않았습니다."
    error = data.get("error", data)
    if not isinstance(error, dict) or not isinstance(error.get("message"), str):
        return "문자열 오류 메시지가 제공되지 않았습니다."
    message = error["message"]
    private_values = [api_key]
    if isinstance(payload, dict):
        for item in payload.get("messages", []):
            if isinstance(item, dict) and isinstance(item.get("content"), str):
                content = item["content"]
                private_values.append(content)
                try:
                    article = json.loads(content)
                except (ValueError, TypeError):
                    continue
                if isinstance(article, dict):
                    private_values.extend(value for value in article.values() if isinstance(value, str))
    for private in sorted(set(private_values), key=len, reverse=True):
        if private:
            message = message.replace(private, "[REDACTED]")
            escaped = json.dumps(private, ensure_ascii=False)[1:-1]
            message = message.replace(escaped, "[REDACTED]")
    message = re.sub(r"(?i)bearer\s+[^\s,;\"']+", "Bearer [REDACTED]", message)
    message = re.sub(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", message)
    message = re.sub(r"\b(?:sk-|sk_)[A-Za-z0-9_-]+", "[REDACTED]", message)
    message = re.sub(r"https?://[^\s\"']+", "[URL]", message)
    # 따옴표 안 값은 옵션명·짧은 기본값만 남기고 가립니다.
    allowed = {"max_completion_tokens", "max_tokens", "stream", "reasoning_effort", "response_format",
               "model", "messages", "temperature", "top_p", "json_schema", "json_object", "minimal",
               "low", "medium", "high", "none", "true", "false", "gpt-5-mini", "openai/gpt-5-mini"}
    message = re.sub(r"(['\"])([^'\"\n]*)\1",
                     lambda match: match.group(0) if match.group(2) in allowed else "'[REDACTED]'", message)
    message = re.sub(r"[A-Za-z0-9_-]{32,}", "[REDACTED]", message)
    return " ".join(message.split())[:700]


def output_schema():
    # 제공사에는 단순한 JSON 구조를 요청하고 길이·개수·기사 ID는 앱에서 검사합니다.
    # 공급자별 JSON Schema 제약 차이 때문에 문장 길이 같은 조건을 중복 전송하지 않습니다.
    def simplify(value):
        if isinstance(value, dict):
            return {key: simplify(item) for key, item in value.items()
                    if key not in {"minLength", "maxLength", "minItems", "maxItems"}}
        if isinstance(value, list):
            return [simplify(item) for item in value]
        return value
    return simplify(SummaryDraft.model_json_schema())


class EliceClient:
    def __init__(self, settings: EliceSettings):
        self.settings = settings
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self.last_model = settings.model
        self.last_usage = {}
        self.last_error_detail = ""

    def _request(self, *, url=None, payload=None):
        self.last_error_detail = ""
        request = Request(
            url or self.settings.api_url,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "Authorization": "Bearer " + self.settings.api_key},
            method="GET" if payload is None else "POST",
        )
        try:
            with self._opener.open(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read(1024 * 1024 + 1)
        except HTTPError as exc:
            status = exc.code
            hint = ""
            try:
                if status == 400:
                    raw_error = exc.read(65536)
                    hint = " " + safe_error_hint(raw_error)
                    self.last_error_detail = redacted_error_detail(raw_error, api_key=self.settings.api_key, payload=payload)
            except (OSError, ValueError):
                hint = " 서버 진단: 상세 오류를 읽을 수 없음"
            finally:
                exc.close()
            errors = {
                400: ("MODEL_BAD_REQUEST", "모델명·요청 옵션·JSON 출력 지원 여부를 확인하세요."),
                401: ("MODEL_AUTH_FAILED", "API 키가 잘못되었거나 만료되었습니다."),
                403: ("MODEL_FORBIDDEN", "해당 모델의 사용 권한을 확인하세요."),
                404: ("MODEL_ENDPOINT_NOT_FOUND", "호출 주소와 /v1/chat/completions 경로를 확인하세요."),
                429: ("MODEL_RATE_LIMITED", "호출 한도 또는 사용 가능한 크레딧을 확인하세요."),
            }
            code, message = errors.get(status, ("MODEL_HTTP_ERROR", "엘리스 서버가 요청을 처리하지 못했습니다."))
            # 서버 오류 본문에는 키·프롬프트가 들어갈 수 있어 원문을 내보내지 않습니다.
            raise LLMSummaryError(code, message + hint) from None
        except (TimeoutError, socket.timeout):
            raise LLMSummaryError("MODEL_TIMEOUT", "모델 응답 시간이 초과되었습니다. 자동 재시도하지 않습니다.") from None
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise LLMSummaryError("MODEL_TIMEOUT", "모델 응답 시간이 초과되었습니다.") from None
            raise LLMSummaryError("MODEL_UNAVAILABLE", "엘리스 서버 연결을 확인하세요.") from None
        except OSError:
            raise LLMSummaryError("MODEL_UNAVAILABLE", "모델 서버 통신 중 연결이 끊겼습니다.") from None
        if len(raw) > 1024 * 1024:
            raise LLMSummaryError("INVALID_MODEL_OUTPUT", "응답 크기가 제한을 초과했습니다.")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise LLMSummaryError("INVALID_MODEL_OUTPUT", "서버 응답을 JSON으로 읽을 수 없습니다.") from None
        if not isinstance(result, dict) or "error" in result:
            raise LLMSummaryError("INVALID_MODEL_OUTPUT", "서버 응답 형식을 확인할 수 없습니다.")
        return result

    def check(self):
        # 생성 요청을 보내지 않고 같은 API의 모델 목록·인증 상태만 점검합니다.
        url = self.settings.api_url.removesuffix("/chat/completions") + "/models"
        result = self._request(url=url)
        models = result.get("data")
        if not isinstance(models, list):
            raise LLMSummaryError("INVALID_MODEL_OUTPUT", "모델 목록 응답을 확인할 수 없습니다.")
        ids = {item.get("id") for item in models if isinstance(item, dict) and isinstance(item.get("id"), str)}
        if not ids.intersection({"gpt-5-mini", "openai/gpt-5-mini"}):
            raise LLMSummaryError("MODEL_NOT_FOUND", "사용 가능한 모델 목록에 GPT-5 mini가 없습니다.")

    def generate(self, system: str, user: str):
        self.last_usage = {}
        self.last_model = self.settings.model
        response = self._request(payload={
            "model": self.settings.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            # GPT-5 mini에는 temperature=0·Ollama의 think/num_ctx를 보내지 않습니다.
            "reasoning_effort": "minimal",
            "max_completion_tokens": self.settings.max_completion_tokens,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "article_summary", "strict": True, "schema": output_schema(),
            }},
        })
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise LLMSummaryError("INVALID_MODEL_OUTPUT", "모델 답변 목록을 읽을 수 없습니다.")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LLMSummaryError("INVALID_MODEL_OUTPUT", "모델 답변 본문을 읽을 수 없습니다.")
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise LLMSummaryError("MODEL_REFUSED", "모델이 이 입력의 요약을 거절했습니다.")
        if choice.get("finish_reason") != "stop":
            raise LLMSummaryError("MODEL_INCOMPLETE", "생성이 정상 종료되지 않았습니다. 출력 한도와 모델 상태를 확인하세요.")
        if (message.get("role") != "assistant" or not isinstance(message.get("content"), str)
                or not message["content"].strip()):
            raise LLMSummaryError("INVALID_MODEL_OUTPUT", "모델이 유효한 요약 본문을 반환하지 않았습니다.")
        resolved_model = response.get("model")
        if isinstance(resolved_model, str) and 0 < len(resolved_model.strip()) <= 200:
            self.last_model = resolved_model.strip()
        usage = response.get("usage")
        if isinstance(usage, dict):
            self.last_usage = {key: value for key, value in usage.items()
                               if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                               and type(value) is int and value >= 0}
        return message["content"]


def summarize_with_elice(article: ArticleBody, settings: EliceSettings | None = None):
    """다른 개발자가 호출할 진입 함수. DB·Docker·Ollama가 필요하지 않습니다."""
    if not isinstance(article, ArticleBody):
        raise TypeError("ArticleBody로 입력을 확인한 뒤 전달하세요.")
    client = EliceClient(settings or EliceSettings.from_env())
    result = summarize_article(article, generate=client.generate,
                               model_version=client.settings.model, is_mock=False)
    return result.model_copy(update={"model_version": client.last_model})
