"""가상 XML 5개 항목의 저장·재실행 검증과 내부 조회를 실행합니다."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .demo import build_demo_items
from .reader import RSSReader
from .storage import RSSStorageError, _get_engine, _register_feed, save_feed_items


DEMO_FEED_IDS = (
    "feed-demo-economy", "feed-demo-industry", "feed-demo-politics", "feed-demo-science",
)
_FEED_PARAMS = {f"feed{index}": value for index, value in enumerate(DEMO_FEED_IDS)}
_FEED_BINDS = ", ".join(f":{key}" for key in _FEED_PARAMS)


def legacy_snapshot(engine):
    """기존 데모 뉴스·기사·연결·언론사의 실제 값을 비교하기 위한 스냅샷."""
    queries = {
        "news": "SELECT * FROM public.stories WHERE id = 'story-001' ORDER BY id",
        "articles": """SELECT * FROM public.articles
            WHERE id IN ('story-001-a1', 'story-001-a2', 'story-001-a3') ORDER BY id""",
        "links": "SELECT * FROM public.story_articles WHERE story_id = 'story-001' ORDER BY article_id",
        "publishers": """SELECT * FROM public.publishers WHERE id IN
            (SELECT publisher_id FROM public.articles
             WHERE id IN ('story-001-a1', 'story-001-a2', 'story-001-a3')) ORDER BY id""",
    }
    with engine.connect() as connection:
        return {key: [dict(row) for row in connection.execute(text(sql)).mappings().all()]
                for key, sql in queries.items()}


def register_demo_sources(items, engine):
    """가상 언론사·피드만 등록합니다. 실제 후보의 unknown 권한은 변경하지 않습니다."""
    feeds = {item.feed.feed_id: item.feed for item in items}
    with engine.begin() as connection:
        for feed in feeds.values():
            if feed.feed_id not in DEMO_FEED_IDS or not feed.is_demo:
                raise RSSStorageError("정해진 가상 피드만 데모 등록에 사용할 수 있습니다.")
            connection.execute(text("""
                INSERT INTO public.publishers (id, name, group_id, homepage)
                VALUES (:id, :name, 'demo-rss', 'https://example.com/demo/')
                ON CONFLICT (id) DO NOTHING
            """), {"id": feed.publisher_id, "name": feed.publisher_name})
            publisher = connection.execute(text("""
                SELECT name, group_id, homepage FROM public.publishers WHERE id = :id
            """), {"id": feed.publisher_id}).mappings().one()
            if (publisher["name"], publisher["group_id"], publisher["homepage"]) != (
                    feed.publisher_name, "demo-rss", "https://example.com/demo/"):
                raise RSSStorageError("가상 언론사 ID에 다른 데이터가 있습니다.")
            _register_feed(connection, feed, f"https://example.com/demo/feeds/{feed.feed_id}.xml")


def demo_state(engine):
    with engine.connect() as connection:
        row = connection.execute(text(f"""
            SELECT
                (SELECT count(*) FROM private.rss_feeds WHERE id IN ({_FEED_BINDS})) AS feeds,
                (SELECT count(*) FROM private.rss_items WHERE feed_id IN ({_FEED_BINDS})) AS items,
                (SELECT count(DISTINCT article_id) FROM private.rss_items
                    WHERE feed_id IN ({_FEED_BINDS})) AS articles
        """), _FEED_PARAMS).mappings().one()
        first_seen = connection.execute(text(f"""
            SELECT id, collected_at FROM private.rss_items
            WHERE feed_id IN ({_FEED_BINDS}) ORDER BY id
        """), _FEED_PARAMS).mappings().all()
    return dict(row), [dict(item) for item in first_seen]


def _save_demo(engine):
    groups = defaultdict(list)
    for item in build_demo_items():
        groups[item.feed.feed_id].append(item)
    for feed_id, items in groups.items():
        save_feed_items(feed_id, items, engine=engine)


def load_demo(engine, verify_repeat=False):
    before = legacy_snapshot(engine)
    if tuple(len(before[key]) for key in ("news", "articles", "links", "publishers")) != (1, 3, 3, 3):
        raise RSSStorageError("기존 데모 기준이 1/3/3/3과 다릅니다. 저장 전에 확인해 주세요.")
    register_demo_sources(build_demo_items(), engine)
    _save_demo(engine)
    first_counts, first_seen = demo_state(engine)
    if first_counts != {"feeds": 4, "items": 5, "articles": 4}:
        raise RSSStorageError("데모 저장 개수가 예상과 다릅니다.")
    print("1차 저장: 피드 4 / RSS 항목 5 / 연결된 고유 기사 4")
    if verify_repeat:
        _save_demo(engine)
        counts, seen = demo_state(engine)
        if counts != first_counts or seen != first_seen:
            raise RSSStorageError("재실행 후 개수 또는 최초 수집 시각이 달라졌습니다.")
        print("2차 저장: 피드 4 / RSS 항목 5 / 연결된 고유 기사 4")
        print("재실행 중복 방지 및 최초 collected_at 보존: 통과")
    if legacy_snapshot(engine) != before:
        raise RSSStorageError("기존 데모 데이터 비교 결과가 다릅니다.")
    print("기존 데모 뉴스 1 / 기사 3 / 연결 3 / 언론사 3 유지: 통과")
    with engine.connect() as connection:
        ids = connection.execute(text(f"""
            SELECT id FROM private.rss_items WHERE feed_id IN ({_FEED_BINDS}) ORDER BY id
        """), _FEED_PARAMS).mappings().all()
    reader = RSSReader(engine)
    records = [reader.get_record(row["id"]) for row in ids]
    if len(records) != 5 or any(record is None for record in records):
        raise RSSStorageError("데모 조회 결과가 예상과 다릅니다.")
    partial = [record for record in records if record["parse_status"] == "partial"]
    if len(partial) != 1 or partial[0]["published_at"] is not None:
        raise RSSStorageError("날짜 미확인 항목의 조회 상태가 예상과 다릅니다.")
    print("내부 reader 조회: 5개 / parsed 4 / partial 1")
    return records


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load-demo", help="가상 데이터 저장")
    load.add_argument("--verify-repeat", action="store_true")
    load.add_argument("--output", type=Path, default=Path("work/rss_db_result.json"))
    show = commands.add_parser("show", help="내부 목록 조회만 실행")
    show.add_argument("--limit", type=int, default=10)
    show.add_argument("--output", type=Path, default=Path("work/rss_db_result.json"))
    detail = commands.add_parser("get", help="항목 ID로 내부 상세 조회만 실행")
    detail.add_argument("record_id")
    detail.add_argument("--output", type=Path, default=Path("work/rss_db_detail.json"))
    args = cli.parse_args()
    engine = None
    try:
        engine = _get_engine()
        if args.command == "load-demo":
            result = load_demo(engine, args.verify_repeat)
        elif args.command == "show":
            result = RSSReader(engine).list_records(args.limit)
            print(f"목록 조회: {len(result)}개")
        else:
            result = RSSReader(engine).get_record(args.record_id)
            print("상세 조회: 1개" if result is not None else "해당 항목 없음")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"결과 파일: {args.output.resolve()}")
    except SQLAlchemyError as exc:
        # DB 예외 문자열에는 연결 주소·SQL·입력 값이 포함될 수 있어 그대로 출력하지 않습니다.
        print(f"DB 작업 실패: {type(exc).__name__}. 연결 설정·테이블·권한을 확인해 주세요.")
        raise SystemExit(1) from None
    except (RSSStorageError, KeyError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, (RSSStorageError, ValueError)) else type(exc).__name__
        print(f"작업 실패: {message}")
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
