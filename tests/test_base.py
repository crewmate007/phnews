"""Unit tests for shared angle utilities (mvp/angles/base.py)."""
from angles.base import parse_json_response, safe_url, clip


def test_parse_plain_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_code_fence():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_bare_fence():
    assert parse_json_response('```\n{"a": 1}\n```') == {"a": 1}


def test_parse_trailing_comma():
    # The bug that crashed the daily run on 2026-05-22.
    assert parse_json_response('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}


def test_parse_fence_plus_trailing_comma():
    assert parse_json_response('```json\n{"groups":[{"id":1,},]}\n```') == {"groups": [{"id": 1}]}


def test_safe_url_allows_gov_ph():
    assert safe_url("https://www.bsp.gov.ph/x") == "https://www.bsp.gov.ph/x"


def test_safe_url_allows_gov_id():
    assert safe_url("https://www.bi.go.id/x") == "https://www.bi.go.id/x"


def test_safe_url_allows_social_handle():
    assert safe_url("https://x.com/dof_ph") == "https://x.com/dof_ph"


def test_safe_url_allows_trends():
    assert safe_url("https://trends.google.com/trends") == "https://trends.google.com/trends"


def test_safe_url_rejects_random_domain():
    assert safe_url("https://evil.example/x") is None


def test_safe_url_handles_none():
    assert safe_url(None) is None
    assert safe_url("") is None


def test_clip_short_passthrough():
    assert clip("hello", 10) == "hello"


def test_clip_truncates_with_ellipsis():
    out = clip("a" * 50, 10)
    assert len(out) == 10 and out.endswith("...")
