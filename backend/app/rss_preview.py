"""RSS display adapter. This does not collect RSS or cluster articles."""
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StrictBool

from .models import Category, Story


class Rights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collect: Literal["allowed", "unknown", "denied"]
    store: Literal["allowed", "unknown", "denied"]
    summarize: Literal["allowed", "unknown", "denied"]
    publish_summary: Literal["allowed", "unknown", "denied"]
    display_image: Literal["allowed", "unknown", "denied"]


class RssRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    id: str = Field(min_length=1)
    feed_id: str = Field(min_length=1)
    publisher_id: str = Field(min_length=1)
    publisher_name: str = Field(min_length=1)
    item_key: str = Field(min_length=1)
    source_item_id: str | None
    original_url: HttpUrl
    canonical_url: HttpUrl
    title: str = Field(min_length=1)
    category: Category
    author: str | None
    source_category: str | None
    rss_description: str | None
    published_at: AwareDatetime | None
    collected_at: AwareDatetime
    parse_status: Literal["parsed", "partial"]
    body_status: Literal["not_provided", "rss_excerpt", "content_available", "blocked"]
    rights: Rights
    is_demo: StrictBool


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("p", "br", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div", "li"):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = _Text()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def rss_to_story(record: RssRecord, now: datetime | None = None, *, article_id: str | None = None) -> tuple[Story | None, str | None]:
    """An explicit single-article preview. Never fabricate dates, summaries or viewpoints."""
    if record.published_at is None:
        return None, "missing_publication_date"
    if record.published_at > (now or datetime.now(timezone.utc)):
        return None, "future_publication_date"
    # Conservative publication gate; private reader access is not permission to publish.
    if any(value != "allowed" for value in (
        record.rights.collect, record.rights.store, record.rights.publish_summary,
    )):
        return None, "publication_not_confirmed"
    title = plain_text(record.title)
    if not title:
        return None, "empty_title"
    key = sha256(str(record.canonical_url).encode()).hexdigest()[:24]
    description = plain_text(record.rss_description or "")
    visual = {"politics": "assembly", "economy": "market", "society": "city", "technology": "research"}
    return Story.model_validate({
        "id": f"rss-preview-{key}", "title": title, "category": record.category,
        "dek": f"RSS 제공 설명 · {description}" if description else "RSS 원문 미리보기 · 제공된 설명이 없습니다.",
        "updated_at": record.published_at, "keywords": [], "visual": visual[record.category],
        "coverage": {"publisher_count": 1, "article_count": 1, "perspective_count": 0, "label_status": "unverified"},
        "summary": {"status": "pending", "bullets": [], "unknowns": [
            "군집분석과 AI 요약 전의 원문 기사 1건입니다. 동일 사건의 여러 출처를 묶은 결과가 아닙니다.",
            "RSS 설명은 언론사 제공 문구이며 AI 요약이 아닙니다.",
        ], "model_version": None, "prompt_version": None},
        "perspectives": [], "articles": [{
            "id": article_id or f"rss-article-{key}", "publisher_id": record.publisher_id,
            "publisher_name": plain_text(record.publisher_name), "title": title,
            "url": str(record.canonical_url), "published_at": record.published_at,
            "framing": "원문 미리보기 · 쟁점 분류 전", "is_demo": record.is_demo,
        }], "public_interest": 0, "is_demo": record.is_demo,
    }), None
