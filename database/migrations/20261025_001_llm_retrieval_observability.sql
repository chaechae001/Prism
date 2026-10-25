create table private.prism_rag_chunks (
  batch_id text not null,
  article_id text not null,
  model_id text not null,
  body_sha256 text not null check (body_sha256 ~ '^[0-9a-f]{64}$'),
  chunk_id text not null check (chunk_id ~ '^[0-9a-f]{64}$'),
  start_offset integer not null check(start_offset>=0),
  end_offset integer not null check(end_offset>start_offset),
  embedding real[] not null check(cardinality(embedding)=384),
  created_at timestamptz not null default now(),
  primary key(batch_id,article_id,model_id,chunk_id),
  foreign key(batch_id,article_id) references private.prism_cluster_articles(batch_id,article_id) on delete cascade
);
create index prism_rag_lookup on private.prism_rag_chunks(batch_id,model_id,article_id,body_sha256);
create table private.prism_llm_runs (
  id uuid primary key,
  task text not null check(task in ('chat','summary')),
  provider text not null,
  model text not null,
  prompt_version text not null,
  input_hash text not null check(input_hash ~ '^[0-9a-f]{64}$'),
  status text not null check(status in ('ok','error')),
  error_type text,
  elapsed_ms integer not null check(elapsed_ms>=0),
  input_tokens integer check(input_tokens>=0),
  output_tokens integer check(output_tokens>=0),
  estimated_cost_usd numeric(16,8) check(estimated_cost_usd>=0),
  created_at timestamptz not null default now()
);
create index prism_llm_recent on private.prism_llm_runs(created_at desc);
alter table private.prism_rag_chunks enable row level security;
alter table private.prism_llm_runs enable row level security;
revoke all on private.prism_rag_chunks,private.prism_llm_runs from public,anon,authenticated,service_role;
comment on table private.prism_rag_chunks is 'prism-ai-storage/v1';
comment on table private.prism_llm_runs is 'prism-ai-storage/v1';
