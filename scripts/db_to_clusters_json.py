"""Export Supabase rows back into a clusters_{date}.json file (P2b).

This is the read side of the Supabase migration. db.py (write side) mirrors a
cluster_with_llm() result into 4 tables; this script reconstructs the exact
`clusters_{date}.json` shape that gen_html.py consumes, so Supabase can become
the source of truth while gen_html / publish_site / the static site stay
untouched.

The reconstruction is a clean inverse of db.py's _insert_* mapping:
  runs row            -> top-level (region, total_entries, clustered_at, ...)
  topics rows         -> group dicts (scores, questions, source_mix, ...)
  angles rows         -> serious_candidates[] + reddit_angles[] + tiktok_angles[]
  source_examples rows-> source_examples[]

`rows_to_clusters()` is pure (no network) so it can be unit-tested as the
inverse of db.py. The CLI wraps it with Supabase reads.

Usage:
  python scripts/db_to_clusters_json.py 2026-05-29 --region ph
  python scripts/db_to_clusters_json.py 2026-05-29 --region id --stdout
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mvp"))
from regions import get_region  # noqa: E402
import db  # noqa: E402  (Supabase client; reused for reads)


# --------------------------------------------------------------------------
# Pure reconstruction (no network) — inverse of db.py's _insert_* mapping
# --------------------------------------------------------------------------

def _topic_to_group(topic: Dict, angle_rows: List[Dict],
                    source_rows: List[Dict]) -> Dict:
    """Rebuild one raw group dict (the shape cluster_with_llm produced) from a
    topics row + its angles + source_examples rows."""
    g: Dict = {
        "name": topic.get("name"),
        "name_zh": topic.get("name_zh"),
        "narrative": topic.get("narrative"),
        "narrative_zh": topic.get("narrative_zh"),
        "topic_type": topic.get("topic_type"),
        "density": topic.get("density"),
        "entry_ids": topic.get("entry_ids"),
        "market_hint": topic.get("market_hint"),
        "source_mix": topic.get("source_mix") or {},
        "source_labels": topic.get("source_labels") or [],
        "R": topic.get("R"), "R_reason": topic.get("R_reason"),
        "S": topic.get("S"), "S_reason": topic.get("S_reason"),
        "T": topic.get("T"), "T_reason": topic.get("T_reason"),
        "U": topic.get("U"), "U_reason": topic.get("U_reason"),
        "H": topic.get("H"), "H_reason": topic.get("H_reason"),
        "contract_quality": topic.get("contract_quality"),
        "volume_potential": topic.get("volume_potential"),
        "volume_score": topic.get("volume_score"),
        "scoring_version": topic.get("scoring_version"),
        "BDLT": topic.get("bdlt"),
        "yes_buyer": topic.get("yes_buyer"),
        "no_buyer": topic.get("no_buyer"),
        "bettable": bool(topic.get("bettable")),
        "suggested_question": topic.get("suggested_question"),
        "suggested_question_zh": topic.get("suggested_question_zh"),
        "resolution_source": topic.get("resolution_source"),
        "disposition_hint": topic.get("disposition"),
        "why_users_bet": topic.get("why_users_bet"),
        "prob": topic.get("prob"),
        "prob_reason_en": topic.get("prob_reason_en"),
        "prob_reason_zh": topic.get("prob_reason_zh"),
    }

    # angles, split + ordered by position
    by_type: Dict[str, List[Dict]] = {"serious_candidate": [], "reddit": [], "tiktok": []}
    for a in sorted(angle_rows, key=lambda r: r.get("position", 0)):
        by_type.setdefault(a.get("angle_type"), []).append(a)

    serious = []
    for a in by_type["serious_candidate"]:
        scores = a.get("scores") or {}
        cand = {
            "suggested_question": a.get("question_en"),
            "suggested_question_zh": a.get("question_zh"),
            "resolution_source": a.get("source"),
        }
        cand.update({k: scores.get(k) for k in ("R", "S", "T", "U", "H", "BDLT") if k in scores})
        serious.append(cand)
    if serious:
        g["serious_candidates"] = serious

    def _angle_list(rows):
        return [{
            "subtopic": a.get("subtopic"),
            "question_en": a.get("question_en"),
            "question_zh": a.get("question_zh"),
            "source": a.get("source"),
            "url": a.get("url"),
        } for a in rows]

    if by_type["reddit"]:
        g["reddit_angles"] = _angle_list(by_type["reddit"])
        first = g["reddit_angles"][0]
        g["reddit_question"] = first["question_en"]
        g["reddit_question_zh"] = first["question_zh"]
        g["reddit_resolution_source"] = first["source"]
        g["reddit_resolution_url"] = first["url"]
    if by_type["tiktok"]:
        g["tiktok_angles"] = _angle_list(by_type["tiktok"])

    g["source_examples"] = [{
        "id": se.get("position"),
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
    } for se in sorted(source_rows, key=lambda r: r.get("position", 0))]

    return g


def rows_to_clusters(run: Dict, topics: List[Dict], angles: List[Dict],
                     sources: List[Dict]) -> Dict:
    """Reconstruct the clusters_{date}.json dict from raw table rows. Pure."""
    angles_by_topic: Dict[str, List[Dict]] = {}
    for a in angles:
        angles_by_topic.setdefault(a.get("topic_id"), []).append(a)
    sources_by_topic: Dict[str, List[Dict]] = {}
    for s in sources:
        sources_by_topic.setdefault(s.get("topic_id"), []).append(s)

    ordered = sorted(topics, key=lambda t: t.get("broad_index", 0))
    groups = [
        _topic_to_group(t, angles_by_topic.get(t["id"], []),
                        sources_by_topic.get(t["id"], []))
        for t in ordered
    ]
    return {
        "region": run.get("region"),
        "clustered_at": run.get("clustered_at"),
        "total_entries": run.get("total_entries"),
        "cluster_pipeline": run.get("cluster_pipeline"),
        "target_group_range": run.get("target_group_range"),
        "noise_count": run.get("noise_count") or 0,
        "groups": groups,
        "noise": [],
    }


# --------------------------------------------------------------------------
# CLI: read Supabase, reconstruct, write file
# --------------------------------------------------------------------------

def export(region_slug: str, run_date: str) -> Dict:
    client = db.get_client()
    if client is None:
        raise RuntimeError("Supabase credentials absent (SUPABASE_URL / "
                           "SUPABASE_SERVICE_KEY); cannot export.")
    run_rows = (client.table("runs").select("*")
                .eq("region", region_slug).eq("run_date", run_date).execute().data)
    if not run_rows:
        raise RuntimeError(f"No run in Supabase for {region_slug} {run_date}")
    run = run_rows[0]
    topics = (client.table("topics").select("*").eq("run_id", run["id"])
              .execute().data)
    topic_ids = [t["id"] for t in topics]
    angles, sources = [], []
    # chunk the IN() filter to stay well under URL limits
    for i in range(0, len(topic_ids), 50):
        chunk = topic_ids[i:i + 50]
        angles += (client.table("angles").select("*")
                   .in_("topic_id", chunk).execute().data)
        sources += (client.table("source_examples").select("*")
                    .in_("topic_id", chunk).execute().data)
    return rows_to_clusters(run, topics, angles, sources)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=dt.date.today().isoformat())
    parser.add_argument("--region", default="ph", choices=("ph", "id"))
    parser.add_argument("--stdout", action="store_true",
                        help="print JSON to stdout instead of writing the file")
    args = parser.parse_args()

    region = get_region(args.region)
    data = export(region.slug, args.date)
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    if args.stdout:
        print(payload)
        return

    base = Path(__file__).resolve().parent.parent
    reports_dir = base / "mvp" / "reports"
    if region.reports_subdir:
        reports_dir = reports_dir / region.reports_subdir
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"clusters_{args.date}.json"
    out.write_text(payload, encoding="utf-8")
    print(f"[OK] DB -> {out}  ({len(data['groups'])} groups)")


if __name__ == "__main__":
    main()
