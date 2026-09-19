"""Institutional ownership of ONE symbol from the user's own vendors
(2026-09-13 — the Nasdaq route and the Yahoo holder table are gone). Every
source is a paid plan; without one the panels show the key that would fill
them. The shape is the one the ownership panels render; a summary figure a
vendor does not report stays absent, never estimated.
"""

from __future__ import annotations


def institutional_holdings(symbol: str, limit: int = 25) -> dict:
    from alphadesk.providers import get_prices
    router = get_prices()
    out = dict(router.ask("institutional_ownership", symbol.upper()))
    out["holders"] = list(out.get("holders") or [])[:limit]
    out["source"] = out.get("source") or router.answered_by
    return out


def top_holders(symbol: str) -> dict:
    """The older ownership tile's shape, from the same record."""
    got = institutional_holdings(symbol, 10)
    return {"symbol": got["symbol"], "breakdown": got.get("summary") or {},
            "top_holders": [{"holder": h.get("name"), "shares": h.get("shares"), "value": h.get("value"),
                             "pct_change": h.get("change_pct"), "date_reported": h.get("date")}
                            for h in got["holders"]]}
