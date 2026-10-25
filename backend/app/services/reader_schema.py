"""Additive private schema installation with collision and access checks."""
from pathlib import Path
from sqlalchemy import text
from ..cluster_store.repository import _engine

TABLES={'prism_editorial_summaries','prism_reader_bookmarks','prism_reader_comments','prism_reader_threads','prism_reader_messages','prism_reader_usage'}
FILE=Path(__file__).resolve().parents[3]/'database/migrations/20261024_001_summary_quality_accounts.sql'


def status(*,engine=None):
    with _engine(engine).connect() as c,c.begin():
        c.execute(text('SET TRANSACTION READ ONLY'))
        rows=c.execute(text("""SELECT c.relname,c.relkind,c.relrowsecurity,obj_description(c.oid,'pg_class') AS marker,
            has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
            has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
            has_table_privilege('service_role',c.oid,'SELECT,INSERT,UPDATE,DELETE') AS exposed
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='private' AND c.relkind IN ('r','p','v','m','f')
            AND (c.relname LIKE 'prism_reader_%' OR c.relname='prism_editorial_summaries')""")).mappings().all()
    if rows:
        if {r['relname'] for r in rows}!=TABLES or any(r['relkind']!='r' or not r['relrowsecurity'] or r['exposed'] for r in rows):
            raise ValueError('새 스키마와 같은 이름의 구조 또는 접근 권한을 확인해주세요.')
        markers={r['relname']:r['marker'] for r in rows}
        if markers['prism_editorial_summaries']!='prism-editorial/v1: source-bound reviewed cluster summaries' or markers['prism_reader_bookmarks']!='prism-reader/v1: owner-scoped server storage; no direct browser grants':
            raise ValueError('기존 테이블 버전이 다릅니다. 변경하지 않았습니다.')
    return {'ready':bool(rows),'tables':len(rows),'public_access':False}


def install(*,engine=None):
    current=status(engine=engine)
    if current['ready']: return {**current,'changed':False}
    with _engine(engine).begin() as c:
        c.execute(text("SET LOCAL lock_timeout='2s'"))
        c.exec_driver_sql(FILE.read_text(encoding='utf-8'))
    return {**status(engine=engine),'changed':True}
