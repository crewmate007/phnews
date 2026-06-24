-- PHNews data platform schema (Phase 0)
-- 4 tables: runs -> topics -> (angles, source_examples)
-- Field shapes mirror the existing clusters_{date}.json produced by cluster_with_llm.

create extension if not exists "pgcrypto";

-- ============================================================
-- runs: one row per (region, run_date); overall state machine
-- ============================================================
create table if not exists runs (
  id                  uuid primary key default gen_random_uuid(),
  region              text not null check (region in ('ph','id')),
  run_date            date not null,
  status              text not null default 'pending'
                        check (status in ('pending','clustering','scoring','angles','done','failed')),
  total_entries       int,
  clustered_at        timestamptz,
  cluster_pipeline    text,
  target_group_range  int[],
  prompt_version      text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (region, run_date)
);

-- ============================================================
-- topics: one row per topic group; core unit + per-angle checkpoints
-- ============================================================
create table if not exists topics (
  id                   uuid primary key default gen_random_uuid(),
  run_id               uuid not null references runs(id) on delete cascade,
  region               text not null,
  run_date             date not null,
  broad_index          int not null,
  name                 text,
  name_zh              text,
  narrative            text,
  narrative_zh         text,
  topic_type           text,
  density              int,
  entry_ids            int[],
  market_hint          text,
  source_mix           jsonb,
  source_labels        text[],
  content_hash         text,
  "R" int, "R_reason" text,
  "S" int, "S_reason" text,
  "T" int, "T_reason" text,
  "U" int, "U_reason" text,
  "H" int, "H_reason" text,
  bdlt                 jsonb,
  bettable             boolean default false,
  suggested_question   text,
  suggested_question_zh text,
  resolution_source    text,
  disposition          text,
  why_users_bet        text,
  prob                 int,
  prob_reason_en       text,
  prob_reason_zh       text,
  serious_status       text not null default 'pending' check (serious_status in ('pending','done','failed')),
  reddit_status        text not null default 'pending' check (reddit_status in ('pending','done','failed')),
  tiktok_status        text not null default 'pending' check (tiktok_status in ('pending','done','failed')),
  prob_status          text not null default 'pending' check (prob_status in ('pending','done','failed')),
  resolved_outcome     text,
  resolved_at          timestamptz,
  resolution_note      text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (run_id, broad_index)
);

create index if not exists idx_topics_run on topics(run_id);
create index if not exists idx_topics_region_date on topics(region, run_date);
create index if not exists idx_topics_content_hash on topics(content_hash);

-- ============================================================
-- angles: reddit/tiktok angles + serious candidates (flattened arrays)
-- ============================================================
create table if not exists angles (
  id           uuid primary key default gen_random_uuid(),
  topic_id     uuid not null references topics(id) on delete cascade,
  angle_type   text not null check (angle_type in ('reddit','tiktok','serious_candidate')),
  position     int not null default 0,
  subtopic     text,
  question_en  text,
  question_zh  text,
  source       text,
  url          text,
  is_primary   boolean default false,
  scores       jsonb,
  created_at   timestamptz not null default now()
);

create index if not exists idx_angles_topic on angles(topic_id);
create index if not exists idx_angles_type on angles(topic_id, angle_type);

-- ============================================================
-- source_examples: one row per news source per topic
-- ============================================================
create table if not exists source_examples (
  id           uuid primary key default gen_random_uuid(),
  topic_id     uuid not null references topics(id) on delete cascade,
  position     int not null default 0,
  source       text,
  source_label text,
  section      text,
  title_en     text,
  title_zh     text,
  summary_en   text,
  summary_zh   text,
  link         text,
  rank_score   double precision,
  social_heat  text,
  uncertainty  text,
  created_at   timestamptz not null default now()
);

create index if not exists idx_source_examples_topic on source_examples(topic_id);

-- updated_at touch trigger
create or replace function touch_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

create trigger trg_runs_touch before update on runs
  for each row execute function touch_updated_at();
create trigger trg_topics_touch before update on topics
  for each row execute function touch_updated_at();

-- RLS lockdown: enable with no policies. anon/public key can touch nothing;
-- the service_role key used by CI bypasses RLS. Static site never queries directly.
alter table runs            enable row level security;
alter table topics          enable row level security;
alter table angles          enable row level security;
alter table source_examples enable row level security;;
