"""Read SourceIntel artifacts for PHNews without fetching upstream sources."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
from typing import Any

from regions import RegionConfig, get_region


_REPORT_RE_TEMPLATE = r"hotspots_{region}_(\d{{4}}-\d{{2}}-\d{{2}})\.json"


def default_source_intel_dir() -> Path:
    env_path = os.environ.get("SOURCE_INTEL_DIR")
    if env_path:
        return Path(env_path).expanduser()
    return Path(__file__).resolve().parents[2] / "SourceIntel"


def load_source_intel_payload(*, region: RegionConfig | str | None = None,
                              source_intel_dir: str | Path | None = None,
                              report_path: str | Path | None = None) -> dict[str, Any]:
    region_cfg = region if isinstance(region, RegionConfig) else get_region(region)
    path = _resolve_report_path(
        region=region_cfg.slug,
        source_intel_dir=Path(source_intel_dir) if source_intel_dir else default_source_intel_dir(),
        report_path=Path(report_path) if report_path else None,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def load_source_intel_clusters(*, region: RegionConfig | str | None = None,
                               source_intel_dir: str | Path | None = None,
                               report_path: str | Path | None = None,
                               source: str | None = None) -> list[dict[str, Any]]:
    payload = load_source_intel_payload(
        region=region,
        source_intel_dir=source_intel_dir,
        report_path=report_path,
    )
    hotspots = payload.get("hotspots", [])
    if source:
        hotspots = [item for item in hotspots if item.get("source") == source]
    return [_hotspot_to_cluster(index, item) for index, item in enumerate(hotspots)]


def source_intel_signals_for_topic(topic: dict[str, Any], *,
                                   region: RegionConfig | str | None = None,
                                   source_intel_dir: str | Path | None = None,
                                   report_path: str | Path | None = None) -> dict[str, list[dict[str, str]]]:
    """Return SourceIntel news hotspots that roughly match a YAML topic."""
    try:
        payload = load_source_intel_payload(
            region=region,
            source_intel_dir=source_intel_dir,
            report_path=report_path,
        )
    except FileNotFoundError:
        return {"gnews_en": [], "gnews_tl": []}

    topic_tokens = _topic_tokens(topic)
    matches = []
    for item in payload.get("hotspots", []):
        if item.get("source") != "google_news":
            continue
        if _overlap_count(topic_tokens, _hotspot_text(item)) >= 2:
            matches.append(_hotspot_to_article(item))
    return {"gnews_en": matches, "gnews_tl": []}


def source_intel_discoveries(topics: list[dict[str, Any]], *,
                             region: RegionConfig | str | None = None,
                             source_intel_dir: str | Path | None = None,
                             report_path: str | Path | None = None) -> dict[str, Any]:
    clusters = load_source_intel_clusters(
        region=region,
        source_intel_dir=source_intel_dir,
        report_path=report_path,
        source="google_news",
    )
    topic_token_map = {topic["topic_id"]: _topic_tokens(topic) for topic in topics}
    matched: list[dict[str, Any]] = []
    new: list[dict[str, Any]] = []

    for cluster in clusters:
        cluster_text = _cluster_text(cluster)
        best_topic = None
        best_overlap = 0
        for topic_id, tokens in topic_token_map.items():
            overlap = _overlap_count(tokens, cluster_text)
            if overlap > best_overlap:
                best_topic = topic_id
                best_overlap = overlap
        entry = {"cluster": cluster, "matched_topic": best_topic if best_overlap >= 2 else None}
        if entry["matched_topic"]:
            matched.append(entry)
        else:
            new.append(entry)

    return {
        "matched": matched,
        "new": new,
        "total_clusters": len(clusters),
        "fetched_at": dt.datetime.now().isoformat(),
        "source": "source_intel",
    }


def mock_source_intel_clusters(region: RegionConfig | str | None = None) -> list[dict[str, Any]]:
    region_cfg = region if isinstance(region, RegionConfig) else get_region(region)
    return [
        {
            "cluster_title": f"{region_cfg.country_label_en} currency pressure debate",
            "published": "mock",
            "link": "https://mock/source-intel/1",
            "section": "source_intel:google_news",
            "region": region_cfg.slug,
            "sub_articles": [
                {"title": "Central bank officials discuss currency pressure", "source": "Mock News", "link": "https://mock/source-intel/1a"},
                {"title": "Analysts watch inflation and rate guidance", "source": "Mock Wire", "link": "https://mock/source-intel/1b"},
            ],
            "source_count": 2,
            "sources": ["Mock News", "Mock Wire"],
        },
        {
            "cluster_title": f"{region_cfg.country_label_en} cabinet reshuffle speculation",
            "published": "mock",
            "link": "https://mock/source-intel/2",
            "section": "source_intel:x_grok",
            "region": region_cfg.slug,
            "sub_articles": [
                {"title": "Political accounts circulate cabinet names", "source": "SourceIntel", "link": "https://mock/source-intel/2a"},
            ],
            "source_count": 1,
            "sources": ["SourceIntel"],
        },
    ]


def _resolve_report_path(*, region: str, source_intel_dir: Path,
                         report_path: Path | None) -> Path:
    if report_path:
        path = report_path.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise FileNotFoundError(f"SourceIntel report not found: {path}")
        return path

    reports_dir = source_intel_dir / "reports"
    pattern = re.compile(_REPORT_RE_TEMPLATE.format(region=re.escape(region)))
    candidates: list[tuple[str, Path]] = []
    for path in reports_dir.glob(f"hotspots_{region}_*.json"):
        match = pattern.fullmatch(path.name)
        if match:
            candidates.append((match.group(1), path))
    if not candidates:
        raise FileNotFoundError(
            f"No SourceIntel report found for region '{region}' in {reports_dir}. "
            f"Run SourceIntel first, e.g. python3 -m source_intel.cli collect --source all --region {region}"
        )
    return sorted(candidates)[-1][1]


def _hotspot_to_cluster(index: int, item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence_urls", [])
    claims = item.get("claims_en") or item.get("claims_zh") or []
    sub_articles = []
    for claim_index, claim in enumerate(claims):
        sub_articles.append({
            "title": claim,
            "source": item.get("source", "source_intel"),
            "link": evidence[claim_index] if claim_index < len(evidence) else "",
        })
    if not sub_articles:
        sub_articles.append({
            "title": item.get("summary_en") or item.get("title_en", ""),
            "source": item.get("source", "source_intel"),
            "link": evidence[0] if evidence else "",
        })

    sources = item.get("entities") or [item.get("source", "source_intel")]
    source_label = item.get("source", "unknown")
    if item.get("source_section"):
        source_label = f"{source_label}:{item['source_section']}"
    return {
        "cluster_title": item.get("title_en") or item.get("title_zh") or f"SourceIntel hotspot {index}",
        "published": item.get("observed_at", ""),
        "link": evidence[0] if evidence else "",
        "section": f"source_intel:{source_label}",
        "region": item.get("region", ""),
        "sub_articles": sub_articles,
        "source_count": max(len(evidence), len(sub_articles), 1),
        "sources": sources,
        "summary": item.get("summary_en") or item.get("summary_zh") or "",
        "summary_zh": item.get("summary_zh") or item.get("summary_en") or "",
        "keywords": item.get("keywords", []),
        "prediction_angle": item.get("prediction_angle_en") or item.get("prediction_angle_zh") or "",
        "social_heat": item.get("social_heat", ""),
        "uncertainty": item.get("uncertainty", ""),
        "rank_score": item.get("rank_score"),
        "rank_reason": item.get("rank_reason", ""),
    }


def _hotspot_to_article(item: dict[str, Any]) -> dict[str, str]:
    evidence = item.get("evidence_urls", [])
    return {
        "title": item.get("title_en") or item.get("title_zh") or "",
        "link": evidence[0] if evidence else "",
        "published": item.get("observed_at", ""),
        "source": "SourceIntel News",
        "summary": item.get("summary_en") or item.get("summary_zh") or "",
    }


def _topic_tokens(topic: dict[str, Any]) -> set[str]:
    parts = [topic.get("topic_id", ""), topic.get("topic_name", "")]
    queries = topic.get("queries", {})
    for source_queries in queries.values():
        if isinstance(source_queries, dict):
            for values in source_queries.values():
                if isinstance(values, list):
                    parts.extend(str(value) for value in values)
        elif isinstance(source_queries, list):
            parts.extend(str(value) for value in source_queries)
    for entity in topic.get("canonical_entities", []):
        parts.append(str(entity.get("name", "")))
        parts.extend(str(alias) for alias in entity.get("aliases", []))
    return _tokens(" ".join(parts))


def _hotspot_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title_en", ""),
        item.get("title_zh", ""),
        item.get("summary_en", ""),
        item.get("summary_zh", ""),
    ]
    parts.extend(item.get("keywords", []))
    parts.extend(item.get("claims_en", []))
    parts.extend(item.get("claims_zh", []))
    return " ".join(str(part) for part in parts)


def _cluster_text(cluster: dict[str, Any]) -> str:
    parts = [cluster.get("cluster_title", "")]
    parts.extend(article.get("title", "") for article in cluster.get("sub_articles", []))
    return " ".join(parts)


def _overlap_count(tokens: set[str], text: str) -> int:
    return len(tokens & _tokens(text))


def _tokens(text: str) -> set[str]:
    stop_words = {
        "the", "and", "for", "with", "from", "that", "this", "will", "news",
        "when", "what", "philippines", "philippine", "filipino", "indonesia",
        "indonesian", "jakarta", "manila", "google", "reddit",
    }
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text.lower())
        if token not in stop_words
    }
