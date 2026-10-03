"""The facts a person weighs before entering a position (2026-10-03): how wide
the spread is, how much trades, where the day's levels sit, what could cap or
gap the price, and whether it can be traded or sold short at all. Plain
measurements and arithmetic on what the reader supplies — no entry, exit,
target or sizing advice, and NO ORDER IS EVER PLACED from here.
"""

from __future__ import annotations

from statistics import median


def spread(bid, ask) -> dict | None:
    """The quoted spread, absolute and as a share of the midpoint."""
    if not bid or not ask or ask < bid:
        return None
    mid = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "spread": round(ask - bid, 4), "spread_pct": round(100 * (ask - bid) / mid, 3)}


def liquidity(daily: list[dict], last_price: float | None, today_volume: float | None = None, sessions: int = 20) -> dict:
    """Typical traded volume from the last `sessions` completed daily bars."""
    rows = [b for b in daily if b.get("c") and b.get("v")][-sessions:]
    vols = [b["v"] for b in rows]
    dollars = [b["v"] * b["c"] for b in rows]
    med_v = median(vols) if vols else None
    return {"sessions_measured": len(rows),
            "median_daily_shares": med_v,
            "median_daily_dollars": round(median(dollars)) if dollars else None,
            "today_volume": today_volume,
            "today_vs_median": round(today_volume / med_v, 2) if today_volume and med_v else None,
            # How far one position of N shares would reach into a normal day's
            # trading: shares per 1% of the median day.
            "shares_per_1pct_of_median_day": int(med_v / 100) if med_v else None}


def vwap(bars: list[dict]) -> float | None:
    """Volume-weighted average price of the given intraday bars."""
    num = sum(((b.get("h") or b["c"]) + (b.get("l") or b["c"]) + b["c"]) / 3 * (b.get("v") or 0) for b in bars if b.get("c"))
    den = sum(b.get("v") or 0 for b in bars if b.get("c"))
    return round(num / den, 4) if den else None


def levels(last: float | None, **named) -> dict:
    """Each named level with the last price's distance from it, in percent
    (positive: the last price is above the level)."""
    out = {}
    for name, level in named.items():
        if level:
            out[name] = {"price": round(level, 4), "last_vs_level_pct": round(100 * (last / level - 1), 2) if last else None}
    return out


def size_for(price: float | None, risk_dollars: float | None, stop_pct: float | None) -> dict | None:
    """Pure arithmetic on numbers the caller supplied: the share count at which
    a move of `stop_pct` from `price` costs `risk_dollars`. Not a
    recommendation of either number."""
    if not price or not risk_dollars or not stop_pct or price <= 0 or stop_pct <= 0 or risk_dollars <= 0:
        return None
    per_share = price * stop_pct / 100
    shares = int(risk_dollars // per_share)
    return {"risk_dollars": risk_dollars, "stop_distance_pct": stop_pct, "loss_per_share": round(per_share, 4),
            "shares": shares, "position_dollars": round(shares * price, 2)}
