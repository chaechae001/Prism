"""RSS 입력을 피드 단위 트랜잭션으로 저장합니다. HTTP 요청은 하지 않습니다."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable

from sqlalchemy import text

from .parser import FeedConfig, ParsedItem, canonicalize_url


class RSSStorageError(ValueError):
    """피드 설정, 이용 상태 또는 기존 데이터와의 충돌."""


@dataclass(frozen=True)
class SaveResult:
    processed: int
    linked: int
    unlinked: int
    record_ids: tuple[str, ...]


def _get_engine(engine=None):
    # 모듈을 가져오기만 할 때는 .env나 DB 연결 설정을 읽지 않습니다.
    if engine is not None:
        return engine
    from ..db import get_engine
    return get_engine()


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _object(value):
    return json.loads(value) if isinstance(value, str) else dict(value)


def _timestamp(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.utcoffset() is None:
        raise RSSStorageError("시각에는 시간대가 있어야 합니다.")
    return result.astimezone(timezone.utc)


def _register_feed(connection, feed: FeedConfig, feed_url: str):
    canonicalize_url(feed_url)
    connection.execute(text("""
        INSERT INTO private.rss_feeds
            (id, publisher_id, feed_url, default_category, enabled, rights)
        VALUES (:id, :publisher_id, :feed_url, :category, false, CAST(:rights AS jsonb))
        ON CONFLICT (id) DO NOTHING
    """), {"id": feed.feed_id, "publisher_id": feed.publisher_id,
           "feed_url": feed_url, "category": feed.default_category, "rights": _json(dict(feed.rights))})
    row = connection.execute(text("""
        SELECT publisher_id, feed_url, default_category, rights
        FROM private.rss_feeds WHERE id = :id FOR UPDATE
    """), {"id": feed.feed_id}).mappings().one()
    expected = (feed.publisher_id, feed_url, feed.default_category, dict(feed.rights))
    actual = (row["publisher_id"], row["feed_url"], row["default_category"], _object(row["rights"]))
    if actual != expected:
        # 재등록할 때 기존 설정이나 권한을 덮어쓰지 않습니다.
        raise RSSStorageError("기존 피드 설정과 다릅니다. DB 설정을 확인해 주세요.")


def register_feed(feed: FeedConfig, feed_url: str, *, engine=None):
    """기존 언론사에 피드를 등록합니다. enabled는 기본 false이며 재등록 시 유지합니다."""
    with _get_engine(engine).begin() as connection:
        _register_feed(connection, feed, feed_url)


def _article_id(connection, item: ParsedItem):
    data = item.storage
    if data["parse_status"] == "error" or data["published_at"] is None:
        return None
    # 발행일을 모르면 private에만 보존합니다. 기존 필수 날짜를 가짜로 채우지 않습니다.
    article_id = "rss-article-v1-" + sha256(data["canonical_url"].encode()).hexdigest()
    row = connection.execute(text("""
        INSERT INTO public.articles
            (id, publisher_id, canonical_url, title, published_at, is_demo, publish_allowed)
        VALUES (:id, :publisher_id, :url, :title, :published_at, :is_demo, false)
        ON CONFLICT (canonical_url) DO NOTHING
        RETURNING id, publisher_id, is_demo
    """), {"id": article_id, "publisher_id": item.feed.publisher_id,
           "url": data["canonical_url"], "title": data["title"],
           "published_at": _timestamp(data["published_at"]), "is_demo": data["is_demo"]}).mappings().first()
    if row is None:
        row = connection.execute(text("""
            SELECT id, publisher_id, is_demo FROM public.articles WHERE canonical_url = :url
        """), {"url": data["canonical_url"]}).mappings().one()
    if row["publisher_id"] != item.feed.publisher_id or row["is_demo"] != data["is_demo"]:
        raise RSSStorageError("같은 URL의 언론사 또는 가상 데이터 표시가 충돌합니다.")
    # 기존 기사의 제목·발행일·공개 허용 값은 RSS 재수신으로 덮어쓰지 않습니다.
    return row["id"]


ITEM_COLUMNS = (
    "id", "feed_id", "item_key", "source_item_id", "original_url", "canonical_url",
    "title", "author", "source_category", "category", "rss_description", "content_html",
    "media", "raw_item_xml", "source_published_raw", "published_at", "collected_at",
    "last_seen_at", "parse_status", "parse_issues", "body_status", "rights_snapshot", "is_demo",
)
JSON_COLUMNS = {"media", "parse_issues", "rights_snapshot"}
TIME_COLUMNS = {"published_at", "collected_at", "last_seen_at"}
# 컬럼 이름은 사용자 입력이 아닌 위 고정 목록에서만 가져옵니다.
_values = [f"CAST(:{key} AS jsonb)" if key in JSON_COLUMNS else f":{key}" for key in ITEM_COLUMNS]
_updates = [f"{key} = EXCLUDED.{key}" for key in ITEM_COLUMNS if key not in {"id", "feed_id", "item_key", "collected_at", "last_seen_at"}]
UPSERT_ITEM = text(f"""
    INSERT INTO private.rss_items ({', '.join(ITEM_COLUMNS)}, article_id)
    VALUES ({', '.join(_values)}, :article_id)
    ON CONFLICT (feed_id, item_key) DO UPDATE SET
        {', '.join(_updates)},
        article_id = EXCLUDED.article_id,
        last_seen_at = GREATEST(private.rss_items.last_seen_at, EXCLUDED.last_seen_at)
    RETURNING id
""")


def save_feed_items(feed_id: str, items: Iterable[ParsedItem], *, engine=None) -> SaveResult:
    """피드 한 개의 항목을 저장합니다. 실패하면 해당 호출 전체가 롤백됩니다.

    enabled는 HTTP 자동 수집의 설정이며 이 함수는 이미 확보한 XML을 저장합니다.
    DB 피드의 collect/store가 모두 allowed여야 합니다. 예외를 빈 결과로 바꾸지 않습니다.
    """
    items = list(items)
    if any(item.feed.feed_id != feed_id or item.storage["feed_id"] != feed_id for item in items):
        raise RSSStorageError("한 번에 같은 피드의 항목만 저장할 수 있습니다.")
    engine = _get_engine(engine)
    ids = []
    linked = 0
    with engine.begin() as connection:
        feed = connection.execute(text("""
            SELECT id, publisher_id, default_category, rights FROM private.rss_feeds
            WHERE id = :id FOR UPDATE
        """), {"id": feed_id}).mappings().first()
        if feed is None:
            raise RSSStorageError("등록되지 않은 피드입니다.")
        rights = _object(feed["rights"])
        if any(rights[key] != "allowed" for key in ("collect", "store")):
            raise RSSStorageError("수집·저장 허용이 확인된 피드만 저장할 수 있습니다.")
        for item in items:
            data = item.storage
            if (item.feed.publisher_id != feed["publisher_id"]
                    or item.feed.default_category != feed["default_category"]
                    or data["category"] != feed["default_category"]
                    or dict(item.feed.rights) != rights or data["rights_snapshot"] != rights
                    or data["is_demo"] != item.feed.is_demo):
                raise RSSStorageError("파싱할 때 사용한 설정이 현재 DB 피드와 다릅니다.")
            previous = connection.execute(text("""
                SELECT id, article_id, last_seen_at FROM private.rss_items
                WHERE feed_id = :feed_id AND item_key = :item_key
            """), {"feed_id": feed_id, "item_key": data["item_key"]}).mappings().first()
            if previous and _timestamp(previous["last_seen_at"]) > _timestamp(data["last_seen_at"]):
                # 늦게 도착한 과거 수신 자료가 최신 수신 값을 되돌리지 않게 합니다.
                ids.append(previous["id"])
                linked += int(previous["article_id"] is not None)
                continue
            article_id = _article_id(connection, item)
            params = {
                key: _json(data[key]) if key in JSON_COLUMNS else
                _timestamp(data[key]) if key in TIME_COLUMNS else data[key]
                for key in ITEM_COLUMNS
            }
            params["article_id"] = article_id
            ids.append(connection.execute(UPSERT_ITEM, params).scalar_one())
            linked += int(article_id is not None)
        now = datetime.now(timezone.utc)
        connection.execute(text("""
            UPDATE private.rss_feeds SET last_attempt_at = :now,
                last_success_at = :now, last_error_code = NULL WHERE id = :id
        """), {"now": now, "id": feed_id})
    return SaveResult(len(items), linked, len(items) - linked, tuple(ids))
