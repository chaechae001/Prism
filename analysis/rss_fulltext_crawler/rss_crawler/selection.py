"""Metadata-only selection before article requests; never consults model outputs."""

from dataclasses import dataclass
from datetime import datetime, timezone

from .parsing import article_identity


def _utc(value):
    if not isinstance(value, str):
        raise ValueError('Publication bounds must be timezone-aware ISO timestamps')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError('Publication bounds must be timezone-aware ISO timestamps') from None


@dataclass(frozen=True)
class SelectionPolicy:
    published_after: str
    published_before: str
    excluded_article_ids: frozenset[str] = frozenset()
    excluded_publisher_ids: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self):
        after, before = _utc(self.published_after), _utc(self.published_before)
        if after >= before:
            raise ValueError('Publication selection needs after < before')
        for values in (self.excluded_article_ids, self.excluded_publisher_ids):
            if not isinstance(values, (frozenset, set, tuple, list)):
                raise ValueError('Exclusions must be explicit collections')
        if any(not isinstance(value, str) or not value for value in self.excluded_article_ids):
            raise ValueError('Excluded article IDs must be nonempty strings')
        if any(not isinstance(value, tuple) or len(value) != 2 or any(not isinstance(part, str) or not part for part in value)
               for value in self.excluded_publisher_ids):
            raise ValueError('Excluded publisher IDs must be (publisher key, article ID) pairs')
        object.__setattr__(self, 'excluded_article_ids', frozenset(self.excluded_article_ids))
        object.__setattr__(self, 'excluded_publisher_ids', frozenset(self.excluded_publisher_ids))
        object.__setattr__(self, 'published_after', after.isoformat())
        object.__setattr__(self, 'published_before', before.isoformat())

    def reason(self, item):
        identity = article_identity(item.get('url') or '')
        if (item.get('issue') is not None or not item.get('article_id') or not item.get('title')
                or identity is None or identity[1] != item.get('publisher_article_id')):
            return 'invalid_rss_item'
        if item['article_id'] in self.excluded_article_ids:
            return 'development_article_id'
        if identity in self.excluded_publisher_ids:
            return 'development_publisher_id'
        try:
            published = _utc(item.get('published_at'))
        except ValueError:
            return 'missing_or_invalid_publication'
        if published <= _utc(self.published_after):
            return 'not_after_development'
        if published > _utc(self.published_before):
            return 'after_collection_cutoff'
        return None

    def to_dict(self):
        return {'version': 'temporal-article-selection/v1', 'published_after_exclusive': self.published_after,
                'published_before_inclusive': self.published_before,
                'excluded_article_ids': sorted(self.excluded_article_ids),
                'excluded_publisher_ids': [list(value) for value in sorted(self.excluded_publisher_ids)]}
