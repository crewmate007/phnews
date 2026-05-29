"""End-to-end test of cluster_with_llm() with a fake Gemini client.

This is the test that would have caught the _build_score_groups() arity
crash and the H=0 / TOP=0 regression that shipped silently because angle
failures are swallowed by the orchestrator's try/except.
"""
import cluster
import gen_html
from conftest import make_clusters


def _run(fake_gemini, n=6):
    fake_gemini["n"] = n
    clusters = make_clusters(n)
    return cluster.cluster_with_llm(clusters, api_key="fake", region="ph", model="fake")


def test_pipeline_produces_groups(fake_gemini):
    result = _run(fake_gemini)
    assert len(result["groups"]) == 6


def test_serious_scoring_runs(fake_gemini):
    """Regression: serious angle must actually populate scores (the arity
    crash left every group at R=S=T=U=H=0, bettable=False)."""
    result = _run(fake_gemini)
    groups = result["groups"]
    assert all(g.get("bettable") for g in groups), "serious angle did not run"
    assert all(any(g.get(k) for k in ("R", "S", "T", "U", "H")) for g in groups)
    assert all(g.get("serious_candidates") for g in groups)


def test_top_tier_appears(fake_gemini):
    """Regression: TOP tier was 0 for all groups. With max-score candidates
    the disposition must yield TOP."""
    result = _run(fake_gemini)
    built = [gen_html.build_group(g) for g in result["groups"]]
    disps = [gen_html.classify_disposition(b) for b in built]
    assert disps.count("top") > 0, f"no TOP tier: {disps}"


def test_clusters_attached_before_serious(fake_gemini):
    """Serious scoring needs group['clusters'] for sample_titles; if missing,
    H defaults to 0 and TOP never appears. Verify clusters are present."""
    result = _run(fake_gemini)
    assert all(g.get("clusters") for g in result["groups"])


def test_all_three_angles_present(fake_gemini):
    result = _run(fake_gemini)
    groups = result["groups"]
    assert any(g.get("serious_candidates") for g in groups)
    assert any(g.get("reddit_angles") for g in groups)
    assert any(g.get("tiktok_angles") for g in groups)


def test_reddit_and_tiktok_are_separate(fake_gemini):
    result = _run(fake_gemini)
    # A group that got both should keep them in distinct fields.
    for g in result["groups"]:
        if g.get("reddit_angles") and g.get("tiktok_angles"):
            assert g["reddit_angles"] is not g["tiktok_angles"]


def test_disallowed_url_filtered_end_to_end(fake_gemini):
    result = _run(fake_gemini)
    for g in result["groups"]:
        for a in (g.get("reddit_angles") or []) + (g.get("tiktok_angles") or []):
            if a.get("source") == "Disallowed Source":
                assert a.get("url") is None


def test_clustered_at_timestamp(fake_gemini):
    result = _run(fake_gemini)
    assert result.get("clustered_at")


def test_serious_failure_does_not_kill_pipeline(fake_gemini):
    """If serious returns malformed JSON, the orchestrator swallows it and
    the pipeline still returns groups (degraded, not crashed)."""
    fake_gemini["overrides"]["serious"] = "totally not json"
    result = _run(fake_gemini)
    assert len(result["groups"]) == 6  # pipeline survived
    # serious produced nothing, so groups are not bettable
    assert not any(g.get("serious_candidates") for g in result["groups"])
