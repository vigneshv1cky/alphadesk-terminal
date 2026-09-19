"""OAuth sign-in for agent apps (2026-09-17).

Claude.ai and ChatGPT connect by URL and then sign the reader in over OAuth.
These tests walk the whole flow the way a connector does — discovery,
registration, authorize, consent, code exchange, tool call, refresh, revoke —
and then hold each place it could be abused: a replayed code, a wrong PKCE
verifier, a replayed refresh token, an altered consent request, a consent
post from another site, a reader who is signed out, and an open redirect
through the sign-in return.
"""

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest

MASTER = base64.b64encode(b"k" * 32).decode()
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
MCP_HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream",
               "host": "127.0.0.1:8000"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", MASTER)
    monkeypatch.setenv("ALPHADESK_AUTH", "off")


@pytest.fixture()
def client(store, monkeypatch):
    from fastapi.testclient import TestClient

    from alphadesk.app import agent_access, agent_oauth, dashboard
    store.ensure_local_user()
    monkeypatch.setattr(agent_access, "limiter", agent_access.RateLimit())
    monkeypatch.setattr(agent_oauth, "registration_limiter", agent_access.RateLimit(per_min=10))
    with TestClient(dashboard.app, follow_redirects=False) as c:
        c.uid = dashboard._local_uid()
        yield c


def _mcp(c, token, method="tools/list", params=None):
    headers = dict(MCP_HEADERS)
    if token:
        headers["authorization"] = f"Bearer {token}"
    return c.post("/api/agent/tools/mcp", headers=headers,
                  content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}))


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register(c, **extra):
    body = {"redirect_uris": [REDIRECT], "client_name": "Claude", "token_endpoint_auth_method": "none", **extra}
    resp = c.post("/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _consent_blob(c, client_id, challenge, state="st-1"):
    resp = c.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "scope": "alphadesk", "resource": "http://localhost:8000/api/agent/tools/mcp"})
    assert resp.status_code == 302, resp.text
    loc = urlsplit(resp.headers["location"])
    assert loc.path == "/oauth/consent"
    return parse_qs(loc.query)["request"][0]


def _approve(c, blob, decision="allow", origin="http://testserver"):
    return c.post("/oauth/consent", data={"request": blob, "decision": decision},
                  headers={"origin": origin} if origin else {})


def _connect(c):
    """The whole connector flow; returns (client record, token response)."""
    reg = _register(c)
    verifier, challenge = _pkce()
    blob = _consent_blob(c, reg["client_id"], challenge)
    page = c.get("/oauth/consent", params={"request": blob})
    assert page.status_code == 200 and "Allow Claude to use AlphaDesk?" in page.text
    back = _approve(c, blob)
    assert back.status_code == 303
    q = parse_qs(urlsplit(back.headers["location"]).query)
    assert back.headers["location"].startswith(REDIRECT) and q["state"] == ["st-1"]
    tok = c.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                 "redirect_uri": REDIRECT, "client_id": reg["client_id"],
                                 "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    return reg, tok.json(), q["code"][0], verifier


# ── discovery ─────────────────────────────────────────────────────────────


def test_an_unauthenticated_call_points_the_connector_at_the_sign_in(client):
    resp = _mcp(client, None)
    assert resp.status_code == 401
    header = resp.headers["www-authenticate"]
    assert 'resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/api/agent/tools/mcp"' in header

    meta = client.get("/.well-known/oauth-protected-resource/api/agent/tools/mcp").json()
    assert meta["resource"] == "http://localhost:8000/api/agent/tools/mcp"
    assert meta["authorization_servers"] == ["http://localhost:8000/"]
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200

    auth = client.get("/.well-known/oauth-authorization-server").json()
    assert auth["authorization_endpoint"].endswith("/authorize")
    assert auth["token_endpoint"].endswith("/token")
    assert auth["registration_endpoint"].endswith("/register")
    assert auth["code_challenge_methods_supported"] == ["S256"]
    assert "none" in auth["token_endpoint_auth_methods_supported"]


# ── the whole flow ────────────────────────────────────────────────────────


def test_a_connector_signs_in_and_calls_tools_as_the_reader(client, monkeypatch, store):
    from alphadesk.identity import request_user
    seen = []

    class FakeRouter:
        def market_tape(self):
            seen.append(request_user())
            return []

    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: FakeRouter())
    _, tok, _, _ = _connect(client)
    assert tok["access_token"].startswith("ado_") and tok["refresh_token"].startswith("adr_")
    assert tok["token_type"].lower() == "bearer" and tok["expires_in"] == 3600

    resp = _mcp(client, tok["access_token"], "tools/call", {"name": "market_tape", "arguments": {}})
    assert resp.status_code == 200, resp.text[:300]
    assert seen == [client.uid]

    conns = client.get("/api/agent/connections").json()["connections"]
    assert [c["client_name"] for c in conns] == ["Claude"]
    # Nothing secret is stored in the clear.
    with store._connect() as conn:
        dump = json.dumps([dict(r) for t in ("oauth_grants", "oauth_codes", "oauth_clients")
                           for r in conn.execute(f"SELECT * FROM {t}")])
    assert tok["access_token"] not in dump and tok["refresh_token"] not in dump


def test_a_code_works_once(client):
    reg, _, code, verifier = _connect(client)
    again = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                        "redirect_uri": REDIRECT, "client_id": reg["client_id"],
                                        "code_verifier": verifier})
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_a_wrong_pkce_verifier_gets_nothing(client):
    reg = _register(client)
    _, challenge = _pkce()
    blob = _consent_blob(client, reg["client_id"], challenge)
    code = parse_qs(urlsplit(_approve(client, blob).headers["location"]).query)["code"][0]
    wrong, _ = _pkce()
    resp = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                       "redirect_uri": REDIRECT, "client_id": reg["client_id"],
                                       "code_verifier": wrong})
    assert resp.status_code == 400 and resp.json()["error"] == "invalid_grant"


def test_refresh_rotates_and_a_replayed_refresh_token_is_refused(client):
    reg, tok, _, _ = _connect(client)
    fresh = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                        "client_id": reg["client_id"]})
    assert fresh.status_code == 200, fresh.text
    new = fresh.json()
    assert new["access_token"] != tok["access_token"] and new["refresh_token"] != tok["refresh_token"]
    assert _mcp(client, new["access_token"]).status_code == 200
    assert _mcp(client, tok["access_token"]).status_code == 401
    replay = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                         "client_id": reg["client_id"]})
    assert replay.status_code == 400


def test_disconnecting_on_the_account_page_stops_the_app(client):
    _, tok, _, _ = _connect(client)
    grant = client.get("/api/agent/connections").json()["connections"][0]
    assert client.delete(f"/api/agent/connections/{grant['grant_id']}").status_code == 200
    assert _mcp(client, tok["access_token"]).status_code == 401
    assert client.get("/api/agent/connections").json()["connections"] == []


def test_allowing_an_app_again_replaces_the_grant_it_had(client):
    """One live grant per registered app per reader (2026-09-17). A grant was
    created on every consent and nothing collapsed them, so re-allowing an app
    already connected left its old grant live beside the new one — four
    approvals of the Claude connector in one afternoon left four rows, each
    holding a 90-day refresh token."""
    reg, first, _, _ = _connect(client)
    verifier, challenge = _pkce()
    blob = _consent_blob(client, reg["client_id"], challenge, state="st-2")
    back = _approve(client, blob)
    q = parse_qs(urlsplit(back.headers["location"]).query)
    second = client.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                         "redirect_uri": REDIRECT, "client_id": reg["client_id"],
                                         "code_verifier": verifier}).json()

    rows = client.get("/api/agent/connections").json()["connections"]
    assert len(rows) == 1                                  # the app, not the approvals
    assert _mcp(client, second["access_token"]).status_code == 200
    assert _mcp(client, first["access_token"]).status_code == 401   # the leftover is dead


def test_a_second_app_is_not_superseded_by_the_first(client):
    """The collapse is per registered app: another app's grant is untouched,
    and so is an app that registers afresh (Claude.ai does on every add) —
    to the server that is a different client, which the Account page groups
    by name instead."""
    _, first, _, _ = _connect(client)
    _, second, _, _ = _connect(client)                     # a fresh registration
    rows = client.get("/api/agent/connections").json()["connections"]
    assert len(rows) == 2
    assert _mcp(client, first["access_token"]).status_code == 200
    assert _mcp(client, second["access_token"]).status_code == 200


def test_the_app_can_revoke_its_own_token(client):
    reg, tok, _, _ = _connect(client)
    # The library's revocation form declares client_secret as a required
    # field even for a public client; an empty one is what such a client sends.
    resp = client.post("/revoke", data={"token": tok["access_token"], "client_id": reg["client_id"],
                                        "client_secret": ""})
    assert resp.status_code == 200, resp.text
    assert _mcp(client, tok["access_token"]).status_code == 401


def test_an_expired_access_token_is_refused(client, store):
    _, tok, _, _ = _connect(client)
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE oauth_grants SET access_expires=1")
    assert _mcp(client, tok["access_token"]).status_code == 401


# ── consent ───────────────────────────────────────────────────────────────


def test_declining_sends_the_app_access_denied(client):
    reg = _register(client)
    _, challenge = _pkce()
    blob = _consent_blob(client, reg["client_id"], challenge)
    back = _approve(client, blob, decision="deny")
    q = parse_qs(urlsplit(back.headers["location"]).query)
    assert q["error"] == ["access_denied"] and "code" not in q


def test_an_altered_consent_request_is_refused(client):
    reg = _register(client)
    _, challenge = _pkce()
    blob = _consent_blob(client, reg["client_id"], challenge)
    head, tail = blob.split(".")
    body = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
    body["redirect_uri"] = "https://evil.example.net/cb"
    forged = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    assert _approve(client, f"{forged}.{tail}").status_code == 400
    assert client.get("/oauth/consent", params={"request": f"{forged}.{tail}"}).status_code == 400


def test_a_consent_post_from_another_site_is_refused(client):
    reg = _register(client)
    _, challenge = _pkce()
    blob = _consent_blob(client, reg["client_id"], challenge)
    assert _approve(client, blob, origin="https://evil.example.net").status_code == 403


def test_the_consent_page_cannot_be_framed(client):
    reg = _register(client)
    _, challenge = _pkce()
    page = client.get("/oauth/consent", params={"request": _consent_blob(client, reg["client_id"], challenge)})
    assert page.headers["x-frame-options"] == "DENY"
    # no-referrer would make the browser post `Origin: null`, which the
    # Origin check refuses — the reader's own Allow would never land.
    assert page.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_the_app_name_cannot_inject_markup(client):
    reg = _register(client, client_name='<script>alert(1)</script>')
    _, challenge = _pkce()
    page = client.get("/oauth/consent", params={"request": _consent_blob(client, reg["client_id"], challenge)})
    assert "<script>alert(1)</script>" not in page.text and "&lt;script&gt;" in page.text


def test_a_signed_out_reader_is_sent_to_sign_in_and_brought_back(client, monkeypatch):
    reg = _register(client)
    _, challenge = _pkce()
    blob = _consent_blob(client, reg["client_id"], challenge)
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    page = client.get("/oauth/consent", params={"request": blob})
    assert page.status_code == 303 and page.headers["location"] == "/"
    assert "alphadesk_return=" in page.headers["set-cookie"]
    # A consent post with no session never issues a code.
    assert _approve(client, blob).status_code == 401


def test_the_sign_in_return_only_ever_goes_to_the_consent_page():
    from starlette.requests import Request

    from alphadesk.app.agent_oauth import return_path

    def req(cookie):
        return Request({"type": "http", "headers": [(b"cookie", f"alphadesk_return={cookie}".encode())]})

    assert return_path(req("/oauth/consent?request=abc")) == "/oauth/consent?request=abc"
    for bad in ("https://evil.example.net/", "//evil.example.net", "/oauth/consentx", "/account"):
        assert return_path(req(bad)) is None


def test_registration_is_rate_limited(client):
    codes = [client.post("/register", json={"redirect_uris": [REDIRECT], "client_name": f"c{i}"}).status_code
             for i in range(12)]
    assert codes[:10] == [201] * 10 and 429 in codes[10:]


def test_stale_codes_and_never_allowed_apps_are_swept(client, store):
    import time
    reg_used, _, _, _ = _connect(client)          # has a grant: kept
    reg_idle = _register(client)                  # never allowed in
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE oauth_clients SET created_at='2000-01-01T00:00:00+00:00'")
        conn.execute("UPDATE oauth_codes SET expires_at=1")
    assert store.prune_oauth(int(time.time())) >= 2
    with store._connect() as conn:
        left = {r["client_id"] for r in conn.execute("SELECT client_id FROM oauth_clients")}
        codes = conn.execute("SELECT COUNT(*) AS n FROM oauth_codes").fetchone()["n"]
    assert reg_used["client_id"] in left and reg_idle["client_id"] not in left
    assert codes == 0


# ── the way back after a password sign-in ─────────────────────────────────


def _password_reader(client, store, monkeypatch):
    """A gated instance with a password account, signed in on `client`."""
    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.setattr(auth, "sso_enabled", lambda: False)
    store.create_user("pw-reader", "reader@example.com", auth.hash_password("correct horse battery"))
    resp = client.post("/api/auth/login", json={"email": "reader@example.com", "password": "correct horse battery"})
    assert resp.status_code == 200, resp.text


def test_a_password_sign_in_returns_to_the_consent_page_once(client, store, monkeypatch):
    reg = _register(client)
    _, challenge = _pkce()
    blob = _consent_blob(client, reg["client_id"], challenge)
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    left = client.get("/oauth/consent", params={"request": blob})
    assert left.status_code == 303 and "alphadesk_return=" in left.headers["set-cookie"]
    # Signed out, /me names no destination — the login screen shows.
    assert client.get("/api/auth/me").json().get("next") is None

    _password_reader(client, store, monkeypatch)
    me = client.get("/api/auth/me")
    assert me.json()["next"].startswith("/oauth/consent?request=")
    # Given once: the cookie is cleared, so the next check names nothing.
    assert client.get("/api/auth/me").json().get("next") is None
    # And the reader, now signed in, sees the consent page itself.
    page = client.get(me.json()["next"])
    assert page.status_code == 200 and "Allow Claude to use AlphaDesk?" in page.text


def test_the_consent_page_says_what_the_app_actually_gets(client):
    """AlphaDesk holds no model key since 2026-09-17 (#190); the page said
    "your own data and model keys" for a day after."""
    reg = _register(client)
    _, challenge = _pkce()
    page = client.get("/oauth/consent", params={"request": _consent_blob(client, reg["client_id"], challenge)})
    assert "vendor keys" in page.text and "model key" not in page.text
    assert "read-only tools" in page.text
