"""Shared fixtures for the PHNews test suite.

The pipeline's only external dependency is the Gemini API (google-genai).
cluster_with_llm() does `from google import genai; genai.Client(...)`. We
replace that with a fake module so the whole pipeline can run offline and
deterministically. Tests can override the canned response per prompt-kind
(broad / serious / reddit / tiktok) to exercise edge cases.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# mvp/ and scripts/ are imported as top-level modules by the app itself.
for sub in ("mvp", "scripts"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------------
# Fake SourceIntel clusters (the input to cluster_with_llm)
# --------------------------------------------------------------------------
def make_clusters(n: int = 6) -> list[dict]:
    out = []
    for i in range(n):
        out.append({
            # intentionally long title so truncation regressions are caught
            "cluster_title": f"Senator faces plunder probe as Senate debates charter "
                             f"change reforms in extended session number {i} - Inquirer.net",
            "title_zh": f"参议员掠夺案与宪法改革辩论 第{i}场",
            "summary": f"Detailed summary {i} of an unfolding Philippine political story.",
            "summary_zh": f"中文摘要 {i}",
            "section": "google_news" if i % 2 == 0 else "x_grok",
            "source_name": "google_news" if i % 2 == 0 else "x_grok",
            "source_count": 3,
            "rank_score": 90 - i,
            "keywords": ["senate", "plunder", "charter"],
            "link": f"https://example.com/{i}",
        })
    return out


# --------------------------------------------------------------------------
# Canned LLM responses keyed by prompt-kind
# --------------------------------------------------------------------------
def _classify_prompt(p: str) -> str:
    if "broad coverage clusters" in p:
        return "broad"
    if "PROPOSE 2-3 CANDIDATE" in p or "SCORING GUIDE" in p:
        return "serious"
    if "lurked Reddit" in p:
        return "reddit"
    if "TikTok creator" in p:
        return "tiktok"
    return "unknown"


def default_broad(n: int) -> str:
    groups = [{
        "name": f"Topic {i}", "name_zh": f"话题{i}", "entry_ids": [i],
        "density": 1, "narrative": f"Narrative {i}", "narrative_zh": f"叙事{i}",
        "topic_type": "politics", "source_mix": {"google_news": 1},
        "market_hint": "Will X happen by date Y?",
    } for i in range(n)]
    return json.dumps({"groups": groups, "noise": []})


def default_serious(n: int) -> str:
    """Two candidates per group; first is max-score so best-of-N -> TOP."""
    groups = []
    for i in range(n):
        groups.append({"broad_index": i, "candidates": [
            {"suggested_question": f"Will event {i} resolve by Dec 31?",
             "suggested_question_zh": f"事件{i}会在12月31日前解决吗？",
             "resolution_source": "Senate of the Philippines", "bettable": True,
             "disposition_hint": "top",
             "R": 2, "R_reason": "x", "S": 2, "S_reason": "x", "T": 2, "T_reason": "x",
             "U": 2, "U_reason": "x", "H": 2, "H_reason": "x",
             "volume_potential": {"audience_reach": 5, "stake_salience": 5,
                                  "two_sided_conviction": 5, "trade_now_trigger": 4,
                                  "update_cadence": 4, "comprehension_speed": 5,
                                  "narrative_heat": 5, "local_relevance": 5,
                                  "personas": ["politics/public events"]},
             "volume_score": 92,
             "BDLT": {"B": 2, "B_reason": "x", "D": 2, "D_reason": "x",
                      "L": 2, "L_reason": "x", "T": 2, "T_reason": "x"},
             "yes_buyer": "opposition supporters",
             "no_buyer": "administration supporters",
             "why_users_bet": "drama"},
            {"suggested_question": f"Alt question {i}?",
             "suggested_question_zh": f"备选问题{i}？",
             "resolution_source": "DOF", "bettable": True, "disposition_hint": "candidate",
             "R": 2, "R_reason": "", "S": 1, "S_reason": "", "T": 2, "T_reason": "",
             "U": 1, "U_reason": "", "H": 1, "H_reason": "",
             "volume_potential": {"audience_reach": 3, "stake_salience": 3,
                                  "two_sided_conviction": 3, "trade_now_trigger": 3,
                                  "update_cadence": 2, "comprehension_speed": 4,
                                  "narrative_heat": 3, "local_relevance": 3,
                                  "personas": ["local retail"]},
             "volume_score": 58,
             "BDLT": {"B": 1, "B_reason": "", "D": 1, "D_reason": "",
                      "L": 1, "L_reason": "", "T": 1, "T_reason": ""},
             "yes_buyer": "policy optimists",
             "no_buyer": "policy skeptics",
             "why_users_bet": ""},
        ]})
    return json.dumps({"groups": groups})


def default_angles(n: int, viral: bool = False) -> str:
    """Mix: some groups 2 angles (one with a disallowed URL), some 1, some 0."""
    hook = "🔥 " if viral else ""
    groups = []
    for i in range(n):
        if i % 3 == 0:
            angles = [
                {"subtopic": f"子话题A{i}", "question_en": f"{hook}Angle one {i}?",
                 "question_zh": f"{hook}角度一 {i}？", "source": "PAGASA",
                 "url": "https://www.pagasa.dost.gov.ph/x"},
                {"subtopic": f"子话题B{i}", "question_en": f"Angle two {i}?",
                 "question_zh": f"角度二 {i}？", "source": "Disallowed Source",
                 "url": "https://evil-not-allowlisted.example/x"},
            ]
        elif i % 3 == 1:
            angles = [{"subtopic": None, "question_en": f"Single {i}?",
                       "question_zh": f"单角度 {i}？", "source": "BSP",
                       "url": "https://www.bsp.gov.ph/y"}]
        else:
            angles = []
        groups.append({"broad_index": i, "angles": angles,
                       "drop_reason": None if angles else "no hook"})
    return json.dumps({"groups": groups})


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, state):
        self.state = state

    def generate_content(self, model=None, contents=None):
        kind = _classify_prompt(contents or "")
        self.state.setdefault("calls", []).append(kind)
        overrides = self.state.get("overrides", {})
        if kind in overrides:
            return _FakeResp(overrides[kind])
        n = self.state["n"]
        if kind == "broad":
            return _FakeResp(default_broad(n))
        if kind == "serious":
            return _FakeResp(default_serious(n))
        if kind == "reddit":
            return _FakeResp(default_angles(n, viral=False))
        if kind == "tiktok":
            return _FakeResp(default_angles(n, viral=True))
        return _FakeResp(json.dumps({"groups": []}))


@pytest.fixture
def fake_gemini(monkeypatch):
    """Install a fake `google.genai`. Returns a mutable state dict so tests
    can set state['overrides'][kind] = raw_json and state['n']."""
    state = {"n": 6, "overrides": {}, "calls": []}

    def Client(api_key=None):
        return types.SimpleNamespace(models=_FakeModels(state))

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=Client)
    monkeypatch.setitem(sys.modules, "google", fake_google)
    return state


@pytest.fixture
def clusters6():
    return make_clusters(6)
