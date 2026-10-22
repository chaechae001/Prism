"""Provider-independent boundaries for the future offline worker; no LLM calls here."""
from typing import Protocol
from .models import AnalystBatch, ArticleInput, SummaryOutput

REQUIRED_USES={'collect','store','summarize','publish_summary'}

class Clusterer(Protocol):
    def cluster(self, articles: list[ArticleInput]) -> list[list[str]]: ...

class Summarizer(Protocol):
    async def summarize(self, articles: list[ArticleInput]) -> SummaryOutput: ...

def allowed_articles(batch: AnalystBatch) -> list[ArticleInput]:
    """Fail closed for unknown rights. This checks declared rights, not their legal validity."""
    seen_ids,seen_urls,seen_hashes=set(),set(),set()
    allowed=[]
    for a in batch.articles:
        if a.id in seen_ids: raise ValueError(f'Duplicate article id: {a.id}')
        seen_ids.add(a.id)
        if a.license_status!='allowed' or not REQUIRED_USES.issubset(a.allowed_uses): continue
        if str(a.canonical_url) in seen_urls or a.content_hash in seen_hashes: continue
        seen_urls.add(str(a.canonical_url));seen_hashes.add(a.content_hash)
        allowed.append(a)
    return allowed

def validate_summary(summary: SummaryOutput, articles: list[ArticleInput]):
    ids={a.id for a in articles}
    if len({a.publisher_group_id for a in articles})<2:
        raise ValueError('At least two independent publisher groups required for publication')
    for claim in [*summary.bullets,*summary.perspectives]:
        if not claim.article_ids or not set(claim.article_ids)<=ids:
            raise ValueError('Every claim must cite articles from this event')
    # Citation existence alone cannot prove entailment or truth: human/automated review is still required.
    return summary
