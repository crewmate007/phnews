"""Shared utilities for angle plugins.

Angles are independent personas for generating market questions. Each lives
in its own file (see serious.py, reddit.py, tiktok.py) and uses a small
shared toolkit defined here:

- RESOLVER_URL_ALLOWLIST: domain regex every angle MUST run a candidate URL
  through, so hallucinated URLs degrade to plain-text source labels instead
  of becoming clickable dead links.
- parse_json_response: tolerates trailing commas + code fences in LLM output.
- generate_content_with_retry: retries Gemini transient overloads.
- clip(text, n): truncate with ellipsis for prompt-side text snippets.

Everything else (prompt template, input builder, output schema) belongs in
each angle's own module so adding a new angle stays a single-file change.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Dict


# Shared resolver URL allowlist. Used by every angle to filter hallucinated
# URLs. When a model emits a URL that doesn't match, the source label is kept
# as plain text. Expand this list as new official resolvers appear.
RESOLVER_URL_ALLOWLIST = re.compile(
    r"^https?://("
    # Philippines government
    r"[a-z0-9-]+\.gov\.ph(?:/|$)"
    r"|(?:www\.)?bsp\.gov\.ph(?:/|$)"
    r"|(?:www\.)?doe\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dof\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dbm\.gov\.ph(?:/|$)"
    r"|(?:www\.)?neda\.gov\.ph(?:/|$)"
    r"|(?:www\.)?pagasa\.dost\.gov\.ph(?:/|$)"
    r"|(?:www\.)?phivolcs\.dost\.gov\.ph(?:/|$)"
    r"|(?:www\.)?comelec\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dilg\.gov\.ph(?:/|$)"
    r"|(?:www\.)?congress\.gov\.ph(?:/|$)"
    r"|(?:www\.)?senate\.gov\.ph(?:/|$)"
    r"|(?:www\.)?dswd\.gov\.ph(?:/|$)"
    r"|(?:www\.)?meralco\.com\.ph(?:/|$)"
    r"|(?:www\.)?ngcp\.ph(?:/|$)"
    r"|(?:www\.)?pse\.com\.ph(?:/|$)"
    # Indonesia government
    r"|(?:www\.)?bi\.go\.id(?:/|$)"
    r"|(?:www\.)?kemenkeu\.go\.id(?:/|$)"
    r"|(?:www\.)?bps\.go\.id(?:/|$)"
    r"|(?:www\.)?bmkg\.go\.id(?:/|$)"
    r"|(?:www\.)?idx\.co\.id(?:/|$)"
    r"|(?:www\.)?kpu\.go\.id(?:/|$)"
    # Social handles
    r"|(?:www\.)?x\.com/[A-Za-z0-9_]+"
    r"|(?:www\.)?twitter\.com/[A-Za-z0-9_]+"
    r"|(?:www\.)?facebook\.com/[A-Za-z0-9._-]+"
    r"|(?:www\.)?youtube\.com/@[A-Za-z0-9._-]+"
    # Public statistical / trends services
    r"|trends\.google\.com(?:/|$)"
    r"|trends24\.in/(?:philippines|indonesia)"
    r")",
    re.IGNORECASE,
)


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def parse_json_response(text: str) -> Dict:
    """Parse LLM JSON output, tolerating code fences and trailing commas."""
    text = text.strip()
    if text.startswith("```"):
        text = text[3:]
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.lstrip("\r\n")
        end = text.rfind("```")
        if end != -1:
            text = text[:end]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", text))


def generate_content_with_retry(
    client,
    model: str,
    prompt: str,
    attempts: int = 4,
    usage_label: str | None = None,
):
    """Retry transient Gemini overloads without hiding persistent failures."""
    last_exc = None
    active_model = model
    fallback_model = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
    for attempt in range(attempts):
        try:
            response = _call_generate_content(client, active_model, prompt)
            log_gemini_usage(response, usage_label)
            return response
        except Exception as exc:
            last_exc = exc
            message = str(exc).lower()
            status_code = getattr(exc, "status_code", None)
            # Network-level disconnects (httpx RemoteProtocolError /
            # ConnectError / ReadError) surface as exception *types*, not HTTP
            # status codes, and their str() doesn't contain "503"/"timeout".
            # On 2026-05-29 a "Server disconnected without sending a response"
            # RemoteProtocolError fell through this check, the serious angle
            # was swallowed by the orchestrator try/except, and every PH group
            # shipped unscored (TOP tier = 0). Match disconnects by type name
            # and message so they retry.
            exc_type = type(exc).__name__.lower()
            transient = status_code in (429, 500, 502, 503, 504) or any(
                marker in message
                for marker in (
                    "503", "504", "429", "unavailable", "high demand", "timeout",
                    "deadline", "deadline_exceeded",
                    "disconnected", "connection reset", "connection aborted",
                    "remote protocol", "server disconnected", "read error",
                )
            ) or any(
                marker in exc_type
                for marker in (
                    "remoteprotocol", "connecterror", "readerror",
                    "connecttimeout", "readtimeout", "protocolerror",
                )
            )
            if not transient or attempt == attempts - 1:
                raise
            if _should_fallback_from_model(status_code, message, active_model, fallback_model):
                print(
                    f"[WARN] Gemini model {active_model} hit 503/high demand; "
                    f"falling back to {fallback_model}",
                    file=sys.stderr,
                )
                active_model = fallback_model
            time.sleep(5 * (2 ** attempt))
    raise last_exc


def _should_fallback_from_model(
    status_code,
    message: str,
    active_model: str,
    fallback_model: str,
) -> bool:
    if not fallback_model or active_model == fallback_model:
        return False
    if status_code == 503:
        return True
    return "503" in message or "high demand" in message or "unavailable" in message


def _call_generate_content(client, model: str, prompt: str):
    config = {
        "thinking_config": {"thinking_budget": int(os.environ.get("GEMINI_THINKING_BUDGET", "0"))}
    }
    try:
        return client.models.generate_content(model=model, contents=prompt, config=config)
    except TypeError:
        return client.models.generate_content(model=model, contents=prompt)
    except Exception as exc:
        if "thinking" not in str(exc).lower():
            raise
        return client.models.generate_content(model=model, contents=prompt)


def log_gemini_usage(response, label: str | None = None) -> None:
    """Log Gemini token usage and cache-hit metadata when the SDK exposes it."""
    if os.environ.get("PHNEWS_GEMINI_USAGE_LOG", "1") == "0":
        return
    usage = gemini_usage_summary(response)
    if not usage:
        return
    name = f" {label}" if label else ""
    print(
        "[INFO] Gemini usage"
        f"{name}: prompt={_fmt_usage(usage.get('prompt_token_count'))}"
        f" output={_fmt_usage(usage.get('candidates_token_count'))}"
        f" total={_fmt_usage(usage.get('total_token_count'))}"
        f" cached={_fmt_usage(usage.get('cached_content_token_count'))}"
        f" cache_hit={usage['cache_hit']}",
        file=sys.stderr,
    )


def gemini_usage_summary(response) -> Dict | None:
    """Return normalized token usage metadata for Gemini responses."""
    meta = (
        getattr(response, "usage_metadata", None)
        or getattr(response, "usageMetadata", None)
    )
    if meta is None:
        return None
    cached = _usage_value(meta, "cached_content_token_count", "cachedContentTokenCount")
    summary = {
        "prompt_token_count": _usage_value(meta, "prompt_token_count", "promptTokenCount"),
        "candidates_token_count": _usage_value(meta, "candidates_token_count", "candidatesTokenCount"),
        "total_token_count": _usage_value(meta, "total_token_count", "totalTokenCount"),
        "cached_content_token_count": cached,
        "cache_hit": "unknown",
    }
    if cached is not None:
        summary["cache_hit"] = "yes" if _as_int(cached) > 0 else "no"
    return summary


def _usage_value(meta, snake_name: str, camel_name: str):
    if isinstance(meta, dict):
        return meta.get(snake_name, meta.get(camel_name))
    value = getattr(meta, snake_name, None)
    if value is not None:
        return value
    return getattr(meta, camel_name, None)


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fmt_usage(value) -> str:
    return "?" if value is None else str(value)


def clip(text: str, n: int) -> str:
    """Truncate text to n chars with '...' suffix."""
    s = str(text or "")
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def safe_url(url) -> str | None:
    """Return URL if allowlisted, else None. Caller falls back to plain text."""
    if not url:
        return None
    if RESOLVER_URL_ALLOWLIST.match(str(url).strip()):
        return str(url).strip()
    return None
