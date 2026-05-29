"""Round-trip test: db.py (write) and db_to_clusters_json (read) are inverses.

Takes a realistic group, captures exactly what db.write_run would insert into
Supabase via a recording fake client, turns those captured payloads into
table rows (adding the ids the DB would generate), feeds them through the pure
rows_to_clusters() reconstruction, then runs the result through gen_html's
build_group and asserts the rendered fields match a build_group of the
original. If write and read drift apart, this fails.
"""
import db
import gen_html
from db_to_clusters_json import rows_to_clusters

from test_db import SAMPLE_GROUP, FakeClient


def _capture_and_reconstruct(group):
    """Write `group` through a fake client, then rebuild the clusters dict
    from the captured insert payloads."""
    fake = FakeClient()
    import pytest  # noqa
    import os
    os.environ["SUPABASE_URL"] = "https://fake.supabase.co"
    os.environ["SUPABASE_SERVICE_KEY"] = "fake"
    _orig = db.get_client
    db.get_client = lambda: fake
    try:
        db.write_run({"total_entries": 120, "clustered_at": "2026-05-29T00:00:00+00:00",
                      "cluster_pipeline": "broad_then_angles",
                      "target_group_range": [25, 60], "noise_count": 5,
                      "groups": [group]}, "ph", "2026-05-29")
    finally:
        db.get_client = _orig

    # Reassemble rows from captured payloads, assigning DB-style ids.
    run = {"id": "run-1", "region": "ph", "run_date": "2026-05-29",
           "total_entries": 120, "clustered_at": "2026-05-29T00:00:00+00:00",
           "cluster_pipeline": "broad_then_angles", "target_group_range": [25, 60],
           "noise_count": 5}
    topics, angles, sources = [], [], []
    tid = "topic-1"
    for table, op, payload in fake.log:
        if table == "topics" and op == "insert":
            row = dict(payload); row["id"] = tid
            topics.append(row)
        elif table == "angles" and op == "insert":
            for a in payload:
                row = dict(a); row["topic_id"] = tid
                angles.append(row)
        elif table == "source_examples" and op == "insert":
            for s in payload:
                row = dict(s); row["topic_id"] = tid
                sources.append(row)
    return rows_to_clusters(run, topics, angles, sources)


def test_roundtrip_preserves_rendered_fields():
    clusters = _capture_and_reconstruct(SAMPLE_GROUP)
    assert clusters["total_entries"] == 120
    assert clusters["noise_count"] == 5
    assert len(clusters["groups"]) == 1

    rebuilt = gen_html.build_group(clusters["groups"][0])
    original = gen_html.build_group(SAMPLE_GROUP)

    # Every field gen_html actually renders must survive the round trip.
    for key in ("name_en", "name_zh", "density", "R", "S", "T", "U", "H",
                "bettable", "question_en", "question_zh", "source",
                "source_mix", "source_labels"):
        assert rebuilt[key] == original[key], f"{key}: {rebuilt[key]!r} != {original[key]!r}"

    # BDLT total preserved
    assert rebuilt["BDLT"]["total"] == original["BDLT"]["total"]
    # angle arrays preserved
    assert len(rebuilt["reddit_angles"]) == len(original["reddit_angles"])
    assert len(rebuilt["tiktok_angles"]) == len(original["tiktok_angles"])
    assert rebuilt["reddit_angles"][0]["question_zh"] == original["reddit_angles"][0]["question_zh"]
    # source examples preserved (title not truncated, etc.)
    assert len(rebuilt["source_examples"]) == len(original["source_examples"])
    assert rebuilt["source_examples"][0]["title_en"] == original["source_examples"][0]["title_en"]


def test_roundtrip_serious_candidates_rebuilt():
    clusters = _capture_and_reconstruct(SAMPLE_GROUP)
    g = clusters["groups"][0]
    cands = g.get("serious_candidates") or []
    assert len(cands) == 2  # SAMPLE_GROUP has 2 candidates
    # primary candidate's scores survive (BDLT nested dict in scores jsonb)
    primary = cands[0]
    assert primary["suggested_question"] == SAMPLE_GROUP["serious_candidates"][0]["suggested_question"]
    assert primary["R"] == 2 and "BDLT" in primary


def test_roundtrip_disposition_matches():
    """The disposition computed from the reconstructed group must equal the
    one from the original (so TOP/candidate/etc. tiers are stable)."""
    clusters = _capture_and_reconstruct(SAMPLE_GROUP)
    rebuilt = gen_html.build_group(clusters["groups"][0])
    original = gen_html.build_group(SAMPLE_GROUP)
    assert gen_html.classify_disposition(rebuilt) == gen_html.classify_disposition(original)
