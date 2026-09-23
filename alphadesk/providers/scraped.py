"""SCRAPED SOURCES — data read from a public web endpoint rather than from a
vendor's API under the reader's key (2026-09-22, the owner's call, reopening
what was closed on 2026-09-13).

A scraped source is a vendor like any other on the seam: it registers under a
name, the per-reader router asks it, and the reader switches it on and off on
the Account page. Two things make it different, and both are deliberate:

  IT CARRIES NO KEY. There is nothing to paste, so the Account page offers a
  button rather than a field, and the stored row holds an empty config. That
  is the whole of "connecting" one.

  IT SAYS WHAT IT IS, EVERYWHERE. A scraped class sets `official = False`, and
  that marker travels with every answer: the panel's source line, the movers
  payload, and the agent tools all name the source and whether it is official.
  A figure read off a public page must never be mistaken for one delivered
  under a licence — by the reader, and especially not by an agent reasoning
  over the numbers.

WHAT THE MARKER DOES NOT DO: telling a reader (or an agent) that a figure was
scraped protects their reasoning. It is not consent from the site, and it does
not move the terms question. That is why the router asks every keyed vendor
FIRST — a scraped source is a fallback for a surface the reader has no key
for, never a substitute for one they have.

Ordering falls out of the catalogue without a special case: the router asks
the vendors a surface lists, in order, and only then any other connected
vendor that has the method. A scraped source is not listed on any surface, so
it is always asked last.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from alphadesk.providers.base import ProviderError
from alphadesk.providers.registry import register

log = logging.getLogger("alphadesk.providers.scraped")

#: Seconds between requests to one scraped host, process-wide. A public
#: endpoint has no plan to meter us, which is a reason to be slower than a
#: keyed vendor rather than faster: one request every 0.4s is a pace a person
#: with a browser could plausibly produce, and it keeps a board full of tiles
#: from arriving as a burst.
_MIN_GAP_S = 0.4
_gate = threading.Lock()
_last_at = 0.0


def _slot() -> None:
    """Reserve the next send slot. Held across every scraped provider."""
    global _last_at
    with _gate:
        wait = _last_at + _MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_at = time.monotonic()


def _get_json(url: str, timeout: float = 20.0) -> Any:
    """One bounded GET against a public endpoint, paced. No credential rides
    with it — that is what makes this a scraped source and not a vendor."""
    import json as _json
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    _slot()
    req = Request(url, headers={"User-Agent": "AlphaDesk/1.0 (market research terminal)",
                                "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        # A public endpoint answers 401/403/429 when it does not want to be
        # read this way. That is not a plan refusal to route around — it is
        # this source declining, and the router should move on.
        raise ProviderError(f"scraped source refused ({exc.code})") from exc
    except (URLError, ValueError, TimeoutError) as exc:
        raise ProviderError(f"scraped source unreachable: {exc}") from exc


def _get_text(url: str, timeout: float = 20.0) -> str:
    """The same bounded, paced GET for a source that answers XML or CSV."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    _slot()
    req = Request(url, headers={"User-Agent": "AlphaDesk/1.0 (market research terminal)",
                                "Accept": "application/xml, text/xml, text/plain, */*"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        raise ProviderError(f"scraped source refused ({exc.code})") from exc
    except (URLError, TimeoutError) as exc:
        raise ProviderError(f"scraped source unreachable: {exc}") from exc


def _rfc822(text: str) -> str | None:
    """"Tue, 22 Sep 2026 11:14:40 +0000" as an ISO instant. Pure."""
    from email.utils import parsedate_to_datetime
    try:
        at = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None                  # NaN is a gap in the series
    except (TypeError, ValueError):
        return None


class YahooPrices:
    """Charts and quotes read from Yahoo's public chart endpoint.

    One request answers a whole series AND the quote that goes with it, so a
    chart costs one call and a board of quotes costs one per symbol. Extended
    hours come with it, which is what the endpoint calls pre- and post-market:
    the series carries them and the quote states the last print either way.
    """

    name = "yahoo"
    label = "Yahoo Finance"
    #: Surfaces this source is the ONLY one for, in words — things no vendor
    #: in the catalogue carries, so the Account page can say whether
    #: switching it on would give the reader anything at all (2026-09-23).
    #: Yahoo has none: charts, quotes and daily history are all catalogued,
    #: so a reader with any price vendor keyed will never reach it.
    EXCLUSIVE: tuple[str, ...] = ()
    #: Read off a public page, not delivered under a key. Provenance reads it.
    official = False

    _BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

    #: What this endpoint serves, and how far back each reaches — its own
    #: published limits, not ours: one-minute bars stop at 7 days, every other
    #: intraday size at 60, and daily bars run to the start of the listing.
    _INTERVALS: dict[str, dict] = {
        "1m": {"n": 1, "unit": "Min", "max_days": 7, "label": "1 min"},
        "2m": {"n": 2, "unit": "Min", "max_days": 60, "label": "2 mins"},
        "5m": {"n": 5, "unit": "Min", "max_days": 60, "label": "5 mins"},
        "15m": {"n": 15, "unit": "Min", "max_days": 60, "label": "15 mins"},
        "30m": {"n": 30, "unit": "Min", "max_days": 60, "label": "30 mins"},
        "1h": {"n": 1, "unit": "Hour", "max_days": 730, "label": "1 hour"},
        "1d": {"n": 1, "unit": "Day", "max_days": None, "label": "1 day"},
        "1wk": {"n": 1, "unit": "Week", "max_days": None, "label": "1 week"},
        "1mo": {"n": 1, "unit": "Month", "max_days": None, "label": "1 month"},
    }

    #: The app's interval ids that this endpoint does not serve, mapped to the
    #: nearest COARSER one it does. The payload reports what was served, so a
    #: reader whose saved preference is a four-hour bar sees hourly and is told.
    _SUBSTITUTE = {"1s": "1m", "5s": "1m", "10s": "1m", "15s": "1m", "30s": "1m",
                   "3m": "5m", "10m": "15m", "2h": "1h", "4h": "1h"}

    #: Which range string to ask for, per the app's range key.
    _RANGE = {"1D": "1d", "5D": "5d", "1M": "1mo", "3M": "3mo", "6M": "6mo",
              "YTD": "ytd", "1Y": "1y", "5Y": "5y", "MAX": "max"}

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        # Both ignored: a scraped source takes no credential. The signature
        # matches every other provider so the registry builds it the same way.
        self.reader_id: str | None = None

    # ── the endpoint ───────────────────────────────────────────────────────

    def _chart(self, symbol: str, rng: str, interval: str) -> dict | None:
        url = (f"{self._BASE}/{symbol}?range={rng}&interval={interval}"
               f"&includePrePost=true&events=div%2Csplit")
        try:
            body = _get_json(url)
        except ProviderError as exc:
            log.debug("yahoo chart %s %s/%s: %s", symbol, rng, interval, exc)
            return None
        chart = (body or {}).get("chart") or {}
        if chart.get("error"):
            return None
        results = chart.get("result") or []
        return results[0] if results else None

    @staticmethod
    def _bars(result: dict) -> list[dict]:
        """The result's OHLCV arrays as bars, oldest first, gaps dropped.

        The arrays are parallel and Yahoo writes null into every one of them
        for a minute that did not trade, so a bar is kept only where the close
        is a real number — a null close read as zero would draw the price
        falling to nothing."""
        stamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens, highs = quote.get("open") or [], quote.get("high") or []
        lows, closes = quote.get("low") or [], quote.get("close") or []
        vols = quote.get("volume") or []
        bars = []
        for i, at in enumerate(stamps):
            close = _f(closes[i]) if i < len(closes) else None
            if close is None:
                continue
            bars.append({
                "ts": datetime.fromtimestamp(int(at), tz=timezone.utc),
                "open": _f(opens[i]) if i < len(opens) else close,
                "high": _f(highs[i]) if i < len(highs) else close,
                "low": _f(lows[i]) if i < len(lows) else close,
                "close": close,
                "volume": (_f(vols[i]) if i < len(vols) else 0.0) or 0.0,
            })
        bars.sort(key=lambda b: b["ts"])
        return bars

    # ── the contract ───────────────────────────────────────────────────────

    def chart_intervals(self) -> dict[str, dict]:
        return self._INTERVALS

    def _wanted(self, range_key: str, interval: str | None) -> str:
        if interval and interval in self._INTERVALS:
            return interval
        if interval and interval in self._SUBSTITUTE:
            return self._SUBSTITUTE[interval]
        return "1m" if range_key == "1D" else "5m" if range_key == "5D" else "1d"

    def chart_series(self, symbol: str, days: int = 2, range_key: str | None = None,
                     interval: str | None = None, before: datetime | None = None,
                     need: int | None = None) -> dict | None:
        from alphadesk.ingest import prices as ip

        # This endpoint answers a range ending NOW; it cannot be asked for a
        # window that ended in the past, so panning left past the oldest bar
        # is not something this source can serve. Answering None is the
        # contract's own way of saying the history ends here.
        if before is not None:
            return None
        sym = symbol.upper()
        rk = (range_key or "1D").upper()
        served = self._wanted(rk, interval)
        rng = self._RANGE.get(rk, "1d")
        # A range deeper than the interval reaches would be answered with a
        # short series that looked like a thin feed rather than a limit, so
        # the coarser bar is served and the payload reports which.
        reach = self._INTERVALS[served]["max_days"]
        while reach is not None and ip.RANGE_DAYS.get(rk, days) > reach:
            nxt = {"1m": "5m", "2m": "5m", "5m": "15m", "15m": "30m",
                   "30m": "1h", "1h": "1d", "1d": "1wk", "1wk": "1mo"}.get(served)
            if not nxt:
                break
            served = nxt
            reach = self._INTERVALS[served]["max_days"]

        result = self._chart(sym, rng, served)
        if not result:
            return None
        bars = self._bars(result)
        if not bars:
            return None
        stats = None if served in ("1m", "2m") else ip._daily_coverage(bars)
        return ip.build_series_payload(sym, bars, served, range_key=rk,
                                       interval=interval, stats=stats)

    def context(self, symbol: str) -> dict | None:
        """Last price and the day's shape, from the one-day chart's own
        summary block."""
        result = self._chart(symbol.upper(), "1d", "1m")
        meta = (result or {}).get("meta") or {}
        price = _f(meta.get("regularMarketPrice"))
        prev = _f(meta.get("chartPreviousClose")) or _f(meta.get("previousClose"))
        if price is None:
            return None
        return {"symbol": meta.get("symbol") or symbol.upper(), "price": price,
                "change_pct": round(100 * (price / prev - 1), 2) if prev else None,
                "prev_close": prev,
                "day_low": _f(meta.get("regularMarketDayLow")),
                "day_high": _f(meta.get("regularMarketDayHigh")),
                "volume": _f(meta.get("regularMarketVolume"))}

    def quote(self, symbol: str) -> dict | None:
        return (self.quotes([symbol]) or {}).get(symbol.upper())

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        """One request per symbol — this endpoint takes one at a time. The
        pacing gate above is what keeps a wide board civil."""
        out: dict[str, dict] = {}
        for raw in symbols:
            sym = (raw or "").upper()
            if not sym:
                continue
            result = self._chart(sym, "1d", "1m")
            meta = (result or {}).get("meta") or {}
            price = _f(meta.get("regularMarketPrice"))
            prev = _f(meta.get("chartPreviousClose")) or _f(meta.get("previousClose"))
            if price is None:
                continue
            # The endpoint states the regular close and, separately, the last
            # print outside the session. The headline change is measured from
            # the last close BEFORE the price shown, which is the rule every
            # other source here follows (2026-09-22).
            bars = self._bars(result or {})
            last = bars[-1]["close"] if bars else price
            extended = None
            session_end = _f(meta.get("regularMarketTime"))
            latest = bars[-1]["ts"].timestamp() if bars else None
            if session_end and latest and latest > session_end and abs(last - price) > 1e-9:
                extended = {"price": last, "change_pct": round(100 * (last / price - 1), 2),
                            "from_close": price,
                            "as_of": datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()}
            shown = extended["price"] if extended else price
            base = price if extended else prev
            dp = 4 if shown < 1 else 2
            out[sym] = {
                "symbol": sym, "name": meta.get("longName") or meta.get("shortName") or sym,
                "exchange": meta.get("exchangeName"), "exchange_name": meta.get("fullExchangeName")
                or meta.get("exchangeName"),
                "currency": meta.get("currency") or "USD",
                "price": round(shown, dp),
                "change": round(shown - base, dp) if base else None,
                "change_pct": round(100 * (shown - base) / base, 2) if base else None,
                "change_from": base,
                "previous_close": prev,
                "open": bars[0]["open"] if bars else None,
                "day_low": _f(meta.get("regularMarketDayLow")),
                "day_high": _f(meta.get("regularMarketDayHigh")),
                "volume": _f(meta.get("regularMarketVolume")),
                "extended_hours": extended,
                "quote_source": "Yahoo Finance · scraped",
                "vendor": self.name,
                # Read off a public page, not licensed to the reader.
                "official": False,
            }
        return out

    def daily_history(self, symbols: list[str], sessions: int = 21) -> dict[str, list[dict]]:
        """Daily bars for several symbols, for the twenty-session volatility
        and liquidity figures the movers tables carry."""
        span = "1mo" if sessions <= 21 else "3mo" if sessions <= 65 else "1y"
        out: dict[str, list[dict]] = {}
        for raw in symbols:
            sym = (raw or "").upper()
            if not sym:
                continue
            result = self._chart(sym, span, "1d")
            bars = self._bars(result or {}) if result else []
            if bars:
                out[sym] = bars[-sessions:]
        return out

    def search_symbols(self, query: str, limit: int = 10) -> list[dict] | None:
        """Not carried: the SEC listing already answers this keylessly, and
        it is the one the picker and the agent's symbol lookup share."""
        return None


class NasdaqCalendars:
    """The four corporate calendars — earnings, dividends, splits and new
    listings — from the routes Nasdaq's own calendar pages read.

    These are the calendars a reader with no key cannot otherwise see: the
    keyed vendors that carry them are a paid plan or a free one that omits
    the session. Nasdaq states the SESSION outright ("time-pre-market"),
    which is the one fact the earnings calendar otherwise has to infer from
    a company's filing history.

    EACH CALENDAR IS A DAY AT A TIME, so a window costs one request per day
    and the pacing gate above spaces them. A window wider than
    `_MAX_DAYS` is refused rather than served slowly and partially — the
    router then moves on and the panel says what it could not fill, which is
    truer than a calendar missing its later half without saying so.
    """

    name = "nasdaq"
    label = "Nasdaq calendars"
    official = False
    #: The calendars are all catalogue surfaces FMP and Finnhub carry; the
    #: halts are carried by nobody, which is the reason this source exists
    #: for a reader who already pays for calendars.
    EXCLUSIVE: tuple[str, ...] = ("Trading halts and resumptions",)

    _BASE = "https://api.nasdaq.com/api"
    #: Days a range request may span. Three weeks is the earnings window the
    #: calendar asks for (-14/+7); beyond that the cost is the reader's
    #: patience rather than a vendor's bill, and it is still too long.
    _MAX_DAYS = 31

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.reader_id: str | None = None

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _days(start: str, end: str) -> list[str] | None:
        """Every calendar day in the window, or None when it is too wide."""
        from datetime import date as _date
        try:
            a = _date.fromisoformat(start[:10])
            b = _date.fromisoformat(end[:10])
        except ValueError:
            return None
        if b < a or (b - a).days > NasdaqCalendars._MAX_DAYS:
            return None
        out, day = [], a
        while day <= b:
            # Weekends carry no corporate calendar, so they are not asked for.
            if day.weekday() < 5:
                out.append(day.isoformat())
            day += timedelta(days=1)
        return out

    @staticmethod
    def _us_date(value: Any) -> str | None:
        """Nasdaq writes dates as M/D/YYYY; the app speaks ISO throughout."""
        from datetime import datetime as _dt
        text = str(value or "").strip()
        if not text or text.upper() in ("N/A", "--"):
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return _dt.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _money(value: Any) -> float | None:
        """A figure Nasdaq writes for a page — "$78,656,864,000", "N/A"."""
        text = str(value or "").replace("$", "").replace(",", "").strip()
        return _f(text) if text and text.upper() not in ("N/A", "--") else None

    def _rows(self, path: str, holder: str = "rows") -> list[dict]:
        body = _get_json(f"{self._BASE}/{path}")
        data = (body or {}).get("data") or {}
        if holder != "rows" and isinstance(data.get(holder), dict):
            data = data[holder]
        rows = data.get("rows")
        return [r for r in (rows or []) if isinstance(r, dict)]

    # ── the calendars ──────────────────────────────────────────────────────

    def earnings_calendar(self, start: str, end: str, symbol: str | None = None) -> list[dict] | None:
        """The market's reporters, day by day, WITH the session each states.

        One company is not asked for separately: this route is a day's list,
        so a single symbol is that reader's window filtered — which is what
        the caller does with the result anyway."""
        days = self._days(start, end)
        if days is None:
            return None
        # "time-pre-market" / "time-after-hours" / "time-not-supplied".
        session = {"time-pre-market": "BMO", "time-after-hours": "AMC"}
        want = (symbol or "").upper()
        out: list[dict] = []
        for day in days:
            try:
                rows = self._rows(f"calendar/earnings?date={day}")
            except ProviderError as exc:
                log.debug("nasdaq earnings %s: %s", day, exc)
                continue
            for r in rows:
                sym = str(r.get("symbol") or "").upper()
                if not sym or (want and sym != want):
                    continue
                when = session.get(str(r.get("time") or "").lower())
                out.append({"symbol": sym, "report_date": day, "session": when,
                            # A stated session is the company's own schedule,
                            # not a guess; a missing one stays silent so the
                            # calendar predicts it from filing history.
                            "confirmed": when is not None,
                            "eps_estimate": self._money(r.get("epsForecast")),
                            "eps_actual": None,
                            "revenue_estimate": None, "revenue_actual": None,
                            "market_cap": self._money(r.get("marketCap")),
                            "source": self.name})
        return out or None

    def dividend_calendar(self, start: str, end: str) -> list[dict] | None:
        days = self._days(start, end)
        if days is None:
            return None
        out: list[dict] = []
        for day in days:
            try:
                rows = self._rows(f"calendar/dividends?date={day}", holder="calendar")
            except ProviderError as exc:
                log.debug("nasdaq dividends %s: %s", day, exc)
                continue
            for r in rows:
                sym = str(r.get("symbol") or "").upper()
                ex = self._us_date(r.get("dividend_Ex_Date"))
                if not sym or not ex:
                    continue
                out.append({"symbol": sym, "ex_date": ex,
                            "record_date": self._us_date(r.get("record_Date")),
                            "payment_date": self._us_date(r.get("payment_Date")),
                            "declaration_date": self._us_date(r.get("announcement_Date")),
                            "amount": _f(r.get("dividend_Rate")),
                            # Nasdaq states the cash rate only; an adjusted
                            # figure would be ours to compute, so it is absent
                            # rather than invented.
                            "adjusted_amount": None,
                            "annual_amount": _f(r.get("indicated_Annual_Dividend")),
                            "source": self.name})
        return out or None

    def split_calendar(self, start: str, end: str) -> list[dict] | None:
        """Splits, asked for ONCE and filtered here.

        Unlike the earnings and dividend routes, this one IGNORES the date it
        is given and answers the same upcoming list every time (measured
        2026-09-22: a six-day window returned thirteen distinct splits six
        times over, some of them weeks past the window's end). Asking per day
        would have put every split in the calendar six times and added dates
        nobody asked for. One request, filtered to the window, is both correct
        and cheaper — the shape of the answer decides the shape of the ask."""
        if self._days(start, end) is None:          # the same width guard
            return None
        try:
            rows = self._rows("calendar/splits?date=" + start[:10])
        except ProviderError as exc:
            log.debug("nasdaq splits: %s", exc)
            return None
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            when = self._us_date(r.get("executionDate"))
            # "3 : 1" — the ratio as the page prints it.
            parts = [_f(x) for x in str(r.get("ratio") or "").split(":")]
            if not sym or not when or len(parts) != 2 or not all(parts):
                continue
            if not (start[:10] <= when <= end[:10]) or (sym, when) in seen:
                continue
            seen.add((sym, when))
            out.append({"symbol": sym, "date": when, "to": parts[0], "from": parts[1],
                        "kind": None, "source": self.name})
        return out or None

    #: Why a stock stopped trading, in the exchange's own vocabulary. Only
    #: codes whose meaning is published are spelled out; anything else is
    #: handed over as the bare code rather than guessed at.
    _HALT_REASONS = {
        "T1": "News pending",
        "T2": "News released",
        "T3": "News released — resumption times set",
        "T6": "Extraordinary market activity",
        "T8": "Exchange-traded fund halt",
        "T12": "Additional information requested by the exchange",
        "H4": "Non-compliance with exchange listing rules",
        "H9": "Not current in its required filings",
        "H10": "SEC trading suspension",
        "H11": "Regulatory concern",
        "O1": "Operational halt",
        "LUDP": "Volatility pause (limit up–limit down)",
        "LUDS": "Volatility pause — straddle condition",
        "MWC1": "Market-wide circuit breaker, level 1",
        "MWC2": "Market-wide circuit breaker, level 2",
        "MWC3": "Market-wide circuit breaker, level 3",
        "MWC0": "Market-wide circuit breaker — carried over from the prior day",
        "IPO1": "New issue not yet trading",
        "IPOQ": "New issue — quotation period",
    }

    def trading_halts(self, limit: int = 100) -> list[dict] | None:
        """TODAY'S TRADING HALTS AND RESUMPTIONS, newest first.

        A halt is a catalyst with its own clock: the exchange stopped the
        stock at a stated time for a stated reason, and said when quoting and
        trading would resume. Nothing else here carries it — it is not a
        price, not a filing and not a story — and no keyed vendor in the
        catalogue serves it either.

        The record is handed over whole, reason CODE included, with the
        exchange's own wording beside it only where that wording is
        published. A code nobody publishes stays a code."""
        from alphadesk.config import ET
        # A FAILED READ IS NOT "I DO NOT CARRY THIS" (2026-09-23). Returning
        # None here told the router this source has no such surface, so it
        # moved on, found nobody else — nobody sells this — and the panel
        # showed nothing. A source switched ON but unreachable then looked
        # exactly like a quiet day. The error travels instead.
        body = _get_text("https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts")
        out: list[dict] = []
        for chunk in re.findall(r"<item>(.*?)</item>", body, re.S):
            def field(tag: str) -> str:
                m = re.search(rf"<ndaq:{tag}>(.*?)</ndaq:{tag}>", chunk, re.S)
                return (m.group(1) or "").strip() if m else ""
            sym = field("IssueSymbol").upper()
            day, at = self._us_date(field("HaltDate")), field("HaltTime")
            if not sym or not day or not at:
                continue
            code = field("ReasonCode").upper()
            # The exchange states its times in New York, without saying so.
            halted_at = f"{day}T{at[:8]}" if len(at) >= 8 else None
            resumed_on = self._us_date(field("ResumptionDate"))
            trade_at = field("ResumptionTradeTime")
            out.append({
                "symbol": sym, "name": field("IssueName") or None,
                "market": field("Market") or None,
                "reason_code": code or None,
                "reason": self._HALT_REASONS.get(code) or None,
                "halted_at": halted_at, "timezone": str(ET),
                "resumption_quote_at": (f"{resumed_on}T{field('ResumptionQuoteTime')[:8]}"
                                        if resumed_on and field("ResumptionQuoteTime") else None),
                "resumption_trade_at": (f"{resumed_on}T{trade_at[:8]}"
                                        if resumed_on and trade_at else None),
                # Still halted when the exchange has named no resumption.
                "resumed": bool(resumed_on and trade_at),
                "pause_threshold_price": _f(field("PauseThresholdPrice")) or None,
                "source": self.name,
            })
        # Newest first. The same stock can be halted several times in a day —
        # each pause is its own event and none of them is a duplicate.
        out.sort(key=lambda r: r["halted_at"] or "", reverse=True)
        return out[:max(1, min(int(limit), 500))] or None

    def ipo_calendar(self, start: str, end: str) -> list[dict] | None:
        """New listings. This route is a MONTH at a time and answers four
        lists; the priced and upcoming ones are the listings a reader is
        looking for, and a filed or withdrawn registration is not a date."""
        from datetime import date as _date
        try:
            a, b = _date.fromisoformat(start[:10]), _date.fromisoformat(end[:10])
        except ValueError:
            return None
        if b < a or (b - a).days > 370:
            return None
        months, cursor = [], a.replace(day=1)
        while cursor <= b and len(months) < 14:
            months.append(cursor.strftime("%Y-%m"))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        out: list[dict] = []
        for month in months:
            try:
                body = _get_json(f"{self._BASE}/ipo/calendar?date={month}")
            except ProviderError as exc:
                log.debug("nasdaq ipo %s: %s", month, exc)
                continue
            data = (body or {}).get("data") or {}
            for holder in ("priced", "upcoming"):
                block = data.get(holder) or {}
                rows = block.get("rows") or (block.get("upcomingTable") or {}).get("rows") or []
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    when = self._us_date(r.get("pricedDate") or r.get("expectedPriceDate"))
                    if not when or not (start[:10] <= when <= end[:10]):
                        continue
                    price = self._money(r.get("proposedSharePrice"))
                    out.append({"symbol": str(r.get("proposedTickerSymbol") or "").upper() or None,
                                "date": when, "company": r.get("companyName") or None,
                                "exchange": r.get("proposedExchange") or None,
                                "status": r.get("dealStatus") or holder,
                                "shares": self._money(r.get("sharesOffered")),
                                "price_low": price, "price_high": price,
                                "market_cap": self._money(r.get("dollarValueOfSharesOffered")),
                                "source": self.name})
        return out or None


class SocialPulse:
    """WHAT PEOPLE ARE POSTING AND WATCHING (2026-09-22).

    THIS IS THE ONE SOURCE ANYONE CAN WRITE INTO ON PURPOSE. An exchange, the
    SEC and a federal agency are accountable for what they publish; a social
    post is accountable to nobody, and a post reading "(NASDAQ: XYZ)
    announces merger" costs nothing to write. That makes this the only feed
    here that is a manipulation surface as well as a signal, and three
    decisions follow from it:

      IT IS OFF UNTIL A READER SWITCHES IT ON, like every scraped source and
      unlike the government feeds, which are on for everyone.

      NO TICKER IS EXTRACTED FROM POST TEXT. A ticker inside a post is the
      AUTHOR'S CLAIM about which company the post concerns, not a fact, and
      tagging it would route an unverified assertion into that symbol's
      context. The text is handed over whole and the reader's agent decides.

      ATTENTION IS NOT NEWS. The trending list below is StockTwits' own
      ranking of what is being watched and posted about. Manufactured
      attention is precisely what a pump is, so a symbol trending is
      evidence that people are talking, and evidence of nothing else.
    """

    name = "social"
    label = "Social posts and attention"
    official = False
    #: No vendor in the catalogue sells either of these, so this source is
    #: reachable whatever the reader has keyed.
    EXCLUSIVE: tuple[str, ...] = ("Social posts", "Trending symbols")

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.reader_id: str | None = None

    def social_posts(self, limit: int = 20) -> list[dict] | None:
        """Recent posts from the Truth Social account mirror at
        trumpstruth.org, newest first.

        A MIRROR, NOT THE SOURCE. Truth Social's own API refuses us (403,
        measured 2026-09-22), so this is a third party's copy: it can lag,
        it can miss posts, and it is not the account itself. The row says so
        rather than presenting the mirror as the platform."""
        # A FAILED READ IS NOT "I DO NOT CARRY THIS" (2026-09-23). Returning
        # None here told the router this source has no such surface, so it
        # moved on, found nobody else — nobody sells this — and the panel
        # showed nothing. A source switched ON but unreachable then looked
        # exactly like a quiet day. The error travels instead.
        body = _get_text("https://trumpstruth.org/feed")
        out: list[dict] = []
        for chunk in re.findall(r"<item>(.*?)</item>", body, re.S):
            def field(tag: str) -> str:
                m = re.search(rf"<{tag}>(.*?)</{tag}>", chunk, re.S)
                text = (m.group(1) if m else "").strip()
                inner = re.match(r"^<!\[CDATA\[(.*?)\]\]>$", text, re.S)
                return (inner.group(1) if inner else text).strip()
            when, link = field("pubDate"), field("link")
            text = re.sub(r"<[^>]+>", " ", field("description"))
            text = re.sub(r"\s+", " ", text).strip()
            at = _rfc822(when)
            if not at or not text:
                continue
            out.append({"at": at, "text": text, "url": link or None,
                        "account": "realDonaldTrump", "platform": "Truth Social",
                        "via": "trumpstruth.org (mirror)",
                        # Said on every row, not only in the tool description:
                        # whatever reads this next must not act on it.
                        "trust": "unverified: anyone may write a social post, "
                                 "and this is a third party's copy of one",
                        "source": self.name})
        out.sort(key=lambda r: r["at"], reverse=True)
        return out[:max(1, min(int(limit), 100))] or None

    def social_trending(self, limit: int = 30) -> list[dict] | None:
        """The symbols StockTwits says are being talked about, in ITS rank
        order with ITS figures — never a score of ours (invariant 3)."""
        import json as _json
        try:
            body = _get_text("https://api.stocktwits.com/api/2/trending/symbols.json")
            data = _json.loads(body)
        # A FAILED READ IS NOT "I DO NOT CARRY THIS" (2026-09-23). Returning
        # None here told the router this source has no such surface, so it
        # moved on, found nobody else — nobody sells this — and the panel
        # showed nothing. A source switched ON but unreachable then looked
        # exactly like a quiet day. The error travels instead.
        except ValueError as exc:                 # a body that is not JSON
            raise ProviderError(f"scraped source answered unreadably: {exc}") from exc
        out = []
        for row in (data or {}).get("symbols") or []:
            sym = str(row.get("symbol") or "").upper()
            if not sym:
                continue
            out.append({"symbol": sym, "name": row.get("title") or None,
                        # The vendor's own numbers, passed through.
                        "rank": _f(row.get("rank")),
                        "watchers": _f(row.get("watchlist_count")),
                        "sector": row.get("sector") or None,
                        "industry": row.get("industry") or None,
                        "measures": "attention, not news — how many are watching "
                                    "and posting, which can be manufactured",
                        "source": self.name})
        return out[:max(1, min(int(limit), 100))] or None


register("prices", YahooPrices.name, YahooPrices)
register("prices", NasdaqCalendars.name, NasdaqCalendars)
register("prices", SocialPulse.name, SocialPulse)

#: Every scraped source registered here, by the name the router knows it by.
#: The Account page reads it to offer a button instead of a key field, and
#: provenance reads it to mark an answer.
SCRAPED_SOURCES: dict[str, type] = {YahooPrices.name: YahooPrices,
                                    NasdaqCalendars.name: NasdaqCalendars,
                                    SocialPulse.name: SocialPulse}


def is_scraped(vendor: str | None) -> bool:
    """True when a vendor name belongs to a scraped source. The one place
    that question is answered, so a panel, a payload and an agent tool all
    agree on it."""
    return bool(vendor) and vendor in SCRAPED_SOURCES


__all__ = ["SCRAPED_SOURCES", "NasdaqCalendars", "SocialPulse", "YahooPrices", "is_scraped"]
