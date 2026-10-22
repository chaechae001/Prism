"""Validates analyst outputs and materializes reviewed publications. Does not call an LLM."""

from collections import Counter
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from ..models import Story
from .models import AnalysisOutput, NewsRecord, ResultBatch, digest
from .storage import jsonb, atomic


def input_rows(conn, event_id, run_id):
    return conn.execute(
        """select i.*,a.current_body_id,a.analysis_signature,b.text,b.rights,b.content_hash
        from private.news_v2_members m join private.news_v2_run_inputs i
          on i.run_id=m.run_id and i.article_id=m.article_id
        join private.news_v2_articles a on a.id=i.article_id
        join private.news_v2_bodies b on b.id=i.body_id
        where m.event_id=%s and m.run_id=%s order by i.article_id""",
        (event_id, run_id),
    ).fetchall()


def require_current(rows):
    if not rows or any(
        r["current_body_id"] != r["body_id"]
        or r["analysis_signature"] != r["article_signature"]
        for r in rows
    ):
        raise ValueError("STALE_OR_EMPTY_INPUT")


def validate_output(output: AnalysisOutput, rows):
    if output.status != "ready":
        return
    payload = output.payload
    permission = "analyze" if output.mode == "sentiment" else "summarize"
    if any(not r["rights"].get(permission) for r in rows):
        raise ValueError("ANALYSIS_USE_NOT_ALLOWED")
    ids = {str(r["article_id"]) for r in rows}
    if output.mode == "sentiment":
        texts = {str(r["article_id"]): r["text"] for r in rows}
        observed = set()
        for observation in payload["observations"]:
            key = observation["article_id"]
            if (
                key not in ids
                or key in observed
                or observation["evidence"] not in texts[key]
            ):
                raise ValueError("INVALID_SENTIMENT_EVIDENCE")
            observed.add(key)
        return
    claims = (
        [*payload["bullets"], *payload["perspectives"]]
        if output.mode == "summary"
        else [*payload["paragraphs"], *payload["glossary"]]
        if output.mode == "easy"
        else [
            payload[k]
            for k in ("who", "what", "when", "where", "why")
            if payload[k] is not None
        ]
    )
    if not claims:
        raise ValueError("EMPTY_FACTS")
    for claim in claims:
        if (
            not claim.get("text", "").strip()
            or not claim.get("article_ids")
            or not set(claim["article_ids"]) <= ids
        ):
            raise ValueError("CITATION_OUTSIDE_EVENT")
    # Membership/exact quote checks do not prove factual entailment: review remains necessary.


@atomic
def import_results(conn, batch: ResultBatch):
    run = conn.execute(
        "select * from private.news_v2_runs where id=%s for update", (batch.run_id,)
    ).fetchone()
    if not run or run["input_hash"] != batch.input_hash:
        raise ValueError("RUN_OR_INPUT_HASH_MISMATCH")
    available = {
        r["article_id"]
        for r in conn.execute(
            "select article_id from private.news_v2_run_inputs where run_id=%s",
            (batch.run_id,),
        ).fetchall()
    }
    used, event_keys, event_ids = set(), set(), []
    for cluster in batch.clusters:
        ids = set(cluster.article_ids)
        if (
            len(ids) != len(cluster.article_ids)
            or not ids <= available
            or used & ids
            or cluster.event_key in event_keys
        ):
            raise ValueError("INVALID_CLUSTER_MEMBERSHIP")
        if len({o.mode for o in cluster.outputs}) != len(cluster.outputs):
            raise ValueError("DUPLICATE_MODE")
        used |= ids
        event_keys.add(cluster.event_key)
        event_id = uuid5(NAMESPACE_URL, "prism:event:" + cluster.event_key)
        conn.execute(
            """insert into private.news_v2_events(id,event_key,current_run_id,same_event_verified,cluster_model_version,category)
          values (%s,%s,%s,%s,%s,%s) on conflict(event_key) do update set current_run_id=excluded.current_run_id,
          same_event_verified=excluded.same_event_verified,cluster_model_version=excluded.cluster_model_version,category=excluded.category""",
            (
                event_id,
                cluster.event_key,
                batch.run_id,
                cluster.same_event_verified,
                batch.cluster_model_version,
                cluster.category,
            ),
        )
        previous = {
            r["article_id"]
            for r in conn.execute(
                """select article_id from private.news_v2_members
            where event_id=%s and run_id=%s""",
                (event_id, batch.run_id),
            ).fetchall()
        }
        if previous and previous != ids:
            raise ValueError("SAME_RUN_EVENT_MEMBERSHIP_CHANGED")
        for article_id in ids:
            conn.execute(
                """insert into private.news_v2_members(event_id,run_id,article_id) values(%s,%s,%s)
                on conflict do nothing""",
                (event_id, batch.run_id, article_id),
            )
        rows = input_rows(conn, event_id, batch.run_id)
        require_current(rows)
        for output in cluster.outputs:
            validate_output(output, rows)
            conn.execute(
                """insert into private.news_v2_analyses(event_id,run_id,mode,status,payload,payload_hash,model_version,prompt_version)
              values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing""",
                (
                    event_id,
                    batch.run_id,
                    output.mode,
                    output.status,
                    jsonb(output.payload) if output.payload else None,
                    digest(output.model_dump(mode="json")),
                    output.model_version,
                    output.prompt_version,
                ),
            )
        event_ids.append(str(event_id))
    conn.execute(
        "update private.news_v2_runs set status='imported' where id=%s", (batch.run_id,)
    )
    return event_ids


@atomic
def publish(conn, event_id, *, reviewed: bool, modes=("summary",)):
    if (
        not reviewed
        or "summary" not in modes
        or not set(modes) <= {"summary", "five_w", "easy", "sentiment"}
    ):
        raise ValueError("EXPLICIT_REVIEW_REQUIRED")
    event = conn.execute(
        "select * from private.news_v2_events where id=%s for update", (event_id,)
    ).fetchone()
    if not event or not event["same_event_verified"]:
        raise ValueError("SAME_EVENT_REVIEW_REQUIRED")
    rows = input_rows(conn, event_id, event["current_run_id"])
    require_current(rows)
    articles = [NewsRecord.model_validate(r["article_snapshot"]) for r in rows]
    if (
        any(not a.publisher for a in articles)
        or len({a.publisher.group_id for a in articles}) < 2
    ):
        raise ValueError("TWO_INDEPENDENT_PUBLISHERS_REQUIRED")
    if len({a.is_demo for a in articles}) > 1:
        raise ValueError("MIXED_REAL_AND_DEMO_INPUT")
    if any(not r["rights"].get("publish_summary") for r in rows):
        raise ValueError("PUBLICATION_NOT_ALLOWED")
    selected = {}
    for mode in modes:
        row = conn.execute(
            """select * from private.news_v2_analyses where event_id=%s and run_id=%s and mode=%s
            order by created_at desc,id desc limit 1""",
            (event_id, event["current_run_id"], mode),
        ).fetchone()
        if not row or row["status"] != "ready":
            raise ValueError("REQUESTED_MODE_NOT_READY")
        validate_output(
            AnalysisOutput.model_validate(
                {
                    k: row[k]
                    for k in (
                        "mode",
                        "status",
                        "payload",
                        "model_version",
                        "prompt_version",
                    )
                }
            ),
            rows,
        )
        conn.execute(
            "update private.news_v2_analyses set review_status='approved' where id=%s",
            (row["id"],),
        )
        selected[mode] = row
    summary = selected["summary"]
    output = summary["payload"]
    times = [a.publisher_published_at or a.provider_published_at for a in articles]
    if any(t is None or t > datetime.now(timezone.utc) for t in times):
        raise ValueError("MISSING_OR_FUTURE_ARTICLE_TIME")
    event_date = min(times).astimezone(ZoneInfo("Asia/Seoul")).date()
    category = (
        event["category"] or Counter(a.category for a in articles).most_common(1)[0][0]
    )
    story = Story.model_validate(
        {
            "id": str(event_id),
            "title": output["title"],
            "category": category,
            "dek": output["bullets"][0]["text"],
            "updated_at": max(times),
            "keywords": [],
            "visual": {
                "politics": "assembly",
                "economy": "market",
                "society": "city",
                "technology": "research",
            }[category],
            "coverage": {
                "publisher_count": len({a.publisher.id for a in articles}),
                "article_count": len(articles),
                "perspective_count": len(output["perspectives"]),
                "label_status": "demo" if articles[0].is_demo else "reviewed",
            },
            "summary": {
                "status": "ready",
                "bullets": output["bullets"],
                "unknowns": output["unknowns"],
                "model_version": summary["model_version"],
                "prompt_version": summary["prompt_version"],
            },
            "perspectives": output["perspectives"],
            "articles": [
                {
                    "id": str(a.id),
                    "publisher_id": a.publisher.id,
                    "publisher_name": a.publisher.name,
                    "title": a.title,
                    "url": str(a.canonical_url),
                    "published_at": t,
                    "framing": "사건 관련 원문",
                    "is_demo": a.is_demo,
                }
                for a, t in zip(articles, times)
            ],
            "public_interest": 0,
            "is_demo": articles[0].is_demo,
        }
    )
    conn.execute(
        """insert into private.news_v2_publications(event_id,run_id,analysis_id,event_date,category,story)
      values(%s,%s,%s,%s,%s,%s) on conflict(event_id) do update set run_id=excluded.run_id,
      analysis_id=excluded.analysis_id,event_date=excluded.event_date,category=excluded.category,
      story=excluded.story,published_at=now(),retracted_at=null""",
        (
            event_id,
            event["current_run_id"],
            summary["id"],
            event_date,
            category,
            jsonb(story.model_dump(mode="json")),
        ),
    )
    return story
