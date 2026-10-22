from pathlib import Path
import os


def load_env_file(path):
    """Small, literal env loader: no shell evaluation, expansion or secret printing."""
    allowed = {
        "NEWS_DATABASE_URL",
        "NAVER_CLIENT_ID",
        "NAVER_CLIENT_SECRET",
        "CORS_ORIGINS",
    }
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key.strip() not in allowed:
            raise ValueError("INVALID_NEWS_ENV_FILE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)
