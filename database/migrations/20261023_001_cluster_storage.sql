-- Execute once in a transaction. Adds only this worker's private batch tables.
-- No automatic publication; existing application tables are not modified.
create schema if not exists private;

create table private.prism_cluster_batches (
  batch_id text primary key check (batch_id ~ '^prism-batch-[0-9a-f]{64}$'),
  payload_sha256 text not null unique check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  namespace text not null check (namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$'),
  source_hashes jsonb not null check (jsonb_typeof(source_hashes)='object'),
  article_count integer not null check (article_count between 1 and 2000),
  group_count integer not null check (group_count between 1 and article_count),
  automatic_publication boolean not null default false check (automatic_publication=false),
  accuracy_measured boolean not null default false check (accuracy_measured=false),
  requires_human_review boolean not null default true check (requires_human_review=true),
  created_at timestamptz not null default now()
);

create table private.prism_cluster_articles (
  batch_id text not null references private.prism_cluster_batches(batch_id),
  article_id text not null check (char_length(article_id) between 1 and 512),
  canonical_url text not null,
  title text not null,
  publisher_name text not null,
  category text not null check (category in ('politics','economy','society','technology')),
  published_at timestamptz not null,
  raw_text text not null check (char_length(raw_text) between 1 and 2000000),
  body_sha256 text not null check (body_sha256=encode(sha256(convert_to(raw_text,'UTF8')),'hex')),
  content_hash text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  image_url text,
  rights jsonb not null check (rights @> '{"collect":"allowed","store":"allowed"}'::jsonb),
  record jsonb not null check (jsonb_typeof(record)='object' and not(record ? 'body')),
  primary key (batch_id,article_id),
  unique (batch_id,canonical_url)
);

create table private.prism_cluster_groups (
  batch_id text not null references private.prism_cluster_batches(batch_id),
  group_id text not null,
  representative_article_id text not null,
  category text not null check (category in ('politics','economy','society','technology')),
  article_count integer not null check (article_count between 1 and 2000),
  same_event_verified boolean not null default false check (same_event_verified=false),
  review jsonb not null check (jsonb_typeof(review)='object'),
  primary key (batch_id,group_id),
  foreign key (batch_id,representative_article_id) references private.prism_cluster_articles(batch_id,article_id)
);

create table private.prism_cluster_members (
  batch_id text not null,
  group_id text not null,
  article_id text not null,
  primary key (batch_id,group_id,article_id),
  unique (batch_id,article_id),
  foreign key (batch_id,group_id) references private.prism_cluster_groups(batch_id,group_id),
  foreign key (batch_id,article_id) references private.prism_cluster_articles(batch_id,article_id)
);

alter table private.prism_cluster_groups add constraint prism_cluster_representative_member
  foreign key (batch_id,group_id,representative_article_id)
  references private.prism_cluster_members(batch_id,group_id,article_id)
  deferrable initially deferred;

alter table private.prism_cluster_batches enable row level security;
alter table private.prism_cluster_articles enable row level security;
alter table private.prism_cluster_groups enable row level security;
alter table private.prism_cluster_members enable row level security;
revoke all on private.prism_cluster_batches,private.prism_cluster_articles,
  private.prism_cluster_groups,private.prism_cluster_members from public,anon,authenticated,service_role;
comment on table private.prism_cluster_batches is 'prism-cluster-storage/v1: immutable private worker batches; no automatic publishing';
comment on table private.prism_cluster_articles is 'Allowed source text and optional image URLs; backend DB role only';
