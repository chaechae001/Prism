"""Validate a private storage batch from unchanged local cluster artifacts."""
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from ..article_images.collection import images_from_manifest
from ..article_images.metadata import safe_image_url
from ..cluster_preview import CATEGORIES, _convert

VERSION = 'prism-cluster-storage/v1'
MAX_BYTES = 20_000_000
USES = ('collect', 'store', 'summarize', 'publish_summary', 'display_image')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _require(condition):
    if not condition:
        raise ValueError('Invalid or inconsistent private cluster batch')


def _object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def load_json(raw):
    _require(len(raw) <= MAX_BYTES)
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_object,
                      parse_constant=lambda _: _require(False))


def _text(value, maximum=8000):
    _require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum and '\0' not in value)
    value.encode('utf-8')
    return value


def _hash(value):
    _require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None)


def _url(value):
    _text(value)
    parts = urlsplit(value)
    _require(parts.scheme in {'http','https'} and parts.hostname and parts.username is None and parts.password is None)
    _require(parts.port is None or 1 <= parts.port <= 65535)


def _views(articles, exported, source):
    by_id = {row['article_id']:row for row in articles}
    views = {identity:[] for identity in by_id}

    def attach(row, parent=None, depth=0):
        _require(isinstance(row, dict) and depth <= 8)
        identity = row.get('article_id', row.get('id', parent))
        if identity not in by_id:
            _require(parent is None)
            return
        _require(parent is None or parent == identity)
        original = by_id[identity]
        _require(row.get('url', row.get('canonical_url', original['url'])) == original['url'])
        _require(row.get('title', original['title']) == original['title'])
        body_hash = sha256(original['body'].encode()).hexdigest()
        _require(row.get('content_hash', original['content_hash']) in {original['content_hash'], body_hash})
        for field in ('body','text'):
            if row.get(field) is not None:
                _require(row[field] == original['body'])
        views[identity].append(row)
        for field in ('metadata','analyst_metadata'):
            if field in row:
                attach(row[field], identity, depth+1)

    for row in articles:
        attach(row)
    if source is not None:
        rows = source if isinstance(source,list) else source.get('articles',source.get('results')) if isinstance(source,dict) else None
        _require(isinstance(rows,list) and len(rows) <= 2000)
        for row in rows:
            attach(row)
    for group in exported['groups']:
        attach(group['representative'])
        for row in group.get('related_articles',[]):
            attach(row)
    return views


def _licensed_permission(row, use):
    status = row['license_status']
    uses = row.get('allowed_uses', [])
    _require(type(status) is str and status in ('allowed','unknown','denied'))
    _require(isinstance(uses,list) and len(uses)<=len(USES) and all(type(v) is str and v in USES for v in uses))
    _require(len(set(uses))==len(uses))
    return 'denied' if status=='denied' else 'allowed' if status=='allowed' and use in uses else 'unknown'


def _permission(views, use):
    values = []
    for row in views:
        for field in ('rights','rights_snapshot'):
            rights = row.get(field)
            if isinstance(rights,dict):
                if use in rights:
                    value = rights[use]
                    _require(value in ('allowed','unknown','denied'))
                    values.append(value)
                if 'license_status' in rights:
                    values.append(_licensed_permission(rights,use))
        if 'license_status' in row:
            values.append(_licensed_permission(row,use))
    if 'denied' in values:
        return 'denied'
    return 'allowed' if values and all(value=='allowed' for value in values) else 'unknown'


def prepare_bundle(results_dir, *, namespace, image_manifest=None):
    _require(isinstance(namespace,str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',namespace) is not None)
    folder = Path(results_dir)
    article_bytes = (folder/'articles.json').read_bytes()
    representative_bytes = (folder/'representatives.json').read_bytes()
    input_bytes = (folder/'input.json').read_bytes() if (folder/'input.json').is_file() else None
    normalized, exported = load_json(article_bytes), load_json(representative_bytes)
    _convert(exported,normalized)  # Reuse the existing full partition/identity/body validation.
    _require(len(normalized['articles']) > 0)
    source = load_json(input_bytes) if input_bytes is not None else None
    views = _views(normalized['articles'],exported,source)
    image_bytes = Path(image_manifest).read_bytes() if image_manifest is not None else None
    if image_bytes is not None:
        load_json(image_bytes)  # Reject duplicate keys before using the existing bytes-bound reader.
    images = images_from_manifest(image_bytes,article_bytes,representative_bytes,
        normalized['articles'],input_bytes=input_bytes) if image_bytes is not None else {}
    articles = []
    for row in normalized['articles']:
        rights = {use:_permission(views[row['article_id']],use) for use in USES}
        demo_values = [v['is_demo'] for v in views[row['article_id']] if 'is_demo' in v]
        _require(all(type(v) is bool for v in demo_values) and len(set(demo_values)) <= 1)
        articles.append(dict(article_id=row['article_id'],title=row['title'],body=row['body'],
            url=row['url'],publisher=row['publisher'],source_id=row['source_id'],
            original_category=row['category'],category=CATEGORIES[row['category']],
            published_at=row['published_at'],body_kind=row['body_kind'],source_notice=row['source_notice'],
            content_hash=row['content_hash'],body_sha256=sha256(row['body'].encode()).hexdigest(),
            image_url=images.get(row['article_id']) if rights['display_image']!='denied' else None,
            rights=rights,is_demo=demo_values[0] if demo_values else False))
    groups = [dict(group_id=g['group_id'],category=CATEGORIES[g['category']],
        representative_article_id=g['representative']['article_id'],article_ids=sorted(g['article_ids']),
        same_event_verified=False,quality_review_required=g.get('quality_review_required',False),
        quality_review_reasons=g.get('quality_review_reasons',[])) for g in exported['groups']]
    digest = lambda raw: sha256(raw).hexdigest() if raw is not None else None
    payload = dict(namespace=namespace,automatic_publication=False,accuracy_measured=False,
        requires_human_review=True,sources=dict(articles=digest(article_bytes),representatives=digest(representative_bytes),
        input=digest(input_bytes),images=digest(image_bytes)),
        articles=sorted(articles,key=lambda a:a['article_id']),groups=sorted(groups,key=lambda g:g['group_id']))
    hashed = sha256(canonical(payload).encode()).hexdigest()
    return validate_bundle(dict(schema_version=VERSION,batch_id='prism-batch-'+hashed,payload_sha256=hashed,payload=payload))


def validate_bundle(value):
    _require(isinstance(value,dict) and set(value)=={'schema_version','batch_id','payload_sha256','payload'})
    _require(value['schema_version']==VERSION)
    p = value['payload']
    _require(isinstance(p,dict) and set(p)=={'namespace','automatic_publication','accuracy_measured','requires_human_review','sources','articles','groups'})
    _require(isinstance(p['namespace'],str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',p['namespace']) is not None)
    _require(p['automatic_publication'] is False and p['accuracy_measured'] is False and p['requires_human_review'] is True)
    _require(isinstance(p['sources'],dict) and set(p['sources'])=={'articles','representatives','input','images'})
    for key,hashed in p['sources'].items():
        if hashed is not None or key in {'articles','representatives'}:
            _hash(hashed)
    _require(isinstance(p['articles'],list) and 1 <= len(p['articles']) <= 2000)
    expected = {'article_id','title','body','url','publisher','source_id','original_category','category','published_at',
                'body_kind','source_notice','content_hash','body_sha256','image_url','rights','is_demo'}
    by_id,urls = {},set()
    for row in p['articles']:
        _require(isinstance(row,dict) and set(row)==expected)
        _text(row['article_id'],512);_text(row['title'],2000);_text(row['body'],2_000_000)
        _text(row['publisher'],2000);_text(row['source_id'],512)
        _require(isinstance(row['source_notice'],str) and len(row['source_notice'])<=8000 and '\0' not in row['source_notice'])
        _require(row['original_category'] in CATEGORIES and row['category']==CATEGORIES[row['original_category']])
        _url(row['url'])
        _text(row['published_at'],100)
        date = datetime.fromisoformat(row['published_at'].replace('Z','+00:00'))
        _require(date.tzinfo is not None and date.utcoffset() is not None)
        _require(row['body_kind'] in {'publisher_html','provided_body','rss_content'})
        _hash(row['content_hash']);_hash(row['body_sha256'])
        _require(row['content_hash']==sha256(f"{row['title']}\n{row['body']}".strip().encode()).hexdigest())
        _require(row['body_sha256']==sha256(row['body'].encode()).hexdigest())
        _require(type(row['is_demo']) is bool)
        _require(isinstance(row['rights'],dict) and set(row['rights'])==set(USES))
        _require(all(v in ('allowed','unknown','denied') for v in row['rights'].values()))
        _require(row['image_url'] is None or (safe_image_url(row['image_url'])==row['image_url'] and row['rights']['display_image']!='denied'))
        _require(row['article_id'] not in by_id and row['url'] not in urls)
        by_id[row['article_id']] = row
        urls.add(row['url'])
    _require(isinstance(p['groups'],list) and 1 <= len(p['groups']) <= len(by_id))
    seen,identities = set(),set()
    for group in p['groups']:
        _require(isinstance(group,dict) and set(group)=={'group_id','category','representative_article_id','article_ids',
            'same_event_verified','quality_review_required','quality_review_reasons'})
        _text(group['group_id'],512)
        _require(group['group_id'] not in identities and group['category'] in set(CATEGORIES.values()))
        members = group['article_ids']
        _require(isinstance(members,list) and members and all(isinstance(k,str) for k in members))
        _require(len(set(members))==len(members) and set(members)<=set(by_id) and not(seen & set(members)))
        _require(group['representative_article_id'] in members and group['same_event_verified'] is False)
        _require(type(group['quality_review_required']) is bool)
        _require(isinstance(group['quality_review_reasons'],list) and len(group['quality_review_reasons'])<=32)
        for reason in group['quality_review_reasons']:_text(reason,512)
        identities.add(group['group_id']);seen.update(members)
    _require(seen==set(by_id))
    text = canonical(p).encode()
    _require(len(text)<=MAX_BYTES)
    hashed = sha256(text).hexdigest()
    _require(value['payload_sha256']==hashed and value['batch_id']=='prism-batch-'+hashed)
    _require(len(canonical(value).encode())+1<=MAX_BYTES)  # Include envelope and the file's final newline.
    return json.loads(canonical(value))


def summarize_bundle(value):
    value = validate_bundle(value);p=value['payload']
    blocked = sum(a['rights']['collect']!='allowed' or a['rights']['store']!='allowed' for a in p['articles'])
    return dict(batch_id=value['batch_id'],namespace=p['namespace'],articles=len(p['articles']),groups=len(p['groups']),
        image_urls=sum(a['image_url'] is not None for a in p['articles']),blocked_articles=blocked,
        ready_to_store=blocked==0,automatic_publication=False,llm_calls=0)


def write_bundle(value, output):
    value = validate_bundle(value);target=Path(output)
    if target.exists() or target.is_symlink():raise FileExistsError('Use a fresh private batch path')
    raw=(canonical(value)+'\n').encode()
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.prism-store-',delete=False) as temporary:
            name=temporary.name;temporary.write(raw);temporary.flush();os.fsync(temporary.fileno())
        os.link(name,target)
    finally:
        if name is not None:
            try:os.unlink(name)
            except OSError:pass
    return target
