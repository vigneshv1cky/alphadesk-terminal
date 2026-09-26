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

from alphadesk.config import session_label
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
            for k in ("volatility", "liquidity", "open_interest", "underlying", "expiry", "volume_suspect",
                      # A price struck outside the regular session, and the
                      # closed session's own move (2026-09-22).
                      "extended", "regular_pct", "extended_at"):
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
    # Which session the prices on this list were struck in (2026-09-22). The
    # figures move outside the regular session now, so the tile has to say
    # so: the change is measured from the last close, while the volume and
    # dollars traded beside it are still that closed session's.
    moment = session_label()
    extended = moment != "Open" and any(r.get("extended") for t in tabs for r in t["rows"])
    from alphadesk.providers.scraped import is_scraped
    result = {"category": cat, "label": CATEGORIES[cat], "change_label": CHANGE_LABEL.get(cat, "1D"),
              "extended": extended, "session_label": moment if extended else None,
              # Whether the vendor that answered is a keyed one or a scraped
              # source (2026-09-22): the tile says so, and so does the agent
              # tool, because a figure read off a public page must never pass
              # for one delivered under a licence.
              "official": not is_scraped(source),
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


# ── a past session's movers (2026-09-26, #87) ─────────────────────────────
#
# WHY THIS IS A SEPARATE PATH. Every vendor's movers endpoint answers "what
# is moving", present tense — Alpaca's screener and Polygon's snapshot both
# describe today and cannot be asked about the 24th. A past session has to
# be COMPUTED, from the whole market on that day against the session before
# it, which is why it needs `market_day` and why only a vendor that
# publishes a whole-market day can serve it at all.
#
# It is deliberately NOT threaded through category_movers(): that path is
# built for a 30-second cache and an async refresh because today's list
# changes under you. A past session cannot change, so it wants the opposite
# — fetch once, keep it for a long time, and never refresh in the
# background.
SESSION_CATEGORIES = ("stocks", "etfs")

# EXCHANGE TEST SYMBOLS. They print real prices and real volume and are not
# securities: ZVZZT closed at 25.12 with a 89% "gain" in the first list this
# produced, sitting third among the day's gainers. Nasdaq's test tickers all
# take the form Z?ZZT; the rest are named because they do not follow a rule.
_TEST_SYMBOL = re.compile(r"^Z[A-Z]ZZT$|^(ZEXIT|ZIEXT|ZTEST|ATEST|CTEST|CBO|CBX|IGZZT|LZZZT|NTEST)$")

# A move this big is either real or a basis error, and the difference is
# worth one market-wide lookup. Below it, nothing is fetched — the same
# rule keystats.py follows: pay for the explanation only where the
# arithmetic found a conflict.
_SPLIT_CHECK_PCT = 50.0
#: A finished session is finished. The only reason to re-read one is a
#: vendor restating it, which is rare enough to wait a day for.
SESSION_TTL_S = 21600
#: How many calendar days back to step looking for an open session before
#: giving up — a long weekend with a holiday either side is four.
_SESSION_LOOKBACK = 6


class VendorRefused(Exception):
    """The vendor was asked and would not answer — NOT an absence.

    Polygon's free plan allows five requests a minute and answers the sixth
    with 429. That arrived here as a None, which the router reads as "this
    vendor does not carry the surface", which became a NeedsKey, which this
    module printed as "the market did not open on 2026-09-23" — a Wednesday.
    A rate limit dressed as a public holiday is the same fault as a switched
    -on source reported as off (#63), and it is worse here because the
    reader concluded there was a limit on how far back the data went.
    """


def _market_day(router, day: str) -> dict:
    """One session's whole market. Empty dict when the market did not open.

    Raises VendorRefused when the vendor was asked and failed, and NeedsKey
    when no connected vendor carries a whole-market day at all. A FAILURE IS
    NEVER CACHED: a minute's rate limit must not turn into six hours of a
    day that looks shut.
    """
    from alphadesk.providers.base import NeedsKey
    key = f"marketday|{router.owner}|{day}"
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < SESSION_TTL_S:
        return hit[1]
    try:
        got = router.ask("market_day", day)
    except NeedsKey as exc:
        if getattr(exc, "failed", None):
            raise VendorRefused("; ".join(exc.failed.values())) from exc
        raise
    got = got if isinstance(got, dict) else {}
    with _lock:
        _cache[key] = (time.time(), got)
    return got


#: One symbol liquid enough to have traded on every session there is. Its
#: bars ARE the trading calendar.
_CALENDAR_SYMBOL = "SPY"


def trading_sessions(router, count: int = 15) -> list[str]:
    """The last `count` sessions that actually opened, newest first.

    READ FROM A SYMBOL'S OWN BARS, not by asking the vendor day by day. The
    first version probed the whole-market endpoint once per candidate day,
    so offering fifteen sessions cost fifteen requests against a plan that
    allows five a minute — the stepper exhausted the budget before the
    reader pressed anything. A daily bar exists only on a session, so one
    request for one liquid symbol is the same answer for one five-hundredth
    of the cost.
    """
    key = f"sessions|{router.owner}|{count}"
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < SESSION_TTL_S:
        return hit[1]
    try:
        bars = router.get("daily_history", [_CALENDAR_SYMBOL], max(count + 5, 20)) or {}
    except Exception as exc:
        log.debug("trading sessions: %s", exc)
        return hit[1] if hit else []
    days = sorted({b["ts"].date().isoformat() for b in (bars.get(_CALENDAR_SYMBOL) or [])}, reverse=True)
    out = days[:count]
    if out:
        with _lock:
            _cache[key] = (time.time(), out)
    return out


def previous_session(router, before: str) -> Optional[str]:
    """The last session that actually opened before `before`."""
    for d in trading_sessions(router, 40):
        if d < before:
            return d
    return None


def session_movers(category: str, day: str, top: int = 20,
                   min_price: Optional[float] = None,
                   min_turnover: Optional[float] = None) -> dict:
    """One PAST session's movers, computed from the whole market.

    The change is measured close-to-close against the session before it,
    which is what a vendor's own gainer list means by "change" — not the
    day's open-to-close, which would call a stock that gapped up and drifted
    down a loser.
    """
    from alphadesk.providers import get_prices
    from alphadesk.providers.alpaca import common_stock_symbol
    from alphadesk.providers.base import NeedsKey
    cat = (category or "").strip().lower()
    if cat not in SESSION_CATEGORIES:
        raise KeyError(cat)
    router = get_prices()
    top = max(1, min(int(top), 50))
    d_price, d_turn = DEFAULT_FLOORS.get(cat, (0.0, 0.0))
    mp = max(0.0, float(min_price)) if min_price is not None else d_price
    mt = max(0.0, float(min_turnover)) if min_turnover is not None else d_turn

    key = f"session|{router.owner}|{','.join(router.connected)}|{cat}:{day}:{top}:{mp:g}:{mt:g}"
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < SESSION_TTL_S:
        return hit[1]

    # WHETHER ANYONE CARRIES THIS IS A DIFFERENT QUESTION FROM WHETHER THE
    # MARKET OPENED. A provider returning nothing means "I do not carry this
    # surface" to the router, so without asking first, a public holiday and
    # a reader with no Polygon key would give the same answer — and the one
    # that needs a key prompt would get "the market was shut" instead.
    if not router.vendor_for("market_day", "market_day"):
        raise NeedsKey("market_day")
    try:
        today = _market_day(router, day)
        prev_day = previous_session(router, day)
        prev = _market_day(router, prev_day) if prev_day else {}
    except VendorRefused as exc:
        # SAID PLAINLY, and never cached. "The market did not open" would be
        # a lie about a Wednesday, and the reader would conclude the history
        # simply stops there.
        return _unavailable(cat, day, str(exc))
    if not today or not prev:
        # Not an error and not an empty list: the market was shut that day.
        return _closed(cat, day)

    funds = fund_list(router) or frozenset()
    rows: list[dict] = []
    for sym, bar in today.items():
        if not common_stock_symbol(sym) or _TEST_SYMBOL.match(sym):
            continue
        is_fund = sym in funds or bool(_FUND_NAME.search(sym))
        if (cat == "etfs") != is_fund:
            continue
        was = (prev.get(sym) or {}).get("close")
        close, vol = bar.get("close"), bar.get("volume") or 0
        if not was or not close:
            continue
        rows.append(_row(sym, close, (close - was) / was * 100.0, vol))

    rows, unverified = _verify_extremes(router, rows, prev_day, day)
    # NO "ALL" TAB HERE, deliberately. On the live list that tab is the
    # VENDOR'S curated set of what is moving; here the input is every symbol
    # that traded — twelve thousand of them — so "All" would be an arbitrary
    # slice of the market in dictionary order, presented as though someone
    # chose it. The three the reader asked for are the three that mean
    # something: active, gainers, losers.
    tabs = [t for t in tabs_from_list(rows) if t["id"] != "all"]
    apply_floors(tabs, mp, mt)
    for t in tabs:
        t["rows"] = t["rows"][:top]
    # Names only for the rows that survived — the SEC's ticker file is one
    # cached lookup, so twenty of them cost nothing, and ten thousand would.
    from alphadesk.ingest import edgar
    for t in tabs:
        for r in t["rows"]:
            r["name"] = edgar.company_title(r["symbol"])
    # THE SEC'S LIST DOES NOT CARRY MOST FUNDS. SOXS, HYG, QQQ and TQQQ all
    # come back with nothing from it, so an ETF list showed a column of
    # dashes where the names should be. A quote carries the fund's own name
    # — one batched request for the twenty rows on screen, and a name does
    # not change with the session being viewed.
    nameless = sorted({r["symbol"] for t in tabs for r in t["rows"] if not r.get("name")})
    quotes: dict = {}
    # ASK FOR ALL OF THEM, IN CHUNKS — never a slice of a sorted list. The
    # first version capped at 120 symbols taken from an ALPHABETICAL set, so
    # with three tabs of fifty rows everything past the letter T was simply
    # never asked about: TSLG, TSLL, USHY, VTEB, XLE, XLF and XLU all showed
    # a dash while the vendor knew every one of them. A cap that silently
    # drops the end of the alphabet is worse than no cap, because it looks
    # like missing data rather than an unasked question.
    for i in range(0, len(nameless), 100):
        try:
            quotes.update(router.get("quotes", nameless[i:i + 100]) or {})
        except Exception as exc:
            log.debug("session movers: no names from quotes (%s)", exc)
            break
        for t in tabs:
            for r in t["rows"]:
                if not r.get("name"):
                    r["name"] = (quotes.get(r["symbol"]) or {}).get("name")

    result = {"category": cat, "label": CATEGORIES[cat], "change_label": "1D",
              "session": day, "previous_session": prev_day, "historical": True,
              "extended": False, "session_label": None,
              "official": True, "source": "polygon",
              "filling": False,
              "note": (f"{day} close against {prev_day}. Volatility and liquidity are not "
                       f"shown for a past session — they describe today's twenty days, not that day's."
                       + (f" {unverified} large move{'s' if unverified != 1 else ''} left out: "
                          f"no second source to check it against." if unverified else "")),
              "floors": {"min_price": mp, "min_turnover": mt, "min_liquidity": 0.0, "min_volatility": 0.0,
                         "default_min_price": d_price, "default_min_turnover": d_turn},
              "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tabs": tabs}
    with _lock:
        if len(_cache) > 2048:
            _cache.clear()
        _cache[key] = (time.time(), result)
    return result


def _closed(cat: str, day: str) -> dict:
    """A day the market did not open, said plainly."""
    return {"category": cat, "label": CATEGORIES[cat], "change_label": "1D",
            "session": day, "previous_session": None, "historical": True, "closed": True,
            "extended": False, "session_label": None, "official": True, "source": "polygon",
            "filling": False, "note": f"the market did not open on {day}",
            "floors": {"min_price": 0.0, "min_turnover": 0.0, "min_liquidity": 0.0, "min_volatility": 0.0,
                       "default_min_price": 0.0, "default_min_turnover": 0.0},
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tabs": []}


def _verify_extremes(router, rows: list[dict], prev_day: str, day: str) -> tuple[list[dict], int]:
    """Check the biggest moves against a SECOND source, and correct them.

    MEASURED, not assumed (2026-09-26): asked for 2026-09-25, this list put
    Tutor Perini top of the gainers at +406.45% on 224,651 shares. Its real
    move was +0.78% — 83.32 to 83.97. Polygon's whole-market day does not
    restate the session BEFORE a split the way its own per-symbol bars do,
    so a stock that split between the two sessions shows a move that never
    happened, and it lands at the top of the list where it does the most
    damage.

    THE CORROBORATED SPLIT CALENDAR WAS TRIED FIRST AND DID NOT CATCH IT —
    the split was not listed by two vendors for that window. Dropping every
    large move instead would have deleted the day's real ones: WidePoint
    genuinely fell 50.6% and Masonglory genuinely rose 309.6%, both
    confirmed against per-symbol bars.

    So the extremes are re-measured from the reader's own daily bars, which
    are split-adjusted per symbol. Only rows past the threshold are checked,
    so a normal session costs nothing, and a row that cannot be checked at
    all is dropped: an unverifiable 400% belongs nowhere near the top of a
    list someone reads for what moved.
    """
    suspicious = [r for r in rows if abs(r.get("change_pct") or 0) >= _SPLIT_CHECK_PCT]
    if not suspicious:
        return rows, 0
    syms = [r["symbol"] for r in suspicious][:60]
    # Enough sessions to reach back to the day asked for, with room for
    # holidays. Roughly five sessions a week, plus a week of slack.
    try:
        back = (date.today() - date.fromisoformat(day)).days
    except ValueError:
        back = 0
    want = min(260, int(back * 0.72) + 8)
    try:
        bars = router.get("daily_history", syms, want) or {}
    except Exception as exc:                  # no second vendor is not a verdict
        log.debug("session movers: cannot verify extremes (%s)", exc)
        return rows, 0
    if not bars:
        return rows, 0
    dropped = 0
    out: list[dict] = []
    for r in rows:
        if abs(r.get("change_pct") or 0) < _SPLIT_CHECK_PCT:
            out.append(r)
            continue
        series = {b["ts"].date().isoformat(): b for b in (bars.get(r["symbol"]) or [])}
        was, now = series.get(prev_day), series.get(day)
        if not was or not now or not was.get("close"):
            dropped += 1
            continue
        truth = (now["close"] - was["close"]) / was["close"] * 100.0
        if abs(truth - (r["change_pct"] or 0)) > 5.0:
            r = {**r, "price": now["close"], "change_pct": round(truth, 2)}
        out.append(r)
    return out, dropped


def _unavailable(cat: str, day: str, why: str) -> dict:
    """The vendor was asked and refused. Not a closed market, not an empty
    day, and not a key prompt — all three would be lies."""
    return {"category": cat, "label": CATEGORIES[cat], "change_label": "1D",
            "session": day, "previous_session": None, "historical": True,
            "unavailable": True,
            "extended": False, "session_label": None, "official": True, "source": "polygon",
            "filling": False,
            # Said in words. "HTTP 429 Too Many Requests" is true and tells a
            # reader nothing about what to do, and the answer here is simply
            # to wait — Polygon's free plan allows five requests a minute.
            "note": (f"{day} is a trading session, but the data vendor's rate limit was reached. "
                     f"It answers a few requests a minute; try again shortly."
                     if ("429" in why or "too many requests" in why.lower())
                     else f"the data vendor would not answer for {day}: {why}"),
            "rate_limited": "429" in why or "too many requests" in why.lower(),
            "floors": {"min_price": 0.0, "min_turnover": 0.0, "min_liquidity": 0.0, "min_volatility": 0.0,
                       "default_min_price": 0.0, "default_min_turnover": 0.0},
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tabs": []}
