"""Atomic analyst body import into the existing private.raw_articles table."""

import json
from hashlib import sha256
from sqlalchemy import text
from ..db import get_engine
from ..models import AnalystBatch
from .analyst_validation import InvalidAnalystBatch, check_batch


def import_bodies(batch: AnalystBatch, *, engine=None):
    checked = check_batch(batch)
    if not checked.report["valid"]:
        raise InvalidAnalystBatch(checked.report)
    with (engine or get_engine()).begin() as connection:
        return _store_bodies(connection, batch)


def _store_bodies(connection, batch: AnalystBatch):
    """Store an already validated batch inside the caller's transaction."""
    result = []
    for article in batch.articles:
        uses = set(article.allowed_uses)
        if article.license_status != "allowed" or not {"collect", "store"} <= uses:
            raise ValueError("Body collection/storage is not approved")
        digest = sha256(article.text.encode()).hexdigest()
        if article.content_hash != digest:
            raise ValueError(
                "Body content_hash must be the SHA-256 of the supplied UTF-8 text"
            )
        row = (
            connection.execute(
                text("""
            SELECT id, publisher_id FROM public.articles WHERE canonical_url=:url FOR UPDATE
        """),
                {"url": str(article.canonical_url)},
            )
            .mappings()
            .first()
        )
        if row is None or row["publisher_id"] != article.publisher_id:
            raise ValueError("Body URL/publisher must match an existing DB article")
        previous = (
            connection.execute(
                text("""
            SELECT content_hash, license_status, allowed_uses FROM private.raw_articles
            WHERE canonical_url=:url FOR UPDATE
        """),
                {"url": str(article.canonical_url)},
            )
            .mappings()
            .first()
        )
        changed = previous is None or (
            previous["content_hash"],
            previous["license_status"],
            set(previous["allowed_uses"]),
        ) != (digest, article.license_status, uses)
        connection.execute(
            text("""
            INSERT INTO private.raw_articles
              (id,publisher_id,canonical_url,content_hash,raw_text,license_status,allowed_uses,
               rights_evidence,batch_id,collected_at)
            VALUES (:id,:publisher,:url,:hash,:body,:license,:uses,CAST(:evidence AS jsonb),:batch,:at)
            ON CONFLICT (canonical_url) DO UPDATE SET content_hash=EXCLUDED.content_hash,
              raw_text=EXCLUDED.raw_text,license_status=EXCLUDED.license_status,
              allowed_uses=EXCLUDED.allowed_uses,batch_id=EXCLUDED.batch_id,
              collected_at=EXCLUDED.collected_at,rights_evidence=EXCLUDED.rights_evidence
        """),
            {
                "id": row["id"],
                "publisher": article.publisher_id,
                "url": str(article.canonical_url),
                "hash": digest,
                "body": article.text,
                "license": article.license_status,
                "uses": sorted(uses),
                "evidence": json.dumps(
                    {"batch_id": batch.batch_id, "input_article_id": article.id}
                ),
                "batch": batch.batch_id,
                "at": article.collected_at,
            },
        )
        if changed:
            connection.execute(
                text("""
                UPDATE public.stories SET event_version=event_version+1,summary_status='pending',
                  updated_at=now() WHERE id IN
                  (SELECT story_id FROM public.story_articles WHERE article_id=:id)
            """),
                {"id": row["id"]},
            )
        result.append(
            {
                "input_article_id": article.id,
                "article_id": row["id"],
                "changed": changed,
            }
        )
    return result
