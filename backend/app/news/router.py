from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import (
    CategoriesResponse,
    CategoryInfo,
    FeedItem,
    Reason,
    Story,
    Category,
    FeedbackRequest,
    FeedbackResponse,
)
from ..recommendation import cursor_key, decode_cursor, encode_cursor
from .models import (
    AnalysisMode,
    AnalysisResponse,
    ArticleContent,
    NewsFeedMeta,
    NewsFeedResponse,
    NewsStoryResponse,
)
from .reader import (
    FROM,
    VALID,
    list_publications,
    publication,
    read_analysis,
    read_content,
)
from .storage import connect

router = APIRouter(prefix="/api/v2")


@router.get("/stories", response_model=NewsFeedResponse)
def feed(
    request: Request,
    q: str = Query(default="", max_length=100),
    category: Category | None = None,
    day: date | None = Query(default=None, alias="date"),
    from_day: date | None = Query(default=None, alias="from"),
    to_day: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=6, ge=1, le=20),
    cursor: str | None = Query(default=None, max_length=1000),
):
    if (day and (from_day or to_day)) or (from_day and to_day and from_day > to_day):
        raise HTTPException(
            422, "날짜 또는 기간 중 한 가지 조건을 올바르게 선택해주세요."
        )
    with connect() as conn:
        conn.execute("set transaction isolation level repeatable read, read only")
        _, info = list_publications(
            conn,
            q=q.strip(),
            category=category,
            day=day,
            from_day=from_day,
            to_day=to_day,
            limit=1,
        )
        key = cursor_key(
            info["version"],
            f"{q.strip()}|{day}|{from_day}|{to_day}",
            category,
            "latest",
            0,
        )
        try:
            offset = decode_cursor(cursor, key, info["total"]) if cursor else 0
        except ValueError:
            raise HTTPException(
                422, "조회 조건이나 데이터가 바뀌었습니다. 목록을 새로 불러주세요."
            ) from None
        rows, _ = list_publications(
            conn,
            q=q.strip(),
            category=category,
            day=day,
            from_day=from_day,
            to_day=to_day,
            limit=limit,
            offset=offset,
        )
    items = [
        FeedItem(
            story=Story.model_validate(r["story"]),
            reason=Reason(code="latest", label="검토된 사건 · 날짜순"),
        )
        for r in rows
    ]
    return NewsFeedResponse(
        items=items,
        total=info["total"],
        next_cursor=encode_cursor(key, offset + limit)
        if offset + limit < info["total"]
        else None,
        meta=NewsFeedMeta(
            request_id=request.state.request_id,
            generated_at=datetime.now(timezone.utc),
            dataset_version=info["version"],
            is_mock=bool(items) and all(i.story.is_demo for i in items),
            mode="latest",
            diversity=0,
            policy_version="news-v2",
            policy_notes=[
                "날짜는 사건에 포함된 기사들의 최초 시각을 한국 시간으로 환산한 날짜입니다.",
                "언론사 발행시각이 없으면 네이버 제공시각을 사용합니다. 수집시각으로 대체하지 않습니다.",
                "현재 v2 피드는 최신순입니다. 다양성 정렬·편향 점수는 평가 후 별도로 연결합니다.",
            ],
            returned_categories=list(dict.fromkeys(i.story.category for i in items)),
            source_cap_relaxed=False,
            event_dates={str(r["event_id"]): r["event_date"] for r in rows},
        ),
    )


@router.get("/categories", response_model=CategoriesResponse)
def categories():
    with connect() as conn:
        rows = conn.execute(
            f"select p.category,count(*) as count {FROM} where {VALID} group by p.category"
        ).fetchall()
    counts = {r["category"]: r["count"] for r in rows}
    return CategoriesResponse(
        items=[
            CategoryInfo(id=k, label=v, count=counts.get(k, 0))
            for k, v in {
                "politics": "정치",
                "economy": "경제",
                "society": "사회",
                "technology": "기술",
            }.items()
        ]
    )


@router.get("/stories/{story_id}", response_model=NewsStoryResponse)
def detail(story_id: str, request: Request):
    with connect() as conn:
        row = publication(conn, story_id)
    if row is None:
        raise HTTPException(404, "게시 가능한 사건이 없습니다.")
    return NewsStoryResponse(
        story=row["story"],
        request_id=request.state.request_id,
        is_mock=row["story"]["is_demo"],
        event_date=row["event_date"],
    )


@router.get("/stories/{story_id}/analyses/{mode}", response_model=AnalysisResponse)
def analysis(story_id: str, mode: AnalysisMode):
    with connect() as conn:
        row = read_analysis(conn, story_id, mode)
    if row is None:
        raise HTTPException(404, "게시 가능한 사건이 없습니다.")
    return row


@router.get(
    "/stories/{story_id}/articles/{article_id}/content", response_model=ArticleContent
)
def content(story_id: str, article_id: str):
    with connect() as conn:
        row = read_content(conn, story_id, article_id)
    if row is None:
        raise HTTPException(404, "사건에 포함된 기사가 없습니다.")
    return row


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
def feedback(body: FeedbackRequest, request: Request):
    with connect() as conn:
        row = publication(conn, body.story_id)
    if row is None:
        raise HTTPException(404, "게시 가능한 사건이 없습니다.")
    return FeedbackResponse(
        id=str(uuid4()), request_id=request.state.request_id, persisted=False
    )
