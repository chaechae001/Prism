"""Create an unpublished single-article story with the DB article identifier."""

from hashlib import sha256
from sqlalchemy import text
from ..db import get_engine
from ..rss.reader import SELECT_RECORD, _record
from ..rss_preview import RssRecord, rss_to_story


def prepare_rss_story(record_id: str, *, engine=None):
    db = engine or get_engine()
    with db.begin() as connection:
        row = (
            connection.execute(
                text(
                    SELECT_RECORD
                    + " AND i.id=:id AND f.rights->>'summarize'='allowed' AND f.rights->>'publish_summary'='allowed'"
                ),
                {"id": record_id},
            )
            .mappings()
            .first()
        )
        if row is None or row["article_id"] is None:
            raise ValueError("RSS item has no eligible DB article")
        record = RssRecord.model_validate(_record(row))
        if record.rights.summarize != "allowed":
            raise ValueError("RSS summary processing is not approved")
        story, reason = rss_to_story(record, article_id=row["article_id"])
        if story is None:
            raise ValueError("RSS projection held: " + reason)
        story_id = "rss-story-" + sha256(row["article_id"].encode()).hexdigest()[:24]
        connection.execute(
            text("""
            INSERT INTO public.stories
              (id,title,dek,category,visual,is_demo,summary_status,summary,keywords,label_status)
            VALUES (:id,:title,:dek,:category,:visual,:demo,'pending',
                    '{"bullets":[],"unknowns":[]}'::jsonb,'{}','unverified')
            ON CONFLICT (id) DO NOTHING
        """),
            {
                "id": story_id,
                "title": story.title,
                "dek": "RSS 기사 1건 · 본문 요약 준비 중",
                "category": story.category,
                "visual": story.visual,
                "demo": story.is_demo,
            },
        )
        connection.execute(
            text("""
            INSERT INTO public.story_articles(story_id,article_id,same_event_verified)
            VALUES (:story,:article,true) ON CONFLICT DO NOTHING
        """),
            {"story": story_id, "article": row["article_id"]},
        )
    return {"story_id": story_id, "article_id": row["article_id"], "published": False}
