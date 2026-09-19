"""The option chain's row join, vendor-neutral (2026-09-13). The chain itself
is fetched by the user's own vendor (providers/alpaca.py); what stays here is
the rule set every chain passes through: contract metadata joined to its
quote, a mid only when both sides quote, both sides in strike order.
"""


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _merge(contracts, snaps) -> tuple[list[dict], list[dict]]:
    """Join contract metadata to its quote, split by side, sort by strike.

    Split out from the fetch so the rules that matter are testable without a
    network client: that a one-sided book yields no mid, and that both sides
    come back in strike order.

    A snapshot is Alpaca's REST shape (`latestQuote`, `latestTrade`,
    `dailyBar`, `greeks`, `impliedVolatility`). The day's volume counts only
    when the contract's daily bar is from the chain's latest session: a
    contract that has not traded since last week carries last week's bar.
    """
    calls: list[dict] = []
    puts: list[dict] = []
    session = max((((s or {}).get("dailyBar") or {}).get("t") or "")[:10] for s in snaps.values()) if snaps else ""
    for c in contracts:
        occ = getattr(c, "symbol", "")
        snap = (snaps.get(occ) if snaps else None) or {}
        q = snap.get("latestQuote") or {}
        t = snap.get("latestTrade") or {}
        bar = snap.get("dailyBar") or {}
        prev = snap.get("prevDailyBar") or {}
        g = snap.get("greeks") or {}
        bid, ask, last = _num(q.get("bp")), _num(q.get("ap")), _num(t.get("p"))
        iv = _num(snap.get("impliedVolatility"))
        prev_close = _num(prev.get("c"))
        today = (bar.get("t") or "")[:10] == session and bool(session)
        row = {
            "symbol": occ,
            "strike": float(getattr(c, "strike_price", 0) or 0),
            "bid": round(float(bid), 2) if bid is not None else None,
            "ask": round(float(ask), 2) if ask is not None else None,
            "last": round(float(last), 2) if last else None,
            # Midpoint only when BOTH sides quote. One-sided books are common
            # far from the money, and a mid computed off a single side is a made
            # up price rather than a wide one.
            "mid": round((float(bid) + float(ask)) / 2, 2)
                   if bid is not None and ask is not None else None,
            "open_interest": int(getattr(c, "open_interest", 0) or 0),
            "bid_size": int(q["bs"]) if q.get("bs") is not None else None,
            "ask_size": int(q["as"]) if q.get("as") is not None else None,
            "volume": int(bar.get("v") or 0) if today else 0,
            "change_pct": round((last - prev_close) / prev_close * 100, 2) if last and prev_close else None,
            "implied_volatility": round(iv * 100, 1) if iv else None,
            **{k: (round(_num(g.get(k)), 4) if _num(g.get(k)) is not None else None)
               for k in ("delta", "gamma", "theta", "vega", "rho")},
        }
        side = str(getattr(c, "type", "")).lower()
        (calls if "call" in side else puts).append(row)
    calls.sort(key=lambda r: r["strike"])
    puts.sort(key=lambda r: r["strike"])
    return calls, puts

