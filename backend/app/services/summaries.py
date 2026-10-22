"""Offline summary generation and explicit approval. No generation on feed reads."""

import json
from hashlib import sha256
from sqlalchemy import text
from ..db import get_engine
from ..llm.schemas import ArticleBody
from ..llm.elice_client import summarize_with_elice
from ..llm.elice_settings import EliceSettings
from ..llm.prompts import PROMPT_VERSION
from .article_context import load_bodies


class StaleSummaryError(ValueError):
    pass


def _load_input(story_id, *, engine=None):
    db = engine or get_engine()
    with db.connect() as connection:
        story = (
            connection.execute(
                text("""
            SELECT id,title,event_version,retracted_at FROM public.stories WHERE id=:id
        """),
                {"id": story_id},
            )
            .mappings()
            .first()
        )
        if story is None or story["retracted_at"] is not None:
            raise ValueError("Story not found or withdrawn")
        rows = (
            connection.execute(
                text("""
            SELECT a.id FROM public.story_articles sa JOIN public.articles a ON a.id=sa.article_id
            WHERE sa.story_id=:id AND sa.same_event_verified=true
            ORDER BY a.id
        """),
                {"id": story_id},
            )
            .mappings()
            .all()
        )
    ids = [row["id"] for row in rows]
    if not ids:
        raise ValueError("Story needs verified article links")
    bodies = load_bodies(ids, engine=db)
    if set(bodies) != set(ids) or any(
        not body["publish_summary"] for body in bodies.values()
    ):
        raise ValueError(
            "Every linked article needs a permitted body and summary publication approval"
        )
    # Bound the synchronous offline job; use a queued workflow for larger event sets.
    if len(ids) > 10:
        raise ValueError("At most 10 articles per offline summary job")
    articles = [
        ArticleBody.model_validate(
            {key: bodies[id][key] for key in ("id", "title", "text", "is_demo")}
        )
        for id in ids
    ]
    fingerprint = sha256(
        json.dumps(
            {
                "articles": [
                    {
                        "id": a.id,
                        "title": a.title,
                        "hash": bodies[a.id]["content_hash"],
                        "is_demo": a.is_demo,
                    }
                    for a in articles
                ]
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return dict(story), articles, fingerprint


def generate_summary(story_id, *, engine=None, generate=None, settings=None):
    db = engine or get_engine()
    story, articles, fingerprint = _load_input(story_id, engine=db)
    config = settings or EliceSettings.from_env()
    with db.connect() as connection:
        prior = (
            connection.execute(
                text("""
            SELECT id, review_status FROM private.summary_versions
            WHERE story_id=:id AND event_version=:version AND article_set_hash=:hash
              AND model_version=:model AND prompt_version=:prompt
        """),
                {
                    "id": story_id,
                    "version": story["event_version"],
                    "hash": fingerprint,
                    "model": config.model,
                    "prompt": PROMPT_VERSION,
                },
            )
            .mappings()
            .first()
        )
    if prior is not None:
        return {"id": prior["id"], "cached": True, "status": prior["review_status"]}
    # The existing single-article summarizer is reused without inventing cross-source perspectives.
    summarize = generate or (lambda article: summarize_with_elice(article, config))
    outputs = [summarize(article) for article in articles]
    if any(
        output.article_id != article.id
        or output.is_mock
        or output.is_demo != article.is_demo
        for article, output in zip(articles, outputs)
    ):
        raise ValueError(
            "Generated summaries must refer to the matching input articles"
        )
    merged = {
        "title": outputs[0].summary.title if len(articles) == 1 else story["title"],
        "bullets": [
            bullet.model_dump()
            for output in outputs
            for bullet in output.summary.bullets
        ],
        "perspectives": [],
        "unknowns": list(
            dict.fromkeys(
                value for output in outputs for value in output.summary.unknowns
            )
        ),
    }
    # Display is explicitly a collection of article summaries, not a generated consensus.
    payload = {
        "summary": merged,
        "article_summaries": [o.model_dump(mode="json") for o in outputs],
        "kind": "single_article"
        if len(articles) == 1
        else "article_summary_collection",
        "input_hash": fingerprint,
    }
    # Recheck after billable calls. Changing bodies/membership requires a new draft.
    current, _, current_hash = _load_input(story_id, engine=db)
    if (
        current["event_version"] != story["event_version"]
        or current_hash != fingerprint
    ):
        raise StaleSummaryError("Summary inputs changed during generation")
    with db.begin() as connection:
        locked = connection.execute(
            text("SELECT event_version FROM public.stories WHERE id=:id FOR UPDATE"),
            {"id": story_id},
        ).scalar_one()
        if locked != story["event_version"]:
            raise StaleSummaryError("Story version changed")
        row = connection.execute(
            text("""
            INSERT INTO private.summary_versions
              (story_id,event_version,article_set_hash,model_version,prompt_version,output)
            VALUES (:id,:version,:hash,:model,:prompt,CAST(:output AS jsonb))
            ON CONFLICT (story_id,event_version,article_set_hash,model_version,prompt_version)
            DO NOTHING RETURNING id
        """),
            {
                "id": story_id,
                "version": story["event_version"],
                "hash": fingerprint,
                "model": config.model,
                "prompt": PROMPT_VERSION,
                "output": json.dumps(payload, ensure_ascii=False),
            },
        ).scalar()
        if row is None:
            row = connection.execute(
                text("""
                SELECT id FROM private.summary_versions WHERE story_id=:id AND event_version=:version
                AND article_set_hash=:hash AND model_version=:model AND prompt_version=:prompt
            """),
                {
                    "id": story_id,
                    "version": story["event_version"],
                    "hash": fingerprint,
                    "model": config.model,
                    "prompt": PROMPT_VERSION,
                },
            ).scalar_one()
    return {"id": row, "cached": False, "status": "pending"}


def approve_summary(version_id: int, *, engine=None):
    db = engine or get_engine()
    with db.begin() as connection:
        draft = (
            connection.execute(
                text("SELECT * FROM private.summary_versions WHERE id=:id FOR UPDATE"),
                {"id": version_id},
            )
            .mappings()
            .first()
        )
        if not draft or draft["review_status"] == "rejected":
            raise ValueError("Summary draft not available")
        story = connection.execute(
            text("SELECT event_version FROM public.stories WHERE id=:id FOR UPDATE"),
            {"id": draft["story_id"]},
        ).scalar_one()
        current, articles, fingerprint = _load_input(draft["story_id"], engine=db)
        if story != draft["event_version"] or fingerprint != draft["article_set_hash"]:
            raise StaleSummaryError("Summary is stale; regenerate before approval")
        output = (
            draft["output"]
            if isinstance(draft["output"], dict)
            else json.loads(draft["output"])
        )
        summary = output["summary"]
        # The public summary model has no title or internal job metadata.
        ids = {a.id for a in articles}
        if any(
            not b["article_ids"] or not set(b["article_ids"]) <= ids
            for b in summary["bullets"]
        ):
            raise ValueError("Invalid published citation")
        rows = (
            connection.execute(
                text("""
            SELECT a.publish_allowed FROM public.story_articles sa JOIN public.articles a ON a.id=sa.article_id
            WHERE sa.story_id=:id AND sa.same_event_verified=true
        """),
                {"id": draft["story_id"]},
            )
            .mappings()
            .all()
        )
        if not rows or not all(row["publish_allowed"] for row in rows):
            raise ValueError("Article metadata publication approval is required")
        public_summary = {
            "bullets": summary["bullets"],
            "unknowns": summary["unknowns"],
            "model_version": draft["model_version"],
            "prompt_version": draft["prompt_version"],
        }
        notice = (
            "기사별 본문 요약 모음 · 사건 통합 요약 아님"
            if len(articles) > 1
            else "기사 본문 요약"
        )
        connection.execute(
            text("""
            UPDATE public.stories SET summary=CAST(:summary AS jsonb),summary_status='ready',
              title=:title,dek=:notice,perspectives='[]'::jsonb,updated_at=now(),
              published_at=COALESCE(published_at,now()) WHERE id=:id AND retracted_at IS NULL
        """),
            {
                "summary": json.dumps(public_summary, ensure_ascii=False),
                "title": summary["title"],
                "notice": notice,
                "id": draft["story_id"],
            },
        )
        connection.execute(
            text(
                "UPDATE private.summary_versions SET review_status='approved' WHERE id=:id"
            ),
            {"id": version_id},
        )
    return {"id": version_id, "status": "approved"}
