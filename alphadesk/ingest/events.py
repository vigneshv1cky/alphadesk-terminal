"""Dated events for the chart: earnings releases, dividends, splits.

EARNINGS come from EDGAR, not a calendar vendor: a results release is an
8-K with Item 2.02 (Results of Operations and Financial Condition), filed
the day of the release. That is the primary source, it is free, and every
marker carries the accession of the filing it stands for — so an "E" on the
chart is a link to the document, not a date someone typed into a feed.

DIVIDENDS and SPLITS come from the user's own vendors (2026-09-13).
Nothing here polls.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta

from alphadesk.ingest import edgar

log = logging.getLogger(__name__)

_TTL_S = 3600
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _earnings(symbol: str, since: date) -> list[dict]:
    rows = edgar.recent_filings(symbol, forms=("8-K",), limit=80)
    out = []
    for r in rows:
        items = {i.strip() for i in (r.get("items") or "").split(",") if i.strip()}
        if "2.02" not in items:
            continue
        # The release day is the 8-K's date of report; a company may file
        # it up to four business days later (2026-09-14, Optical Cable).
        d = (r.get("report_date") or r.get("filing_date") or "")[:10]
        if d < since.isoformat():
            continue
        out.append({"date": d, "filed": r.get("filing_date"), "accession": r["accession"], "url": r["url"]})
    return out


def _actions(symbol: str, since: date) -> tuple[list[dict], list[dict]]:
    """Dividends and splits since `since` from the user's vendors (2026-09-13
    — the Yahoo corporate-action history is gone); none without a vendor
    that carries them. Earnings markers stay EDGAR's, keyless."""
    from alphadesk.ingest import corporate_actions
    from alphadesk.providers.base import NeedsKey
    try:
        got = corporate_actions.corporate_actions(symbol)
    except NeedsKey:
        return [], []
    cut = since.isoformat()
    dividends = [{"date": r["ex_date"], "amount": r.get("adjusted_amount") if r.get("adjusted_amount") is not None else r.get("amount")}
                 for r in got["dividends"] if (r.get("ex_date") or "") >= cut]
    splits = [{"date": r["date"], "ratio": (r["to"] / r["from"]) if r.get("from") and r.get("to") else None}
              for r in got["splits"] if (r.get("date") or "") >= cut]
    return dividends, splits


def events(symbol: str, days: int = 400) -> dict:
    """{symbol, earnings, dividends, splits} for the last `days` days."""
    from alphadesk.providers.registry import _request_uid
    sym = symbol.upper()
    # Scoped to the user: the dividend half is from their own vendors.
    key = f"{_request_uid() or 'anonymous'}:{sym}:{days}"
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _TTL_S:
            return hit[1]
    since = date.today() - timedelta(days=days)
    dividends, splits = _actions(sym, since)
    out = {
        "symbol": sym,
        "earnings": _earnings(sym, since),
        "dividends": dividends,
        "splits": splits,
    }
    with _lock:
        _cache[key] = (time.time(), out)
    return out
