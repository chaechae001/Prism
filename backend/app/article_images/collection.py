"""Explicit local image-URL enrichment and offline, input-bound manifest reads."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from .metadata import image_from_html, image_from_rss, safe_image_url

SCHEMA = 'local-news-images/v1'
ORIGINS = {'rss_media', 'og_image', 'twitter_image'}


def _source_metadata(articles, exported, input_bytes):
    by_id = {row['article_id']: row for row in articles}
    views = {identity: [] for identity in by_id}

    def attach(row, parent=None):
        if not isinstance(row, dict):
            raise ValueError('Source metadata must be an object')
        identity = row.get('article_id', row.get('id', parent))
        if identity not in by_id:
            if parent is not None:
                raise ValueError('Source metadata article ID differs')
            return
        if parent is not None and identity != parent:
            raise ValueError('Source metadata article ID differs')
        original = by_id[identity]
        url = row.get('url', row.get('canonical_url', original['url']))
        if url != original['url'] or row.get('content_hash', original['content_hash']) != original['content_hash']:
            raise ValueError('Source metadata does not match the normalized article')
        views[identity].append(row)
        if 'metadata' in row:
            attach(row['metadata'], identity)

    for row in articles:
        attach(row)
    if input_bytes is not None:
        if len(input_bytes) > 20_000_000:
            raise ValueError('Original input is too large')
        raw = json.loads(input_bytes.decode('utf-8-sig'))
        rows = raw if isinstance(raw, list) else raw.get('articles', raw.get('results')) if isinstance(raw, dict) else None
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError('Original input must contain article records')
        for row in rows:
            attach(row)
    for group in exported['groups']:
        attach(group['representative'])
        for row in group.get('related_articles', []):
            attach(row)
    return views


def _image_rights(views):
    values = []
    for row in views:
        for key in ('rights', 'rights_snapshot'):
            rights = row.get(key)
            if isinstance(rights, dict) and 'display_image' in rights:
                values.append(rights['display_image'])
    if 'denied' in values:
        return 'denied'
    return 'allowed' if values and all(value == 'allowed' for value in values) else 'unknown'


def collect_images(results_dir, *, client=None, limit=None, progress=None):
    # Imports with HTTP capabilities exist only in this explicitly invoked batch.
    from rss_fulltext_crawler.rss_crawler.extraction import extract_article
    from rss_fulltext_crawler.rss_crawler.network import CrawlClient, FetchError, decode_html
    from rss_fulltext_crawler.rss_crawler.parsing import article_identity, source_for_url
    from ..cluster_preview import load_cluster_preview

    folder = Path(results_dir).resolve()
    load_cluster_preview(folder)  # Require a valid original partition before enrichment.
    article_bytes = (folder/'articles.json').read_bytes()
    export_bytes = (folder/'representatives.json').read_bytes()
    articles = json.loads(article_bytes.decode('utf-8-sig'))['articles']
    input_bytes = (folder/'input.json').read_bytes() if (folder/'input.json').is_file() else None
    views = _source_metadata(articles, json.loads(export_bytes.decode('utf-8-sig')), input_bytes)
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 2000):
        raise ValueError('limit must be between 1 and 2000')
    selected = articles if limit is None else articles[:limit]
    results = []
    for article in selected:
        metadata = views[article['article_id']]
        declared = _image_rights(metadata)
        row = dict(article_id=article['article_id'], article_url=article['url'],
            content_hash=article['content_hash'], status='missing', image_url=None,
            origin=None, rights_status=declared, html_sha256=None)
        candidate = None
        if declared == 'denied':
            row['status'] = 'rights_denied'
        else:
            for source_row in metadata:
                candidate = image_from_rss(source_row.get('media'), article['url'])
                if candidate:
                    break
            if candidate is None:
                identity = article_identity(article['url'])
                source = source_for_url(article['url'])
                if identity is None or source is None:
                    row['status'] = 'unsupported_article_url'
                else:
                    try:
                        if client is None:
                            client = CrawlClient()
                        response = client.get(article['url'], 3_000_000, identity)
                        content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                        if content_type not in {'', 'text/html', 'application/xhtml+xml'}:
                            raise FetchError('unexpected_content_type')
                        html = decode_html(response)
                        row['html_sha256'] = sha256(response.body).hexdigest()
                        evidence = extract_article(html, source, identity[1], response.url, min_chars=1)
                        if evidence['identity']['page_article_id'] != identity[1]:
                            row['status'] = 'identity_mismatch'
                        else:
                            candidate = image_from_html(html, response.url)
                    except FetchError as exc:
                        row['status'] = exc.code
                    except (ValueError, RecursionError):
                        row['status'] = 'extraction_error'
            if candidate:
                row.update(status='found', image_url=candidate['url'], origin=candidate['origin'])
        results.append(row)
        if progress:
            progress(f"{row['article_id']}: {row['status']}")
    return dict(schema_version=SCHEMA, created_at=datetime.now(timezone.utc).isoformat(),
        articles_sha256=sha256(article_bytes).hexdigest(), representatives_sha256=sha256(export_bytes).hexdigest(),
        input_sha256=sha256(input_bytes).hexdigest() if input_bytes is not None else None,
        automatic_publication=False, local_preview=True, image_bytes_downloaded=0,
        summary=dict(selected_articles=len(results), images_found=sum(r['status']=='found' for r in results),
                     statuses=dict(Counter(r['status'] for r in results))), results=results)


def validate_destination(output, results_dir):
    output, folder = Path(output).resolve(), Path(results_dir).resolve()
    if output == folder or folder in output.parents:
        raise ValueError('Image metadata must be written outside the original result folder')
    if output.exists():
        raise FileExistsError('Use a fresh image manifest path')
    return output


def write_manifest(manifest, output, results_dir):
    output = validate_destination(output, results_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                dir=output.parent, prefix='.images-', suffix='.partial', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        os.link(temporary, output)  # Atomic create: never overwrite an existing manifest.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def images_from_manifest(raw, article_bytes, export_bytes, articles, input_bytes=None):
    def invalid():
        raise ValueError('Invalid or stale image metadata')
    def require(value):
        if not value:
            invalid()
    require(len(raw) <= 5_000_000)
    manifest = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda _: invalid())
    require(isinstance(manifest, dict) and manifest['schema_version'] == SCHEMA)
    require(manifest['local_preview'] is True and manifest['automatic_publication'] is False)
    require(manifest['articles_sha256'] == sha256(article_bytes).hexdigest())
    require(manifest['representatives_sha256'] == sha256(export_bytes).hexdigest())
    require(input_bytes is None or len(input_bytes) <= 20_000_000)
    require(manifest.get('input_sha256') == (sha256(input_bytes).hexdigest() if input_bytes is not None else None))
    rows = manifest['results']
    require(isinstance(rows, list) and len(rows) <= len(articles))
    by_id = {a['article_id']: a for a in articles}
    seen, images = set(), {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row['article_id'], str))
        identity = row['article_id']
        require(identity in by_id and identity not in seen)
        seen.add(identity)
        require(row['article_url'] == by_id[identity]['url'] and row['content_hash'] == by_id[identity]['content_hash'])
        require(row['rights_status'] in {'unknown', 'allowed', 'denied'})
        require(isinstance(row['status'], str) and bool(row['status']))
        if row['status'] == 'found':
            require(row['rights_status'] != 'denied' and row['origin'] in ORIGINS)
            require(safe_image_url(row['image_url']) == row['image_url'] and row['image_url'] is not None)
            images[identity] = row['image_url']
        else:
            require(row['image_url'] is None)
    return images
