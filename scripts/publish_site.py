"""
Publish the generated daily HTML report into docs/ for GitHub Pages.

Usage:
  python3 scripts/publish_site.py                 # publish today's report
  python3 scripts/publish_site.py 2026-05-02      # publish a specific date

Reads:
  mvp/reports/cluster_YYYY-MM-DD.html

Writes:
  docs/reports/cluster_YYYY-MM-DD.html
  docs/index.html
  docs/.nojekyll
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mvp"))
from regions import get_region


def publish(date: str, region_slug: str = "ph") -> tuple[Path, Path]:
    region = get_region(region_slug)
    base = Path(__file__).resolve().parent.parent
    src_dir = base / "mvp" / "reports"
    if region.reports_subdir:
        src_dir = src_dir / region.reports_subdir
    src = src_dir / f"cluster_{date}.html"
    if not src.exists():
        raise FileNotFoundError(f"missing generated report: {src}")

    docs_dir = base / "docs"
    if region.reports_subdir:
        docs_dir = docs_dir / region.reports_subdir
    reports_dir = docs_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    archived = reports_dir / src.name
    index = docs_dir / "index.html"
    shutil.copy2(src, archived)
    shutil.copy2(src, index)

    # Keep GitHub Pages from treating the static site as a Jekyll project.
    (base / "docs" / ".nojekyll").touch()
    return archived, index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=dt.date.today().isoformat())
    parser.add_argument("--region", default="ph", choices=("ph", "id"))
    args = parser.parse_args()

    archived, index = publish(args.date, args.region)
    print(f"[OK] Published archive → {archived}")
    print(f"[OK] Published homepage → {index}")


if __name__ == "__main__":
    main()
