"""Local data import and reviewed summary publication, separate from HTTP reads."""

import argparse
import json
from pathlib import Path
from .config import load_environment


def main(argv=None):
    load_environment()
    parser = argparse.ArgumentParser(description="PRISM data workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-db")
    validate = sub.add_parser("validate-batch", help="분석 입력 검증. 기본은 DB 연결 없는 검사입니다.")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--check-db", action="store_true", help="DB를 읽어 기존 기사 매핑도 확인합니다. 저장하지 않습니다.")
    intake = sub.add_parser("intake-articles", help="신규 기사와 본문 입력. 기본은 읽기 전용 계획입니다.")
    intake.add_argument("--input", type=Path, required=True)
    intake.add_argument("--apply", action="store_true", help="기사·본문을 하나의 트랜잭션으로 저장합니다.")
    intake.add_argument("--demo", action="store_true", help="신규 가상 기사 입력으로 표시합니다.")
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
        if args.command == "validate-batch":
            from .services.analyst_validation import read_checked_batch, plan_import

            checked = read_checked_batch(args.input)
            result = plan_import(checked) if args.check_db else checked.report
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["valid"] and result.get("ready_for_import", True) else 1
        elif args.command == "intake-articles":
            from .services.analyst_validation import read_checked_batch
            from .services.article_intake import intake_articles

            checked = read_checked_batch(args.input)
            if not checked.report["valid"]:
                print(json.dumps(checked.report, ensure_ascii=False))
                return 1
            result = intake_articles(checked.batch, apply=args.apply, is_demo=args.demo)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ready_for_intake"] else 1
        elif args.command == "check-db":
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

            from .services.analyst_validation import read_checked_batch

            checked = read_checked_batch(args.input)
            if not checked.report["valid"]:
                print(json.dumps(checked.report, ensure_ascii=False))
                return 1
            result = {"articles": import_bodies(checked.batch)}
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
        from .services.analyst_validation import InvalidAnalystBatch
        from .services.article_intake import IntakeConflict

        if isinstance(exc, (InvalidAnalystBatch, IntakeConflict)):
            print(json.dumps(exc.report, ensure_ascii=False))
            return 1
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
