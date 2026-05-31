"""Tests for the HTML generation layer (scripts/gen_html.py)."""
import gen_html
import add_probabilities


def _base_group(**over):
    g = {
        "name": "Topic", "name_zh": "话题", "density": 2,
        "R": 2, "S": 2, "T": 2, "U": 2, "H": 2,
        "contract_quality": {"R": 2, "S": 2, "T": 2, "U": 2, "total": 8},
        "volume_potential": {"audience_reach": 5, "stake_salience": 5,
                             "two_sided_conviction": 5, "trade_now_trigger": 4,
                             "update_cadence": 4, "comprehension_speed": 5,
                             "narrative_heat": 5, "local_relevance": 5,
                             "personas": ["sports/fandom"]},
        "volume_score": 90,
        "BDLT": {"B": 2, "D": 2, "L": 2, "T": 2, "total": 8},
        "yes_buyer": "local fans backing the favorite",
        "no_buyer": "local fans backing the underdog",
        "bettable": True, "suggested_question": "Will X by Y?",
        "suggested_question_zh": "X会在Y前发生吗？", "resolution_source": "BSP",
        "narrative": "n", "narrative_zh": "叙事", "source_mix": {"google_news": 2},
        "source_examples": [],
    }
    g.update(over)
    return g


def test_classify_top():
    assert gen_html.classify_disposition(_base_group()) == "top"


def test_classify_candidate():
    assert gen_html.classify_disposition(_base_group(volume_score=65)) == "candidate"


def test_classify_drop_when_not_bettable():
    assert gen_html.classify_disposition(_base_group(bettable=False)) == "drop"


def test_classify_drop_when_tradeability_gate_fails():
    assert gen_html.classify_disposition(_base_group(
        volume_potential={"audience_reach": 5, "stake_salience": 5,
                          "two_sided_conviction": 0, "trade_now_trigger": 5,
                          "update_cadence": 5, "comprehension_speed": 5,
                          "narrative_heat": 5, "local_relevance": 5},
        volume_score=80,
    )) == "drop"
    assert gen_html.classify_disposition(_base_group(
        volume_potential={"audience_reach": 1, "stake_salience": 1,
                          "two_sided_conviction": 4, "trade_now_trigger": 1,
                          "update_cadence": 1, "comprehension_speed": 4,
                          "narrative_heat": 1, "local_relevance": 2},
        volume_score=30,
    )) == "drop"


def test_classify_low_tradeability_cannot_be_top():
    assert gen_html.classify_disposition(_base_group(
        volume_potential={"audience_reach": 3, "stake_salience": 3,
                          "two_sided_conviction": 2, "trade_now_trigger": 2,
                          "update_cadence": 2, "comprehension_speed": 4,
                          "narrative_heat": 3, "local_relevance": 3},
        volume_score=52,
    )) == "watch"
    assert gen_html.classify_disposition(_base_group(
        volume_potential={"audience_reach": 5, "stake_salience": 5,
                          "two_sided_conviction": 2, "trade_now_trigger": 5,
                          "update_cadence": 5, "comprehension_speed": 5,
                          "narrative_heat": 5, "local_relevance": 5},
        volume_score=86,
    )) != "top"


def test_classify_watch_on_veto():
    # any 0 contract dimension is a hard veto
    assert gen_html.classify_disposition(_base_group(S=0, contract_quality={"R": 2, "S": 0, "T": 2, "U": 2})) == "drop"


def test_product_sku_listing_drops_despite_clean_contract():
    g = _base_group(
        name="Haier Mini-LED TV website listing",
        R=2, S=2, T=2, U=1, H=1,
        volume_potential={"audience_reach": 1, "stake_salience": 1,
                          "two_sided_conviction": 1, "trade_now_trigger": 1,
                          "update_cadence": 1, "comprehension_speed": 4,
                          "narrative_heat": 1, "local_relevance": 2},
        volume_score=26,
        yes_buyer="Haier product launch watchers",
        no_buyer="retail skeptics",
    )
    assert gen_html.classify_disposition(g) == "drop"


def test_hot_one_sided_market_cannot_be_top():
    g = _base_group(
        volume_potential={"audience_reach": 5, "stake_salience": 5,
                          "two_sided_conviction": 2, "trade_now_trigger": 5,
                          "update_cadence": 5, "comprehension_speed": 5,
                          "narrative_heat": 5, "local_relevance": 5},
        volume_score=86,
    )
    assert gen_html.classify_disposition(g) != "top"


def test_probability_selection_uses_volume_gate():
    top = _base_group(name="High volume")
    low = _base_group(
        name="Low volume",
        volume_potential={"audience_reach": 1, "stake_salience": 1,
                          "two_sided_conviction": 1, "trade_now_trigger": 1,
                          "update_cadence": 1, "comprehension_speed": 4,
                          "narrative_heat": 1, "local_relevance": 1},
        volume_score=25,
    )
    selected = add_probabilities.select_probability_groups({"groups": [top, low]})
    assert selected == [top]


def test_build_group_passes_reddit_angles():
    g = _base_group(reddit_angles=[
        {"subtopic": "a", "question_en": "q?", "question_zh": "问？",
         "source": "BSP", "url": "https://www.bsp.gov.ph/x"}])
    out = gen_html.build_group(g)
    assert len(out["reddit_angles"]) == 1
    assert out["reddit_angles"][0]["subtopic"] == "a"


def test_build_group_passes_tiktok_angles():
    g = _base_group(tiktok_angles=[
        {"subtopic": None, "question_en": "🔥 q?", "question_zh": "🔥 问？",
         "source": "PAGASA", "url": "https://www.pagasa.dost.gov.ph/x"}])
    out = gen_html.build_group(g)
    assert len(out["tiktok_angles"]) == 1


def test_build_group_legacy_reddit_flat_fields():
    """Old JSON only had flat reddit_question* fields -> must wrap into array."""
    g = _base_group(reddit_question="legacy", reddit_question_zh="旧",
                    reddit_resolution_source="BSP",
                    reddit_resolution_url="https://www.bsp.gov.ph/x")
    out = gen_html.build_group(g)
    assert len(out["reddit_angles"]) == 1
    assert out["reddit_angles"][0]["question_en"] == "legacy"


def test_translate_title_fallback_not_capped_at_28():
    """Regression: titles were clipped to 28 chars ('Event spotlights smarter
    ene'). Must return the full title now."""
    long_title = "Event spotlights smarter energy options to beat the heat - ABS-CBN"
    out = gen_html.translate_title_fallback(long_title)
    assert len(out) > 28
    assert "smarter energy options" in out


def test_normalize_angle_list_drops_empty():
    lst = gen_html._normalize_angle_list([
        {"question_en": "q?", "question_zh": "问？", "source": "BSP", "url": None},
        {"question_en": None, "question_zh": None},  # dropped: no question
        "not a dict",  # dropped
    ])
    assert len(lst) == 1


def test_format_manila_time():
    # UTC 23:43 -> Manila 07:43 next day
    out = gen_html._format_manila_time("2026-05-26T23:43:50+00:00")
    assert "2026-05-27 07:43" == out
