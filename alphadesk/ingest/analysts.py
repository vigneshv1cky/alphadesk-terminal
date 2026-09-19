"""The sell side on ONE symbol — the consensus rating and its distribution,
the price-target range, the recent rating changes and the short-interest
report — each from whichever vendor the user connected carries it
(2026-09-13).

Vendors split these very differently: Finnhub's free key has the rating
distribution but not targets or changes; Alpha Vantage's free overview has
the counts and the mean target; the full set is on paid plans. So the view
is assembled section by section, and a section no connected vendor serves
carries the prompt for the key that would, instead of silently vanishing.
Nothing here scores the analysts or ranks the firms.
"""

from __future__ import annotations

import logging

from alphadesk.providers.base import NeedsKey

log = logging.getLogger("alphadesk.analysts")

SECTIONS = ("analyst_ratings", "price_targets", "rating_changes", "short_interest")


def analyst_view(symbol: str) -> dict:
    """{symbol, recommendation, distribution, targets, changes,
    short_interest, sources, needs}. Raises NeedsKey only when not one
    section has a connected vendor."""
    from alphadesk.providers import get_prices
    router = get_prices()
    sym = symbol.upper()
    got: dict = {}
    sources: dict = {}
    needs: dict = {}
    for section in SECTIONS:
        try:
            got[section] = router.ask(section, sym)
            sources[section] = router.answered_by
        except NeedsKey as exc:
            got[section] = None
            needs[section] = exc.prompt()
    if all(v is None for v in got.values()):
        raise NeedsKey("analyst_ratings", refused=needs.get("analyst_ratings", {}).get("refused"),
                       signed_in=router.uid is not None)
    ratings = got["analyst_ratings"] or {}
    quote = router.get("quote", sym) or {}
    t = got["price_targets"] or {}
    return {
        "symbol": sym,
        "recommendation": ratings.get("recommendation") or {"mean": None, "key": None, "analysts": None},
        "distribution": ratings.get("distribution") or [],
        "targets": {"current": quote.get("price"), "low": t.get("low"), "mean": t.get("mean"),
                    "median": t.get("median"), "high": t.get("high"), "analysts": t.get("analysts"),
                    "published_month": t.get("published_month"), "published_quarter": t.get("published_quarter"),
                    "recent_mean": t.get("recent_mean"), "recent_window": t.get("recent_window")},
        "changes": got["rating_changes"] or [],
        "short_interest": got["short_interest"] or {"shares_short": None, "prior_month": None, "days_to_cover": None,
                                                    "pct_float": None, "float_shares": None, "as_of": None},
        "sources": sources,
        "needs": needs,
    }
