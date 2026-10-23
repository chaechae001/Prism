-- Add only worker-owned inbox revisions and a namespace preview pointer.
create table private.prism_ingest_articles (
  namespace text not null check (namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$'),
  article_id text not null,
  revision_sha256 text not null check (revision_sha256 ~ '^[0-9a-f]{64}$'),
  canonical_url text not null,
  source_id text not null,
  published_at timestamptz not null,
  raw_text text not null check (char_length(raw_text) between 1 and 2000000),
  body_sha256 text not null check (body_sha256=encode(sha256(convert_to(raw_text,'UTF8')),'hex')),
  record jsonb not null check (jsonb_typeof(record)='object' and not(record ? 'body')),
  first_seen_at timestamptz not null,
  last_seen_at timestamptz not null check (last_seen_at>=first_seen_at),
  primary key (namespace,article_id,revision_sha256),
  check (record->'rights' @> '{"collect":"allowed","store":"allowed"}'::jsonb)
);
create index prism_ingest_window on private.prism_ingest_articles(namespace,published_at desc);
create table private.prism_cluster_heads (
  namespace text primary key check (namespace ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$'),
  batch_id text not null references private.prism_cluster_batches(batch_id),
  input_sha256 text not null check (input_sha256 ~ '^[0-9a-f]{64}$'),
  analyzed_at timestamptz not null
);
alter table private.prism_ingest_articles enable row level security;
alter table private.prism_cluster_heads enable row level security;
revoke all on private.prism_ingest_articles,private.prism_cluster_heads from public,anon,authenticated,service_role;
comment on table private.prism_ingest_articles is 'prism-scheduled-news/v1: private source revisions and observation times';
comment on table private.prism_cluster_heads is 'prism-scheduled-news/v1: current completed candidate batch per namespace';
