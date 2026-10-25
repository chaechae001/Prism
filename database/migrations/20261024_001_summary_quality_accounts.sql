create table private.prism_editorial_summaries (
  id uuid primary key default gen_random_uuid(),
  namespace text not null,
  batch_id text not null references private.prism_cluster_batches(batch_id),
  group_id text not null,
  input_hash text not null check (input_hash ~ '^[0-9a-f]{64}$'),
  model_version text not null,
  prompt_version text not null,
  review_status text not null default 'pending' check (review_status in ('pending','approved','rejected')),
  output jsonb not null check (jsonb_typeof(output)='object'),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  unique(namespace,group_id,input_hash,model_version,prompt_version)
);
create index prism_editorial_active on private.prism_editorial_summaries(namespace,batch_id,group_id,review_status);

create table private.prism_reader_bookmarks (
  user_id uuid not null references auth.users(id) on delete cascade,
  story_id text not null check (char_length(story_id) between 1 and 100),
  created_at timestamptz not null default now(),
  primary key(user_id,story_id)
);
create table private.prism_reader_comments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  story_id text not null,
  text text not null check(char_length(text) between 1 and 1000),
  created_at timestamptz not null default now()
);
create index prism_reader_comments_owner on private.prism_reader_comments(user_id,created_at);
create table private.prism_reader_threads (
  user_id uuid not null references auth.users(id) on delete cascade,
  story_id text not null,
  title text not null,
  category text not null check(category in ('politics','economy','society','technology')),
  updated_at timestamptz not null default now(),
  primary key(user_id,story_id)
);
create table private.prism_reader_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  story_id text not null,
  role text not null check(role in ('user','assistant')),
  text text not null check(char_length(text) between 1 and 10000),
  article_ids jsonb not null default '[]',
  model text,
  created_at timestamptz not null default now(),
  foreign key(user_id,story_id) references private.prism_reader_threads(user_id,story_id) on delete cascade
);
create index prism_reader_messages_owner on private.prism_reader_messages(user_id,story_id,created_at);
create table private.prism_reader_usage (
  user_id uuid not null references auth.users(id) on delete cascade,
  bucket timestamptz not null,
  requests integer not null check(requests>=0),
  primary key(user_id,bucket)
);

alter table private.prism_editorial_summaries enable row level security;
alter table private.prism_reader_bookmarks enable row level security;
alter table private.prism_reader_comments enable row level security;
alter table private.prism_reader_threads enable row level security;
alter table private.prism_reader_messages enable row level security;
alter table private.prism_reader_usage enable row level security;
revoke all on private.prism_editorial_summaries,private.prism_reader_bookmarks,
  private.prism_reader_comments,private.prism_reader_threads,private.prism_reader_messages,
  private.prism_reader_usage from public,anon,authenticated,service_role;

create policy prism_bookmarks_owner on private.prism_reader_bookmarks to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy prism_comments_owner on private.prism_reader_comments to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy prism_threads_owner on private.prism_reader_threads to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
create policy prism_messages_owner on private.prism_reader_messages to authenticated
  using ((select auth.uid())=user_id) with check ((select auth.uid())=user_id);
comment on table private.prism_editorial_summaries is 'prism-editorial/v1: source-bound reviewed cluster summaries';
comment on table private.prism_reader_bookmarks is 'prism-reader/v1: owner-scoped server storage; no direct browser grants';
