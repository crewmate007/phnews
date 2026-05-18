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
from pathlib import Path


def publish(date: str) -> tuple[Path, Path]:
    base = Path(__file__).resolve().parent.parent
    src = base / "mvp" / "reports" / f"cluster_{date}.html"
    if not src.exists():
        raise FileNotFoundError(f"missing generated report: {src}")

    reports_dir = base / "docs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    archived = reports_dir / src.name
    index = base / "docs" / "index.html"
    shutil.copy2(src, archived)
    shutil.copy2(src, index)

    # Keep GitHub Pages from treating the static site as a Jekyll project.
    (base / "docs" / ".nojekyll").touch()
    return archived, index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=dt.date.today().isoformat())
    args = parser.parse_args()

    archived, index = publish(args.date)
    print(f"[OK] Published archive → {archived}")
    print(f"[OK] Published homepage → {index}")


if __name__ == "__main__":
    main()
