"""The terminal's tools, served to an agent AS A READER (2026-09-17).

The same MCP tools `python -m alphadesk.main mcp` serves, mounted inside the
web app instead of beside it. Inside, a tool call shares everything a page
request has — the store, the caches, the key vault and the per-reader data
router — so there is nothing to duplicate and nothing to keep in step.

The difference from the standalone server is identity. Every call must carry
a bearer token the reader authorised. The gate verifies it and runs the call
as that reader, exactly the way the login gate runs a page request: the
reader's own keys, caches keyed by them, and a 428 where they have connected
nothing that carries the surface. Without a valid token the request never
reaches a tool.

Three more fences, all deliberate:

  * STATELESS. Each MCP request is complete in itself, so nothing about one
    reader's session can linger in a transport another request reuses.
  * KNOWN HOSTS ONLY. The MCP library's DNS-rebinding protection is left on
    and admits loopback plus this instance's public address
    (ALPHADESK_BASE_URL) — readers' own agents call it from outside.
  * RATE LIMITED per token (app/agent_access.py).

Two credentials open the gate: an access token a reader issued on the
Account page (app/agent_access.py), or an OAuth access token from a
connector's sign-in (app/agent_oauth.py). (A short-lived signed token, for an
agent runtime the app would host itself, existed briefly and was removed on
2026-09-17 when AlphaDesk went MCP-first: readers bring their own agent.)

Only AlphaDesk's own read-only tools are here.
"""

from __future__ import annotations

import json

import anyio

from alphadesk import agent_log
from alphadesk.identity import reset_request_user, set_request_user
from alphadesk.app import agent_access, agent_oauth


#: Where the tools answer, under the app. The MCP endpoint itself is this
#: prefix plus the library's path, "/mcp".
MOUNT = "/api/agent/tools"


def client_address(scope) -> str:
    """The caller's address as the FRONT DOOR saw it: the last X-Forwarded-For
    entry — Cloud Run appends the real client, and anything earlier was sent by
    the caller and proves nothing — else the socket peer."""
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
    forwarded = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return forwarded[-1] if forwarded else (scope.get("client") or ("",))[0]


def _host_ok(headers: dict) -> bool:
    """The Host header is one this server answers to (the same list the tool
    server's rebinding guard uses)."""
    import fnmatch
    host = (headers.get("host") or "").lower()
    hosts, _ = agent_access.allowed_hosts()
    return any(fnmatch.fnmatch(host, h.lower()) for h in hosts)


class TokenGate:
    """ASGI wrapper: no valid token, no tool. A valid one runs the whole
    request as its reader — the tool functions resolve their data router from
    the same request identity a page request sets."""

    def __init__(self, app):
        self.app = app

    async def _feedback(self, scope, receive, send, headers, uid, limit_key):
        """POST .../feedback: an agent says whether a result was useful. It
        writes one row to our own usage log and nothing else (2026-10-03)."""
        if not _host_ok(headers):
            await _json(send, 421, {"detail": "unknown host"})
            return
        chunks, size = [], 0
        while True:
            message = await receive()
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 8192:
                await _json(send, 413, {"detail": "too large"})
                return
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        try:
            body = json.loads(b"".join(chunks) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("a JSON object is required")
        except ValueError:
            await _json(send, 400, {"detail": "a JSON object is required"})
            return
        held = set_request_user(uid)
        said = agent_log.set_context(limit_key, headers.get("x-agent-task"), headers.get("x-agent-intent"))
        try:
            out = await anyio.to_thread.run_sync(agent_log.record_feedback, body)
        except ValueError as exc:
            await _json(send, 400, {"detail": str(exc)})
            return
        finally:
            agent_log.reset_context(said)
            reset_request_user(held)
        await _json(send, 200, out)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        token = agent_access.bearer(headers.get("authorization"))
        uid = limit_key = None
        allowed = []
        if token and token.startswith(agent_oauth.ACCESS_PREFIX):
            # An access token from the OAuth sign-in (connectors).
            found = await anyio.to_thread.run_sync(agent_oauth.resolve_access, token)
            if found:
                limit_key, uid = found
        elif token and token.startswith(agent_access.TOKEN_PREFIX):
            # A reader-issued access token: a store lookup, so off the loop.
            row = await anyio.to_thread.run_sync(agent_access.resolve_row, token)
            if row:
                limit_key, uid = row["token_id"], row["user_id"]
                allowed = agent_access.parse_allowlist(row.get("allowed_ips") or "")
        if not uid:
            await _refuse(send)
            return
        # A token its reader tied to addresses answers only to them, so a
        # leaked one is useless from anywhere else.
        if not agent_access.address_allowed(client_address(scope), allowed):
            await _forbidden(send)
            return
        # The allow-list reaches the agent too: a token made by an account no
        # longer the login stops working (app/auth.py, allowed_emails).
        from alphadesk.app import auth as _auth
        if not await anyio.to_thread.run_sync(_auth.uid_allowed, uid):
            await _forbidden_account(send)
            return
        wait = agent_access.limiter.check(limit_key)
        if wait:
            await _slow_down(send, wait)
            return
        remaining = agent_access.limiter.remaining(limit_key)

        async def send_with_limits(message):
            # Said on every answer, so a program can slow down before it is
            # refused rather than learn the limit from a 429.
            if message["type"] == "http.response.start":
                message = {**message, "headers": [
                    *message.get("headers", []),
                    (b"x-ratelimit-limit", str(agent_access.limiter.per_min).encode()),
                    (b"x-ratelimit-remaining", str(remaining).encode()),
                    (b"x-ratelimit-window", str(int(agent_access.limiter.window_s)).encode())]}
            await send(message)

        if scope.get("method") == "POST" and scope.get("path", "").rstrip("/").endswith("/feedback"):
            await self._feedback(scope, receive, send_with_limits, headers, uid, limit_key)
            return
        held = set_request_user(uid)
        # WHY THE CALLS ARE BEING MADE, as far as the caller says (2026-10-03):
        # an optional task id and a one-line intent, kept beside each call.
        said = agent_log.set_context(limit_key, headers.get("x-agent-task"), headers.get("x-agent-intent"),
                                     headers.get("user-agent"), headers.get("x-agent-toolset"))
        try:
            await self.app(scope, receive, send_with_limits)
        finally:
            agent_log.reset_context(said)
            reset_request_user(held)


async def _json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))]})
    await send({"type": "http.response.body", "body": body})


async def _forbidden_account(send) -> None:
    body = json.dumps({"detail": "this account is not allowed on this server"}).encode("utf-8")
    await send({"type": "http.response.start", "status": 403, "headers": [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]})
    await send({"type": "http.response.body", "body": body})


async def _forbidden(send) -> None:
    body = json.dumps({"detail": "this token cannot be used from this address"}).encode("utf-8")
    await send({"type": "http.response.start", "status": 403, "headers": [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]})
    await send({"type": "http.response.body", "body": body})


async def _refuse(send) -> None:
    body = json.dumps({"detail": "a valid agent token is required"}).encode("utf-8")
    await send({"type": "http.response.start", "status": 401, "headers": [
        (b"content-type", b"application/json"),
        # Names the protected resource metadata, which is how a connector
        # finds the OAuth sign-in (RFC 9728).
        (b"www-authenticate", (f'Bearer realm="alphadesk-agent-tools", '
                               f'resource_metadata="{agent_oauth.resource_metadata_url()}"').encode("latin-1")),
        (b"content-length", str(len(body)).encode("ascii")),
    ]})
    await send({"type": "http.response.body", "body": body})


async def _slow_down(send, wait_s: float) -> None:
    body = json.dumps({"detail": "too many tool calls — slow down"}).encode("utf-8")
    await send({"type": "http.response.start", "status": 429, "headers": [
        (b"content-type", b"application/json"),
        (b"retry-after", str(int(wait_s) + 1).encode("ascii")),
        (b"content-length", str(len(body)).encode("ascii")),
    ]})
    await send({"type": "http.response.body", "body": body})


def _fresh_inner():
    """A new MCP app with a NEW session manager. The library's manager runs
    once per instance, so an app started twice in one process — a dev
    reload, every test — needs its own; the tools themselves are shared."""
    from alphadesk.mcp_server import mcp
    mcp.settings.streamable_http_path = "/mcp"
    mcp.settings.stateless_http = True
    from mcp.server.transport_security import TransportSecuritySettings
    hosts, origins = agent_access.allowed_hosts()
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)
    mcp._session_manager = None
    inner = mcp.streamable_http_app()
    return inner, mcp.session_manager


def build():
    """(the gated ASGI app to mount, an async context manager that must span
    the web app's lifetime). Each run of the lifespan swaps in a fresh MCP
    app behind the same gate, so the mount itself never changes."""
    import contextlib

    inner, _ = _fresh_inner()
    gate = TokenGate(inner)

    @contextlib.asynccontextmanager
    async def lifetime():
        gate.app, sessions = _fresh_inner()
        async with sessions.run():
            yield

    return gate, lifetime
