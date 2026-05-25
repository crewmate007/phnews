"""
LLM-based topic clustering for SourceIntel entries.

Takes normalized SourceIntel hotspots, first groups them broadly for coverage,
then evaluates each group for prediction-market bettability.

Flow:
  SourceIntel hotspots → broad clusters → RSTUH scoring → report groups
"""
from __future__ import annotations
import json
import os
import re
import sys
import datetime as dt
import time
from typing import List, Dict, Optional

from regions import RegionConfig, get_region


# ============================================================
# LLM-based clustering (Gemini Flash)
# ============================================================

BROAD_CLUSTER_PROMPT_TEMPLATE = """\
You are a source-intelligence analyst covering {country_name}. Today is {date}.

Below are {n} SourceIntel hotspots collected today for {country_adjective} coverage.
Each entry has an ID, source label, source count, title, short summary, claims,
entities/keywords, and a possible prediction angle.

Source model:
- Treat Google News and Grok/X as two parallel intelligence lanes.
- Google News is stronger for publisher-confirmed coverage and cross-source
  corroboration.
- Grok/X is stronger for social heat, emerging controversy, rumor velocity,
  on-the-ground reports, and topics that mainstream news has not yet clustered.
- Do not treat Grok/X as a weak duplicate of Google News. If a Grok/X entry is
  a distinct local political, legal, economic, disaster, security, or social
  controversy topic, keep it visible as its own 1-entry cluster unless it truly
  describes the same event/outcome as another entry.
- If a cluster mixes both lanes, make the narrative explain the combined signal:
  "publisher coverage + social discussion" or similar.

YOUR TASK:
Create broad coverage clusters before any final market selection.

Target {min_groups}–{max_groups} topic clusters.

Rules:
- Prefer semantic separation over neat large buckets.
- Small but distinct topics with 1–3 entries should remain separate.
- Merge entries only when they share the same real-world event, institution,
  actor, market variable, policy decision, sports competition, court case,
  disaster, health outbreak, or future outcome.
- Do not create generic catch-all groups like "Sports", "Technology",
  "Local Issues", "Business News", "Entertainment", "Global Political and
  Economic Issues", "Global Sports News", "Science Discoveries", or "Product
  Launches". Split those by specific event/company/league/agency/outcome.
- A group with more than 6 entries is allowed only when all entries are about
  the same named event/outcome or recurring data series. Otherwise split it.
- Do not merge unrelated countries merely because they are "global" or
  "international". Iran conflict, Thailand visa rules, Taiwan diplomacy, and
  US indictments are separate topics unless a single outcome connects them.
- Preserve local political, legal, economic, weather, health, security, and
  infrastructure topics even if they have lower volume than global sports or
  entertainment stories.
- An entry may appear in at most one cluster.
- Use "noise" only for entries that are truly unusable, duplicate residue, or
  too vague to connect to a real-world topic. Do not put an entry in noise just
  because it is small.

ENTRIES:
{entries}

OUTPUT: strict JSON only, no markdown fences, no extra text.

{{
  "groups": [
    {{
      "name": "specific topic name (English, ≤8 words)",
      "name_zh": "中文话题名（≤10字）",
      "entry_ids": [0, 5, 12],
      "density": <int, number of entries in this group>,
      "narrative": "1 concise sentence describing the common real-world topic",
      "narrative_zh": "中文摘要，1句",
      "topic_type": "politics|legal|economy|security|weather|health|infrastructure|technology|sports|entertainment|science|world|local|other",
      "source_mix": {{"google_news": 2, "x_grok": 1}},
      "market_hint": "most natural future outcome, or null if mostly digest"
    }}
  ],
  "noise": [<entry_ids not assigned to any group>]
}}
"""


SCORE_PROMPT_TEMPLATE = """\
You are a prediction-market analyst covering {country_name}. Today is {date}.

Below are broad topic clusters created from SourceIntel hotspots. Your task is
to score every cluster for prediction-market usefulness. Do not merge clusters,
drop clusters, or invent new clusters. Return one scored object per input cluster.

Region discipline:
- The market question must be relevant to {country_name} or to a genuinely
  global outcome.
- If a cluster is mainly another country's domestic policy, central bank,
  local election, local sports league, local court case, or local company
  story with no clear {country_name} relevance, mark it as digest/watch:
  bettable=false, suggested_question=null, suggested_question_zh=null.
- Use {country_name} or global authoritative sources for resolvable questions.
  Do not use another country's domestic regulator or central bank as the
  resolver for a {country_name} page unless the topic is explicitly about a
  cross-border/global market outcome.

CLUSTERS:
{groups}

OUTPUT: strict JSON only, no markdown fences, no extra text.

{{
  "groups": [
    {{
      "broad_index": <int, index from the input cluster>,
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
      "BDLT": {{
        "B": <0|1|2>,
        "B_reason": "bet demand: would local DigiPlus-style users want to take a side?",
        "D": <0|1|2>,
        "D_reason": "disagreement: are there plausible buyers on both YES and NO?",
        "L": <0|1|2>,
        "L_reason": "local hook: is this familiar and emotionally relevant to local users?",
        "T": <0|1|2>,
        "T_reason": "timeliness: is settlement soon enough to feel playable?"
      }},
      "why_users_bet": "1 short reason this might attract real-money local bettors",
      "bettable": <true|false>,
      "suggested_question": "Will ... by ...? (null if not bettable)",
      "suggested_question_zh": "中文预测市场问题（不可下注则为 null）",
      "resolution_source": "specific official or authoritative source",
      "disposition_hint": "top|candidate|watch|digest|drop"
    }}
  ]
}}

SCORING GUIDE:
- R=2: clear yes/no outcome with objective criteria (e.g. "Will BSP cut by 25bp?")
- R=1: outcome exists but boundary is fuzzy
- R=0: outcome is purely subjective or has no defined endpoint
- S=2: official government/regulatory body, court, league, exchange, company, or
  tournament body announces result
- S=1: reputable media consensus, or official source exists but is not clean
- S=0: no clear authoritative resolver
- T=2: specific date, deadline, meeting, recurring cadence, or tournament window
- T=1: approximate deadline (this quarter, this month)
- T=0: open-ended, no deadline
- U=2: outcome is genuinely in doubt, implied probability 25%–75%
- U=1: one side heavily favored but not certain
- U=0: outcome is essentially decided / a sure thing
- H=2: multiple sources, social discussion, or cross-section coverage
- H=1: 2–4 evidence items, limited social discussion
- H=0: single weak source or very low interest

BDLT GUIDE, optimized for local DigiPlus-like betting demand:
- B=2: strong real-money betting appeal; familiar rivalry, sports, prices,
  lotto, disaster, celebrity, or political drama. B=1: niche but playable.
  B=0: informative but unlikely to make users bet.
- D=2: both YES and NO have emotionally/plausibly motivated buyers. D=1:
  some uncertainty but one side dominates. D=0: boring, settled, or one-sided.
- L=2: directly local and familiar to everyday users. L=1: indirect local
  effect. L=0: foreign/abstract with little local hook.
- T=2: settles in days/weeks or at a known event. T=1: this quarter/season.
  T=0: long, vague, or open-ended.

Important:
- A cluster can be valuable digest even when it is not bettable.
- Sports and entertainment can be bettable if the event has an official result
  and a future time window; otherwise mark digest/watch.
- Local politics, legal processes, economic policy, health outbreaks, weather,
  security, and infrastructure should get careful market-question treatment.
"""


LEGACY_CLUSTER_PROMPT_TEMPLATE = """\
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


# ============================================================
# Reddit-style dry-wit angle (secondary market question)
# ============================================================

REDDIT_ANGLE_PROMPT_TEMPLATE = """\
You have lurked Reddit for ten years. Your feed sprawls across
prediction-market communities, regional / local-culture threads, and
data-visualization corners. You read the news but never take the official
narrative at face value. You like noticing the small observable signals
nobody is bothering to track.

Today is {date}. Country: {country_name}.

The serious analyst has already produced a primary market question for each
topic group below. Your job: for EACH group, propose ONE second market
angle in your own voice -- a dry-wit, lateral, observational angle.

Approach each topic from scratch. Do NOT follow a template. For every
group, ask yourself fresh:
- What numeric or observable signal would catch this story from the side?
- What is nobody bothering to count here?
- Where is the gap between the official narrative and what you'd actually see?
- What single, specific, future-checkable thing best captures the tension?
- Could this be answered by waiting for an event, a non-event, a ratio,
  a ranking, a threshold, a cadence change, a document appearing, a phrase
  being used or avoided, a counter resetting, a comparison crossing over?

You bet on the trace something leaves, not on the headline conclusion.
Across the batch, vary your angles -- if two consecutive groups would
naturally produce the same shape, force yourself to find a different
shape for the second.

Voice rules (hard):
- Allowed: any cool, observant angle. Counting, comparing, tracking a
  metric over time, watching for a specific document or post, noticing
  what an official does NOT say, ratios, rankings, thresholds, cadence
  shifts.
- Forbidden: jokes, puns, 段子, 哈哈/笑死/绷不住/笑点, sarcasm aimed at
  individuals or groups, emoji-heavy framing, condescension.
- You are careful side-eye, NOT roast.

Resolution-source rules (hardest, this is what separates real markets
from shower thoughts):
- The reddit_resolution_url MUST point at a real, currently-existing
  public resource. Acceptable shapes are: official government /
  regulatory agency websites in the relevant country, public statistical
  or trends services, and the verified official social-media accounts of
  named agencies or organizations.
- The reddit_resolution_source string must name that resource in a way a
  reader can recognize.
- No real resolver exists for this topic? Return null for the entire
  angle and set drop_reason. NEVER invent URLs. Unsure whether a URL
  truly exists? Return null + drop_reason="uncertain resolver".

Topic groups:
{groups}

OUTPUT: strict JSON only, no markdown fences, no extra prose.

{{
  "groups": [
    {{
      "broad_index": <int, MUST match the input index>,
      "reddit_question": "English question, or null",
      "reddit_question_zh": "中文问题，or null",
      "reddit_resolution_source": "Human-readable source name, or null",
      "reddit_resolution_url": "https://... or null",
      "drop_reason": "short reason when all null, otherwise null"
    }}
  ]
}}
"""


_REDDIT_URL_ALLOWLIST = re.compile(
    r"^https?://("
    r"[a-z0-9-]+\.gov\.ph(?:/|$)"
    r"|[a-z0-9-]+\.gov\.id(?:/|$)"
    r"|(?:www\.)?bsp\.gov\.ph(?:/|$)"
    r"|(?:www\.)?doe\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dof\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dbm\.gov\.ph(?:/|$)"
    r"|(?:www\.)?neda\.gov\.ph(?:/|$)"
    r"|(?:www\.)?pagasa\.dost\.gov\.ph(?:/|$)"
    r"|(?:www\.)?phivolcs\.dost\.gov\.ph(?:/|$)"
    r"|(?:www\.)?comelec\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dilg\.gov\.ph(?:/|$)"
    r"|(?:www\.)?congress\.gov\.ph(?:/|$)"
    r"|(?:www\.)?senate\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dswd\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dof\.gov\.ph(?:/|$)"
    r"|(?:www\.)?meralco\.com\.ph(?:/|$)"
    r"|(?:www\.)?ngcp\.ph(?:/|$)"
    r"|(?:www\.)?pse\.com\.ph(?:/|$)"
    r"|(?:www\.)?bi\.go\.id(?:/|$)"
    r"|(?:www\.)?kemenkeu\.go\.id(?:/|$)"
    r"|(?:www\.)?bps\.go\.id(?:/|$)"
    r"|(?:www\.)?bmkg\.go\.id(?:/|$)"
    r"|(?:www\.)?idx\.co\.id(?:/|$)"
    r"|(?:www\.)?kpu\.go\.id(?:/|$)"
    r"|(?:www\.)?x\.com/[A-Za-z0-9_]+"
    r"|(?:www\.)?twitter\.com/[A-Za-z0-9_]+"
    r"|(?:www\.)?facebook\.com/[A-Za-z0-9._-]+"
    r"|(?:www\.)?youtube\.com/@[A-Za-z0-9._-]+"
    r"|trends\.google\.com(?:/|$)"
    r"|trends24\.in/(?:philippines|indonesia)"
    r")",
    re.IGNORECASE,
)


def _build_reddit_input(groups: List[Dict]) -> str:
    """Build the per-group input for the Reddit-angle prompt.

    Reads group["clusters"] (full SourceIntel cluster dicts attached by
    cluster_with_llm at line ~319), so this helper works both during the live
    pipeline AND when loading a saved clusters_*.json for backfill.
    """
    blocks = []
    for index, group in enumerate(groups):
        group_clusters = group.get("clusters") or []
        sample_titles = []
        sample_summaries = []
        keywords_set: List[str] = []
        for c in group_clusters[:5]:
            title = c.get("cluster_title") or ""
            if title:
                sample_titles.append(_clip(title, 120))
        for c in group_clusters[:3]:
            summary = c.get("summary") or ""
            if summary:
                sample_summaries.append(_clip(summary, 220))
            for kw in (c.get("keywords") or [])[:2]:
                if kw and str(kw) not in keywords_set:
                    keywords_set.append(str(kw))
            if len(keywords_set) >= 6:
                break
        block = "\n".join([
            f"[{index}] {group.get('name', '')} / {group.get('name_zh', '')}",
            f"narrative={_clip(group.get('narrative', ''), 220)}",
            f"primary_question={_clip(str(group.get('suggested_question') or ''), 180)}",
            f"market_hint={_clip(str(group.get('market_hint') or ''), 140)}",
            "sample_titles=" + " | ".join(sample_titles),
            "sample_summaries=" + " || ".join(sample_summaries),
            "keywords=" + ", ".join(keywords_set[:6]),
        ])
        blocks.append(block)
    return "\n\n".join(blocks)


def generate_reddit_angles(
    groups: List[Dict],
    client,
    model: str,
    region_cfg: RegionConfig,
) -> Dict[str, int]:
    """Attach reddit_* fields to each group in-place via one batched Gemini call.

    Returns {"attached": int, "total": int}. Never raises — on parse or API
    failure the caller's groups are left untouched and stats reflect zero.
    Hallucinated URLs are dropped via _REDDIT_URL_ALLOWLIST; source label is
    preserved as plain text in that case.
    """
    stats = {"attached": 0, "total": len(groups)}
    if not groups:
        return stats

    prompt = REDDIT_ANGLE_PROMPT_TEMPLATE.format(
        date=dt.date.today().isoformat(),
        country_name=region_cfg.country_name,
        groups=_build_reddit_input(groups),
    )
    response = _generate_content_with_retry(client, model, prompt)
    result = _parse_json_response(response.text)

    by_index: Dict[int, Dict] = {}
    for item in result.get("groups", []):
        if not isinstance(item, dict):
            continue
        idx = item.get("broad_index")
        if isinstance(idx, int):
            by_index[idx] = item

    for i, group in enumerate(groups):
        item = by_index.get(i)
        if not item:
            continue
        q_en = item.get("reddit_question")
        q_zh = item.get("reddit_question_zh")
        if not (q_en or q_zh):
            continue  # legitimately empty angle; skip silently
        src = item.get("reddit_resolution_source")
        url = item.get("reddit_resolution_url")
        if url and not _REDDIT_URL_ALLOWLIST.match(str(url).strip()):
            url = None  # drop unsafe URL, keep source name as text
        group["reddit_question"] = q_en
        group["reddit_question_zh"] = q_zh
        group["reddit_resolution_source"] = src
        group["reddit_resolution_url"] = url
        stats["attached"] += 1
    return stats


# ============================================================


def cluster_with_llm(clusters: List[Dict], api_key: str,
                     region: RegionConfig | str | None = None,
                     model: str = "gemini-flash-latest") -> Dict:
    """Cluster SourceIntel entries broadly, then score each group with Gemini.

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

    today = dt.date.today().isoformat()
    min_groups, max_groups = _target_group_range(len(clusters))

    broad_prompt = BROAD_CLUSTER_PROMPT_TEMPLATE.format(
        date=today,
        n=len(clusters),
        min_groups=min_groups,
        max_groups=max_groups,
        entries=_build_broad_entries(clusters),
        country_name=region_cfg.country_name,
        country_adjective=region_cfg.country_adjective,
    )

    broad_response = _generate_content_with_retry(client, model, broad_prompt)
    broad_result = _parse_json_response(broad_response.text)
    broad_result = _normalize_broad_result(broad_result, clusters)
    broad_result = _split_catchall_groups(broad_result, clusters)
    broad_result = _ensure_minimum_broad_groups(broad_result, clusters, min_groups)
    broad_result = _promote_excess_noise(broad_result, clusters)

    score_prompt = SCORE_PROMPT_TEMPLATE.format(
        date=today,
        groups=_build_score_groups(broad_result["groups"], clusters),
        country_name=region_cfg.country_name,
    )
    score_response = _generate_content_with_retry(client, model, score_prompt)
    score_result = _parse_json_response(score_response.text)
    result = _merge_scored_groups(broad_result, score_result, clusters)
    _apply_region_relevance_guard(result, region_cfg)
    result["region"] = region_cfg.slug
    result["total_entries"] = len(clusters)
    result["clustered_at"] = dt.datetime.now().isoformat()
    result["cluster_pipeline"] = "broad_then_score"
    result["target_group_range"] = [min_groups, max_groups]
    result["entries"] = [_compact_entry(i, cluster) for i, cluster in enumerate(clusters)]

    for group in result.get("groups", []):
        group["clusters"] = [clusters[i] for i in group.get("entry_ids", [])
                             if i < len(clusters)]

    # Reddit-style dry-wit angle: best-effort, never blocks the serious pipeline.
    # Toggle off in CI by setting PHNEWS_REDDIT_ANGLES=0.
    if os.environ.get("PHNEWS_REDDIT_ANGLES", "1") != "0":
        try:
            stats = generate_reddit_angles(
                result.get("groups", []),
                client,
                model,
                region_cfg,
            )
            print(
                f"[INFO] Reddit angles attached: {stats['attached']}/{stats['total']}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"[WARN] Reddit angles skipped: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    return result


def _target_group_range(n_entries: int) -> tuple[int, int]:
    if n_entries >= 100:
        return 25, 60
    if n_entries >= 60:
        return 18, 40
    if n_entries >= 30:
        return 12, 28
    return 6, 14


def _generate_content_with_retry(client, model: str, prompt: str,
                                 attempts: int = 4):
    """Retry transient Gemini overloads without hiding persistent failures."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return client.models.generate_content(model=model, contents=prompt)
        except Exception as exc:  # google-genai exposes multiple transient types.
            last_exc = exc
            message = str(exc).lower()
            status_code = getattr(exc, "status_code", None)
            transient = status_code in (429, 500, 502, 503, 504) or any(
                marker in message
                for marker in ("503", "429", "unavailable", "high demand", "timeout")
            )
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(5 * (2 ** attempt))
    raise last_exc


def _build_broad_entries(clusters: List[Dict]) -> str:
    lines = []
    for i, c in enumerate(clusters):
        claims = [a.get("title", "") for a in c.get("sub_articles", []) if a.get("title")]
        fields = [
            f"[{i}]",
            f"source={c.get('section', '')}",
            f"lane={c.get('source_lane') or c.get('source_name') or ''}",
            f"source_count={c.get('source_count', 0)}",
            f"rank={c.get('rank_score', '')}",
            f"title={_clip(c.get('cluster_title', ''), 170)}",
        ]
        if c.get("summary"):
            fields.append(f"summary={_clip(c.get('summary', ''), 220)}")
        if claims:
            fields.append(f"claims={_clip(' | '.join(claims[:3]), 260)}")
        if c.get("sources"):
            fields.append(f"entities={_clip(', '.join(str(s) for s in c.get('sources', [])[:8]), 140)}")
        if c.get("keywords"):
            fields.append(f"keywords={_clip(', '.join(str(k) for k in c.get('keywords', [])[:8]), 120)}")
        if c.get("prediction_angle"):
            fields.append(f"prediction_angle={_clip(c.get('prediction_angle', ''), 180)}")
        lines.append("\n".join(fields))
    return "\n\n".join(lines)


def _build_score_groups(groups: List[Dict], clusters: List[Dict]) -> str:
    blocks = []
    for index, group in enumerate(groups):
        entry_ids = [i for i in group.get("entry_ids", []) if isinstance(i, int) and 0 <= i < len(clusters)]
        titles = [_clip(clusters[i].get("cluster_title", ""), 120) for i in entry_ids[:8]]
        source_labels = sorted({clusters[i].get("section", "") for i in entry_ids})
        blocks.append("\n".join([
            f"[{index}] {group.get('name', '')} / {group.get('name_zh', '')}",
            f"type={group.get('topic_type', '')}",
            f"density={group.get('density', len(entry_ids))}",
            f"entry_ids={entry_ids}",
            f"sources={', '.join(source_labels[:6])}",
            f"narrative={_clip(group.get('narrative', ''), 220)}",
            f"market_hint={_clip(str(group.get('market_hint') or ''), 180)}",
            "sample_titles=" + " | ".join(titles),
        ]))
    return "\n\n".join(blocks)


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _parse_json_response(text: str) -> Dict:
    text = text.strip()
    if text.startswith("```"):
        text = text[3:]
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.lstrip("\r\n")
        end = text.rfind("```")
        if end != -1:
            text = text[:end]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Gemini occasionally emits trailing commas before } or ]; clean once and retry.
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", text))


def _normalize_broad_result(result: Dict, clusters: List[Dict]) -> Dict:
    used: set[int] = set()
    normalized_groups = []
    for group in result.get("groups", []):
        entry_ids = []
        for value in group.get("entry_ids", []):
            if not isinstance(value, int) or value < 0 or value >= len(clusters):
                continue
            if value in used:
                continue
            used.add(value)
            entry_ids.append(value)
        if not entry_ids:
            continue
        group = dict(group)
        group["entry_ids"] = entry_ids
        group["density"] = int(group.get("density") or len(entry_ids))
        normalized_groups.append(group)

    noise = {
        value for value in result.get("noise", [])
        if isinstance(value, int) and 0 <= value < len(clusters)
    }
    assigned = {entry_id for group in normalized_groups for entry_id in group["entry_ids"]}
    noise.update(i for i in range(len(clusters)) if i not in assigned)
    return {"groups": normalized_groups, "noise": sorted(noise)}


def _ensure_minimum_broad_groups(result: Dict, clusters: List[Dict],
                                 min_groups: int) -> Dict:
    groups = list(result.get("groups", []))
    noise = list(result.get("noise", []))
    if len(groups) >= min_groups or not noise:
        return result

    needed = min_groups - len(groups)
    noise.sort(
        key=lambda i: (
            clusters[i].get("rank_score") or 0,
            clusters[i].get("source_count") or 0,
        ),
        reverse=True,
    )
    promoted = noise[:needed]
    remaining_noise = noise[needed:]
    for entry_id in promoted:
        cluster = clusters[entry_id]
        title = cluster.get("cluster_title", "SourceIntel topic")
        summary = cluster.get("summary") or title
        groups.append({
            "name": _clip(title, 64),
            "name_zh": _clip(title, 32),
            "entry_ids": [entry_id],
            "density": 1,
            "narrative": _clip(summary, 220),
            "narrative_zh": _clip(summary, 120),
            "topic_type": "other",
            "market_hint": cluster.get("prediction_angle"),
        })
    return {"groups": groups, "noise": remaining_noise}


def _promote_excess_noise(result: Dict, clusters: List[Dict]) -> Dict:
    groups = list(result.get("groups", []))
    noise = [
        entry_id for entry_id in result.get("noise", [])
        if isinstance(entry_id, int) and 0 <= entry_id < len(clusters)
    ]
    max_noise = max(8, int(len(clusters) * 0.12))
    if len(noise) <= max_noise:
        return result

    noise.sort(
        key=lambda i: (
            clusters[i].get("rank_score") or 0,
            clusters[i].get("source_count") or 0,
        ),
        reverse=True,
    )
    promoted = noise[:len(noise) - max_noise]
    remaining_noise = noise[len(noise) - max_noise:]
    for entry_id in promoted:
        cluster = clusters[entry_id]
        title = cluster.get("cluster_title", "SourceIntel topic")
        title_zh = cluster.get("title_zh") or title
        summary = cluster.get("summary") or title
        summary_zh = cluster.get("summary_zh") or summary
        groups.append({
            "name": _compact_topic_name(title, max_len=58),
            "name_zh": _compact_topic_name(title_zh, max_len=28),
            "entry_ids": [entry_id],
            "density": 1,
            "narrative": _clip(summary, 220),
            "narrative_zh": _clip(summary_zh, 120),
            "topic_type": _infer_topic_type({}, cluster),
            "source_mix": {},
            "market_hint": cluster.get("prediction_angle"),
            "promoted_from_noise": True,
        })
    return {"groups": groups, "noise": remaining_noise}


_CATCHALL_NAME_TERMS = (
    "global political", "global economic", "political and economic",
    "international geopolitics", "global sports", "sports leagues",
    "sports news", "technology product", "product launches",
    "consumer electronics", "entertainment and celebrity",
    "celebrity news", "global health", "health and outbreaks", "health alerts",
    "space and science", "science milestones", "science discoveries", "public health initiatives",
    "personal legal and celebrity",
    "全球政经", "国际政经", "全球政治", "全球经济", "体育赛事",
    "体育新闻", "科技产品", "产品发布", "消费电子", "娱乐与名人",
    "全球健康", "疾病爆发", "太空与科学", "科学发现", "公共卫生倡议",
)


def _split_catchall_groups(result: Dict, clusters: List[Dict]) -> Dict:
    groups = []
    split_count = 0
    for group in result.get("groups", []):
        entry_ids = [
            entry_id for entry_id in group.get("entry_ids", [])
            if isinstance(entry_id, int) and 0 <= entry_id < len(clusters)
        ]
        if _is_catchall_group(group, len(entry_ids)):
            split_count += 1
            groups.extend(_specific_groups_from_entries(group, entry_ids, clusters))
        else:
            groups.append(group)

    normalized = {"groups": groups, "noise": result.get("noise", [])}
    if split_count:
        normalized["catchall_groups_split"] = split_count
    return normalized


def _is_catchall_group(group: Dict, density: int) -> bool:
    name_text = " ".join(str(group.get(key) or "") for key in (
        "name", "name_zh", "narrative", "narrative_zh",
    )).lower()
    has_generic_name = any(term in name_text for term in _CATCHALL_NAME_TERMS)
    if has_generic_name and density >= 2:
        return True
    if density > 6 and any(term in name_text for term in (
        "global", "international", "news", "updates", "issues", "trends",
        "developments", "全球", "国际", "新闻", "动态", "议题", "趋势",
    )):
        return True
    return False


def _specific_groups_from_entries(group: Dict, entry_ids: List[int],
                                  clusters: List[Dict]) -> List[Dict]:
    split_groups = []
    for entry_id in entry_ids:
        cluster = clusters[entry_id]
        title = cluster.get("cluster_title", "SourceIntel topic")
        title_zh = cluster.get("title_zh") or title
        summary = cluster.get("summary") or title
        summary_zh = cluster.get("summary_zh") or summary
        topic_type = _infer_topic_type(group, cluster)
        split_groups.append({
            "name": _compact_topic_name(title, max_len=58),
            "name_zh": _compact_topic_name(title_zh, max_len=28),
            "entry_ids": [entry_id],
            "density": 1,
            "narrative": _clip(summary, 220),
            "narrative_zh": _clip(summary_zh, 120),
            "topic_type": topic_type,
            "source_mix": {},
            "market_hint": cluster.get("prediction_angle"),
            "split_from": group.get("name") or group.get("name_zh"),
        })
    return split_groups


def _infer_topic_type(group: Dict, cluster: Dict) -> str:
    text = " ".join([
        str(group.get("topic_type") or ""),
        str(cluster.get("section") or ""),
        str(cluster.get("cluster_title") or ""),
        str(cluster.get("summary") or ""),
    ]).lower()
    if any(term in text for term in ("sport", "nba", "pba", "fifa", "football", "basketball")):
        return "sports"
    if any(term in text for term in ("entertainment", "celebrity", "actor", "singer", "movie", "concert")):
        return "entertainment"
    if any(term in text for term in ("health", "virus", "outbreak", "disease", "medical")):
        return "health"
    if any(term in text for term in ("ai", "tech", "software", "phone", "chip", "app")):
        return "technology"
    if any(term in text for term in ("market", "rate", "peso", "rupiah", "stock", "inflation", "price")):
        return "economy"
    if any(term in text for term in ("court", "legal", "trial", "indict", "icc")):
        return "legal"
    if any(term in text for term in ("senate", "minister", "president", "visa", "policy")):
        return "politics"
    if any(term in text for term in ("war", "defense", "missile", "security")):
        return "security"
    if any(term in text for term in ("storm", "flood", "typhoon", "weather", "climate")):
        return "weather"
    return group.get("topic_type") or "other"


def _compact_topic_name(title: str, max_len: int) -> str:
    cleaned = " ".join(str(title or "").split())
    for separator in (" - ", " | ", " — ", " – "):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
            break
    return _clip(cleaned, max_len)


def _merge_scored_groups(broad_result: Dict, score_result: Dict,
                         clusters: List[Dict]) -> Dict:
    scores_by_index = {
        item.get("broad_index"): item
        for item in score_result.get("groups", [])
        if isinstance(item.get("broad_index"), int)
    }
    groups = []
    for index, broad in enumerate(broad_result.get("groups", [])):
        scored = scores_by_index.get(index, {})
        group = dict(broad)
        for key in (
            "R", "R_reason", "S", "S_reason", "T", "T_reason",
            "U", "U_reason", "H", "H_reason", "bettable",
            "suggested_question", "suggested_question_zh",
            "resolution_source", "disposition_hint", "BDLT",
            "why_users_bet",
        ):
            if key in scored:
                group[key] = scored[key]
        _fill_missing_scores(group)
        group["density"] = len(group.get("entry_ids", []))
        _attach_source_metadata(group, clusters)
        _fill_missing_bdlt(group)
        groups.append(group)
    return {
        "groups": groups,
        "noise": broad_result.get("noise", []),
    }


def _attach_source_metadata(group: Dict, clusters: List[Dict]) -> None:
    entry_ids = [
        entry_id for entry_id in group.get("entry_ids", [])
        if isinstance(entry_id, int) and 0 <= entry_id < len(clusters)
    ]
    source_mix: Dict[str, int] = {}
    for entry_id in entry_ids:
        source = clusters[entry_id].get("source_name") or _source_from_section(
            clusters[entry_id].get("section", "")
        )
        source_mix[source] = source_mix.get(source, 0) + 1
    group["source_mix"] = {
        source: source_mix[source]
        for source in sorted(source_mix, key=lambda name: (name != "google_news", name))
    }
    group["source_labels"] = [
        _source_label(source, count)
        for source, count in group["source_mix"].items()
    ]

    ranked = sorted(
        entry_ids,
        key=lambda entry_id: (
            0 if (clusters[entry_id].get("source_name") == "x_grok") else 1,
            -(clusters[entry_id].get("rank_score") or 0),
        ),
    )
    group["source_examples"] = [
        _compact_entry(entry_id, clusters[entry_id])
        for entry_id in ranked[:6]
    ]


def _compact_entry(entry_id: int, cluster: Dict) -> Dict:
    return {
        "id": entry_id,
        "source": cluster.get("source_name") or _source_from_section(cluster.get("section", "")),
        "source_label": cluster.get("source_lane") or cluster.get("section", ""),
        "section": cluster.get("source_section") or cluster.get("section", ""),
        "title_en": cluster.get("cluster_title", ""),
        "title_zh": cluster.get("title_zh") or cluster.get("cluster_title", ""),
        "summary_en": _clip(cluster.get("summary", ""), 240),
        "summary_zh": _clip(cluster.get("summary_zh", ""), 180),
        "link": cluster.get("link", ""),
        "rank_score": cluster.get("rank_score"),
        "social_heat": cluster.get("social_heat", ""),
        "uncertainty": cluster.get("uncertainty", ""),
    }


def _source_from_section(section: str) -> str:
    if "x_grok" in section:
        return "x_grok"
    if "google_news" in section:
        return "google_news"
    return "source_intel"


def _source_label(source: str, count: int) -> str:
    names = {
        "google_news": "Google News",
        "x_grok": "Grok/X",
    }
    return f"{names.get(source, source)} {count}"


def _apply_region_relevance_guard(result: Dict, region: RegionConfig) -> None:
    """Prevent another country's domestic story from becoming the local market."""
    foreign_terms_by_region = {
        "ph": (
            "bank indonesia", "rupiah", "ihsg", "idx ", "jakarta", "indonesian ",
            "indonesia ", "ministry of finance of indonesia",
            "ministry of energy and mineral resources of indonesia",
        ),
        "id": (
            "bangko sentral", "bsp ", "philippine peso", "peso ", "comelec",
            "senate of the philippines", "supreme court of the philippines",
            "philippines ", "philippine ",
        ),
    }
    foreign_terms = foreign_terms_by_region.get(region.slug, ())
    if not foreign_terms:
        return

    for group in result.get("groups", []):
        question_text = " ".join(str(group.get(key) or "") for key in (
            "suggested_question", "suggested_question_zh", "resolution_source",
        )).lower()
        has_foreign_resolver = any(term in question_text for term in foreign_terms)
        if has_foreign_resolver:
            _mark_digest(
                group,
                f"Foreign domestic resolver is not suitable for {region.country_label_en} page.",
            )


def _mark_digest(group: Dict, reason: str) -> None:
    group["bettable"] = False
    group["suggested_question"] = None
    group["suggested_question_zh"] = None
    group["resolution_source"] = ""
    group["disposition_hint"] = "digest"
    group["R"] = min(group.get("R", 0), 1)
    group["S"] = min(group.get("S", 0), 1)
    group["T"] = min(group.get("T", 0), 1)
    group["R_reason"] = reason
    group["S_reason"] = reason
    group["T_reason"] = reason
    group["BDLT"] = {
        "B": min(group.get("BDLT", {}).get("B", 0), 1),
        "B_reason": reason,
        "D": min(group.get("BDLT", {}).get("D", 0), 1),
        "D_reason": reason,
        "L": 0,
        "L_reason": reason,
        "T": min(group.get("BDLT", {}).get("T", 0), 1),
        "T_reason": reason,
    }
    group["BDLT"]["total"] = sum(group["BDLT"][key] for key in ("B", "D", "L", "T"))


def _fill_missing_scores(group: Dict) -> None:
    for key in ("R", "S", "T", "U", "H"):
        value = group.get(key)
        group[key] = value if value in (0, 1, 2) else 0
        reason_key = f"{key}_reason"
        group.setdefault(reason_key, "")
    group.setdefault("bettable", False)
    group.setdefault("suggested_question", None)
    group.setdefault("suggested_question_zh", None)
    group.setdefault("resolution_source", "")


def _fill_missing_bdlt(group: Dict) -> None:
    raw = group.get("BDLT") if isinstance(group.get("BDLT"), dict) else {}
    inferred = _infer_bdlt(group)
    normalized = {}
    for key in ("B", "D", "L", "T"):
        value = raw.get(key)
        normalized[key] = value if value in (0, 1, 2) else inferred[key]
        reason_key = f"{key}_reason"
        normalized[reason_key] = raw.get(reason_key) or inferred[f"{key}_reason"]
    normalized["total"] = sum(normalized[key] for key in ("B", "D", "L", "T"))
    group["BDLT"] = normalized
    group.setdefault("why_users_bet", inferred["why_users_bet"])


def _infer_bdlt(group: Dict) -> Dict:
    text = " ".join(str(group.get(key) or "") for key in (
        "name", "name_zh", "narrative", "narrative_zh",
        "suggested_question", "suggested_question_zh", "topic_type",
    )).lower()
    text += " " + " ".join(
        str(item.get("title_en") or "") + " " + str(item.get("title_zh") or "")
        for item in group.get("source_examples", [])[:4]
    ).lower()
    topic_type = str(group.get("topic_type") or "").lower()
    rstuh_total = sum(group.get(key, 0) for key in ("R", "S", "T", "U", "H"))
    source_mix = group.get("source_mix", {})

    high_demand_terms = (
        "duterte", "marcos", "impeachment", "senate", "pba", "nba", "gilas",
        "pacquiao", "lotto", "jackpot", "peso", "rupiah", "fuel", "rice",
        "oil", "inflation", "rate", "bsp", "bank indonesia", "pvl", "fifa",
        "world cup", "typhoon", "flood", "volcano", "earthquake", "celebrity",
        "tiktok", "viral", "scandal", "菲律宾", "印尼", "杜特尔特", "马科斯",
        "弹劾", "比索", "印尼盾", "油价", "大米", "通胀", "彩票", "台风",
    )
    local_terms = (
        "philippine", "philippines", "filipino", "manila", "cebu", "pba",
        "bsp", "pagasa", "meralco", "pcso", "sara duterte", "marcos",
        "indonesia", "indonesian", "jakarta", "rupiah", "ihsg", "idx",
        "prabowo", "pertamina", "bank indonesia", "菲律宾", "印尼", "雅加达",
        "马尼拉", "杜特尔特", "马科斯", "普拉博沃", "印尼盾", "比索",
    )
    foreign_noise_terms = (
        "ronald mcdonald house new england", "kentucky primary",
        "hungary", "cuba", "lebanon", "gaza flotilla", "toyota corolla",
    )

    has_high_demand = any(term in text for term in high_demand_terms)
    has_local = any(term in text for term in local_terms)
    looks_foreign = any(term in text for term in foreign_noise_terms)

    if not group.get("bettable") and not has_high_demand:
        b = 0
    elif has_high_demand or topic_type in ("sports", "politics", "economy", "weather", "entertainment"):
        b = 2
    elif rstuh_total >= 7 or source_mix.get("x_grok"):
        b = 1
    else:
        b = 0

    d = 2 if group.get("U") == 2 else (1 if group.get("U") == 1 or group.get("bettable") else 0)
    l = 0 if looks_foreign else (2 if has_local else (1 if source_mix.get("x_grok") else 0))
    t = 2 if group.get("T") == 2 else (1 if group.get("T") == 1 else 0)

    why = "Local users know the actors and can take a side." if b >= 2 and l >= 2 else ""
    if not why and b >= 1:
        why = "Playable if framed with a clear near-term outcome."
    if not why:
        why = "Low expected betting demand."

    return {
        "B": b,
        "B_reason": "Measures whether local users would actually want to bet.",
        "D": d,
        "D_reason": "Uses uncertainty and likely two-sided demand.",
        "L": l,
        "L_reason": "Measures local familiarity and emotional hook.",
        "T": t,
        "T_reason": "Uses the market time window and settlement proximity.",
        "why_users_bet": why,
    }


def _clip(value: str, length: int) -> str:
    value = " ".join(str(value or "").split())
    if len(value) <= length:
        return value
    return value[:length - 1].rstrip() + "…"


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
    entries = result.get("entries") or _entries_from_groups(result.get("groups", []))
    source_counts = _source_counts(entries)
    # Don't serialize the full clusters list (too large); save summary
    summary = {
        "region": result.get("region", region_cfg.slug),
        "clustered_at": result["clustered_at"],
        "total_entries": result["total_entries"],
        "source_counts": source_counts,
        "cluster_pipeline": result.get("cluster_pipeline", "legacy"),
        "target_group_range": result.get("target_group_range"),
        "noise_count": len(result.get("noise", [])),
        "groups": [
            {k: v for k, v in g.items() if k != "clusters"}
            for g in result.get("groups", [])
        ],
        "noise": result.get("noise", []),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    inputs_path = out_dir / f"source_intel_inputs_{today}.json"
    inputs = {
        "region": result.get("region", region_cfg.slug),
        "date": today,
        "total_entries": len(entries),
        "source_counts": source_counts,
        "entries": entries,
    }
    with open(inputs_path, "w", encoding="utf-8") as f:
        json.dump(inputs, f, ensure_ascii=False, indent=2)
    return str(path)


def _entries_from_groups(groups: List[Dict]) -> List[Dict]:
    entries_by_id: dict[int, Dict] = {}
    for group in groups:
        for cluster in group.get("clusters", []):
            entry_id = cluster.get("id")
            if isinstance(entry_id, int):
                entries_by_id[entry_id] = _compact_entry(entry_id, cluster)
    return [entries_by_id[key] for key in sorted(entries_by_id)]


def _source_counts(entries: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for entry in entries:
        source = entry.get("source") or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return counts
