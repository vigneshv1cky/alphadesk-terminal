"""Sign-in for agent apps that cannot take a pasted token (2026-09-17).

Claude.ai and ChatGPT add a remote MCP server as a "connector" by URL alone,
and then expect to sign the reader in over OAuth — the MCP authorization
spec: OAuth 2.1 with PKCE, dynamic client registration (RFC 7591),
authorization server metadata (RFC 8414) and protected resource metadata
(RFC 9728). This module makes AlphaDesk that authorization server.

The protocol work — validating requests, redirect URIs, scopes and the PKCE
verifier — is the MCP library's own handlers (mcp.server.auth). What lives
here is what they leave to the server: where clients, codes and tokens are
kept, and the one step only AlphaDesk can do, asking the signed-in reader
whether to let the app in.

THE FLOW, as a connector sees it:

  1. It calls the tool server with no token, gets 401 naming the protected
     resource metadata, and from there finds this authorization server.
  2. It registers itself and sends the reader's browser to /authorize.
  3. The library validates the request; `authorize` answers with our consent
     page, carrying the request SIGNED (so nothing about it can be altered in
     the browser and no pending table is needed).
  4. The reader — signed in, or sent to sign in first and brought back — sees
     the app's name and where it will send them, and approves or refuses.
  5. Approval stores a single-use code (5 minutes) and redirects back; the
     app exchanges it, with its PKCE verifier, for an access token (1 hour)
     and a refresh token (90 days, rotated on every use).

WHAT A GRANT IS. One approval by one reader for one app: every tool call on
its access token runs as that reader, on their keys, rate-limited like a
pasted token. It appears on the Account page under Agent access and is
revoked there. Codes and tokens are stored only as SHA-256; a client's
record, secret included, is vault-sealed.

The consent POST is protected three ways: the session cookie is SameSite
(a cross-site form post arrives signed out), the Origin must be this
instance, and the page refuses to be framed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

SCOPE = "alphadesk"
ACCESS_PREFIX = "ado_"
REFRESH_PREFIX = "adr_"
CODE_TTL_S = 5 * 60
ACCESS_TTL_S = 60 * 60
REFRESH_TTL_S = 90 * 24 * 3600
REQUEST_TTL_S = 10 * 60
#: Where the reader is sent back to after signing in.
RETURN_COOKIE = "alphadesk_return"
CONSENT_PATH = "/oauth/consent"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def base_url() -> str:
    """This instance's public origin — the issuer and the resource."""
    base = (os.environ.get("ALPHADESK_BASE_URL") or "").strip().rstrip("/")
    return base or f"http://localhost:{int(os.environ.get('DASHBOARD_PORT', '8000'))}"


def resource_url() -> str:
    from alphadesk.app.agent_tools import MOUNT
    return f"{base_url()}{MOUNT}/mcp"


def resource_metadata_url() -> str:
    from alphadesk.app.agent_tools import MOUNT
    return f"{base_url()}/.well-known/oauth-protected-resource{MOUNT}/mcp"


# ── the signed consent request ────────────────────────────────────────────


def _request_key() -> bytes:
    from alphadesk.ledger.vault import _master
    return hmac.new(_master(), b"alphadesk oauth consent request v1", hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_request(payload: dict, now: float | None = None) -> str:
    body = dict(payload, exp=int((now if now is not None else time.time()) + REQUEST_TTL_S))
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{_b64(raw)}.{_b64(hmac.new(_request_key(), raw, hashlib.sha256).digest())}"


def read_request(blob: str, now: float | None = None) -> dict | None:
    """The request a consent page carries, or None if altered or expired."""
    try:
        head, tail = (blob or "").split(".", 1)
        raw, sig = _unb64(head), _unb64(tail)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(sig, hmac.new(_request_key(), raw, hashlib.sha256).digest()):
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    if (now if now is not None else time.time()) >= int(body.get("exp", 0)):
        return None
    return body


# ── the provider the library's handlers call ──────────────────────────────


def _seal_client(info: OAuthClientInformationFull) -> str:
    from alphadesk.ledger import vault
    return vault.encrypt({"client": info.model_dump(mode="json")})


def _grant_tokens(now: int) -> tuple[str, str, dict]:
    access = ACCESS_PREFIX + secrets.token_urlsafe(32)
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
    return access, refresh, {
        "access_hash": _hash(access), "access_expires": now + ACCESS_TTL_S,
        "refresh_hash": _hash(refresh), "refresh_expires": now + REFRESH_TTL_S,
    }


class Provider:
    """OAuthAuthorizationServerProvider over the store."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        from alphadesk.ledger import store, vault
        sealed = await anyio.to_thread.run_sync(store.get_oauth_client, client_id)
        if not sealed:
            return None
        return OAuthClientInformationFull.model_validate(vault.decrypt(sealed)["client"])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        from alphadesk.ledger import store
        # Registration is the one open write, so it is where leftovers are
        # swept: stale codes and apps that were never allowed in.
        await anyio.to_thread.run_sync(store.prune_oauth, int(time.time()))
        await anyio.to_thread.run_sync(store.save_oauth_client, client_info.client_id,
                                       _seal_client(client_info))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        blob = sign_request({
            "client_id": client.client_id,
            "state": params.state,
            "scopes": params.scopes or [SCOPE],
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "explicit": params.redirect_uri_provided_explicitly,
            "resource": params.resource,
        })
        return f"{base_url()}{CONSENT_PATH}?{urlencode({'request': blob})}"

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        from alphadesk.ledger import store
        row = await anyio.to_thread.run_sync(store.get_oauth_code, _hash(authorization_code))
        if not row or row["client_id"] != client.client_id:
            return None
        p = json.loads(row["payload"])
        return AuthorizationCode(
            code=authorization_code, scopes=p["scopes"], expires_at=float(row["expires_at"]),
            client_id=row["client_id"], code_challenge=p["code_challenge"],
            redirect_uri=p["redirect_uri"], redirect_uri_provided_explicitly=p["explicit"],
            resource=p.get("resource"))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        from alphadesk.ledger import store
        code_hash = _hash(authorization_code.code)
        row = await anyio.to_thread.run_sync(store.get_oauth_code, code_hash)
        # Spent exactly once: a replayed or raced code gets nothing.
        if not row or not await anyio.to_thread.run_sync(store.spend_oauth_code, code_hash):
            raise TokenError("invalid_grant", "authorization code already used")
        now = int(time.time())
        access, refresh, hashes = _grant_tokens(now)
        grant_id = "grant_" + secrets.token_hex(8)
        await anyio.to_thread.run_sync(store.create_oauth_grant, {
            "grant_id": grant_id,
            "user_id": row["user_id"],
            "client_id": client.client_id,
            "client_name": (client.client_name or "agent app")[:80],
            "scopes": " ".join(authorization_code.scopes),
            "resource": authorization_code.resource,
            **hashes,
        })
        # The app just consented again, so whatever it held before is a
        # leftover: one live grant per registered app per reader.
        await anyio.to_thread.run_sync(store.supersede_oauth_grants,
                                       row["user_id"], client.client_id, grant_id)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL_S,
                          refresh_token=refresh, scope=" ".join(authorization_code.scopes))

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        from alphadesk.ledger import store
        row = await anyio.to_thread.run_sync(store.oauth_grant_by, "refresh_hash", _hash(refresh_token))
        if not row or row["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=row["client_id"],
                            scopes=row["scopes"].split(), expires_at=int(row["refresh_expires"]))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        from alphadesk.ledger import store
        old = _hash(refresh_token.token)
        row = await anyio.to_thread.run_sync(store.oauth_grant_by, "refresh_hash", old)
        if not row:
            raise TokenError("invalid_grant", "refresh token is no longer valid")
        access, refresh, hashes = _grant_tokens(int(time.time()))
        rotated = await anyio.to_thread.run_sync(
            lambda: store.rotate_oauth_grant(row["grant_id"], old, hashes["access_hash"],
                                             hashes["access_expires"], hashes["refresh_hash"],
                                             hashes["refresh_expires"]))
        if not rotated:
            raise TokenError("invalid_grant", "refresh token is no longer valid")
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL_S,
                          refresh_token=refresh, scope=" ".join(scopes))

    async def load_access_token(self, token: str) -> AccessToken | None:
        from alphadesk.ledger import store
        row = await anyio.to_thread.run_sync(store.oauth_grant_by, "access_hash", _hash(token))
        if not row or int(row["access_expires"]) <= time.time():
            return None
        return AccessToken(token=token, client_id=row["client_id"], scopes=row["scopes"].split(),
                           expires_at=int(row["access_expires"]), resource=row["resource"])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        from alphadesk.ledger import store
        column = "refresh_hash" if isinstance(token, RefreshToken) else "access_hash"
        row = await anyio.to_thread.run_sync(store.oauth_grant_by, column, _hash(token.token))
        if row:
            await anyio.to_thread.run_sync(store.revoke_oauth_grant, row["grant_id"])


provider = Provider()


# ── the gate's side ───────────────────────────────────────────────────────

_touched: dict[str, float] = {}
_touch_lock = threading.Lock()


def resolve_access(token: str) -> tuple[str, str] | None:
    """(grant id, reader) for a live, unexpired access token, else None."""
    if not token.startswith(ACCESS_PREFIX):
        return None
    from alphadesk.ledger import store
    row = store.oauth_grant_by("access_hash", _hash(token))
    if row is None or int(row["access_expires"]) <= time.time():
        return None
    now = time.monotonic()
    with _touch_lock:
        due = now - _touched.get(row["grant_id"], -60.0) >= 60.0
        if due:
            _touched[row["grant_id"]] = now
    if due:
        store.touch_oauth_grant(row["grant_id"])
    return row["grant_id"], row["user_id"]


# ── the routes ────────────────────────────────────────────────────────────


def _registration_limiter():
    from alphadesk.app.agent_access import RateLimit
    return RateLimit(per_min=10)


#: Client registrations per address per minute (the endpoint is open, as the
#: spec requires, so it is the one place a stranger can write rows).
registration_limiter = _registration_limiter()


class _RateLimited:
    """Per-client-address limit in front of an open endpoint (registration).
    A class, not a function: the router treats a plain function as a request
    handler and an object as an ASGI app."""

    def __init__(self, asgi_app) -> None:
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "POST":
            headers = dict(scope.get("headers") or [])
            forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()
            who = forwarded or (scope.get("client") or ("?",))[0]
            wait = registration_limiter.check(f"register:{who}")
            if wait:
                body = b'{"error":"slow_down"}'
                await send({"type": "http.response.start", "status": 429, "headers": [
                    (b"content-type", b"application/json"), (b"retry-after", str(int(wait) + 1).encode()),
                    (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.asgi_app(scope, receive, send)


def oauth_routes() -> list:
    """The authorization server and protected resource metadata routes, at
    the root of the app as the specs place them."""
    from mcp.server.auth.handlers.metadata import MetadataHandler
    from mcp.server.auth.routes import (
        build_metadata,
        cors_middleware,
        create_auth_routes,
        create_protected_resource_routes,
    )
    from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
    from pydantic import AnyHttpUrl
    from starlette.routing import Route

    issuer = AnyHttpUrl(base_url())
    routes = create_auth_routes(
        provider, issuer,
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
        revocation_options=RevocationOptions(enabled=True),
    )
    for i, route in enumerate(routes):
        if isinstance(route, Route) and route.path == "/register":
            routes[i] = Route(route.path, endpoint=_RateLimited(route.app),
                              methods=["POST", "OPTIONS"])
        elif isinstance(route, Route) and route.path == "/.well-known/oauth-authorization-server":
            # The library's metadata omits "none", but connectors register as
            # public clients (PKCE, no secret) and the handlers accept that.
            metadata = build_metadata(issuer, None, ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]), RevocationOptions(enabled=True))
            metadata.token_endpoint_auth_methods_supported = ["none", "client_secret_post", "client_secret_basic"]
            routes[i] = Route(route.path, endpoint=cors_middleware(MetadataHandler(metadata).handle, ["GET", "OPTIONS"]),
                              methods=["GET", "OPTIONS"])
    resource = create_protected_resource_routes(
        AnyHttpUrl(resource_url()), [issuer], scopes_supported=[SCOPE], resource_name="AlphaDesk")
    # Some clients look at the bare well-known path before the path-suffixed one.
    bare = [Route("/.well-known/oauth-protected-resource", endpoint=resource[0].app,
                  methods=["GET", "OPTIONS"])]
    return routes + resource + bare


router = APIRouter()

_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https: http:; frame-ancestors 'none'",
    # same-origin, NOT no-referrer: under no-referrer a browser sends
    # `Origin: null` on the form post (Fetch spec), and the consent POST's
    # Origin check then refuses the reader's own click. same-origin still
    # sends nothing to the app the reader returns to.
    "Referrer-Policy": "same-origin",
}


def _reader(request: Request) -> tuple[str, str] | None:
    """(user id, how to name them) for the browser at the consent page."""
    from alphadesk.app import auth
    if not auth.auth_required():
        from alphadesk.app import dashboard
        return dashboard._local_uid(), "this instance's local account"
    claims = auth.current_user(request)
    if not claims or not claims.get("uid"):
        return None
    return claims["uid"], claims.get("email") or "your account"


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · AlphaDesk</title>
<style>
:root{{--bg:#f7f7f5;--panel:#fff;--fg:#16181d;--muted:#5d636f;--border:#d9dbe0;--accent:#e5484d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1013;--panel:#15181d;--fg:#e8eaed;--muted:#9aa0aa;--border:#2a2f37}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:460px;margin:12vh auto;padding:0 16px}}
.card{{background:var(--panel);border:2px solid var(--border);border-radius:8px;padding:22px}}
.brand{{font-weight:800;letter-spacing:.02em;margin-bottom:14px}} .brand b{{color:var(--accent)}}
h1{{font-size:17px;margin:0 0 10px}} p{{margin:8px 0;color:var(--muted)}} strong{{color:var(--fg)}}
ul{{margin:10px 0 16px;padding-left:18px;color:var(--muted)}}
.row{{display:flex;gap:8px;margin-top:18px}}
button,a.btn{{flex:1;height:34px;border:1px solid var(--border);border-radius:5px;background:transparent;color:var(--fg);
font:600 13px system-ui;cursor:pointer;text-align:center;line-height:32px;text-decoration:none}}
button.primary{{background:var(--fg);color:var(--bg);border-color:var(--fg)}}
code{{font-size:12.5px;word-break:break-all}}
</style></head><body><main><div class="card"><div class="brand"><b>■</b> ALPHADESK</div>{body}</div></main></body></html>"""
    return HTMLResponse(doc, status_code=status, headers=_PAGE_HEADERS)


def _secure_cookie() -> bool:
    return os.environ.get("ALPHADESK_COOKIE_SECURE", "").strip() == "1"


@router.get(CONSENT_PATH, include_in_schema=False)
async def consent_page(request: Request):
    blob = request.query_params.get("request", "")
    req = read_request(blob)
    if req is None:
        return _page("Link expired", "<h1>This sign-in link has expired</h1>"
                     "<p>Start connecting again from the app you were adding AlphaDesk to.</p>", 400)
    who = _reader(request)
    if who is None:
        # Sign in first, then come straight back here.
        resp = RedirectResponse("/", status_code=303, headers={"Cache-Control": "no-store"})
        resp.set_cookie(RETURN_COOKIE, f"{CONSENT_PATH}?{urlencode({'request': blob})}",
                        max_age=REQUEST_TTL_S, httponly=True, samesite="lax", secure=_secure_cookie())
        return resp
    client = await provider.get_client(req["client_id"])
    if client is None:
        return _page("Unknown app", "<h1>This app is not registered</h1>", 400)
    name = html.escape(client.client_name or "An agent app")
    dest = html.escape(urlsplit(req["redirect_uri"]).netloc or req["redirect_uri"])
    body = f"""<h1>Allow {name} to use AlphaDesk?</h1>
<p>Signed in as <strong>{html.escape(who[1])}</strong>.</p>
<ul><li>It can call AlphaDesk's read-only tools <strong>as you</strong>, on your own data and vendor keys.</li>
<li>It cannot see your keys, change your account, or place trades.</li>
<li>You can disconnect it any time on the Account page, under Agent access.</li></ul>
<p>After you choose, you go back to <code>{dest}</code>.</p>
<form method="post" action="{CONSENT_PATH}"><input type="hidden" name="request" value="{html.escape(blob)}">
<div class="row"><button type="submit" name="decision" value="deny">Cancel</button>
<button class="primary" type="submit" name="decision" value="allow">Allow</button></div></form>"""
    return _page("Connect an app", body)


@router.post(CONSENT_PATH, include_in_schema=False)
async def consent_decision(request: Request):
    form = await request.form()
    req = read_request(str(form.get("request") or ""))
    if req is None:
        return _page("Link expired", "<h1>This sign-in link has expired</h1>", 400)
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in (base_url(), f"{request.url.scheme}://{request.url.netloc}"):
        return _page("Refused", "<h1>Refused</h1><p>That request did not come from this page.</p>", 403)
    who = _reader(request)
    if who is None:
        return _page("Signed out", "<h1>Sign in first</h1><p>Your session ended; start connecting again.</p>", 401)
    client = await provider.get_client(req["client_id"])
    if client is None:
        return _page("Unknown app", "<h1>This app is not registered</h1>", 400)

    redirect_uri = req["redirect_uri"]
    if form.get("decision") != "allow":
        return RedirectResponse(construct_redirect_uri(
            redirect_uri, error="access_denied", error_description="the reader declined",
            state=req.get("state")), status_code=303, headers={"Cache-Control": "no-store"})

    from alphadesk.ledger import store
    code = secrets.token_urlsafe(32)
    payload = json.dumps({k: req.get(k) for k in
                          ("scopes", "code_challenge", "redirect_uri", "explicit", "resource")})
    await anyio.to_thread.run_sync(store.save_oauth_code, _hash(code), client.client_id, who[0],
                                   payload, int(time.time()) + CODE_TTL_S)
    target = construct_redirect_uri(redirect_uri, code=code, state=req.get("state"))
    return RedirectResponse(target, status_code=303, headers={"Cache-Control": "no-store"})


def return_path(request: Request) -> str | None:
    """Where to send a reader who just signed in, if they left a consent page
    to do it. Only ever our own consent path."""
    value = request.cookies.get(RETURN_COOKIE) or ""
    return value if value.startswith(CONSENT_PATH + "?") else None
