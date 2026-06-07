"""Unit tests for shared angle utilities (mvp/angles/base.py)."""
from types import SimpleNamespace

import pytest

from angles.base import (
    clip,
    gemini_usage_summary,
    generate_content_with_retry,
    log_gemini_usage,
    parse_json_response,
    safe_url,
)


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


def test_gemini_usage_summary_detects_cache_hit():
    resp = SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=123,
        candidates_token_count=45,
        total_token_count=168,
        cached_content_token_count=67,
    ))
    usage = gemini_usage_summary(resp)
    assert usage["prompt_token_count"] == 123
    assert usage["cached_content_token_count"] == 67
    assert usage["cache_hit"] == "yes"


def test_log_gemini_usage_reports_cache_hit(capsys, monkeypatch):
    monkeypatch.delenv("PHNEWS_GEMINI_USAGE_LOG", raising=False)
    resp = SimpleNamespace(usage_metadata={
        "promptTokenCount": 100,
        "candidatesTokenCount": 20,
        "totalTokenCount": 120,
        "cachedContentTokenCount": 50,
    })
    log_gemini_usage(resp, "serious_angle:reordered")
    err = capsys.readouterr().err
    assert "serious_angle:reordered" in err
    assert "cached=50" in err
    assert "cache_hit=yes" in err


# --- generate_content_with_retry transient handling --------------------------

class _Resp:
    text = '{"ok": 1}'


class _FlakyModels:
    """Fails `fail_n` times with `exc`, then succeeds."""
    def __init__(self, exc, fail_n):
        self.exc = exc
        self.fail_n = fail_n
        self.calls = 0

    def generate_content(self, model=None, contents=None):
        self.calls += 1
        if self.calls <= self.fail_n:
            raise self.exc
        return _Resp()


class _Client:
    def __init__(self, models):
        self.models = models


class RemoteProtocolError(Exception):
    """Mimics httpx.RemoteProtocolError by type name."""


def test_retry_recovers_from_remote_protocol_error(monkeypatch):
    # Regression for 2026-05-29: a "Server disconnected" RemoteProtocolError
    # must be treated as transient and retried, not raised on first hit.
    monkeypatch.setattr("angles.base.time.sleep", lambda *_: None)
    exc = RemoteProtocolError("Server disconnected without sending a response.")
    models = _FlakyModels(exc, fail_n=2)
    resp = generate_content_with_retry(_Client(models), "fake", "prompt")
    assert resp.text == '{"ok": 1}'
    assert models.calls == 3  # 2 failures + 1 success


def test_retry_recovers_from_disconnect_message(monkeypatch):
    monkeypatch.setattr("angles.base.time.sleep", lambda *_: None)
    exc = Exception("connection reset by peer")
    models = _FlakyModels(exc, fail_n=1)
    resp = generate_content_with_retry(_Client(models), "fake", "prompt")
    assert resp.text == '{"ok": 1}'


def test_retry_gives_up_on_non_transient(monkeypatch):
    monkeypatch.setattr("angles.base.time.sleep", lambda *_: None)
    exc = ValueError("totally unrelated bug")
    models = _FlakyModels(exc, fail_n=99)
    with pytest.raises(ValueError):
        generate_content_with_retry(_Client(models), "fake", "prompt")
    assert models.calls == 1  # not retried
