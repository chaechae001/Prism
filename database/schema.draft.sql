-- DESIGN DRAFT ONLY. Not a generated migration; not applied to any database.
-- Requires Supabase Postgres (auth.users, auth.uid(), anon/authenticated/service_role).
-- Confirm exposed schemas, roles and grants on a disposable development project first.
begin;
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table public.publishers (
  id text primary key,
  name text not null,
  group_id text not null,
  homepage text,
  created_at timestamptz not null default now()
);

create table public.stories (
  id text primary key,
  title text not null,
  dek text not null default '',
  category text not null check (category in ('politics','economy','society','technology')),
  keywords text[] not null default '{}',
  summary_status text not null default 'pending'
    check (summary_status in ('pending','ready','insufficient_sources','failed')),
  summary jsonb not null default '{"bullets":[],"unknowns":[]}',
  perspectives jsonb not null default '[]',
  label_status text not null default 'unverified' check (label_status in ('demo','reviewed','unverified')),
  event_version integer not null default 1 check (event_version > 0),
  updated_at timestamptz not null default now(),
  published_at timestamptz, -- null means not approved for public exposure
  retracted_at timestamptz,
  check (retracted_at is null or published_at is not null)
);

create table public.articles (
  id text primary key,
  publisher_id text not null references public.publishers(id),
  canonical_url text not null unique,
  title text not null,
  framing text,
  published_at timestamptz not null,
  publish_allowed boolean not null default false
  -- Public metadata only. Raw text, rights evidence, processing logs remain private.
);

create table public.story_articles (
  story_id text not null references public.stories(id) on delete cascade,
  article_id text not null references public.articles(id) on delete cascade,
  same_event_verified boolean not null default false,
  primary key (story_id,article_id)
);

create table private.raw_articles (
  id text primary key,
  publisher_id text not null references public.publishers(id),
  canonical_url text not null unique,
  content_hash text not null,
  raw_text text not null,
  license_status text not null check (license_status in ('allowed','unknown','denied')),
  allowed_uses text[] not null default '{}',
  rights_evidence jsonb not null default '{}',
  batch_id text not null,
  collected_at timestamptz not null default now()
);

create table private.pipeline_jobs (
  id uuid primary key default gen_random_uuid(),
  stage text not null check (stage in ('collect','preprocess','embed','cluster','summarize','review','publish')),
  status text not null default 'queued' check (status in ('queued','running','succeeded','failed')),
  idempotency_key text not null unique,
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 3 check (max_attempts > 0),
  run_after timestamptz not null default now(),
  locked_at timestamptz,
  locked_by text,
  payload jsonb not null default '{}',
  error_code text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);

create table private.summary_versions (
  id bigint generated always as identity primary key,
  story_id text not null references public.stories(id),
  event_version integer not null,
  article_set_hash text not null,
  model_version text not null,
  prompt_version text not null,
  output jsonb not null,
  review_status text not null default 'pending' check (review_status in ('pending','approved','rejected')),
  created_at timestamptz not null default now(),
  unique (story_id,event_version,article_set_hash,model_version,prompt_version)
);

-- Optional phase 2: these tables differ from today's anonymous/local-only mock.
create table public.bookmarks (
  user_id uuid not null references auth.users(id) on delete cascade,
  story_id text not null references public.stories(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id,story_id)
);

create table public.user_preferences (
  user_id uuid primary key references auth.users(id) on delete cascade,
  diversity smallint not null default 70 check (diversity between 0 and 100),
  updated_at timestamptz not null default now()
);

create table public.feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  story_id text not null references public.stories(id),
  kind text not null check (kind in ('useful','more_perspectives','report_error')),
  comment text check (char_length(comment) <= 500),
  created_at timestamptz not null default now()
);

create index stories_published_category_updated_idx on public.stories(category,updated_at desc,id)
  where published_at is not null and retracted_at is null;
create index stories_published_updated_idx on public.stories(updated_at desc,id)
  where published_at is not null and retracted_at is null;
create index articles_publisher_idx on public.articles(publisher_id);
create index story_articles_article_idx on public.story_articles(article_id);
create index raw_articles_publisher_idx on private.raw_articles(publisher_id);
create index raw_articles_hash_idx on private.raw_articles(content_hash);
create index pipeline_jobs_queue_idx on private.pipeline_jobs(run_after,created_at) where status='queued';
create index summary_versions_story_idx on private.summary_versions(story_id,created_at desc);
create index bookmarks_story_idx on public.bookmarks(story_id);
create index feedback_user_idx on public.feedback(user_id);
create index feedback_story_idx on public.feedback(story_id);

alter table public.publishers enable row level security;
alter table public.stories enable row level security;
alter table public.articles enable row level security;
alter table public.story_articles enable row level security;
alter table public.bookmarks enable row level security;
alter table public.user_preferences enable row level security;
alter table public.feedback enable row level security;
alter table private.raw_articles enable row level security;
alter table private.pipeline_jobs enable row level security;
alter table private.summary_versions enable row level security;

revoke all on public.publishers,public.stories,public.articles,public.story_articles,
  public.bookmarks,public.user_preferences,public.feedback from anon,authenticated;
grant select on public.publishers,public.stories,public.articles,public.story_articles to anon,authenticated;
grant select,insert,delete on public.bookmarks to authenticated;
grant select,insert,update on public.user_preferences to authenticated;
grant select,insert on public.feedback to authenticated;

create policy publishers_public_read on public.publishers for select to anon,authenticated using (true);
create policy stories_public_read on public.stories for select to anon,authenticated
  using (published_at is not null and published_at <= now() and retracted_at is null);
create policy articles_public_read on public.articles for select to anon,authenticated using (publish_allowed);
create policy links_public_read on public.story_articles for select to anon,authenticated using (
  same_event_verified
  and exists (select 1 from public.stories s where s.id=story_id and s.published_at is not null and s.published_at<=now() and s.retracted_at is null)
  and exists (select 1 from public.articles a where a.id=article_id and a.publish_allowed)
);
create policy bookmarks_owner_read on public.bookmarks for select to authenticated using ((select auth.uid())=user_id);
create policy bookmarks_owner_insert on public.bookmarks for insert to authenticated
  with check ((select auth.uid())=user_id and exists(select 1 from public.stories s where s.id=story_id));
create policy bookmarks_owner_delete on public.bookmarks for delete to authenticated using ((select auth.uid())=user_id);
create policy preferences_owner_read on public.user_preferences for select to authenticated using ((select auth.uid())=user_id);
create policy preferences_owner_insert on public.user_preferences for insert to authenticated with check ((select auth.uid())=user_id);
create policy preferences_owner_update on public.user_preferences for update to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy feedback_owner_read on public.feedback for select to authenticated using ((select auth.uid())=user_id);
create policy feedback_owner_insert on public.feedback for insert to authenticated
  with check ((select auth.uid())=user_id and exists(select 1 from public.stories s where s.id=story_id));

-- Private tables have no anon/authenticated access. Backend SQL worker access only.
-- Do not expose the private schema via PostgREST. Use a dedicated worker DB role;
-- validate RLS/bypass behavior before assigning privileges or applying migrations.
revoke all on all tables in schema private from public,anon,authenticated;
commit;
