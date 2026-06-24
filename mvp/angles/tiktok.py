"""TikTokAngle: viral creator persona that wraps real markets in clickbait.

Generates 1-3 markets per cluster framed as TikTok-grade hook + emoji,
but the underlying question is still a real, future-checkable yes/no with
a citable resolver. Clickbait wrapper, serious substance.

If a cluster genuinely has no viral hook (pure technical / niche local /
no shareable angle), the model returns an empty array with drop_reason.

Stored on each group as g.tiktok_angles (array), same shape as
g.reddit_angles. Runs in PHASE_2.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from regions import RegionConfig

from .base import clip, generate_content_with_retry, parse_json_response, safe_url


TIKTOK_ANGLE_PROMPT_TEMPLATE = """\
You are a top TikTok creator with 1M+ followers covering {country_name}
news. Your craft: turn boring news topics into market questions that get
viewed, shared, and bet on. Your hooks are sharp, your titles use emoji
surgically (1-2 max), your framing creates anticipation by challenging
what the audience already assumes.

But you respect the audience: every question is a REAL future event with
an objective yes/no answer and a citable resolver. Clickbait wrapper,
serious substance. Never lie. Never bait without a real question.

Today is {date}. Country: {country_name}.

For EACH group, propose between ONE and THREE viral market angles in
your own voice. If a topic genuinely has no viral hook -- purely
technical, very niche local, no shareable angle that holds up to
scrutiny -- emit an empty array with drop_reason. Quality over quantity.

How many angles per group?
- One angle is the right default. Use 2-3 only when the group has
  multiple genuinely distinct sub-storylines (different people, events,
  or markets) that each deserve their own hook. Give each angle a short
  Chinese `subtopic` label.
- HARD CAP: never exceed 3 angles per group.

Voice rules (hard):
- Allowed:
  * 1-2 emoji per question, used surgically as a hook signal
    (🔥 📢 ⚡ 🚨 💸 🏀 🎬 🎤 ☔ etc.)
  * Strong opening hook ("All of PH wonders...", "比 X 更狠的是...",
    "你以为只是 Y，结果...", "0-3 落后能逆转吗")
  * Challenging audience assumptions, contrasting two outcomes
  * Mild dramatic framing tied to the actual stakes
- Forbidden:
  * Lies / vague claims / "you won't believe" with no substance
  * Actual jokes, puns, 段子, personal mockery
  * Emoji spam (3+ per question)
  * Hype without a real future-checkable question
  * Snide / cynical tone
- The question itself MUST end with "?" and have:
  * An objective yes/no answer
  * A specific deadline or event window
  * A real citable resolver

Resolution-source rules (identical to the serious analyst's):
- The `url` MUST point at a real, currently-existing public resource:
  official .gov.ph / .gov.id agency pages, public statistical or trends
  services, or the verified official social-media accounts of named
  agencies or organizations.
- The `source` string names that resource recognizably.
- No real resolver exists? Skip that angle. If the whole group has no
  viral angle with a real resolver, emit empty `angles` + drop_reason.
- NEVER invent URLs.

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
          "question_en": "English clickbait-hook + real question ending in ?",
          "question_zh": "中文 爆款钩子 + 真实问题，以 ？结尾",
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


class TikTokAngle:
    name = "tiktok"

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

        prompt = TIKTOK_ANGLE_PROMPT_TEMPLATE.format(
            date=dt.date.today().isoformat(),
            country_name=region_cfg.country_name,
            groups=_build_tiktok_input(groups),
        )
        response = generate_content_with_retry(
            client, model, prompt, usage_label="tiktok_angle"
        )
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
            group["tiktok_angles"] = clean_angles
            stats["attached"] += 1
            stats["angle_count"] += len(clean_angles)
        return stats


def _build_tiktok_input(groups: List[Dict]) -> str:
    """Same shape as reddit input -- texture for the hook + the underlying
    real market signal."""
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
            f"topic_type={group.get('topic_type', '')}",
            f"narrative={clip(group.get('narrative', ''), 220)}",
            f"primary_question={clip(str(group.get('suggested_question') or ''), 180)}",
            "sample_titles=" + " | ".join(sample_titles),
            "sample_summaries=" + " || ".join(sample_summaries),
            "keywords=" + ", ".join(keywords_set[:6]),
        ])
        blocks.append(block)
    return "\n\n".join(blocks)
