"""
Backfill: attach Reddit dry-wit angles to an existing clusters_YYYY-MM-DD.json.

The daily pipeline (run_daily.py --cluster) now generates these angles
automatically via cluster_with_llm. This script exists ONLY for backfilling
a day whose JSON was generated BEFORE that wiring landed — without rerunning
the (expensive, non-deterministic) clustering+scoring pass.

After running this, regenerate the HTML (no API calls):
  python3 scripts/gen_html.py YYYY-MM-DD --region ph
  python3 scripts/publish_site.py YYYY-MM-DD --region ph

Usage:
  python3 scripts/add_reddit_angles.py                 # today, ph
  python3 scripts/add_reddit_angles.py 2026-05-24      # specific date, ph
  python3 scripts/add_reddit_angles.py --region id
  python3 scripts/add_reddit_angles.py --limit 5       # smoke test on first 5 groups
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mvp"))
from regions import get_region  # noqa: E402
from cluster import generate_reddit_angles  # noqa: E402


def load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GEMINI_API_KEY not set and .env missing")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=dt.date.today().isoformat())
    parser.add_argument("--region", default="ph", choices=("ph", "id"))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N groups (smoke test).",
    )
    args = parser.parse_args()

    region = get_region(args.region)
    base = Path(__file__).resolve().parent.parent
    reports_dir = base / "mvp" / "reports"
    if region.reports_subdir:
        reports_dir = reports_dir / region.reports_subdir
    json_path = reports_dir / f"clusters_{args.date}.json"
    if not json_path.exists():
        print(f"[ERR] missing {json_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    all_groups = data.get("groups", [])
    if not all_groups:
        print("[INFO] No groups; nothing to do.")
        return

    target_groups = all_groups[: args.limit] if args.limit else all_groups
    if args.limit:
        print(f"[INFO] Smoke test mode: processing first {len(target_groups)} groups only")

    try:
        from google import genai
    except ImportError:
        print("[ERR] pip install google-genai", file=sys.stderr)
        sys.exit(1)

    api_key = load_api_key()
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    client = genai.Client(api_key=api_key)

    print(
        f"[INFO] Generating Reddit angles for {len(target_groups)} groups "
        f"({args.region}, {args.date}) via {model}..."
    )
    stats = generate_reddit_angles(target_groups, client, model, region)
    print(f"[OK] Reddit angles attached: {stats['attached']}/{stats['total']}")

    # generate_reddit_angles mutated target_groups in-place; that's the same
    # list of dicts that lives inside data["groups"][:limit], so the writeback
    # just needs to re-serialize the whole data dict.
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] Updated {json_path}")


if __name__ == "__main__":
    main()
