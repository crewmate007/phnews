"""SeriousAngle: institutional prediction-market analyst persona.

Generates 2-3 candidate market questions per cluster, each independently
scored on RSTUH + BDLT. Picks the highest-scoring candidate as the primary
(populates the flat g.suggested_question / g.R / g.BDLT / etc. fields the
rest of the system reads). All candidates are preserved under
g.serious_candidates for inspection and future "show alternatives" UI.

This was the only angle prior to v3. It is special because its scoring
drives card disposition (TOP / candidate / watch / drop), so it runs in
PHASE_1 (before region guard / cluster attach).
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import Dict, List

from regions import RegionConfig

from .base import (
    RESOLVER_URL_ALLOWLIST,
    clip,
    generate_content_with_retry,
    parse_json_response,
)


SCORE_PROMPT_TEMPLATE = """\
You are a prediction-market analyst covering {country_name}. Today is {date}.

Below are broad topic clusters created from SourceIntel hotspots. For each
cluster, PROPOSE 2-3 CANDIDATE market questions, each scored independently.
The system will pick the highest-scoring candidate to surface as the primary
market; the others are stored for inspection.

Why multiple candidates: a topic often supports several market shapes of
different quality (different thresholds, different time windows, different
resolution sources). Generating multiple forces you to explore those shapes
explicitly instead of locking onto the first one that comes to mind.

Make the candidates GENUINELY different. Different resolver, different
deadline, different threshold, different question shape. Do NOT just rephrase
the same question 3 times. If a cluster truly only supports one good market
angle, you may return just one candidate -- never return zero. If the cluster
is not bettable at all, return one candidate with bettable=false and null
question fields.

Region discipline:
- Each candidate's market question must be relevant to {country_name} or to a
  genuinely global outcome.
- If a cluster is mainly another country's domestic policy, central bank,
  local election, local sports league, local court case, or local company
  story with no clear {country_name} relevance, mark every candidate as
  digest/watch: bettable=false, suggested_question=null,
  suggested_question_zh=null.
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
      "candidates": [
        {{
          "suggested_question": "Will ... by ...? (null if not bettable)",
          "suggested_question_zh": "中文预测市场问题（不可下注则为 null）",
          "resolution_source": "specific official or authoritative source",
          "bettable": <true|false>,
          "disposition_hint": "top|candidate|watch|digest|drop",
          "R": <0|1|2>, "R_reason": "why this outcome is/isn't resolvable",
          "S": <0|1|2>, "S_reason": "what authoritative source resolves it",
          "T": <0|1|2>, "T_reason": "what is the time window / deadline",
          "U": <0|1|2>, "U_reason": "how uncertain is the outcome",
          "H": <0|1|2>, "H_reason": "how much public attention",
          "BDLT": {{
            "B": <0|1|2>, "B_reason": "bet demand reason",
            "D": <0|1|2>, "D_reason": "disagreement reason",
            "L": <0|1|2>, "L_reason": "local hook reason",
            "T": <0|1|2>, "T_reason": "timeliness reason"
          }},
          "yes_buyer": "specific motivated YES-buyer archetype, or null",
          "no_buyer": "specific motivated NO-buyer archetype, or null",
          "tradeability_reason": "why this has or lacks real two-sided demand",
          "why_users_bet": "1 short reason this might attract real-money local bettors"
        }}
      ]
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
- U=2: outcome is genuinely in doubt, implied probability 25%-75%
- U=1: one side heavily favored but not certain
- U=0: outcome is essentially decided / a sure thing
- H=2: multiple sources, social discussion, or cross-section coverage
- H=1: 2-4 evidence items, limited social discussion
- H=0: single weak source or very low interest

TRADEABILITY GATE (BDLT), optimized for local DigiPlus-like betting demand:
- First name a plausible motivated YES buyer and NO buyer. If either side is
  missing or merely "someone following the news", the candidate is not a real
  market even when R/S/T are objectively clean.
- B=2: broad or intense local betting demand from users with money, identity,
  fandom, livelihood, status, or daily-life stakes. B=1: niche but playable.
  B=0: informative, routine, narrow-audience, or unlikely to make users bet.
- D=2: both YES and NO have plausible motivated buyers with different priors
  or incentives. D=1: some two-sided demand but one side is much easier to
  imagine. D=0: no real counterparty, boring, settled, or one-sided.
- L=2: directly local and familiar to everyday users. L=1: indirect local
  effect or strong global relevance. L=0: foreign/abstract with little local
  hook.
- T=2: near-term settlement or active information flow before a known event.
  T=1: this quarter/season or a slower but trackable cadence. T=0: long,
  vague, open-ended, or no meaningful information flow before settlement.

Tradeability hard rules:
- If B=0 or D=0, set bettable=false and null question fields.
- If B+D < 3, set bettable=false and null question fields. Weak demand plus
  weak disagreement does not create a real order book.
- If B+D+L+T < 4, set bettable=false and null question fields.
- B+D+L+T = 4 is at most watch. B+D+L+T = 5 is at most candidate.
- TOP requires B=2, B+D >= 3, B+D+L+T >= 6, and no RSTUH veto.
- Do not blacklist by topic label. Judge the market mechanism: motivated
  counterparties, local stake, uncertainty, and information flow.

Important:
- A cluster can be valuable digest even when it is not bettable.
- Sports and entertainment can be bettable if the event has an official result
  and a future time window; otherwise mark digest/watch.
- Local politics, legal processes, economic policy, health outbreaks, weather,
  security, and infrastructure should get careful market-question treatment.
"""


class SeriousAngle:
    """Generate scored, bettable serious market questions."""

    name = "serious"

    def generate(
        self,
        groups: List[Dict],
        client,
        model: str,
        region_cfg: RegionConfig,
    ) -> Dict[str, int]:
        """Populate primary serious-market fields on each group in-place.

        For each group: ask Gemini for 2-3 candidate market questions with
        independent RSTUH+BDLT scores. Pick the highest-total candidate as
        primary (flat fields). Store all candidates under g.serious_candidates.

        Returns {"attached": int, "total": int, "candidate_count": int}.
        Never raises - on parse / API failure the groups are left untouched
        and stats reflect zero.
        """
        stats = {"attached": 0, "total": len(groups), "candidate_count": 0}
        if not groups:
            return stats

        today = dt.date.today().isoformat()
        prompt = SCORE_PROMPT_TEMPLATE.format(
            date=today,
            country_name=region_cfg.country_name,
            groups=_build_score_groups(groups),
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
            raw = item.get("candidates")
            # Tolerate old-format response that returns scoring fields at the
            # top level instead of under candidates[].
            if not raw and any(k in item for k in ("R", "S", "suggested_question")):
                raw = [item]
            if not isinstance(raw, list) or not raw:
                continue
            cleaned = [_normalize_candidate(c) for c in raw[:3] if isinstance(c, dict)]
            cleaned = [c for c in cleaned if c is not None]
            if not cleaned:
                continue
            best = max(cleaned, key=_candidate_total)
            # Flat fields = best candidate, for renderer + disposition logic.
            group["R"] = best["R"]
            group["R_reason"] = best["R_reason"]
            group["S"] = best["S"]
            group["S_reason"] = best["S_reason"]
            group["T"] = best["T"]
            group["T_reason"] = best["T_reason"]
            group["U"] = best["U"]
            group["U_reason"] = best["U_reason"]
            group["H"] = best["H"]
            group["H_reason"] = best["H_reason"]
            group["BDLT"] = best["BDLT"]
            group["yes_buyer"] = best["yes_buyer"]
            group["no_buyer"] = best["no_buyer"]
            group["tradeability_reason"] = best["tradeability_reason"]
            group["why_users_bet"] = best["why_users_bet"]
            group["bettable"] = best["bettable"]
            group["suggested_question"] = best["suggested_question"]
            group["suggested_question_zh"] = best["suggested_question_zh"]
            group["resolution_source"] = best["resolution_source"]
            group["disposition_hint"] = best["disposition_hint"]
            # All candidates preserved for inspection / future UI.
            group["serious_candidates"] = cleaned
            stats["attached"] += 1
            stats["candidate_count"] += len(cleaned)
        return stats


def _build_score_groups(groups: List[Dict]) -> str:
    """Serialize a per-group block for the SCORE prompt input.

    IMPORTANT: include sample_titles and the source mix. The Heat (H)
    dimension is scored on "multiple sources / social discussion / cross-
    section coverage"; without article titles and source breakdown in the
    prompt the model has no evidence for H and defaults every group to H=0,
    which vetoes every group out of the TOP tier. Reads group["clusters"]
    (attached before PHASE_1 in cluster_with_llm).
    """
    blocks = []
    for index, group in enumerate(groups):
        entry_ids = group.get("entry_ids", []) or []
        group_clusters = group.get("clusters") or []
        titles = [
            clip(c.get("cluster_title", ""), 120)
            for c in group_clusters[:8]
            if c.get("cluster_title")
        ]
        source_mix = group.get("source_mix") or {}
        sources = ", ".join(f"{name}:{count}" for name, count in source_mix.items())
        blocks.append("\n".join([
            f"[{index}] {group.get('name', '')} / {group.get('name_zh', '')}",
            f"type={group.get('topic_type', '')}",
            f"density={group.get('density', len(entry_ids))}",
            f"entry_ids={entry_ids}",
            f"sources={sources}",
            f"narrative={clip(group.get('narrative', ''), 220)}",
            f"market_hint={clip(str(group.get('market_hint') or ''), 180)}",
            "sample_titles=" + " | ".join(titles),
        ]))
    return "\n\n".join(blocks)


def _normalize_candidate(c: Dict) -> Dict | None:
    """Clean / validate one candidate dict. Returns None if too malformed."""
    bdlt = c.get("BDLT") or {}
    if not isinstance(bdlt, dict):
        bdlt = {}
    normalized = {
        "suggested_question": c.get("suggested_question"),
        "suggested_question_zh": c.get("suggested_question_zh"),
        "resolution_source": c.get("resolution_source", "") or "",
        "bettable": bool(c.get("bettable")),
        "disposition_hint": c.get("disposition_hint", "watch") or "watch",
        "R": _clip_score(c.get("R")),
        "R_reason": c.get("R_reason", "") or "",
        "S": _clip_score(c.get("S")),
        "S_reason": c.get("S_reason", "") or "",
        "T": _clip_score(c.get("T")),
        "T_reason": c.get("T_reason", "") or "",
        "U": _clip_score(c.get("U")),
        "U_reason": c.get("U_reason", "") or "",
        "H": _clip_score(c.get("H")),
        "H_reason": c.get("H_reason", "") or "",
        "BDLT": {
            "B": _clip_score(bdlt.get("B")),
            "B_reason": bdlt.get("B_reason", "") or "",
            "D": _clip_score(bdlt.get("D")),
            "D_reason": bdlt.get("D_reason", "") or "",
            "L": _clip_score(bdlt.get("L")),
            "L_reason": bdlt.get("L_reason", "") or "",
            "T": _clip_score(bdlt.get("T")),
            "T_reason": bdlt.get("T_reason", "") or "",
        },
        "yes_buyer": c.get("yes_buyer", "") or "",
        "no_buyer": c.get("no_buyer", "") or "",
        "tradeability_reason": c.get("tradeability_reason", "") or "",
        "why_users_bet": c.get("why_users_bet", "") or "",
    }
    _apply_tradeability_gate(normalized)
    return normalized


def _clip_score(v) -> int:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return 0
    return max(0, min(2, i))


def _bdlt_total(c: Dict) -> int:
    b = c["BDLT"]
    return b["B"] + b["D"] + b["L"] + b["T"]


def _tradeability_rejection_reason(c: Dict) -> str:
    b = c["BDLT"]
    if b["B"] <= 0:
        return "No plausible motivated buyer demand."
    if b["D"] <= 0:
        return "No plausible motivated YES and NO buyer."
    if b["B"] + b["D"] < 3:
        return "Buyer demand and disagreement are both too weak."
    if _bdlt_total(c) < 4:
        return "Tradeability score is below the surfacing threshold."
    return ""


def _passes_tradeability_gate(c: Dict) -> bool:
    return bool(c.get("bettable")) and not _tradeability_rejection_reason(c)


def _apply_tradeability_gate(c: Dict) -> None:
    if not c.get("bettable"):
        return
    reason = _tradeability_rejection_reason(c)
    if not reason:
        return
    c["bettable"] = False
    c["suggested_question"] = None
    c["suggested_question_zh"] = None
    c["disposition_hint"] = "digest"
    c["tradeability_reason"] = c.get("tradeability_reason") or reason
    c["why_users_bet"] = c.get("why_users_bet") or reason


def _candidate_total(c: Dict) -> tuple:
    """Sorting key: tradeability first, then market-structure quality."""
    rstuh = c["R"] + c["S"] + c["T"] + c["U"] + c["H"]
    b = c["BDLT"]
    bdlt = _bdlt_total(c)
    rstuh_has_no_veto = all(c[key] > 0 for key in ("R", "S", "T", "U", "H"))
    two_sided_strength = min(b["B"], b["D"])
    return (_passes_tradeability_gate(c), rstuh_has_no_veto, bdlt, two_sided_strength, rstuh)
