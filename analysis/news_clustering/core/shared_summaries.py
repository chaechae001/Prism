"""Review candidates for identical analysis bodies under divergent headlines.

Copied text can be a multi-topic broadcast synopsis or valid syndication. This
diagnostic neither judges event identity nor changes or deduplicates articles.
"""

from hashlib import sha256
import unicodedata

from news_clustering.core.analysis_text import prepare_article
from news_clustering.models import Article


def _normalized_headline(title: str) -> str:
    normalized = unicodedata.normalize('NFKC', title).casefold()
    without_punctuation = ''.join(
        character for character in normalized
        if not unicodedata.category(character).startswith('P')
    )
    return ' '.join(without_punctuation.split())


def audit_shared_summaries(articles: list[Article]) -> dict:
    """Flag exact, nonempty cleaned-body matches for human review only.

    SHA256 is an analysis identifier; the exact cleaned text is also part of the
    grouping key, so a hash alone can never establish shared content. Original
    titles and content hashes remain tied to every source article ID.
    """
    seen_ids = set()
    for original in articles:
        if original.article_id in seen_ids:
            raise ValueError(f'duplicate article_id: {original.article_id}')
        seen_ids.add(original.article_id)

    groups: dict[tuple[str, str], list[tuple[Article, str]]] = {}
    for original in articles:
        analysis = prepare_article(original).article
        if not analysis.body.strip():
            continue
        digest = sha256(analysis.body.encode('utf-8')).hexdigest()
        groups.setdefault((digest, analysis.body), []).append(
            (original, _normalized_headline(analysis.title))
        )

    clusters = []
    for (digest, body), members in sorted(groups.items()):
        if len({title for _, title in members}) < 2:
            continue
        originals = sorted(
            (original for original, _ in members),
            key=lambda original: (original.article_id, original.url, original.content_hash),
        )
        clusters.append({
            'analysis_body_sha256': digest,
            'analysis_body_characters': len(body),
            'article_ids': [original.article_id for original in originals],
            'article_count': len(originals),
            'titles': [
                {'article_id': original.article_id, 'title': original.title}
                for original in originals
            ],
            'source_content_hashes': {
                original.article_id: original.content_hash for original in originals
            },
            'reason': 'identical_cleaned_body_different_headlines',
            'requires_review': True,
            'human_verified': False,
        })

    return {
        'method': 'identical-cleaned-body-divergent-headlines/v1',
        'clusters': clusters,
        'article_ids_requiring_review': sorted({
            article_id for cluster in clusters for article_id in cluster['article_ids']
        }),
        'equality_is_same_event_proof': False,
        'human_verified': False,
    }
