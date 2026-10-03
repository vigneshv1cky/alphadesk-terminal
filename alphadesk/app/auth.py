"""Authentication — the login gate, and nothing else.

COMPULSORY BY DEFAULT (an instance is gated unless the operator sets
`ALPHADESK_AUTH=off`). The only door is an email and password the operator
makes: set in the settings (ALPHADESK_LOGIN_EMAIL with a password hash), or
added from the command line (`python -m alphadesk.main user add`). There is no
sign-up and no third-party sign-in: Google, GitHub and Microsoft sign-in were
removed on 2026-10-03.

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

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

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


# ── the allow-list (2026-10-03) ─────────────────────────────────────────────
# ALPHADESK_ALLOWED_EMAILS limits the accounts that may be used to the people
# the operator names: a comma- or space-separated list, compared without case.
# Unset or empty, nothing changes. It applies wherever accounts gate — to
# sign-ins, to sessions already open, and (in the agent door) to tokens made by
# an account no longer on the list — and not to an instance with sign-in off,
# which has one account and no addresses.

def allowed_emails() -> set[str] | None:
    # ONE USER (2026-10-03): where a login is set it is the only address that
    # may be used, whatever else the list says.
    if login_email():
        return {login_email()}
    raw = os.environ.get("ALPHADESK_ALLOWED_EMAILS", "")
    names = {e.strip().lower() for e in raw.replace(",", " ").split() if e.strip()}
    return names or None


def email_allowed(email: str | None) -> bool:
    names = allowed_emails()
    if names is None or not auth_required():
        return True
    return (email or "").strip().lower() in names


def uid_allowed(user_id: str) -> bool:
    """For credentials that carry only an account id (agent tokens)."""
    if allowed_emails() is None or not auth_required():
        return True
    return email_allowed(store.account_email(user_id))


# ── the access token (2026-10-03) ──────────────────────────────────────────
# One person's own server that is reachable beyond their machine. With sign-in
# off it acts as a single local account and would answer anyone who finds it,
# so ALPHADESK_ACCESS_TOKEN puts one shared secret in front of it: the browser
# types it once (a normal session cookie follows) and the agent door is
# unchanged — it already carries its own tokens, made on the Agent access page
# behind this gate.

ACCESS_TOKEN_MIN = 16


def access_token() -> str:
    return os.environ.get("ALPHADESK_ACCESS_TOKEN", "").strip()


def token_gate() -> bool:
    """Whether the shared access token is in force: set, on an instance that
    has no accounts of its own. Where sign-in is required the accounts are the
    gate and the token is ignored."""
    return not auth_required() and bool(access_token())


def gate_active() -> bool:
    """Whether a data route needs a session: accounts, or the access token."""
    return auth_required() or token_gate()


def access_token_problem() -> str | None:
    """Why the configured token cannot be used, or None. A short token is
    refused at start rather than quietly guarding nothing."""
    tok = access_token()
    if tok and len(tok) < ACCESS_TOKEN_MIN:
        return (f"ALPHADESK_ACCESS_TOKEN must be at least {ACCESS_TOKEN_MIN} characters "
                "(generate one with: python -c \"import secrets; print(secrets.token_urlsafe(24))\")")
    return None


# ── a login set in the settings (2026-10-03) ────────────────────────────────
# ALPHADESK_LOGIN_EMAIL with ALPHADESK_LOGIN_PASSWORD_HASH (or, simpler but
# readable to anyone who can read the settings, ALPHADESK_LOGIN_PASSWORD): the
# operator chooses the sign-in. At
# start the account is made, or — if that email already has one — given the
# password, keeping its data (an account an earlier Google or GitHub sign-in
# made has no password until this gives it one).
# Make a hash with:  python -m alphadesk.main hash-password

LOGIN_PASSWORD_MIN = 12


def login_email() -> str:
    return os.environ.get("ALPHADESK_LOGIN_EMAIL", "").strip().lower()


def login_problem() -> str | None:
    """Why the configured login cannot be used, or None."""
    email = login_email()
    if not email:
        if auth_required():
            return ("sign-in is on but no login is set: set ALPHADESK_LOGIN_EMAIL with ALPHADESK_LOGIN_PASSWORD_HASH "
                    "(make one with `python -m alphadesk.main hash-password`), or set ALPHADESK_AUTH=off "
                    "for a server only you can reach")
        return None
    if "@" not in email or " " in email:
        return "ALPHADESK_LOGIN_EMAIL must be an email address (the account is keyed by it)"
    hashed = os.environ.get("ALPHADESK_LOGIN_PASSWORD_HASH", "").strip()
    plain = os.environ.get("ALPHADESK_LOGIN_PASSWORD", "")
    if hashed:
        if not hashed.startswith("scrypt$"):
            return "ALPHADESK_LOGIN_PASSWORD_HASH is not a hash made by `hash-password`"
        return None
    if not plain:
        return "ALPHADESK_LOGIN_EMAIL needs ALPHADESK_LOGIN_PASSWORD_HASH (or ALPHADESK_LOGIN_PASSWORD)"
    if len(plain) < LOGIN_PASSWORD_MIN:
        return f"ALPHADESK_LOGIN_PASSWORD must be at least {LOGIN_PASSWORD_MIN} characters"
    return None


def apply_login_from_settings() -> str | None:
    """Make the settings' account match them. Returns what was done
    ("created", "password set", "unchanged") or None when no login is set.
    Idempotent: a restart changes nothing once they agree."""
    email = login_email()
    if not email:
        return None
    hashed = os.environ.get("ALPHADESK_LOGIN_PASSWORD_HASH", "").strip()
    plain = os.environ.get("ALPHADESK_LOGIN_PASSWORD", "")
    row = store.get_user_by_email(email)
    if hashed:
        want_hash = hashed
        agrees = row is not None and row["password_hash"] == hashed
    else:
        want_hash = None
        agrees = row is not None and verify_password(plain, row["password_hash"])
    if row is None:
        store.create_user(uuid.uuid4().hex, email, want_hash or hash_password(plain))
        return "created"
    if agrees:
        return "unchanged"
    store.set_user_password(email, want_hash or hash_password(plain))
    return "password set"


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


def session_age_s(claims: dict) -> float:
    """Seconds since this session was issued. A session records only its
    expiry, and every one is issued with the same lifetime, so the issue time
    is the expiry less that lifetime — the same for a password or a single
    sign-on session. What a deliberate, sensitive action reads to ask the
    reader to sign in again first."""
    return time.time() - (int(claims.get("exp", 0)) - SESSION_TTL_S)


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
    if not email_allowed(claims.get("email")):
        return None                                   # taken off the list: signed out
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
    page to sign in is sent back to it. Sign-in happens in the SPA, which
    re-checks this endpoint afterwards, so the return rides here. It also rescues a
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
        "auth_required": gate_active(),
        "token_login": token_gate(),
        # The methods THIS account has signed in with, latest first — recorded
        # from 2026-09-18, so an older sign-in is not in it (2026-09-18).
        "user": {"email": claims["email"],
                 "sign_ins": store.list_sign_ins(claims["uid"]) if claims.get("uid") else [],
                 }
                if claims else None,
    }


@router.post("/login")
def login(body: LoginBody, response: Response):
    if not auth_required():
        raise HTTPException(400, "this instance has no login — it is open")
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
    if not email_allowed(user["email"]):
        raise HTTPException(403, "this account is not allowed on this server")
    store.record_sign_in(user["user_id"], "password")
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user["user_id"], user["email"], user.get("session_version") or 1),
        max_age=SESSION_TTL_S, httponly=True, samesite="strict",
        secure=os.environ.get("ALPHADESK_COOKIE_SECURE", "").strip() == "1",
    )
    return {"user": {"email": user["email"]}}


class TokenBody(BaseModel):
    token: str


@router.post("/token-login")
def token_login(body: TokenBody, response: Response):
    """Trade the instance's access token for a session cookie, as the one
    local account. Compared in constant time and rate limited like a password
    (the same five-misses-a-minute lock, shared across callers because there
    is only one secret to guess)."""
    if not token_gate():
        raise HTTPException(400, "this instance has no access token")
    fails, lock_until = _attempts.get("\x00token", (0, 0.0))
    if time.time() < lock_until:
        raise HTTPException(429, "too many attempts — wait a minute and try again")
    if not hmac.compare_digest(body.token.strip().encode(), access_token().encode()):
        fails += 1
        _attempts["\x00token"] = (fails, time.time() + _LOCK_S if fails >= _LOCK_AFTER else 0.0)
        raise HTTPException(401, "that is not this instance's access token")
    _attempts.pop("\x00token", None)
    from alphadesk.app import dashboard
    uid = dashboard._local_uid()
    state = store.user_session_state(uid)
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(uid, store.user_email(uid) or "local@alphadesk.invalid", (state or {}).get("session_version") or 1),
        max_age=SESSION_TTL_S, httponly=True, samesite="strict",
        secure=os.environ.get("ALPHADESK_COOKIE_SECURE", "").strip() == "1",
    )
    return {"user": {"email": "this instance"}}


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
    # agent calls it from outside, with no browser session to present. The
    # plain-HTTP data API (/api/v1, app/rest_data.py) carries the same one,
    # for the programs that read AlphaDesk without being agents.
    return path.startswith("/api") and not path.startswith("/api/auth") \
        and not path.startswith("/api/agent/tools") and not path.startswith("/api/v1") \
        and path != "/api/healthz" and path != "/healthz"
