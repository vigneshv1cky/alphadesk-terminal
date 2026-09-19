"""Hosted-mode authentication — the login gate, and nothing else.

COMPULSORY BY DEFAULT (an instance is gated unless the operator sets
`ALPHADESK_AUTH=off`). With any SSO provider configured (Google, GitHub,
or the Microsoft slot), those are the ONLY doors and each doubles as
sign-up: a verified account provisions its own row on first sign-in, and
password logins are refused — the break-glass is unsetting the client
envs, not a side entrance. Without any provider (self-host, dev), the gate
is an operator-managed password allowlist from the CLI
(`python -m alphadesk.main user add`).

Deliberately absent: password reset, email verification flows, roles. Phase
2 (per-user keys) hangs off the user rows this creates — see
docs/hosted-mode.md for the vault design.

Crypto posture, stated plainly:
- Passwords are hashed with the standard library's scrypt (n=2^14, r=8,
  p=1, 32-byte random salt) — a memory-hard KDF from the stdlib, chosen
  over a new dependency; verification is constant-time.
- Sessions are HMAC-SHA256-signed values (user id, email, expiry) under a
  server secret — signed, not encrypted, holding nothing confidential. The
  secret comes from `ALPHADESK_SECRET` or, absent that, a generated file in
  the data directory (0600), so restarts keep sessions without forcing the
  operator to mint one.
- Login attempts are throttled per email: 5 failures locks that account's
  logins for 60 seconds. In-process state — enough for one instance, which
  is the only deployment shape this app has.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from alphadesk import billing
from alphadesk.ledger import store

log = logging.getLogger("alphadesk.auth")

SESSION_COOKIE = "alphadesk_session"
SESSION_TTL_S = 14 * 24 * 3600

_LOCK_AFTER = 5
_LOCK_S = 60.0
_attempts: dict[str, tuple[int, float]] = {}   # email -> (fails, lock_until)


def auth_required() -> bool:
    """COMPULSORY BY DEFAULT (product decision, 2026-09-01): an instance is
    gated unless the operator explicitly sets `ALPHADESK_AUTH=off`. A fresh
    deployment therefore boots to the login screen with zero accounts — add
    one from the CLI, or opt out deliberately. Read per request, not at
    import — tests and operators flip it live."""
    return os.environ.get("ALPHADESK_AUTH", "required").strip().lower() != "off"


# ── SSO providers ──────────────────────────────────────────────────────────
# One table, one flow. Each entry is a standard authorization-code client:
# the identity claim always comes from calling the provider's own API over
# TLS with the token it just issued — the transport authenticates the
# answer, so no local JWT verification anywhere. The EMAIL is the account
# key: the same verified address lands in the same account whichever door
# it walked through.
#
# A provider is enabled by its <ENV>_CLIENT_ID / <ENV>_CLIENT_SECRET pair.
# Google and GitHub clients exist today; Microsoft is a ready slot (create
# an app registration in Azure and set the envs). Apple is deliberately
# absent: it requires a paid Apple Developer enrollment and its token flow
# is not the plain form-POST the others share — add it when an iOS app
# forces the question.

_SSO_PROVIDERS: dict[str, dict] = {
    "google": {
        "label": "Google",
        "env": "GOOGLE",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email",
        "extra_authorize": {"prompt": "select_account"},
    },
    "github": {
        "label": "GitHub",
        "env": "GITHUB",
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "user:email",
        "extra_authorize": {},
    },
    "microsoft": {
        "label": "Microsoft",
        "env": "MICROSOFT",
        "authorize": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scope": "openid email",
        "extra_authorize": {},
    },
}


def _client(provider: str) -> tuple[str, str]:
    env = _SSO_PROVIDERS[provider]["env"]
    return (os.environ.get(f"{env}_CLIENT_ID", "").strip(),
            os.environ.get(f"{env}_CLIENT_SECRET", "").strip())


def provider_enabled(provider: str) -> bool:
    return provider in _SSO_PROVIDERS and all(_client(provider))


def enabled_providers() -> list[str]:
    """In table order, so the login screen's button order is deliberate."""
    return [p for p in _SSO_PROVIDERS if provider_enabled(p)]


def sso_enabled() -> bool:
    return bool(enabled_providers())


def google_enabled() -> bool:
    """Kept for the frontend's cached bundles; new code reads the list."""
    return provider_enabled("google")


# ── passwords ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(32)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        want = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    got = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(got, want)


# ── the server secret ──────────────────────────────────────────────────────

_secret_cache: bytes | None = None


def _secret() -> bytes:
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    env = os.environ.get("ALPHADESK_SECRET", "").strip()
    if env:
        _secret_cache = env.encode()
        return _secret_cache
    from alphadesk.config import DATA_DIR
    path = DATA_DIR / "session_secret"
    try:
        _secret_cache = path.read_bytes()
    except FileNotFoundError:
        _secret_cache = secrets.token_bytes(32)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_secret_cache)
        path.chmod(0o600)
        log.info("generated a session secret at %s", path)
    return _secret_cache


def reset_for_tests() -> None:
    global _secret_cache
    _secret_cache = None
    _attempts.clear()
    _session_states.clear()


# ── sessions ───────────────────────────────────────────────────────────────

def _sign(payload: bytes) -> str:
    mac = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(mac).decode()


def issue_session(user_id: str, email: str, session_version: int = 1) -> str:
    """`sv` is the account row's session_version at issue time. A cookie
    whose stamp trails the row is dead — bumping the row is how one account's
    every outstanding session dies at once (sign-out-everywhere, revocation),
    without the server keeping any per-session state."""
    payload = json.dumps({"uid": user_id, "email": email,
                          "sv": int(session_version),
                          "exp": int(time.time()) + SESSION_TTL_S}).encode()
    return _sign(payload)


def read_session(token: str | None) -> dict | None:
    """The session's claims, or None for anything invalid — a bad signature,
    a tampered payload and an expired session all read the same: not
    signed in."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, mac_b64 = token.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64)
        mac = base64.urlsafe_b64decode(mac_b64)
    except (ValueError, TypeError):
        return None
    want = hmac.new(_secret(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, want):
        return None
    try:
        claims = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(claims, dict) or int(claims.get("exp", 0)) < time.time():
        return None
    return claims


# (session_version, disabled) per user, cached briefly: the per-request
# re-check below must not cost a database read per request. 30 seconds is
# the honest revocation latency ACROSS processes; within this process a
# bump clears the entry and takes effect immediately.
_SESSION_STATE_TTL_S = 30.0
_session_states: dict[str, tuple[float, dict | None]] = {}


def _session_state(user_id: str) -> dict | None:
    now = time.monotonic()
    hit = _session_states.get(user_id)
    if hit and now - hit[0] < _SESSION_STATE_TTL_S:
        return hit[1]
    state = store.user_session_state(user_id)
    _session_states[user_id] = (now, state)
    if len(_session_states) > 10_000:               # bound a long process
        _session_states.clear()
    return state


def invalidate_sessions(user_id: str) -> bool:
    """Bump the account's session_version: every outstanding cookie for it —
    this device's included — stops verifying. The reader's button and the
    operator's revoke both land here."""
    ok = store.bump_session_version(user_id)
    _session_states.pop(user_id, None)
    return ok


def current_user(request: Request) -> dict | None:
    """The signed-in reader, or None. Beyond the cookie's signature and
    expiry, the claims are re-validated against the ACCOUNT ROW (cached
    ~30s): a stamp behind the row's session_version, a disabled flag, or a
    deleted account all read as signed out. Cookies from before the stamp
    existed carry an implicit version 1, so a deploy alone signs nobody
    out — rows start at 1 too."""
    claims = read_session(request.cookies.get(SESSION_COOKIE))
    if claims is None or not claims.get("uid"):
        return claims
    state = _session_state(claims["uid"])
    if state is None or state.get("disabled")             or int(claims.get("sv", 1)) != int(state.get("session_version") or 1):
        return None
    return claims


# ── routes ─────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    email: str
    password: str


@router.get("/me")
def me(request: Request, response: Response):
    """Who am I, and does this instance even ask? The SPA boots on this:
    open instances render straight away, gated ones show the login screen.
    Deliberately reachable without a session.

    `next` (2026-09-17): a signed-in reader who left an agent app's consent
    page to sign in is sent back to it. The SSO callback redirects there
    itself; a PASSWORD sign-in happens in the SPA, which re-checks this
    endpoint afterwards, so the return rides here instead. It also rescues a
    password reader whose SameSite=Strict session cookie was not sent on the
    cross-site arrival from the app: the consent page saw them as signed out,
    but this same-site request sees them. Given once, then cleared, so a
    session that really is gone cannot loop."""
    from alphadesk.app.agent_oauth import RETURN_COOKIE, return_path
    claims = current_user(request)
    back = return_path(request) if claims else None
    if back:
        response.delete_cookie(RETURN_COOKIE)
    return {
        **({"next": back} if back else {}),
        "auth_required": auth_required(),
        # The list drives the login screen's buttons; the bare google flag
        # survives for cached bundles of the older frontend.
        "providers": [{"id": p, "label": _SSO_PROVIDERS[p]["label"]}
                      for p in enabled_providers()],
        "google": google_enabled(),
        # The methods THIS account has signed in with, latest first — recorded
        # from 2026-09-18, so an older sign-in is not in it (2026-09-18).
        "user": {"email": claims["email"],
                 "sign_ins": store.list_sign_ins(claims["uid"]) if claims.get("uid") else [],
                 # Trial or subscription, and whether the gate applies
                 # (alphadesk/billing.py); `owner` shows the admin page.
                 "access": _access(claims),
                 "owner": billing.is_owner(claims.get("email"))}
                if claims else None,
    }


def _access(claims: dict) -> dict | None:
    return billing.access(store.user_access_row(claims["uid"])) if claims.get("uid") else None


# ── Google sign-in (the default method) ────────────────────────────────────
# The standard authorization-code flow, shared by every provider in the
# table. State rides a short-lived signed cookie against CSRF.

_STATE_COOKIE = "alphadesk_oauth_state"


def _redirect_uri(request: Request, provider: str) -> str:
    base = os.environ.get("ALPHADESK_BASE_URL", "").strip().rstrip("/") \
        or f"{request.url.scheme}://{request.url.netloc}"
    return base + f"/api/auth/{provider}/callback"


def _sso_exchange(provider: str, code: str, redirect_uri: str) -> dict:
    """code -> tokens, at the provider's token endpoint. Split out for
    tests. The JSON Accept header matters: GitHub answers form-encoded
    without it; the others ignore it."""
    import urllib.parse
    import urllib.request
    cid, csecret = _client(provider)
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": cid,
        "client_secret": csecret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(_SSO_PROVIDERS[provider]["token"], data=body,
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _sso_email(provider: str, access_token: str) -> tuple[str, bool]:
    """(email, verified) from the provider's own API — the one identity
    fact this app takes, however many the provider offers."""
    import urllib.request

    def _get(url: str, extra: dict[str, str] | None = None) -> Any:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {access_token}", **(extra or {})})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    if provider == "github":
        # GitHub's profile email can be private/absent; the emails endpoint
        # is the truth, and only the PRIMARY VERIFIED address counts.
        rows = _get("https://api.github.com/user/emails",
                    {"Accept": "application/vnd.github+json"})
        for r in rows if isinstance(rows, list) else []:
            if r.get("primary"):
                return str(r.get("email", "")).lower().strip(), bool(r.get("verified"))
        return "", False
    if provider == "microsoft":
        info = _get("https://graph.microsoft.com/oidc/userinfo")
        email = str(info.get("email", "")).lower().strip()
        # Microsoft's userinfo only carries an email claim it considers
        # usable; there is no separate verified flag to read.
        return email, bool(email)
    info = _get("https://openidconnect.googleapis.com/v1/userinfo")
    return (str(info.get("email", "")).lower().strip(),
            bool(info.get("email_verified", False)))


@router.get("/{provider}/start")
def sso_start(provider: str, request: Request):
    import urllib.parse
    if not provider_enabled(provider):
        raise HTTPException(404, f"{provider} sign-in is not configured")
    cid, _ = _client(provider)
    state = secrets.token_urlsafe(24)
    params = urllib.parse.urlencode({
        "client_id": cid,
        "redirect_uri": _redirect_uri(request, provider),
        "response_type": "code",
        "scope": _SSO_PROVIDERS[provider]["scope"],
        "state": state,
        **_SSO_PROVIDERS[provider]["extra_authorize"],
    })
    response = Response(status_code=307,
                        headers={"Location": _SSO_PROVIDERS[provider]["authorize"] + "?" + params})
    response.set_cookie(_STATE_COOKIE, _sign(state.encode()), max_age=600,
                        httponly=True, samesite="lax",
                        secure=os.environ.get("ALPHADESK_COOKIE_SECURE", "").strip() == "1")
    return response


@router.get("/{provider}/callback")
def sso_callback(provider: str, request: Request, code: str = "", state: str = ""):
    """Errors land back on the login screen with a short code in the URL —
    the login page prints the reason; details stay in the server log."""
    def bounce(err: str) -> Response:
        return Response(status_code=307, headers={"Location": f"/?auth_error={err}"})

    if not provider_enabled(provider):
        return bounce("not-configured")
    signed = read_state = None
    try:
        signed = request.cookies.get(_STATE_COOKIE)
        payload_b64, mac_b64 = (signed or "").split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64)
        if hmac.compare_digest(base64.urlsafe_b64decode(mac_b64),
                               hmac.new(_secret(), payload, hashlib.sha256).digest()):
            read_state = payload.decode()
    except (ValueError, TypeError):
        read_state = None
    if not code or not state or read_state != state:
        return bounce("state-mismatch")

    try:
        tokens = _sso_exchange(provider, code, _redirect_uri(request, provider))
        email, verified = _sso_email(provider, tokens["access_token"])
    except Exception as exc:
        log.warning("%s sign-in failed: %s", provider, exc)
        return bounce("sso-failed")

    if not email or not verified:
        return bounce("no-verified-email")
    user = store.get_user_by_email(email)
    if user and user.get("disabled"):
        # Disabling a row is the operator's ban switch, and it survives the
        # open-signup policy.
        log.info("%s sign-in refused for %s: account disabled", provider, email)
        return bounce("account-disabled")
    if not user:
        # SSO IS sign-up (policy, 2026-09-01): a verified account from any
        # configured provider provisions itself on first sign-in — no
        # allowlist step. Consent-screen testing modes still limit who gets
        # this far; publishing the apps is what truly opens the door.
        store.create_user(uuid.uuid4().hex, email, "sso-only")
        user = store.get_user_by_email(email)
        log.info("%s sign-in provisioned a new account for %s", provider, email)
    if not user:                                     # a write race lost; retry the flow
        return bounce("sso-failed")
    # Which methods this account really uses (2026-09-18) — the Security
    # panel had shown every offered method as active for everyone.
    store.record_sign_in(user["user_id"], provider)

    # A reader who left an agent app's consent page to sign in goes back to it.
    from alphadesk.app.agent_oauth import RETURN_COOKIE, return_path
    back = return_path(request)
    # Into the app, not "/": the root is the landing page (2026-09-18).
    response = Response(status_code=307, headers={"Location": back or "/markets"})
    response.delete_cookie(_STATE_COOKIE)
    if back:
        response.delete_cookie(RETURN_COOKIE)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user["user_id"], user["email"], user.get("session_version") or 1),
        max_age=SESSION_TTL_S, httponly=True, samesite="lax",
        secure=os.environ.get("ALPHADESK_COOKIE_SECURE", "").strip() == "1",
    )
    return response


@router.post("/login")
def login(body: LoginBody, response: Response):
    if not auth_required():
        raise HTTPException(400, "this instance has no login — it is open")
    if sso_enabled():
        # SSO-only by policy (2026-09-01): with any identity provider
        # configured, those are the doors. The operator's break-glass is
        # config, not a side entrance — unset the client envs and password
        # login returns.
        names = " or ".join(_SSO_PROVIDERS[p]["label"] for p in enabled_providers())
        raise HTTPException(400, f"this instance signs in with {names}")
    email = body.email.lower().strip()

    fails, lock_until = _attempts.get(email, (0, 0.0))
    if time.time() < lock_until:
        raise HTTPException(429, "too many attempts — wait a minute and try again")

    user = store.get_user_by_email(email)
    # The same failure for a wrong password and an unknown email, on purpose:
    # a login form must not confirm which addresses have accounts.
    if not user or user.get("disabled") or not verify_password(body.password, user["password_hash"]):
        fails += 1
        _attempts[email] = (fails, time.time() + _LOCK_S if fails >= _LOCK_AFTER else 0.0)
        raise HTTPException(401, "wrong email or password")

    _attempts.pop(email, None)
    store.record_sign_in(user["user_id"], "password")
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user["user_id"], user["email"], user.get("session_version") or 1),
        max_age=SESSION_TTL_S, httponly=True, samesite="strict",
        secure=os.environ.get("ALPHADESK_COOKIE_SECURE", "").strip() == "1",
    )
    return {"user": {"email": user["email"]}}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response):
    """Sign out EVERYWHERE: bump the account's session_version so every
    cookie issued before this moment — other devices' included — stops
    verifying. Other processes converge within the state cache's TTL."""
    claims = current_user(request)
    if claims is None or not claims.get("uid"):
        raise HTTPException(401, "sign in first")
    invalidate_sessions(claims["uid"])
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


# ── the gate ───────────────────────────────────────────────────────────────

def is_gated(path: str) -> bool:
    """Only the DATA is gated. Static files and SPA routes stay open — the
    application shell is public code, and a deep link must be able to load
    the page that shows the login screen. Everything under /api except this
    module's own routes and the liveness probe requires a session."""
    # The agent's tool server carries its own credential — an access token
    # the reader issued (app/agent_access.py) — because the reader's own
    # agent calls it from outside, with no browser session to present.
    # The payment processor's webhook likewise: the processor calls it with
    # no session, and the route verifies the processor's signature instead —
    # gated, every Stripe event was refused with 401 (2026-09-19).
    return path.startswith("/api") and not path.startswith("/api/auth") \
        and not path.startswith("/api/agent/tools") \
        and not (path == "/api/billing/webhook" or path.startswith("/api/billing/webhook/")) \
        and path != "/api/healthz" and path != "/healthz"


def make_user_cli() -> None:
    """`python -m alphadesk.main user <add|list|passwd|remove> [email]` —
    the allowlist, operated from the terminal on the box. Passwords are
    prompted, never taken as arguments: argv lands in shell history."""
    import argparse
    import getpass
    import sys

    parser = argparse.ArgumentParser(prog="alphadesk user")
    sub = parser.add_subparsers(dest="op", required=True)
    for op in ("add", "allow", "passwd", "remove", "revoke"):
        p = sub.add_parser(op)
        p.add_argument("email")
    sub.add_parser("list")
    args = parser.parse_args(sys.argv[2:])

    store.init()
    if args.op == "allow":
        # Google-only account: on the allowlist with no password at all. The
        # stored sentinel never verifies, so the password form cannot be a
        # side door into an account that was invited for Google sign-in.
        if store.get_user_by_email(args.email):
            print("that email already has an account")
            sys.exit(1)
        store.create_user(uuid.uuid4().hex, args.email, "sso-only")
        print(f"allowed {args.email} (Google sign-in only)")
        return
    if args.op == "list":
        for u in store.list_users():
            flag = "  (disabled)" if u["disabled"] else ""
            print(f"{u['email']:40} {u['created_at'][:19]}{flag}")
        return
    if args.op == "remove":
        print("removed" if store.remove_user(args.email) else "no such user")
        return
    if args.op == "revoke":
        u = store.get_user_by_email(args.email)
        if not u:
            print("no such user")
            sys.exit(1)
        invalidate_sessions(u["user_id"])
        print(f"revoked every session for {args.email}"
              " (other server processes converge within ~30s)")
        return
    pw = getpass.getpass("password: ")
    if len(pw) < 10:
        print("refusing: use at least 10 characters")
        sys.exit(1)
    if getpass.getpass("again: ") != pw:
        print("passwords do not match")
        sys.exit(1)
    if args.op == "add":
        if store.get_user_by_email(args.email):
            print("that email already has an account")
            sys.exit(1)
        store.create_user(uuid.uuid4().hex, args.email, hash_password(pw))
        print(f"added {args.email}")
    else:
        print("updated" if store.set_user_password(args.email, hash_password(pw)) else "no such user")
