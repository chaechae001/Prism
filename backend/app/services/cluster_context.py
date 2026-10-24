"""Server-only, membership-bound reads of permitted cluster bodies."""
import os

from pydantic import HttpUrl
from sqlalchemy import bindparam, text

from ..cluster_feed import story_identity, legacy_story_identity
from ..cluster_store.repository import _engine
from ..scheduled_news.repository import namespace as check_namespace, _schema


class ClusterContextError(ValueError):
    """The selected news no longer matches a usable current DB context."""


def _require(value):
    if not value:
        raise ClusterContextError('Selected news context is stale or unavailable')


def chat_cluster_bodies(story, *, engine=None, namespace=None):
    namespace = check_namespace(namespace or os.getenv('PRISM_CLUSTER_NAMESPACE', 'scheduled-local-test'))
    with _engine(engine).connect() as c, c.begin():
        c.execute(text('SET TRANSACTION READ ONLY'))
        _schema(c)
        head = c.execute(text('''SELECT b.batch_id FROM private.prism_cluster_heads h
            JOIN private.prism_cluster_batches b ON b.batch_id=h.batch_id
            WHERE h.namespace=:ns AND b.namespace=:ns'''),
                         {'ns':namespace}).scalar_one_or_none()
        _require(head is not None)
        groups = c.execute(text('SELECT group_id,representative_article_id FROM private.prism_cluster_groups WHERE batch_id=:batch LIMIT 2001'),
                           {'batch':head}).mappings().all()
        _require(len(groups) <= 2000)
        group = next((g for g in groups if story.id in {
            story_identity(namespace,g['group_id']), legacy_story_identity(g['group_id'])}), None)
        _require(group is not None)
        rows = c.execute(text('''SELECT a.article_id,a.record,a.rights,a.body_sha256,a.content_hash
            FROM private.prism_cluster_members m JOIN private.prism_cluster_articles a
            ON a.batch_id=m.batch_id AND a.article_id=m.article_id
            WHERE m.batch_id=:batch AND m.group_id=:group LIMIT 2001'''),
            {'batch':head,'group':group['group_id']}).mappings().all()
        _require(len(rows) <= 2000 and len(rows) == len(story.articles))
        by_id = {r['article_id']:r for r in rows}
        _require(set(by_id) == {a.id for a in story.articles})
        _require(story.articles and story.articles[0].id == group['representative_article_id'])
        _require(story.title == story.articles[0].title)
        permitted = []
        for article in story.articles:
            row = by_id[article.id]
            record = row['record']
            _require(record['article_id'] == article.id and record['title'] == article.title)
            _require(HttpUrl(record['url']) == article.url and record['rights'] == row['rights'])
            _require(record['body_sha256'] == row['body_sha256'] and record['content_hash'] == row['content_hash'])
            if all(row['rights'].get(use) == 'allowed' for use in ('collect','store','summarize')):
                permitted.append(article.id)
        _require(permitted)
        # Return only bounded excerpts. Fingerprints are checked inside Postgres.
        query = text('''SELECT article_id,left(raw_text,12000) AS excerpt,char_length(raw_text) AS body_length,
            body_sha256=encode(sha256(convert_to(raw_text,'UTF8')),'hex') AS valid
            FROM private.prism_cluster_articles WHERE batch_id=:batch AND article_id IN :ids''').bindparams(bindparam('ids',expanding=True))
        bodies = c.execute(query, {'batch':head,'ids':permitted[:50]}).mappings().all()
        _require(len(bodies) == len(permitted[:50]) and all(r['valid'] for r in bodies))
        texts = {r['article_id']:r for r in bodies}
    remaining, result = 24000, []
    for identity in permitted[:50]:
        if remaining <= 0:
            break
        row = texts[identity]
        _require(isinstance(row['excerpt'],str) and row['excerpt'].strip())
        excerpt = row['excerpt'][:remaining]
        remaining -= len(excerpt)
        result.append({'article_id':identity,'text':excerpt,'is_excerpt':len(excerpt)<row['body_length']})
    return result
