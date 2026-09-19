"""What an ETF or a mutual fund HOLDS — category, family, expense ratio, net
assets, the asset-class split, sector weights and the largest positions —
from whichever vendor the user connected carries fund holdings
(2026-09-13; every source for this is a paid plan). Raises NeedsKey when
none does; the pages then leave the fund panels out.

A refused holdings LIST is filled from another vendor (2026-09-18). FMP's
Premium plan answers a fund's profile and sector weights but keeps the
holdings list on Ultimate; Alpha Vantage's ETF profile carries the list on
the reader's own key. The first answer keeps its profile and descriptions,
the list comes from the second, and `holdings_vendor` names it so the panel
can say where each part came from.
"""

from __future__ import annotations


def fund_profile(symbol: str) -> dict:
    from alphadesk.providers import get_prices
    router = get_prices()
    sym = symbol.upper()
    out = dict(router.ask("fund_holdings", sym))
    out["vendor"] = router.answered_by
    if not out.get("holdings"):
        for name, other in router.ask_others("fund_holdings", sym, skip=out["vendor"]):
            if not other.get("holdings"):
                continue
            out["holdings"] = other["holdings"]
            out["top_weight"] = other.get("top_weight")
            out["holdings_vendor"] = name
            out["holdings_needs_key"] = None
            # The second answer fills only what the first left empty.
            for k in ("sectors", "expense_ratio", "net_assets", "as_of"):
                if not out.get(k) and other.get(k):
                    out[k] = other[k]
            break
    return out
