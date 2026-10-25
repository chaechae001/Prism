"""DB read adapter. Public v1 Story fields remain unchanged."""

import json
from sqlalchemy import bindparam, text
from .db import get_engine
from .models import Story

MAX_SNAPSHOT = 500
STORY_SELECT = """
SELECT s.id, s.title, s.category, s.dek, s.updated_at, s.keywords, s.visual,
       s.public_interest, s.is_demo, s.summary_status, s.summary, s.perspectives,
       s.label_status
FROM public.stories s
WHERE s.published_at IS NOT NULL AND s.published_at <= now()
  AND s.retracted_at IS NULL
"""
ARTICLE_SELECT = """
SELECT sa.story_id, a.id, a.publisher_id, p.name AS publisher_name,
       a.title, a.canonical_url AS url, a.published_at, a.framing, a.is_demo
FROM public.story_articles sa
JOIN public.articles a ON a.id=sa.article_id
JOIN public.publishers p ON p.id=a.publisher_id
WHERE sa.story_id IN :ids AND sa.same_event_verified=true
  AND a.publish_allowed=true AND a.published_at <= now()
ORDER BY a.published_at, a.id
"""


def _object(value):
    return json.loads(value) if isinstance(value, str) else value


def _to_api_news(news_row, article_rows):
    articles = [
        {key: value for key, value in dict(row).items() if key != "story_id"}
        for row in article_rows
    ]
    # The feed requires a source; hold stories with no publishable related articles.
    if not articles:
        return None
    for article in articles:
        article["framing"] = article.get("framing") or "쟁점 분류 전"
    summary = dict(_object(news_row["summary"]))
    summary["status"] = news_row["summary_status"]
    perspectives = _object(news_row["perspectives"])
    ids = {a["id"] for a in articles}
    if summary["status"] == "ready":
        if any(
            not b.get("article_ids") or not set(b["article_ids"]) <= ids
            for b in [*summary.get("bullets", []), *perspectives]
        ):
            # Withdrawn source metadata must never leave dangling published citations.
            summary = {
                "status": "pending",
                "bullets": [],
                "unknowns": ["요약의 출처 변경을 확인하고 있습니다."],
            }
            perspectives = []
    result = {
        key: news_row[key]
        for key in (
            "id",
            "title",
            "category",
            "dek",
            "updated_at",
            "keywords",
            "visual",
            "public_interest",
            "is_demo",
        )
    }
    result.update(
        summary=summary,
        perspectives=perspectives,
        articles=articles,
        coverage={
            "publisher_count": len({a["publisher_id"] for a in articles}),
            "article_count": len(articles),
            "perspective_count": len(perspectives),
            "label_status": news_row["label_status"],
        },
    )
    return Story.model_validate(result).model_dump(mode="json")


def _read(story_id=None, *, engine=None):
    sql = STORY_SELECT
    params = {}
    if story_id is not None:
        sql += " AND s.id=:id"
        params["id"] = story_id
    sql += " ORDER BY s.updated_at DESC, s.id LIMIT :cap"
    params["cap"] = MAX_SNAPSHOT + 1
    with (engine or get_engine()).connect() as connection:
        # A single read transaction prevents metadata drift between story/article queries.
        rows = connection.execute(text(sql), params).mappings().all()
        if len(rows) > MAX_SNAPSHOT:
            raise RuntimeError("Snapshot limit exceeded; enable DB-level pagination")
        if not rows:
            return []
        statement = text(ARTICLE_SELECT).bindparams(bindparam("ids", expanding=True))
        article_rows = (
            connection.execute(statement, {"ids": [r["id"] for r in rows]})
            .mappings()
            .all()
        )
    grouped = {}
    for row in article_rows:
        grouped.setdefault(row["story_id"], []).append(row)
    return [
        value
        for row in rows
        if (value := _to_api_news(row, grouped.get(row["id"], []))) is not None
    ]


def list_news_from_db(*, engine=None):
    return _read(engine=engine)


def get_news_from_db(news_id: str, *, engine=None):
    rows = _read(news_id, engine=engine)
    return rows[0] if rows else None
