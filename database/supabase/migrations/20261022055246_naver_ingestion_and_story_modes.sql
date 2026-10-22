-- Additive pipeline tables. Does not alter existing RSS, public articles/stories or user tables.
-- Generated with Supabase CLI; verified separately before remote application.
begin;
create schema if not exists private;
create table private.news_v2_articles (
 id uuid primary key, canonical_url text not null unique, title text not null,
 category text not null check(category in ('politics','economy','society','technology')),
 analysis_signature text not null, record jsonb not null check(jsonb_typeof(record)='object'),
 publisher_id text, publisher_group_id text,
 provider_published_at timestamptz, publisher_published_at timestamptz,
 current_body_id uuid, is_demo boolean not null default false,
 first_seen_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table private.news_v2_observations (
 id bigint generated always as identity primary key,
 article_id uuid not null references private.news_v2_articles(id),
 provider text not null, query text not null, payload jsonb not null,
 payload_hash text not null, first_seen_at timestamptz not null default now(),
 last_seen_at timestamptz not null default now(),
 unique(article_id,provider,query,payload_hash)
);
create table private.news_v2_bodies (
 id uuid primary key default gen_random_uuid(),
 article_id uuid not null references private.news_v2_articles(id),
 text text not null check(char_length(text) between 1 and 2000000),
 content_hash text not null check(length(content_hash)=64),
 provenance_hash text not null check(length(provenance_hash)=64),
 content_kind text not null check(content_kind in ('full_text','excerpt')),
 provenance jsonb not null, rights jsonb not null,
 acquired_at timestamptz not null, created_at timestamptz not null default now(),
 unique(article_id,content_hash,provenance_hash), unique(article_id,id),
 check(rights @> '{"store":true}'::jsonb)
);
alter table private.news_v2_articles add constraint news_v2_current_body_fk
 foreign key(id,current_body_id) references private.news_v2_bodies(article_id,id);
create table private.news_v2_runs (
 id uuid primary key, input_hash text not null, excluded jsonb not null,
 status text not null default 'exported' check(status in ('exported','imported')),
 created_at timestamptz not null default now()
);
create table private.news_v2_run_inputs (
 run_id uuid not null references private.news_v2_runs(id),
 article_id uuid not null references private.news_v2_articles(id),
 body_id uuid not null, article_signature text not null, article_snapshot jsonb not null,
 primary key(run_id,article_id),
 foreign key(article_id,body_id) references private.news_v2_bodies(article_id,id)
);
create table private.news_v2_events (
 id uuid primary key, event_key text not null unique,
 current_run_id uuid not null references private.news_v2_runs(id),
 same_event_verified boolean not null default false, category text,
 cluster_model_version text not null, created_at timestamptz not null default now()
);
create table private.news_v2_members (
 event_id uuid not null references private.news_v2_events(id),
 run_id uuid not null references private.news_v2_runs(id),
 article_id uuid not null, primary key(event_id,run_id,article_id),
 foreign key(run_id,article_id) references private.news_v2_run_inputs(run_id,article_id)
);
create table private.news_v2_analyses (
 id uuid primary key default gen_random_uuid(), event_id uuid not null references private.news_v2_events(id),
 run_id uuid not null references private.news_v2_runs(id),
 mode text not null check(mode in ('summary','five_w','easy','sentiment')),
 status text not null check(status in ('ready','failed','insufficient_sources')),
 payload jsonb, payload_hash text not null,
 model_version text not null, prompt_version text not null,
 review_status text not null default 'pending' check(review_status in ('pending','approved','rejected')),
 created_at timestamptz not null default now(),
 unique(event_id,run_id,mode,model_version,prompt_version,payload_hash),
 check((status='ready' and payload is not null) or (status<>'ready' and payload is null))
);
create table private.news_v2_publications (
 event_id uuid primary key references private.news_v2_events(id),
 run_id uuid not null references private.news_v2_runs(id),
 analysis_id uuid not null references private.news_v2_analyses(id),
 event_date date not null, category text not null,
 story jsonb not null, published_at timestamptz not null default now(),
 retracted_at timestamptz
);
create index news_v2_observations_article_idx on private.news_v2_observations(article_id);
create index news_v2_bodies_article_idx on private.news_v2_bodies(article_id,created_at desc);
create index news_v2_inputs_body_idx on private.news_v2_run_inputs(body_id);
create index news_v2_members_input_idx on private.news_v2_members(run_id,article_id);
create index news_v2_analyses_read_idx on private.news_v2_analyses(event_id,run_id,mode,created_at desc) where review_status='approved';
create index news_v2_publications_date_idx on private.news_v2_publications(event_date desc,event_id) where retracted_at is null;
create index news_v2_publications_category_date_idx on private.news_v2_publications(category,event_date desc,event_id) where retracted_at is null;
alter table private.news_v2_articles enable row level security;
alter table private.news_v2_observations enable row level security;
alter table private.news_v2_bodies enable row level security;
alter table private.news_v2_runs enable row level security;
alter table private.news_v2_run_inputs enable row level security;
alter table private.news_v2_events enable row level security;
alter table private.news_v2_members enable row level security;
alter table private.news_v2_analyses enable row level security;
alter table private.news_v2_publications enable row level security;
revoke all on private.news_v2_articles,private.news_v2_observations,private.news_v2_bodies,
 private.news_v2_runs,private.news_v2_run_inputs,private.news_v2_events,private.news_v2_members,
 private.news_v2_analyses,private.news_v2_publications from public,anon,authenticated;
grant usage on schema private to service_role;
grant select,insert,update on private.news_v2_articles,private.news_v2_observations,private.news_v2_bodies,
 private.news_v2_runs,private.news_v2_run_inputs,private.news_v2_events,private.news_v2_members,
 private.news_v2_analyses,private.news_v2_publications to service_role;
grant usage,select on sequence private.news_v2_observations_id_seq to service_role;
comment on table private.news_v2_bodies is 'Private licensed text revisions. Never expose through the browser Data API.';
comment on table private.news_v2_publications is 'Approved v1-compatible read projection; FastAPI serves it, not direct anonymous database access.';
commit;
