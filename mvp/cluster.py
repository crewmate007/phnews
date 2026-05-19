"""
LLM-based topic clustering for SourceIntel entries.

Takes normalized SourceIntel hotspots and groups them into
10-15 coherent topic groups, each assessed for prediction market
bettability.

Flow:
  SourceIntel hotspots → cluster_with_llm() → 10-15 groups
  Each group has: name, entry_ids, density, RSTUH scores, suggested question
"""
from __future__ import annotations
import json
import datetime as dt
from typing import List, Dict, Optional

from regions import RegionConfig, get_region


# ============================================================
# LLM-based clustering (Gemini Flash)
# ============================================================

CLUSTER_PROMPT_TEMPLATE = """\
You are a prediction market analyst covering {country_name}. Today is {date}.

Below are {n} SourceIntel hotspots collected today for {country_adjective} coverage.
Each entry has an ID, source label, coverage count, and title.
Some entries may be written in local-language media; still output English names, Chinese names,
and English narratives/questions.

YOUR TASK:
Group these entries into 10–15 coherent topic groups and evaluate each group's \
potential as a prediction market. An entry may appear in at most one group; \
low-signal noise entries can be left unassigned (put them in a "noise" group).

ENTRIES:
{entries}

OUTPUT: strict JSON only, no markdown fences, no extra text.

{{
  "groups": [
    {{
      "name": "short topic name (English, ≤6 words)",
      "name_zh": "中文话题名（≤8字）",
      "entry_ids": [0, 5, 12],
      "density": <int, number of entries in this group>,
      "narrative": "1-2 sentence summary of what is happening",
      "narrative_zh": "中文摘要，1-2句",
      "R": <0|1|2>,
      "R_reason": "why this outcome is/isn't resolvable",
      "S": <0|1|2>,
      "S_reason": "what authoritative source resolves it",
      "T": <0|1|2>,
      "T_reason": "what is the time window / deadline",
      "U": <0|1|2>,
      "U_reason": "how uncertain is the outcome (0=decided, 2=genuinely uncertain)",
      "H": <0|1|2>,
      "H_reason": "how much public attention / discussion",
      "bettable": <true|false>,
      "suggested_question": "Will ... by ...? (null if not bettable)",
      "suggested_question_zh": "中文预测市场问题（不可下注则为 null）",
      "resolution_source": "e.g. BSP press release, DOE weekly bulletin"
    }}
  ],
  "noise": [<entry_ids not assigned to any group>]
}}

SCORING GUIDE:
- R=2: clear yes/no outcome with objective criteria (e.g. "Will BSP cut by 25bp?")
- R=1: outcome exists but boundary is fuzzy
- R=0: outcome is purely subjective or has no defined endpoint
- S=2: official government/regulatory body announces result
- S=1: reputable media consensus, or official source exists but disputed
- S=0: no clear authoritative resolver
- T=2: specific date or recurring cadence (weekly DOE bulletin, May FOMC-equivalent)
- T=1: approximate deadline (this quarter, this month)
- T=0: open-ended, no deadline
- U=2: outcome is genuinely in doubt, implied probability 25%–75%
- U=1: one side heavily favored but not certain
- U=0: outcome is essentially decided / a sure thing
- H=2: multiple sources, social discussion, cross-section coverage
- H=1: 2–4 sources, limited social
- H=0: single source or very low interest
"""


def cluster_with_llm(clusters: List[Dict], api_key: str,
                     region: RegionConfig | str | None = None,
                     model: str = "gemini-flash-latest") -> Dict:
    """Send all cluster titles to Gemini Flash and get topic groups back.

    Args:
        clusters: list of SourceIntel cluster-shaped dicts
        api_key: Gemini API key
        model: Gemini model to use

    Returns:
        {
            "groups": [...],       # list of group dicts with RSTUH
            "noise": [...],        # unassigned entry IDs
            "total_entries": int,
            "clustered_at": str,
        }
    """
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("pip install google-genai")

    region_cfg = region if isinstance(region, RegionConfig) else get_region(region)
    client = genai.Client(api_key=api_key)

    entry_lines = []
    for i, c in enumerate(clusters):
        section = c.get("section", "")
        title = c.get("cluster_title", "")
        n_src = c.get("source_count", 0)
        entry_lines.append(f"[{i}] ({section}, {n_src}src) {title}")

    entries_text = "\n".join(entry_lines)
    today = dt.date.today().isoformat()

    prompt = CLUSTER_PROMPT_TEMPLATE.format(
        date=today,
        n=len(clusters),
        entries=entries_text,
        country_name=region_cfg.country_name,
        country_adjective=region_cfg.country_adjective,
    )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )
    text = response.text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    result = json.loads(text)
    result["region"] = region_cfg.slug
    result["total_entries"] = len(clusters)
    result["clustered_at"] = dt.datetime.now().isoformat()

    for group in result.get("groups", []):
        group["clusters"] = [clusters[i] for i in group.get("entry_ids", [])
                             if i < len(clusters)]

    return result


# ============================================================
# Fallback: keyword-based clustering (no LLM)
# ============================================================

def cluster_keyword_fallback(clusters: List[Dict],
                             region: RegionConfig | str | None = None) -> Dict:
    """Simple keyword-based grouping when no API key is available.

    Groups entries by shared significant keywords. Much lower quality
    than LLM clustering but useful for offline testing.
    """
    import re

    region_cfg = region if isinstance(region, RegionConfig) else get_region(region)
    STOP = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
        "is", "are", "was", "were", "will", "be", "been", "has", "have", "had",
        "says", "said", "new", "news", "philippines", "philippine", "ph",
        "vs", "by", "from", "with", "this", "that", "its", "indonesia",
        "indonesian", "jakarta", "ri", "berita", "terbaru", "dan", "yang",
        "dari", "untuk", "dengan", "akan", "ini", "itu", "pada",
    }

    def keywords(text):
        tokens = re.findall(r'[a-zA-Z]{4,}', text.lower())
        return {t for t in tokens if t not in STOP}

    # Build keyword sets per entry
    entry_kw = [keywords(c["cluster_title"]) for c in clusters]

    assigned = [-1] * len(clusters)
    groups = []

    for i in range(len(clusters)):
        if assigned[i] != -1:
            continue
        group_ids = [i]
        for j in range(i + 1, len(clusters)):
            if assigned[j] != -1:
                continue
            overlap = len(entry_kw[i] & entry_kw[j])
            if overlap >= 2:
                group_ids.append(j)
        if len(group_ids) > 1:
            group_idx = len(groups)
            for k in group_ids:
                assigned[k] = group_idx
            rep = clusters[group_ids[0]]["cluster_title"]
            source_count = sum(clusters[k].get("source_count", 1) for k in group_ids)
            groups.append({
                "name": rep[:50],
                "name_zh": rep[:50],
                "entry_ids": group_ids,
                "density": source_count,
                "narrative": f"{len(group_ids)} related entries",
                "R": 1, "R_reason": "(heuristic)",
                "S": 1, "S_reason": "(heuristic)",
                "T": 1, "T_reason": "(heuristic)",
                "U": 1, "U_reason": "(heuristic)",
                "H": 2 if source_count >= 5 else 1,
                "H_reason": f"{source_count} source articles across {len(group_ids)} entries",
                "bettable": source_count >= 3,
                "suggested_question": None,
                "resolution_source": "",
                "clusters": [clusters[k] for k in group_ids],
            })

    # Keep the no-LLM path useful for mock runs and low-dependency demos:
    # promote the strongest remaining SourceIntel hotspots as standalone topics.
    remaining = [i for i, a in enumerate(assigned) if a == -1]
    remaining.sort(key=lambda i: clusters[i].get("source_count", 1), reverse=True)
    for i in remaining[:max(0, 15 - len(groups))]:
        c = clusters[i]
        source_count = c.get("source_count", 1)
        if source_count < 2:
            continue
        assigned[i] = len(groups)
        title = c["cluster_title"]
        groups.append({
            "name": title[:50],
            "name_zh": title[:50],
            "entry_ids": [i],
            "density": source_count,
            "narrative": f"{source_count} evidence items in one SourceIntel hotspot",
            "R": 1, "R_reason": "(heuristic singleton)",
            "S": 1, "S_reason": "(heuristic singleton)",
            "T": 1, "T_reason": "(heuristic singleton)",
            "U": 1, "U_reason": "(heuristic singleton)",
            "H": 2 if source_count >= 5 else 1,
            "H_reason": f"{source_count} source articles",
            "bettable": source_count >= 3,
            "suggested_question": None,
            "resolution_source": "",
            "clusters": [c],
        })

    noise = [i for i, a in enumerate(assigned) if a == -1]
    if len(groups) > 15:
        groups.sort(key=lambda g: g.get("density", 0), reverse=True)
        dropped_groups = groups[15:]
        groups = groups[:15]
        noise.extend(
            entry_id
            for group in dropped_groups
            for entry_id in group.get("entry_ids", [])
        )
        noise = sorted(set(noise))

    return {
        "region": region_cfg.slug,
        "groups": groups,
        "noise": noise,
        "total_entries": len(clusters),
        "clustered_at": dt.datetime.now().isoformat(),
    }


# ============================================================
# Convert group results to scored_topics format for reporter
# ============================================================

def groups_to_scored_topics(cluster_result: Dict) -> List[Dict]:
    """Convert LLM cluster groups to the scored_topics format
    expected by reporter.generate_report().

    This creates synthetic topic + signals + scores dicts so we
    can reuse the existing Excel reporter without modification.
    """
    scored = []
    for group in cluster_result.get("groups", []):
        # Synthetic topic object
        topic = {
            "topic_id": _slugify(group["name"]),
            "topic_name": group.get("name_zh") or group["name"],
            "category": "discovered",
            "cadence": "one-shot",
            "resolution": {
                "primary_source": group.get("resolution_source", ""),
                "primary_url": "",
                "dispute_risk": "medium",
            },
            "market_templates": [
                {
                    "type": "binary",
                    "question_template": group.get("suggested_question") or "",
                }
            ] if group.get("bettable") else [],
            "canonical_entities": [],
            "queries": {},
        }

        # Synthetic signals: aggregate sub-articles from member clusters
        gnews_en = []
        for c in group.get("clusters", []):
            for art in c.get("sub_articles", []):
                gnews_en.append({
                    "title": art["title"],
                    "source": art.get("source", ""),
                    "link": art.get("link", ""),
                })
        signals = {
            "gnews_en": gnews_en,
            "gnews_tl": [],
            "reddit": [],
        }

        # Use LLM-provided RSTUH directly
        R = {"score": group.get("R", 0), "reason": group.get("R_reason", "")}
        S = {"score": group.get("S", 0), "reason": group.get("S_reason", ""),
             "proposed_source": group.get("resolution_source", "")}
        T = {"score": group.get("T", 0), "reason": group.get("T_reason", "")}
        U = {"score": group.get("U", 0), "reason": group.get("U_reason", ""),
             "implied_prob": None}
        H = {
            "score": group.get("H", 0),
            "reason": group.get("H_reason", f"density={group.get('density',0)}"),
            "metrics": {
                "gnews_en": len(gnews_en),
                "gnews_tl": 0,
                "reddit": 0,
                "bilingual_hot": False,
            },
        }

        total = R["score"] + S["score"] + T["score"] + U["score"] + H["score"]
        veto = [d for d, sc in [("R", R), ("S", S), ("T", T), ("U", U), ("H", H)]
                if sc["score"] == 0]

        import math
        gn = len(gnews_en)
        heat_score = round(min(math.log1p(gn) / math.log1p(30), 1.0) * 0.9, 2)

        disposition = _decide_disposition(total, veto, heat_score, H["score"])

        scores = {
            "R": R, "S": S, "T": T, "U": U, "H": H,
            "total": total,
            "veto_dimensions": veto,
            "disposition": disposition,
            "heat_score": heat_score,
            "scored_at": dt.datetime.now().isoformat(),
            "suggested_market_question": group.get("suggested_question"),
            # Extra cluster metadata
            "density": group.get("density", 0),
            "narrative": group.get("narrative", ""),
        }

        scored.append({"topic": topic, "signals": signals, "scores": scores})

    return scored


def _slugify(name: str) -> str:
    import re
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40]


def _decide_disposition(total, veto, heat_score, H_score):
    has_su_veto = ("S" in veto) or ("U" in veto)
    if has_su_veto and heat_score >= 0.5:
        return "DROP_BUT_DIGEST"
    if veto and total <= 4:
        return "DROP"
    if not veto and total >= 9:
        return "TOP"
    if not veto and 7 <= total <= 8:
        return "CANDIDATE"
    if 5 <= total <= 6:
        return "WATCH"
    if total >= 6 and veto == ["T"]:
        return "WATCH"
    return "DROP"


# ============================================================
# Save / Load cluster results
# ============================================================

def save_cluster_result(result: Dict, output_dir: str,
                        region: RegionConfig | str | None = None) -> str:
    from pathlib import Path
    region_cfg = region if isinstance(region, RegionConfig) else get_region(region)
    out_dir = Path(output_dir)
    if region_cfg.reports_subdir:
        out_dir = out_dir / region_cfg.reports_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    path = out_dir / f"clusters_{today}.json"
    # Don't serialize the full clusters list (too large); save summary
    summary = {
        "region": result.get("region", region_cfg.slug),
        "clustered_at": result["clustered_at"],
        "total_entries": result["total_entries"],
        "noise_count": len(result.get("noise", [])),
        "groups": [
            {k: v for k, v in g.items() if k != "clusters"}
            for g in result.get("groups", [])
        ],
        "noise": result.get("noise", []),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return str(path)
