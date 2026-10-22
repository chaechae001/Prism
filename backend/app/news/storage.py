"""Private Postgres storage. Credentials are server-only, never returned by the API."""

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
from functools import wraps
from uuid import uuid4

from .models import AnalysisArticle, AnalysisBatch, BodyImport, NewsRecord, digest


def atomic(fn):
    @wraps(fn)
    def wrapped(conn, *args, **kwargs):
        with conn.transaction():
            return fn(conn, *args, **kwargs)

    return wrapped


@contextmanager
def connect():
    import psycopg
    from psycopg.rows import dict_row

    dsn = os.getenv("NEWS_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("NEWS_DATABASE_URL_MISSING")
    with psycopg.connect(
        dsn, row_factory=dict_row, connect_timeout=10, prepare_threshold=None
    ) as conn:
        with conn.transaction():
            yield conn


def jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def signature(article: NewsRecord) -> str:
    return digest(
        article.model_dump(
            mode="json",
            exclude={"collected_at", "snippet", "provider_url", "original_url"},
        )
    )


@atomic
def save_article(conn, article: NewsRecord, *, query: str, raw: dict):
    old = conn.execute(
        "select record from private.news_v2_articles where id=%s for update",
        (article.id,),
    ).fetchone()
    if old:
        previous = NewsRecord.model_validate(old["record"])
        if previous.is_demo != article.is_demo:
            raise ValueError("DEMO_REAL_ID_COLLISION")
        article = article.model_copy(
            update={
                "publisher_published_at": previous.publisher_published_at
                or article.publisher_published_at,
                "publisher": article.publisher or previous.publisher,
                "category": previous.category
                if previous.category_basis == "reviewed"
                else article.category,
                "category_basis": previous.category_basis
                if previous.category_basis == "reviewed"
                else article.category_basis,
            }
        )
    conn.execute(
        """insert into private.news_v2_articles
      (id,canonical_url,title,category,record,analysis_signature,publisher_id,publisher_group_id,
       provider_published_at,publisher_published_at,is_demo)
      values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      on conflict(id) do update set title=excluded.title, category=excluded.category, record=excluded.record,
        analysis_signature=excluded.analysis_signature,publisher_id=excluded.publisher_id,
        publisher_group_id=excluded.publisher_group_id,provider_published_at=excluded.provider_published_at,
        publisher_published_at=excluded.publisher_published_at,updated_at=now()""",
        (
            article.id,
            str(article.canonical_url),
            article.title,
            article.category,
            jsonb(article.model_dump(mode="json")),
            signature(article),
            article.publisher.id if article.publisher else None,
            article.publisher.group_id if article.publisher else None,
            article.provider_published_at,
            article.publisher_published_at,
            article.is_demo,
        ),
    )
    conn.execute(
        """insert into private.news_v2_observations(article_id,provider,query,payload,payload_hash)
      values (%s,%s,%s,%s,%s) on conflict(article_id,provider,query,payload_hash)
      do update set last_seen_at=now()""",
        (article.id, article.provider, query, jsonb(raw), digest(raw)),
    )
    return article


@atomic
def save_body(conn, body: BodyImport):
    row = conn.execute(
        "select * from private.news_v2_articles where id=%s for update",
        (body.article_id,),
    ).fetchone()
    if not row:
        raise ValueError("UNKNOWN_ARTICLE")
    if not body.rights.store:
        raise ValueError("BODY_STORAGE_NOT_ALLOWED")
    if body.source_kind == "demo" and not row["is_demo"]:
        raise ValueError("DEMO_BODY_FOR_REAL_ARTICLE")
    text = "\n".join(" ".join(line.split()) for line in body.text.splitlines()).strip()
    if not text:
        raise ValueError("EMPTY_BODY")
    content_hash = sha256(text.encode()).hexdigest()
    provenance = body.model_dump(mode="json", exclude={"text", "article_id"})
    # acquired_at is observation time, not a new content/permission revision on repeat imports.
    fingerprint = digest({k: v for k, v in provenance.items() if k != "acquired_at"})
    inserted = conn.execute(
        """insert into private.news_v2_bodies
      (article_id,text,content_hash,provenance_hash,content_kind,provenance,rights,acquired_at)
      values (%s,%s,%s,%s,%s,%s,%s,%s)
      on conflict(article_id,content_hash,provenance_hash) do nothing returning id""",
        (
            body.article_id,
            text,
            content_hash,
            fingerprint,
            body.content_kind,
            jsonb(provenance),
            jsonb(body.rights.model_dump()),
            body.acquired_at,
        ),
    ).fetchone()
    if not inserted:
        # Replaying an older revision must not overwrite the latest body pointer.
        return conn.execute(
            """select id from private.news_v2_bodies where
            article_id=%s and content_hash=%s and provenance_hash=%s""",
            (body.article_id, content_hash, fingerprint),
        ).fetchone()["id"]
    article = NewsRecord.model_validate(row["record"])
    if body.publisher_published_at:
        article = article.model_copy(
            update={"publisher_published_at": body.publisher_published_at}
        )
    conn.execute(
        """update private.news_v2_articles set current_body_id=%s,record=%s,
        publisher_published_at=%s,analysis_signature=%s,updated_at=now() where id=%s""",
        (
            inserted["id"],
            jsonb(article.model_dump(mode="json")),
            article.publisher_published_at,
            signature(article),
            body.article_id,
        ),
    )
    return inserted["id"]


@atomic
def export_batch(
    conn, *, min_chars=200, allow_excerpt=False, limit=500
) -> AnalysisBatch:
    if min_chars < 1 or not 1 <= limit <= 1000:
        raise ValueError("INVALID_EXPORT_LIMIT")
    rows = conn.execute(
        """select a.*,b.id as body_id,b.text,b.content_hash,b.content_kind,b.rights
        from private.news_v2_articles a left join private.news_v2_bodies b on b.id=a.current_body_id
        order by a.first_seen_at,a.id limit %s""",
        (limit,),
    ).fetchall()
    articles, excluded = [], Counter()
    for row in rows:
        article = NewsRecord.model_validate(row["record"])
        reason = (
            "body_missing"
            if not row["body_id"]
            else "publisher_unresolved"
            if not article.publisher
            else "date_missing"
            if not (article.publisher_published_at or article.provider_published_at)
            else "future_date"
            if (article.publisher_published_at or article.provider_published_at)
            > datetime.now(timezone.utc)
            else "cluster_not_allowed"
            if not row["rights"].get("cluster")
            else "excerpt_not_enabled"
            if row["content_kind"] != "full_text" and not allow_excerpt
            else "body_too_short"
            if len(row["text"]) < min_chars
            else None
        )
        if reason:
            excluded[reason] += 1
            continue
        articles.append(
            AnalysisArticle(
                article=article,
                body_version_id=row["body_id"],
                content_hash=row["content_hash"],
                text=row["text"],
                text_basis=row["content_kind"],
                rights=row["rights"],
            )
        )
    input_hash = digest(
        [
            {
                "id": str(a.article.id),
                "signature": signature(a.article),
                "body": str(a.body_version_id),
                "hash": a.content_hash,
            }
            for a in articles
        ]
    )
    candidates = conn.execute(
        "select count(*) as n from private.news_v2_articles"
    ).fetchone()["n"]
    batch = AnalysisBatch(
        run_id=uuid4(),
        input_hash=input_hash,
        articles=articles,
        excluded=dict(excluded),
        selection={
            "limit": limit,
            "candidate_total": candidates,
            "considered": len(rows),
            "truncated": candidates > limit,
        },
    )
    conn.execute(
        "insert into private.news_v2_runs(id,input_hash,excluded) values (%s,%s,%s)",
        (batch.run_id, batch.input_hash, jsonb(batch.excluded)),
    )
    for item in articles:
        conn.execute(
            """insert into private.news_v2_run_inputs(run_id,article_id,body_id,article_signature,article_snapshot)
            values (%s,%s,%s,%s,%s)""",
            (
                batch.run_id,
                item.article.id,
                item.body_version_id,
                signature(item.article),
                jsonb(item.article.model_dump(mode="json")),
            ),
        )
    return batch
