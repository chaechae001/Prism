"""Load a small literal server-only local environment file, without shell expansion."""

import os
from pathlib import Path


def load_chat_env():
    path = Path(__file__).resolve().parents[2] / ".env.chat.local"
    if not path.exists():
        return
    allowed = {
        "OPENAI_API_KEY",
        "OPENAI_CHAT_MODEL",
        "PRISM_CHAT_ENABLED",
        "PRISM_DATA_SOURCE",
        "CORS_ORIGINS",
        "PRISM_CHAT_PROVIDER",
        "ELICE_API_KEY",
        "ELICE_API_URL",
        "ELICE_CHAT_MODEL",
    }
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in allowed:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name, value)
