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
import re
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


def generate_content_with_retry(client, model: str, prompt: str, attempts: int = 4):
    """Retry transient Gemini overloads without hiding persistent failures."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return client.models.generate_content(model=model, contents=prompt)
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
                    "503", "429", "unavailable", "high demand", "timeout",
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
            time.sleep(5 * (2 ** attempt))
    raise last_exc


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
