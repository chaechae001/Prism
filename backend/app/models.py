"""The API source of truth. Export OpenAPI; generate TS instead of hand-copying DTOs."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, HttpUrl

Category = Literal['politics', 'economy', 'society', 'technology']
Mode = Literal['balanced', 'latest', 'explore']

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Citation(Model):
    text: str
    article_ids: list[str]

class Article(Model):
    id: str
    publisher_id: str
    publisher_name: str
    title: str
    url: HttpUrl
    published_at: AwareDatetime
    framing: str
    is_demo: bool = True

class Perspective(Model):
    label: str
    text: str
    article_ids: list[str]

class Coverage(Model):
    publisher_count: int = Field(ge=1)
    article_count: int = Field(ge=1)
    perspective_count: int = Field(ge=0)
    label_status: Literal['demo', 'reviewed', 'unverified']

class Summary(Model):
    status: Literal['ready', 'pending', 'insufficient_sources', 'failed']
    bullets: list[Citation]
    unknowns: list[str]
    model_version: str | None = None
    prompt_version: str | None = None

class Story(Model):
    id: str
    title: str
    category: Category
    dek: str
    updated_at: AwareDatetime
    keywords: list[str]
    visual: Literal['city', 'chip', 'energy', 'school', 'market', 'assembly', 'work', 'research']
    coverage: Coverage
    summary: Summary
    perspectives: list[Perspective]
    articles: list[Article]
    public_interest: float = Field(ge=0, le=1)
    is_demo: bool = True

class Reason(Model):
    code: Literal['public_interest', 'source_diversity', 'discovery', 'latest']
    label: str

class FeedItem(Model):
    story: Story
    reason: Reason

class FeedMeta(Model):
    request_id: str
    generated_at: AwareDatetime
    dataset_version: str
    is_mock: bool = True
    mode: Mode
    diversity: int = Field(ge=0, le=100)
    policy_version: str = 'mock-v1'
    policy_notes: list[str]
    returned_categories: list[Category]
    source_cap_relaxed: bool

class FeedResponse(Model):
    items: list[FeedItem]
    total: int = Field(ge=0)
    next_cursor: str | None
    meta: FeedMeta

class StoryResponse(Model):
    story: Story
    request_id: str
    is_mock: bool = True

class CategoryInfo(Model):
    id: Category
    label: str
    count: int

class CategoriesResponse(Model):
    items: list[CategoryInfo]

class ErrorBody(Model):
    code: str
    message: str
    details: list[dict] = Field(default_factory=list)
    request_id: str

class ErrorResponse(Model):
    error: ErrorBody

class FeedbackRequest(Model):
    story_id: str
    kind: Literal['useful', 'more_perspectives', 'report_error']
    comment: str | None = Field(default=None, max_length=500)

class FeedbackResponse(Model):
    id: str
    status: Literal['accepted'] = 'accepted'
    persisted: bool = False
    request_id: str

class JobRequest(Model):
    stage: Literal['collect', 'cluster', 'summarize']
    dry_run: Literal[True] = True

class Job(Model):
    id: str
    stage: Literal['collect', 'cluster', 'summarize']
    status: Literal['queued', 'running', 'succeeded', 'failed']
    dry_run: Literal[True] = True
    note: str

class Health(Model):
    status: Literal['ok'] = 'ok'
    mode: Literal['mock'] = 'mock'
    dataset_version: str

# Analyst -> worker boundary. Raw text belongs in private storage, never in feed DTOs.
class ArticleInput(Model):
    id: str
    canonical_url: HttpUrl
    publisher_id: str
    publisher_group_id: str
    title: str
    text: str = Field(min_length=1)
    published_at: AwareDatetime
    collected_at: AwareDatetime
    category: Category
    content_hash: str
    license_status: Literal['allowed', 'unknown', 'denied']
    allowed_uses: list[Literal['collect', 'store', 'summarize', 'publish_summary']]

class AnalystBatch(Model):
    schema_version: Literal['1.0']
    batch_id: str
    articles: Annotated[list[ArticleInput], Field(min_length=1)]

class SummaryOutput(Model):
    title: str
    bullets: Annotated[list[Citation], Field(min_length=1, max_length=5)]
    perspectives: list[Perspective]
    unknowns: list[str]
