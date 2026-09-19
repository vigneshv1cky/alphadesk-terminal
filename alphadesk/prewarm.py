"""Keep an owner's panels warm (2026-09-19, the owner's call after measuring:
"go with your recommendation").

Measured on the owner's keys: most panels answer in under half a second, but
a handful are slow when the server's short-term caches are cold — currency
movers 3.4s, insider trades 3.1s, options flow 2.6s, the dividend calendar
and stock movers ~1.2s — and the first strip after a restart took 11.9s.
Warm, each answers in milliseconds.

So the server REPLAYS what an owner actually looked at:
  * a middleware notes each successful read request an OWNER makes under
    /api/ (the request, never its answer), kept in the database so a
    restart can warm up at once;
  * a background thread re-sends those requests to the server itself, as
    that owner, one at a time — fast-changing data (movers, quotes, the
    strip, today's charts, options flow, sectors, the news window) every
    minute, everything else every ten minutes — so the page's own request
    finds its exact answer already warm.

Owners only, and only while the owner has used the terminal within
ACTIVE_HOURS: this is the owner's personal-use decision, and invariant 4
("an idle terminal spends nothing") still holds for every other reader and
for an owner who stops visiting. A request not repeated by the owner within
KEEP_HOURS is dropped. Only reads are replayed; sign-in, admin, agent
access, keys, account and streaming routes never are.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

ACTIVE_HOURS = 48.0
KEEP_HOURS = 24.0
FAST_S = 60.0
SLOW_S = 600.0
TICK_S = 15.0
MAX_PER_TICK = 60
HEADER = "X-AlphaDesk-Prewarm"

#: Never recorded or replayed: not reads of market data, or not safe to repeat.
_NEVER = ("/api/stream", "/api/auth", "/api/admin", "/api/agent", "/api/account", "/api/keys",
          "/api/views", "/api/board", "/api/chart/state", "/api/widgets", "/api/system",
          "/api/data/vendors", "/api/news/related", "/api/search", "/api/earnings/find")
#: Refreshed every FAST_S: what changes minute to minute.
_FAST = ("/api/movers", "/api/rail", "/api/quote", "/api/quotes", "/api/tape", "/api/indices",
         "/api/crypto", "/api/options-flow", "/api/sectors")

_seen: dict[str, dict[str, float]] = {}          # user -> path -> last used (epoch)
_replayed: dict[tuple[str, str], float] = {}     # (user, path) -> last replayed
_persisted: dict[tuple[str, str], float] = {}    # (user, path) -> last written to the store
_lock = threading.Lock()
_started = False


def enabled() -> bool:
    return os.environ.get("ALPHADESK_PREWARM", "on").lower() not in ("off", "0", "false", "no")


def worth_keeping(path: str) -> bool:
    """Whether a request is a market-data read worth keeping warm. Pure."""
    if not path.startswith("/api/") or path.startswith(_NEVER):
        return False
    # A search or an older page is a one-off, not a panel.
    return "q=" not in path and "before=" not in path


def interval(path: str) -> float:
    """How often a kept request is refreshed. Pure."""
    if path.startswith(_FAST):
        return FAST_S
    if path.startswith("/api/chart/") and ("range=1D" in path or "range=5D" in path):
        return FAST_S
    if path.startswith("/api/news") and "symbol=" not in path:
        return FAST_S
    return SLOW_S


def note(user_id: str, path: str) -> None:
    """An owner just read `path`: keep it warm."""
    if not enabled() or not worth_keeping(path):
        return
    now = time.time()
    with _lock:
        _seen.setdefault(user_id, {})[path] = now
        # A replay the owner just made unnecessary.
        _replayed[(user_id, path)] = now
        last = _persisted.get((user_id, path), 0.0)
        write = now - last > 300
        if write:
            _persisted[(user_id, path)] = now
    if write:
        try:
            from alphadesk.ledger import store
            store.note_warm_path(user_id, path)
        except Exception as exc:                  # warming is a convenience, never an error
            log.debug("prewarm note: %s", exc)


def _load(user_id: str) -> dict[str, float]:
    """The owner's kept requests: this process's, and the store's (after a
    restart, the store's are all there is)."""
    from alphadesk.ledger import store
    cutoff = datetime.now(timezone.utc) - timedelta(hours=KEEP_HOURS)
    with _lock:
        mine = dict(_seen.get(user_id, {}))
    for row in store.warm_paths(user_id, cutoff.isoformat()):
        try:
            at = datetime.fromisoformat(row["last_used_at"]).timestamp()
        except ValueError:
            continue
        mine[row["path"]] = max(mine.get(row["path"], 0.0), at)
    return {p: at for p, at in mine.items() if at >= cutoff.timestamp()}


def _owners() -> list[tuple[str, str]]:
    """(user_id, email) of every owner seen within ACTIVE_HOURS; on an open
    instance, its one local account."""
    from alphadesk import billing
    from alphadesk.app import auth
    from alphadesk.ledger import store
    return [(u["user_id"], u.get("email") or "") for u in store.active_users(ACTIVE_HOURS)
            if not auth.auth_required() or billing.is_owner(u.get("email"))]


def _replay(user_id: str, email: str, path: str) -> None:
    from alphadesk.app import auth
    from alphadesk.ledger import store
    port = os.environ.get("DASHBOARD_PORT", "8000")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={HEADER: "1"})
    if auth.auth_required():
        state = store.user_session_state(user_id) or {}
        cookie = auth.issue_session(user_id, email, state.get("session_version", 1))
        req.add_header("Cookie", f"{auth.SESSION_COOKIE}={cookie}")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            resp.read()
    except Exception as exc:                      # a 428 or a vendor hiccup: try again next round
        log.debug("prewarm %s: %s", path, exc)


def tick() -> int:
    """Replay what is due for every active owner. Returns how many."""
    done = 0
    now = time.time()
    for user_id, email in _owners():
        for path in sorted(_load(user_id)):
            if done >= MAX_PER_TICK:
                return done
            with _lock:
                last = _replayed.get((user_id, path), 0.0)
            if now - last < interval(path):
                continue
            _replay(user_id, email, path)
            with _lock:
                _replayed[(user_id, path)] = time.time()
            done += 1
    return done


def _loop() -> None:
    time.sleep(10)                               # let the web server bind first
    while True:
        try:
            n = tick()
            if n:
                log.info("prewarm: refreshed %d panels", n)
        except Exception as exc:
            log.warning("prewarm: %s", exc)
        time.sleep(TICK_S)


def start() -> None:
    """Start keeping owners' panels warm, in the background."""
    global _started
    if _started or not enabled():
        return
    _started = True
    threading.Thread(target=_loop, name="prewarm", daemon=True).start()
