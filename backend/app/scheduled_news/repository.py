"""Own inbox revisions and completed-preview pointer; never writes team tables."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import re

from sqlalchemy import text

from ..article_images.metadata import safe_image_url
from ..cluster_preview import CATEGORIES,_date
from ..cluster_store.bundle import USES,canonical,_url
from ..cluster_store.repository import _engine,_check_schema,store_bundle
from ..config import ROOT

TABLES={'prism_ingest_articles','prism_cluster_heads'}
MARKERS={'prism_ingest_articles':'prism-scheduled-news/v1: private source revisions and observation times',
         'prism_cluster_heads':'prism-scheduled-news/v1: current completed candidate batch per namespace'}
COLUMNS={'prism_ingest_articles':set('namespace article_id revision_sha256 canonical_url source_id published_at raw_text body_sha256 record first_seen_at last_seen_at'.split()),
         'prism_cluster_heads':set('namespace batch_id input_sha256 analyzed_at'.split())}
VOLATILE={'collected_at','rss_fetched_at','last_seen_at'}


def namespace(value):
    if not isinstance(value,str) or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',value) is None:
        raise ValueError('Invalid worker namespace')
    return value


def stable_row(row):return {k:v for k,v in row.items() if k not in VOLATILE}


def validate_rows(rows):
    if not isinstance(rows,list) or len(rows)>500:raise ValueError('Expected at most 500 inbox articles')
    result=[];ids=set();urls=set()
    for original in rows:
        if not isinstance(original,dict):raise ValueError('Expected article object')
        row=deepcopy(original)
        for key,maximum in [('article_id',512),('title',2000),('body',2000000),('publisher',2000),('source_id',512)]:
            value=row.get(key)
            if not isinstance(value,str) or not value.strip() or '\0' in value or len(value)>maximum:
                raise ValueError('Invalid inbox article text or identity')
        _url(row.get('url'));_date(row.get('published_at'))
        if row.get('category') not in CATEGORIES or row.get('body_kind') not in {'provided_body','publisher_html','rss_content'}:
            raise ValueError('Invalid inbox article category/body kind')
        if row.get('content_hash')!=sha256(f"{row['title']}\n{row['body']}".strip().encode()).hexdigest():
            raise ValueError('Inbox content hash differs')
        bodyhash=sha256(row['body'].encode()).hexdigest()
        if row.get('body_sha256',bodyhash)!=bodyhash:raise ValueError('Inbox body hash differs')
        rights=row.get('rights')
        if (not isinstance(rights,dict) or set(rights)!=set(USES) or
            any(v not in ('allowed','unknown','denied') for v in rights.values()) or
            rights['collect']!='allowed' or rights['store']!='allowed'):
            raise ValueError('Inbox needs explicit collect/store approval')
        image=row.get('image_url')
        if image is not None and safe_image_url(image)!=image:raise ValueError('Invalid inbox image URL')
        if rights['display_image']=='denied':row.update(image_url=None,image_origin=None)
        if row['article_id'] in ids or row['url'] in urls:raise ValueError('Duplicate inbox ID or URL')
        if type(row.get('is_demo',False)) is not bool:raise ValueError('Invalid demo flag')
        row['body_sha256']=bodyhash
        row.setdefault('source_notice','')
        if len(canonical(row).encode())>3_000_000:raise ValueError('Inbox record too large')
        ids.add(row['article_id']);urls.add(row['url']);result.append(row)
    return sorted(result,key=lambda a:a['article_id'])


def _schema(connection):
    _check_schema(connection)
    rows=connection.execute(text("""SELECT c.relname,c.relkind,c.relrowsecurity,
      obj_description(c.oid,'pg_class') AS marker,
      (has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
       has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
       has_table_privilege('service_role',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
       EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal)) AS exposed
      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='private' AND c.relname IN ('prism_ingest_articles','prism_cluster_heads')""")).mappings().all()
    if len(rows)!=2 or any(r['relkind']!='r' or not r['relrowsecurity'] or r['exposed'] or r['marker']!=MARKERS[r['relname']] for r in rows):
        raise ValueError('Scheduled private schema is missing or incompatible')
    cols=connection.execute(text("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='private' AND table_name IN ('prism_ingest_articles','prism_cluster_heads')")).mappings().all()
    if {t:{r['column_name'] for r in cols if r['table_name']==t} for t in TABLES}!=COLUMNS:
        raise ValueError('Scheduled private columns are incompatible')


def schema_status(*,engine=None):
    with _engine(engine).connect() as connection,connection.begin():
        connection.execute(text('SET TRANSACTION READ ONLY'))
        found=set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='private' AND table_name IN ('prism_ingest_articles','prism_cluster_heads')")).scalars().all())
        if found and found!=TABLES:raise ValueError('Partial scheduled schema; inspect before changing it')
        if found:_schema(connection)
        else:_check_schema(connection)
    return dict(schema_ready=found==TABLES,tables_found=len(found))


def install_schema(*,engine=None):
    engine=_engine(engine);status=schema_status(engine=engine)
    if status['schema_ready']:return dict(**status,changed=False)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout='2s'"))
        connection.exec_driver_sql((ROOT/'database/migrations/20261023_002_scheduled_news.sql').read_text(encoding='utf-8'))
        _schema(connection)
    return dict(schema_ready=True,tables_found=2,changed=True)


class Repository:
    def __init__(self,engine=None):self.engine=_engine(engine)

    @contextmanager
    def lock(self,value):
        value=namespace(value)
        key=int.from_bytes(sha256(('prism-scheduled:'+value).encode()).digest()[:8],'big',signed=True)
        with self.engine.connect() as connection:
            acquired=False
            try:
                with connection.begin():
                    _schema(connection)
                    acquired=connection.execute(text('SELECT pg_try_advisory_lock(:key)'),{'key':key}).scalar_one()
                yield bool(acquired)
            finally:
                if acquired:
                    try:
                        if connection.in_transaction():connection.rollback()
                        with connection.begin():
                            unlocked=connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':key}).scalar_one()
                            if not unlocked:raise RuntimeError('Worker lock ownership was lost')
                    except Exception:
                        connection.invalidate()  # Never return a session holding a lock to the pool.
                        raise

    def known_ids(self,value,*,since):
        with self.engine.connect() as c,c.begin():
            c.execute(text('SET TRANSACTION READ ONLY'))
            return set(c.execute(text('SELECT DISTINCT article_id FROM private.prism_ingest_articles WHERE namespace=:ns AND last_seen_at>=:since'),
                dict(ns=namespace(value),since=since)).scalars().all())

    def observations(self,value,*,after):
        with self.engine.connect() as c,c.begin():
            c.execute(text('SET TRANSACTION READ ONLY'))
            rows=c.execute(text('''SELECT article_id,max(last_seen_at) AS last_seen_at
                FROM private.prism_ingest_articles WHERE namespace=:ns AND published_at>:after
                GROUP BY article_id'''),dict(ns=namespace(value),after=after)).mappings().all()
            return {r['article_id']:r['last_seen_at'] for r in rows}

    def ingest(self,value,rows,*,observed_at):
        rows=validate_rows(rows);value=namespace(value)
        if not rows:return 0
        with self.engine.begin() as c:
            c.execute(text("SET LOCAL statement_timeout='10s'"));_schema(c)
            for row in rows:
                collision=c.execute(text('SELECT article_id,canonical_url FROM private.prism_ingest_articles WHERE namespace=:ns AND (article_id=:id OR canonical_url=:url)'),
                    dict(ns=value,id=row['article_id'],url=row['url'])).mappings().all()
                if any(r['article_id']!=row['article_id'] or r['canonical_url']!=row['url'] for r in collision):
                    raise ValueError('Existing inbox article ID/URL conflict')
                record={k:v for k,v in row.items() if k!='body'}
                revision=sha256(canonical(stable_row(row)).encode()).hexdigest()
                c.execute(text('''INSERT INTO private.prism_ingest_articles
                  (namespace,article_id,revision_sha256,canonical_url,source_id,published_at,raw_text,body_sha256,record,first_seen_at,last_seen_at)
                  VALUES (:ns,:id,:rev,:url,:source,:at,:body,:bodyhash,CAST(:record AS jsonb),:seen,:seen)
                  ON CONFLICT (namespace,article_id,revision_sha256) DO UPDATE
                  SET last_seen_at=GREATEST(prism_ingest_articles.last_seen_at,EXCLUDED.last_seen_at)'''),
                  dict(ns=value,id=row['article_id'],rev=revision,url=row['url'],source=row['source_id'],at=row['published_at'],
                       body=row['body'],bodyhash=row['body_sha256'],record=canonical(record),seen=observed_at))
        return len(rows)

    def read_window(self,value,*,after,before,maximum):
        with self.engine.connect() as c,c.begin():
            c.execute(text('SET TRANSACTION READ ONLY'))
            rows=c.execute(text('''WITH latest AS (
                SELECT DISTINCT ON (article_id) article_id,published_at,raw_text,record
                FROM private.prism_ingest_articles WHERE namespace=:ns
                ORDER BY article_id,last_seen_at DESC,revision_sha256 DESC)
              SELECT raw_text,record FROM latest WHERE published_at>:after AND published_at<=:before
              ORDER BY published_at DESC,article_id LIMIT :cap'''),
              dict(ns=namespace(value),after=after,before=before,cap=maximum+1)).mappings().all()
        if len(rows)>maximum:raise ValueError('Analysis window exceeds cap; shorten window before replacing results')
        return validate_rows([{**r['record'],'body':r['raw_text']} for r in rows])

    def latest_input_hash(self,value):
        with self.engine.connect() as c,c.begin():
            c.execute(text('SET TRANSACTION READ ONLY'))
            return c.execute(text('SELECT input_sha256 FROM private.prism_cluster_heads WHERE namespace=:ns'),dict(ns=namespace(value))).scalar_one_or_none()

    def store(self,bundle,*,input_hash,analyzed_at):
        result=store_bundle(bundle,engine=self.engine)
        value=bundle['payload']['namespace']
        with self.engine.begin() as c:
            _schema(c)
            matched=c.execute(text('SELECT batch_id FROM private.prism_cluster_batches WHERE batch_id=:batch AND namespace=:ns'),
                dict(batch=bundle['batch_id'],ns=value)).scalar_one_or_none()
            if matched is None:raise ValueError('Completed batch namespace mismatch')
            c.execute(text('''INSERT INTO private.prism_cluster_heads(namespace,batch_id,input_sha256,analyzed_at)
                VALUES (:ns,:batch,:hash,:at) ON CONFLICT(namespace) DO UPDATE
                SET batch_id=EXCLUDED.batch_id,input_sha256=EXCLUDED.input_sha256,analyzed_at=EXCLUDED.analyzed_at'''),
                dict(ns=value,batch=bundle['batch_id'],hash=input_hash,at=analyzed_at))
        return result
