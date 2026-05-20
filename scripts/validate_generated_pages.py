#!/usr/bin/env python3
"""Validate generated static pages before the automation commits them."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


FOREIGN_TERMS = {
    "ph": (
        "bank indonesia", "rupiah", "ihsg", "idx ", "jakarta",
        "ministry of finance of indonesia",
    ),
    "id": (
        "bangko sentral", "bsp ", "philippine peso", "comelec",
        "senate of the philippines", "supreme court of the philippines",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    checks = [
        ("ph", Path("docs/index.html"), Path(f"mvp/reports/clusters_{args.date}.json")),
        ("id", Path("docs/id/index.html"), Path(f"mvp/reports/id/clusters_{args.date}.json")),
    ]
    failed = False
    for region, html_path, json_path in checks:
        if not html_path.exists():
            print(f"[ERR] Missing {html_path}", file=sys.stderr)
            failed = True
            continue
        if not json_path.exists():
            print(f"[ERR] Missing {json_path}", file=sys.stderr)
            failed = True
            continue

        html = html_path.read_text(encoding="utf-8")
        groups = _extract_groups(html)
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        if summary.get("total_entries") != 120:
            print(f"[ERR] {region}: expected 120 entries, got {summary.get('total_entries')}", file=sys.stderr)
            failed = True
        if len(groups) == 0:
            print(f"[ERR] {region}: page contains no groups", file=sys.stderr)
            failed = True
        if _has_foreign_bettable_question(region, groups):
            print(f"[ERR] {region}: foreign domestic resolver in bettable question", file=sys.stderr)
            failed = True
        print(
            f"[OK] {region}: {len(groups)} page groups, "
            f"{summary.get('total_entries')} entries, {summary.get('noise_count')} noise"
        )
    return 1 if failed else 0


def _extract_groups(html: str) -> list[dict]:
    match = re.search(r"const groups = (\[[\s\S]*?\]);", html)
    if not match:
        raise RuntimeError("Could not find `const groups = [...]` in HTML")
    return json.loads(match.group(1))


def _has_foreign_bettable_question(region: str, groups: list[dict]) -> bool:
    terms = FOREIGN_TERMS.get(region, ())
    for group in groups:
        if not group.get("bettable"):
            continue
        text = " ".join(str(group.get(key) or "") for key in (
            "question", "question_en", "question_zh", "source",
        )).lower()
        if any(term in text for term in terms):
            print(f"[ERR] {region}: {group.get('name_en')} => {text}", file=sys.stderr)
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
