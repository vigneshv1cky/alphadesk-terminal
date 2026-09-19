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
    return out
