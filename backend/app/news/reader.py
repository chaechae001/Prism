from uuid import UUID
from copy import deepcopy

from .models import AnalysisResponse, ArticleContent

# Check freshness and permissions on EVERY public read, including old bookmarks.
VALID = """p.retracted_at is null and e.current_run_id=p.run_id and e.same_event_verified
 and s.review_status='approved' and s.status='ready'
 and not exists (
   select 1 from private.news_v2_members m
   join private.news_v2_run_inputs i on i.run_id=m.run_id and i.article_id=m.article_id
   join private.news_v2_articles a on a.id=i.article_id
   join private.news_v2_bodies b on b.id=i.body_id
   where m.event_id=p.event_id and m.run_id=p.run_id
   and (a.current_body_id is distinct from i.body_id or a.analysis_signature<>i.article_signature
     or not (b.rights @> '{"publish_summary":true,"store":true,"summarize":true,"cluster":true}'::jsonb)))"""
FROM = """from private.news_v2_publications p join private.news_v2_events e on e.id=p.event_id
          join private.news_v2_analyses s on s.id=p.analysis_id"""


def uuid_or_none(value):
    try:
        return UUID(str(value))
    except ValueError:
        return None


def publication(conn, story_id):
    key = uuid_or_none(story_id)
    if key is None:
        return None
    return conn.execute(
        f"select p.* {FROM} where {VALID} and p.event_id=%s", (key,)
    ).fetchone()


def list_publications(
    conn,
    *,
    q="",
    category=None,
    day=None,
    from_day=None,
    to_day=None,
    limit=6,
    offset=0,
):
    clauses, args = [VALID], []
    for value, clause in (
        (category, "p.category=%s"),
        (day, "p.event_date=%s"),
        (from_day, "p.event_date>=%s"),
        (to_day, "p.event_date<=%s"),
    ):
        if value is not None:
            clauses.append(clause)
            args.append(value)
    if q:
        clauses.append("(p.story->>'title' ilike %s or p.story->>'dek' ilike %s)")
        args.extend(["%" + q + "%"] * 2)
    where = " and ".join(clauses)
    # One repeatable-read snapshot (configured by the API) binds count/version/page.
    info = conn.execute(
        f"""select count(*) as total,
        coalesce(md5(string_agg(p.event_id::text||p.analysis_id::text||p.published_at::text,',' order by p.event_id)),'empty') as version
        {FROM} where {where}""",
        args,
    ).fetchone()
    rows = conn.execute(
        f"""select p.* {FROM} where {where}
        order by p.event_date desc,p.published_at desc,p.event_id limit %s offset %s""",
        [*args, limit, offset],
    ).fetchall()
    return rows, info


def read_analysis(conn, story_id, mode):
    public = publication(conn, story_id)
    if public is None:
        return None
    result = conn.execute(
        """select * from private.news_v2_analyses
        where event_id=%s and run_id=%s and mode=%s and review_status='approved'
        order by created_at desc,id desc limit 1""",
        (public["event_id"], public["run_id"], mode),
    ).fetchone()
    payload = (
        deepcopy(result["payload"]) if result and result["status"] == "ready" else None
    )
    if payload and mode == "sentiment":
        permissions = {
            str(r["article_id"]): r["rights"].get("display_full_text", False)
            for r in conn.execute(
                """
            select i.article_id,b.rights from private.news_v2_run_inputs i
            join private.news_v2_bodies b on b.id=i.body_id where i.run_id=%s""",
                (public["run_id"],),
            ).fetchall()
        }
        for row in payload["observations"]:
            if not permissions.get(row["article_id"]):
                row["evidence"] = "원문 인용문은 언론사 원문에서 확인해주세요."
    return AnalysisResponse(
        story_id=story_id,
        mode=mode,
        status=result["status"] if result else "pending",
        payload=payload,
        model_version=result["model_version"] if result else None,
        prompt_version=result["prompt_version"] if result else None,
        input_hash=conn.execute(
            "select input_hash from private.news_v2_runs where id=%s",
            (public["run_id"],),
        ).fetchone()["input_hash"],
        is_demo=public["story"]["is_demo"],
        notice="검토된 저장 결과를 표시합니다. 사실 여부·정치 성향을 판정하는 점수가 아닙니다."
        if result
        else "아직 검토·게시된 분석 결과가 없습니다. 요청 시 LLM을 새로 실행하지 않습니다.",
    )


def read_content(conn, story_id, article_id):
    public = publication(conn, story_id)
    article_key = uuid_or_none(article_id)
    if public is None or article_key is None:
        return None
    row = conn.execute(
        """select i.article_snapshot,b.text,b.rights from private.news_v2_members m
        join private.news_v2_run_inputs i on i.run_id=m.run_id and i.article_id=m.article_id
        join private.news_v2_bodies b on b.id=i.body_id
        where m.event_id=%s and m.run_id=%s and m.article_id=%s""",
        (public["event_id"], public["run_id"], article_key),
    ).fetchone()
    if row is None:
        return None
    allowed = row["rights"].get("display_full_text", False)
    return ArticleContent(
        article_id=article_id,
        status="available" if allowed else "link_only",
        text=row["text"] if allowed else None,
        source_url=row["article_snapshot"]["canonical_url"],
        notice="재표시가 허용된 본문입니다."
        if allowed
        else "본문 재표시 권한이 확인되지 않아 원문 링크로 제공합니다.",
    )
