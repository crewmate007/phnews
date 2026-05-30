create extension if not exists pgcrypto;

create table if not exists public.source_entries (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.runs(id) on delete cascade,
  region text not null,
  run_date date not null,
  entry_id integer not null,
  source text,
  source_label text,
  source_section text,
  title_en text,
  title_zh text,
  summary_en text,
  summary_zh text,
  link text,
  rank_score double precision,
  rank_reason text,
  social_heat text,
  uncertainty text,
  observed_at text,
  source_count integer,
  article_count integer,
  entities jsonb not null default '[]'::jsonb,
  keywords jsonb not null default '[]'::jsonb,
  claims_en jsonb not null default '[]'::jsonb,
  claims_zh jsonb not null default '[]'::jsonb,
  evidence_urls jsonb not null default '[]'::jsonb,
  prediction_angle text,
  raw jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, entry_id)
);

create table if not exists public.topic_source_entries (
  topic_id uuid not null references public.topics(id) on delete cascade,
  source_entry_id uuid not null references public.source_entries(id) on delete cascade,
  entry_id integer not null,
  position integer not null,
  is_example boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (topic_id, source_entry_id)
);

create index if not exists source_entries_run_source_idx
  on public.source_entries (run_id, source);

create index if not exists source_entries_region_date_source_idx
  on public.source_entries (region, run_date, source);

create index if not exists topic_source_entries_source_entry_idx
  on public.topic_source_entries (source_entry_id);

alter table public.source_entries enable row level security;
alter table public.topic_source_entries enable row level security;
