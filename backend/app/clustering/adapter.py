"""PRISM input contracts -> unchanged local news bot -> private review artifacts."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from news_clustering.bot import prepare_articles, run_bot

from ..models import AnalystBatch
from ..services.analyst_validation import check_batch


ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / '.models/multilingual-e5-small'
CACHE_PATH = ROOT / 'data/private/clustering/e5.sqlite3'
PROFILES = ('v2', 'multiview', 'multiview-dev', 'multiview-group', 'multiview-anchor')
REQUIRED_USES = {'collect', 'store', 'summarize', 'publish_summary'}


def _analyst_rows(raw):
    # Dump first so nested, caller-mutated Pydantic instances are revalidated.
    value = raw.model_dump(mode='json') if isinstance(raw, AnalystBatch) else deepcopy(raw)
    checked = check_batch(value)
    if not checked.report['valid'] or checked.batch is None:
        raise ValueError('Article batch failed the shared analyst input checks')
    batch = checked.batch
    ids, urls, rows = set(), set(), []
    for article in batch.articles:
        if any(not value.strip() or '\0' in value for value in (
                article.id, article.title, article.publisher_id, article.publisher_group_id)):
            raise ValueError('Article identity, title and source must be nonempty')
        if not article.text.strip():
            raise ValueError('The team input must contain a usable article body')
        if article.id in ids or str(article.canonical_url) in urls:
            raise ValueError('Duplicate article ID or canonical URL')
        parsed = urlsplit(str(article.canonical_url))
        if parsed.username is not None or parsed.password is not None:
            raise ValueError('Article URL cannot contain credentials')
        if article.license_status != 'allowed' or not REQUIRED_USES <= set(article.allowed_uses):
            raise ValueError('The team input must declare all required uses')
        if article.content_hash != sha256(article.text.encode('utf-8')).hexdigest():
            raise ValueError('content_hash must match the exact provided UTF-8 body')
        ids.add(article.id)
        urls.add(str(article.canonical_url))
        metadata = article.model_dump(mode='json', exclude={'text', 'title'})
        rows.append(dict(article_id=article.id, title=article.title, body=article.text,
            category=article.category, published_at=article.published_at.isoformat(),
            publisher=article.publisher_id, url=str(article.canonical_url),
            source_id=article.publisher_group_id, body_kind='provided_body',
            source_notice='PRISM analyst-provided body; no DB identity remapping',
            analyst_metadata=metadata))
    return rows, batch.batch_id


def run_batch(raw, output_dir, *, input_format='analyst', profile='v2',
              encoder=None, cache_path=CACHE_PATH, model_dir=MODEL_DIR, provenance=None):
    """Write one fresh, atomic local run; never import DB or summary providers.

    Analyst input uses the team's exact-body hash and declared rights. Collector
    input is explicitly local analysis: source rights remain unchanged/unknown.
    Neither result is a storage envelope or publication approval.
    """
    if profile not in PROFILES or input_format not in ('analyst', 'collector'):
        raise ValueError('Unsupported local profile or input format')
    requested = Path(output_dir)
    if requested.exists() or requested.is_symlink():
        raise FileExistsError('Output already exists; use a fresh directory')
    target = requested.resolve()
    if not target.parent.is_dir():
        raise ValueError('Output parent must already exist')
    cache = Path(cache_path).resolve()
    if cache.is_relative_to(target):
        raise ValueError('The mutable cache must be outside the output directory')
    rows, batch_id = _analyst_rows(raw) if input_format == 'analyst' else (deepcopy(raw), None)
    articles, _, _ = prepare_articles(rows)
    if profile != 'v2' and len(articles) > 500:
        raise ValueError('Experimental multiview profiles accept at most 500 eligible articles')
    context = {**(provenance or {}), 'mode': 'prism_local_batch',
               'input_format': input_format, 'batch_id': batch_id}
    # Only a freshly owned staging directory is cleaned if preparation fails.
    with TemporaryDirectory(prefix='.prism-clustering-', dir=target.parent) as directory:
        staging = Path(directory).resolve()
        if staging.parent != target.parent:
            raise ValueError('Unexpected staging location')
        result_path = staging / 'result'
        result = run_bot(rows, result_path, encoder=encoder, profile=profile,
                         cache_path=cache, model_dir=model_dir, provenance=context)
        handoff = dict(schema_version='prism-local-clustering/v1', batch_id=batch_id,
            input_format=input_format, profile=profile,
            team_rights_validated=input_format == 'analyst', ready_for_publication=False,
            rights_validation_is_permission_verification=False,
            article_count=result['article_count'], group_count=result['group_count'],
            shared_database_writes=0, llm_calls=0, automatic_publication=False,
            accuracy_measured=False, requires_human_review=True,
            note='Local representative candidates. No public Story IDs, DB updates or summaries.')
        (result_path/'handoff.json').write_text(
            json.dumps(handoff, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if target.exists() or target.is_symlink():
            raise FileExistsError('Output was created concurrently')
        # On Windows rename refuses an existing destination; nothing is replaced.
        os.rename(result_path, target)
    return result


class NewsClusterer:
    """Implements pipeline.Clusterer.cluster with original article IDs.

    This synchronous offline adapter belongs in a batch worker, not HTTP reads.
    Use run_batch when representative metadata and review artifacts are needed.
    """

    def __init__(self, *, profile='v2', encoder=None, cache_path=CACHE_PATH, model_dir=MODEL_DIR):
        self.options = dict(profile=profile, encoder=encoder, cache_path=cache_path, model_dir=model_dir)

    def cluster(self, articles):
        if not articles:
            return []
        raw = dict(schema_version='1.0', batch_id='protocol-local',
                   articles=[article.model_dump(mode='json') for article in articles])
        with TemporaryDirectory(prefix='prism-clusterer-') as directory:
            result = run_batch(raw, Path(directory)/'run', **self.options)
        return [group['article_ids'] for group in result['groups']]
