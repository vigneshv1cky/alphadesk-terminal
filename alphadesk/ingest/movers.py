"""Market movers by CATEGORY, from the user's own vendors (2026-09-13 — the
Yahoo screeners, the keyless CoinGecko page and the fixed Yahoo universes
are gone).

Every category answers the same shape so one tile draws all of them:

    {category, label, change_label, source, note, floors, as_of,
     tabs: [{id, label, rows: [{symbol, display, name, price, change_pct,
                                volume, turnover, volatility, liquidity}]}]}

Where the rows come from:

  stocks      the user's screener vendor: Alpaca's most active and day's
              gainers and losers (free key), or Polygon's full snapshot.
  etfs        a broad list of the most traded ETFs priced on the user's
              quote vendor (Alpaca), or Polygon's snapshot.
  indices     market ETFs standing in for the indices — an index level is
              licensed data no free key carries — labelled as the funds.
  crypto      CoinGecko by market cap on the user's key, or Alpaca's coins.
  currencies  Polygon's forex snapshot (paid).
  options     Polygon's option snapshots, busiest contracts (paid).
  bonds       the US Treasury's daily par yield curve — public government
              data, keyless, the change in basis points.

Twenty-session volatility and average dollar volume come from the user's
daily bars (one request for the whole list). The reader's floors apply on
top. A category no connected vendor serves raises NeedsKey and the tile
shows the key that would fill it. Payloads are cached per user — one user's
keyed answer is never served to another — and rebuilt behind the cached
copy once past their lifetime.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
import threading
import time
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Optional

from alphadesk.providers.base import NeedsKey

log = logging.getLogger("alphadesk.movers")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}

CATEGORIES: dict[str, str] = {
    "stocks": "Stocks", "etfs": "ETFs", "indices": "Market ETFs", "crypto": "Crypto",
    "currencies": "Currencies", "options": "Options", "bonds": "Treasury yields",
}
CHANGE_LABEL = {"crypto": "24h", "bonds": "1D bp"}

TTL_S = {"stocks": 30, "crypto": 30, "indices": 30, "etfs": 60, "currencies": 120, "options": 120, "bonds": 900}
# CoinGecko's free Demo key allows 10,000 calls a month; rebuilding every 30s
# while a tab is open eight hours a day spends ~21,000. Its payload is kept
# two minutes instead (~5,000).
SOURCE_TTL_S = {"coingecko": 120}
# How long a request past the lifetime waits for the rebuild before it takes
# the old payload (2026-09-15). Handing the old copy back at once and
# rebuilding behind it meant the tile, which asks every 30 seconds, showed a
# list a whole cycle late: measured at 61 seconds old on arrival while
# Alpaca's screener had updated 30 seconds before. A rebuild takes 0.2-1.1s.
# How long a request waits for a stale list's refresh before answering with
# the previous one. It was 2.0: any visit more than a category's TTL after
# the last one sat for the whole refresh — measured 1.5s for stock movers and
# 1.1s for ETFs on every return to Markets (2026-09-16). A list half a
# minute old answers at once; a fast vendor still lands inside this window,
# and a slow one's rebuild is there for the tile's next poll.
REFRESH_WAIT_S = 0.25
# A list the vendor marked as still filling in (Alpaca's gainers and losers
# before the dollar-volume pool is first built, 2026-09-17) is kept this long
# instead of the category's lifetime, so the full list replaces it in seconds.
FILLING_TTL_S = 3

STATS_DAYS = 20
STOCK_MIN_PRICE = 5.0
STOCK_MIN_TURNOVER = 1_000_000

DEFAULT_FLOORS: dict[str, tuple[float, float]] = {
    "stocks": (STOCK_MIN_PRICE, STOCK_MIN_TURNOVER), "etfs": (STOCK_MIN_PRICE, STOCK_MIN_TURNOVER),
    "crypto": (0.0, STOCK_MIN_TURNOVER), "options": (0.0, 0.0), "indices": (0.0, 0.0),
    "bonds": (0.0, 0.0), "currencies": (0.0, 0.0),
}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _row(symbol: str, price, change_pct, volume=None, name: str | None = None, display: str | None = None,
         turnover_is_volume: bool = False) -> dict:
    chg = _f(change_pct)
    p, v = _f(price), int(_f(volume) or 0)
    return {"symbol": symbol, "display": display or symbol, "name": name,
            "price": p, "change_pct": round(chg, 2) if chg is not None else None,
            "volume": v, "turnover": (v if turnover_is_volume else (p or 0) * v),
            "volatility": None, "liquidity": None, "spark": []}


def tabs_from_list(rows: list[dict], with_active: bool = True) -> list[dict]:
    """The list as given, then by volume, then by change either way. Pure."""
    priced = [r for r in rows if r["price"] is not None]
    tabs: list[dict] = [{"id": "all", "label": "All", "rows": priced}]
    if with_active and any(r["volume"] for r in priced):
        tabs.append({"id": "most_active", "label": "Active", "rows": sorted(priced, key=lambda r: -r["volume"])})
    changed = [r for r in priced if r["change_pct"] is not None]
    tabs.append({"id": "gainers", "label": "Gainers", "rows": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])})
    tabs.append({"id": "losers", "label": "Losers", "rows": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])})
    return tabs


def periods_a_year(dates: list[str]) -> int:
    """How many bars a year a daily series has, read from its own dates:
    currencies trade from Sunday evening to Friday, so a year is neither 252
    sessions nor 365 days. 252 when the dates cannot tell. Pure."""
    ds = sorted(date.fromisoformat(d[:10]) for d in dates if d)
    span = (ds[-1] - ds[0]).days if len(ds) > 1 else 0
    return round(365 * (len(ds) - 1) / span) if span > 0 else 252


def stats_from_bars(closes: list[float], volumes: list[float], periods: int = 252) -> dict:
    """{volatility, liquidity} from daily closes and volumes, oldest first.
    Volatility is the annualised standard deviation of daily log returns
    over the last STATS_DAYS sessions, in percent, None under six returns —
    annualised over `periods` a year: 252 sessions for stocks, 365 days for
    coins, which trade every day;
    liquidity the mean of close × volume over the same window, None when
    there is no volume at all."""
    cs = [c for c in closes if c is not None and c > 0][-(STATS_DAYS + 1):]
    rets = [math.log(cs[i] / cs[i - 1]) for i in range(1, len(cs))]
    vol = None
    if len(rets) >= 6:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        vol = math.sqrt(var) * math.sqrt(periods) * 100
    pairs = [(c, v) for c, v in zip(closes, volumes) if c is not None and v is not None][-STATS_DAYS:]
    dollars = [c * v for c, v in pairs if v > 0]
    liq = (sum(dollars) / len(dollars)) if dollars else None
    return {"volatility": round(vol, 1) if vol is not None else None,
            "liquidity": round(liq) if liq is not None else None}


def _money(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:g}B"
    if v >= 1e6:
        return f"${v / 1e6:g}M"
    if v >= 1e3:
        return f"${v / 1e3:g}K"
    return f"${v:g}"


def floors_note(min_price: float, min_turnover: float, min_liquidity: float = 0.0, min_volatility: float = 0.0) -> Optional[str]:
    parts = []
    if min_price > 0:
        parts.append(f"≥ {_money(min_price)}")
    if min_turnover > 0:
        parts.append(f"≥ {_money(min_turnover)} turnover")
    if min_liquidity > 0:
        parts.append(f"liq ≥ {_money(min_liquidity)}")
    if min_volatility > 0:
        parts.append(f"vol ≥ {min_volatility:g}%")
    return " · ".join(parts) or None


def apply_floors(tabs: list[dict], min_price: float, min_turnover: float,
                 min_liquidity: float = 0.0, min_volatility: float = 0.0) -> None:
    """Drop, in place, every row under the floors. A row with no figure
    passes a floor of zero and fails any other — except a row whose volume
    the vendor sent and was discarded as a data error (`volume_suspect`): the
    turnover floor does not apply to it, so a coin is not dropped for the
    vendor's mistake."""
    if min_price <= 0 and min_turnover <= 0 and min_liquidity <= 0 and min_volatility <= 0:
        return
    for t in tabs:
        t["rows"] = [r for r in t["rows"]
                     if r["price"] is not None and r["price"] >= min_price
                     and (min_turnover <= 0 or r.get("volume_suspect") or (r.get("turnover") or 0) >= min_turnover)
                     and (min_liquidity <= 0 or (r.get("liquidity") or 0) >= min_liquidity)
                     and (min_volatility <= 0 or (r.get("volatility") or 0) >= min_volatility)]


# ── the one keyless category: Treasury yields ─────────────────────────────

_TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                 "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
_TREASURY_TTL_S = 3600
_treasury_cache: tuple[float, list[dict]] = (0.0, [])
_MATURITIES = {"1 Mo": "1-month bill", "2 Mo": "2-month bill", "3 Mo": "3-month bill", "6 Mo": "6-month bill",
               "1 Yr": "1-year", "2 Yr": "2-year note", "3 Yr": "3-year note", "5 Yr": "5-year note",
               "7 Yr": "7-year note", "10 Yr": "10-year note", "20 Yr": "20-year bond", "30 Yr": "30-year bond"}


def yield_volatility(yields: list[float]) -> float | None:
    """A yield's volatility in basis points a year: the standard deviation of
    its last STATS_DAYS daily changes, times the square root of 252 — the
    usual measure for rates, where a percentage of a percentage means
    little. None under six changes. Oldest first. Pure."""
    ys = [y for y in yields if y is not None][-(STATS_DAYS + 1):]
    ch = [(ys[i] - ys[i - 1]) * 100 for i in range(1, len(ys))]
    if len(ch) < 6:
        return None
    mean = sum(ch) / len(ch)
    var = sum((c - mean) ** 2 for c in ch) / (len(ch) - 1)
    return round(math.sqrt(var) * math.sqrt(252), 1)


def treasury_rows(csv_text: str) -> list[dict]:
    """The par yield curve CSV → one row per maturity: the latest yield, its
    change from the day before in basis points, and its volatility in basis
    points a year from the year's daily curve (2026-09-19). A point on the
    curve has no traded volume, so there is no liquidity. Pure."""
    days = list(csv.DictReader(io.StringIO(csv_text)))
    if len(days) < 1:
        return []
    days.sort(key=lambda r: datetime.strptime(r["Date"], "%m/%d/%Y"), reverse=True)
    last, prev = days[0], (days[1] if len(days) > 1 else {})
    out = []
    for col, label in _MATURITIES.items():
        y, p = _f(last.get(col)), _f(prev.get(col))
        if y is None:
            continue
        bp = round((y - p) * 100, 1) if p is not None else None
        history = [_f(d.get(col)) for d in reversed(days)]
        out.append({"symbol": f"UST{col.replace(' ', '').upper()}", "display": col, "name": label, "price": y,
                    "change_pct": bp, "volume": 0, "turnover": 0, "volatility": yield_volatility(history), "liquidity": None,
                    "spark": [], "as_of": datetime.strptime(last["Date"], "%m/%d/%Y").date().isoformat()})
    return out


def _treasury() -> dict:
    global _treasury_cache
    ts, rows = _treasury_cache
    if not rows or time.time() - ts > _TREASURY_TTL_S:
        year = date.today().year
        req = urllib.request.Request(_TREASURY_URL.format(year=year), headers={"User-Agent": "AlphaDesk/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            rows = treasury_rows(resp.read().decode("utf-8", "replace"))
        if len(rows) < 2 and date.today().month == 1:
            req = urllib.request.Request(_TREASURY_URL.format(year=year - 1), headers={"User-Agent": "AlphaDesk/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                rows = treasury_rows(resp.read().decode("utf-8", "replace"))
        _treasury_cache = (time.time(), rows)
    return {"tabs": tabs_from_list([dict(r) for r in rows], with_active=False), "source": "treasury"}


# ── assembly ──────────────────────────────────────────────────────────────


def _normalize_tabs(got: dict, category: str) -> list[dict]:
    coin = category == "crypto"
    tabs: list[dict] = []
    for t in got.get("tabs") or []:
        rows = []
        for r in t.get("rows") or []:
            row = _row(r["symbol"], r.get("price"), r.get("change_pct"), r.get("volume"), name=r.get("name"),
                       display=r.get("display") or (r["symbol"].split("-")[0] if coin else r["symbol"]),
                       # CoinGecko states volume in dollars; Alpaca's crypto
                       # volume is in coins, so its turnover is price × volume.
                       turnover_is_volume=bool(r.get("volume_is_dollars")))
            # An option row keeps its underlying and expiry: a click opens the
            # chain there, and without them the row opened nothing.
            for k in ("volatility", "liquidity", "open_interest", "underlying", "expiry", "volume_suspect"):
                if r.get(k) is not None:
                    row[k] = r[k]
            # A vendor's own figure wins: an option's premium, or the dollar
            # volume tab's volume × volume-weighted price.
            if r.get("turnover") is not None:
                row["turnover"] = r["turnover"]
            rows.append(row)
        tabs.append({"id": t["id"], "label": t["label"], "rows": rows})
    return tabs


def _enrich_stats(router, tabs: list[dict], category: str, venue: bool = False) -> None:
    if category == "crypto":
        _enrich_coins(router, tabs, venue)
        return
    if category == "currencies":
        _enrich_currencies(router, tabs)
        return
    if category not in ("stocks", "etfs", "indices"):
        return
    syms = sorted({r["symbol"] for t in tabs for r in t["rows"] if r.get("volatility") is None})
    if not syms:
        return
    bars = router.get("daily_history", syms, STATS_DAYS + 1) or {}
    for t in tabs:
        for r in t["rows"]:
            b = bars.get(r["symbol"])
            if b and r.get("volatility") is None:
                st = stats_from_bars([x["close"] for x in b], [x["volume"] for x in b])
                r["volatility"], r["liquidity"] = st["volatility"], st["liquidity"]


def only_tradable_coins(router, tabs: list[dict], got: dict) -> None:
    """With an Alpaca key connected, a crypto list from another vendor keeps
    only the coins that account can trade against the dollar (2026-09-19,
    the owner: "only show crypto I can trade in alpaca" — 29 of CoinGecko's
    top 47 were not on Alpaca and had no volatility either). Without Alpaca
    the list stands: nothing says what the reader can trade."""
    try:
        coins = router.get("crypto_symbols")
    except Exception:
        coins = None
    if not coins:
        return
    for t in tabs:
        t["rows"] = [r for r in t["rows"] if str(r.get("display") or r["symbol"].split("-")[0]).upper() in coins]
    got["note"] = "coins you can trade on Alpaca"


def _enrich_currencies(router, tabs: list[dict]) -> None:
    """A pair's volatility from its last twenty daily closes (2026-09-19),
    annualised by the bars a year its own dates show. No liquidity: currency
    trading has no consolidated volume, and a vendor's figure is its own
    feed's tick count."""
    pairs = sorted({r["symbol"] for t in tabs for r in t["rows"]})
    bars = (router.get("fx_daily_history", pairs, STATS_DAYS + 1) or {}) if pairs else {}
    for t in tabs:
        for r in t["rows"]:
            b = bars.get(r["symbol"])
            if b and r.get("volatility") is None:
                r["volatility"] = stats_from_bars([x["close"] for x in b], [None] * len(b),
                                                  periods=periods_a_year([x["date"] for x in b]))["volatility"]


def _enrich_coins(router, tabs: list[dict], venue: bool) -> None:
    """Coins' volatility and liquidity (2026-09-19, the owner's request).
    Volatility from the last twenty DAILY closes, annualised over 365 days.
    Liquidity: a vendor whose volume is worldwide dollars (CoinGecko) keeps
    its 24-hour turnover; a venue's (Alpaca, `venue`) is the twenty-day mean
    of close × volume ON THAT VENUE — Bitcoin about $1.2M a day there against
    tens of billions worldwide, so the payload marks it and the column says
    so (the owner's pick of three, 2026-09-19: fill it, labelled)."""
    syms = sorted({r["symbol"] for t in tabs for r in t["rows"]})
    bars = (router.get("crypto_daily_history", syms, STATS_DAYS + 1) or {}) if syms else {}
    for t in tabs:
        for r in t["rows"]:
            b = bars.get(r["symbol"])
            st = stats_from_bars([x["close"] for x in b], [x["volume"] for x in b], periods=365) if b else {}
            if r.get("volatility") is None:
                r["volatility"] = st.get("volatility")
            if venue:
                r["liquidity"] = st.get("liquidity")
            elif r.get("liquidity") is None:
                r["liquidity"] = r["turnover"] or None


# ── funds and stocks ──────────────────────────────────────────────────────

# Words a fund's own name carries when no fund list is at hand. The list is
# FMP's (etf_symbols); this is the fallback for a reader without it, and it
# errs toward calling a fund a stock: "Invesco QQQ Trust, Series 1" says
# neither ETF nor fund, so the fund families are named too.
_FUND_NAME = re.compile(
    r"\b(ETF|ETN|ETP)s?\b|\bTrust,? Series\b|^(iShares|SPDR|State Street SPDR|Vanguard|ProShares|Direxion|"
    r"GraniteShares|Tradr|Defiance|T-Rex|Leverage Shares|YieldMax|Roundhill|Grayscale|MicroSectors)\b",
    re.IGNORECASE)

_fund_lists: dict[str, tuple[float, Optional[frozenset[str]]]] = {}
FUND_LIST_KEEP_S = 86400
FUND_LIST_RETRY_S = 600


def fund_list(router) -> Optional[frozenset[str]]:
    """The reader's vendor's list of fund symbols, or None when no connected
    vendor carries one. Kept a day per reader; a missing list is asked
    again after ten minutes, so a key added later is noticed."""
    owner = router.owner or ""
    with _lock:
        hit = _fund_lists.get(owner)
    if hit and time.time() - hit[0] < (FUND_LIST_KEEP_S if hit[1] is not None else FUND_LIST_RETRY_S):
        return hit[1]
    try:
        got = router.get("etf_symbols")
    except Exception as exc:                 # a vendor failure is not a verdict
        log.debug("fund list: %s", exc)
        return hit[1] if hit else None
    got = frozenset(got) if got else None
    with _lock:
        _fund_lists[owner] = (time.time(), got)
    return got


def is_fund(row: dict, funds: Optional[frozenset[str]]) -> bool:
    """Whether a movers row is a fund: by the vendor's list when there is
    one, by its name otherwise."""
    if funds is not None:
        return row["symbol"].upper() in funds
    return bool(_FUND_NAME.search(row.get("name") or ""))


def split_funds(tabs: list[dict], keep: str, funds: Optional[frozenset[str]]) -> None:
    """In place: `keep` "only" leaves the funds, "exclude" the rest (2026-09-15
    — Alpaca's most-active list mixed leveraged ETFs in with stocks, about
    half its rows). Order is kept. Pure given `funds`."""
    for t in tabs:
        t["rows"] = [r for r in t["rows"] if is_fund(r, funds) == (keep == "only")]


def _build(router, key: str, cat: str, top: int, mp: float, ml_floor: tuple[Optional[float], float, float]) -> dict:
    from alphadesk.providers.catalogue import MOVER_SURFACE
    mt_asked, ml, mv = ml_floor
    d_price, d_turn = DEFAULT_FLOORS.get(cat, (0.0, 0.0))
    if cat == "bonds":
        got = _treasury()
        source = "treasury"
        tabs = got["tabs"]
    else:
        got = router.ask("category_movers", cat, max(top, 50), surface=MOVER_SURFACE[cat])
        source = got.get("source") or router.answered_by
        tabs = _normalize_tabs(got, cat)
        if got.get("funds") in ("only", "exclude"):
            split_funds(tabs, got["funds"], fund_list(router))
        if cat == "crypto" and source != "alpaca":
            only_tradable_coins(router, tabs, got)
    # A vendor whose volume is one venue's (Alpaca's crypto: Bitcoin about
    # $1.2M a day there, 2026-09-15) cannot meet a market-wide turnover
    # floor — the default $1M left Crypto movers one row. Its default is
    # none. Its liquidity is the venue's own twenty-day figure, marked as
    # such (`liquidity_scope`, 2026-09-19) — not its one-day turnover.
    venue = bool(isinstance(got, dict) and got.get("venue_volume"))
    if venue:
        d_turn = 0.0
    mt = d_turn if mt_asked is None else mt_asked
    apply_floors(tabs, mp, mt)
    for t in tabs:
        t["rows"] = t["rows"][:max(top, 50) if (ml > 0 or mv > 0) else top]
    _enrich_stats(router, tabs, cat, venue)
    apply_floors(tabs, 0.0, 0.0, ml, mv)
    for t in tabs:
        t["rows"] = t["rows"][:top]
    result = {"category": cat, "label": CATEGORIES[cat], "change_label": CHANGE_LABEL.get(cat, "1D"),
              "source": source, "filling": bool(isinstance(got, dict) and got.get("filling")), "note": got.get("note") if isinstance(got, dict) else None,
              "floors": {"min_price": mp, "min_turnover": mt, "min_liquidity": ml, "min_volatility": mv,
                         "default_min_price": d_price, "default_min_turnover": d_turn},
              "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tabs": tabs}
    if venue:
        result["liquidity_scope"] = "venue"
    if result["note"] is None:
        result["note"] = floors_note(mp, mt, ml, mv)
    with _lock:
        if len(_cache) > 2048:
            _cache.clear()
        _cache[key] = (time.time(), result)
    return result


def _refresh_async(router, key: str, cat: str, top: int, mp: float,
                   floors: tuple[float, float, float]) -> threading.Event:
    """Rebuild `key` on a thread; the event is set when it is done, whether
    it succeeded or not. A rebuild already running is joined, not repeated."""
    with _lock:
        running = _inflight.get(key)
        if running is not None:
            return running
        done = _inflight[key] = threading.Event()

    def run() -> None:
        try:
            _build(router, key, cat, top, mp, floors)
        except Exception as exc:          # a failed rebuild keeps the stale payload
            log.warning("%s movers refresh failed: %s", cat, exc)
        finally:
            with _lock:
                _inflight.pop(key, None)
            done.set()

    threading.Thread(target=run, name=f"movers-{cat}", daemon=True).start()
    return done


def category_movers(category: str, top: int = 20, min_price: Optional[float] = None,
                    min_turnover: Optional[float] = None, min_liquidity: Optional[float] = None,
                    min_volatility: Optional[float] = None) -> dict:
    """KeyError for an unknown category; NeedsKey when no connected vendor
    serves it. The router is resolved on the request and handed to any
    background rebuild — a thread does not inherit the request's user."""
    from alphadesk.providers import get_prices
    cat = (category or "").strip().lower()
    if cat not in CATEGORIES:
        raise KeyError(cat)
    router = get_prices()
    top = max(1, min(int(top), 50))
    d_price, d_turn = DEFAULT_FLOORS.get(cat, (0.0, 0.0))
    mp = max(0.0, float(min_price)) if min_price is not None else d_price
    # None = the category's default, settled in _build: a vendor whose volume
    # is one venue's gets none (see _build).
    mt: Optional[float] = max(0.0, float(min_turnover)) if min_turnover is not None else None
    ml = max(0.0, float(min_liquidity or 0.0))
    mv = max(0.0, float(min_volatility or 0.0))
    owner = "public" if cat == "bonds" else router.owner
    key = f"{owner}|{','.join(router.connected)}|{cat}:{top}:{mp:g}:{'d' if mt is None else f'{mt:g}'}:{ml:g}:{mv:g}"
    with _lock:
        hit = _cache.get(key)
    if hit:
        ttl = max(TTL_S.get(cat, 60), SOURCE_TTL_S.get(hit[1].get("source") or "", 0))
        if hit[1].get("filling"):
            ttl = FILLING_TTL_S
        if time.time() - hit[0] >= ttl:
            # Wait briefly for the fresh list; a slow vendor still gets the
            # old one, and the rebuild lands for the next ask.
            if _refresh_async(router, key, cat, top, mp, (mt, ml, mv)).wait(REFRESH_WAIT_S):
                with _lock:
                    hit = _cache.get(key, hit)
        return hit[1]
    return _build(router, key, cat, top, mp, (mt, ml, mv))


def reset_cache() -> None:
    global _treasury_cache
    with _lock:
        _cache.clear()
        _fund_lists.clear()
    _treasury_cache = (0.0, [])


__all__ = ["CATEGORIES", "DEFAULT_FLOORS", "NeedsKey", "apply_floors", "category_movers", "floors_note",
           "stats_from_bars", "tabs_from_list", "treasury_rows"]
