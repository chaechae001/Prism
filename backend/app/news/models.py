from datetime import date
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from ..models import (
    Model,
    Category,
    Citation,
    Perspective,
    FeedMeta,
    FeedResponse,
    StoryResponse,
)

AnalysisMode = Literal["summary", "five_w", "easy", "sentiment"]
MODES = {
    "summary": "핵심 요약",
    "five_w": "팩트 5W",
    "easy": "쉽게 읽기",
    "sentiment": "보도 어조",
}


def digest(value) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class Publisher(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    domains: list[str] = Field(min_length=1)


class NewsRecord(Model):
    schema_version: Literal["2.0"] = "2.0"
    id: UUID
    provider: Literal["naver_search", "rss", "demo"]
    provider_url: HttpUrl
    original_url: HttpUrl
    canonical_url: HttpUrl
    title: str = Field(min_length=1)
    snippet: str
    publisher: Publisher | None
    category: Category
    category_basis: Literal["collection_query", "reviewed"] = "collection_query"
    provider_published_at: AwareDatetime | None
    publisher_published_at: AwareDatetime | None = None
    collected_at: AwareDatetime
    is_demo: bool = False


class BodyRights(Model):
    store: bool = False
    cluster: bool = False
    summarize: bool = False
    analyze: bool = False
    publish_summary: bool = False
    display_full_text: bool = False
    evidence: str = Field(min_length=1, max_length=2000)


class BodyImport(Model):
    article_id: UUID
    content_kind: Literal["full_text", "excerpt"]
    text: str = Field(min_length=1, max_length=2_000_000)
    source_kind: Literal[
        "licensed_api", "provided_file", "permitted_extraction", "demo"
    ]
    source_url: HttpUrl
    acquired_at: AwareDatetime
    publisher_published_at: AwareDatetime | None = None
    extractor_version: str = Field(min_length=1)
    rights: BodyRights


class BodyBatch(Model):
    schema_version: Literal["2.0"] = "2.0"
    items: list[BodyImport] = Field(min_length=1, max_length=1000)


class AnalysisArticle(Model):
    article: NewsRecord
    body_version_id: UUID
    content_hash: str
    text: str
    text_basis: Literal["full_text", "excerpt"]
    rights: BodyRights


class AnalysisBatch(Model):
    schema_version: Literal["2.0"] = "2.0"
    run_id: UUID
    input_hash: str
    articles: list[AnalysisArticle]
    excluded: dict[str, int]
    selection: dict[str, int | bool] = Field(default_factory=dict)


class SummaryPayload(Model):
    title: str = Field(min_length=1)
    bullets: list[Citation] = Field(min_length=1, max_length=5)
    perspectives: list[Perspective] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class FiveWPayload(Model):
    who: Citation | None
    what: Citation | None
    when: Citation | None
    where: Citation | None
    why: Citation | None
    unknowns: list[str] = Field(default_factory=list)


class EasyPayload(Model):
    paragraphs: list[Citation] = Field(min_length=1, max_length=8)
    glossary: list[Citation] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class SentimentObservation(Model):
    article_id: UUID
    label: Literal["positive", "negative", "neutral", "mixed"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str = Field(min_length=1)


class SentimentPayload(Model):
    scope: Literal["article_language"]
    observations: list[SentimentObservation] = Field(min_length=1)
    note: str = (
        "기사의 표현상 어조이며 사실 여부·정치 성향·독자의 감정을 뜻하지 않습니다."
    )


PAYLOADS = {
    "summary": SummaryPayload,
    "five_w": FiveWPayload,
    "easy": EasyPayload,
    "sentiment": SentimentPayload,
}


class AnalysisOutput(Model):
    mode: AnalysisMode
    status: Literal["ready", "failed", "insufficient_sources"]
    model_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    payload: dict | None

    @model_validator(mode="after")
    def check_payload(self):
        if self.status == "ready":
            self.payload = (
                PAYLOADS[self.mode].model_validate(self.payload).model_dump(mode="json")
            )
        elif self.payload is not None:
            raise ValueError("Non-ready result must have null payload")
        return self


class ClusterOutput(Model):
    event_key: str = Field(min_length=1)
    article_ids: list[UUID] = Field(min_length=1)
    same_event_verified: bool = False
    category: Category | None = None
    outputs: list[AnalysisOutput] = Field(default_factory=list)


class ResultBatch(Model):
    schema_version: Literal["2.0"] = "2.0"
    run_id: UUID
    input_hash: str
    cluster_model_version: str = Field(min_length=1)
    clusters: list[ClusterOutput] = Field(min_length=1)


class AnalysisResponse(Model):
    schema_version: Literal["2.0"] = "2.0"
    story_id: str
    mode: AnalysisMode
    status: Literal["pending", "ready", "failed", "insufficient_sources", "stale"]
    payload: dict | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    input_hash: str | None = None
    is_demo: bool
    notice: str


class ArticleContent(Model):
    article_id: str
    status: Literal["available", "link_only", "stale"]
    text: str | None = None
    source_url: HttpUrl
    notice: str


class NewsFeedMeta(FeedMeta):
    event_dates: dict[str, date]
    date_basis: Literal["earliest_article_time_kst"] = "earliest_article_time_kst"
    server_date_filter: Literal[True] = True


class NewsFeedResponse(FeedResponse):
    meta: NewsFeedMeta


class NewsStoryResponse(StoryResponse):
    event_date: date
    date_basis: Literal["earliest_article_time_kst"] = "earliest_article_time_kst"
