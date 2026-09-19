"""One company's earnings record from the user's vendors, with revenue as
FILED from SEC EDGAR (2026-09-13).

The report rows — dates, EPS estimate and actual, the surprise, and a
vendor's revenue figures where it has them — come from whichever connected
vendor carries the earnings history. The quarter's revenue is joined from
the company's own 10-Q and 10-K figures (keyless public data), matched to
each report by its period end, so the revenue column never depends on a key.
"""

from __future__ import annotations

import logging

log = logging.getLogger("alphadesk.earnings_record")


def history(symbol: str) -> dict:
    """{symbol, reports, vendor}. Raises NeedsKey when no connected vendor
    carries an earnings history."""
    from alphadesk.ingest import edgar
    from alphadesk.ingest.prices import match_report_periods
    from alphadesk.providers import get_prices
    router = get_prices()
    sym = symbol.upper()
    got = router.ask("earnings_history", sym)
    vendor = router.answered_by
    reports = [dict(r) for r in (got or {}).get("reports") or []]
    try:
        by_end = edgar.quarterly_revenue(sym)
    except Exception as exc:
        log.debug("filed revenue unavailable for %s: %s", sym, exc)
        by_end = {}
    if by_end and reports:
        from datetime import date as _date
        # A row that knows its period end is matched to the filed quarter
        # ending within ten days of it (a 52/53-week year closes Apple's
        # June quarter on the 27th); a row with only its report date is
        # matched to the latest quarter that closed before it.
        ends = {e: _date.fromisoformat(e) for e in by_end}
        for r in reports:
            pe = r.get("period_end")
            if r.get("revenue") is None and pe:
                p = _date.fromisoformat(pe[:10])
                near = min(ends, key=lambda e: abs((ends[e] - p).days), default=None)
                if near and abs((ends[near] - p).days) <= 10:
                    r["revenue"] = by_end[near]
        dated = [r for r in reports if not r.get("period_end")]
        link = match_report_periods([r["date"] for r in dated], list(by_end))
        for r in dated:
            if r.get("revenue") is None and r["date"] in link:
                r["revenue"] = by_end[link[r["date"]]]
    for r in reports:
        r.setdefault("revenue", None)
        r.setdefault("revenue_estimate", None)
        r.setdefault("period_end", None)
        r.setdefault("date_kind", "report")
    reports.sort(key=lambda r: r["date"], reverse=True)
    return {"symbol": sym, "reports": reports, "vendor": vendor}


def context(symbol: str) -> dict:
    """The reported record the EPS chart draws, from the same vendors, with
    the last four filed quarters' revenue and net income from EDGAR."""
    from alphadesk.ingest import edgar_financials
    from alphadesk.providers import get_prices
    router = get_prices()
    sym = symbol.upper()
    out = dict(router.ask("earnings_context", sym))
    out["vendor"] = router.answered_by
    fin = edgar_financials.fundamentals_series(sym, "quarterly", limit=5)
    rev = [p["v"] for p in fin["series"].get("revenue", [])]
    ni = [p["v"] for p in fin["series"].get("net_income", [])]
    if len(rev) >= 2 and rev[-2]:
        out["revenue_qoq_pct"] = round(100 * (rev[-1] / rev[-2] - 1), 2)
    if rev:
        out["revenue_last4_bn"] = [round(v / 1e9, 3) for v in rev[-4:]]
    if ni:
        out["net_income_last4_bn"] = [round(v / 1e9, 3) for v in ni[-4:]]
    return out
