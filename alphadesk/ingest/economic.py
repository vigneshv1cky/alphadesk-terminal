"""The economic calendar — scheduled releases (CPI, payrolls, rate
decisions, PMIs) with the consensus, the prior figure and the actual once
out — from whichever vendor the user connected carries one (2026-09-13;
Finnhub and Financial Modeling Prep, both on paid plans). There is no free
structured source, so without one the panel names the key that would fill
it, never an empty week.
"""

import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger("alphadesk.economic")

MAX_SPAN_DAYS = 31


def _window(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    today = date.today()
    s = date.fromisoformat(start) if start else today
    e = date.fromisoformat(end) if end else s + timedelta(days=7)
    if e < s:
        s, e = e, s
    if (e - s).days > MAX_SPAN_DAYS:
        e = s + timedelta(days=MAX_SPAN_DAYS)
    return s.isoformat(), e.isoformat()


def calendar(start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """{start, end, rows, source}. Raises NeedsKey (with any plan refusal
    named) when no connected vendor carries an economic calendar."""
    from alphadesk.providers import get_prices
    s, e = _window(start, end)
    router = get_prices()
    rows = router.ask("economic_calendar", s, e)
    # A few US releases arrive on the wrong clock — retail sales and the
    # Employment Cost Index an hour late, twice measured — so US rows are
    # put on their agency's own time where the vendor disagrees, and say so
    # (ingest/release_times.py, 2026-09-15).
    from alphadesk.ingest import release_times
    moved = release_times.correct_times(rows or [])
    if moved:
        log.info("economic calendar: %d US rows put on the agency clock", moved)
    return {"start": s, "end": e, "rows": rows, "source": router.answered_by, "note": None}


def reset_cache() -> None:
    """Nothing is cached here: the per-user vendor memo holds it."""
