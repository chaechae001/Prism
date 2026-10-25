-- RSS 수집 입력 저장용 테이블 두 개를 추가합니다.
-- 대상: 기존 schema.draft.sql을 적용한 Supabase 개발 DB.
-- 기존 public 7개/private 3개 테이블과 데이터는 변경하지 않습니다.
-- 최초 1회 적용용입니다. 이미 테이블이 있다면 구조를 확인하고 재실행하지 않습니다.
begin;

create table private.rss_feeds (
  id text primary key check (length(btrim(id)) > 0),
  publisher_id text not null references public.publishers(id),
  feed_url text not null unique
    check (feed_url ~* '^https?://[^[:space:]]+$'),
  default_category text not null
    check (default_category in ('politics','economy','society','technology')),

  -- 수집 허용 여부를 확인하기 전에는 실제 HTTP 수집을 활성화하지 않습니다.
  enabled boolean not null default false,
  rights jsonb not null default
    '{"collect":"unknown","store":"unknown","summarize":"unknown","publish_summary":"unknown","display_image":"unknown"}'::jsonb,

  last_attempt_at timestamptz,
  last_success_at timestamptz,
  last_error_code text,
  created_at timestamptz not null default now(),

  constraint rss_feeds_rights_check check (
    jsonb_typeof(rights) = 'object'
    and rights ?& array['collect','store','summarize','publish_summary','display_image']
    and (rights - array['collect','store','summarize','publish_summary','display_image']) = '{}'::jsonb
    and coalesce(rights->>'collect', '') in ('allowed','unknown','denied')
    and coalesce(rights->>'store', '') in ('allowed','unknown','denied')
    and coalesce(rights->>'summarize', '') in ('allowed','unknown','denied')
    and coalesce(rights->>'publish_summary', '') in ('allowed','unknown','denied')
    and coalesce(rights->>'display_image', '') in ('allowed','unknown','denied')
  )
);

create table private.rss_items (
  id text primary key check (length(btrim(id)) > 0),
  feed_id text not null references private.rss_feeds(id),

  -- 기존 기사에 연결하기 전에는 null입니다. 기사 삭제 시에도 수신 이력은 보존합니다.
  article_id text references public.articles(id) on delete set null,
  item_key text not null check (length(btrim(item_key)) > 0),
  source_item_id text,

  -- 제목/URL 오류 입력도 error 상태로 보존할 수 있도록 컬럼은 null을 허용합니다.
  original_url text,
  canonical_url text,
  title text,
  author text,
  source_category text,
  category text not null
    check (category in ('politics','economy','society','technology')),

  -- RSS 설명은 AI 요약이 아닙니다. HTML·미디어 정보는 private에 보관합니다.
  rss_description text,
  content_html text,
  media jsonb not null default '[]'::jsonb
    check (jsonb_typeof(media) = 'array'),
  raw_item_xml text,
  source_published_raw text,

  -- 발행일이 없거나 잘못되면 null을 유지합니다. 수집 시각으로 대신하지 않습니다.
  published_at timestamptz,
  collected_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),

  -- error는 내부 보존 상태입니다. reader는 parsed/partial만 반환해야 합니다.
  parse_status text not null default 'partial'
    check (parse_status in ('parsed','partial','error')),
  parse_issues jsonb not null default '[]'::jsonb
    check (jsonb_typeof(parse_issues) = 'array'),
  body_status text not null default 'not_provided'
    check (body_status in ('not_provided','rss_excerpt','content_available','blocked')),
  rights_snapshot jsonb not null default
    '{"collect":"unknown","store":"unknown","summarize":"unknown","publish_summary":"unknown","display_image":"unknown"}'::jsonb,
  is_demo boolean not null default false,

  -- 같은 피드의 재수집 중복을 막고, 같은 기사의 다른 피드 유입은 각각 보존합니다.
  constraint rss_items_feed_item_key_unique unique (feed_id, item_key),

  constraint rss_items_displayable_fields_check check (
    parse_status = 'error'
    or (
      title is not null and length(btrim(title)) > 0
      and original_url is not null
      and original_url ~* '^https?://[^[:space:]]+$'
      and canonical_url is not null
      and canonical_url ~* '^https?://[^[:space:]]+$'
    )
  ),

  constraint rss_items_rights_snapshot_check check (
    jsonb_typeof(rights_snapshot) = 'object'
    and rights_snapshot ?& array['collect','store','summarize','publish_summary','display_image']
    and (rights_snapshot - array['collect','store','summarize','publish_summary','display_image']) = '{}'::jsonb
    and coalesce(rights_snapshot->>'collect', '') in ('allowed','unknown','denied')
    and coalesce(rights_snapshot->>'store', '') in ('allowed','unknown','denied')
    and coalesce(rights_snapshot->>'summarize', '') in ('allowed','unknown','denied')
    and coalesce(rights_snapshot->>'publish_summary', '') in ('allowed','unknown','denied')
    and coalesce(rights_snapshot->>'display_image', '') in ('allowed','unknown','denied')
  )
);

create index rss_feeds_publisher_idx on private.rss_feeds(publisher_id);
create index rss_items_feed_collected_idx
  on private.rss_items(feed_id, collected_at desc, id);
create index rss_items_collected_idx
  on private.rss_items(collected_at desc, id);
create index rss_items_article_idx
  on private.rss_items(article_id) where article_id is not null;

-- 같은 기사의 다중 피드 유입을 보존하므로 canonical_url에는 UNIQUE를 붙이지 않습니다.
create index rss_items_canonical_url_idx
  on private.rss_items(canonical_url) where canonical_url is not null;

alter table private.rss_feeds enable row level security;
alter table private.rss_items enable row level security;

-- 새 테이블만 제한합니다. 기존 테이블·스키마 권한은 변경하지 않습니다.
revoke all privileges on table private.rss_feeds, private.rss_items
  from public, anon, authenticated;

comment on table private.rss_feeds is
  'RSS 입력 피드 설정. 기본 비활성 및 권한 미확인. 백엔드 전용.';
comment on table private.rss_items is
  'RSS 수신 이력. 피드별 item_key 중복 방지. 원문 HTML과 오류 입력은 비공개 보존.';
comment on column private.rss_items.parse_status is
  'parsed/partial은 내부 reader 반환 후보. error는 원본 보존용이며 reader에서 제외.';
comment on column private.rss_items.raw_item_xml is
  '원본 항목 보존용 내부 추가 필드. 공통 JSON에는 노출하지 않음.';
comment on column private.rss_items.parse_issues is
  '날짜 오류·누락 등 파싱 이슈 목록. 공통 JSON에는 노출하지 않음.';
comment on column private.rss_items.last_seen_at is
  '같은 항목을 다시 수신한 시각. collected_at은 최초 수집 시각으로 보존할 예정.';
comment on column private.rss_items.is_demo is
  '가상 XML 적재 시 true를 명시. 실제 수집 데이터는 false.';

commit;
