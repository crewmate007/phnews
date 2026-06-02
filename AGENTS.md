# AGENTS.md — Daily News

Guidance for Claude Code / Codex agents working in this repo. Read this first.

## What this project is

A daily pipeline that turns collected news hotspots into bilingual (zh/en)
prediction-market topic cards for the Philippines (`ph`), then renders a 100%
static site. Runs unattended via GitHub Actions; output is
committed to `docs/` and auto-deployed by Vercel + GitHub Pages.

## Architecture (data flow)

```
SourceIntel repo (separate)  →  hotspots_ph_{date}.json
   │  (checked out as ../SourceIntel in CI)
   ▼
mvp/run_daily.py --cluster --region ph
   ├─ source_intel_bridge.py   load + normalize hotspots → "clusters"
   ├─ cluster.cluster_with_llm()   the core orchestration:
   │     1. BROAD clustering   1 Gemini call: ~120 hotspots → ~65 topic groups
   │     2. attach group["clusters"]  (full cluster dicts, needed by angles)
   │     3. PHASE_1 angles (serious)  scoring → drives TOP/candidate/watch/drop
   │     4. housekeeping  fill scores, source_mix, BDLT
   │     5. region relevance guard
   │     6. PHASE_2 angles (reddit, tiktok)
   ├─ save_cluster_result()  → mvp/reports/clusters_{date}.json  (source of truth)
   ├─ db.write_run()         → Supabase mirror (no-op without creds; never raises)
   ├─ scripts/gen_html.py    → mvp/reports/cluster_{date}.html (data inlined)
   ├─ scripts/add_probabilities.py  → patches HTML with YES probabilities
   └─ scripts/publish_site.py → copies into docs/{,id/}
   ▼
scripts/validate_generated_pages.py  (gate: fails build on bad output)
   ▼
git commit docs/ → push → Vercel + GitHub Pages auto-deploy
```

Frontend is **fully static**: all data is inlined into each HTML page as a
`const groups = [...]` JS blob. There is NO runtime API; the browser never
queries Supabase.

### Angle library — `mvp/angles/`

Each market-question "angle" is a plugin with a uniform contract:
`generate(self, groups, client, model, region_cfg) -> stats_dict`. It mutates
group dicts **in place** and returns `{"attached", "total", ...}`.

- `serious.py` — institutional analyst; multi-candidate scoring (RSTUH + BDLT),
  picks best candidate, keeps the rest in `serious_candidates`. Drives disposition.
- `reddit.py` — dry-wit lateral angles (1–3 per group, `reddit_angles[]`).
- `tiktok.py` — viral clickbait-hook + real resolvable question (`tiktok_angles[]`).
- `base.py` — shared `generate_content_with_retry` (retries network drops too),
  `parse_json_response` (tolerates code fences + trailing commas), `safe_url`
  (resolver URL allowlist), `clip`.
- `__init__.py` — `PHASE_1_ANGLES` (serious) + `PHASE_2_ANGLES` (reddit, tiktok).

To add an angle: drop a new file with the `generate()` contract, register it in
`__init__.py`. For UI, add a `.{name}-box` CSS rule + render line in `gen_html.py`.

### Supabase (data platform, in progress)

`mvp/db.py` mirrors each run into Supabase: `runs → source_entries → topics →
(topic_source_entries, angles, source_examples)`. Currently **dual-write only**
— JSON stays source of truth. RLS is on with no policies (anon blocked; CI uses
the `service_role` key which bypasses RLS). `topics` has per-angle checkpoint
columns (`serious_status` / `reddit_status` / `tiktok_status` / `prob_status`).

## Build / run commands

```bash
pip install -r requirements-dev.txt          # deps + pytest

# Full PH pipeline (needs GEMINI_API_KEY; SourceIntel data in ../SourceIntel)
python mvp/run_daily.py --cluster --region ph --source-intel-dir ../SourceIntel

# Re-render HTML from existing clusters JSON (NO LLM, safe to run anytime)
python scripts/gen_html.py 2026-05-29 --region ph
python scripts/publish_site.py 2026-05-29 --region ph

# Validate generated pages (the CI gate)
python scripts/validate_generated_pages.py --date 2026-05-29
```

Regenerating HTML for a date you have JSON for is cheap and LLM-free — prefer it
when iterating on `gen_html.py` / CSS. Backfill all dates by looping over
`mvp/reports/clusters_*.json`.

## Testing

```bash
python -m pytest            # full suite (offline, deterministic)
python -m pytest tests/test_pipeline.py -q
```

- Tests are **fully offline**: `tests/conftest.py` installs a fake `google.genai`
  so `cluster_with_llm` runs without network. Override canned LLM output per
  prompt-kind via the `fake_gemini` fixture (`state["overrides"]["serious"]`, etc).
- `.github/workflows/ci.yml` runs pytest on every push/PR — keep it green.
- Add a test for any pipeline/angle/db change. The 2026-05-29 TOP=0 incident
  shipped silently *because there were no tests*; that's why they exist now.

## Coding conventions

- Python 3.11 (CI) / 3.13 (local dev). Stdlib + the 4 deps in `requirements.txt`.
- `mvp/` and `scripts/` are imported as **top-level modules** (e.g. `import db`,
  `import cluster`), not as packages — `sys.path` is set up by callers/conftest.
- LLM calls go through `angles/base.py` helpers — never call the SDK raw; you'd
  lose the network-retry + tolerant-JSON parsing.
- Angles mutate group dicts in place and return stats; do not change this contract.
- Bilingual everywhere: zh + en fields, `g.x_zh || g.x_en` fallback in the
  renderer; UI labels via the `i18n` dict + `data-zh`/`data-en` attributes.
- Resolver URLs MUST pass `safe_url`'s allowlist; unverified URLs degrade to
  plain-text source labels (never render a guessed link).
- Commits: end the message with
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
  Author identity used in this repo: `Kumu_SZ <kumu_sz@Kumu-SZtekiMacBook-Pro.local>`.

## Important constraints

- **No "all-or-nothing" LLM calls.** Angle generation is batched (`_run_angles`
  in `cluster.py`, ~10 groups/batch, failed batches retried). A transient error
  must never wipe a whole region. Broad clustering stays a single call.
- **Angle failures must not break the build.** Each angle is wrapped in
  try/except; the serious angle dying must still produce a (degraded) page.
- **The validator is the safety net.** `validate_generated_pages.py` FAILS the
  build if a region has ≥20 groups but 0 bettable (the TOP=0 fingerprint), or
  total_entries ≠ 120, or no Grok/X source. Don't weaken these without reason.
- **Static site only.** Do not introduce a runtime backend / dynamic frontend.
  Data is inlined at build time. Supabase is a mirror, not a live data source.
- **Secrets live in GitHub Actions**, not in files. Pipeline needs
  `GEMINI_API_KEY`, `XAI_API_KEY`, `SOURCE_INTEL_REPO_TOKEN`, `SUPABASE_URL`,
  `SUPABASE_SERVICE_ROLE_KEY`. `db.py` no-ops cleanly when Supabase creds absent.
- **Never reproduce source-article text at length.** Cards summarize; titles are
  shown but full article bodies are not stored or rendered.
- **CSS grid + long text:** wrapping needs `min-width: 0` on every nested grid
  level (`.card`, `.source-list`, `.source-item`, `.source-title`) — a known trap
  that caused repeated title-truncation bugs.

## Schedule & deploy

- Cron: `0 23 * * *` UTC = **07:00 Asia/Manila** daily (`.github/workflows/daily-news.yml`).
  The workflow is PH-only: it collects SourceIntel PH hotspots, generates PHNews,
  validates PH output, and commits only PH `docs/` + `mvp/reports/` artifacts.
  Also `workflow_dispatch` for manual runs.
- Concurrency group serializes runs (no cancel-in-progress).
- Push to `main` → Vercel Production + GitHub Pages deploy automatically.
- Public URL: https://crewmate007.github.io/phnews/ (Vercel may be SSO-gated).

## Key files quick map

| Path | Role |
|---|---|
| `mvp/run_daily.py` | entry point / orchestration |
| `mvp/cluster.py` | broad clustering + `_run_angles` batching + `cluster_with_llm` |
| `mvp/angles/*.py` | angle plugins (serious / reddit / tiktok / base) |
| `mvp/db.py` | Supabase dual-write mirror |
| `scripts/gen_html.py` | static HTML renderer (data inlined) |
| `scripts/validate_generated_pages.py` | CI quality gate |
| `04_topic_schema_v1.4.md` | the topic data contract (read for field semantics) |
| `tests/conftest.py` | fake-Gemini fixture, offline test harness |
