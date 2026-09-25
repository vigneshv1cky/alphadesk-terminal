"""Keeping the scraped pages fresh in the background (2026-09-25, #71).

THE OWNER'S CALL, taken with the trade stated. Until now a scraped page was
read on a reader's request and held for that reader. Two things were wrong
with that, and the owner's argument for fixing them is the better one: the
page is IDENTICAL for every reader — no key shapes a halt list — so keying
it per reader bought no privacy and cost one fetch of the site PER READER.
Ten readers meant ten hits on the same Nasdaq page.

So the store is shared (ledger/store.py, `scraped_data`, no owner column)
and this loop keeps it warm, which means a reader never waits for a scrape
at all.

WHAT IT DOES NOT DISSOLVE: one copy of someone else's data, served from our
server to many readers, is the redistribution shape that removed operator
sources in PR #71 — "an opt-in still runs from our server under our name".
The owner weighed that and chose this. It is written down in CLAUDE.md so
nobody re-opens it as though it were an oversight.

TWO THINGS KEEP IT HONEST, both deliberate:

  * IT ONLY RUNS FOR A SOURCE SOMEBODY SWITCHED ON. Invariant 4 says an idle
    terminal spends nothing, and a blind timer scrapes at 3am for nobody. A
    source no account has enabled is not fetched at all, so an instance
    where nobody wants scraping does none.
  * IT HAS A KILL SWITCH. ALPHADESK_SCRAPE_LOOP=off stops it dead, for the
    same reason the embedding worker has one: background work that reaches
    the network is exactly what you want to be able to stop from the console
    without a deploy (semantic.py's outage, 2026-09-19).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta

log = logging.getLogger("alphadesk.scrape")

# How often each kind is re-read. Halts move minute to minute; a calendar
# day does not, and a past one never does.
HALTS_EVERY_S = 120.0
SOCIAL_EVERY_S = 300.0
CALENDAR_EVERY_S = 1800.0
# The calendar window kept warm: what the earnings page and the split
# calendar actually ask for, no wider.
CALENDAR_BACK_DAYS = 14
CALENDAR_FORWARD_DAYS = 14


def switched_on() -> bool:
    """The kill switch. Background work that reaches the network is exactly
    what you want to stop from the console without a deploy — the lesson the
    embedding worker's outage left (semantic.py, 2026-09-19)."""
    return os.environ.get("ALPHADESK_SCRAPE_LOOP", "on").lower() not in ("off", "0", "false", "no")


def enabled_sources() -> set[str]:
    """Which scraped sources at least one account has switched on.

    The gate that keeps invariant 4: nobody has asked for it, so it is not
    fetched. Read fresh each cycle, so switching a source on starts it
    within a cycle and switching it off stops it."""
    from alphadesk.ledger import store
    from alphadesk.providers.scraped import SCRAPED_SOURCES
    try:
        return store.enabled_providers("prices") & set(SCRAPED_SOURCES)
    except Exception as exc:                                  # never kill the loop
        log.warning("scrape gate unreadable: %s", exc)
        return set()


def refresh_halts() -> int:
    """Today's halts, into the shared store. No vendor in the catalogue
    carries halts at all, which is why this source exists."""
    from alphadesk.providers.scraped import NasdaqCalendars, store_day
    rows = NasdaqCalendars().trading_halts(limit=500) or []
    store_day("halts", "today", rows)
    return len(rows)


def refresh_social() -> int:
    from alphadesk.ledger import store
    from alphadesk.providers.scraped import SocialPulse
    rows = SocialPulse().social_posts(limit=100) or []
    store.put_scraped("social", "posts", "latest", rows)
    return len(rows)


def calendar_days(today: date | None = None) -> list[str]:
    """The weekdays the calendars ask for. Weekends carry no corporate
    calendar, so they are never fetched."""
    today = today or date.today()
    out: list[str] = []
    day = today - timedelta(days=CALENDAR_BACK_DAYS)
    end = today + timedelta(days=CALENDAR_FORWARD_DAYS)
    while day <= end:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def refresh_calendars() -> int:
    """Each weekday's earnings list, and the splits list, into the shared
    store — but only the ones that are actually stale. A past day is held
    for a week, so a cycle normally fetches nothing at all."""
    from alphadesk.providers.scraped import _SPLITS_KEY, NasdaqCalendars, cached_day, store_day
    v = NasdaqCalendars()
    read = 0
    for day in calendar_days():
        if cached_day("earnings", day) is not None:
            continue
        try:
            store_day("earnings", day, v._rows(f"calendar/earnings?date={day}"))
            read += 1
        except Exception as exc:
            log.debug("scrape earnings %s: %s", day, exc)
    if cached_day("splits", _SPLITS_KEY) is None:
        try:
            from alphadesk.providers.scraped import _today_ny
            store_day("splits", _SPLITS_KEY, v._rows("calendar/splits?date=" + _today_ny()))
            read += 1
        except Exception as exc:
            log.debug("scrape splits: %s", exc)
    return read


def cycle(last: dict[str, float]) -> dict[str, int]:
    """One pass. Returns what was refreshed, for the log. Each kind keeps its
    own clock, and a kind whose source is switched off is skipped entirely.

    The monotonic clock counts from the machine's boot, so a caller's first
    clock must be minus infinity rather than 0 — starting at 0 skipped the
    first interval on a fresh container (#264)."""
    on = enabled_sources()
    now = time.monotonic()
    done: dict[str, int] = {}
    jobs = (("halts", "nasdaq", HALTS_EVERY_S, refresh_halts),
            ("calendars", "nasdaq", CALENDAR_EVERY_S, refresh_calendars),
            ("social", "social", SOCIAL_EVERY_S, refresh_social))
    for name, source, every, job in jobs:
        if source not in on or now - last.get(name, float("-inf")) < every:
            continue
        last[name] = now
        try:
            got = job()
            if got:
                done[name] = got
        except Exception as exc:
            # A scrape that fails is tried again next cycle; it must never
            # stop the others or the loop.
            log.warning("scrape %s failed: %s", name, exc)
    return done
