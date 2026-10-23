from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class Article:
    article_id: str
    title: str
    body: str
    category: str
    published_at: str | None
    publisher: str = ""
    url: str = ""
    source_id: str = ""
    body_kind: str = "provided_body"
    source_notice: str = ""

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()

    @property
    def content_hash(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "content_hash": self.content_hash}

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "Article":
        fields = cls.__dataclass_fields__
        article = cls(**{k: v for k, v in item.items() if k in fields})
        if not article.article_id.strip() or not article.title.strip():
            raise ValueError("article_id and title must be non-empty")
        if not isinstance(article.body, str):
            raise ValueError("body must be a string")
        return article
