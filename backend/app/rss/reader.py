"""팀원이 API 연결에서 사용할 내부 RSS 조회 함수입니다."""

from sqlalchemy import text

from .storage import _get_engine, _object, _timestamp


SELECT_RECORD = """
    SELECT i.article_id, i.id, i.feed_id, f.publisher_id, p.name AS publisher_name,
        i.item_key, i.source_item_id, i.original_url, i.canonical_url, i.title,
        i.category, i.author, i.source_category, i.rss_description, i.published_at,
        i.collected_at, i.parse_status, i.body_status, i.rights_snapshot, i.is_demo
    FROM private.rss_items i
    JOIN private.rss_feeds f ON f.id = i.feed_id
    JOIN public.publishers p ON p.id = f.publisher_id
    WHERE i.parse_status IN ('parsed', 'partial') AND i.body_status <> 'blocked'
        AND i.rights_snapshot->>'collect' = 'allowed'
        AND i.rights_snapshot->>'store' = 'allowed'
        AND f.rights->>'collect' = 'allowed' AND f.rights->>'store' = 'allowed'
"""


def _record(row):
    keys = (
        "id", "feed_id", "publisher_id", "publisher_name", "item_key", "source_item_id",
        "original_url", "canonical_url", "title", "category", "author", "source_category",
        "rss_description", "parse_status", "body_status", "is_demo",
    )
    return {
        "schema_version": "1.0", **{key: row[key] for key in keys},
        "published_at": _timestamp(row["published_at"]).isoformat() if row["published_at"] else None,
        "collected_at": _timestamp(row["collected_at"]).isoformat(),
        "rights": _object(row["rights_snapshot"]),
    }


class RSSReader:
    """engine를 주입할 수 있는 조회 구현. 기본값은 기존 db.py의 engine입니다."""

    def __init__(self, engine=None):
        self.engine = engine

    def list_records(self, limit: int = 10) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit는 1~100 사이의 정수여야 합니다.")
        with _get_engine(self.engine).connect() as connection:
            rows = connection.execute(text(SELECT_RECORD + """
                ORDER BY i.collected_at DESC, i.id ASC LIMIT :limit
            """), {"limit": limit}).mappings().all()
        return [_record(row) for row in rows]

    def get_record(self, record_id: str) -> dict | None:
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValueError("record_id에는 비어 있지 않은 문자열이 필요합니다.")
        with _get_engine(self.engine).connect() as connection:
            row = connection.execute(text(SELECT_RECORD + " AND i.id = :id"),
                                     {"id": record_id}).mappings().first()
        return _record(row) if row else None


def list_rss_records(limit: int = 10) -> list[dict]:
    """표시 가능한 내부 RSS 목록. DB 실패는 호출자에게 예외로 전달합니다."""
    return RSSReader().list_records(limit)


def get_rss_record(record_id: str) -> dict | None:
    """표시할 수 있는 항목 한 개. 없거나 제외 대상일 때만 None을 반환합니다."""
    return RSSReader().get_record(record_id)


def list_rss_article_links(limit: int = 100) -> dict[str, str]:
    """Internal canonical URL -> DB article ID. Public RSS record keys stay unchanged."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    with _get_engine().connect() as connection:
        rows = connection.execute(text(SELECT_RECORD + " ORDER BY i.collected_at DESC, i.id ASC LIMIT :limit"),
                                  {"limit": limit}).mappings().all()
    return {row["canonical_url"]: row["article_id"] for row in rows if row["article_id"]}
