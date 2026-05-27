"""RedditAngle: 10-year r/PredictionMarkets lurker persona.

Generates 1-3 dry-wit / lateral observation market angles per cluster.
Each angle has an optional `subtopic` label so groups bundling multiple
distinct sub-storylines (e.g. three different senators in one cluster)
can get one angle per sub-storyline rather than a single angle that
covers only one.

Stored on each group as g.reddit_angles (array). Legacy flat fields
(reddit_question, reddit_question_zh, reddit_resolution_source,
reddit_resolution_url) are also populated from the first angle so older
archive HTML keeps rendering one block.

Runs in PHASE_2 (after group["clusters"] is attached) because the prompt
input pulls from cluster_title / summary / keywords.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from regions import RegionConfig

from .base import clip, generate_content_with_retry, parse_json_response, safe_url


REDDIT_ANGLE_PROMPT_TEMPLATE = """\
You have lurked Reddit for ten years. Your feed sprawls across
prediction-market communities, regional / local-culture threads, and
data-visualization corners. You read the news but never take the official
narrative at face value. You like noticing the small observable signals
nobody is bothering to track.

Today is {date}. Country: {country_name}.

The serious analyst has already produced a primary market question for each
topic group below. Your job: for EACH group, propose between ONE and THREE
second-market angles in your own voice -- dry-wit, lateral, observational.

How many angles per group?
- Most groups are about one story being covered from several angles.
  ONE angle is the right answer for those.
- Some groups bundle DISTINCT sub-storylines under one umbrella name
  (different actors, different legal cases, different events linked by
  theme but not by causality -- e.g. "Senate plunder + ICC arrest +
  gun-permit revocation against different senators"). For those, propose
  ONE angle PER sub-storyline, up to 3 total. Give each angle a short
  Chinese `subtopic` label naming which sub-storyline it covers.
- HARD CAP: never exceed 3 angles per group.

Approach each topic from scratch. Do NOT follow a template. For every
angle, ask yourself fresh:
- What numeric or observable signal would catch this story from the side?
- What is nobody bothering to count here?
- Where is the gap between the official narrative and what you'd actually see?
- What single, specific, future-checkable thing best captures the tension?
- Could this be answered by waiting for an event, a non-event, a ratio,
  a ranking, a threshold, a cadence change, a document appearing, a phrase
  being used or avoided, a counter resetting, a comparison crossing over?

You bet on the trace something leaves, not on the headline conclusion.
Across the batch AND within a group's multi-angle list, vary your angle
shapes -- if two angles would naturally produce the same shape, force
yourself to find a different shape for the second.

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
- Every angle's `url` MUST point at a real, currently-existing public
  resource. Acceptable shapes: official government / regulatory agency
  websites in the relevant country, public statistical or trends services,
  and the verified official social-media accounts of named agencies or
  organizations.
- The `source` string must name that resource in a way a reader can
  recognize.
- No real resolver exists for an angle? Skip that angle (do NOT include
  it in the array). If no resolver exists for ANY angle in the group,
  emit an empty `angles` array and set `drop_reason`.
- NEVER invent URLs. Unsure whether a URL truly exists? Skip that angle.

Topic groups:
{groups}

OUTPUT: strict JSON only, no markdown fences, no extra prose.

{{
  "groups": [
    {{
      "broad_index": <int, MUST match the input index>,
      "angles": [
        {{
          "subtopic": "短中文标签 naming which sub-storyline this angle covers, or null if the group is one unified story",
          "question_en": "English question",
          "question_zh": "中文问题",
          "source": "Human-readable source name",
          "url": "https://..."
        }}
      ],
      "drop_reason": "short reason when angles array is empty, otherwise null"
    }}
  ]
}}
"""


_CAP = 3


class RedditAngle:
    name = "reddit"

    def generate(
        self,
        groups: List[Dict],
        client,
        model: str,
        region_cfg: RegionConfig,
    ) -> Dict[str, int]:
        stats = {"attached": 0, "total": len(groups), "angle_count": 0}
        if not groups:
            return stats

        prompt = REDDIT_ANGLE_PROMPT_TEMPLATE.format(
            date=dt.date.today().isoformat(),
            country_name=region_cfg.country_name,
            groups=_build_reddit_input(groups),
        )
        response = generate_content_with_retry(client, model, prompt)
        result = parse_json_response(response.text)

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
            raw_angles = item.get("angles") or []
            if not isinstance(raw_angles, list):
                continue
            clean_angles: List[Dict] = []
            for ang in raw_angles[:_CAP]:
                if not isinstance(ang, dict):
                    continue
                q_en = ang.get("question_en") or ang.get("question")
                q_zh = ang.get("question_zh")
                if not (q_en or q_zh):
                    continue
                src = ang.get("source") or ang.get("resolution_source")
                url = safe_url(ang.get("url") or ang.get("resolution_url"))
                subtopic = ang.get("subtopic")
                if isinstance(subtopic, str):
                    subtopic = subtopic.strip() or None
                else:
                    subtopic = None
                clean_angles.append({
                    "subtopic": subtopic,
                    "question_en": q_en,
                    "question_zh": q_zh,
                    "source": src,
                    "url": url,
                })
            if not clean_angles:
                continue
            group["reddit_angles"] = clean_angles
            first = clean_angles[0]
            group["reddit_question"] = first["question_en"]
            group["reddit_question_zh"] = first["question_zh"]
            group["reddit_resolution_source"] = first["source"]
            group["reddit_resolution_url"] = first["url"]
            stats["attached"] += 1
            stats["angle_count"] += len(clean_angles)
        return stats


def _build_reddit_input(groups: List[Dict]) -> str:
    """Build per-group input for the Reddit-angle prompt.

    Reads group["clusters"] -- the full SourceIntel cluster dicts attached
    upstream -- so this helper works both during the live pipeline AND when
    loading a saved clusters_*.json for backfill.
    """
    blocks = []
    for index, group in enumerate(groups):
        group_clusters = group.get("clusters") or []
        sample_titles: List[str] = []
        sample_summaries: List[str] = []
        keywords_set: List[str] = []
        for c in group_clusters[:5]:
            title = c.get("cluster_title") or ""
            if title:
                sample_titles.append(clip(title, 120))
        for c in group_clusters[:3]:
            summary = c.get("summary") or ""
            if summary:
                sample_summaries.append(clip(summary, 220))
            for kw in (c.get("keywords") or [])[:2]:
                if kw and str(kw) not in keywords_set:
                    keywords_set.append(str(kw))
            if len(keywords_set) >= 6:
                break
        block = "\n".join([
            f"[{index}] {group.get('name', '')} / {group.get('name_zh', '')}",
            f"narrative={clip(group.get('narrative', ''), 220)}",
            f"primary_question={clip(str(group.get('suggested_question') or ''), 180)}",
            f"market_hint={clip(str(group.get('market_hint') or ''), 140)}",
            "sample_titles=" + " | ".join(sample_titles),
            "sample_summaries=" + " || ".join(sample_summaries),
            "keywords=" + ", ".join(keywords_set[:6]),
        ])
        blocks.append(block)
    return "\n\n".join(blocks)
