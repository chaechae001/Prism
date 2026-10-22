"""Install v2 in an explicitly selected localhost database, never remote Supabase."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

dsn = os.environ.get("NEWS_DATABASE_URL", "")
if urlsplit(dsn).hostname not in ("127.0.0.1", "localhost", "::1"):
    raise SystemExit(
        "Set NEWS_DATABASE_URL to the disposable localhost PostgreSQL first."
    )
with psycopg.connect(dsn, autocommit=True) as conn:
    for role in ("anon", "authenticated", "service_role"):
        if not conn.execute(
            "select 1 from pg_roles where rolname=%s", (role,)
        ).fetchone():
            conn.execute(
                sql.SQL("create role {} nologin {}").format(
                    sql.Identifier(role),
                    sql.SQL("bypassrls" if role == "service_role" else ""),
                )
            )
    if conn.execute("select to_regclass('private.news_v2_articles')").fetchone()[0]:
        print("Local v2 schema already exists; no migration rerun.")
    else:
        path = (
            Path(__file__).resolve().parents[1]
            / "database/supabase/migrations/20261022055246_naver_ingestion_and_story_modes.sql"
        )
        conn.execute(path.read_text(encoding="utf-8-sig"))
        print("Local v2 migration applied. No external API called.")
