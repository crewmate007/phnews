-- noise_count is the one top-level field gen_html.py reads that wasn't being
-- mirrored. Needed so the DB->JSON exporter (P2b) can reproduce the
-- "noise filtered" stat faithfully.
alter table runs add column if not exists noise_count int;;
