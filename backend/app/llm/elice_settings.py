"""엘리스 접속 정보는 코드 대신 프로젝트 .env에서 읽습니다."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from ..config import load_environment


@dataclass(frozen=True)
class EliceSettings:
    api_url: str
    api_key: str = field(repr=False)
    model: str = "gpt-5-mini"
    timeout_seconds: float = 120
    # 현재 기관 프록시의 비스트리밍 응답 한도에 맞춥니다.
    max_completion_tokens: int = 2000

    def __post_init__(self):
        parts = urlsplit(self.api_url)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or not parts.path.endswith("/v1/chat/completions")):
            raise ValueError("ELICE_API_URL에는 /v1/chat/completions까지 포함한 HTTPS 주소가 필요합니다.")
        try:
            parts.port
        except ValueError:
            raise ValueError("ELICE_API_URL의 포트를 확인하세요.") from None
        if not self.api_key.strip() or self.api_key.strip().upper() in {"REPLACE_WITH_YOUR_KEY", "YOUR_API_KEY"}:
            raise ValueError("ELICE_API_KEY에 본인의 새 키를 입력하세요.")
        if any(character.isspace() for character in self.api_key):
            raise ValueError("ELICE_API_KEY의 공백·줄바꿈을 확인하세요.")
        if self.model not in {"gpt-5-mini", "openai/gpt-5-mini"}:
            raise ValueError("이번 연결은 팀이 정한 GPT-5 mini를 기준으로 합니다.")
        if not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 600:
            raise ValueError("ELICE_TIMEOUT_SECONDS는 1~600초 범위로 입력하세요.")
        if type(self.max_completion_tokens) is not int or not 1024 <= self.max_completion_tokens <= 2000:
            raise ValueError("현재 비스트리밍 연결의 ELICE_MAX_COMPLETION_TOKENS는 1024~2000 범위로 입력하세요.")

    @classmethod
    def from_env(cls):
        load_dotenv(Path(__file__).resolve().parents[3] / ".env", interpolate=False, override=False)
        load_environment()
        try:
            return cls(
                api_url=os.getenv("ELICE_API_URL", "").strip().rstrip("/"),
                api_key=os.getenv("ELICE_API_KEY", "").strip(),
                model=(os.getenv("ELICE_CHAT_MODEL") or os.getenv("ELICE_MODEL", "gpt-5-mini")).strip(),
                timeout_seconds=float(os.getenv("ELICE_TIMEOUT_SECONDS", "120")),
                max_completion_tokens=int(os.getenv("ELICE_MAX_COMPLETION_TOKENS", "2000")),
            )
        except (ValueError, TypeError):
            raise ValueError(".env의 ELICE_* 설정을 확인하세요. 키·주소 원문은 출력하지 않습니다.") from None
