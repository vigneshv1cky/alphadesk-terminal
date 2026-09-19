"""Earnings-calendar helpers, vendor-neutral (2026-09-13).

The calendar itself is built per user from their own calendar vendors in
ingest/earnings_calendar.py, and results releases come from SEC EDGAR in
ingest/edgar_releases.py. The Nasdaq route that used to fill a shared
calendar table, and the Yahoo-armed liquidity and implied-move columns, are
gone. What stays here is the arithmetic both use: unioning several vendors'
rows, collapsing a report listed on two dates, and the session clocks.
"""

import logging
from datetime import datetime, timedelta

from alphadesk.config import ET

log = logging.getLogger("alphadesk.earnings")


def _f(v) -> float | None:
    """Parse a Nasdaq numeric string ('$1.23', '(0.45)', '89.08', 'N/A') → float|None."""
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s or s.upper() in ("N/A", "NA", "--"):
        return None
    neg = s.startswith("(") and s.endswith(")")   # accounting negatives: (0.45)
    if neg:
        s = s[1:-1]
    try:
        f = float(s)
        f = -f if neg else f
        return f if f == f else None               # drop NaN
    except (TypeError, ValueError):
        return None


def run_at(report_iso: str, session: str | None) -> str | None:
    """When to run Find Trades to catch the drift: 9:30 ET on the first trading
    session AFTER the result is public. BMO reports are out before that day's open
    (trade the same day); AMC / intraday reports first trade the next session."""
    try:
        dt = datetime.fromisoformat(report_iso).astimezone(ET)
    except (ValueError, TypeError):
        return None
    run_day = dt.date() if session == "BMO" else dt.date() + timedelta(days=1)
    while run_day.weekday() >= 5:      # skip Sat/Sun to the next weekday open
        run_day += timedelta(days=1)
    return datetime(run_day.year, run_day.month, run_day.day, 9, 30, tzinfo=ET).isoformat()


def reported_public(report_iso: str) -> datetime | None:
    """The moment a report counts as PUBLIC — the boundary between 'reporting
    soon' and 'just reported'. Nasdaq's BMO/AMC session tag is unreliable for
    the large majority of reporters (confirmed empirically: ~95% come back
    unclassified even close to the report date — a real data-coverage gap,
    not a parsing bug), so this no longer tries to pinpoint intraday timing
    at all. A report counts as public from midnight ET of its calendar date
    onward — just the date, no BMO/AMC/session distinction."""
    try:
        d = datetime.fromisoformat(report_iso[:10])   # date-only key
    except (ValueError, TypeError):
        return None
    return datetime(d.year, d.month, d.day, 0, 0, tzinfo=ET)


# SECOND SOURCES (2026-09-11). Nasdaq's calendar misses a share of reporters —
# of sixteen names on Yahoo's hub for one Thursday, two (ALOT, GNS) were not
# on Nasdaq's day at all. Each of these serves a whole calendar in one call
# on a free key and is read only when its key is set: FINNHUB_API_KEY,
# ALPHAVANTAGE_API_KEY. Their rows are UNIONED with Nasdaq's — a company
# Nasdaq already lists within three days is the same event and is not added
# — and every row names its sources, so the reader can see which calendar
# knew. Nothing here ranks or curates; it widens who is listed.
_SAME_EVENT_DAYS = 3


def union_calendars(primary: list[dict], others: list[dict]) -> list[dict]:
    """Nasdaq's rows plus what the other calendars know that it does not.

    A company the primary lists within _SAME_EVENT_DAYS of another source's
    date is the same event: the primary's date stands and the source is
    added to its row. A company the primary does not list at all is added
    with its own row. Every row carries `sources`."""
    by_key: dict[tuple[str, str], dict] = {}
    by_sym: dict[str, list[str]] = {}
    for r in primary:
        r = dict(r)
        r["sources"] = sorted(set((r.get("sources") or "nasdaq").split(",")))
        # Which vendors carry an ACTUAL for this report — one vendor's actual
        # with nothing else behind it is a claim, not a report (2026-09-14).
        r["actual_vendors"] = list(r["sources"]) if r.get("eps_actual") is not None else []
        by_key[(r["symbol"], r["report_date"])] = r
        by_sym.setdefault(r["symbol"], []).append(r["report_date"])
    for o in others:
        sym, date = o["symbol"], o["report_date"]
        near = next((d for d in by_sym.get(sym, [])
                     if abs((datetime.fromisoformat(d) - datetime.fromisoformat(date)).days) <= _SAME_EVENT_DAYS), None)
        if near is not None:
            row = by_key[(sym, near)]
            row["sources"] = sorted(set(row["sources"]) | {o["source"]})
            if o.get("eps_actual") is not None:
                row["actual_vendors"] = sorted(set(row.get("actual_vendors") or []) | {o["source"]})
            if row.get("eps_estimate") is None and o.get("eps_estimate") is not None:
                row["eps_estimate"] = o["eps_estimate"]
            # The FAST PATH for the number itself: a source that already
            # carries the actual fills a row whose calendar has not backfilled
            # it (Nasdaq's arrives overnight; Finnhub's the same session).
            if row.get("eps_actual") is None and o.get("eps_actual") is not None:
                row["eps_actual"] = o["eps_actual"]
                est = row.get("eps_estimate")
                if row.get("surprise_pct") is None and est not in (None, 0):
                    row["surprise_pct"] = round((o["eps_actual"] - est) / abs(est) * 100, 2)
                row["confirmed"] = True
            if o.get("confirmed") and not row.get("confirmed"):
                row["confirmed"] = True
                if o.get("session") in ("BMO", "AMC"):
                    row["session"] = o["session"]
            continue
        if (sym, date) in by_key:
            by_key[(sym, date)]["sources"] = sorted(set(by_key[(sym, date)]["sources"]) | {o["source"]})
            continue
        r = dict(o)
        r["sources"] = [o["source"]]
        r["actual_vendors"] = [o["source"]] if o.get("eps_actual") is not None else []
        r.pop("source", None)
        by_key[(sym, date)] = r
        by_sym.setdefault(sym, []).append(date)
    out = []
    for r in by_key.values():
        r = dict(r)
        r.pop("source", None)
        r["sources"] = ",".join(r["sources"])
        out.append(r)
    return out


def collapse_moved(rows: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """One row per report: a company listed on two dates within
    _SAME_EVENT_DAYS is one report whose date moved, and the calendar kept
    both (CMCM sat on a Thursday and the Friday after it, 2026-09-11).

    The row kept is the one with the most standing: a named time, then a
    reported actual, then the later date — a move is usually a postponement.
    Returns the kept rows and the (symbol, date) pairs dropped, so the
    caller can prune them from the ledger."""
    by_sym: dict[str, list[dict]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    kept: list[dict] = []
    dropped: list[tuple[str, str]] = []
    rank = lambda r: (1 if r.get("confirmed") else 0, 1 if r.get("eps_actual") is not None else 0, r["report_date"])  # noqa: E731
    for sym, group in by_sym.items():
        group = sorted(group, key=lambda r: r["report_date"])
        clusters: list[list[dict]] = []
        for r in group:
            if clusters and (datetime.fromisoformat(r["report_date"]) - datetime.fromisoformat(clusters[-1][-1]["report_date"])).days <= _SAME_EVENT_DAYS:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        for c in clusters:
            best = max(c, key=rank)
            kept.append(best)
            dropped.extend((sym, r["report_date"]) for r in c if r is not best)
    return kept, dropped


def previous_weekday(date_str: str) -> str:
    """The weekday before `date_str` — Friday for a Monday."""
    d = datetime.fromisoformat(date_str).date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()
