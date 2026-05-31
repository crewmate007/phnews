"""Unit tests for the three angle plugins."""
import json

from regions import get_region
from angles import SeriousAngle, RedditAngle, TikTokAngle
from conftest import make_clusters, default_serious, default_angles


class _Resp:
    def __init__(self, text): self.text = text


class _Client:
    """Minimal client returning a fixed response regardless of prompt."""
    def __init__(self, text):
        self._text = text
        self.last_contents = None
        self.models = self
    def generate_content(self, model=None, contents=None):
        self.last_contents = contents
        return _Resp(self._text)


def _attach_clusters(groups, clusters):
    for g in groups:
        g["clusters"] = [clusters[i] for i in g.get("entry_ids", []) if i < len(clusters)]


def _broad_groups(n):
    return [{"name": f"T{i}", "name_zh": f"话题{i}", "entry_ids": [i], "density": 1,
             "narrative": f"N{i}", "market_hint": "Will X?"} for i in range(n)]


def test_serious_multi_candidate_picks_best():
    region = get_region("ph")
    clusters = make_clusters(3)
    groups = _broad_groups(3)
    _attach_clusters(groups, clusters)
    client = _Client(default_serious(3))
    stats = SeriousAngle().generate(groups, client, "fake", region)
    assert stats["attached"] == 3
    # candidate_count counts all candidates (2 per group)
    assert stats["candidate_count"] == 6
    for g in groups:
        # best-of-N: the max-score candidate (all 2s) should win -> H == 2
        assert g["H"] == 2
        assert g["bettable"] is True
        assert g["suggested_question"]
        assert len(g["serious_candidates"]) == 2


def test_serious_prompt_reordered_ab_switch(monkeypatch):
    region = get_region("ph")
    clusters = make_clusters(1)
    groups = _broad_groups(1)
    _attach_clusters(groups, clusters)

    legacy_client = _Client(default_serious(1))
    SeriousAngle().generate(groups, legacy_client, "fake", region)
    assert legacy_client.last_contents.index("CLUSTERS:") < legacy_client.last_contents.index("OUTPUT:")

    monkeypatch.setenv("PHNEWS_SERIOUS_PROMPT_ORDER", "reordered")
    reordered_groups = _broad_groups(1)
    _attach_clusters(reordered_groups, clusters)
    reordered_client = _Client(default_serious(1))
    SeriousAngle().generate(reordered_groups, reordered_client, "fake", region)
    assert reordered_client.last_contents.index("OUTPUT:") < reordered_client.last_contents.index("CLUSTERS:")


def test_serious_handles_not_bettable():
    region = get_region("ph")
    clusters = make_clusters(1)
    groups = _broad_groups(1)
    _attach_clusters(groups, clusters)
    payload = json.dumps({"groups": [{"broad_index": 0, "candidates": [
        {"suggested_question": None, "suggested_question_zh": None,
         "resolution_source": "", "bettable": False, "disposition_hint": "digest",
         "R": 0, "S": 0, "T": 0, "U": 0, "H": 0,
         "BDLT": {"B": 0, "D": 0, "L": 0, "T": 0}, "why_users_bet": ""}]}]})
    SeriousAngle().generate(groups, _Client(payload), "fake", region)
    assert groups[0]["bettable"] is False


def test_serious_tradeability_gate_beats_clean_but_one_sided_market():
    region = get_region("ph")
    clusters = make_clusters(1)
    groups = _broad_groups(1)
    _attach_clusters(groups, clusters)
    payload = json.dumps({"groups": [{"broad_index": 0, "candidates": [
        {"suggested_question": "Will a company list a niche item by Dec 31?",
         "suggested_question_zh": "某公司会在12月31日前上架小众商品吗？",
         "resolution_source": "Company website", "bettable": True,
         "disposition_hint": "top",
         "R": 2, "R_reason": "x", "S": 2, "S_reason": "x",
         "T": 2, "T_reason": "x", "U": 2, "U_reason": "x",
         "H": 2, "H_reason": "x",
         "BDLT": {"B": 2, "D": 0, "L": 2, "T": 2},
         "why_users_bet": "resolvable but one-sided"},
        {"suggested_question": "Will a cabinet vote fail by Dec 31?",
         "suggested_question_zh": "内阁投票会在12月31日前失败吗？",
         "resolution_source": "Official records", "bettable": True,
         "disposition_hint": "candidate",
         "R": 2, "R_reason": "x", "S": 2, "S_reason": "x",
         "T": 2, "T_reason": "x", "U": 1, "U_reason": "x",
         "H": 1, "H_reason": "x",
         "BDLT": {"B": 2, "D": 2, "L": 1, "T": 1},
         "yes_buyer": "government critics",
         "no_buyer": "administration supporters",
         "why_users_bet": "both sides care"},
    ]}]})
    SeriousAngle().generate(groups, _Client(payload), "fake", region)
    assert groups[0]["suggested_question"] == "Will a cabinet vote fail by Dec 31?"
    assert groups[0]["serious_candidates"][0]["bettable"] is False


def test_reddit_angles_array_and_url_filter():
    region = get_region("ph")
    clusters = make_clusters(3)
    groups = _broad_groups(3)
    _attach_clusters(groups, clusters)
    stats = RedditAngle().generate(groups, _Client(default_angles(3)), "fake", region)
    assert stats["attached"] >= 1
    # group 0 has 2 angles; the disallowed URL must be dropped to None
    g0 = groups[0]
    assert len(g0["reddit_angles"]) == 2
    bad = [a for a in g0["reddit_angles"] if a["source"] == "Disallowed Source"][0]
    assert bad["url"] is None
    good = [a for a in g0["reddit_angles"] if a["source"] == "PAGASA"][0]
    assert good["url"] == "https://www.pagasa.dost.gov.ph/x"


def test_tiktok_angles_populate_separate_field():
    region = get_region("ph")
    clusters = make_clusters(3)
    groups = _broad_groups(3)
    _attach_clusters(groups, clusters)
    TikTokAngle().generate(groups, _Client(default_angles(3, viral=True)), "fake", region)
    assert any(g.get("tiktok_angles") for g in groups)
    # tiktok writes its own field, not reddit's
    assert not any(g.get("reddit_angles") for g in groups)


def test_angle_cap_at_3():
    region = get_region("ph")
    clusters = make_clusters(1)
    groups = _broad_groups(1)
    _attach_clusters(groups, clusters)
    five = json.dumps({"groups": [{"broad_index": 0, "angles": [
        {"subtopic": f"s{i}", "question_en": f"q{i}?", "question_zh": f"问{i}？",
         "source": "BSP", "url": "https://www.bsp.gov.ph/x"} for i in range(5)]}]})
    RedditAngle().generate(groups, _Client(five), "fake", region)
    assert len(groups[0]["reddit_angles"]) == 3  # capped


def test_angle_generate_never_raises_on_bad_json():
    region = get_region("ph")
    clusters = make_clusters(2)
    groups = _broad_groups(2)
    _attach_clusters(groups, clusters)
    # Totally malformed -> generate should swallow? No: base.parse raises,
    # but the orchestrator (_run_angles) is what swallows. Direct call may
    # raise, so assert it raises a JSON error rather than silently corrupting.
    import json as _json
    raised = False
    try:
        RedditAngle().generate(groups, _Client("not json at all"), "fake", region)
    except _json.JSONDecodeError:
        raised = True
    assert raised
    # groups untouched
    assert not any(g.get("reddit_angles") for g in groups)
