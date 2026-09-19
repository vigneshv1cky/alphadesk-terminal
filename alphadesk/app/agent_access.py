"""Readers connect their own agent to AlphaDesk (2026-09-17).

AlphaDesk does not run an agent of its own. A reader points the agent they
already use — Claude, ChatGPT, Cursor, opencode, anything that speaks MCP —
at this app's tool server, and every call runs as that reader on their own
keys (app/agent_tools.py). Their agent brings what it already has (web
browsing, memory, file uploads, their subscription); AlphaDesk brings the
data and the tools that verify their citations.

This module is the credential for that:

  * ACCESS TOKENS a reader issues on the Account page, one per agent they
    connect. A token is "adk_" plus 256 bits of randomness. It is shown once;
    only its SHA-256 is stored — a fast hash is enough because the token is
    random, not a password a person chose. Revoking one stops it at once:
    every request looks the hash up, nothing is cached.
  * A RATE LIMIT per token, so a looping agent cannot spend a reader's vendor
    quota (or the instance's EDGAR allowance) in a burst. It is kept in
    memory per instance: with several instances an agent may get a little
    more than the limit, never unbounded.
  * THE HOSTS the tool server answers: loopback, plus the instance's public
    address from ALPHADESK_BASE_URL. A request naming any other host is
    refused before a tool runs (the MCP library's DNS-rebinding check).
"""

from __future__ import annotations

import collections
import hashlib
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

TOKEN_PREFIX = "adk_"
#: Live tokens one reader may hold.
MAX_TOKENS = 10
#: Tool-server requests one token may make per minute. An MCP tool call is
#: one request; listing tools at connect is one more.
RATE_PER_MIN = 120
#: last-used is written at most this often per token.
TOUCH_EVERY_S = 60.0


def bearer(header_value: str | None) -> str | None:
    """The token from an `Authorization: Bearer …` header, or None."""
    text = (header_value or "").strip()
    if not text.lower().startswith("bearer "):
        return None
    return text[7:].strip() or None


class TokenLimit(Exception):
    """The reader already holds MAX_TOKENS live tokens."""


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue(user_id: str, name: str) -> tuple[dict, str]:
    """(the stored row as listed, the token itself — shown once)."""
    from alphadesk.ledger import store
    if len(store.list_agent_access_tokens(user_id)) >= MAX_TOKENS:
        raise TokenLimit(f"revoke a token first — at most {MAX_TOKENS} can be live")
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token_id = "tok_" + secrets.token_hex(6)
    label = (name or "").strip()[:60] or "agent"
    store.create_agent_access_token(user_id, token_id, label, _hash(secret), secret[-4:])
    row = next(r for r in store.list_agent_access_tokens(user_id) if r["token_id"] == token_id)
    return row, secret


_touched: dict[str, float] = {}
_touch_lock = threading.Lock()


def resolve(secret: str) -> tuple[str, str] | None:
    """(token id, reader) for a live access token, else None."""
    if not secret.startswith(TOKEN_PREFIX):
        return None
    from alphadesk.ledger import store
    row = store.agent_access_token_by_hash(_hash(secret))
    if row is None:
        return None
    now = time.monotonic()
    with _touch_lock:
        due = now - _touched.get(row["token_id"], -TOUCH_EVERY_S) >= TOUCH_EVERY_S
        if due:
            _touched[row["token_id"]] = now
    if due:
        store.touch_agent_access_token(row["token_id"])
    return row["token_id"], row["user_id"]


class RateLimit:
    """A sliding one-minute window per key."""

    def __init__(self, per_min: int = RATE_PER_MIN) -> None:
        self.per_min = per_min
        self._hits: dict[str, collections.deque] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float:
        """0 when the request may proceed (and counts it); otherwise the
        seconds until it may."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, collections.deque())
            while hits and now - hits[0] >= 60.0:
                hits.popleft()
            if len(hits) >= self.per_min:
                return max(0.1, 60.0 - (now - hits[0]))
            hits.append(now)
            return 0.0


limiter = RateLimit()


def allowed_hosts() -> tuple[list[str], list[str]]:
    """(Host header values, Origin values) the tool server answers."""
    hosts = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"]
    origins = ["http://127.0.0.1", "http://127.0.0.1:*", "http://localhost", "http://localhost:*"]
    base = (os.environ.get("ALPHADESK_BASE_URL") or "").strip().rstrip("/")
    if base:
        parts = urlsplit(base)
        if parts.netloc:
            hosts.append(parts.netloc)
            if ":" not in parts.netloc:
                hosts.append(parts.netloc + ":*")
            origins.append(f"{parts.scheme}://{parts.netloc}")
    return hosts, origins
