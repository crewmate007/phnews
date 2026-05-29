"""Tests for the HTML generation layer (scripts/gen_html.py)."""
import gen_html


def _base_group(**over):
    g = {
        "name": "Topic", "name_zh": "话题", "density": 2,
        "R": 2, "S": 2, "T": 2, "U": 2, "H": 2,
        "BDLT": {"B": 2, "D": 2, "L": 2, "T": 2, "total": 8},
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
    assert gen_html.classify_disposition(_base_group(H=0, U=1, R=2, S=2, T=2)) in ("candidate", "watch")


def test_classify_drop_when_not_bettable():
    assert gen_html.classify_disposition(_base_group(bettable=False)) == "drop"


def test_classify_watch_on_veto():
    # any 0 dimension is a veto -> cannot be top/candidate
    assert gen_html.classify_disposition(_base_group(S=0)) == "watch"


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
