"""Additive private AI storage, installed only by an explicit command."""
from pathlib import Path
from sqlalchemy import text
from ..cluster_store.repository import _engine

TABLES={'prism_rag_chunks','prism_llm_runs'}
COLUMNS={'prism_rag_chunks':set('batch_id article_id model_id body_sha256 chunk_id start_offset end_offset embedding created_at'.split()),
    'prism_llm_runs':set('id task provider model prompt_version input_hash status error_type elapsed_ms input_tokens output_tokens estimated_cost_usd created_at'.split())}
SQL=Path(__file__).resolve().parents[3]/'database/migrations/20261025_001_llm_retrieval_observability.sql'


DIMENSIONS=SQL.with_name('20261025_002_rag_embedding_dimensions.sql')

def status(*,engine=None):
    with _engine(engine).connect() as c,c.begin():
        c.execute(text('SET TRANSACTION READ ONLY'))
        rows=c.execute(text("""SELECT c.relname,c.relkind,c.relrowsecurity,obj_description(c.oid,'pg_class') AS marker,
            has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
            has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') OR
            has_table_privilege('service_role',c.oid,'SELECT,INSERT,UPDATE,DELETE') AS exposed
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='private'
            AND c.relname IN ('prism_rag_chunks','prism_llm_runs')""")).mappings().all()
        columns=c.execute(text("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='private' AND table_name IN ('prism_rag_chunks','prism_llm_runs')")).mappings().all()
        dimension_check=c.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid=to_regclass('private.prism_rag_chunks') AND conname='prism_rag_chunks_embedding_check'")).scalar_one_or_none()
    if rows and ({r['relname'] for r in rows}!=TABLES or any(r['relkind']!='r' or not r['relrowsecurity'] or r['exposed'] or r['marker']!='prism-ai-storage/v1' for r in rows)):
        raise ValueError('AI 저장 스키마 또는 접근 권한이 예상과 다릅니다.')
    if rows and {name:{r['column_name'] for r in columns if r['table_name']==name} for name in TABLES}!=COLUMNS:
        raise ValueError('AI 저장 테이블 열이 예상 버전과 다릅니다.')
    return {'ready':bool(rows),'tables':len(rows),'bge_dimensions_ready':bool(dimension_check and '1024' in dimension_check)}


def install(*,engine=None):
    existing=status(engine=engine)
    if existing['ready'] and existing['bge_dimensions_ready']: return {**existing,'changed':False}
    with _engine(engine).begin() as c:
        c.execute(text("SET LOCAL lock_timeout='2s'"))
        if not existing['ready']:c.exec_driver_sql(SQL.read_text(encoding='utf-8'))
        c.exec_driver_sql(DIMENSIONS.read_text(encoding='utf-8'))
    return {**status(engine=engine),'changed':True}
