"""Shadow-mode diff: pipeline JSON vs Supabase-exported JSON (P2b-2).

In CI the pipeline writes clusters_{date}.json to disk AND dual-writes the
same data to Supabase in one run. This script reads both back, runs each
group through gen_html.build_group, and reports any field-level drift -- so
we can confirm the exporter faithfully reproduces the page BEFORE flipping
the render source to Supabase.

NON-BLOCKING by design: always exits 0 (unless --strict). Drift is logged,
not fatal, during the shadow period.

Usage:
  python scripts/shadow_diff_db.py 2026-05-29 --region ph
  python scripts/shadow_diff_db.py 2026-05-29 --region id --strict   # exit 1 on drift
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mvp"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from regions import get_region  # noqa: E402
import gen_html  # noqa: E402
from db_to_clusters_json import export  # noqa: E402

# Fields that actually drive the rendered page; drift in these matters.
_COMPARE_KEYS = (
    "name_en", "name_zh", "density", "R", "S", "T", "U", "H",
    "bettable", "question_en", "question_zh", "source",
)


def _index(groups):
    """build_group every non-noise group, keyed by (name_en, position)."""
    out = []
    for g in groups:
        if str(g.get("name", "")).lower() == "noise":
            continue
        out.append(gen_html.build_group(g))
    return out


def diff(region_slug: str, run_date: str) -> list[str]:
    base = Path(__file__).resolve().parent.parent
    region = get_region(region_slug)
    reports = base / "mvp" / "reports"
    if region.reports_subdir:
        reports = reports / region.reports_subdir
    disk_path = reports / f"clusters_{run_date}.json"
    if not disk_path.exists():
        return [f"disk JSON missing: {disk_path}"]

    disk = _index(json.loads(disk_path.read_text(encoding="utf-8")).get("groups", []))
    db_clusters = export(region_slug, run_date)
    dbg = _index(db_clusters.get("groups", []))

    problems = []
    if len(disk) != len(dbg):
        problems.append(f"group count: disk={len(disk)} db={len(dbg)}")

    for i, (a, b) in enumerate(zip(disk, dbg)):
        for k in _COMPARE_KEYS:
            if a.get(k) != b.get(k):
                problems.append(
                    f"group[{i}] {a.get('name_en','?')[:30]!r} field {k}: "
                    f"disk={a.get(k)!r} db={b.get(k)!r}"
                )
        # angle-count drift
        for arr in ("reddit_angles", "tiktok_angles", "source_examples"):
            if len(a.get(arr) or []) != len(b.get(arr) or []):
                problems.append(
                    f"group[{i}] {arr} count: disk={len(a.get(arr) or [])} "
                    f"db={len(b.get(arr) or [])}"
                )
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=dt.date.today().isoformat())
    parser.add_argument("--region", default="ph", choices=("ph", "id"))
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 if any drift (default: log-only, exit 0)")
    args = parser.parse_args()

    try:
        problems = diff(args.region, args.date)
    except Exception as exc:  # noqa: BLE001
        print(f"[SHADOW] {args.region} {args.date}: diff skipped "
              f"({type(exc).__name__}: {exc})", file=sys.stderr)
        sys.exit(0)  # shadow mode never blocks

    if not problems:
        print(f"[SHADOW] {args.region} {args.date}: DB export matches pipeline JSON ✓")
        sys.exit(0)

    print(f"[SHADOW] {args.region} {args.date}: {len(problems)} drift(s):", file=sys.stderr)
    for p in problems[:40]:
        print(f"[SHADOW]   {p}", file=sys.stderr)
    sys.exit(1 if args.strict else 0)


if __name__ == "__main__":
    main()
