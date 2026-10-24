"""Local RSS/body collection -> existing v2 clustering -> one article per group.

Run from the workspace root: python -m news_clustering.bot --source sbs
No hosted database, LLM calls, automatic publishing, or model downloads.
"""

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

import numpy as np
from threadpoolctl import threadpool_limits

from news_clustering.bot_report import render_report
from news_clustering.core.embedding_cache import CachedNewsE5Encoder
from news_clustering.core.embeddings import RecordingEncoder
from news_clustering.core.pipeline import ClusterConfig, cluster_articles
from news_clustering.models import Article
from news_clustering.multiview import cluster_multiview, multiview_settings
from rss_fulltext_crawler.rss_crawler.parsing import SOURCES, canonical_url, source_for_url
from rss_fulltext_crawler.rss_crawler.runner import collect


WORKSPACE = Path(__file__).resolve().parents[1]
MODEL_DIR = WORKSPACE / '.models/multilingual-e5-small'
CACHE_PATH = WORKSPACE / 'data/cache/news-bot-e5.sqlite3'
FULL_BODY_KINDS = {'publisher_html', 'provided_body', 'rss_content'}


class _ViewRecorder(RecordingEncoder):
    """Freeze each view's diagnostics before the shared encoder is reused."""
    def __init__(self, encoder):
        super().__init__(encoder)
        self._diagnostics = {}

    def encode(self, texts):
        values = super().encode(texts)
        self._diagnostics = deepcopy(getattr(self.encoder, 'last_diagnostics', {}))
        return values

    @property
    def last_diagnostics(self):
        return self._diagnostics


def _rows(raw):
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get('articles', raw.get('results'))
    else:
        rows = None
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError('Expected an article array or {articles/results: [...]} with at most 2000 records')
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('Every article record must be an object')
    # Ensure metadata can be preserved exactly as JSON; reject NaN and objects.
    json.dumps(raw, ensure_ascii=False, allow_nan=False)
    return rows


def prepare_articles(raw):
    """Preserve source metadata; never substitute RSS descriptions for a body."""
    articles, metadata, skipped = [], {}, []
    seen = set()
    for row in _rows(raw):
        identity = row.get('article_id')
        reason = None
        if row.get('status', 'ok') != 'ok':
            reason = 'collection_status:' + str(row['status'])
        elif not isinstance(row.get('body'), str) or not row['body'].strip():
            reason = 'missing_body'
        elif row.get('body_kind', 'provided_body') not in FULL_BODY_KINDS:
            reason = 'unsupported_body_kind'
        if reason:
            skipped.append({'article_id': identity, 'url': row.get('url', ''), 'reason': reason})
            continue
        # Malformed RSS items can lack an ID; they belong in skipped.json.
        # Only articles eligible for analysis require a unique usable ID.
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError('Every eligible article needs a nonempty article_id')
        if identity in seen:
            raise ValueError('Duplicate article_id values in the input')
        seen.add(identity)
        values = {key: row.get(key, '') for key in ('publisher', 'url', 'source_id', 'source_notice')}
        values.update(article_id=identity, title=row.get('title'), body=row['body'],
                      category=row.get('category', 'unknown'), published_at=row.get('published_at'),
                      body_kind=row.get('body_kind', 'provided_body'))
        if any(not isinstance(value, str) for key, value in values.items() if key != 'published_at'):
            raise ValueError('Article text and metadata fields must be strings')
        if values['published_at'] is not None and not isinstance(values['published_at'], str):
            raise ValueError('published_at must be text or null')
        article = Article.from_dict(values)
        if 'content_hash' in row and row['content_hash'] != article.content_hash:
            raise ValueError('Source content_hash differs from the title and body')
        articles.append(article)
        metadata[identity] = deepcopy(row)
    articles.sort(key=lambda article: article.article_id)
    return articles, metadata, skipped


def _representatives(articles, metadata, result, vectors):
    by_id = {article.article_id: article for article in articles}
    indices = {article.article_id: index for index, article in enumerate(articles)}
    if articles:
        values = np.asarray(vectors, dtype=np.float32)
        values = values / np.linalg.norm(values, axis=1, keepdims=True)
        similarity = np.clip(values @ values.T, -1, 1)
    groups = []
    for group in result['groups'] if result is not None else []:
        identity = group['representative_article_id']
        article = by_id[identity]
        members = [indices[key] for key in group['article_ids']]
        score = float(similarity[indices[identity], members].mean()) if len(members) > 1 else None
        groups.append({
            'group_id': group['group_id'], 'category': group['category'],
            'article_count': group['article_count'], 'publisher_count': group['publisher_count'],
            'article_ids': list(group['article_ids']), 'same_event_confirmed': False,
            'representative_mean_cosine': round(score, 6) if score is not None else None,
            'representative': {**article.to_dict(),
                'metadata': {key: value for key, value in metadata[identity].items()
                             if key not in {'body', 'title'}}},
            'related_articles': [{key: by_id[other].to_dict()[key] for key in (
                'article_id', 'title', 'url', 'publisher', 'published_at', 'body_kind')}
                for other in group['article_ids'] if other != identity],
        })
    return groups


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def run_bot(raw, output, *, encoder=None, cache_path=CACHE_PATH, model_dir=MODEL_DIR, provenance=None, profile='v2'):
    """Run a saved collector/Article batch locally and return the export document."""
    output = Path(output).resolve()
    if profile not in {'v2', 'multiview', 'multiview-dev', 'multiview-group', 'multiview-anchor'}:
        raise ValueError('Expected a supported local clustering profile')
    if output.exists():
        raise FileExistsError('Output already exists; choose a new directory')
    articles, metadata, skipped = prepare_articles(raw)
    cache_path = Path(cache_path).resolve()
    if cache_path.is_relative_to(output):
        raise ValueError('The mutable embedding cache must be outside the result directory')
    if articles and encoder is None:
        encoder = CachedNewsE5Encoder(cache_path, model_dir=model_dir)
    # No model construction is needed when all article bodies were skipped.
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    try:
        _write(output / 'input.json', raw)
        _write(output / 'articles.json', {'articles': [article.to_dict() for article in articles]})
        _write(output / 'skipped.json', skipped)
        result, vectors = None, None
        if articles:
            recorded = _ViewRecorder(encoder)
            config = ClusterConfig(min_similarity=.94, min_title_similarity=.025)
            with threadpool_limits(limits=4):
                if profile != 'v2':
                    lead_recorded = _ViewRecorder(encoder)
                    result = cluster_multiview(articles, config, encoder=recorded, lead_encoder=lead_recorded,
                                              settings=multiview_settings(profile),
                                              neighbor_scope='seed_group' if profile in {'multiview-group', 'multiview-anchor'} else 'article',
                                              anchor_rescue=profile == 'multiview-anchor')
                    lead_recorded.save(output / 'lead-vectors.npz')
                else:
                    result = cluster_articles(articles, config, encoder=recorded)
            vectors = recorded.vectors
            recorded.save(output / 'vectors.npz')
            _write(output / 'clustering.json', result)
        groups = _representatives(articles, metadata, result, vectors)
        exported = {
            'schema_version': 'local-news-representatives/v1',
            'status': 'completed' if articles else 'no_eligible_articles',
            'article_count': len(articles), 'group_count': len(groups), 'skipped_count': len(skipped),
            'selection_method': 'core-v2-maximum-mean-group-cosine-including-self',
            'selection_note': 'Existing core representative; ties follow sorted article IDs. Singleton scores are null.',
            'representative_score_is_quality_probability': False,
            'accuracy_measured': False, 'automatic_publication': False,
            'shared_database_writes': 0, 'llm_calls': 0, 'groups': groups,
        }
        if profile != 'v2':
            detail = result['diagnostics']['multiview'] if result is not None else {}
            exported.update(profile=profile, selection_method='maximum-mean-full-view-cosine-in-final-group',
                selection_note='Maximum mean full-view cosine within the final group; sorted-ID ties.',
                multiview={key: detail.get(key, 0) for key in (
                    'added_pair_count', 'removed_pair_count', 'baseline_view_disagreement_count')})
            exported['multiview']['development_tuned'] = profile in {'multiview-dev', 'multiview-group', 'multiview-anchor'}
            if profile in {'multiview-group', 'multiview-anchor'}:
                exported['multiview']['neighbor_scope'] = 'seed_group'
            if profile == 'multiview-anchor':
                shared = detail.get('shared_summary_audit', {})
                anchor = detail.get('anchor_rescue', {})
                exported['quality_audit'] = {
                    'shared_summary_cluster_count': len(shared.get('clusters', [])),
                    'article_ids_requiring_review': shared.get('article_ids_requiring_review', []),
                    'shared_summary_is_error_label': False,
                    'grouped_anchor_pair_count': anchor.get('grouped_relaxed_pair_count', 0),
                    'source_anchor_rules_are_human_gold': False}
                native_groups = {group['group_id']: group for group in result['groups']} if result else {}
                for group in groups:
                    native = native_groups[group['group_id']]
                    group['quality_review_required'] = native['quality_review_required']
                    group['quality_review_reasons'] = native['quality_review_reasons']
        _write(output / 'representatives.json', exported)
        (output / 'report.html').write_text(render_report(exported), encoding='utf-8')
        _write(output / 'run.json', {
            'schema_version': 'local-news-bot-run/v1', 'status': exported['status'], 'profile': profile,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'input_sha256': (provenance or {}).get('input_sha256'),
            'snapshot_sha256': sha256((output / 'input.json').read_bytes()).hexdigest(),
            'provenance': provenance or {'mode': 'provided_batch'},
            'article_count': len(articles), 'group_count': len(groups), 'skipped_count': len(skipped),
            'elapsed_seconds': perf_counter() - started,
            'algorithm_version': result['algorithm_version'] if result is not None else None,
            'model_id': result['model_id'] if result is not None else None,
            'embedding_diagnostics': result['diagnostics']['embedding'] if result is not None else None,
            'shared_database_writes': 0, 'llm_calls': 0, 'automatic_publication': False,
        })
        return exported
    except Exception as exc:
        # Preserve the newly created run's evidence; never leave it marked complete.
        if not (output / 'run.json').exists():
            _write(output / 'run.json', {'schema_version': 'local-news-bot-run/v1', 'status': 'failed',
                                        'error_type': type(exc).__name__})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local RSS/body -> v2 clusters -> representative articles. No Supabase or LLM.')
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--input', type=Path, help='Existing collector articles.json/results.json or an Article array')
    inputs.add_argument('--source', choices=('sbs', 'khan', 'mk', 'all'), help='Collect supported publisher RSS; default sbs')
    inputs.add_argument('--feed', action='append', help='Supported publisher RSS URL; repeat for multiple feeds')
    parser.add_argument('--limit', type=int, default=20, help='Article request limit per feed, 1-100 (default 20)')
    parser.add_argument('--output', type=Path, help='New result folder; default data/news-bot/<unique run>')
    parser.add_argument('--cache', type=Path, default=CACHE_PATH, help='Local vector cache, outside result folder')
    parser.add_argument('--model-dir', type=Path, default=MODEL_DIR, help='Existing local E5 files; never auto-download')
    parser.add_argument('--profile', choices=('v2', 'multiview', 'multiview-dev', 'multiview-group', 'multiview-anchor'), default='v2',
                        help='v2 default; optional full/lead, seed-group, and source-anchor comparisons')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error('--limit must be between 1 and 100')
    output = args.output or WORKSPACE / 'data/news-bot' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid4().hex[:8])
    if output.exists():
        parser.error('Output already exists; choose a new directory')
    if args.cache.resolve().is_relative_to(output.resolve()):
        parser.error('The mutable embedding cache must be outside the result directory')
    if args.input and args.cache.resolve() == args.input.resolve():
        parser.error('The input file cannot be used as the embedding cache')
    try:
        encoder = None
        if args.input:
            source = args.input.read_bytes()
            raw = json.loads(source.decode('utf-8-sig'))
            provenance = {'mode': 'saved_json', 'input_path': str(args.input.resolve()),
                          'input_sha256': sha256(source).hexdigest()}
        else:
            sources = []
            if args.feed:
                for url in args.feed:
                    source = source_for_url(url)
                    if source is None:
                        raise ValueError('RSS URL must be on a supported SBS, Khan or MK host')
                    category = source.category if canonical_url(url) == canonical_url(source.feed_url) else 'unknown'
                    sources.append(replace(source, feed_url=url, category=category))
            else:
                sources = list(SOURCES.values()) if args.source == 'all' else [SOURCES[args.source or 'sbs']]
            # Check existing model files before making any article HTTP requests.
            encoder = CachedNewsE5Encoder(args.cache, model_dir=args.model_dir)
            raw = collect(sources, limit=args.limit, min_chars=200,
                          progress=lambda message: print(message, file=sys.stderr, flush=True))
            provenance = {'mode': 'live_rss', 'rss_urls': [source.feed_url for source in sources],
                          'collection_summary': raw['summary']}
        result = run_bot(raw, output, encoder=encoder, cache_path=args.cache, model_dir=args.model_dir,
                         provenance=provenance, profile=args.profile)
        print(json.dumps({'output': str(output.resolve()), 'articles': result['article_count'],
                          'groups': result['group_count'], 'skipped': result['skipped_count'],
                          'status': result['status']}, ensure_ascii=False))
        return 0 if result['article_count'] else 1
    except KeyboardInterrupt:
        print('Local bot interrupted; no shared database or LLM calls.', file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Local bot failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
