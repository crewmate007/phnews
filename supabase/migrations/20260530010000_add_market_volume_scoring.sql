alter table public.topics
  add column if not exists contract_quality jsonb,
  add column if not exists volume_potential jsonb,
  add column if not exists volume_score integer,
  add column if not exists scoring_version text,
  add column if not exists yes_buyer text,
  add column if not exists no_buyer text;

create index if not exists idx_topics_volume_score
  on public.topics (region, run_date, volume_score desc);
