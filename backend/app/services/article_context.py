"""Only server-side reads of permitted article bodies; never exposed as feed fields."""

from hashlib import sha256
from sqlalchemy import bindparam, text
from ..db import get_engine

BODY_SQL = """
SELECT a.id, a.title, a.is_demo, r.raw_text, r.content_hash, r.license_status, r.allowed_uses
FROM public.articles a JOIN private.raw_articles r
  ON r.canonical_url=a.canonical_url AND r.publisher_id=a.publisher_id
WHERE a.id IN :ids
"""


def load_bodies(article_ids, *, engine=None):
    if not article_ids:
        return {}
    query = text(BODY_SQL).bindparams(bindparam("ids", expanding=True))
    with (engine or get_engine()).connect() as connection:
        rows = connection.execute(query, {"ids": list(article_ids)}).mappings().all()
    bodies = {}
    for row in rows:
        uses = set(row["allowed_uses"])
        if row["license_status"] != "allowed" or not {"store", "summarize"} <= uses:
            continue
        digest = sha256(row["raw_text"].encode()).hexdigest()
        if row["content_hash"] != digest:
            raise ValueError("Stored body fingerprint mismatch")
        bodies[row["id"]] = {
            "id": row["id"],
            "title": row["title"],
            "text": row["raw_text"],
            "content_hash": digest,
            "is_demo": row["is_demo"],
            "publish_summary": "publish_summary" in uses,
        }
    return bodies


def chat_bodies(story):
    bodies = load_bodies([a.id for a in story.articles])
    remaining, result = 24000, []
    for article in story.articles:
        body = bodies.get(article.id)
        if not body or remaining <= 0:
            continue
        excerpt = body["text"][: min(12000, remaining)]
        remaining -= len(excerpt)
        result.append(
            {
                "article_id": article.id,
                "text": excerpt,
                "is_excerpt": len(excerpt) < len(body["text"]),
            }
        )
    return result
