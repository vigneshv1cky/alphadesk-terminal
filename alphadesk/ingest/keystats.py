"""Key statistics for ONE symbol — the summary block a quote page shows:
where the price sits (day range, 52-week range, the moving averages), how
big and how traded it is (market cap, enterprise value, shares, float,
average volume), what it earns and pays (P/E both ways, PEG, price to book
and sales, EPS, dividend and yield), and who holds it.

From the user's own vendors (2026-09-13): the figures from whichever
connected vendor carries key statistics, the day's price block from the
quote vendor. A field neither carries stays None — the panel draws a dash.
Caching lives in the per-user vendor memo (providers/registry.py), so one
user's keyed answers are never served to another.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("alphadesk.keystats")

# Price-block fields taken from the quote vendor when present.
_FROM_QUOTE = ("price", "previous_close", "open", "day_low", "day_high", "volume")

# ----------------------------------------------------------------------------
# A REPEATEDLY SPLIT COMPANY BREAKS THIS PANEL IN TWO DIFFERENT WAYS
# (2026-09-23, #65, after a reader's agent read WHLR: market cap $16,581,
# 52-week high $94,608, trailing EPS $8,750.65, P/E 0.000114).
#
# THE TWO ARE NOT THE SAME FAULT AND MUST NOT GET THE SAME TREATMENT, which
# is the mistake this nearly shipped with. Measured against the company's own
# SEC XBRL filings that day, Wheeler's filed diluted EPS was -$22.04 for 2022,
# -$13,157.97 for 2023 and -$346,484.38 for 2024. Those are the COMPANY'S OWN
# NUMBERS: a reverse split restates every historical per-share figure
# retroactively, so after enough of them the honest figure IS enormous. A
# vendor reporting a $94,608 52-week high is being FAITHFUL, and deleting it
# would be suppressing a true number — a quieter lie than printing it.
#
# What is genuinely impossible is the share count. A NASDAQ-listed REIT with
# $99M of annual revenue and a $434M enterprise value cannot have 3,048 shares
# outstanding or a $16,581 market capitalisation; NASDAQ alone requires a
# 500,000-share public float. There the vendor has applied the cumulative
# split factor to the share count while quoting an unadjusted current price.
#
# So: figures on a PRE-SPLIT basis are kept and marked, the impossible share
# count is withheld, and anything that DIVIDES a current price by a pre-split
# per-share figure is withheld because it is meaningless rather than merely
# large — a P/E of 0.000114 is not a cheap stock, it is two different share
# counts in one fraction.

# Kept, and marked: true figures on the basis the vendor restated them to.
_PRE_SPLIT = ("week52_low", "week52_high", "avg_50d", "avg_200d",
              "trailing_eps", "forward_eps", "book_value")
# Withheld: a current price over a pre-split per-share figure. `week52_position`
# is OURS — we computed a stock up 191% on the day as sitting at the very
# bottom of its year, because the range it was measured against spans a split.
_MIXED_BASIS = ("trailing_pe", "forward_pe", "peg", "price_to_book",
                "price_to_sales", "week52_position")
# Withheld: contradicted by a figure from the same response.
_SHARE_COUNT = ("market_cap", "shares_outstanding", "float_shares")

# Each threshold is set where no correctly adjusted record can reach it, not
# where the suspicious ones sit — a false positive hides a true figure, so
# these are deliberately far out. A company in deep distress trades at a tenth
# of book; a hundred times book per share is not a valuation, it is a unit
# mismatch. Enterprise value legitimately dwarfs a small equity — a thousand
# times over does not happen without the share count being wrong.
_BOOK_TO_PRICE = 100.0
_EPS_TO_PRICE = 100.0
_HIGH_TO_PRICE = 1000.0
_AVG_TO_PRICE = 100.0
_EV_TO_CAP = 1000.0


def _ratio(a, b) -> Optional[float]:
    """a/b where both are numbers and b is positive. Pure."""
    if a is None or b is None:
        return None
    try:
        return abs(a) / b if b > 0 else None
    except TypeError:                                   # pragma: no cover
        return None


def basis_conflict(out: dict) -> dict:
    """Which of this record's figures cannot be read beside its price, and
    why, in the reader's own words. Pure — arithmetic on one response, no
    vendor call, so it costs nothing on the overwhelming majority of symbols
    where nothing fires.

    Returns {"pre_split": [...], "share_count": [...]}; either list empty
    means that group is sound.
    """
    price = out.get("price")
    pre: list[str] = []
    counted: list[str] = []
    if price:
        book = _ratio(out.get("book_value"), price)
        eps = _ratio(out.get("trailing_eps"), price)
        high = _ratio(out.get("week52_high"), price)
        avg = _ratio(out.get("avg_200d"), price)
        if book and book > _BOOK_TO_PRICE:
            pre.append(f"book value per share is {book:,.0f} times the share price")
        if eps and eps > _EPS_TO_PRICE:
            pre.append(f"trailing earnings per share is {eps:,.0f} times the share price")
        if high and high > _HIGH_TO_PRICE:
            pre.append(f"the 52-week high is {high:,.0f} times the price")
        if avg and avg > _AVG_TO_PRICE:
            pre.append(f"the 200-day average is {avg:,.0f} times the price")
    ev = _ratio(out.get("enterprise_value"), out.get("market_cap") or 0)
    if ev and ev > _EV_TO_CAP:
        counted.append(f"an enterprise value {ev:,.0f} times the market capitalisation, "
                       "which cannot both be true of the same company")
    return {"pre_split": pre, "share_count": counted}


def merge(stats: dict, quote: Optional[dict]) -> dict:
    """The vendor's statistics with the quote's price block laid over, and
    the 52-week position computed. Pure."""
    out = dict(stats)
    for k in _FROM_QUOTE:
        if quote and quote.get(k) is not None:
            out[k] = quote[k]
        out.setdefault(k, None)
    lo, hi, p = out.get("week52_low"), out.get("week52_high"), out.get("price")
    out["week52_position"] = (round((p - lo) / (hi - lo) * 100, 1)
                              if lo is not None and hi is not None and p is not None and hi > lo else None)
    found = basis_conflict(out)
    if found["pre_split"] or found["share_count"]:
        # Withheld figures are set to None, which the panel already draws as
        # a dash — the reasons travel beside them so the dash is explained
        # rather than reading as "no data exists" (invariant 8's rule for a
        # missing panel, applied to a missing figure).
        for field in (_MIXED_BASIS if found["pre_split"] else ()):
            out[field] = None
        for field in (_SHARE_COUNT if found["share_count"] else ()):
            out[field] = None
        out["basis"] = {
            "pre_split": found["pre_split"],
            "share_count": found["share_count"],
            # The figures that survive but are not on today's share count.
            "marked": [f for f in _PRE_SPLIT if out.get(f) is not None] if found["pre_split"] else [],
            "withheld": ([f for f in _MIXED_BASIS if found["pre_split"]]
                         + [f for f in _SHARE_COUNT if found["share_count"]]),
            "split": None,          # filled by key_stats when one explains it
        }
    return out


def key_stats(symbol: str) -> dict:
    """Raises NeedsKey when no connected vendor carries key statistics."""
    from alphadesk.providers import get_prices
    router = get_prices()
    sym = symbol.upper()
    stats = router.ask("key_stats", sym)
    vendor = router.answered_by
    quote = router.get("quote", sym)
    out = merge(stats, quote)
    out["vendor"] = vendor
    if out.get("avg_50d") is None or out.get("avg_200d") is None:
        # The moving averages, when the statistics vendor lacks them, from
        # the user's own daily bars (one request for 200 sessions).
        bars = (router.get("daily_history", [sym], 200) or {}).get(sym) or []
        closes = [b["close"] for b in bars]
        if len(closes) >= 50 and out.get("avg_50d") is None:
            out["avg_50d"] = round(sum(closes[-50:]) / 50, 4)
        if len(closes) >= 200 and out.get("avg_200d") is None:
            out["avg_200d"] = round(sum(closes[-200:]) / 200, 4)
    # THE APP ALREADY HELD THE EXPLANATION AND NEVER CONNECTED IT: the split
    # calendar carried WHLR's 1-for-9 of 2026-09-22, corroborated by all
    # three of the reader's vendors, while the symbol's own panel said
    # nothing. Looked up ONLY when the arithmetic above found a conflict, so
    # the market-wide fetch is paid on the rare broken symbol and never on
    # the ordinary one — and a failure here loses the explanation, never the
    # guard.
    if out.get("basis"):
        try:
            out["basis"]["split"] = recent_split(router, sym)
        except Exception as exc:                        # the panel still renders
            log.debug("recent split for %s: %s", sym, exc)
    return out


# How far back a split is still the explanation for a mismatched basis. A
# vendor catches up within days; three months is generous and keeps the
# window cheap.
SPLIT_LOOKBACK_DAYS = 120


def recent_split(router, symbol: str) -> Optional[dict]:
    """The most recent corroborated split for `symbol` in the last
    SPLIT_LOOKBACK_DAYS, or None. A split only one vendor lists is NOT
    returned: the same rule the calendar uses, because a single vendor's
    split is a claim rather than an event, and this one is being offered as
    the reason a figure is being withheld."""
    from datetime import date, timedelta

    from alphadesk.ingest.corporate_calendars import split_rows
    today = date.today()
    rows, _vendors = split_rows(router, (today - timedelta(days=SPLIT_LOOKBACK_DAYS)).isoformat(),
                                today.isoformat())
    mine = [r for r in rows
            if r.get("symbol") == symbol and r.get("corroborated") is not False
            and r.get("to") and r.get("from")]
    if not mine:
        return None
    last = max(mine, key=lambda r: r.get("date") or "")
    return {"date": last.get("date"), "to": last["to"], "from": last["from"],
            "reverse": last["to"] < last["from"], "sources": last.get("sources") or []}
