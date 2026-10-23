"""Insert-only storage, one transaction, no changes to existing application data."""
from pathlib import Path
from sqlalchemy import text

from .bundle import validate_bundle, summarize_bundle, canonical

TABLES = ('prism_cluster_batches','prism_cluster_articles','prism_cluster_groups','prism_cluster_members')
SCHEMA_FILE = Path(__file__).resolve().parents[3]/'database/migrations/20261023_001_cluster_storage.sql'
SCHEMA_MARKER = 'prism-cluster-storage/v1: immutable private worker batches; no automatic publishing'
COLUMNS = {
    TABLES[0]:set('batch_id payload_sha256 namespace source_hashes article_count group_count automatic_publication accuracy_measured requires_human_review created_at'.split()),
    TABLES[1]:set('batch_id article_id canonical_url title publisher_name category published_at raw_text body_sha256 content_hash image_url rights record'.split()),
    TABLES[2]:set('batch_id group_id representative_article_id category article_count same_event_verified review'.split()),
    TABLES[3]:set('batch_id group_id article_id'.split()),
}


def _engine(engine):
    if engine is not None:return engine
    # An explicit storage command may run while the shell still has cluster-local selected.
    # Only this DB boundary loads the private DB file; offline preparation does not.
    from dotenv import load_dotenv
    from ..config import ROOT
    from ..db import get_engine
    load_dotenv(ROOT/'.env',interpolate=False,override=False,encoding='utf-8-sig')
    return get_engine()


def _check_schema(connection):
    marker=connection.execute(text("SELECT obj_description(to_regclass('private.prism_cluster_batches'),'pg_class')")).scalar_one_or_none()
    if marker!=SCHEMA_MARKER:raise ValueError('Existing table namespace has a different schema marker')
    columns=connection.execute(text("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='private' AND table_name IN ('prism_cluster_batches','prism_cluster_articles','prism_cluster_groups','prism_cluster_members')")).mappings().all()
    actual={name:{row['column_name'] for row in columns if row['table_name']==name} for name in TABLES}
    if actual!=COLUMNS:raise ValueError('Private storage columns differ from the expected version')
    rows=connection.execute(text("""SELECT c.relname,c.relkind,c.relrowsecurity,
        (has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
         has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
         has_table_privilege('service_role',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
         EXISTS(SELECT 1 FROM pg_catalog.pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal)) AS exposed
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='private' AND c.relname IN ('prism_cluster_batches','prism_cluster_articles','prism_cluster_groups','prism_cluster_members')""")).mappings().all()
    if len(rows)!=4 or any(r['relkind']!='r' or r['relrowsecurity'] is not True or r['exposed'] for r in rows):
        raise ValueError('Private storage RLS or grants differ from the expected boundary')


def schema_status(*,engine=None):
    with _engine(engine).connect() as connection:
        with connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            rows=connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='private' AND table_name IN ('prism_cluster_batches','prism_cluster_articles','prism_cluster_groups','prism_cluster_members')")).scalars().all()
            found=set(rows)
            if found and found!=set(TABLES):raise ValueError('Private storage schema is partial; inspect before changing it')
            if found:_check_schema(connection)
    return dict(schema_ready=found==set(TABLES),tables_found=len(found))


def install_schema(*,engine=None):
    engine=_engine(engine)
    status=schema_status(engine=engine)
    if status['schema_ready']:return dict(**status,changed=False)
    with engine.begin() as connection:
        connection.execute(text('SET LOCAL lock_timeout=\'2s\''))
        connection.exec_driver_sql(SCHEMA_FILE.read_text(encoding='utf-8'))
    return dict(schema_ready=True,tables_found=4,changed=True)


def _existing(connection,value):
    row=connection.execute(text('SELECT payload_sha256,article_count,group_count FROM private.prism_cluster_batches WHERE batch_id=:batch'),
        {'batch':value['batch_id']}).mappings().first()
    if row is not None:
        summary=summarize_bundle(value)
        if (row['payload_sha256'],row['article_count'],row['group_count'])!=(value['payload_sha256'],summary['articles'],summary['groups']):
            raise ValueError('Existing batch identity conflicts; no rows changed')
    return row


def plan_bundle(value,*,engine=None):
    value=validate_bundle(value);summary=summarize_bundle(value)
    if not summary['ready_to_store']:
        return dict(**summary,status='blocked_rights',database_writes=0)
    engine=_engine(engine)
    if not schema_status(engine=engine)['schema_ready']:
        return dict(**summary,status='schema_required',database_writes=0)
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            existing=_existing(connection,value)
    return dict(**summary,status='already_stored' if existing else 'ready',database_writes=0)


def store_bundle(value,*,engine=None):
    value=validate_bundle(value);summary=summarize_bundle(value)
    if not summary['ready_to_store']:raise ValueError('Source collect/store approval is missing; no DB connection or writes')
    p=value['payload'];engine=_engine(engine)
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout='10s'"))
        connection.execute(text("SET LOCAL lock_timeout='2s'"))
        _check_schema(connection)  # Reject a conflicting relation before the first mutation.
        inserted=connection.execute(text('''INSERT INTO private.prism_cluster_batches
            (batch_id,payload_sha256,namespace,source_hashes,article_count,group_count)
            VALUES (:batch,:hash,:namespace,CAST(:sources AS jsonb),:articles,:groups)
            ON CONFLICT (batch_id) DO NOTHING RETURNING batch_id'''),
            dict(batch=value['batch_id'],hash=value['payload_sha256'],namespace=p['namespace'],
                 sources=canonical(p['sources']),articles=summary['articles'],groups=summary['groups'])).scalar_one_or_none()
        if inserted is None:
            if _existing(connection,value) is None:raise ValueError('Existing batch could not be verified')
            return dict(**summary,status='already_stored',database_writes=0)
        for a in p['articles']:
            record={k:v for k,v in a.items() if k!='body'}
            connection.execute(text('''INSERT INTO private.prism_cluster_articles
                (batch_id,article_id,canonical_url,title,publisher_name,category,published_at,raw_text,
                 body_sha256,content_hash,image_url,rights,record)
                VALUES (:batch,:id,:url,:title,:publisher,:category,:at,:body,:bodyhash,:hash,:image,CAST(:rights AS jsonb),CAST(:record AS jsonb))'''),
                dict(batch=value['batch_id'],id=a['article_id'],url=a['url'],title=a['title'],publisher=a['publisher'],
                     category=a['category'],at=a['published_at'],body=a['body'],bodyhash=a['body_sha256'],
                     hash=a['content_hash'],image=a['image_url'],rights=canonical(a['rights']),record=canonical(record)))
        for g in p['groups']:
            connection.execute(text('''INSERT INTO private.prism_cluster_groups
                (batch_id,group_id,representative_article_id,category,article_count,review)
                VALUES (:batch,:id,:representative,:category,:count,CAST(:review AS jsonb))'''),
                dict(batch=value['batch_id'],id=g['group_id'],representative=g['representative_article_id'],category=g['category'],
                     count=len(g['article_ids']),review=canonical(dict(required=True,quality_review_required=g['quality_review_required'],reasons=g['quality_review_reasons']))))
            for identity in g['article_ids']:
                connection.execute(text('INSERT INTO private.prism_cluster_members (batch_id,group_id,article_id) VALUES (:batch,:group,:article)'),
                    dict(batch=value['batch_id'],group=g['group_id'],article=identity))
    return dict(**summary,status='stored',database_writes=1+summary['articles']+summary['groups']+summary['articles'])
