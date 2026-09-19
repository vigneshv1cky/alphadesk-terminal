"""The Sectors page's figures (2026-09-15): the S&P sector funds and a set of
industry-group funds, each with its trailing returns, where it sits in its
52-week range, today's dollars traded, and its return relative to SPY.

Funds stand in for the sectors for the same reason Market ETFs stand in for
the indices: a sector index level is licensed data no connected vendor
carries, while the funds trade on the tape.

One request for every fund on the page rather than a chart request per
fund: the reader's daily bars for all of them at once (Alpaca answers ~30
symbols in about half a second) and one batch of quotes for today. Cached
per reader, like every other vendor figure (invariant 8).
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

BENCHMARK = "SPY"

# The eleven GICS sectors, as State Street's Select Sector funds.
SECTORS: tuple[tuple[str, str], ...] = (
    ("XLK", "Technology"), ("XLF", "Financials"), ("XLV", "Health care"), ("XLY", "Consumer discretionary"),
    ("XLC", "Communication services"), ("XLI", "Industrials"), ("XLP", "Consumer staples"), ("XLE", "Energy"),
    ("XLU", "Utilities"), ("XLRE", "Real estate"), ("XLB", "Materials"),
)

# Each sector fund's sector as FMP names it (weights, company screener).
FMP_SECTOR = {
    "XLK": "Technology", "XLF": "Financial Services", "XLV": "Healthcare", "XLY": "Consumer Cyclical",
    "XLC": "Communication Services", "XLI": "Industrials", "XLP": "Consumer Defensive", "XLE": "Energy",
    "XLU": "Utilities", "XLRE": "Real Estate", "XLB": "Basic Materials",
}

# A level below: the industry groups that move on their own stories.
INDUSTRIES: tuple[tuple[str, str], ...] = (
    ("SMH", "Semiconductors"), ("IGV", "Software"), ("KRE", "Regional banks"), ("KBE", "Banks"),
    ("XBI", "Biotech"), ("IHI", "Medical devices"), ("ITB", "Homebuilders"), ("XRT", "Retail"),
    ("IYT", "Transports"), ("JETS", "Airlines"), ("ITA", "Aerospace & defense"), ("XOP", "Oil & gas producers"),
    ("OIH", "Oil services"), ("GDX", "Gold miners"), ("XME", "Metals & mining"), ("TAN", "Solar"),
    ("URA", "Uranium"), ("KWEB", "China internet"),
)

# Sessions of daily bars: a year and a little, for the 1Y base and the range.
SESSIONS = 260
TTL_S = 60

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _close_on_or_before(days: list[tuple[date, float]], when: date) -> Optional[float]:
    base = None
    for d, c in days:
        if d > when:
            break
        base = c
    return base


def _ret(last: Optional[float], base: Optional[float]) -> Optional[float]:
    return round((last / base - 1) * 100, 2) if last is not None and base else None


def fund_row(symbol: str, label: str, bars: list[dict], quote: Optional[dict], today: date,
             bench: Optional[dict] = None) -> dict:
    """One fund's figures from its daily bars (oldest first, Alpaca's shape)
    and today's quote. Returns are from the last close — the live price when
    the quote has one — to the close on or before the same day a week, a
    month (30 days), three months (91 days) and a year back, and to the
    previous year's last close for YTD. Relative figures subtract the
    benchmark's same return. Pure."""
    days = sorted((b["ts"].date() if isinstance(b["ts"], datetime) else date.fromisoformat(str(b["ts"])[:10]), b["close"])
                  for b in bars if b.get("close"))
    q = quote or {}
    last = q.get("price") or (days[-1][1] if days else None)
    base = lambda n: _close_on_or_before(days, today - timedelta(days=n))  # noqa: E731
    ytd_base = _close_on_or_before(days, date(today.year - 1, 12, 31))
    highs = [b.get("high") or b["close"] for b in bars if b.get("close")]
    lows = [b.get("low") or b["close"] for b in bars if b.get("close")]
    bases = {"w1": base(7), "m1": base(30), "m3": base(91), "ytd": ytd_base, "y1": base(365)}
    prev = q.get("previous_close")
    if prev is None and q.get("price") and q.get("change_pct") is not None and q["change_pct"] > -100:
        prev = q["price"] / (1 + q["change_pct"] / 100)
    row = {
        "symbol": symbol, "label": label, "name": q.get("name"),
        "price": last, "change_pct": q.get("change_pct"),
        # The closes the returns run from, so a page with live prices can
        # move every return with the price instead of only the day's change.
        "bases": {**bases, "d1": prev},
        "w1": _ret(last, base(7)), "m1": _ret(last, base(30)), "m3": _ret(last, base(91)),
        "ytd": _ret(last, ytd_base), "y1": _ret(last, base(365)),
        "high_52w": max(highs) if highs else None, "low_52w": min(lows) if lows else None,
        "turnover": (last or 0) * (q.get("volume") or 0) or None,
    }
    for k in ("m1", "m3"):
        b = (bench or {}).get(k)
        row[f"rel_{k}"] = round(row[k] - b, 2) if row[k] is not None and b is not None else None
    return row


def rotation(rel_m1: Optional[float], rel_m3: Optional[float]) -> Optional[str]:
    """Where a group stands against the market, from its return relative to
    SPY over three months (the trend) and one month (the latest turn):
    leading (ahead on both), weakening (ahead over three months, behind over
    one), lagging (behind on both), improving (behind over three, ahead over
    one). A description of the two numbers, not a forecast. Pure."""
    if rel_m1 is None or rel_m3 is None:
        return None
    if rel_m3 >= 0:
        return "leading" if rel_m1 >= 0 else "weakening"
    return "improving" if rel_m1 >= 0 else "lagging"


def sectors() -> dict:
    """{benchmark, sectors, industries, as_of}. NeedsKey when no connected
    vendor carries daily bars."""
    from alphadesk.config import ET
    from alphadesk.providers import get_prices
    router = get_prices()
    key = f"{router.owner}|{','.join(router.connected)}"
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    groups = {"sectors": SECTORS, "industries": INDUSTRIES}
    syms = [BENCHMARK] + [s for g in groups.values() for s, _ in g]
    bars = router.ask("daily_history", syms, SESSIONS) or {}
    try:
        quotes = router.get("quotes", syms) or {}
    except Exception:                          # returns still stand on the closes
        quotes = {}
    today = datetime.now(ET).date()
    bench = fund_row(BENCHMARK, "S&P 500", bars.get(BENCHMARK) or [], quotes.get(BENCHMARK), today)
    out: dict = {"benchmark": bench, "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "source": router.answered_by, "weights": sector_weights(router)}
    for name, group in groups.items():
        rows = []
        for sym, label in group:
            row = fund_row(sym, label, bars.get(sym) or [], quotes.get(sym), today, bench)
            row["rotation"] = rotation(row["rel_m1"], row["rel_m3"])
            rows.append(row)
        out[name] = rows
    with _lock:
        _cache[key] = (time.time(), out)
    return out


_daily: dict[str, tuple[float, object]] = {}
DAILY_KEEP_S = 86400
# Companies counted for breadth and leaders: large enough to trade on the
# consolidated tape every day.
MIN_MARKET_CAP = 2e9
LEADERS = 10


def _kept_daily(router, name: str, fetch):
    """A reader's slow-moving vendor answer, kept a day (a missing one is
    asked again after ten minutes, so a key added later is noticed)."""
    key = f"{router.owner}|{','.join(router.connected)}|{name}"
    with _lock:
        hit = _daily.get(key)
    if hit and time.time() - hit[0] < (DAILY_KEEP_S if hit[1] is not None else 600):
        return hit[1]
    try:
        got = fetch()
    except Exception:
        got = None
    with _lock:
        _daily[key] = (time.time(), got)
    return got


def sector_weights(router) -> Optional[dict]:
    """{sector fund: its share of the S&P 500, percent}, or None when no
    connected vendor carries sector weights."""
    raw = _kept_daily(router, "weights", lambda: router.get("sector_weights"))
    if not raw:
        return None
    return {fund: raw[name] for fund, name in FMP_SECTOR.items() if name in raw}


def breadth_and_leaders(companies: list[dict], changes: dict[str, dict]) -> dict:
    """Per sector fund: how many of the sector's companies are up, down and
    unchanged today (only those with a change), and its LEADERS largest
    companies by market cap with today's price and change. Pure."""
    by_fund = {name: fund for fund, name in FMP_SECTOR.items()}
    out = {fund: {"up": 0, "down": 0, "flat": 0, "companies": 0, "leaders": [], "drivers": []} for fund in FMP_SECTOR}
    # One listing per company. The S&P list gives each share class its own
    # row under one SEC CIK (GOOG and GOOGL); the screener lists classes and
    # some exchange-traded notes under the company's name (BRK-A and BRK-B;
    # SOJE beside SO). Counted per listing, a company counted twice and bonds
    # led a sector. The listing with the most dollars traded today stands, or
    # the most traded on average without today's figure.
    def traded(c: dict) -> float:
        return (changes.get(c["symbol"]) or {}).get("turnover") or c.get("avg_volume") or 0

    one: dict[str, dict] = {}
    for c in companies:
        key = str(c.get("cik") or (c.get("name") or c["symbol"]).strip().lower())
        kept = one.get(key)
        if kept is None or traded(c) > traded(kept):
            one[key] = c
    for c in sorted(one.values(), key=lambda c: -(c.get("market_cap") or 0)):
        fund = by_fund.get(c.get("sector"))
        if not fund:
            continue
        g = out[fund]
        g["companies"] += 1
        ch = changes.get(c["symbol"]) or {}
        pct = ch.get("change_pct")
        entry = {"symbol": c["symbol"], "name": c.get("name"), "industry": c.get("industry"),
                 "market_cap": c.get("market_cap"), "price": ch.get("price"), "change_pct": pct,
                 "value_change": value_change(c.get("market_cap"), pct)}
        if pct is not None:
            g["up" if pct > 0 else "down" if pct < 0 else "flat"] += 1
            if entry["value_change"] is not None:
                g["drivers"].append(entry)
        if len(g["leaders"]) < LEADERS:
            g["leaders"].append(entry)
    # The companies that moved the sector most in market value today, either
    # way: a $5T company up 0.4% adds more than a $5B one up 20%.
    for g in out.values():
        g["drivers"] = sorted(g["drivers"], key=lambda e: -abs(e["value_change"]))[:LEADERS]
    return out


def value_change(market_cap: Optional[float], change_pct: Optional[float]) -> Optional[float]:
    """The market value a company added (or lost) today, in dollars, from its
    market cap now and today's change: cap − cap / (1 + change). Pure."""
    if not market_cap or change_pct is None or change_pct <= -100:
        return None
    return round(market_cap - market_cap / (1 + change_pct / 100))


def sp500_companies(router) -> Optional[list[dict]]:
    """The S&P 500's members with market caps (2026-09-15): breadth and
    leaders describe the same companies as the sector funds, which hold only
    S&P members. The US screener over $2B counted 271 technology companies
    against the index's 85 listings. Members and caps are kept a day; caps
    come in one batch, since 25 members registered abroad (LIN, MDT, ACN…)
    are missing from the US screener. None without a vendor that lists
    members."""
    members = _kept_daily(router, "sp500", lambda: router.get("sp500_constituents"))
    if not members:
        return None
    caps = _kept_daily(router, "sp500_caps", lambda: router.get("market_caps", [m["symbol"] for m in members])) or {}
    return [{**m, "market_cap": caps.get(m["symbol"])} for m in members]


def latest_session(changes: dict[str, dict]) -> Optional[str]:
    """The trading day most of today's changes come from — the latest session
    that at least a tenth of the companies traded in, so a handful of early
    prints do not call the day open for the rest. Pure."""
    from collections import Counter
    counts = Counter(c.get("session") for c in changes.values() if c.get("session"))
    if not counts:
        return None
    total = sum(counts.values())
    for day in sorted(counts, reverse=True):
        if counts[day] * 10 >= total:
            return day
    return max(counts)


def breadth() -> dict:
    """{groups: {sector fund: {up, down, flat, companies, leaders, drivers}},
    universe, session, as_of}. The companies are the S&P 500's members
    (sp500_companies), or the US companies over $2B from the reader's screener
    when no vendor lists members; today's changes come from their quote vendor
    in one pass. NeedsKey when neither list is carried."""
    from alphadesk.providers import get_prices
    from alphadesk.providers.base import NeedsKey
    router = get_prices()
    key = f"{router.owner}|{','.join(router.connected)}|breadth"
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    companies, universe = sp500_companies(router), "S&P 500 companies"
    if not companies:
        companies = _kept_daily(router, "companies", lambda: router.get("sector_companies", MIN_MARKET_CAP))
        universe = f"US companies over ${MIN_MARKET_CAP / 1e9:g}B"
    if not companies:
        raise NeedsKey("sp500", [], signed_in=router.owner is not None)
    changes = router.ask("day_changes", [c["symbol"] for c in companies]) or {}
    from alphadesk.config import ET
    session = latest_session(changes)
    out = {"groups": breadth_and_leaders(companies, changes), "min_market_cap": MIN_MARKET_CAP, "universe": universe,
           # Before the day's first trades every company's "today" is its last
           # session; the page says so rather than showing yesterday as today.
           "session": session, "session_is_today": session == datetime.now(ET).date().isoformat(),
           "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def reset_cache() -> None:
    with _lock:
        _cache.clear()
        _daily.clear()
