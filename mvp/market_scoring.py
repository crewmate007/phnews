"""Shared contract and volume scoring for prediction-market candidates.

The pipeline used to mix market validity and demand in BDLT.  This module
keeps contract quality as a gate, then ranks surfaced markets by expected
local retail trading demand.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping


SCORING_VERSION = "volume_v1"

CONTRACT_DIMENSIONS = ("R", "S", "T", "U")
VOLUME_DIMENSIONS = (
    "audience_reach",
    "stake_salience",
    "two_sided_conviction",
    "trade_now_trigger",
    "update_cadence",
    "comprehension_speed",
    "narrative_heat",
    "local_relevance",
)

VOLUME_WEIGHTS = {
    "audience_reach": 1.2,
    "stake_salience": 1.2,
    "two_sided_conviction": 1.3,
    "trade_now_trigger": 1.2,
    "update_cadence": 1.0,
    "comprehension_speed": 0.9,
    "narrative_heat": 1.0,
    "local_relevance": 1.2,
}

MIN_VOLUME_SCORE = 45
CANDIDATE_VOLUME_SCORE = 60
TOP_VOLUME_SCORE = 75
TOP_TWO_SIDED_MIN = 4
TOP_TRADE_NOW_MIN = 3
TOP_UPDATE_CADENCE_MIN = 3

DISPOSITION_RANK = {"drop": 0, "watch": 1, "candidate": 2, "top": 3}


def clip_score(value: Any, high: int) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(high, score))


def normalize_contract_quality(g: Mapping[str, Any]) -> Dict[str, Any]:
    raw = g.get("contract_quality") if isinstance(g.get("contract_quality"), dict) else {}
    quality: Dict[str, Any] = {}
    for key in CONTRACT_DIMENSIONS:
        quality[key] = clip_score(raw.get(key, g.get(key)), 2)
        quality[f"{key}_reason"] = raw.get(f"{key}_reason") or g.get(f"{key}_reason", "") or ""
    quality["total"] = sum(quality[key] for key in CONTRACT_DIMENSIONS)
    reason = _contract_rejection_reason_from_quality(g, quality)
    quality["passes_gate"] = not reason
    quality["reason"] = raw.get("reason") or reason
    return quality


def normalize_volume_potential(g: Mapping[str, Any]) -> Dict[str, Any]:
    raw = g.get("volume_potential") if isinstance(g.get("volume_potential"), dict) else {}
    fallback = _volume_from_legacy_bdlt(g)
    volume: Dict[str, Any] = {}
    for key in VOLUME_DIMENSIONS:
        volume[key] = clip_score(raw.get(key, fallback.get(key)), 5)
        volume[f"{key}_reason"] = (
            raw.get(f"{key}_reason")
            or fallback.get(f"{key}_reason")
            or ""
        )
    personas = raw.get("personas")
    volume["personas"] = personas[:6] if isinstance(personas, list) else []
    raw_score = g.get("volume_score")
    if raw_score is None:
        raw_score = raw.get("score")
    volume["score"] = clip_score(raw_score, 100) if raw_score is not None else _weighted_volume_score(volume)
    volume["total"] = sum(volume[key] for key in VOLUME_DIMENSIONS)
    return volume


def ensure_scoring_fields(g: Dict[str, Any]) -> Dict[str, Any]:
    """Populate normalized scoring fields and legacy BDLT compatibility."""
    g["scoring_version"] = SCORING_VERSION
    g["contract_quality"] = normalize_contract_quality(g)
    g["volume_potential"] = normalize_volume_potential(g)
    g["volume_score"] = g["volume_potential"]["score"]
    g["BDLT"] = bdlt_from_volume_potential(g["volume_potential"])
    return g


def apply_market_gates(g: Dict[str, Any]) -> None:
    """Normalize fields, then mark candidates that cannot surface as drops."""
    ensure_scoring_fields(g)
    reason = contract_rejection_reason(g) or volume_rejection_reason(g)
    if reason:
        g["bettable"] = False
        g["suggested_question"] = None
        g["suggested_question_zh"] = None
        g["resolution_source"] = ""
        g["disposition_hint"] = "digest"
        g["tradeability_filtered"] = True
        g["tradeability_reason"] = g.get("tradeability_reason") or reason
        g["why_users_bet"] = g.get("why_users_bet") or reason
        return
    g["disposition_hint"] = classify_disposition(g)


def contract_rejection_reason(g: Mapping[str, Any]) -> str:
    quality = normalize_contract_quality(g)
    return _contract_rejection_reason_from_quality(g, quality)


def passes_contract_gate(g: Mapping[str, Any]) -> bool:
    return not contract_rejection_reason(g)


def has_strong_contract(g: Mapping[str, Any]) -> bool:
    quality = normalize_contract_quality(g)
    return (
        not _contract_rejection_reason_from_quality(g, quality)
        and quality["total"] >= 7
        and quality["R"] >= 2
        and quality["S"] >= 2
        and quality["T"] >= 1
        and quality["U"] >= 1
    )


def volume_rejection_reason(g: Mapping[str, Any]) -> str:
    if not passes_contract_gate(g):
        return contract_rejection_reason(g)
    volume = normalize_volume_potential(g)
    if not (_has_concrete_buyer(g.get("yes_buyer")) and _has_concrete_buyer(g.get("no_buyer"))):
        return "Missing concrete motivated YES and NO buyers."
    if volume["two_sided_conviction"] < 2:
        return "Two-sided conviction is too weak for an order book."
    if volume["score"] < MIN_VOLUME_SCORE:
        return "Volume potential is below the surfacing threshold."
    return ""


def passes_volume_gate(g: Mapping[str, Any]) -> bool:
    return not volume_rejection_reason(g)


def passes_tradeability_gate(g: Mapping[str, Any]) -> bool:
    """Compatibility alias for older call sites."""
    return passes_volume_gate(g)


def classify_disposition(g: Mapping[str, Any]) -> str:
    if not passes_volume_gate(g):
        return "drop"
    volume = normalize_volume_potential(g)
    if (
        has_strong_contract(g)
        and volume["score"] >= TOP_VOLUME_SCORE
        and volume["two_sided_conviction"] >= TOP_TWO_SIDED_MIN
        and volume["trade_now_trigger"] >= TOP_TRADE_NOW_MIN
        and volume["update_cadence"] >= TOP_UPDATE_CADENCE_MIN
    ):
        return "top"
    if volume["score"] >= CANDIDATE_VOLUME_SCORE:
        return "candidate"
    return "watch"


def candidate_sort_key(g: Mapping[str, Any]) -> tuple:
    volume = normalize_volume_potential(g)
    contract = normalize_contract_quality(g)
    disposition = classify_disposition(g)
    return (
        DISPOSITION_RANK.get(disposition, 0),
        volume["score"],
        volume["two_sided_conviction"],
        volume["trade_now_trigger"],
        volume["update_cadence"],
        contract["total"],
        clip_score(g.get("H"), 2),
    )


def bdlt_from_volume_potential(volume: Mapping[str, Any]) -> Dict[str, Any]:
    b = _score2_from_score5(max(
        volume.get("audience_reach", 0),
        volume.get("stake_salience", 0),
        volume.get("narrative_heat", 0),
    ))
    d = _score2_from_score5(volume.get("two_sided_conviction", 0))
    l = _score2_from_score5(volume.get("local_relevance", 0))
    t = _score2_from_score5(max(
        volume.get("trade_now_trigger", 0),
        volume.get("update_cadence", 0),
    ))
    out = {
        "B": b,
        "B_reason": "Mapped from audience, stake, and narrative heat.",
        "D": d,
        "D_reason": "Mapped from two-sided conviction.",
        "L": l,
        "L_reason": "Mapped from local relevance.",
        "T": t,
        "T_reason": "Mapped from trade-now trigger and update cadence.",
    }
    out["total"] = b + d + l + t
    return out


def _contract_rejection_reason_from_quality(
    g: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> str:
    if not bool(g.get("bettable")):
        return "Market candidate is marked not bettable."
    if not _question_text(g):
        return "No suggested market question."
    if quality["R"] <= 0:
        return "Outcome is not objectively resolvable."
    if quality["S"] <= 0:
        return "No authoritative resolution source."
    if quality["T"] <= 0:
        return "No clear time window or deadline."
    if quality["U"] <= 0:
        return "Outcome is essentially decided."
    if not _resolution_source(g):
        return "No authoritative resolution source."
    return ""


def _weighted_volume_score(volume: Mapping[str, Any]) -> int:
    total_weight = sum(VOLUME_WEIGHTS.values())
    weighted = sum(
        clip_score(volume.get(key), 5) / 5 * weight
        for key, weight in VOLUME_WEIGHTS.items()
    )
    return round(weighted / total_weight * 100)


def _volume_from_legacy_bdlt(g: Mapping[str, Any]) -> Dict[str, Any]:
    bdlt = g.get("BDLT") if isinstance(g.get("BDLT"), dict) else {}
    b = _score5_from_score2(bdlt.get("B"))
    d = _score5_from_score2(bdlt.get("D"))
    l = _score5_from_score2(bdlt.get("L"))
    t = _score5_from_score2(bdlt.get("T"))
    return {
        "audience_reach": b,
        "audience_reach_reason": bdlt.get("B_reason", ""),
        "stake_salience": b,
        "stake_salience_reason": bdlt.get("B_reason", ""),
        "two_sided_conviction": d,
        "two_sided_conviction_reason": bdlt.get("D_reason", ""),
        "trade_now_trigger": t,
        "trade_now_trigger_reason": bdlt.get("T_reason", ""),
        "update_cadence": t,
        "update_cadence_reason": bdlt.get("T_reason", ""),
        "comprehension_speed": 4 if g.get("suggested_question") else 1,
        "comprehension_speed_reason": "Legacy fallback from suggested question clarity.",
        "narrative_heat": max(b, l),
        "narrative_heat_reason": bdlt.get("B_reason", ""),
        "local_relevance": l,
        "local_relevance_reason": bdlt.get("L_reason", ""),
    }


def _score5_from_score2(value: Any) -> int:
    return {0: 0, 1: 3, 2: 5}.get(clip_score(value, 2), 0)


def _score2_from_score5(value: Any) -> int:
    score = clip_score(value, 5)
    if score >= 4:
        return 2
    if score >= 2:
        return 1
    return 0


def _has_concrete_buyer(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if len(text) < 4:
        return False
    weak = {
        "someone",
        "people",
        "users",
        "bettors",
        "traders",
        "news followers",
        "general public",
        "someone following the news",
    }
    return text not in weak


def _question_text(g: Mapping[str, Any]) -> Any:
    return g.get("suggested_question") or g.get("question") or g.get("question_en")


def _resolution_source(g: Mapping[str, Any]) -> Any:
    return g.get("resolution_source") or g.get("source")
