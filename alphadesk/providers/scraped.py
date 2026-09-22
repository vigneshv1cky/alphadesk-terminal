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
import threading
import time
from datetime import datetime, timezone
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


register("prices", YahooPrices.name, YahooPrices)

#: Every scraped source registered here, by the name the router knows it by.
#: The Account page reads it to offer a button instead of a key field, and
#: provenance reads it to mark an answer.
SCRAPED_SOURCES: dict[str, type] = {YahooPrices.name: YahooPrices}


def is_scraped(vendor: str | None) -> bool:
    """True when a vendor name belongs to a scraped source. The one place
    that question is answered, so a panel, a payload and an agent tool all
    agree on it."""
    return bool(vendor) and vendor in SCRAPED_SOURCES


__all__ = ["SCRAPED_SOURCES", "YahooPrices", "is_scraped"]
