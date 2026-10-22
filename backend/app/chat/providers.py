"""Explicit provider routing. Elice credentials never go to OpenAI endpoints."""

import json
import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException


def elice_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "mlapi.run"
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(
            r"/[0-9a-fA-F-]{36}(?:/v1/chat/completions)?/?", parsed.path
        )
    ):
        raise ValueError("Invalid Elice endpoint")
    return value


def settings():
    provider = os.getenv("PRISM_CHAT_PROVIDER", "openai")
    if provider == "openai":
        return (
            provider,
            os.getenv("OPENAI_API_KEY", ""),
            os.getenv("OPENAI_CHAT_MODEL", ""),
            "https://api.openai.com/v1/responses",
        )
    if provider == "elice":
        url = elice_url(os.getenv("ELICE_API_URL", ""))
        return (
            provider,
            os.getenv("ELICE_API_KEY", ""),
            os.getenv("ELICE_CHAT_MODEL") or os.getenv("ELICE_MODEL", ""),
            url,
        )
    raise ValueError("Unknown chat provider")


async def elice_answer(payload: dict) -> dict:
    provider, key, model, url = settings()
    if provider != "elice":
        raise ValueError("Wrong provider")
    format_config = payload["text"]["format"]
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": payload["instructions"]},
            *payload["input"],
        ],
        "max_completion_tokens": payload["max_output_tokens"],
        "reasoning_effort": "minimal",
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                name: format_config[name] for name in ("name", "schema", "strict")
            },
        },
    }
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        response = await client.post(
            url,
            json=request_body,
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
    try:
        result = response.json()
    except ValueError:
        result = {}
    if response.status_code == 404 and isinstance(result, dict):
        error = result.get("error", {})
        if isinstance(error, dict) and error.get("code") == "api_not_found":
            raise HTTPException(
                502,
                "엘리스 API ID를 찾을 수 없습니다. 현재 API 예시의 요청 주소를 확인해주세요.",
            )
    if response.status_code in (401, 403):
        raise HTTPException(502, "엘리스 API 키 또는 모델 접근 권한을 확인해주세요.")
    if response.status_code == 429:
        raise HTTPException(
            429, "엘리스 요청 한도에 도달했습니다. 잠시 후 다시 시도해주세요."
        )
    if response.status_code >= 300:
        raise HTTPException(502, "엘리스 API 주소·모델·요청 설정을 확인해주세요.")
    choices = result.get("choices", [])
    if not choices or choices[0].get("finish_reason") != "stop":
        raise HTTPException(
            502, "엘리스 답변이 완료되지 않았습니다. 다시 시도해주세요."
        )
    message = choices[0].get("message", {})
    if message.get("refusal"):
        raise HTTPException(
            422, "이 질문에는 답변할 수 없습니다. 기사 내용에 관한 질문으로 바꿔주세요."
        )
    return json.loads(message.get("content", ""))
