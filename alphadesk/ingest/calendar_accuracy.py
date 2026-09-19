"""How right a reader's calendar vendors were AHEAD of each report
(2026-09-14), scored against EDGAR.

The truth is a quarterly results 8-K filed the day of its release, whose
acceptance instant gives the session: before 09:30 New York is before the
open, from 16:00 after the close. A late filing has no trustworthy clock and
is left out, as are warrants, units and mid-quarter Item 2.02 filings.

For each vendor and each horizon (a day, three days, a week before the
release) the vendor's latest capture on or before that day is read. A
company absent from a capture that exists is "not listed"; a horizon with no
capture at all is not counted — the log only knows what was recorded.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

HORIZONS = (1, 3, 7)


def _session_of(accepted_at: str) -> str:
    from alphadesk.config import ET
    t = datetime.fromisoformat(accepted_at).astimezone(ET)
    hm = t.hour * 60 + t.minute
    return "BMO" if hm < 9 * 60 + 30 else "AMC" if hm >= 16 * 60 else "DAY"


def truth_from_releases(releases: dict[str, list[dict]], start: str, end: str, keep=lambda sym, day: True) -> dict[str, tuple[str, str]]:
    """{symbol: (release day, session)} for same-day results 8-Ks with a
    clock in [start, end], common stock only; `keep` screens out filings
    that are not a quarter's release. Pure apart from `keep`."""
    from alphadesk.ingest.earnings_calendar import release_clock, release_day
    from alphadesk.providers.alpaca import common_stock_symbol
    # One symbol per company: a filer listed under its warrants too (BNC and
    # BNCWZ) is scored once, under its shortest ticker.
    by_cik: dict[str, str] = {}
    for sym, filings in releases.items():
        s = sym.upper()
        if not common_stock_symbol(s) or (len(s) == 5 and s[3] == "W"):
            continue
        cik = next((f.get("cik") for f in filings if f.get("cik")), None) or s
        if cik not in by_cik or len(s) < len(by_cik[cik]):
            by_cik[cik] = s
    out: dict[str, tuple[str, str]] = {}
    for sym in by_cik.values():
        for f in sorted(releases[sym], key=lambda f: f["file_date"]):
            day, clock = release_day(f), release_clock(f)
            if clock and start <= day <= end and keep(sym, day):
                out[sym] = (day, _session_of(clock))
    return out


def score(truth: dict[str, tuple[str, str]], forecasts: list[dict], capture_days: dict[str, list[str]],
          horizons=HORIZONS) -> dict[str, dict[int, dict]]:
    """{vendor: {horizon: {counted, listed, date_exact, date_within_1, session_named, session_right}}}.
    Pure."""
    by_key: dict[tuple[str, str, str], dict] = {(f["vendor"], f["symbol"], f["captured_on"]): f for f in forecasts}
    out: dict[str, dict[int, dict]] = {}
    for vendor, days in capture_days.items():
        out[vendor] = {}
        for h in horizons:
            m = {"counted": 0, "listed": 0, "date_exact": 0, "date_within_1": 0, "session_named": 0, "session_right": 0}
            for sym, (day, sess) in truth.items():
                cutoff = (date.fromisoformat(day) - timedelta(days=h)).isoformat()
                seen = [d for d in days if d <= cutoff]
                if not seen:
                    continue
                m["counted"] += 1
                f = by_key.get((vendor, sym, seen[-1]))
                if not f:
                    continue
                m["listed"] += 1
                gap = abs((date.fromisoformat(f["report_date"]) - date.fromisoformat(day)).days)
                m["date_exact"] += gap == 0
                m["date_within_1"] += gap <= 1
                if f.get("confirmed") and f.get("session") in ("BMO", "AMC"):
                    m["session_named"] += 1
                    m["session_right"] += f["session"] == sess
            out[vendor][h] = m
    return out


def report(owner: str, days: int = 30) -> dict:
    """The reader's scorecard over the last `days` of releases."""
    from alphadesk.config import now_et
    from alphadesk.ingest import earnings_calendar, edgar_releases
    from alphadesk.ledger import store
    today = now_et().date()
    start, end = (today - timedelta(days=days)).isoformat(), today.isoformat()
    releases = edgar_releases.releases_by_symbol(start, (today + timedelta(days=7)).isoformat())
    truth = truth_from_releases(releases, start, end, keep=earnings_calendar.quarter_release)
    lo = (today - timedelta(days=days + 30)).isoformat()
    forecasts = store.forecasts_for(owner, lo, (today + timedelta(days=30)).isoformat())
    capture_days = store.forecast_capture_days(owner)
    first = min((d[0] for d in capture_days.values() if d), default=None)
    return {"start": start, "end": end, "releases": len(truth), "captures_since": first,
            "horizons": list(HORIZONS), "vendors": score(truth, forecasts, capture_days)}
