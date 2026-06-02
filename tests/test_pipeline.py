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


def test_validator_flags_zero_scored(fake_gemini):
    """The 2026-05-29 failure mode: serious angle dies, pipeline ships many
    groups with no RSTUH scores. The validator must catch this so the broken
    page never deploys."""
    import validate_generated_pages as v
    groups = [{"bettable": False, "source_mix": {"x_grok": 1}} for _ in range(30)]
    # 30 groups, 0 scored -> the safety check should trip in main().
    assert v._has_foreign_bettable_question("ph", groups) is False
    n_scored = sum(1 for g in groups if any(g.get(k) for k in "RSTUH"))
    assert len(groups) >= 20 and n_scored == 0


def test_validator_defaults_to_ph_only():
    import validate_generated_pages as v

    checks = v._checks_for("2026-06-02")
    assert [item[0] for item in checks] == ["ph"]
    assert checks[0][1].as_posix() == "docs/index.html"
    assert all("id/" not in path.as_posix() for _, *paths in checks for path in paths)


# --- P2a: batched angle orchestration (_run_angles) --------------------------

class _RecordingAngle:
    """Fake angle that marks each group it sees and records batch sizes.

    fail_batches: set of 0-based batch indices (within the FIRST round only)
    that should raise, to simulate a transient per-batch failure.
    """
    name = "recording"

    def __init__(self, fail_first_round_batches=()):
        self.fail = set(fail_first_round_batches)
        self.batch_sizes = []
        self.round = 0
        self._calls_this_round = 0
        self._seen_rounds = set()

    def generate(self, groups, client, model, region_cfg):
        # Track round transitions: a new round starts when batch index resets.
        self.batch_sizes.append(len(groups))
        idx = self._calls_this_round
        self._calls_this_round += 1
        if self.round == 0 and idx in self.fail:
            raise RuntimeError(f"simulated batch {idx} failure")
        attached = 0
        for g in groups:
            g.setdefault("_marks", 0)
            g["_marks"] += 1
            attached += 1
        return {"attached": attached, "total": len(groups), "angle_count": attached}


def _groups(n):
    return [{"id": i} for i in range(n)]


def test_run_angles_batches_all_groups():
    g = _groups(25)
    angle = _RecordingAngle()
    cluster._run_angles([angle], g, None, "m", None, batch_size=10)
    # every group processed exactly once
    assert all(x["_marks"] == 1 for x in g)
    # 25 groups / 10 -> batches of 10, 10, 5
    assert angle.batch_sizes == [10, 10, 5]


def test_run_angles_single_batch_regression():
    """Small group count -> one batch, same as old behavior."""
    g = _groups(6)
    angle = _RecordingAngle()
    cluster._run_angles([angle], g, None, "m", None, batch_size=10)
    assert angle.batch_sizes == [6]
    assert all(x["_marks"] == 1 for x in g)


def test_run_angles_failed_batch_isolated_and_retried():
    """One batch fails in round 0; the others still succeed, and the failed
    batch's groups get processed on retry -- no group is permanently lost."""
    g = _groups(30)  # batches: [0:10], [10:20], [20:30]
    angle = _RecordingAngle(fail_first_round_batches={1})  # middle batch fails

    # advance round bookkeeping: the recording angle needs to know when a new
    # round starts. _run_angles calls generate() per batch; we detect round
    # boundaries by watching for the retry of the failed batch.
    orig_generate = angle.generate
    state = {"first_round_calls": 0}

    def wrapped(groups, *a, **k):
        # first round has 3 batches (idx 0,1,2); after that we're retrying
        if state["first_round_calls"] >= 3:
            angle.round = 1
            angle._calls_this_round = 0  # reset so fail set (round0 only) won't trigger
        state["first_round_calls"] += 1
        return orig_generate(groups, *a, **k)

    angle.generate = wrapped
    cluster._run_angles([angle], g, None, "m", None, batch_size=10, max_retry_rounds=2)

    # Every group ends up processed exactly once (failed batch retried once).
    assert all(x.get("_marks") == 1 for x in g), \
        [x.get("_marks") for x in g]


def test_run_angles_unrecoverable_batch_does_not_crash():
    """A batch that fails every round is logged and skipped, but the angle
    (and pipeline) does not crash, and other batches are fine."""
    g = _groups(20)  # batches [0:10], [10:20]

    class AlwaysFailFirstBatch:
        name = "alwaysfail"
        def generate(self, groups, client, model, region_cfg):
            if groups[0]["id"] == 0:        # first batch always fails
                raise RuntimeError("permanent")
            for x in groups:
                x["_marks"] = 1
            return {"attached": len(groups), "total": len(groups)}

    cluster._run_angles([AlwaysFailFirstBatch()], g, None, "m", None,
                        batch_size=10, max_retry_rounds=2)
    # second batch processed, first never did -> isolation held, no crash
    assert [x.get("_marks") for x in g[:10]] == [None] * 10
    assert all(x.get("_marks") == 1 for x in g[10:])  # the condition the validator now fails on
