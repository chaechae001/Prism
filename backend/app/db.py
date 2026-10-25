"""Lazy PostgreSQL connection; importing the API needs no DB credentials."""

import os
from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from .config import load_environment


class DatabaseConfigurationError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_engine():
    load_environment()
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    if any(not os.getenv(key) for key in required):
        raise DatabaseConfigurationError("Database settings are incomplete")
    try:
        port = int(os.environ["DB_PORT"])
        if not 1 <= port <= 65535:
            raise ValueError()
        sslmode = os.getenv("DB_SSLMODE", "require")
        if sslmode not in {"require", "verify-full"}:
            if not (
                sslmode == "disable"
                and os.environ["DB_HOST"] in {"127.0.0.1", "localhost", "::1"}
                and os.environ["DB_NAME"] == "prism_test"
            ):
                raise ValueError()
        url = URL.create(
            "postgresql+psycopg",
            username=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            port=port,
            database=os.environ["DB_NAME"],
        )
        return create_engine(
            url,
            connect_args={
                "sslmode": sslmode,
                "connect_timeout": 10,
                "options": "-c statement_timeout=15000",
            },
            isolation_level="REPEATABLE READ",
            pool_pre_ping=True,
            pool_size=3,
            max_overflow=2,
            pool_timeout=10,
            hide_parameters=True,
        )
    except (ValueError, TypeError):
        raise DatabaseConfigurationError("Database settings are invalid") from None
