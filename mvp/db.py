"""Supabase persistence layer for the Daily News pipeline.

Phase 0/1: thin write-only mirror. Everything is a NO-OP when the
SUPABASE_URL / SUPABASE_SERVICE_KEY env vars are absent, so local dev and
any environment without credentials keeps working exactly as before — only
CI (which has the secrets) actually writes to Supabase.

The single public entry point is `write_run(result, region, run_date)`, which
maps the dict returned by cluster.cluster_with_llm() into the Supabase mirror:
runs -> source_entries -> topics -> (topic_source_entries, angles,
source_examples).

Design choices:
- Never raises to the caller. Any failure is logged to stderr and swallowed,
  so a Supabase outage can never block the JSON/HTML pipeline.
- Idempotent per (region, run_date): re-running a day deletes that run's rows
  and rewrites them, so repeated runs converge instead of duplicating.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional


_SOURCE_ENTRY_CHUNK = 500
_DOTENV_CACHE: Optional[Dict[str, str]] = None


def _env(name: str) -> Optional[str]:
    v = os.environ.get(name)
    if v:
        return v.strip()
    return _dotenv_values().get(name)


def _dotenv_values() -> Dict[str, str]:
    """Read repo-root .env once as a local fallback for manual runs."""
    global _DOTENV_CACHE
    if _DOTENV_CACHE is not None:
        return _DOTENV_CACHE

    values: Dict[str, str] = {}
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if name.startswith("export "):
                name = name.removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[name] = value
    _DOTENV_CACHE = values
    return values


def get_client():
    """Return a Supabase client, or None if credentials are absent.

    Reads SUPABASE_URL + SUPABASE_SERVICE_KEY from shell env, then repo .env.
    Returns None (no-op mode) when either is missing or the supabase package
    isn't installed.
    """
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return None
    try:
        from supabase import create_client
    except ImportError:
        print("[WARN] supabase package not installed; DB writes skipped", file=sys.stderr)
        return None
    try:
        return create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] supabase client init failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def write_run(result: Dict, region, run_date: str) -> bool:
    """Mirror one cluster_with_llm() result into Supabase. Returns True on
    success, False on no-op or failure. Never raises.

    `region` may be a slug string ("ph"/"id") or a RegionConfig object with a
    .slug attribute -- callers in run_daily.py pass it in either form depending
    on code path, so coerce defensively here.
    """
    region_slug = getattr(region, "slug", region)
    # Non-secret shape diagnostics: helps catch a malformed URL/key secret
    # (e.g. wrong key type, truncation) without ever printing the values.
    url = _env("SUPABASE_URL") or ""
    key = _env("SUPABASE_SERVICE_KEY") or ""
    print(
        f"[INFO] Supabase cfg: url_len={len(url)} "
        f"key_len={len(key)} key_dots={key.count('.')}",
        file=sys.stderr,
    )
    client = get_client()
    if client is None:
        print("[WARN] Supabase: no client (missing creds)", file=sys.stderr)
        return False
    try:
        _write_run_impl(client, result, region_slug, run_date)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Supabase write_run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False


# ------------------------------------------------------------------ internals


def _write_run_impl(client, result: Dict, region: str, run_date: str) -> None:
    groups = result.get("groups", []) or []

    # 1) Upsert the run row (idempotent on region+run_date).
    run_payload = {
        "region": region,
        "run_date": run_date,
        "status": "done",
        "total_entries": result.get("total_entries"),
        "clustered_at": result.get("clustered_at"),
        "cluster_pipeline": result.get("cluster_pipeline"),
        "target_group_range": result.get("target_group_range"),
    }
    run_row = (
        client.table("runs")
        .upsert(run_payload, on_conflict="region,run_date")
        .execute()
    )
    run_id = run_row.data[0]["id"]

    # 2) Clear prior child rows for this run so re-runs converge (topics cascade
    #    to angles + source_examples via FK ON DELETE CASCADE).
    client.table("topics").delete().eq("run_id", run_id).execute()

    # 3) Store the raw-ish SourceIntel inputs. This is optional until the new
    #    tables are migrated in Supabase; if absent, the old 4-table mirror still
    #    continues.
    source_entry_ids = _try_replace_source_entries(
        client, run_id, result, region, run_date
    )

    # 4) Insert topics, then their joins, angles + source_examples.
    for idx, g in enumerate(groups):
        topic_id = _insert_topic(client, run_id, region, run_date, idx, g)
        _try_insert_topic_source_entries(client, topic_id, g, source_entry_ids)
        _insert_angles(client, topic_id, g)
        _insert_source_examples(client, topic_id, g)


def _score(g: Dict, key: str):
    v = g.get(key)
    return v if isinstance(v, int) else None


def _insert_topic(client, run_id, region, run_date, broad_index, g: Dict) -> str:
    serious_done = bool(g.get("suggested_question") or g.get("serious_candidates"))
    payload = {
        "run_id": run_id,
        "region": region,
        "run_date": run_date,
        "broad_index": broad_index,
        "name": g.get("name"),
        "name_zh": g.get("name_zh"),
        "narrative": g.get("narrative"),
        "narrative_zh": g.get("narrative_zh"),
        "topic_type": g.get("topic_type"),
        "density": g.get("density"),
        "entry_ids": g.get("entry_ids"),
        "market_hint": g.get("market_hint"),
        "source_mix": g.get("source_mix"),
        "source_labels": g.get("source_labels"),
        "R": _score(g, "R"), "R_reason": g.get("R_reason"),
        "S": _score(g, "S"), "S_reason": g.get("S_reason"),
        "T": _score(g, "T"), "T_reason": g.get("T_reason"),
        "U": _score(g, "U"), "U_reason": g.get("U_reason"),
        "H": _score(g, "H"), "H_reason": g.get("H_reason"),
        "contract_quality": g.get("contract_quality"),
        "volume_potential": g.get("volume_potential"),
        "volume_score": _score(g, "volume_score"),
        "scoring_version": g.get("scoring_version"),
        "bdlt": g.get("BDLT"),
        "yes_buyer": g.get("yes_buyer"),
        "no_buyer": g.get("no_buyer"),
        "bettable": bool(g.get("bettable")),
        "suggested_question": g.get("suggested_question"),
        "suggested_question_zh": g.get("suggested_question_zh"),
        "resolution_source": g.get("resolution_source"),
        "disposition": g.get("disposition_hint"),
        "why_users_bet": g.get("why_users_bet"),
        "prob": _score(g, "prob"),
        "prob_reason_en": g.get("prob_reason_en"),
        "prob_reason_zh": g.get("prob_reason_zh"),
        "serious_status": "done" if serious_done else "pending",
        "reddit_status": "done" if g.get("reddit_angles") else "pending",
        "tiktok_status": "done" if g.get("tiktok_angles") else "pending",
        "prob_status": "done" if g.get("prob") is not None else "pending",
    }
    row = client.table("topics").insert(payload).execute()
    return row.data[0]["id"]


def _try_replace_source_entries(client, run_id, result: Dict, region: str,
                                run_date: str) -> Dict[int, str]:
    entries = result.get("entries") or []
    if not entries:
        return {}

    try:
        client.table("source_entries").delete().eq("run_id", run_id).execute()
        rows = [
            _source_entry_payload(run_id, region, run_date, entry)
            for entry in entries
            if isinstance(entry.get("id"), int)
        ]
        entry_ids: Dict[int, str] = {}
        for chunk in _chunks(rows, _SOURCE_ENTRY_CHUNK):
            result = client.table("source_entries").insert(chunk).execute()
            for row in result.data or []:
                if isinstance(row.get("entry_id"), int) and row.get("id"):
                    entry_ids[row["entry_id"]] = row["id"]
        if rows and not entry_ids:
            # Some PostgREST clients/environments can use return=minimal for
            # inserts. Fetch ids back so topic_source_entries still links the
            # raw inputs to topics.
            result = (
                client.table("source_entries")
                .select("id,entry_id")
                .eq("run_id", run_id)
                .execute()
            )
            for row in result.data or []:
                if isinstance(row.get("entry_id"), int) and row.get("id"):
                    entry_ids[row["entry_id"]] = row["id"]
        return entry_ids
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WARN] Supabase source_entries skipped: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return {}


def _source_entry_payload(run_id, region: str, run_date: str, entry: Dict) -> Dict:
    return {
        "run_id": run_id,
        "region": region,
        "run_date": run_date,
        "entry_id": entry.get("id"),
        "source": entry.get("source"),
        "source_label": entry.get("source_label"),
        "source_section": entry.get("section"),
        "title_en": entry.get("title_en"),
        "title_zh": entry.get("title_zh"),
        "summary_en": entry.get("summary_en"),
        "summary_zh": entry.get("summary_zh"),
        "link": entry.get("link"),
        "rank_score": entry.get("rank_score"),
        "rank_reason": entry.get("rank_reason"),
        "social_heat": entry.get("social_heat"),
        "uncertainty": entry.get("uncertainty"),
        "observed_at": entry.get("observed_at"),
        "source_count": entry.get("source_count"),
        "article_count": entry.get("article_count"),
        "entities": _as_list(entry.get("entities")),
        "keywords": _as_list(entry.get("keywords")),
        "claims_en": _as_list(entry.get("claims_en")),
        "claims_zh": _as_list(entry.get("claims_zh")),
        "evidence_urls": _as_list(entry.get("evidence_urls")),
        "prediction_angle": entry.get("prediction_angle"),
        "raw": entry.get("raw") if isinstance(entry.get("raw"), dict) else entry,
    }


def _try_insert_topic_source_entries(client, topic_id, g: Dict,
                                     source_entry_ids: Dict[int, str]) -> None:
    if not source_entry_ids:
        return

    rows = []
    example_ids = {
        item.get("id")
        for item in (g.get("source_examples") or [])
        if isinstance(item.get("id"), int)
    }
    for pos, entry_id in enumerate(g.get("entry_ids") or []):
        source_entry_id = source_entry_ids.get(entry_id)
        if not source_entry_id:
            continue
        rows.append({
            "topic_id": topic_id,
            "source_entry_id": source_entry_id,
            "entry_id": entry_id,
            "position": pos,
            "is_example": entry_id in example_ids,
        })
    if not rows:
        return

    try:
        client.table("topic_source_entries").insert(rows).execute()
    except Exception as exc:  # noqa: BLE001
        print(
            f"[WARN] Supabase topic_source_entries skipped: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def _chunks(rows: List[Dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _insert_angles(client, topic_id, g: Dict) -> None:
    rows: List[Dict] = []
    # serious candidates (with scores)
    for pos, c in enumerate(g.get("serious_candidates") or []):
        rows.append({
            "topic_id": topic_id,
            "angle_type": "serious_candidate",
            "position": pos,
            "subtopic": None,
            "question_en": c.get("suggested_question"),
            "question_zh": c.get("suggested_question_zh"),
            "source": c.get("resolution_source"),
            "url": None,
            "is_primary": c.get("suggested_question") == g.get("suggested_question"),
            "scores": {
                k: c.get(k)
                for k in (
                    "R", "S", "T", "U", "H", "contract_quality",
                    "volume_potential", "volume_score", "scoring_version", "BDLT",
                )
                if k in c
            },
        })
    # reddit + tiktok angle arrays
    for angle_type in ("reddit", "tiktok"):
        for pos, a in enumerate(g.get(f"{angle_type}_angles") or []):
            rows.append({
                "topic_id": topic_id,
                "angle_type": angle_type,
                "position": pos,
                "subtopic": a.get("subtopic"),
                "question_en": a.get("question_en"),
                "question_zh": a.get("question_zh"),
                "source": a.get("source"),
                "url": a.get("url"),
                "is_primary": pos == 0,
                "scores": None,
            })
    if rows:
        client.table("angles").insert(rows).execute()


def _insert_source_examples(client, topic_id, g: Dict) -> None:
    rows: List[Dict] = []
    for pos, se in enumerate(g.get("source_examples") or []):
        rows.append({
            "topic_id": topic_id,
            "position": pos,
            "source": se.get("source"),
            "source_label": se.get("source_label"),
            "section": se.get("section"),
            "title_en": se.get("title_en"),
            "title_zh": se.get("title_zh"),
            "summary_en": se.get("summary_en"),
            "summary_zh": se.get("summary_zh"),
            "link": se.get("link"),
            "rank_score": se.get("rank_score"),
            "social_heat": se.get("social_heat"),
            "uncertainty": se.get("uncertainty"),
        })
    if rows:
        client.table("source_examples").insert(rows).execute()
