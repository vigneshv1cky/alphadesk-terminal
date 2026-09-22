"""Alpaca, on the user's own key and secret (2026-09-13).

What a FREE Alpaca key serves, measured the same day on a basic-plan key:

  * Consolidated bars (SIP: every US exchange) at any interval, as long as
    the request ends at least 15 minutes ago. A request reaching "now" is
    refused with "subscription does not permit querying recent SIP data";
    a paid plan answers it. So the adapter asks for now first and, on that
    refusal, asks again ending 15 minutes back and says the series is
    delayed. One tape either way — no IEX bars are stitched onto SIP bars,
    which is the volume-scale mixing that drew 2,000x spikes once.
  * The overnight session (Blue Ocean, "boats"), unioned onto intraday
    series: its own venue, the whole of that session.
  * Snapshots on the IEX feed: the live last trade and quote from one
    exchange, which is what a live price tag needs.
  * The screener: most active by volume, and the day's gainers and losers.
  * Option contracts and chain snapshots (quotes, last trade, implied
    volatility, greeks); no per-contract daily volume.
  * Crypto bars and snapshots.

What a PAID plan adds (Algo Trader Plus), and how it is noticed without the
reader saying so: recent SIP data. The adapter asks once for SIP's latest
trade; a key that gets it is real-time, and then quotes, the live stream
and every chart come off the consolidated tape with no delay. A key refused
it stays on IEX for live prices and 15-minute-late SIP for bars. Options work
the same way: the chain asks for OPRA (the consolidated options tape, which
needs a paid plan and a signed agreement) and falls back to the free
indicative feed on "OPRA agreement is not signed". Both verdicts are
re-checked every six hours, so an upgrade shows up without replacing the key.

Everything a vendor like this does not carry answers None, and the data
router asks the user's next vendor.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from typing import Any

from alphadesk.providers.base import EntitlementError, ProviderError

log = logging.getLogger("alphadesk.providers.alpaca")

SIP_DELAY_MIN = 15
PLAN_RECHECK_S = 6 * 3600
# How many unnamed symbols make one listing of every asset cheaper than a
# lookup each, and how long that listing is kept (see AlpacaPrices.names).
NAME_BULK_AT = 10
NAMES_KEEP_S = 86400
# Symbols per bars request, and batches asked at once (see stock_bars).
BARS_BATCH = 25
BARS_WORKERS = 4
# The most prints one overnight rebuild will read (see night_bars). The
# busiest name measured over five nights was 51,261 (NVDA, 2026-09-16), so
# this leaves room without letting one chart pull an unbounded feed.
NIGHT_TRADES_MAX = 120_000
# How long a rebuilt night is kept: while the overnight session is running it
# is still growing, so only a few seconds; once it has closed the bars cannot
# change until the next one.
NIGHT_KEEP_OPEN_S = 20
NIGHT_KEEP_CLOSED_S = 600
NIGHT_CACHE_MAX = 200
# The dollar-volume movers (see AlpacaPrices.pool_movers): the pool is every
# listed symbol averaging at least POOL_MIN_DOLLARS traded a day over the last
# POOL_SESSIONS sessions (at most POOL_MAX of them), rebuilt every POOL_KEEP_S.
# A floor, not a count (2026-09-15): the top 1,000 reached down only to ~$117M
# a day, so a liquid leveraged fund like CRWL (~$32M, +4% that day) was in no
# movers list at all.
POOL_MIN_DOLLARS = 10e6
POOL_MAX = 4000
POOL_SESSIONS = 5
POOL_KEEP_S = 86400
POOL_ROWS_KEEP_S = 10
#: A saved pool older than this is not adopted (a long-idle reader's).
POOL_SAVED_MAX_AGE_S = 7 * 86400
# Option movers read contracts expiring within this many days: the busiest
# are the near ones, and 45 days takes in the monthly contracts too
# (2026-09-15; 14 days left them out).
OPTION_MOVERS_DAYS = 45
OPTION_MOVERS_MIN_VOLUME = 1000
# How many of today's most traded names the option movers read, beside the
# index funds whose options always trade most (2026-09-15: 15 missed heavy
# option days in names outside the very largest).
OPTION_MOVERS_NAMES = 37
OPTION_INDEX_FUNDS = ("SPY", "QQQ", "IWM")
OPTION_MOVERS_WORKERS = 12
OPTION_STRIKE_BAND = 0.25
# Coins by size, for the crypto list's order when the vendor's volume cannot
# rank them (Alpaca counts only its own venue).
COIN_ORDER = ("BTC", "ETH", "USDT", "XRP", "SOL", "USDC", "DOGE", "ADA", "TRX", "LINK", "AVAX", "SHIB", "XLM", "DOT",
              "BCH", "LTC", "HYPE", "UNI", "PEPE", "AAVE", "POL", "ARB", "FIL", "GRT", "CRV", "MKR", "XTZ", "SUSHI",
              "BAT", "YFI", "TRUMP", "PAXG")
LISTED_EXCHANGES = frozenset({"NYSE", "NASDAQ", "ARCA", "AMEX", "BATS"})
# Tries for one SIP request that a PAID key sees refused (2026-09-14, measured
# minutes after an upgrade to Algo Trader Plus: 6 of 36 SIP requests came back
# "subscription does not permit querying recent SIP data", the rest answered).
# A refusal is only believed when it repeats; a lone one is retried.
SIP_TRIES = 3


def _sip_call(call):
    """Run a SIP request, retrying a recent-SIP refusal up to SIP_TRIES
    times. Any other error, or a refusal on every try, is raised."""
    for attempt in range(SIP_TRIES):
        try:
            return call()
        except Exception as exc:
            if not _is_recent_sip_refusal(exc) or attempt == SIP_TRIES - 1:
                raise
            time.sleep(0.15 * (attempt + 1))

# Market ETFs: the free stand-ins for index levels, labelled as the funds
# they are. An index level itself is licensed data no free key carries.
MARKET_ETFS: tuple[tuple[str, str], ...] = (
    ("SPY", "S&P 500 ETF"), ("QQQ", "Nasdaq 100 ETF"), ("DIA", "Dow 30 ETF"), ("IWM", "Russell 2000 ETF"),
    ("VIXY", "VIX futures ETF"), ("TLT", "20+ yr Treasury ETF"), ("GLD", "Gold ETF"), ("USO", "Oil ETF"),
    ("UUP", "US dollar ETF"), ("EEM", "Emerging markets ETF"), ("EFA", "Developed ex-US ETF"), ("HYG", "High yield ETF"),
)
LISTED_ETFS: tuple[tuple[str, str], ...] = MARKET_ETFS + (
    ("VOO", "S&P 500"), ("VTI", "Total market"), ("XLK", "Technology"), ("XLF", "Financials"), ("XLE", "Energy"),
    ("XLV", "Health care"), ("XLI", "Industrials"), ("XLY", "Consumer disc."), ("XLP", "Consumer staples"),
    ("XLU", "Utilities"), ("XLB", "Materials"), ("XLRE", "Real estate"), ("XLC", "Communication"), ("SMH", "Semiconductors"),
    ("SOXX", "Semiconductors"), ("ARKK", "ARK Innovation"), ("SLV", "Silver"), ("IBIT", "Bitcoin"), ("ETHA", "Ethereum"),
    ("TQQQ", "3x Nasdaq"), ("SQQQ", "-3x Nasdaq"), ("SOXL", "3x semis"), ("SOXS", "-3x semis"), ("LQD", "IG corporate"),
    ("IEF", "7-10yr Treasury"), ("SHY", "1-3yr Treasury"), ("KRE", "Regional banks"), ("XBI", "Biotech"), ("GDX", "Gold miners"),
)


def coin_pair(symbol: str) -> str | None:
    """The Alpaca pair for a coin symbol ("BTC-USD", "BTC/USD", "BTCUSD"),
    or None for anything that is not one."""
    s = symbol.upper().strip()
    for quote in ("USDT", "USDC", "USD", "BTC"):
        for sep in ("-", "/"):
            if s.endswith(sep + quote) and len(s) > len(quote) + 1:
                return f"{s[: -len(quote) - 1]}/{quote}"
    return None


def common_stock_symbol(symbol: str) -> bool:
    """A screener row worth listing: letters only, and not a Nasdaq
    fifth-letter warrant, right or unit (ACMEW, ACMER, ACMEU), which top
    the gainers list on tiny prints and carry no real volume — nor a
    preferred share or a company in bankruptcy (fifth letter P or Q; NFEGP
    led the gainers at +745% on 2026-09-15)."""
    s = (symbol or "").upper()
    return s.isalpha() and len(s) <= 5 and not (len(s) == 5 and s[-1] in "WRUPQ")


def rank_dollar_volume(bars: dict[str, list[dict]], sessions: int, min_dollars: float,
                       max_size: int) -> list[str]:
    """The symbols whose average close × volume over their last `sessions`
    daily bars (Alpaca's raw bar shape) is at least `min_dollars`, most
    first, at most `max_size`. Pure."""
    scored = []
    for sym, rows in bars.items():
        last = [b for b in rows if b.get("c") and b.get("v")][-sessions:]
        if last:
            avg = sum(b["c"] * b["v"] for b in last) / len(last)
            if avg >= min_dollars:
                scored.append((avg, sym))
    return [sym for _, sym in sorted(scored, reverse=True)[:max_size]]


def _stamp(value: Any) -> datetime | None:
    """An Alpaca timestamp, or None when it is missing or malformed. Pure."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def snapshot_dollar_rows(snaps: dict[str, dict], today: date) -> list[dict]:
    """Movers rows from raw snapshots, most dollars traded first: the day's
    volume × its volume-weighted price.

    The change is always measured from the last regular close BEFORE the
    price shown, so the figure answers the same question in every session
    (2026-09-22). While the regular session runs that is the previous close;
    once it has ended — after hours, overnight, or the next morning before
    the opening bell — a trade printed after four o'clock New York time is
    the price, and the session that just closed is what it is measured
    against. The row says so (`extended`), carries the closed session's own
    move (`regular_pct`) and when the extended print was struck
    (`extended_at`), because its VOLUME and dollars traded remain that
    session's and nothing else.

    Before this the latest trade counted only while the day's own bar
    existed, so every list stood still from four in the afternoon until the
    next opening bell. Pure."""
    from alphadesk.config import ET
    rows = []
    for sym, s in snaps.items():
        day, prev, trade = s.get("dailyBar") or {}, s.get("prevDailyBar") or {}, s.get("latestTrade") or {}
        if not day.get("v"):
            continue
        at = _stamp(day.get("t"))
        if at is None:
            continue
        session = at.astimezone(ET).date()
        close = _f(day.get("c"))
        base = _f(prev.get("c"))
        regular = round(100 * (close / base - 1), 2) if close and base else None
        # A print struck after the session's own closing bell is an
        # extended-hours trade, whatever the clock says here.
        struck = _stamp(trade.get("t"))
        bell = datetime.combine(session, dtime(16, 0), ET)
        late = _f(trade.get("p")) if struck and struck.astimezone(ET) > bell else None
        if late and close:
            price, change, extended = late, round(100 * (late / close - 1), 2), True
        elif session == today:
            # The session is running: the live print against the previous close.
            price, extended = _f(trade.get("p")) or close, False
            change = round(100 * (price / base - 1), 2) if price and base else None
        else:
            price, change, extended = close, regular, False
        if not price:
            continue
        dollars = (_f(day.get("vw")) or close or price) * day["v"]
        row = {"symbol": sym, "name": None, "price": price, "change_pct": change,
               "volume": int(day["v"]), "turnover": dollars, "session": session.isoformat()}
        if extended:
            row.update({"extended": True, "regular_pct": regular,
                        "extended_at": struck.astimezone(ET).isoformat()})
        rows.append(row)
    return sorted(rows, key=lambda r: -r["turnover"])


def option_mover_rows(underlying: str, snaps: dict[str, dict]) -> list[dict]:
    """Movers rows for one underlying's option snapshots (Alpaca's REST shape),
    in the shape the option movers tile reads: the contract, today's volume,
    last price and change against the previous close, implied volatility and
    the premium traded (volume × price × 100). Only contracts whose daily bar
    is from the chain's latest session and that traded. Pure."""
    from alphadesk.ingest.options_flow import parse_occ
    session = max(((s or {}).get("dailyBar") or {}).get("t", "")[:10] for s in snaps.values()) if snaps else ""
    rows = []
    for occ, snap in snaps.items():
        bar, prev, trade = snap.get("dailyBar") or {}, snap.get("prevDailyBar") or {}, snap.get("latestTrade") or {}
        if not session or (bar.get("t") or "")[:10] != session:
            continue
        vol = int(bar.get("v") or 0)
        last = _f(trade.get("p")) or _f(bar.get("c"))
        c = parse_occ(occ)
        if vol <= 0 or not last or not c:
            continue
        base = _f(prev.get("c"))
        iv = _f(snap.get("impliedVolatility"))
        kind = "C" if c["type"] == "call" else "P"
        premium = round(vol * last * 100)
        rows.append({"symbol": occ, "display": f"{underlying} {c['strike']:g}{kind} {c['expiry'][5:]}",
                     "name": f"{underlying} {c['expiry']} {c['type']} {c['strike']:g}",
                     "price": last, "change_pct": round(100 * (last / base - 1), 2) if base else None,
                     "volume": vol, "volatility": round(iv * 100, 1) if iv else None,
                     "liquidity": premium, "turnover": premium,
                     "underlying": underlying, "expiry": c["expiry"]})
    return rows


def merge_movers(screener: list[dict], pool: list[dict], up: bool) -> list[dict]:
    """Gainers (`up`) or losers from the screener's rows and the pool's,
    one row per symbol — the pool's where both have it, since it carries the
    day's dollars traded — largest move first. Pure."""
    by_symbol = {r["symbol"]: r for r in screener}
    by_symbol.update({r["symbol"]: r for r in pool})
    moved = [r for r in by_symbol.values()
             if r.get("change_pct") is not None and (r["change_pct"] > 0 if up else r["change_pct"] < 0)]
    return sorted(moved, key=lambda r: -r["change_pct"] if up else r["change_pct"])


def option_underlyings(pool_rows: list[dict], names: int) -> list[str]:
    """SPY, QQQ and IWM, then the `names` other symbols with the most dollars
    traded today (the pool's rows, most first), in that order. Pure."""
    out = list(OPTION_INDEX_FUNDS)
    for r in pool_rows:
        if len(out) >= len(OPTION_INDEX_FUNDS) + names:
            break
        if r["symbol"] not in out:
            out.append(r["symbol"])
    return out


def rolling_change(price: float | None, bars: list[dict], now: datetime, bar_minutes: int,
                   hours: int = 24) -> float | None:
    """Percent change from the price `hours` ago to `price`: the close of the
    last bar that ended at or before that moment (at most one bar's length
    early). None when no bar ended in time. Pure."""
    if not price:
        return None
    cutoff = now - timedelta(hours=hours)
    base = None
    for b in bars:
        if b["ts"] + timedelta(minutes=bar_minutes) <= cutoff:
            base = b["close"]
        else:
            break
    return round(100 * (price / base - 1), 2) if base else None


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def sip_session_open(now: datetime) -> bool:
    """Whether the consolidated tape prints at `now` (New York time): a
    weekday between 04:00 and 20:00. Holidays are not modelled."""
    return now.weekday() < 5 and 4 <= now.hour < 20


def option_underlying(symbol: str) -> str:
    """An underlying as Alpaca's options endpoints spell it.

    A share class is a DOT there (BRK.A, BRK.B) and a dash everywhere else
    in this app, which follows the SEC's ticker file. Asking with the dash
    is refused outright — "invalid underlying symbols: BRK-A" reached the
    Options page as a 500, and every dash-class ticker was unusable there
    (2026-09-15). Pure."""
    return symbol.upper().replace("-", ".")


def _invalid_symbol(exc: Exception) -> str | None:
    """The symbol in Alpaca's 'invalid symbol: X' refusal, if that is what
    this is. The options endpoint words it "invalid underlying symbols"."""
    import re
    m = re.search(r"invalid (?:underlying )?symbols?:\s*([A-Za-z0-9.\-/]+)", str(exc))
    return m.group(1).upper() if m else None


def _is_plan_refusal(exc: Exception) -> bool:
    msg = str(exc).lower()
    return getattr(exc, "status_code", None) in (401, 402, 403) or "subscription" in msg or "not permit" in msg


def _is_recent_sip_refusal(exc: Exception) -> bool:
    return "recent sip" in str(exc).lower()


def _is_opra_refusal(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "opra" in msg or _is_plan_refusal(exc)


class AlpacaPrices:
    name = "alpaca"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self._clients: dict[str, Any] = {}
        self._lock = threading.Lock()
        # (symbol, bar seconds, window) -> (when, bars). See night_bars.
        self._night_cache: dict[tuple, tuple[float, list[dict]]] = {}
        self._assets: dict[str, tuple[float, Any]] = {}
        # Every active US equity's (name, exchange), from one listing; see
        # names().
        self._names: dict[str, tuple[str | None, str | None]] = {}
        self._names_at = 0.0
        self._names_lock = threading.Lock()
        # (built_at, symbols) for the dollar-volume pool, and whether a build
        # is running.
        self._pool: tuple[float, list[str]] | None = None
        self._pool_building = False
        # Whether the saved pool has been looked for yet (once per instance).
        self._pool_loaded = False
        # The reader this instance serves; set by the registry. The saved
        # pool is theirs alone.
        self.reader_id: str | None = None
        # The last pricing of the pool: the stock and ETF lists rebuild
        # together and share it.
        self._pool_rows: tuple[float, list[dict]] | None = None
        # Whether this key reaches recent SIP bars (a paid plan): learned on
        # the first chart, so a free key is not refused on every poll.
        self._recent_sip: bool | None = None
        # (checked_at, verdict) for the live stock feed and the options feed.
        self._stock_feed_seen: tuple[float, str] | None = None
        self._opra_seen: tuple[float, bool] | None = None

    # ── clients ────────────────────────────────────────────────────────────

    def _need_key(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ProviderError("no Alpaca key and secret")

    def _client(self, kind: str) -> Any:
        self._need_key()
        with self._lock:
            c = self._clients.get(kind)
            if c is not None:
                return c
            from alphadesk.net import bound_timeout
            if kind == "stock":
                from alpaca.data.historical import StockHistoricalDataClient
                c = StockHistoricalDataClient(self.api_key, self.api_secret)
            elif kind == "crypto":
                from alpaca.data.historical import CryptoHistoricalDataClient
                c = CryptoHistoricalDataClient(self.api_key, self.api_secret)
            elif kind == "option":
                from alpaca.data.historical.option import OptionHistoricalDataClient
                c = OptionHistoricalDataClient(self.api_key, self.api_secret)
            elif kind == "screener":
                from alpaca.data.historical.screener import ScreenerClient
                c = ScreenerClient(self.api_key, self.api_secret)
            elif kind in ("paper", "live"):
                from alpaca.trading.client import TradingClient
                c = TradingClient(self.api_key, self.api_secret, paper=(kind == "paper"))
            else:
                raise ValueError(kind)
            c = bound_timeout(c)
            self._clients[kind] = c
            return c

    def _trading(self, call):
        """Account-scoped reads (assets, option contracts) go to the paper or
        the live endpoint depending on which the key belongs to; the first
        one that authenticates is remembered."""
        order = [k for k in ("paper", "live") if self._clients.get(f"{k}:bad") is None]
        last: Exception | None = None
        for kind in order:
            try:
                return call(self._client(kind))
            except Exception as exc:
                last = exc
                if getattr(exc, "status_code", None) in (401, 403):
                    self._clients[f"{kind}:bad"] = True
                    continue
                raise
        raise ProviderError(f"alpaca trading endpoint refused the key: {last}")

    def _wrap(self, what: str, exc: Exception) -> ProviderError:
        if _is_plan_refusal(exc):
            return EntitlementError(f"alpaca plan does not include {what}: {exc}")
        return ProviderError(f"alpaca {what} failed: {exc}")

    # ── plan ───────────────────────────────────────────────────────────────

    def stock_feed(self) -> str:
        """"sip" when this key reaches real-time consolidated data (a paid
        plan), "iex" when it does not. A latest-trade request decides it —
        refused on every one of SIP_TRIES tries before the key is called
        free, since a paid key sees the odd refusal too; the verdict is held
        six hours. A failure that is not a plan refusal (a timeout) answers
        "iex" without being remembered."""
        hit = self._stock_feed_seen
        if hit and time.time() - hit[0] < PLAN_RECHECK_S:
            return hit[1]
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestTradeRequest
        try:
            client = self._client("stock")
            _sip_call(lambda: client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols="SPY", feed=DataFeed.SIP)))
            feed = "sip"
        except ProviderError:
            raise
        except Exception as exc:
            if not (_is_recent_sip_refusal(exc) or _is_plan_refusal(exc)):
                log.debug("alpaca plan probe: %s", exc)
                return "iex"
            feed = "iex"
        self._stock_feed_seen = (time.time(), feed)
        self._recent_sip = feed == "sip"
        return feed

    def plan(self) -> dict:
        """What this key's plan delivers, for the Account page and the
        panels' freshness labels. `options` is None until a chain was asked."""
        feed = self.stock_feed()
        opra = self._opra_seen[1] if self._opra_seen else None
        return {"realtime": feed == "sip", "stocks": feed,
                "options": None if opra is None else "opra" if opra else "indicative",
                "chart_delay_minutes": 0 if feed == "sip" else SIP_DELAY_MIN}

    # ── corporate actions ──────────────────────────────────────────────────

    def split_calendar(self, start: str, end: str) -> list[dict] | None:
        """Forward and reverse splits with an ex-date in [start, end], from
        Alpaca's corporate-actions feed (on every plan). The feed files an
        action under its processing date, which for a split is the ex-date,
        so the request is padded a week either side and filtered here.
        Unlisted securities arrive under a CUSIP and are dropped; class
        shares are written the SEC way (BRK-B). Measured 2026-09-14 against
        FMP: it lists real splits FMP missed (CCUP) and none that did not
        happen, where FMP listed six."""
        self._need_key()
        from urllib.parse import urlencode

        from alphadesk.providers.prices import _get_json
        lo = (date.fromisoformat(start[:10]) - timedelta(days=7)).isoformat()
        hi = (date.fromisoformat(end[:10]) + timedelta(days=7)).isoformat()
        headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}
        out: list[dict] = []
        token: str | None = None
        for _ in range(20):
            q = {"types": "forward_split,reverse_split", "start": lo, "end": hi, "limit": 1000}
            if token:
                q["page_token"] = token
            body = _get_json("https://data.alpaca.markets/v1/corporate-actions?" + urlencode(q), headers, timeout=20.0)
            actions = (body or {}).get("corporate_actions") or {}
            for kind, key in (("forward", "forward_splits"), ("reverse", "reverse_splits")):
                for a in actions.get(key) or []:
                    sym, ex = str(a.get("symbol") or ""), str(a.get("ex_date") or "")[:10]
                    if not sym or any(ch.isdigit() for ch in sym) or not (start[:10] <= ex <= end[:10]):
                        continue
                    new, old = a.get("new_rate"), a.get("old_rate")
                    # A fractional rate is a mutual fund's share adjustment
                    # (NBGAX 9.623 for 10), not a company's split.
                    if not new or not old or float(new) != int(float(new)) or float(old) != int(float(old)):
                        continue
                    out.append({"symbol": sym.upper().replace(".", "-"), "date": ex,
                                "to": float(new), "from": float(old), "kind": kind})
            token = (body or {}).get("next_page_token")
            if not token:
                break
        return out

    # ── reference ──────────────────────────────────────────────────────────

    def _listing(self) -> dict[str, tuple[str | None, str | None]]:
        """Every active US equity's (name, exchange), listed at most once a
        NAMES_KEEP_S; {} when the listing cannot be had."""
        # One listing at a time: the movers and the ETF lists ask at once
        # on a fresh page, and the second waits for the first's answer.
        with self._names_lock:
            if time.time() - self._names_at >= NAMES_KEEP_S:
                try:
                    rows = self._trading(lambda c: c.get("/assets", {"status": "active", "asset_class": "us_equity"}))
                    self._names = {str(r.get("symbol", "")).upper(): (r.get("name"), r.get("exchange"))
                                   for r in rows or [] if isinstance(r, dict) and r.get("symbol")}
                    self._names_at = time.time()
                except Exception as exc:
                    log.debug("alpaca asset listing: %s", exc)
            return self._names if time.time() - self._names_at < NAMES_KEEP_S else {}

    def names(self, symbols: list[str]) -> dict[str, tuple[str | None, str | None]]:
        """(company name, exchange) per symbol; (None, None) when unknown.

        A quote names its company. That was one trading-API request per
        symbol, in sequence: the stock movers' ~140 symbols took 6.7s on a
        fresh process, the first movers view after every deploy, and ran
        past the trading API's 200 requests a minute once the ETF lists
        asked too (2026-09-15). From NAME_BULK_AT unnamed symbols, ONE
        request lists every active US equity instead — 14,274 of them, 6.4MB,
        about a second — read raw rather than through the SDK's models, and
        only each name and exchange is kept, for NAMES_KEEP_S. A few unnamed
        symbols (one chart's quote) still look up alone."""
        syms = [s.upper() for s in symbols]
        fresh = lambda: time.time() - self._names_at < NAMES_KEEP_S  # noqa: E731
        unnamed = [s for s in syms if not (fresh() and s in self._names) and s not in self._assets]
        if len(unnamed) >= NAME_BULK_AT:
            self._listing()
        out: dict[str, tuple[str | None, str | None]] = {}
        alone = 0
        for s in syms:
            if fresh() and s in self._names:
                out[s] = self._names[s]
                continue
            hit = self._assets.get(s)
            if hit is None and (not fresh() or len(unnamed) < NAME_BULK_AT) and alone < NAME_BULK_AT:
                # Not listed as active, or no listing: a lookup each, but
                # never a request per row of a long list.
                alone += 1
                self.asset(s)
                hit = self._assets.get(s)
            a = hit[1] if hit else None
            exch = getattr(getattr(a, "exchange", None), "value", None) or getattr(a, "exchange", None)
            out[s] = (getattr(a, "name", None), exch)
        return out

    def asset(self, symbol: str) -> Any:
        sym = symbol.upper()
        hit = self._assets.get(sym)
        if hit and time.time() - hit[0] < 86400:
            return hit[1]
        try:
            a = self._trading(lambda c: c.get_asset(sym))
        except Exception as exc:
            log.debug("alpaca asset %s: %s", sym, exc)
            a = None
        if len(self._assets) > 4096:
            self._assets.clear()
        self._assets[sym] = (time.time(), a)
        return a

    # ── bars ───────────────────────────────────────────────────────────────

    _INTERVALS: dict[str, dict] = {
        "1m": {"n": 1, "unit": "Min", "max_days": 3650, "label": "1 min"},
        "2m": {"n": 2, "unit": "Min", "max_days": 3650, "label": "2 mins"},
        "5m": {"n": 5, "unit": "Min", "max_days": 3650, "label": "5 mins"},
        "15m": {"n": 15, "unit": "Min", "max_days": 3650, "label": "15 mins"},
        "30m": {"n": 30, "unit": "Min", "max_days": 3650, "label": "30 mins"},
        "1h": {"n": 1, "unit": "Hour", "max_days": 3650, "label": "1 hour"},
        "4h": {"n": 4, "unit": "Hour", "max_days": 3650, "label": "4 hours"},
        "1d": {"n": 1, "unit": "Day", "max_days": None, "label": "1 day"},
        "1wk": {"n": 1, "unit": "Week", "max_days": None, "label": "1 week"},
        "1mo": {"n": 1, "unit": "Month", "max_days": None, "label": "1 month"},
    }

    def chart_intervals(self) -> dict[str, dict]:
        return self._INTERVALS

    @staticmethod
    def _timeframe(spec: dict):
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        return TimeFrame(int(spec["n"]), TimeFrameUnit(spec["unit"]))

    @staticmethod
    def _rows(data: Any, key: str) -> list[dict]:
        seq = data.data.get(key, []) if hasattr(data, "data") else []
        return [{"ts": b.timestamp, "open": float(b.open), "high": float(b.high), "low": float(b.low),
                 "close": float(b.close), "volume": float(getattr(b, "volume", 0) or 0)} for b in seq]

    def stock_bars(self, symbols: list[str] | str, spec: dict, start: datetime, end: datetime | None = None,
                   feed: str = "sip") -> tuple[dict[str, list[dict]], int]:
        """Bars for one or many symbols → ({symbol: bars}, delay_minutes).
        SIP first; a free key's refusal of recent SIP retries 15 minutes back."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        client = self._client("stock")
        syms = [symbols.upper()] if isinstance(symbols, str) else [s.upper() for s in symbols]
        delay = 0
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=SIP_DELAY_MIN)
        want_end = end
        if feed == "sip" and self._recent_sip is False and (end is None or end > cutoff):
            want_end, delay = cutoff, SIP_DELAY_MIN
        feed_enum = {"sip": DataFeed.SIP, "iex": DataFeed.IEX}.get(feed) or getattr(DataFeed, "BOATS", None)
        if feed_enum is None:
            return {}, 0
        if len(syms) > BARS_BATCH:
            # Alpaca answers a many-symbol request in time proportional to
            # the symbols, about 20ms each whatever the span (measured
            # 2026-09-15: 100 symbols 1.9s in one request, 0.71s as four
            # parallel batches of 25). The first stock-movers build of a
            # process asked twice for ~140 symbols. Batches keep the same
            # answer; an invalid symbol still fails the call as before.
            from concurrent.futures import ThreadPoolExecutor
            parts = [syms[i:i + BARS_BATCH] for i in range(0, len(syms), BARS_BATCH)]
            with ThreadPoolExecutor(max_workers=min(BARS_WORKERS, len(parts))) as pool:
                done = list(pool.map(lambda part: self.stock_bars(part, spec, start, end, feed), parts))
            return {k: v for got, _ in done for k, v in got.items()}, max(d for _, d in done)

        # Split-adjusted at EVERY interval (2026-09-15). Intraday bars were
        # asked raw, so a split drew as a cliff: CRWD's 4-for-1 on 2026-07-02
        # put June's minute bars at ~$780 beside July's ~$195 on the 3M chart.
        # Alpaca adjusts minute bars on the consolidated and overnight feeds
        # alike (780 → 195 measured); bars after a split are unchanged, so the
        # live edge still meets the last bar.
        def fetch(e):
            return client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=syms, timeframe=self._timeframe(spec), start=start, end=e, feed=feed_enum,
                adjustment="split"))
        recent = feed == "sip" and delay == 0 and (end is None or end > cutoff)
        try:
            resp = _sip_call(lambda: fetch(want_end)) if recent else fetch(want_end)
            if recent:
                self._recent_sip = True
        except Exception as exc:
            if feed == "sip" and _is_recent_sip_refusal(exc):
                # Refused on every try: this response ends fifteen minutes
                # back. Whether the KEY is free is the plan probe's call, not
                # one request's — it is asked again rather than overwritten.
                self._stock_feed_seen = None
                self._recent_sip = None
                if self.stock_feed() == "iex":
                    self._recent_sip = False
                delay = SIP_DELAY_MIN
                try:
                    resp = fetch(cutoff)
                except Exception as exc2:
                    raise self._wrap("bars", exc2) from exc2
            else:
                raise self._wrap("bars", exc) from exc
        return {s: self._rows(resp, s) for s in syms}, delay

    def night_bars(self, symbol: str, spec: dict, start: datetime,
                   end: datetime | None = None) -> list[dict] | None:
        """The overnight session built from its own PRINTS rather than taken
        as the feed's bars, or None when the window is too long to be worth
        the trades call.

        The feed's bars leave out odd lots — right for the consolidated tape,
        where an odd lot does not set the last sale, and wrong for a session
        that is mostly odd lots. Measured on CrowdStrike (2026-09-16): 466 of
        540 overnight prints were odd lots, so the bars covered 38 of the 135
        minutes that traded; from the prints the same night fills 279 minutes,
        which is the session the reader sees on other terminals. Every trade
        on this feed is overnight by nature, so the request needs no session
        filter of its own."""
        from alphadesk.config import now_et
        from alphadesk.ingest import prices as ip
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockTradesRequest
        feed = getattr(DataFeed, "BOATS", None)
        if feed is None:
            return None
        span = ((end or datetime.now(timezone.utc)) - start).total_seconds() / 86400
        if span > ip.TRADE_NIGHT_MAX_DAYS:
            return None
        seconds = ip.interval_seconds(spec)
        if not seconds or seconds > 3600:
            return None
        sym = symbol.upper()
        # THE NIGHT IS OVER BY BREAKFAST. A 1D chart polls every thirty
        # seconds, and re-reading a session that ended at 04:00 on every one
        # of those polls is the same answer bought again — measured at a
        # third of a second each. So it is remembered, briefly while the
        # overnight session is actually running and for minutes once it has
        # closed. Per key, like the client it is read with.
        key = (sym, int(seconds), start.date().isoformat(), (end or "live") and str(end or "live"))
        keep = NIGHT_KEEP_OPEN_S if ip._is_overnight(now_et()) else NIGHT_KEEP_CLOSED_S
        with self._lock:
            hit = self._night_cache.get(key)
        if hit and time.time() - hit[0] < keep:
            return hit[1]
        try:
            resp = self._client("stock").get_stock_trades(StockTradesRequest(
                symbol_or_symbols=sym, start=start, end=end, feed=feed, limit=NIGHT_TRADES_MAX))
        except Exception as exc:
            log.debug("alpaca overnight prints %s: %s", sym, exc)
            return None
        rows = (getattr(resp, "data", None) or {}).get(sym) or []
        out = ip.bars_from_trades(((t.timestamp, t.price, t.size) for t in rows), int(seconds))
        with self._lock:
            if len(self._night_cache) > NIGHT_CACHE_MAX:
                self._night_cache.clear()
            self._night_cache[key] = (time.time(), out)
        return out

    def crypto_bars(self, pair: str, spec: dict, start: datetime, end: datetime | None = None) -> list[dict]:
        from alpaca.data.requests import CryptoBarsRequest
        try:
            resp = self._client("crypto").get_crypto_bars(CryptoBarsRequest(
                symbol_or_symbols=pair, timeframe=self._timeframe(spec), start=start, end=end))
        except Exception as exc:
            raise self._wrap("crypto bars", exc) from exc
        return self._rows(resp, pair)

    def crypto_daily_history(self, symbols: list[str], days: int = 21) -> dict[str, list[dict]]:
        """The last `days` daily bars for many coins in one request — what the
        crypto list's volatility and liquidity are computed from (2026-09-19).
        Keyed by the symbols as given. The volume is Alpaca's own venue's."""
        from alpaca.data.requests import CryptoBarsRequest
        import re
        pairs = {s: coin_pair(s) for s in symbols}
        # Only symbols in Alpaca's own spelling: CoinGecko lists coins like
        # FIGR_HELOC, and ONE symbol Alpaca calls invalid fails the whole
        # request — every coin's volatility went blank on a reader with both
        # keys (2026-09-19). A coin Alpaca does not trade is simply absent.
        pairs = {s: p for s, p in pairs.items() if p and re.fullmatch(r"[A-Z]+x?/[A-Z]+", p)}
        if not pairs:
            return {}
        start = datetime.now(timezone.utc) - timedelta(days=days + 2)
        try:
            resp = self._client("crypto").get_crypto_bars(CryptoBarsRequest(
                symbol_or_symbols=sorted(set(pairs.values())), timeframe=self._timeframe(self._INTERVALS["1d"]),
                start=start))
        except Exception as exc:
            raise self._wrap("crypto daily bars", exc) from exc
        return {s: rows for s, p in pairs.items() if (rows := self._rows(resp, p))}

    def chart_series(self, symbol: str, days: int = 2, range_key: str | None = None,
                     interval: str | None = None, before=None, need: int | None = None) -> dict | None:
        self._need_key()
        from alphadesk.config import now_et
        from alphadesk.ingest import prices as ip

        sym = symbol.upper()
        rk = (range_key or "1D").upper()
        table = self.chart_intervals()
        used = ip.resolve_interval(rk, interval, table)
        spec = table.get(used) or table["1m"]
        intraday = spec["unit"] in ("Min", "Hour")

        # A HISTORY PAGE reaches one range-span back, and again twice as far
        # each time that came back too thin to fill the blank the chart
        # asked about — a sliver of a page is what made the left edge creep
        # in rather than arrive.
        if before is not None:
            floor = ip.history_floor(used, now_et())
            windows = [(w[0], before) for w in ip.page_attempts(rk, before, floor)]
            if not windows:
                return None
        elif rk == "YTD":
            windows = [(now_et().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), None)]
        elif rk == "MAX":
            windows = [(datetime(2016, 1, 1, tzinfo=timezone.utc), None)]
        else:
            windows = [(now_et() - timedelta(days=ip.RANGE_DAYS.get(rk, days) + 3), None)]

        pair = coin_pair(sym)
        delay = 0
        start, end = windows[0]
        bars: list[dict] = []
        for start, end in windows:
            if pair:
                got_bars = self.crypto_bars(pair, spec, start, end)
                source = "alpaca-crypto"
            else:
                got, delay = self.stock_bars(sym, spec, start, end)
                got_bars = got.get(sym, [])
                source = "sip"
            # A wider window that brought nothing new is the vendor's floor
            # at this interval, not a reason to ask again five times.
            if bars and len(got_bars) <= len(bars):
                break
            bars = got_bars
            if before is None or not ip.page_is_thin(bars, need):
                break
        if not pair and intraday and bars:
            try:
                # The night comes from its own prints where the window is
                # short enough to read them — the feed's bars leave out the
                # odd lots the session is mostly made of — and from the
                # feed's bars otherwise.
                rebuilt = self.night_bars(sym, spec, start, end)
                if rebuilt is None:
                    night, _ = self.stock_bars(sym, spec, start, end, feed="boats")
                    rebuilt = night.get(sym, [])
                bars = ip.merge_overnight(bars, [b for b in rebuilt if ip._is_overnight(b["ts"])])
            except ProviderError as exc:
                log.debug("alpaca overnight bars %s: %s", sym, exc)
        # A widened window can overshoot by thousands of bars; the page keeps
        # the ones nearest the cursor, which are the ones that join what the
        # chart already holds. After the overnight union, so the night bars
        # of a trimmed-away morning do not come back on their own.
        if before is not None:
            bars = ip.page_trim(bars, need)
        if before is not None:
            bars = [b for b in bars if b["ts"] < before]
        provisional = self._provisional(sym, spec, bars) if (delay and intraday and before is None and not pair) else []
        stats = None if used in ("1m", "2m") else ip._daily_coverage(bars)
        out = ip.build_series_payload(sym, bars, used, range_key=rk, interval=interval, stats=stats, table=table)
        if out is not None:
            out["source"] = source
            out["vendor"] = self.name
            out["realtime"] = delay == 0
            # The delay is only news while the consolidated tape is printing
            # (04:00–20:00 ET on a weekday); on a Sunday nothing is missing.
            if delay and sip_session_open(now_et()):
                out["delay_minutes"] = delay
                out["provisional"] = provisional
        return out

    def _provisional(self, sym: str, spec: dict, bars: list[dict]) -> list[dict]:
        """The minutes a delayed consolidated series has not reached yet,
        from IEX: closes only, stamped like bars, strictly after the last
        consolidated bar. NOT bars — no open, range or volume — so nothing
        downstream can mistake one exchange's prints for the tape; the chart
        draws them as a dashed provisional line that the real bars replace
        as they arrive. Only while the tape prints: overnight is Blue
        Ocean's and live already."""
        from alphadesk.config import now_et
        if not bars or not sip_session_open(now_et()):
            return []
        last = bars[-1]["ts"]
        try:
            got, _ = self.stock_bars(sym, spec, last, None, feed="iex")
        except ProviderError as exc:
            log.debug("alpaca provisional %s: %s", sym, exc)
            return []
        return [{"t": b["ts"].isoformat(), "c": b["close"]} for b in got.get(sym, []) if b["ts"] > last]

    def daily_history(self, symbols: list[str], sessions: int = 21) -> dict[str, list[dict]]:
        """The last `sessions` daily bars for many symbols in one request per
        200 — what the calendars' volatility and liquidity columns are computed
        from. Keyed by the symbols as given.

        SEC's ticker file spells share classes and preferreds with a dash
        (LEN-B, ACP-PA); Alpaca spells classes with a dot (LEN.B) and lists no
        preferreds. One symbol Alpaca calls invalid fails the whole batch
        (measured 2026-09-14: "invalid symbol: ACP-PA" blanked a week of
        dividend and earnings liquidity), so the class spelling is translated
        and a symbol still refused is dropped and the batch asked again."""
        import re
        # Preferred series ("ACP-PA", "CTO-PB") are not on Alpaca at all; asking
        # would cost one refused batch each before they could be dropped.
        wanted = [s.upper() for s in symbols if s and not coin_pair(s) and not re.search(r"-P[A-Z]?$", s.upper())]
        if not wanted:
            return {}
        as_alpaca = {s: s.replace("-", ".") for s in wanted}
        back = {v: k for k, v in as_alpaca.items()}
        out: dict[str, list[dict]] = {}
        start = datetime.now(timezone.utc) - timedelta(days=int(sessions * 1.6) + 7)
        names = sorted(set(as_alpaca.values()))

        def one(chunk: list[str]) -> dict:
            for _ in range(20):
                if not chunk:
                    return {}
                try:
                    got, _ = self.stock_bars(chunk, self._INTERVALS["1d"], start)
                    return got
                except ProviderError as exc:
                    bad = _invalid_symbol(exc)
                    if not bad or bad not in chunk:
                        raise
                    log.debug("alpaca has no %s; dropped from the batch", bad)
                    chunk = [c for c in chunk if c != bad]
            return {}

        # Four chunks at a time: an earnings-season week asks for ~1,000
        # symbols, 2.9s for 800 one chunk after another (2026-09-14).
        from concurrent.futures import ThreadPoolExecutor
        chunks = [names[i:i + 200] for i in range(0, len(names), 200)]
        with ThreadPoolExecutor(max_workers=min(4, len(chunks) or 1)) as pool:
            for got in pool.map(one, chunks):
                out.update({back.get(k, k): v[-sessions:] for k, v in got.items() if v})
        return out

    # ── quotes ─────────────────────────────────────────────────────────────

    def _snapshots(self, symbols: list[str], feed: str = "iex") -> tuple[dict[str, Any], str]:
        """Snapshots on `feed`, and the feed that actually answered: a SIP
        request refused on every try falls back to IEX for this call rather
        than failing the quote (which the vendor memo would then hold as a
        plan refusal for an hour)."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockSnapshotRequest
        if not symbols:
            return {}, feed
        client = self._client("stock")

        def ask(f):
            return dict(client.get_stock_snapshot(
                StockSnapshotRequest(symbol_or_symbols=symbols, feed=DataFeed.SIP if f == "sip" else DataFeed.IEX)))
        try:
            if feed == "sip":
                try:
                    return _sip_call(lambda: ask("sip")), "sip"
                except Exception as exc:
                    if not _is_recent_sip_refusal(exc):
                        raise
                    log.info("alpaca SIP snapshots refused on every try; IEX for this call")
                    self._stock_feed_seen = None
            return ask("iex"), "iex"
        except Exception as exc:
            raise self._wrap("snapshots", exc) from exc

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Price blocks for many symbols. The live last trade and quote come
        from the consolidated snapshot on a real-time plan and from the IEX
        snapshot otherwise; the day's open, range, volume and the previous
        close from consolidated daily bars (15 minutes late on a free key),
        so volume is the whole market's, not one exchange's."""
        self._need_key()
        from alphadesk.config import ET
        stocks = [s.upper() for s in symbols if not coin_pair(s)]
        coins = [s.upper() for s in symbols if coin_pair(s)]
        out: dict[str, dict] = {}
        if stocks:
            feed = self.stock_feed()
            snaps, feed = self._snapshots(stocks, feed)
            try:
                daily, _ = self.stock_bars(stocks, self._INTERVALS["1d"], datetime.now(timezone.utc) - timedelta(days=10))
            except ProviderError as exc:
                log.debug("alpaca daily for quotes: %s", exc)
                daily = {}
            today = datetime.now(ET).date()
            named = self.names(stocks)
            for sym in stocks:
                snap = snaps.get(sym)
                bars = daily.get(sym) or []
                trade = getattr(snap, "latest_trade", None)
                q = getattr(snap, "latest_quote", None)
                trade_px = _f(getattr(trade, "price", None))
                trade_ts = getattr(trade, "timestamp", None)
                if not bars and trade_px is None:
                    continue
                last_bar = bars[-1] if bars else None
                # Today's session is open when its daily bar exists: the
                # price is the live last trade, the change is against the
                # previous session's close. Otherwise (a weekend, before the
                # open) the quote IS the last session — its close and its
                # change — and a later print is the extended-hours price.
                in_session = bool(last_bar and last_bar["ts"].astimezone(ET).date() == today)
                session = last_bar
                prior = bars[-2] if len(bars) > 1 else None
                prev = prior["close"] if prior else _f(getattr(getattr(snap, "previous_daily_bar", None), "close", None))
                # A trade struck after the session's own closing bell is an
                # extended-hours print: it is the price, and the session that
                # just closed is what it is measured against (2026-09-22,
                # snapshot_dollar_rows' rule). Before this the test was the
                # hour of the day, which saw the evening and never the
                # morning, and the quote stood still until the opening bell.
                bell = (datetime.combine(session["ts"].astimezone(ET).date(), dtime(16, 0), ET)
                        if session else None)
                late = (trade_px if (session and trade_px and trade_ts and bell
                                     and trade_ts.astimezone(ET) > bell) else None)
                if late:
                    price, as_of = late, trade_ts
                elif in_session:
                    price = trade_px or session["close"]
                    as_of = trade_ts
                else:
                    price = session["close"] if session else trade_px
                    as_of = None
                if price is None:
                    continue
                extended = None
                if late and session and abs(late - session["close"]) > 1e-9:
                    extended = {"price": late, "change_pct": round(100 * (late / session["close"] - 1), 2),
                                "from_close": session["close"],
                                "as_of": trade_ts.astimezone(ET).isoformat()}
                base = session["close"] if (late and session) else prev
                name, exch = named.get(sym, (None, None))
                dp = 4 if price < 1 else 2
                out[sym] = {
                    "symbol": sym, "name": name or sym,
                    "exchange": exch, "exchange_name": exch,
                    "quote_source": ("Alpaca · real-time consolidated" if feed == "sip" else "Alpaca · IEX last trade")
                                    if (in_session or late) else "Alpaca · consolidated close",
                    "feed": feed, "realtime": feed == "sip",
                    # The last session's close is struck at 16:00 in New York.
                    "as_of": as_of.astimezone(ET).isoformat() if as_of else (
                        datetime.combine(session["ts"].astimezone(ET).date(), datetime.min.time(), ET).replace(hour=16).isoformat()
                        if session else None),
                    "currency": "USD",
                    "price": round(price, dp),
                    "change": round(price - base, dp) if base else None,
                    "change_pct": round(100 * (price - base) / base, 2) if base else None,
                    # What the change above is measured from — the previous
                    # close in the session, the session's own close after it.
                    "change_from": base,
                    "previous_close": prev,
                    "open": session["open"] if session else None,
                    "day_low": session["low"] if session else None,
                    "day_high": session["high"] if session else None,
                    "volume": int(session["volume"]) if session else None,
                    "session_date": session["ts"].astimezone(ET).date().isoformat() if session else None,
                    "extended_hours": extended,
                    "bid": _f(getattr(q, "bid_price", None)), "ask": _f(getattr(q, "ask_price", None)),
                    "bid_size": _f(getattr(q, "bid_size", None)), "ask_size": _f(getattr(q, "ask_size", None)),
                    "vendor": self.name,
                }
        if coins:
            from alpaca.data.requests import CryptoSnapshotRequest
            pairs = {coin_pair(s): s for s in coins}
            try:
                snaps = self._client("crypto").get_crypto_snapshot(CryptoSnapshotRequest(symbol_or_symbols=list(pairs)))
            except Exception as exc:
                raise self._wrap("crypto snapshots", exc) from exc
            for pair, sym in pairs.items():
                snap = snaps.get(pair)
                trade = getattr(snap, "latest_trade", None)
                price = _f(getattr(trade, "price", None))
                if price is None:
                    continue
                day = getattr(snap, "daily_bar", None)
                prev = _f(getattr(getattr(snap, "previous_daily_bar", None), "close", None))
                out[sym] = {"symbol": sym, "name": pair, "currency": "USD", "price": price,
                            "change": round(price - prev, 6) if prev else None,
                            "change_pct": round(100 * (price - prev) / prev, 2) if prev else None,
                            "previous_close": prev, "open": _f(getattr(day, "open", None)),
                            "day_low": _f(getattr(day, "low", None)), "day_high": _f(getattr(day, "high", None)),
                            "volume": _f(getattr(day, "volume", None)), "quote_source": "Alpaca crypto",
                            "as_of": getattr(trade, "timestamp", None).isoformat() if getattr(trade, "timestamp", None) else None,
                            "vendor": self.name}
        return out

    def quote(self, symbol: str) -> dict | None:
        return self.quotes([symbol]).get(symbol.upper())

    # ── screens ────────────────────────────────────────────────────────────

    def movers(self, top: int = 20) -> dict | None:
        """{most_active, gainers, losers} rows {symbol, name, price,
        change_pct, volume} from the screener, volume from consolidated daily
        bars (the gainers list carries none of its own)."""
        from alpaca.data.requests import MarketMoversRequest, MostActivesRequest
        client = self._client("screener")
        try:
            act = list(getattr(client.get_most_actives(MostActivesRequest(top=100)), "most_actives", []) or [])
            mv = client.get_market_movers(MarketMoversRequest(top=50))
        except Exception as exc:
            raise self._wrap("screener", exc) from exc
        gain, lose = list(getattr(mv, "gainers", []) or []), list(getattr(mv, "losers", []) or [])
        syms = sorted({r.symbol for r in act + gain + lose if common_stock_symbol(r.symbol)})
        quotes = self.quotes(syms) if syms else {}

        def rows(seq, use_screen_change: bool) -> list[dict]:
            out = []
            for r in seq:
                q = quotes.get(r.symbol)
                if not q:
                    continue
                # The screener's own percentage is the REGULAR session's and
                # stops moving with it, so once a stock has an extended-hours
                # print the quote's figure wins (2026-09-22) — otherwise the
                # gainers and losers stood still from the closing bell to the
                # next opening one.
                late = bool(q.get("extended_hours"))
                chg = _f(getattr(r, "percent_change", None)) if (use_screen_change and not late) else None
                row = {"symbol": r.symbol, "name": q.get("name"), "price": q["price"],
                       "change_pct": round(chg, 2) if chg is not None else q.get("change_pct"),
                       "volume": int(_f(getattr(r, "volume", None)) or q.get("volume") or 0)}
                if late:
                    row["extended"] = True
                out.append(row)
            return out
        out: dict[str, Any] = {"most_active": rows(act, False), "gainers": rows(gain, True), "losers": rows(lose, True)}
        try:
            dollar = self.pool_movers()
        except Exception as exc:                   # the other tabs stand without it
            log.debug("alpaca dollar-volume movers: %s", exc)
            dollar = None
        if dollar is None and self.pool_filling():
            out["filling"] = True
        if dollar:
            out["dollar_volume"] = dollar
            # Gainers and losers from the pool too (2026-09-15). Alpaca's top
            # 50 each way are mostly penny stocks and warrants: after the $5
            # and $1M floors five gainers and eight losers were left, and a
            # liquid stock up 8% outside that 50 never showed. The screener's
            # rows stay, so a big move in a small stock still does.
            out["gainers"] = merge_movers(out["gainers"], dollar, up=True)
            out["losers"] = merge_movers(out["losers"], dollar, up=False)
        return out

    def _build_pool(self) -> None:
        """Rank every listed stock by average dollars traded a day over the
        last POOL_SESSIONS sessions and keep those at POOL_MIN_DOLLARS or more.
        Measured 2026-09-15: 12,654 symbols in 26 requests, 4.6s. Runs on a
        background thread."""
        from concurrent.futures import ThreadPoolExecutor
        try:
            universe = sorted(sym for sym, (_, exch) in self._listing().items()
                              if exch in LISTED_EXCHANGES and common_stock_symbol(sym))
            start = (datetime.now(timezone.utc) - timedelta(days=POOL_SESSIONS * 2 + 4)).strftime("%Y-%m-%dT00:00:00Z")

            def chunk(part: list[str]) -> dict[str, list[dict]]:
                out: dict[str, list[dict]] = {}
                token = None
                for _ in range(50):
                    body = self._data_get("/v2/stocks/bars", symbols=",".join(part), timeframe="1Day", start=start,
                                          feed="sip", limit=10000, page_token=token) or {}
                    for sym, bars in (body.get("bars") or {}).items():
                        out.setdefault(sym, []).extend(bars)
                    token = body.get("next_page_token")
                    if not token:
                        break
                return out

            parts = [universe[i:i + 500] for i in range(0, len(universe), 500)]
            bars: dict[str, list[dict]] = {}
            with ThreadPoolExecutor(max_workers=8) as pool:
                for got in pool.map(chunk, parts):
                    bars.update(got)
            built = (time.time(), rank_dollar_volume(bars, POOL_SESSIONS, POOL_MIN_DOLLARS, POOL_MAX))
            self._pool = built
            if self.reader_id and built[1]:
                try:
                    from alphadesk.ledger import store
                    store.save_dollar_pool(self.reader_id, "alpaca", built[1], int(built[0]))
                except Exception as exc:      # an unsaved pool still serves this instance
                    log.debug("alpaca dollar-volume pool not saved: %s", exc)
        except Exception as exc:
            log.warning("alpaca dollar-volume pool: %s", exc)
        finally:
            self._pool_building = False

    def _load_saved_pool(self) -> None:
        """Adopt this reader's saved pool once, so a restart or a fresh
        server instance lists liquid gainers and losers from its first
        answer (2026-09-17). An old pool is still used — the symbols that
        trade $10M a day change slowly — and replaced by the rebuild it
        triggers."""
        if self._pool_loaded or self._pool is not None:
            return
        self._pool_loaded = True
        if not self.reader_id:
            return
        try:
            from alphadesk.ledger import store
            saved = store.get_dollar_pool(self.reader_id, "alpaca")
        except Exception as exc:
            log.debug("alpaca saved pool unreadable: %s", exc)
            return
        if saved and saved[1] and time.time() - saved[0] < POOL_SAVED_MAX_AGE_S:
            self._pool = (float(saved[0]), saved[1])

    def pool_filling(self) -> bool:
        """True while the pool is being built for the first time: the stock
        and ETF movers are thin until it lands, and should be asked again
        soon rather than kept for their usual lifetime."""
        return self._pool is None and self._pool_building

    def pool_movers(self) -> list[dict] | None:
        """The pool's rows with the most dollars traded in the latest
        session, market-wide, most first (2026-09-15) — stocks and funds
        alike; the movers assembly tells them apart.

        Alpaca's screener ranks only by shares or by trades, so its top 100
        by shares is blind to an expensive stock with fewer shares — a $900
        stock trading 5 million shares ($4.5B) never makes it. So the ranking
        runs over a pool instead: every listed symbol averaging POOL_MIN_DOLLARS
        a day lately, built once a day in the background (4.6s), and each call
        prices that pool from snapshots and ranks it by today's volume ×
        volume-weighted price.

        None until the pool is built — the tab appears on the next rebuild
        rather than making this one wait — and None on a key without
        real-time consolidated data, where the day's volume would be one
        exchange's."""
        if self.stock_feed() != "sip":
            return None
        self._load_saved_pool()
        pool = self._pool
        if pool is None or time.time() - pool[0] >= POOL_KEEP_S:
            if not self._pool_building:
                self._pool_building = True
                threading.Thread(target=self._build_pool, name="alpaca-dollar-pool", daemon=True).start()
            if pool is None:
                return None
        memo = self._pool_rows
        if memo and time.time() - memo[0] < POOL_ROWS_KEEP_S:
            return memo[1]
        from alphadesk.config import ET
        from concurrent.futures import ThreadPoolExecutor
        syms = pool[1]
        parts = [syms[i:i + 250] for i in range(0, len(syms), 250)]
        with ThreadPoolExecutor(max_workers=4) as ex:
            snaps: dict[str, dict] = {}
            for got in ex.map(lambda part: self._data_get("/v2/stocks/snapshots", symbols=",".join(part), feed="sip") or {}, parts):
                snaps.update(got)
        rows = snapshot_dollar_rows(snaps, datetime.now(ET).date())
        named = self.names([r["symbol"] for r in rows])
        for r in rows:
            r["name"] = named.get(r["symbol"], (None, None))[0]
        self._pool_rows = (time.time(), rows)
        return rows

    def day_changes(self, symbols: list[str]) -> dict[str, dict] | None:
        """{symbol: {price, change_pct}} for many stocks at once, from raw
        snapshots 500 to a request, four at a time — the change against the
        previous session's close, or the latest session whole before today's
        first bar (snapshot_dollar_rows' rule). Classes are asked with a dot
        (BRK.B) and answered under the name given."""
        from concurrent.futures import ThreadPoolExecutor
        from alphadesk.config import ET
        wanted = sorted({s.upper() for s in symbols if s})
        if not wanted:
            return {}
        feed = self.stock_feed()
        as_alpaca = {s: s.replace("-", ".") for s in wanted}
        back = {v: k for k, v in as_alpaca.items()}
        names = sorted(set(as_alpaca.values()))
        parts = [names[i:i + 500] for i in range(0, len(names), 500)]

        def one(part: list[str]) -> dict:
            try:
                return self._data_get("/v2/stocks/snapshots", symbols=",".join(part), feed=feed) or {}
            except Exception as exc:          # one bad batch does not empty the rest
                log.debug("alpaca day changes: %s", exc)
                return {}
        snaps: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            for got in pool.map(one, parts):
                snaps.update(got)
        rows = snapshot_dollar_rows(snaps, datetime.now(ET).date())
        return {back.get(r["symbol"], r["symbol"]): {"price": r["price"], "change_pct": r["change_pct"],
                                                     "session": r["session"], "turnover": r["turnover"],
                                                     **({"extended": True} if r.get("extended") else {})}
                for r in rows}

    def listed_quotes(self, universe: tuple[tuple[str, str], ...]) -> list[dict]:
        q = self.quotes([s for s, _ in universe])
        return [{**q[s], "name": label} for s, label in universe if s in q]

    def index_board(self) -> list[dict] | None:
        rows = self.listed_quotes(MARKET_ETFS)
        return [{"symbol": r["symbol"], "label": r["name"], "price": r["price"], "change_pct": r.get("change_pct")}
                for r in rows] or None

    def market_tape(self) -> list[dict] | None:
        return self.index_board()

    def crypto_symbols(self) -> frozenset[str] | None:
        """The coins this account can trade against the dollar, as base
        symbols ("BTC"), from Alpaca's asset list; kept a day. The crypto
        list from another vendor is cut to these (2026-09-19, the owner:
        "only show crypto I can trade in alpaca")."""
        hit = self._assets.get("__crypto__")
        if hit and time.time() - hit[0] < 86400:
            return hit[1]
        from alpaca.trading.enums import AssetClass
        from alpaca.trading.requests import GetAssetsRequest
        assets = self._trading(lambda c: c.get_all_assets(GetAssetsRequest(asset_class=AssetClass.CRYPTO)))
        coins = frozenset(str(a.symbol).split("/")[0] for a in assets
                          if str(a.symbol).endswith("/USD") and getattr(a, "tradable", True))
        self._assets["__crypto__"] = (time.time(), coins)
        return coins or None

    def crypto_movers(self, top: int = 20) -> dict | None:
        """Alpaca's USD coins. "all" runs largest coins first (COIN_ORDER, then
        the rest by symbol): Alpaca's volume counts only its own venue —
        Bitcoin 16 coins, about $1.2M, on 2026-09-15 — so it cannot rank the
        market, and the payload says so ("venue_volume")."""
        from alpaca.trading.enums import AssetClass
        from alpaca.trading.requests import GetAssetsRequest
        try:
            assets = self._trading(lambda c: c.get_all_assets(GetAssetsRequest(asset_class=AssetClass.CRYPTO)))
        except ProviderError:
            raise
        pairs = sorted({a.symbol for a in assets if str(a.symbol).endswith("/USD") and getattr(a, "tradable", True)})
        q = self.quotes([p.replace("/", "-") for p in pairs])
        # The change over the last 24 hours, like every crypto venue shows
        # and the column says (2026-09-15). The quote's change runs from
        # Alpaca's last daily bar close, a clock cut crypto does not observe:
        # BTC read -2.48% there against CoinGecko's rolling -3.30%. One
        # request of 1-minute bars over the two hours before that moment, for
        # every coin, sets each base to within a minute (15-minute bars were
        # 0.13 points off on BTC); a coin quiet for two hours shows no change.
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        try:
            from alpaca.data.requests import CryptoBarsRequest
            resp = self._client("crypto").get_crypto_bars(CryptoBarsRequest(
                symbol_or_symbols=pairs, timeframe=self._timeframe(self._INTERVALS["1m"]),
                start=cutoff - timedelta(hours=2), end=cutoff))
            bars = {p: self._rows(resp, p) for p in pairs}
            # A coin that did not trade on Alpaca's venue in those two hours
            # takes its last trade in the day before instead (2026-09-19):
            # USDT traded 4 times in that day, the last five hours early, and
            # showed no change at all. One more request, for those coins only.
            # A coin with no trade in the day (USDG) still shows none.
            quiet = [p for p in pairs if not bars.get(p)]
            if quiet:
                more = self._client("crypto").get_crypto_bars(CryptoBarsRequest(
                    symbol_or_symbols=quiet, timeframe=self._timeframe(self._INTERVALS["1m"]),
                    start=cutoff - timedelta(hours=24), end=cutoff))
                bars.update({p: self._rows(more, p) for p in quiet})
        except Exception as exc:                  # the list stands without the change
            log.debug("alpaca crypto 24h bars: %s", exc)
            bars = {}
        rows = [{"symbol": s, "name": s.split("-")[0], "price": r["price"],
                 "change_pct": rolling_change(r["price"], bars.get(s.replace("-", "/")) or [], now, 1),
                 "volume": r.get("volume") or 0} for s, r in q.items()]
        rank = {c: i for i, c in enumerate(COIN_ORDER)}
        changed = [r for r in rows if r["change_pct"] is not None]
        return {"all": sorted(rows, key=lambda r: (rank.get(r["symbol"].split("-")[0], len(rank)), r["symbol"]))[:top],
                "gainers": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])[:top],
                "losers": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:top]}

    def option_movers(self, top: int = 20) -> dict | None:
        """The busiest option contracts across today's most traded names,
        expiring within OPTION_MOVERS_DAYS, from the reader's chain snapshots —
        OPRA on a paid plan, the indicative feed otherwise. Alpaca has no
        market-wide option screener, so this reads each underlying's near
        chain, six at a time.

        The underlyings are the index funds whose options trade most (SPY,
        QQQ, IWM) plus the OPTION_MOVERS_NAMES symbols with the most dollars
        traded today, from the dollar-volume pool (2026-09-15) — a fixed
        twelve missed names such as MU or COIN on the days their options were
        busiest. Until the pool is priced, and on a key without it, the
        fixed list."""
        from concurrent.futures import ThreadPoolExecutor
        from alphadesk.providers.prices import OPTION_UNDERLYINGS
        until = (date.today() + timedelta(days=OPTION_MOVERS_DAYS)).isoformat()
        try:
            pool = self.pool_movers()
        except Exception as exc:
            log.debug("alpaca option movers pool: %s", exc)
            pool = None
        underlyings = option_underlyings(pool, OPTION_MOVERS_NAMES) if pool else list(OPTION_UNDERLYINGS)

        spot = {r["symbol"]: r.get("price") for r in (pool or [])}

        def one(u: str) -> tuple[list[dict], str | None]:
            # Strikes within OPTION_STRIKE_BAND of the price, where nearly all
            # the day's volume trades: downloading every strike to 45 days was
            # ~76,000 contracts and 5-8s a build (2026-09-15), almost all of it
            # decoding responses.
            band = {}
            if spot.get(u):
                band = {"strike_price_gte": round(spot[u] * (1 - OPTION_STRIKE_BAND), 2),
                        "strike_price_lte": round(spot[u] * (1 + OPTION_STRIKE_BAND), 2)}
            try:
                snaps, feed = self._chain_snapshots(u, expiration_date_lte=until, **band)
            except ProviderError as exc:
                log.debug("alpaca option movers %s: %s", u, exc)
                return [], None
            return option_mover_rows(u, snaps), feed

        with ThreadPoolExecutor(max_workers=OPTION_MOVERS_WORKERS) as workers:
            got = list(workers.map(one, underlyings))
        rows = [r for part, _ in got for r in part]
        if not rows:
            return None
        feeds = {f for _, f in got if f}
        rows.sort(key=lambda r: -r["volume"])
        # Gainers and losers among contracts that traded in size: a far
        # out-of-the-money put going from $0.01 to $0.38 is +3,700% on a
        # handful of contracts, and it filled the whole tab (2026-09-15).
        changed = [r for r in rows if r["change_pct"] is not None and r["volume"] >= OPTION_MOVERS_MIN_VOLUME]
        return {"tabs": [
            {"id": "most_active", "label": "Active", "rows": rows[:max(top, 50)]},
            {"id": "gainers", "label": "Gainers", "rows": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])[:max(top, 50)]},
            {"id": "losers", "label": "Losers", "rows": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:max(top, 50)]},
        ], "source": "alpaca",
            "note": (f"options on today's {len(underlyings)} most traded names" if pool
                     else f"{len(underlyings)} most traded option markets") + f" · expiring within {OPTION_MOVERS_DAYS} days"
                    f" · gainers and losers from {OPTION_MOVERS_MIN_VOLUME:,} contracts"
                    + (" · indicative feed" if feeds == {"indicative"} else "")}

    def category_movers(self, category: str, top: int = 20) -> dict | None:
        """The movers categories a free Alpaca key carries: stocks from the
        screener, ETFs and the market ETFs from snapshots of a broad list,
        and crypto from Alpaca's coins."""
        from alphadesk.ingest.movers import _row, tabs_from_list
        if category == "stocks":
            m = self.movers(top)
            if not m:
                return None
            # Alpaca's screener lists funds with stocks; the assembly takes
            # them out ("funds": "exclude") and the ETF list shows them.
            return {"tabs": [{"id": k, "label": lbl, "rows": m.get(k) or []}
                             for k, lbl in (("most_active", "Active"), ("dollar_volume", "Dollar volume"),
                                            ("gainers", "Gainers"), ("losers", "Losers"))
                             if k in m],
                    "source": "alpaca", "funds": "exclude", "filling": bool(m.get("filling"))}
        if category == "etfs":
            # Market-wide once the pool is priced: the funds among the most
            # traded listed symbols, which the assembly keeps ("funds":
            # "only"). Until then, and on a key without real-time
            # consolidated data, the fixed list below.
            try:
                pool = self.pool_movers()
            except Exception as exc:
                log.debug("alpaca ETF movers from the pool: %s", exc)
                pool = None
            etf_filling = pool is None and self.pool_filling()
            if pool:
                changed = [r for r in pool if r.get("change_pct") is not None]
                return {"tabs": [
                    {"id": "most_active", "label": "Active", "rows": sorted(pool, key=lambda r: -(r.get("volume") or 0))},
                    {"id": "dollar_volume", "label": "Dollar volume", "rows": pool},
                    {"id": "gainers", "label": "Gainers",
                     "rows": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])},
                    {"id": "losers", "label": "Losers",
                     "rows": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])},
                ], "source": "alpaca", "funds": "only"}
        if category in ("etfs", "indices"):
            universe = LISTED_ETFS if category == "etfs" else MARKET_ETFS
            rows = []
            for r in self.listed_quotes(universe):
                row = _row(r["symbol"], r["price"], r.get("change_pct"), r.get("volume"), name=r["name"])
                if r.get("extended_hours"):
                    row["extended"] = True
                rows.append(row)
            if not rows:
                return None
            return {"tabs": tabs_from_list(rows, with_active=True), "source": "alpaca",
                    "note": "ETFs standing in for the indices — an index level is licensed data" if category == "indices" else None,
                    "filling": category == "etfs" and etf_filling}
        if category == "crypto":
            c = self.crypto_movers(top)
            if not c:
                return None
            return {"tabs": [{"id": k, "label": lbl, "rows": c.get(k) or []}
                             for k, lbl in (("all", "All"), ("gainers", "Gainers"), ("losers", "Losers"))],
                    "source": "alpaca", "venue_volume": True}
        if category == "options":
            return self.option_movers(top)
        return None

    # ── options ────────────────────────────────────────────────────────────

    #: Pages of contracts read when listing a whole underlying. SPY carries
    #: thousands: one page of 1,000 covered four days of expiries and the
    #: picker offered nothing beyond this week (2026-09-15). Eight pages
    #: reach a year out on the widest names and stop early on the rest.
    CONTRACT_PAGES = 8

    def _contracts(self, symbol: str, expiry: str | None = None, limit: int = 1000,
                   pages: int = 1) -> list:
        from alpaca.trading.requests import GetOptionContractsRequest
        kw: dict = {"underlying_symbols": [option_underlying(symbol)], "limit": limit}
        if expiry:
            kw["expiration_date"] = expiry
        else:
            kw["expiration_date_gte"] = date.today()
            kw["expiration_date_lte"] = date.today() + timedelta(days=400)
        out: list = []
        token = None
        for _ in range(max(1, pages)):
            if token:
                kw["page_token"] = token
            res = self._trading(lambda c: c.get_option_contracts(GetOptionContractsRequest(**kw)))
            got = list(getattr(res, "option_contracts", []) or [])
            out.extend(got)
            token = getattr(res, "next_page_token", None)
            if not token or not got:
                break
        return out

    def option_expirations(self, symbol: str) -> list[str] | None:
        try:
            rows = self._contracts(symbol, pages=self.CONTRACT_PAGES)
        except ProviderError as exc:
            # A symbol the vendor does not list options for is not a failure
            # of the page: it has no options, and the panel says so.
            if _invalid_symbol(exc):
                return []
            raise
        except Exception as exc:
            if _invalid_symbol(exc):
                return []
            raise self._wrap("option contracts", exc) from exc
        return sorted({str(c.expiration_date) for c in rows})[:60]

    def option_chain(self, symbol: str, expiry: str) -> dict | None:
        from alphadesk.ingest.options import _merge
        sym = symbol.upper()
        try:
            contracts = self._contracts(sym, expiry=expiry)
            snaps, feed = self._chain_snapshots(sym, expiry)
        except ProviderError:
            raise
        except Exception as exc:
            raise self._wrap("option chain", exc) from exc
        calls, puts = _merge(contracts, snaps)
        return {"symbol": sym, "expiry": expiry, "calls": calls, "puts": puts, "vendor": self.name,
                "feed": feed, "realtime": feed == "opra"}

    def _data_get(self, path: str, **params: Any) -> Any:
        """One market-data REST call on this key (header auth, bounded)."""
        from urllib.parse import urlencode

        from alphadesk.providers.prices import _get_json
        self._need_key()
        q = {k: v for k, v in params.items() if v is not None}
        return _get_json(f"https://data.alpaca.markets{path}?{urlencode(q)}",
                         {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.api_secret}, timeout=20.0)

    def _option_snapshots(self, sym: str, feed: str, **filters: Any) -> dict[str, dict]:
        """Every snapshot for an underlying, paged. Read over REST rather than
        alpaca-py: the library's snapshot model drops `dailyBar`, and the day's
        volume is the chain's most-read column (2026-09-14)."""
        out: dict[str, dict] = {}
        token = None
        for _ in range(20):
            body = self._data_get(f"/v1beta1/options/snapshots/{option_underlying(sym)}",
                                  feed=feed, limit=1000, page_token=token, **filters) or {}
            out.update(body.get("snapshots") or {})
            token = body.get("next_page_token")
            if not token:
                break
        return out

    def _chain_snapshots(self, sym: str, expiry: str | None = None, **filters: Any) -> tuple[dict[str, dict], str]:
        """The chain on OPRA when the key has it, else the indicative feed.
        A refusal is remembered six hours so a free key asks once."""
        if expiry:
            filters["expiration_date"] = expiry
        seen = self._opra_seen
        if not (seen and time.time() - seen[0] < PLAN_RECHECK_S and not seen[1]):
            try:
                snaps = self._option_snapshots(sym, "opra", **filters)
                self._opra_seen = (time.time(), True)
                return snaps, "opra"
            except Exception as exc:
                if not _is_opra_refusal(exc):
                    raise
                self._opra_seen = (time.time(), False)
        return self._option_snapshots(sym, "indicative", **filters), "indicative"

    # The flow screener's three reads (2026-09-14): the most active contracts,
    # their trades, and their quotes now. Alpaca keeps no quote HISTORY for
    # options, so a trade's side (at the bid or the ask) is only knowable for
    # a trade seen close to when its quote is read.

    def option_active_contracts(self, symbol: str, days: int = 60, top: int = 40) -> dict | None:
        """The `top` contracts by today's volume among expiries within `days`,
        with each one's volume, open interest and quote."""
        sym = symbol.upper()
        try:
            snaps, feed = self._chain_snapshots(sym, expiration_date_lte=(date.today() + timedelta(days=days)).isoformat())
            contracts = self._contracts(sym)
        except ProviderError:
            raise
        except Exception as exc:
            raise self._wrap("option contracts", exc) from exc
        oi = {getattr(c, "symbol", ""): int(getattr(c, "open_interest", 0) or 0) for c in contracts}
        session = max(((s.get("dailyBar") or {}).get("t") or "")[:10] for s in snaps.values()) if snaps else ""
        rows = []
        for occ, s in snaps.items():
            bar = s.get("dailyBar") or {}
            vol = int(bar.get("v") or 0) if (bar.get("t") or "")[:10] == session else 0
            if vol:
                rows.append({"symbol": occ, "volume": vol, "open_interest": oi.get(occ, 0)})
        rows.sort(key=lambda r: -r["volume"])
        return {"symbol": sym, "feed": feed, "session": session, "contracts": rows[:top]}

    def option_trades(self, symbols: list[str], start: str) -> list[dict] | None:
        """Every trade in `symbols` since `start` (ISO), oldest first."""
        out: list[dict] = []
        token = None
        for _ in range(40):
            body = self._data_get("/v1beta1/options/trades", symbols=",".join(symbols), start=start,
                                  limit=10000, sort="asc", page_token=token) or {}
            for occ, rows in (body.get("trades") or {}).items():
                out.extend({"symbol": occ, "t": r.get("t"), "price": _f(r.get("p")), "size": int(r.get("s") or 0),
                            "exchange": r.get("x"), "condition": r.get("c")} for r in rows or [])
            token = body.get("next_page_token")
            if not token:
                break
        return out

    def stock_minute_closes(self, symbol: str, start: datetime) -> dict[str, float] | None:
        """{"YYYY-MM-DDTHH:MM" (UTC): close} for one stock since `start`, on
        the key's own stock feed — the stock's price at an option trade's
        minute, for the flow screener."""
        bars, _ = self.stock_bars(symbol, self._INTERVALS["1m"], start, feed=self.stock_feed())
        return {b["ts"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M"): b["close"] for b in bars.get(symbol.upper(), [])}

    def option_latest_quotes(self, symbols: list[str]) -> dict[str, dict] | None:
        """{contract: {bid, ask, t}} now, on OPRA when the key has it."""
        feed = "indicative" if (self._opra_seen and not self._opra_seen[1]) else "opra"
        body = self._data_get("/v1beta1/options/quotes/latest", symbols=",".join(symbols), feed=feed) or {}
        return {occ: {"bid": _f(q.get("bp")), "ask": _f(q.get("ap")), "t": q.get("t")}
                for occ, q in (body.get("quotes") or {}).items()}

    # ── research context ───────────────────────────────────────────────────

    def context(self, symbol: str) -> dict | None:
        """Price and liquidity context over the last ninety sessions."""
        sym = symbol.upper()
        if coin_pair(sym):
            return None
        got, _ = self.stock_bars(sym, self._INTERVALS["1d"], datetime.now(timezone.utc) - timedelta(days=140))
        bars = got.get(sym, [])[-90:]
        if len(bars) < 2:
            return None
        closes = [b["close"] for b in bars]
        trs = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"]))
               for p, b in zip(bars, bars[1:])]
        last, prev = bars[-1], bars[-2]
        dv = [b["close"] * b["volume"] for b in bars[-20:]]
        avg_vol = sum(b["volume"] for b in bars[-21:-1]) / max(1, len(bars[-21:-1]))
        return {"symbol": sym, "price": last["close"], "prev_close": prev["close"],
                "change_pct": round(100 * (last["close"] / prev["close"] - 1), 2) if prev["close"] else None,
                "volume": last["volume"], "high_90d": max(b["high"] for b in bars), "low_90d": min(b["low"] for b in bars),
                "avg_dollar_volume": round(sum(dv) / len(dv)) if dv else None,
                "relative_volume": round(last["volume"] / avg_vol, 2) if avg_vol else None,
                "atr_14": round(sum(trs[-14:]) / len(trs[-14:]), 4) if trs else None,
                "closes_10": closes[-10:], "vendor": self.name}


from alphadesk.providers.registry import register  # noqa: E402

register("prices", AlpacaPrices.name, AlpacaPrices)
