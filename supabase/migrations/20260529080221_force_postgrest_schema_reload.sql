-- DDL triggers Supabase's automatic PostgREST schema-cache reload, which
-- fixes the PGRST205 "Could not find the table 'public.runs' in the schema
-- cache" error the dual-write hit (tables were created via MCP migration but
-- the REST layer's cache hadn't picked them up).
comment on table runs is 'PHNews daily run, one per (region, run_date)';
comment on table topics is 'One topic group per row; per-angle checkpoints';
comment on table angles is 'reddit/tiktok angles + serious candidates';
comment on table source_examples is 'News source examples per topic';
notify pgrst, 'reload schema';;
