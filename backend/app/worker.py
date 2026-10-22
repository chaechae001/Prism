"""Local data import and reviewed summary publication, separate from HTTP reads."""

import argparse
import json
from pathlib import Path
from .config import load_environment
from .models import AnalystBatch


def main(argv=None):
    load_environment()
    parser = argparse.ArgumentParser(description="PRISM data workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-db")
    bodies = sub.add_parser("import-bodies")
    bodies.add_argument("--input", type=Path, required=True)
    rss = sub.add_parser("prepare-rss")
    rss.add_argument("--record-id", required=True)
    summary = sub.add_parser("summarize")
    summary.add_argument("--story-id", required=True)
    approve = sub.add_parser("approve")
    approve.add_argument("--version-id", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check-db":
            from .db import get_engine
            from sqlalchemy import text

            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
                rows = (
                    connection.execute(
                        text("""
                    SELECT table_schema,table_name FROM information_schema.tables
                    WHERE (table_schema='public' AND table_name IN ('stories','articles','story_articles','publishers'))
                       OR (table_schema='private' AND table_name IN ('rss_items','rss_feeds','raw_articles','summary_versions'))
                """)
                    )
                    .mappings()
                    .all()
                )
            if len(rows) != 8:
                raise ValueError("Required schema is incomplete")
            result = {"connected": True, "required_tables_found": len(rows)}
        elif args.command == "import-bodies":
            from .services.body_import import import_bodies

            batch = AnalystBatch.model_validate_json(
                args.input.read_text(encoding="utf-8-sig")
            )
            result = {"articles": import_bodies(batch)}
        elif args.command == "prepare-rss":
            from .services.rss_projection import prepare_rss_story

            result = prepare_rss_story(args.record_id)
        elif args.command == "summarize":
            from .services.summaries import generate_summary

            result = generate_summary(args.story_id)
        else:
            from .services.summaries import approve_summary

            result = approve_summary(args.version_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        print(
            json.dumps(
                {
                    "error": code,
                    "message": "설정·입력·권한 또는 데이터 상태를 확인해주세요. 원문 오류는 출력하지 않습니다.",
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
