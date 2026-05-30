"""
Reddit signal fetcher for the classic YAML topic flow.

Upstream news collection now lives in the sibling SourceIntel project. Daily News
reads SourceIntel JSON artifacts through source_intel_bridge instead of fetching
news sources directly.
"""
from __future__ import annotations

import datetime as dt
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

from source_intel_bridge import source_intel_signals_for_topic


REDDIT_USER_AGENT = "daily-news-bot:v0.1 (by /u/ph_markets_research)"


def _fetch_url(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": REDDIT_USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_reddit(feed_url: str) -> List[Dict]:
    """Fetch one Reddit RSS feed."""
    content = _fetch_url(feed_url)
    return [
        {
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "published": item.get("published", ""),
            "author": item.get("author", ""),
            "summary": item.get("summary", ""),
        }
        for item in _parse_feed_items(content)
    ]


def fetch_topic_signals(topic: dict, mock: bool = False, *, region=None,
                        source_intel_dir=None, source_intel_report=None) -> dict:
    """Build topic signals from SourceIntel artifacts plus Reddit."""
    if mock:
        return _mock_signals(topic)

    source_intel = source_intel_signals_for_topic(
        topic,
        region=region,
        source_intel_dir=source_intel_dir,
        report_path=source_intel_report,
    )
    signals = {
        "topic_id": topic["topic_id"],
        "fetched_at": dt.datetime.now().isoformat(),
        "gnews_en": source_intel["gnews_en"],
        "gnews_tl": source_intel["gnews_tl"],
        "reddit": [],
    }

    queries = topic.get("queries", {})
    for reddit_query in queries.get("reddit", []):
        try:
            results = fetch_reddit(reddit_query["feed_url"])
            signals["reddit"].extend(results)
            time.sleep(2)
        except Exception as exc:
            err = str(exc)
            if "403" in err or "blocked" in err.lower():
                print(f"  [WARN] reddit '{reddit_query.get('subreddit')}' blocked (403)")
            elif "429" in err:
                print(f"  [WARN] reddit '{reddit_query.get('subreddit')}' rate-limited (429)")
            else:
                print(f"  [WARN] reddit '{reddit_query.get('subreddit')}' failed: {err[:80]}")

    signals["gnews_en"] = _dedupe(signals["gnews_en"])
    signals["gnews_tl"] = _dedupe(signals["gnews_tl"])
    signals["reddit"] = _dedupe(signals["reddit"])
    return signals


def _parse_feed_items(content: str) -> list[dict[str, str]]:
    root = ET.fromstring(content)
    items = []
    for item in root.findall(".//item"):
        items.append({
            "title": _child_text(item, "title"),
            "link": _child_text(item, "link"),
            "published": _child_text(item, "pubDate"),
            "author": _child_text(item, "author"),
            "summary": _child_text(item, "description"),
        })
    for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
        link_node = entry.find("{http://www.w3.org/2005/Atom}link")
        items.append({
            "title": _child_text(entry, "{http://www.w3.org/2005/Atom}title"),
            "link": link_node.get("href", "") if link_node is not None else "",
            "published": _child_text(entry, "{http://www.w3.org/2005/Atom}updated"),
            "author": _atom_author(entry),
            "summary": _child_text(entry, "{http://www.w3.org/2005/Atom}content"),
        })
    return items


def _child_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _atom_author(entry: ET.Element) -> str:
    author = entry.find("{http://www.w3.org/2005/Atom}author")
    if author is None:
        return ""
    return _child_text(author, "{http://www.w3.org/2005/Atom}name")


def _dedupe(items: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for item in items:
        key = item.get("link") or item.get("title")
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


_MOCK_FIXTURES = {
    "ph-fuel-weekly": {
        "source_intel_google": [
            {"title": "Oil firms to implement big-time rollback next week", "source": "SourceIntel News", "link": "https://mock/1", "published": "mock"},
            {"title": "DOE confirms fuel price rollback for implementation", "source": "SourceIntel News", "link": "https://mock/2", "published": "mock"},
        ],
        "reddit": [
            {"title": "Big rollback incoming this week - DOE", "link": "https://mock/r1", "published": "mock"},
            {"title": "Impact on inflation: discussion", "link": "https://mock/r2", "published": "mock"},
        ],
    },
    "ph-bsp-rate": {
        "source_intel_google": [
            {"title": "BSP expected to hold rates steady, analysts say", "source": "SourceIntel News", "link": "https://mock/b1", "published": "mock"},
            {"title": "Markets price in small chance of rate cut", "source": "SourceIntel News", "link": "https://mock/b2", "published": "mock"},
        ],
        "reddit": [
            {"title": "Rate cut or hold? phinvest predictions thread", "link": "https://mock/br1", "published": "mock"},
        ],
    },
    "ph-south-china-sea": {
        "source_intel_google": [
            {"title": "Chinese coast guard incident sparks new diplomatic protest", "source": "SourceIntel News", "link": "https://mock/s1", "published": "mock"},
            {"title": "US reaffirms treaty commitment after maritime incident", "source": "SourceIntel News", "link": "https://mock/s2", "published": "mock"},
        ],
        "reddit": [
            {"title": "Latest Ayungin incident footage", "link": "https://mock/sr1", "published": "mock"},
        ],
    },
    "ph-typhoon-season": {
        "source_intel_google": [
            {"title": "PAGASA watches early typhoon season signals", "source": "SourceIntel News", "link": "https://mock/t1", "published": "mock"},
        ],
        "reddit": [],
    },
    "ph-sara-impeachment": {
        "source_intel_google": [
            {"title": "Senate impeachment trial schedule still uncertain", "source": "SourceIntel News", "link": "https://mock/i1", "published": "mock"},
            {"title": "Legal experts debate conviction threshold", "source": "SourceIntel News", "link": "https://mock/i2", "published": "mock"},
        ],
        "reddit": [
            {"title": "Will Sara actually be convicted? Odds thread", "link": "https://mock/ir1", "published": "mock"},
        ],
    },
}


def _mock_signals(topic: dict) -> dict:
    topic_id = topic["topic_id"]
    fixture = _MOCK_FIXTURES.get(topic_id, {"source_intel_google": [], "reddit": []})
    return {
        "topic_id": topic_id,
        "fetched_at": dt.datetime.now().isoformat(),
        "gnews_en": fixture["source_intel_google"],
        "gnews_tl": [],
        "reddit": fixture["reddit"],
        "_mock": True,
    }
