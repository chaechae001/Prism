import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError
from .analysis import import_results, publish
from .config import load_env_file
from .models import BodyBatch, Publisher, ResultBatch
from .naver import NaverClient, NaverError, NaverItem, normalize
from .storage import connect, save_article, save_body, export_batch


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Private news ingestion / analysis handoff. No HTTP admin writes."
    )
    parser.add_argument("--env-file")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--query", required=True)
    collect.add_argument(
        "--category",
        choices=["politics", "economy", "society", "technology"],
        required=True,
    )
    collect.add_argument("--publishers", required=True)
    collect.add_argument(
        "--fixture",
        help="Provider-shaped JSON for offline parser testing; synthetic data only",
    )
    collect.add_argument("--display", type=int, default=100)
    collect.add_argument("--start", type=int, default=1)
    bodies = sub.add_parser("import-bodies")
    bodies.add_argument("path")
    export = sub.add_parser("export-analysis")
    export.add_argument("--out", required=True)
    export.add_argument("--min-chars", type=int, default=200)
    export.add_argument("--allow-excerpt", action="store_true")
    export.add_argument("--limit", type=int, default=500)
    results = sub.add_parser("import-results")
    results.add_argument("path")
    publication = sub.add_parser("publish")
    publication.add_argument("--event-id", required=True)
    publication.add_argument("--reviewed", action="store_true")
    publication.add_argument("--modes", nargs="+", default=["summary"])
    demo = sub.add_parser("seed-demo")
    demo.add_argument("--out-dir", default="data/private/demo-news-v2")
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    with connect() as conn:
        if args.command == "collect":
            publishers = [Publisher.model_validate(p) for p in read(args.publishers)]
            if args.fixture:
                page = read(args.fixture)
                if page.get("is_demo") is not True:
                    raise ValueError("FIXTURE_MUST_BE_MARKED_DEMO")
                items = [NaverItem.model_validate(i) for i in page["items"]]
            else:
                items = (
                    NaverClient()
                    .search(args.query, display=args.display, start=args.start)
                    .items
                )
            saved = 0
            invalid = 0
            for item in items:
                try:
                    article = normalize(
                        item, args.category, publishers, is_demo=bool(args.fixture)
                    )
                except (ValueError, ValidationError):
                    invalid += 1
                    continue
                save_article(conn, article, query=args.query, raw=item.model_dump())
                saved += 1
            print(
                json.dumps(
                    {
                        "observations_processed": saved,
                        "invalid_skipped": invalid,
                        "body_acquired": 0,
                        "note": "검색 결과에는 기사 전문이 없습니다.",
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "import-bodies":
            batch = BodyBatch.model_validate(read(args.path))
            ids = [str(save_body(conn, b)) for b in batch.items]
            print(json.dumps({"body_versions": ids}))
        elif args.command == "export-analysis":
            batch = export_batch(
                conn,
                min_chars=args.min_chars,
                allow_excerpt=args.allow_excerpt,
                limit=args.limit,
            )
            write(args.out, batch.model_dump(mode="json"))
            print(
                json.dumps(
                    {
                        "run_id": str(batch.run_id),
                        "articles": len(batch.articles),
                        "excluded": batch.excluded,
                        "private_file": args.out,
                    }
                )
            )
        elif args.command == "import-results":
            print(
                json.dumps(
                    {
                        "event_ids": import_results(
                            conn, ResultBatch.model_validate(read(args.path))
                        ),
                        "published": False,
                    }
                )
            )
        elif args.command == "publish":
            story = publish(
                conn, args.event_id, reviewed=args.reviewed, modes=args.modes
            )
            print(
                json.dumps(
                    {"story_id": story.id, "published": True, "is_demo": story.is_demo}
                )
            )
        else:
            from .demo import seed_demo

            demo = seed_demo(conn)
            folder = Path(args.out_dir)
            write(folder / "analysis-input.json", demo["batch"].model_dump(mode="json"))
            write(
                folder / "analysis-result.json", demo["results"].model_dump(mode="json")
            )
            write(folder / "bodies.json", demo["bodies"])
            print(
                json.dumps(
                    {
                        "story_id": demo["story"].id,
                        "is_demo": True,
                        "model_executed": False,
                    }
                )
            )


if __name__ == "__main__":
    try:
        main()
    except ValidationError:
        print("INPUT_SCHEMA_INVALID", file=sys.stderr)
        sys.exit(1)
    except (NaverError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # DB exception strings can contain connection information; never print them.
        print(f"NEWS_COMMAND_FAILED: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
