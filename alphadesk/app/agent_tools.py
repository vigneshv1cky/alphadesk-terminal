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

from alphadesk.identity import reset_request_user, set_request_user
from alphadesk.app import agent_access, agent_oauth


#: Where the tools answer, under the app. The MCP endpoint itself is this
#: prefix plus the library's path, "/mcp".
MOUNT = "/api/agent/tools"


class TokenGate:
    """ASGI wrapper: no valid token, no tool. A valid one runs the whole
    request as its reader — the tool functions resolve their data router from
    the same request identity a page request sets."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        token = agent_access.bearer(headers.get("authorization"))
        uid = limit_key = None
        if token and token.startswith(agent_oauth.ACCESS_PREFIX):
            # An access token from the OAuth sign-in (connectors).
            found = await anyio.to_thread.run_sync(agent_oauth.resolve_access, token)
            if found:
                limit_key, uid = found
        elif token and token.startswith(agent_access.TOKEN_PREFIX):
            # A reader-issued access token: a store lookup, so off the loop.
            found = await anyio.to_thread.run_sync(agent_access.resolve, token)
            if found:
                limit_key, uid = found
        if not uid:
            await _refuse(send)
            return
        # The access gate reaches the agent too: a reader past the trial with
        # no subscription is refused here as on the web (alphadesk/billing.py).
        from alphadesk import billing
        if await anyio.to_thread.run_sync(billing.blocked_user, uid):
            await _payment_required(send)
            return
        wait = agent_access.limiter.check(limit_key)
        if wait:
            await _slow_down(send, wait)
            return
        held = set_request_user(uid)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_user(held)


async def _payment_required(send) -> None:
    body = json.dumps({"detail": "this AlphaDesk account's free trial has ended; subscribe on the Account page"}).encode("utf-8")
    await send({"type": "http.response.start", "status": 402, "headers": [
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
