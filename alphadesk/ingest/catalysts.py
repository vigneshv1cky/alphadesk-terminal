"""THE CATALYST TAPE (2026-09-22) — four feeds of things that happened, in
one time-ordered list.

Each feed already answers on its own. This puts them in one shape so the
terminal can show a tape rather than four panels a reader has to read across,
and so the order is decided once, here, rather than differently in each.

WHAT IS IN IT, AND WHAT EACH ONE COSTS:

  filings     EDGAR's own feed. Keyless, on for everyone.
  government  Federal Register, the Fed, Treasury. Keyless, on for everyone.
  halts       the exchange's halt feed, through the reader's scraped Nasdaq
              source — off until they switch it on.
  social      posts, through the reader's scraped social source — off until
              they switch it on, and never acted on (see providers/scraped).

TIME IS THE HARD PART, and it is why the merge lives in one place. The feeds
do not agree on what a timestamp is:

  * EDGAR and the halt feed carry a real MOMENT, to the second.
  * The Federal Register and Treasury carry a DATE, because they publish once
    a day — the event usually happened before the stamp.
  * The halt feed states New York time WITHOUT AN OFFSET, so it is given one
    here; left bare it would be read as UTC and every halt would appear four
    hours late.

Every row says which kind of stamp it carries. A day-stamped row sorts to the
START of its day, so it falls below that day's timed rows — the most that can
honestly be said about their order, and never a guess at a time it does not
have.

NOTHING HERE IS RANKED OR SCORED (invariant 3): the order is the clock's.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger("alphadesk.catalysts")

FEEDS = ("filings", "halts", "government", "social")

#: Characters of a social post kept for the tape's one-line row. The whole
#: post is available from the feed itself; this is a list, not a reader.
POST_CHARS = 180


def _row(feed: str, kind: str, title: str, at: str, precision: str,
         symbols: list[str] | None = None, url: str | None = None,
         via: str | None = None, trust: str | None = None) -> dict:
    row = {"feed": feed, "kind": kind, "title": title, "at": at,
           "precision": precision, "symbols": symbols or [], "url": url, "via": via}
    if trust:
        row["trust"] = trust
    return row


def _et_instant(local: str | None) -> str | None:
    """A New York wall-clock stamp with the offset it was missing.

    The exchange writes "2026-09-22T14:54:49" and means New York. Merged as
    it stands, it would be read as UTC and every halt would sort four hours
    late — ahead of filings that actually preceded it."""
    from datetime import datetime

    from alphadesk.config import ET
    if not local:
        return None
    try:
        return datetime.fromisoformat(local).replace(tzinfo=ET).isoformat()
    except (TypeError, ValueError):
        return None


def _filings(limit: int) -> list[dict]:
    from alphadesk.ingest import edgar_feed
    got = edgar_feed.recent(limit=limit)
    out = []
    for f in got.get("filings") or []:
        out.append(_row("filings", f.get("form") or "Filing",
                        f.get("company") or "", f.get("filed_at") or "",
                        # EDGAR stamps acceptance to the second.
                        "second", f.get("symbols") or [], f.get("url"), "SEC EDGAR"))
    return [r for r in out if r["at"] and r["title"]]


def _government(limit: int) -> list[dict]:
    from alphadesk.ingest import gov_feed
    got = gov_feed.recent(limit=limit)
    out = []
    for e in got.get("events") or []:
        agencies = e.get("agencies") or []
        via = (agencies[-1] if agencies else
               {"fed": "Federal Reserve", "treasury": "US Treasury"}.get(e.get("source"), "US government"))
        out.append(_row("government", e.get("kind") or "Action", e.get("title") or "",
                        e.get("at") or "", e.get("at_precision") or "day",
                        [], e.get("url"), via))
    return [r for r in out if r["at"] and r["title"]]


def _halts(router: Any, limit: int) -> list[dict]:
    rows = router.get("trading_halts", limit=limit, surface="trading_halts") or []
    out = []
    for h in rows:
        at = _et_instant(h.get("halted_at"))
        if not at:
            continue
        # The reason where the exchange publishes one, the bare code where it
        # does not — never a meaning invented here.
        reason = h.get("reason") or h.get("reason_code") or "Halted"
        resumed = "" if h.get("resumed") else " — still halted"
        out.append(_row("halts", "Halt",
                        f"{h.get('symbol')} halted: {reason}{resumed}",
                        at, "second", [h["symbol"]] if h.get("symbol") else [],
                        None, h.get("market") or "Exchange"))
    return out


def _social(router: Any, limit: int) -> list[dict]:
    rows = router.get("social_posts", limit=limit, surface="social") or []
    out = []
    for p in rows:
        text = (p.get("text") or "").strip()
        if not text or not p.get("at"):
            continue
        short = text if len(text) <= POST_CHARS else text[:POST_CHARS].rsplit(" ", 1)[0] + "…"
        out.append(_row("social", "Post", short, p["at"], "second",
                        # Deliberately none: a ticker in a post is the
                        # author's claim, not a fact (providers/scraped.py).
                        [], p.get("url"), p.get("via") or p.get("platform"),
                        trust=p.get("trust")))
    return out


#: How long the tape waits for its four feeds before answering with what it
#: has. THE REASON THIS EXISTS: each feed reaches an outside service — five
#: EDGAR pages and three government ones — and a cold call ran well past a
#: minute on one request worker. This service has been taken down twice by a
#: slow endpoint holding workers until Cloud Run killed them (see
#: app/dashboard.py's note on /api/rail), and a tile that polls every minute
#: is exactly the shape that did it. The underlying feeds cache for minutes,
#: so the first visit is short a feed or two and the next one is whole.
DEADLINE_S = 6.0
_pool: Any = None
_pool_lock = threading.Lock()
#: The one job per feed that is currently running, shared by every caller.
_inflight: dict[str, Any] = {}


def _workers() -> Any:
    """A small pool of this module's own, so a slow feed never competes for
    the request threadpool it was called from."""
    global _pool
    with _pool_lock:
        if _pool is None:
            from concurrent.futures import ThreadPoolExecutor
            _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="catalysts")
        return _pool


def _start(name: str, work: Any) -> Any:
    """The running job for this feed, starting one only if none is.

    MEASURED 2026-09-22: EDGAR's page takes about four seconds cold and the
    deadline is six, so a tile polling every minute reliably asked again
    while the first read was still out — and because the feeds below write
    their cache only when a read FINISHES, the second call found nothing
    cached and started a third. That is the rail's fault exactly: a cache
    written only on completion is not a cache under concurrency, it is a
    multiplier. Callers now join the read that is already running."""
    # The pool is fetched BEFORE the lock: _workers() takes the same lock,
    # and threading.Lock is not reentrant, so doing it inside deadlocked
    # every caller (caught before this shipped).
    pool = _workers()
    with _pool_lock:
        job = _inflight.get(name)
        if job is not None and not job.done():
            return job
        job = pool.submit(work)
        _inflight[name] = job
    # Dropped when it finishes, so the next caller past the cache's lifetime
    # starts a fresh one rather than joining a stale finished job.
    job.add_done_callback(lambda done: _inflight.pop(name, None)
                          if _inflight.get(name) is done else None)
    return job


def tape(limit: int = 60, feeds: list[str] | None = None) -> dict:
    """The four feeds merged, newest first.

    A feed that is switched off, still arriving, or that could not be read is
    named in `unavailable` with WHICH of those it was — an empty tape must
    never be mistaken for a quiet market."""
    from concurrent.futures import wait
    from alphadesk.identity import request_user, reset_request_user, set_request_user
    from alphadesk.providers import get_prices
    wanted = [f for f in (feeds or FEEDS) if f in FEEDS]
    if not wanted:
        wanted = list(FEEDS)
    router = get_prices()
    connected = set(router.connected)
    readers = {
        "filings": lambda: _filings(limit),
        "government": lambda: _government(limit),
        "halts": lambda: _halts(router, limit),
        "social": lambda: _social(router, limit),
    }
    # Which source each keyed feed needs, so "off" is said as off rather than
    # surfacing as an empty list.
    needs = {"halts": "nasdaq", "social": "social"}
    unavailable: dict[str, str] = {}
    jobs = {}
    # A POOL THREAD DOES NOT INHERIT THE READER (identity.py, deliberately),
    # and two of these feeds resolve the reader's own vendors. Stamping it on
    # the thread is what ingest/background_fill.py does, and forgetting it is
    # what broke /api/rail the day after its own deadline landed.
    uid = request_user()

    def run(fn):
        token = set_request_user(uid) if uid else None
        try:
            return fn()
        finally:
            if token is not None:
                reset_request_user(token)

    for name in wanted:
        source = needs.get(name)
        if source and source not in connected:
            unavailable[name] = f"not switched on — connect the {source} source on the Account page"
            continue
        reader = readers[name]
        jobs[_start(name, lambda fn=reader: run(fn))] = name

    rows: list[dict] = []
    done, pending = wait(list(jobs), timeout=DEADLINE_S)
    for job in done:
        name = jobs[job]
        try:
            rows += job.result()
        except Exception as exc:                  # one feed must not empty the tape
            log.info("catalyst tape %s: %s", name, exc)
            unavailable[name] = str(exc)[:200]
    for job in pending:
        # Left running on purpose: it fills the feed's own cache, so the next
        # poll a minute from now has it. Cancelling would repeat the wait.
        unavailable[jobs[job]] = "still arriving — it will be here on the next refresh"
    # The clock decides, and nothing else. A day-stamped row has no time, so
    # it sorts to the start of its day and falls below that day's real moments.
    rows.sort(key=lambda r: r["at"], reverse=True)
    return {"rows": rows[:max(1, min(int(limit), 200))], "unavailable": unavailable}


__all__ = ["FEEDS", "tape"]
