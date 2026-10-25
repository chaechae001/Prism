-- RSS migration 적용 후 실행하는 읽기 전용 확인 쿼리입니다.
select
  n.nspname as schema_name,
  c.relname as table_name,
  c.relrowsecurity as rls_enabled,
  has_table_privilege('anon', c.oid, 'SELECT') as anon_select_allowed,
  has_table_privilege('authenticated', c.oid, 'SELECT') as authenticated_select_allowed
from pg_catalog.pg_class c
join pg_catalog.pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'private'
  and c.relname in ('rss_feeds', 'rss_items')
  and c.relkind = 'r'
order by c.relname;
