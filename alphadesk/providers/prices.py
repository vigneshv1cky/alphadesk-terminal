"""Market-data vendor adapters on the user's own keys (2026-09-13): Polygon,
Finnhub, Alpha Vantage, CoinGecko, and Financial Modeling Prep through the
company mixins (providers/company_vendors.py). Alpaca lives in
providers/alpaca.py. There is no builtin source: the data router asks the
signed-in user's connected vendors, and a surface none of them carries
answers the key prompt.

Every bar source hands its bars to `ingest/prices.build_series_payload`, so
a chart carries the same indicator math and the same coverage verdict
whichever vendor served it — including reporting honestly when bars are too
sparse to support an indicator.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from alphadesk.providers.base import EntitlementError, ProviderError
from alphadesk.providers.company_vendors import AlphaVantageCompany, FinnhubCompany, FmpPrices
from alphadesk.providers.registry import register

log = logging.getLogger("alphadesk.providers.prices")


def _history_from_context(ctx: dict | None) -> dict | None:
    """The report record a partial provider already carries in its earnings
    context, as the earnings_history shape: EPS only (these feeds do not
    tie revenue to a report), newest first, the not-yet-reported row on
    top marked upcoming."""
    from datetime import date
    if not ctx or not ctx.get("report_history"):
        return None
    today = date.today().isoformat()
    reports = []
    for r in ctx["report_history"]:
        actual = r.get("eps_actual")
        reports.append({
            "date": r.get("date"), "period_end": r.get("period_end"), "date_kind": r.get("date_kind") or "report",
            "upcoming": actual is None and (r.get("date") or "") >= today,
            "eps_estimate": r.get("eps_estimate"), "eps_actual": actual,
            "surprise_pct": r.get("surprise_pct"), "revenue": None, "revenue_estimate": None,
        })
    reports.sort(key=lambda r: r["date"] or "", reverse=True)
    return {"symbol": ctx.get("symbol"), "reports": reports}


def _av_date(v) -> str | None:
    """Alpha Vantage writes an unknown date as the string "None"."""
    v = (str(v) if v is not None else "").strip()
    return v if v and v.lower() != "none" else None


def _get_json(url: str, headers: dict[str, str], timeout: float = 20.0):
    """One bounded GET with header-borne auth — a key never rides in the URL,
    and errors surface without it. Each provider passes its own auth header
    (Polygon speaks Bearer, Finnhub its token header)."""
    import json as _json
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    req = Request(url, headers={"User-Agent": "AlphaDesk/1.0",
                                "Accept": "application/json", **headers})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        if exc.code in (401, 402, 403):
            # The plan, not the network: keep the vendor's own sentence
            # ("NOT_AUTHORIZED: Your plan doesn't include this data timeframe")
            # so the reader is told which wall they hit.
            detail = ""
            try:
                body = _json.loads(exc.read().decode("utf-8", "replace"))
                detail = str(body.get("message") or body.get("error") or body.get("Error Message")
                             or body.get("status") or "")[:200]
            except Exception:
                pass
            raise EntitlementError(f"HTTP {exc.code}{': ' + detail if detail else ''}") from exc
        raise ProviderError(f"HTTP {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise ProviderError(f"unreachable: {exc.reason}") from exc
    except ValueError as exc:
        raise ProviderError("response was not JSON") from exc


def _get_text(url: str, headers: dict[str, str] | None = None, timeout: float = 30.0) -> str:
    """The same bounded GET for a vendor that answers CSV."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen
    req = Request(url, headers={"User-Agent": "AlphaDesk/1.0", **(headers or {})})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in (401, 402, 403):
            raise EntitlementError(f"HTTP {exc.code}") from exc
        raise ProviderError(f"HTTP {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise ProviderError(f"unreachable: {exc.reason}") from exc


def polygon_mover_row(symbol: str, price, change_pct, volume, name: str | None = None) -> dict:
    """A movers row in the route's shape, from a Polygon snapshot."""
    def _f(v):
        try:
            x = float(v)
            return x if x == x else None
        except (TypeError, ValueError):
            return None
    chg = _f(change_pct)
    p = _f(price)
    v = int(_f(volume) or 0)
    return {"symbol": symbol, "display": symbol, "name": name, "price": p,
            "change_pct": round(chg, 2) if chg is not None else None, "volume": v,
            "turnover": (p or 0) * v, "volatility": None, "liquidity": None, "spark": []}


CURRENCY_PAIRS: tuple[tuple[str, str], ...] = (
    # The dollar against the majors.
    ("EURUSD=X", "Euro"), ("JPY=X", "Japanese yen"), ("GBPUSD=X", "British pound"), ("AUDUSD=X", "Australian dollar"),
    ("NZDUSD=X", "New Zealand dollar"), ("CAD=X", "Canadian dollar"), ("CHF=X", "Swiss franc"), ("CNY=X", "Chinese yuan"),
    ("HKD=X", "Hong Kong dollar"), ("SGD=X", "Singapore dollar"), ("INR=X", "Indian rupee"), ("MXN=X", "Mexican peso"),
    ("ZAR=X", "South African rand"), ("SEK=X", "Swedish krona"), ("NOK=X", "Norwegian krone"),
    # Crosses: the majors against each other, without the dollar (2026-09-15;
    # every pair here quoted by FMP on Premium, bars in New York time).
    ("EURGBP=X", "Euro / pound"), ("EURJPY=X", "Euro / yen"), ("GBPJPY=X", "Pound / yen"), ("EURCHF=X", "Euro / franc"),
    ("AUDJPY=X", "Aussie / yen"), ("EURAUD=X", "Euro / Aussie"), ("EURCAD=X", "Euro / loonie"), ("GBPCHF=X", "Pound / franc"),
    ("CADJPY=X", "Loonie / yen"), ("CHFJPY=X", "Franc / yen"), ("AUDNZD=X", "Aussie / kiwi"),
    # The dollar against emerging and other currencies.
    ("BRL=X", "Brazilian real"), ("KRW=X", "South Korean won"), ("TRY=X", "Turkish lira"), ("PLN=X", "Polish zloty"),
    ("THB=X", "Thai baht"), ("IDR=X", "Indonesian rupiah"), ("PHP=X", "Philippine peso"), ("TWD=X", "Taiwan dollar"),
    ("ILS=X", "Israeli shekel"), ("CZK=X", "Czech koruna"), ("HUF=X", "Hungarian forint"), ("DKK=X", "Danish krone"),
    ("CLP=X", "Chilean peso"), ("COP=X", "Colombian peso"), ("SAR=X", "Saudi riyal"), ("AED=X", "UAE dirham"),
    ("MYR=X", "Malaysian ringgit"),
)


# The underlyings whose chains the option movers read: the most traded
# option markets.
OPTION_UNDERLYINGS = ("SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "AMD", "AMZN", "META", "MSFT", "PLTR", "GOOGL")


def fx_rollover(now_et):
    """The 5pm New York rollover that began the currency trading day in
    progress at `now_et` (an aware New York time): today's 5pm once it has
    passed, yesterday's before it. The market trades from Sunday's 5pm to
    Friday's, so from Friday's 5pm through Sunday's the day in progress is
    still Friday's, begun Thursday at 5pm. Pure."""
    from datetime import timedelta
    roll = now_et.replace(hour=17, minute=0, second=0, microsecond=0)
    if now_et < roll:
        roll -= timedelta(days=1)
    # A rollover on Friday or Saturday begins no trading day; step back to
    # Thursday's (Sunday's 5pm opens the week, and is kept).
    while roll.weekday() in (4, 5):
        roll -= timedelta(days=1)
    return roll


def close_at(bars: list[dict], moment, bar_minutes: int):
    """The close of the last bar ending at or before `moment`, from bars
    stamped "YYYY-MM-DD HH:MM:SS" in `moment`'s own time zone (FMP's intraday
    charts are New York time). None when none ended by then. Pure."""
    from datetime import datetime, timedelta
    best = None
    for b in bars:
        try:
            start = datetime.strptime(str(b.get("date")), "%Y-%m-%d %H:%M:%S").replace(tzinfo=moment.tzinfo)
        except ValueError:
            continue
        if start + timedelta(minutes=bar_minutes) <= moment and (best is None or start > best[0]) and b.get("close"):
            best = (start, float(b["close"]))
    return best[1] if best else None


def polygon_forex_symbol(yahoo: str) -> str | None:
    """Yahoo's pair name to Polygon's: EURUSD=X -> C:EURUSD, JPY=X -> C:USDJPY.
    The dollar index (DX-Y.NYB) is an index, not a pair: None."""
    if not yahoo.endswith("=X"):
        return None
    base = yahoo[:-2].upper()
    if len(base) == 6:
        return f"C:{base}"
    if len(base) == 3:
        return f"C:USD{base}"
    return None


def finnhub_economic_rows(payload) -> list[dict]:
    """Finnhub's documented calendar shape into the contract's rows:
    {actual, country, estimate, event, impact, prev, time: "2026-09-15
    12:30:00", unit}. Finnhub states `time` in UTC; it becomes an ISO
    datetime with a Z. A row without an event name is dropped."""
    def _f(v):
        try:
            x = float(v)
            return x if x == x else None
        except (TypeError, ValueError):
            return None
    rows = []
    for r in ((payload or {}).get("economicCalendar") or []) if isinstance(payload, dict) else []:
        event = str(r.get("event") or "").strip()
        if not event:
            continue
        t = str(r.get("time") or "").strip()
        if len(t) >= 19 and t[10] == " ":
            t = t[:10] + "T" + t[11:19] + "Z"
        impact = str(r.get("impact") or "").strip().lower() or None
        rows.append({"time": t or None, "country": (str(r.get("country") or "").strip().upper() or None),
                     "event": event, "impact": impact if impact in ("low", "medium", "high") else None,
                     "actual": _f(r.get("actual")), "estimate": _f(r.get("estimate")), "previous": _f(r.get("prev")),
                     "unit": (str(r.get("unit") or "").strip() or None)})
    rows.sort(key=lambda r: r["time"] or "")
    return rows


class PolygonPrices:
    """Polygon.io aggregates and snapshots. Config: the user's Polygon key — the
    same key the polygon news provider uses.

    PARTIAL on purpose, the way the protocol invites: charts, live context,
    a thin quote and gainers/losers are what one Polygon key serves well.
    Fundamentals, ownership, analyst consensus, macro, the tape, options and
    crypto are served by other vendors and answer None here — the UI
    renders absence honestly rather than this provider guessing.

    Charts go through `ingest.prices.build_series_payload`, so a Polygon
    series carries the SAME indicator math and coverage verdict as the
    other vendors — the data-quality gate does not care where bars came from.
    """

    name = "polygon"

    _BASE = "https://api.polygon.io"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def _need_key(self) -> None:
        if not self.api_key:
            raise ProviderError("no Polygon key")

    # ── bars → the shared chart payload ────────────────────────────────────

    def _aggs(self, symbol: str, mult: int, span: str,
              date_from: str, date_to: str) -> list[dict]:
        url = (f"{self._BASE}/v2/aggs/ticker/{symbol}/range/{mult}/{span}/"
               f"{date_from}/{date_to}?adjusted=true&sort=asc&limit=50000")
        auth = {"Authorization": f"Bearer {self.api_key}"}
        bars: list[dict] = []
        for _page in range(5):                      # 250k bars is beyond any range here
            data = _get_json(url, auth)
            for r in data.get("results") or []:
                ts = datetime.fromtimestamp((r.get("t") or 0) / 1000, tz=timezone.utc)
                bars.append({"ts": ts, "open": r.get("o"), "high": r.get("h"),
                             "low": r.get("l"), "close": r.get("c"),
                             "volume": r.get("v") or 0.0})
            nxt = data.get("next_url")
            if not nxt:
                break
            url = nxt
        return bars

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
        unit = str(spec.get("unit") or "")
        if unit == "Sec":
            mult, span = int(spec.get("n") or 1), "second"
        elif unit == "Min":
            mult, span = int(spec.get("n") or 1), "minute"
        elif unit == "Hour":
            mult, span = int(spec.get("n") or 1), "hour"
        else:
            mult, span = 1, {"1d": "day", "1wk": "week", "1mo": "month"}.get(used, "day")

        today = now_et().date()
        # A history page reaches one range-span back, and twice as far again
        # whenever that came back too thin to fill the chart's blank left
        # side — a sliver of a page is what made the edge creep in.
        if before is not None:
            floor = ip.history_floor(used, now_et())
            windows = [(w[0].date(), before.date()) for w in ip.page_attempts(rk, before, floor)]
            if not windows:
                return None
        elif rk == "YTD":
            windows = [(today.replace(month=1, day=1), today)]
        else:
            span_days = ip.RANGE_DAYS.get(rk, days)
            windows = [(today - timedelta(days=span_days + 3), today)]
        bars: list[dict] = []
        for start, end in windows:
            try:
                got = self._aggs(sym, mult, span, start.isoformat(), end.isoformat())
            except EntitlementError:
                raise                               # the plan's wall — say so
            except ProviderError as exc:
                log.debug("polygon aggs failed %s: %s", sym, exc)
                return None
            if before is not None:
                got = [b for b in got if b["ts"] < before]
            # A wider window that brought nothing new is the vendor's floor
            # at this interval, not a reason to ask again.
            if bars and len(got) <= len(bars):
                break
            bars = got
            if before is None or not ip.page_is_thin(bars, need):
                break
        # A widened window can overshoot; the page keeps the bars nearest the
        # cursor, which are the ones that join what the chart already holds.
        if before is not None:
            bars = ip.page_trim(bars, need)
        # Minute bars answer to the minute-density gate; everything coarser
        # is complete by construction — the same split every vendor makes.
        stats = None if used in ("1m", "2m") or unit == "Sec" else ip._daily_coverage(bars)
        return ip.build_series_payload(sym, bars, used, range_key=rk,
                                       interval=interval, stats=stats, table=table)

    # What Polygon's aggregates endpoint serves: any multiple of second,
    # minute, hour, day, week, month. Declared as the useful set rather
    # than every integer. Reach is the plan's, which this cannot see — a
    # request past the plan's history comes back empty and says so.
    _INTERVALS: dict[str, dict] = {
        "1s": {"n": 1, "unit": "Sec", "max_days": 1, "label": "1 sec"},
        "5s": {"n": 5, "unit": "Sec", "max_days": 1, "label": "5 secs"},
        "10s": {"n": 10, "unit": "Sec", "max_days": 2, "label": "10 secs"},
        "15s": {"n": 15, "unit": "Sec", "max_days": 2, "label": "15 secs"},
        "30s": {"n": 30, "unit": "Sec", "max_days": 5, "label": "30 secs"},
        "1m": {"n": 1, "unit": "Min", "max_days": 60, "label": "1 min"},
        "2m": {"n": 2, "unit": "Min", "max_days": 60, "label": "2 mins"},
        "3m": {"n": 3, "unit": "Min", "max_days": 90, "label": "3 mins"},
        "5m": {"n": 5, "unit": "Min", "max_days": 180, "label": "5 mins"},
        "10m": {"n": 10, "unit": "Min", "max_days": 365, "label": "10 mins"},
        "15m": {"n": 15, "unit": "Min", "max_days": 365, "label": "15 mins"},
        "30m": {"n": 30, "unit": "Min", "max_days": 730, "label": "30 mins"},
        "1h": {"n": 1, "unit": "Hour", "max_days": 730, "label": "1 hour"},
        "2h": {"n": 2, "unit": "Hour", "max_days": 730, "label": "2 hours"},
        "4h": {"n": 4, "unit": "Hour", "max_days": 730, "label": "4 hours"},
        "1d": {"n": 1, "unit": "Day", "max_days": None, "label": "1 day"},
        "1wk": {"n": 1, "unit": "Week", "max_days": None, "label": "1 week"},
        "1mo": {"n": 1, "unit": "Month", "max_days": None, "label": "1 month"},
    }

    def chart_intervals(self) -> dict[str, dict]:
        return self._INTERVALS

    # ── snapshots ──────────────────────────────────────────────────────────

    def _snapshot(self, symbol: str) -> dict | None:
        try:
            data = _get_json(
                f"{self._BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}",
                {"Authorization": f"Bearer {self.api_key}"})
        except ProviderError as exc:
            log.debug("polygon snapshot failed %s: %s", symbol, exc)
            return None
        return data.get("ticker") or None

    def context(self, symbol: str) -> dict | None:
        self._need_key()
        snap = self._snapshot(symbol.upper())
        if not snap:
            return None
        day = snap.get("day") or {}
        last = (snap.get("lastTrade") or {}).get("p") or day.get("c")
        prev = (snap.get("prevDay") or {}).get("c")
        if not last:
            return None
        return {
            "symbol": symbol.upper(),
            "price": last,
            "change_pct": snap.get("todaysChangePerc"),
            "prev_close": prev,
            "volume": day.get("v"),
            "day_low": day.get("l"), "day_high": day.get("h"),
        }

    def quote(self, symbol: str) -> dict | None:
        self._need_key()
        snap = self._snapshot(symbol.upper())
        if not snap:
            return None
        day = snap.get("day") or {}
        prev = (snap.get("prevDay") or {}).get("c")
        last = (snap.get("lastTrade") or {}).get("p") or day.get("c")
        if not last:
            return None
        # The readout's shape, thinly served: what Polygon states, stated;
        # the valuation and analyst fields it does not carry stay absent and
        # the overview renders the rows it has.
        return {
            "symbol": symbol.upper(),
            "price": last,
            "change_pct": snap.get("todaysChangePerc"),
            "previous_close": prev,
            "open": day.get("o"),
            "day_low": day.get("l"), "day_high": day.get("h"),
            "volume": day.get("v"),
            "currency": "USD",
            "source": "Polygon",
        }

    def market_day(self, day: str) -> dict[str, dict] | None:
        """EVERY US symbol's bar for ONE past session, keyed by ticker.

        The movers endpoints every vendor publishes are TODAY only — they
        answer "what is moving", not "what moved on the 24th". This is the
        one primitive that makes a past session answerable: the whole market
        in a single request, which is also why it is cheap enough to ask for
        two days at once (a session's change needs the session before it).

        Measured on a live key: 12,591 symbols in 0.3-0.5s. A day the market
        did not open answers with nothing, which the caller reads as "not a
        session" rather than as a failure.
        """
        self._need_key()
        data = _get_json(
            f"{self._BASE}/v2/aggs/grouped/locale/us/market/stocks/{day}?adjusted=true",
            {"Authorization": f"Bearer {self.api_key}"}, timeout=45)
        rows = data.get("results") or []
        out: dict[str, dict] = {}
        for r in rows:
            sym = str(r.get("T") or "").upper()
            close = r.get("c")
            if not sym or close is None:
                continue
            out[sym] = {"open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
                        "close": close, "volume": r.get("v") or 0}
        # AN EMPTY DICT, NOT None. To the router None means "I do not carry
        # this surface", so returning it for a public holiday would put a
        # closed market and an unconnected vendor at the same 428 — the
        # fault #63 fixed for the scraped sources. An empty answer is still
        # an answer.
        return out

    def movers(self, top: int = 20) -> dict:
        self._need_key()
        out: dict = {"most_active": [], "gainers": [], "losers": []}
        for side in ("gainers", "losers"):
            try:
                data = _get_json(
                    f"{self._BASE}/v2/snapshot/locale/us/markets/stocks/{side}",
                    {"Authorization": f"Bearer {self.api_key}"})
            except ProviderError as exc:
                log.debug("polygon %s failed: %s", side, exc)
                continue
            rows = []
            for t in (data.get("tickers") or [])[: top * 3]:
                day = t.get("day") or {}
                price = (t.get("lastTrade") or {}).get("p") or day.get("c")
                # The movers rule: arithmetically large but informationally
                # empty movers are noise — sub-$5 names and thin turnover out.
                if not price or price < 5 or (day.get("v") or 0) * price < 1_000_000:
                    continue
                rows.append({"symbol": t.get("ticker"), "price": price,
                             "change_pct": t.get("todaysChangePerc"),
                             "volume": day.get("v")})
                if len(rows) >= top:
                    break
            out[side] = rows
        return out

    # ── honestly absent ────────────────────────────────────────────────────

    def corporate_actions(self, symbol: str) -> dict | None:
        """Polygon's reference dividends and splits — the one free source
        here that carries declaration, record and pay dates per dividend."""
        self._need_key()
        auth = {"Authorization": f"Bearer {self.api_key}"}
        sym = symbol.upper()
        divs = _get_json(f"{self._BASE}/v3/reference/dividends?ticker={sym}"
                         f"&order=desc&sort=ex_dividend_date&limit=100", auth)
        dividends = [{
            "ex_date": r.get("ex_dividend_date"), "amount": r.get("cash_amount"), "adjusted_amount": None,
            "currency": r.get("currency"), "declaration_date": r.get("declaration_date"),
            "record_date": r.get("record_date"), "payment_date": r.get("pay_date"),
        } for r in (divs.get("results") or []) if r.get("ex_dividend_date")]
        sp = _get_json(f"{self._BASE}/v3/reference/splits?ticker={sym}"
                       f"&order=desc&sort=execution_date&limit=100", auth)
        splits = [{
            "date": r.get("execution_date"), "from": r.get("split_from"), "to": r.get("split_to"),
        } for r in (sp.get("results") or []) if r.get("execution_date")]
        if not dividends and not splits:
            return None
        return {"symbol": sym, "dividends": dividends, "splits": splits}

    # ── movers: the licensed feed for the two categories it carries whole ──

    def economic_calendar(self, start: str, end: str) -> list[dict] | None: return None
    def category_movers(self, category: str, top: int = 20) -> dict | None:
        """Stocks from the full US snapshot (one request: every ticker's
        day bar and change, so active, gainers and losers come from one
        payload) and currencies from the forex snapshot, mapped onto the
        same pairs the free tile lists. Everything else answers None and
        the free path serves it."""
        if category == "stocks":
            return self._stock_movers(top)
        if category == "currencies":
            return self._forex_movers(top)
        if category == "options":
            return self._option_movers(top)
        return None

    # Polygon's option snapshot is a paid-plan endpoint.
    OPTION_UNDERLYINGS = OPTION_UNDERLYINGS

    def _option_movers(self, top: int) -> dict:
        """The busiest contracts across the most traded option markets, from
        Polygon's chain snapshot: the day's volume, last price and change,
        implied volatility and the premium traded (contracts × price × 100)."""
        self._need_key()
        auth = {"Authorization": f"Bearer {self.api_key}"}
        rows = []
        for u in self.OPTION_UNDERLYINGS:
            data = _get_json(f"{self._BASE}/v3/snapshot/options/{u}?limit=250&order=desc&sort=volume", auth, timeout=30)
            for c in (data or {}).get("results") or []:
                det, day = c.get("details") or {}, c.get("day") or {}
                vol, last = int(day.get("volume") or 0), day.get("close")
                if vol <= 0 or not last:
                    continue
                kind = "C" if str(det.get("contract_type") or "").lower().startswith("c") else "P"
                exp, strike = str(det.get("expiration_date") or ""), det.get("strike_price")
                iv = c.get("implied_volatility")
                premium = round(vol * float(last) * 100)
                rows.append({"symbol": det.get("ticker") or f"{u}{exp}{kind}{strike}",
                             "display": f"{u} {strike:g}{kind} {exp[5:]}" if strike is not None and exp else det.get("ticker"),
                             "name": f"{u} {exp} {'call' if kind == 'C' else 'put'} {strike}",
                             "price": float(last), "change_pct": day.get("change_percent"), "volume": vol,
                             "volatility": round(float(iv) * 100, 1) if iv else None, "liquidity": premium,
                             "turnover": premium, "open_interest": c.get("open_interest"),
                             "underlying": u, "expiry": exp})
        if not rows:
            return {"tabs": []}
        rows.sort(key=lambda r: -r["volume"])
        changed = [r for r in rows if r["change_pct"] is not None]
        return {"tabs": [
            {"id": "most_active", "label": "Active", "rows": rows[:top]},
            {"id": "gainers", "label": "Gainers", "rows": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])[:top]},
            {"id": "losers", "label": "Losers", "rows": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:top]},
        ]}

    def _stock_movers(self, top: int) -> dict:
        self._need_key()
        auth = {"Authorization": f"Bearer {self.api_key}"}
        data = _get_json(f"{self._BASE}/v2/snapshot/locale/us/markets/stocks/tickers", auth, timeout=40)
        rows = []
        for t in (data or {}).get("tickers") or []:
            sym = str(t.get("ticker") or "").upper()
            day, prev = t.get("day") or {}, t.get("prevDay") or {}
            price = day.get("c") or (t.get("lastTrade") or {}).get("p")
            # Polygon empties the day block until the opening bell, so a row
            # with a real extended-hours price used to be thrown away for
            # having no volume and the whole list was empty before the open
            # (2026-09-22). The volume beside it is then the last session's,
            # which is what every other vendor's row carries out of hours.
            vol = day.get("v") or 0
            late = vol <= 0 and bool(price)
            if late:
                vol = prev.get("v") or 0
            if not sym or not sym.isalnum() or not price or vol <= 0:
                continue
            row = polygon_mover_row(sym, price, t.get("todaysChangePerc"), vol)
            if late:
                row["extended"] = True
            rows.append(row)
        if not rows:
            return {"tabs": []}
        by_turnover = sorted(rows, key=lambda r: -(r["price"] or 0) * r["volume"])
        changed = [r for r in rows if r["change_pct"] is not None]
        return {"tabs": [
            {"id": "most_active", "label": "Active", "rows": by_turnover[:top]},
            {"id": "gainers", "label": "Gainers", "rows": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])[:top]},
            {"id": "losers", "label": "Losers", "rows": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:top]},
        ]}

    def _forex_movers(self, top: int) -> dict:
        self._need_key()
        auth = {"Authorization": f"Bearer {self.api_key}"}
        data = _get_json(f"{self._BASE}/v2/snapshot/locale/global/markets/forex/tickers", auth, timeout=40)
        snaps = {str(t.get("ticker") or ""): t for t in (data or {}).get("tickers") or []}
        rows = []
        for yahoo_sym, label in CURRENCY_PAIRS:
            poly = polygon_forex_symbol(yahoo_sym)
            t = snaps.get(poly) if poly else None
            if not t:
                continue
            day = t.get("day") or {}
            price = day.get("c") or (t.get("lastQuote") or {}).get("a")
            if not price:
                continue
            rows.append(polygon_mover_row(yahoo_sym, price, t.get("todaysChangePerc"), 0, name=label))
        if not rows:
            return {"tabs": []}
        changed = [r for r in rows if r["change_pct"] is not None]
        return {"tabs": [
            {"id": "all", "label": "All", "rows": rows},
            {"id": "gainers", "label": "Gainers", "rows": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])},
            {"id": "losers", "label": "Losers", "rows": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])},
        ]}

    def fundamentals(self, symbol: str) -> dict | None: return None
    def institutional_ownership(self, symbol: str) -> dict | None: return None
    def earnings_context(self, symbol: str) -> dict | None: return None
    def earnings_history(self, symbol: str) -> dict | None: return None
    def earnings_insights(self, symbol: str) -> dict | None: return None
    def macro(self) -> dict | None: return None
    def sector_change_pct(self, sector: str | None) -> float | None: return None
    def market_tape(self) -> list[dict] | None: return None
    def index_board(self) -> list[dict] | None: return None
    def option_expirations(self, symbol: str) -> list[str] | None: return None

    def option_chain(self, symbol: str, expiry: str) -> dict | None:
        return None

    def crypto_movers(self, top: int = 20) -> dict | None:
        return None


class FinnhubPrices(FinnhubCompany):
    """Finnhub quotes and company data. Config: the user's Finnhub key — the same
    key the finnhub news provider uses.

    The COMPLEMENT of the Polygon provider: Finnhub's free tier is strong on
    the readout side — live quote, company profile, basic financials, the
    EPS-surprise record — while candles sit behind its paid tier. So charts
    are attempted and answer None on a free key (the chart tile says "no
    bars" rather than pretending), and fundamentals/earnings history are
    served where Polygon answers None. Same token header as the news
    provider; the key never rides in a URL.
    """

    name = "finnhub"

    _BASE = "https://finnhub.io/api/v1"

    # Finnhub candle resolutions. A requested interval it lacks serves the
    # nearest COARSER one it has, and the payload says which — the protocol's
    # "serve a coarser one and say which", applied.
    _RES = {"1m": ("1", "1m"), "2m": ("5", "5m"), "5m": ("5", "5m"),
            "15m": ("15", "15m"), "30m": ("30", "30m"),
            "1h": ("60", "1h"), "4h": ("60", "1h"),
            "1d": ("D", "1d"), "1wk": ("W", "1wk"), "1mo": ("M", "1mo")}
    # The catalogue OFFERED: only the resolutions Finnhub really has, so the
    # menu never lists a 2-minute bar it would serve as 5. The map above
    # still catches a stale preference.
    _INTERVALS: dict[str, dict] = {
        "1m": {"n": 1, "unit": "Min", "max_days": 30, "label": "1 min"},
        "5m": {"n": 5, "unit": "Min", "max_days": 60, "label": "5 mins"},
        "15m": {"n": 15, "unit": "Min", "max_days": 60, "label": "15 mins"},
        "30m": {"n": 30, "unit": "Min", "max_days": 60, "label": "30 mins"},
        "1h": {"n": 1, "unit": "Hour", "max_days": 730, "label": "1 hour"},
        "1d": {"n": 1, "unit": "Day", "max_days": None, "label": "1 day"},
        "1wk": {"n": 1, "unit": "Week", "max_days": None, "label": "1 week"},
        "1mo": {"n": 1, "unit": "Month", "max_days": None, "label": "1 month"},
    }

    def chart_intervals(self) -> dict[str, dict]:
        return self._INTERVALS

    def _wanted(self, rk: str, interval: str | None) -> str:
        """The interval to serve: resolved against this provider's own
        catalogue, or — for a preference saved under another provider that
        this one does not carry (a 4-hour bar, say) — against the builtin
        table, which the substitution map then serves as the nearest
        coarser resolution and the payload reports."""
        from alphadesk.ingest import prices as ip
        want = (interval or "").lower()
        if want and want not in self._INTERVALS and want in self._RES:
            return ip.resolve_interval(rk, want, ip.CHART_INTERVALS)
        return ip.resolve_interval(rk, interval, self._INTERVALS)

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def _need_key(self) -> None:
        if not self.api_key:
            raise ProviderError("no Finnhub key")

    def _auth(self) -> dict[str, str]:
        return {"X-Finnhub-Token": self.api_key}

    def _get(self, path: str):
        return _get_json(f"{self._BASE}{path}", self._auth())

    def chart_series(self, symbol: str, days: int = 2, range_key: str | None = None,
                     interval: str | None = None, before=None, need: int | None = None) -> dict | None:
        self._need_key()
        from alphadesk.config import now_et
        from alphadesk.ingest import prices as ip

        sym = symbol.upper()
        rk = (range_key or "1D").upper()
        wanted = self._wanted(rk, interval)
        res, served = self._RES.get(wanted) or ("D", "1d")
        today = now_et().date()
        # One range-span back per page, twice as far again whenever a page
        # came back too thin to fill the chart's blank left side.
        if before is not None:
            floor = ip.history_floor(served, now_et())
            spans = [(int(w[0].timestamp()), int(before.timestamp()) - 1)
                     for w in ip.page_attempts(rk, before, floor)]
            if not spans:
                return None
        else:
            if rk == "YTD":
                start = today.replace(month=1, day=1)
            else:
                start = today - timedelta(days=ip.RANGE_DAYS.get(rk, days) + 3)
            spans = [(int(datetime(start.year, start.month, start.day,
                                   tzinfo=timezone.utc).timestamp()),
                      int(datetime.now(timezone.utc).timestamp()))]
        bars: list[dict] = []
        for frm, to in spans:
            try:
                data = self._get(f"/stock/candle?symbol={sym}&resolution={res}"
                                 f"&from={frm}&to={to}")
            except EntitlementError as exc:
                # Candles are a paid endpoint on Finnhub; a free key gets 403.
                raise EntitlementError(f"Finnhub candles are a paid endpoint on this key ({exc})") from exc
            except ProviderError as exc:
                log.debug("finnhub candles unavailable %s: %s", sym, exc)
                return None
            if (data or {}).get("s") != "ok":
                break
            got = [{"ts": datetime.fromtimestamp(t, tz=timezone.utc),
                    "open": o, "high": h, "low": low, "close": c, "volume": v or 0.0}
                   for t, o, h, low, c, v in zip(data.get("t") or [], data.get("o") or [],
                                                 data.get("h") or [], data.get("l") or [],
                                                 data.get("c") or [], data.get("v") or [])]
            # A wider window that brought nothing new is the vendor's floor
            # at this interval, not a reason to ask again.
            if bars and len(got) <= len(bars):
                break
            bars = got
            if before is None or not ip.page_is_thin(bars, need):
                break
        if not bars:
            return None
        # A widened window can overshoot; the page keeps the bars nearest the
        # cursor, which are the ones that join what the chart already holds.
        if before is not None:
            bars = ip.page_trim(bars, need)
        stats = None if served in ("1m", "2m") else ip._daily_coverage(bars)
        return ip.build_series_payload(sym, bars, served, range_key=rk,
                                       interval=interval, stats=stats)

    def context(self, symbol: str) -> dict | None:
        self._need_key()
        try:
            q = self._get(f"/quote?symbol={symbol.upper()}")
        except ProviderError as exc:
            log.debug("finnhub quote failed %s: %s", symbol, exc)
            return None
        if not (q or {}).get("c"):
            return None
        return {"symbol": symbol.upper(), "price": q.get("c"),
                "change_pct": q.get("dp"), "prev_close": q.get("pc"),
                "day_low": q.get("l"), "day_high": q.get("h"), "volume": None}

    def quote(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        try:
            q = self._get(f"/quote?symbol={sym}")
        except ProviderError as exc:
            log.debug("finnhub quote failed %s: %s", sym, exc)
            return None
        if not (q or {}).get("c"):
            return None
        profile: dict = {}
        try:
            profile = self._get(f"/stock/profile2?symbol={sym}") or {}
        except ProviderError:
            pass                                      # the quote stands alone
        return {
            "symbol": sym,
            "name": profile.get("name"),
            "price": q.get("c"),
            "change_pct": q.get("dp"),
            "previous_close": q.get("pc"),
            "open": q.get("o"),
            "day_low": q.get("l"), "day_high": q.get("h"),
            # profile2 states market cap in MILLIONS.
            "market_cap": (profile.get("marketCapitalization") or 0) * 1e6 or None,
            "currency": profile.get("currency") or "USD",
            "exchange": profile.get("exchange"),
            "source": "Finnhub",
        }

    def fundamentals(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        try:
            data = self._get(f"/stock/metric?symbol={sym}&metric=all") or {}
            profile = self._get(f"/stock/profile2?symbol={sym}") or {}
        except ProviderError as exc:
            log.debug("finnhub metrics failed %s: %s", sym, exc)
            return None
        m = data.get("metric") or {}
        if not m:
            return None

        def _pct(v):
            return v / 100.0 if isinstance(v, (int, float)) else None
        return {
            "market_cap": (m.get("marketCapitalization") or 0) * 1e6 or None,
            "trailing_pe": m.get("peTTM"),
            "forward_pe": None,
            "profit_margin": _pct(m.get("netProfitMarginTTM")),
            "revenue_growth": _pct(m.get("revenueGrowthTTMYoy")),
            "sector": None,
            "industry": profile.get("finnhubIndustry"),
            "short_float_pct": None,
            "days_to_cover": None,
        }

    def earnings_context(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        try:
            rows = self._get(f"/stock/earnings?symbol={sym}") or []
        except ProviderError as exc:
            log.debug("finnhub earnings failed %s: %s", sym, exc)
            return None
        if not isinstance(rows, list) or not rows:
            return None
        # Finnhub dates each row by the QUARTER END, not the day it was
        # reported; the row says so, and the panels label it by its period.
        history = [{"date": r.get("period"), "period_end": r.get("period"), "date_kind": "period_end",
                    "eps_estimate": r.get("estimate"),
                    "eps_actual": r.get("actual"),
                    "surprise_pct": r.get("surprisePercent")}
                   for r in rows if isinstance(r, dict) and r.get("period")]
        history.sort(key=lambda r: r["date"])
        recent = history[-4:]
        beats = sum(1 for r in recent
                    if r["eps_actual"] is not None and r["eps_estimate"] is not None
                    and r["eps_actual"] >= r["eps_estimate"])
        measured = sum(1 for r in recent
                       if r["eps_actual"] is not None and r["eps_estimate"] is not None)
        out: dict = {"symbol": sym, "report_history": history}
        if measured:
            out["beat_streak"] = f"{beats}/{measured} beats"
        return out

    # ── honestly absent ────────────────────────────────────────────────────

    def corporate_actions(self, symbol: str) -> dict | None:
        """Finnhub's dividend record (ex, record, pay and declaration dates
        with the amount) and split history. The dividend endpoint is
        entitlement-gated on some plans; a refusal surfaces as
        EntitlementError and the caller falls back to what it has."""
        self._need_key()
        from datetime import date, timedelta
        sym = symbol.upper()
        to = date.today()
        frm = to - timedelta(days=365 * 15)
        dividends: list[dict] = []
        # Finnhub names the ex-dividend date `date` (older payloads: exDate).
        for r in self._get(f"/stock/dividend?symbol={sym}&from={frm}&to={to}") or []:
            ex = r.get("date") or r.get("exDate")
            if not ex:
                continue
            dividends.append({
                "ex_date": ex, "amount": r.get("amount"), "adjusted_amount": r.get("adjustedAmount"),
                "currency": r.get("currency"), "declaration_date": r.get("declarationDate"),
                "record_date": r.get("recordDate"), "payment_date": r.get("payDate"),
            })
        splits: list[dict] = []
        for r in self._get(f"/stock/split?symbol={sym}&from={frm}&to={to}") or []:
            if r.get("date"):
                splits.append({"date": r.get("date"), "from": r.get("fromFactor"), "to": r.get("toFactor")})
        if not dividends and not splits:
            return None
        dividends.sort(key=lambda r: r["ex_date"] or "", reverse=True)
        splits.sort(key=lambda r: r["date"] or "", reverse=True)
        return {"symbol": sym, "dividends": dividends, "splits": splits}

    def earnings_history(self, symbol: str) -> dict | None:
        return _history_from_context(self.earnings_context(symbol))

    def economic_calendar(self, start: str, end: str) -> list[dict] | None:
        """Finnhub's economic calendar (/calendar/economic, from..to), a
        premium-plan endpoint: a free key answers 403 and the route says so.
        Rows come back in the contract's shape via finnhub_economic_rows."""
        self._need_key()
        data = _get_json(f"{self._BASE}/calendar/economic?from={start}&to={end}",
                         {"X-Finnhub-Token": self.api_key}, timeout=30)
        return finnhub_economic_rows(data)

    def category_movers(self, category: str, top: int = 20) -> dict | None: return None
    def macro(self) -> dict | None: return None
    def sector_change_pct(self, sector: str | None) -> float | None: return None
    def movers(self, top: int = 20) -> dict | None:
        return None
    def market_tape(self) -> list[dict] | None: return None
    def index_board(self) -> list[dict] | None: return None
    def option_expirations(self, symbol: str) -> list[str] | None: return None

    def option_chain(self, symbol: str, expiry: str) -> dict | None:
        return None

    def crypto_movers(self, top: int = 20) -> dict | None:
        return None


class AlphaVantagePrices(AlphaVantageCompany):
    """Alpha Vantage market data. Config: the user's Alpha Vantage key — the same key
    as its news provider.

    The widest free surface of the partial providers — quote, candles at
    every range, OVERVIEW fundamentals, the EPS-surprise record, and real
    top gainers/losers — behind the harshest budget: the free tier's 25
    requests A DAY could not survive one polling chart without the per-user
    TTL memo in front of every keyed provider. It still suits a reader more
    than an operator. Query-param auth is the only kind offered (the news
    provider's documented exception); throttling arrives as an HTTP 200
    Note/Information body and is surfaced as the refusal it is, which each
    method then answers as None/empty rather than an error page.
    """

    name = "alphavantage"

    _BASE = "https://www.alphavantage.co/query"

    # AV intraday resolutions. Requests it lacks serve the nearest it has,
    # and the payload says which (the finnhub rule).
    _RES = {"1m": ("1min", "1m"), "2m": ("5min", "5m"), "5m": ("5min", "5m"),
            "15m": ("15min", "15m"), "30m": ("30min", "30m"),
            "1h": ("60min", "1h"), "4h": ("60min", "1h")}
    _SERIES_KEYS = {"1d": ("TIME_SERIES_DAILY", "Time Series (Daily)"),
                    "1wk": ("TIME_SERIES_WEEKLY", "Weekly Time Series"),
                    "1mo": ("TIME_SERIES_MONTHLY", "Monthly Time Series")}
    _INTERVALS: dict[str, dict] = {
        "1m": {"n": 1, "unit": "Min", "max_days": 30, "label": "1 min"},
        "5m": {"n": 5, "unit": "Min", "max_days": 60, "label": "5 mins"},
        "15m": {"n": 15, "unit": "Min", "max_days": 60, "label": "15 mins"},
        "30m": {"n": 30, "unit": "Min", "max_days": 60, "label": "30 mins"},
        "1h": {"n": 1, "unit": "Hour", "max_days": 730, "label": "1 hour"},
        "1d": {"n": 1, "unit": "Day", "max_days": None, "label": "1 day"},
        "1wk": {"n": 1, "unit": "Week", "max_days": None, "label": "1 week"},
        "1mo": {"n": 1, "unit": "Month", "max_days": None, "label": "1 month"},
    }

    def chart_intervals(self) -> dict[str, dict]:
        return self._INTERVALS

    def _wanted(self, rk: str, interval: str | None) -> str:
        """The interval to serve: resolved against this provider's own
        catalogue, or — for a preference saved under another provider that
        this one does not carry (a 4-hour bar, say) — against the builtin
        table, which the substitution map then serves as the nearest
        coarser resolution and the payload reports."""
        from alphadesk.ingest import prices as ip
        want = (interval or "").lower()
        if want and want not in self._INTERVALS and want in self._RES:
            return ip.resolve_interval(rk, want, ip.CHART_INTERVALS)
        return ip.resolve_interval(rk, interval, self._INTERVALS)

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def _need_key(self) -> None:
        if not self.api_key:
            raise ProviderError("no Alpha Vantage key")

    def _query(self, params: str) -> dict:
        data = _get_json(f"{self._BASE}?{params}&apikey={self.api_key}", {})
        if not isinstance(data, dict):
            raise ProviderError("unexpected payload shape")
        throttle = data.get("Note") or data.get("Information") or data.get("Error Message")
        if throttle and len(data) == 1:
            if "premium" in str(throttle).lower():
                raise EntitlementError(f"Alpha Vantage: {str(throttle)[:200]}")
            raise ProviderError(f"refused: {str(throttle)[:200]}")
        return data

    @staticmethod
    def _num(v) -> float | None:
        try:
            return float(str(v).rstrip("%"))
        except (TypeError, ValueError):
            return None

    # Alpha Vantage answers a whole series per call — the full intraday
    # month, or compact (100 rows) / full (decades) daily — and the free
    # tier allows 25 calls a day. Pages re-read the same payload, so the
    # payload is kept for a few minutes per (symbol, function, size).
    _series_cache: dict[tuple[str, str], tuple[float, dict]] = {}
    _SERIES_TTL_S = 300

    def _series(self, params: str, cache_key: tuple[str, str]) -> dict:
        hit = self._series_cache.get(cache_key)
        if hit and time.time() - hit[0] < self._SERIES_TTL_S:
            return hit[1]
        data = self._query(params)
        self._series_cache[cache_key] = (time.time(), data)
        return data

    def chart_series(self, symbol: str, days: int = 2, range_key: str | None = None,
                     interval: str | None = None, before=None, need: int | None = None) -> dict | None:
        self._need_key()
        from alphadesk.config import ET, now_et
        from alphadesk.ingest import prices as ip

        sym = symbol.upper()
        rk = (range_key or "1D").upper()
        wanted = self._wanted(rk, interval)
        span_days = ip.RANGE_DAYS.get(rk, days)
        # The whole series arrives in one call here, so a page that reaches
        # further back to fill the chart's blank left side costs nothing:
        # the widest window is the one to fetch for, and the narrowest that
        # fills the request is the one to answer with.
        windows = ip.page_attempts(rk, before, ip.history_floor(wanted, now_et())) if before is not None else []
        if before is not None and not windows:
            return None
        # How far back the request REACHES decides compact or full: a page
        # five months back needs the full daily series however short the
        # range is, and compact's 100 rows ended the history there.
        reach_days = (now_et() - windows[-1][0]).days if windows else span_days
        try:
            if wanted in self._RES:
                res, served = self._RES[wanted]
                data = self._series(f"function=TIME_SERIES_INTRADAY&symbol={sym}"
                                    f"&interval={res}&outputsize=full", (sym, f"intraday:{res}"))
                rows = data.get(f"Time Series ({res})") or {}
                fmt = "%Y-%m-%d %H:%M:%S"
            else:
                fn, key = self._SERIES_KEYS.get(wanted) or self._SERIES_KEYS["1d"]
                served = wanted if wanted in self._SERIES_KEYS else "1d"
                size = "compact" if reach_days <= 140 else "full"
                data = self._series(f"function={fn}&symbol={sym}&outputsize={size}", (sym, f"{fn}:{size}"))
                rows = data.get(key) or {}
                fmt = "%Y-%m-%d"
        except EntitlementError:
            raise
        except ProviderError as exc:
            log.debug("alphavantage series failed %s: %s", sym, exc)
            return None

        if windows:
            spans = windows
        elif rk == "YTD":
            spans = [(now_et().replace(month=1, day=1, hour=0, minute=0, second=0), None)]
        else:
            spans = [(now_et() - timedelta(days=span_days + 3), None)]
        # AV states intraday stamps naive in US/Eastern; dates get an ET
        # midnight so both kinds sort truthfully.
        stamped = []
        for ts_str, ohlcv in rows.items():
            try:
                ts = datetime.strptime(ts_str, fmt).replace(tzinfo=ET)
            except ValueError:
                continue
            stamped.append((ts, ohlcv))
        bars: list[dict] = []
        for start, end in spans:
            bars = [{"ts": ts,
                     "open": self._num(ohlcv.get("1. open")),
                     "high": self._num(ohlcv.get("2. high")),
                     "low": self._num(ohlcv.get("3. low")),
                     "close": self._num(ohlcv.get("4. close")),
                     "volume": self._num(ohlcv.get("5. volume")) or 0.0}
                    for ts, ohlcv in stamped
                    if ts >= start and (end is None or ts < end)]
            if before is None or not ip.page_is_thin(bars, need):
                break
        bars.sort(key=lambda b: b["ts"])
        # A widened window can overshoot; the page keeps the bars nearest the
        # cursor, which are the ones that join what the chart already holds.
        if before is not None:
            bars = ip.page_trim(bars, need)
        stats = None if served in ("1m", "2m") else ip._daily_coverage(bars)
        return ip.build_series_payload(sym, bars, served, range_key=rk,
                                       interval=interval, stats=stats)

    def context(self, symbol: str) -> dict | None:
        self._need_key()
        try:
            g = self._query(f"function=GLOBAL_QUOTE&symbol={symbol.upper()}"
                            ).get("Global Quote") or {}
        except ProviderError as exc:
            log.debug("alphavantage quote failed %s: %s", symbol, exc)
            return None
        price = self._num(g.get("05. price"))
        if not price:
            return None
        return {"symbol": symbol.upper(), "price": price,
                "change_pct": self._num(g.get("10. change percent")),
                "prev_close": self._num(g.get("08. previous close")),
                "day_low": self._num(g.get("04. low")),
                "day_high": self._num(g.get("03. high")),
                "volume": self._num(g.get("06. volume"))}

    def quote(self, symbol: str) -> dict | None:
        ctx = self.context(symbol)
        if ctx is None:
            return None
        overview: dict = {}
        try:
            overview = self._query(f"function=OVERVIEW&symbol={symbol.upper()}")
        except ProviderError:
            pass                                      # the quote stands alone
        return {
            "symbol": ctx["symbol"],
            "name": overview.get("Name"),
            "price": ctx["price"],
            "change_pct": ctx["change_pct"],
            "previous_close": ctx["prev_close"],
            "day_low": ctx["day_low"], "day_high": ctx["day_high"],
            "volume": ctx["volume"],
            "market_cap": self._num(overview.get("MarketCapitalization")),
            "pe_trailing": self._num(overview.get("PERatio")),
            "pe_forward": self._num(overview.get("ForwardPE")),
            "week52_low": self._num(overview.get("52WeekLow")),
            "week52_high": self._num(overview.get("52WeekHigh")),
            "currency": overview.get("Currency") or "USD",
            "source": "Alpha Vantage",
        }

    def fundamentals(self, symbol: str) -> dict | None:
        self._need_key()
        try:
            o = self._query(f"function=OVERVIEW&symbol={symbol.upper()}")
        except ProviderError as exc:
            log.debug("alphavantage overview failed %s: %s", symbol, exc)
            return None
        if not o.get("Symbol"):
            return None
        return {
            "market_cap": self._num(o.get("MarketCapitalization")),
            "trailing_pe": self._num(o.get("PERatio")),
            "forward_pe": self._num(o.get("ForwardPE")),
            "profit_margin": self._num(o.get("ProfitMargin")),
            "revenue_growth": self._num(o.get("QuarterlyRevenueGrowthYOY")),
            "sector": o.get("Sector"),
            "industry": o.get("Industry"),
            "short_float_pct": None,
            "days_to_cover": None,
        }

    def earnings_context(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        try:
            rows = self._query(f"function=EARNINGS&symbol={sym}"
                               ).get("quarterlyEarnings") or []
        except ProviderError as exc:
            log.debug("alphavantage earnings failed %s: %s", sym, exc)
            return None
        history = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            date = r.get("reportedDate") or r.get("fiscalDateEnding")
            if not date:
                continue
            history.append({"date": date, "period_end": r.get("fiscalDateEnding"),
                            "date_kind": "report" if r.get("reportedDate") else "period_end",
                            "eps_estimate": self._num(r.get("estimatedEPS")),
                            "eps_actual": self._num(r.get("reportedEPS")),
                            "surprise_pct": self._num(r.get("surprisePercentage"))})
        if not history:
            return None
        history.sort(key=lambda r: r["date"])
        recent = history[-4:]
        measured = [r for r in recent
                    if r["eps_actual"] is not None and r["eps_estimate"] is not None]
        beats = sum(1 for r in measured if r["eps_actual"] >= r["eps_estimate"])
        out: dict = {"symbol": sym, "report_history": history}
        if measured:
            out["beat_streak"] = f"{beats}/{len(measured)} beats"
        return out

    def movers(self, top: int = 20) -> dict:
        self._need_key()
        try:
            data = self._query("function=TOP_GAINERS_LOSERS")
        except ProviderError as exc:
            log.debug("alphavantage movers failed: %s", exc)
            return None
        out: dict = {}
        for side, key in (("gainers", "top_gainers"), ("losers", "top_losers"),
                          ("most_active", "most_actively_traded")):
            rows = []
            for t in (data.get(key) or [])[: top * 3]:
                price = self._num(t.get("price"))
                volume = self._num(t.get("volume")) or 0
                # The movers rule, same as Polygon's: sub-$5 names and thin
                # turnover are arithmetic, not information.
                if not price or price < 5 or volume * price < 1_000_000:
                    continue
                rows.append({"symbol": t.get("ticker"), "price": price,
                             "change_pct": self._num(t.get("change_percentage")),
                             "volume": volume})
                if len(rows) >= top:
                    break
            out[side] = rows
        return out

    def corporate_actions(self, symbol: str) -> dict | None:
        """Alpha Vantage's DIVIDENDS and SPLITS functions — both on the free
        tier, both carrying the full date set. Two of the day's 25 calls,
        so the payload is held in the series cache like a chart page."""
        self._need_key()
        sym = symbol.upper()
        divs = self._series(f"function=DIVIDENDS&symbol={sym}", (sym, "DIVIDENDS"))
        dividends = [{
            "ex_date": r.get("ex_dividend_date"), "amount": self._num(r.get("amount")), "adjusted_amount": None,
            "currency": None, "declaration_date": _av_date(r.get("declaration_date")),
            "record_date": _av_date(r.get("record_date")), "payment_date": _av_date(r.get("payment_date")),
        } for r in (divs.get("data") or []) if r.get("ex_dividend_date")]
        sp = self._series(f"function=SPLITS&symbol={sym}", (sym, "SPLITS"))
        splits = []
        for r in sp.get("data") or []:
            if not r.get("effective_date"):
                continue
            factor = self._num(r.get("split_factor"))
            if factor:
                from alphadesk.ingest.prices import split_ratio_parts
                frm, to = split_ratio_parts(factor)
                splits.append({"date": r["effective_date"], "from": frm, "to": to})
        if not dividends and not splits:
            return None
        dividends.sort(key=lambda r: r["ex_date"] or "", reverse=True)
        splits.sort(key=lambda r: r["date"] or "", reverse=True)
        return {"symbol": sym, "dividends": dividends, "splits": splits}

    def earnings_history(self, symbol: str) -> dict | None:
        return _history_from_context(self.earnings_context(symbol))

    # ── honestly absent ────────────────────────────────────────────────────

    def economic_calendar(self, start: str, end: str) -> list[dict] | None: return None
    def category_movers(self, category: str, top: int = 20) -> dict | None: return None
    def macro(self) -> dict | None: return None
    def sector_change_pct(self, sector: str | None) -> float | None: return None
    def market_tape(self) -> list[dict] | None: return None
    def index_board(self) -> list[dict] | None: return None
    def option_expirations(self, symbol: str) -> list[str] | None: return None

    def option_chain(self, symbol: str, expiry: str) -> dict | None:
        return None

    def crypto_movers(self, top: int = 20) -> dict | None:
        return None


# A coin's 24-hour dollar volume past this many times its market cap is a
# data error, not trading (2026-09-15: CoinGecko sent Ethereum's as about
# $1.19e19, a billion times the real ~$12B, beside a ~$290B market cap).
COINGECKO_VOLUME_MAX_CAP_MULTIPLE = 10


def coingecko_volume(total_volume, market_cap) -> tuple[float, bool]:
    """(the volume to use, whether it was discarded). A volume past
    COINGECKO_VOLUME_MAX_CAP_MULTIPLE × the market cap reads as none, and is
    flagged so a turnover floor does not drop the coin for a figure the
    vendor got wrong. Pure."""
    try:
        v = float(total_volume or 0)
        cap = float(market_cap or 0)
    except (TypeError, ValueError):
        return 0.0, False
    if cap > 0 and v > cap * COINGECKO_VOLUME_MAX_CAP_MULTIPLE:
        return 0.0, True
    return v, False


class CoinGeckoPrices:
    """CoinGecko, on the user's own demo or pro key (2026-09-13: no keyless
    calls). Serves the crypto surfaces; everything else answers None so the
    router asks the next vendor. The surfaces are filled in by the movers
    and company modules that already speak CoinGecko's payloads."""

    name = "coingecko"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()

    def _need_key(self) -> None:
        if not self.api_key:
            raise ProviderError("no CoinGecko key")

    def category_movers(self, category: str, top: int = 20) -> dict | None:
        """Coins by market cap from /coins/markets — theirs' "All" order —
        with the 24-hour change and dollar volume."""
        if category != "crypto":
            return None
        self._need_key()
        # The top 250 by market cap, CoinGecko's page limit, in one request:
        # the list may be cut to the coins the reader can trade on Alpaca
        # (ingest/movers.py), which keeps about a fifth of the top 50.
        per = 250
        data = _get_json(f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc"
                         f"&per_page={per}&page=1&sparkline=false&price_change_percentage=24h",
                         {"x-cg-demo-api-key": self.api_key}, timeout=20)
        rows = []
        for c in data or []:
            sym = str(c.get("symbol") or "").upper()
            if not sym or c.get("current_price") is None:
                continue
            vol, suspect = coingecko_volume(c.get("total_volume"), c.get("market_cap"))
            rows.append({"symbol": f"{sym}-USD", "display": sym, "name": c.get("name"), "price": c.get("current_price"),
                         "change_pct": c.get("price_change_percentage_24h"), "volume": vol,
                         "volume_is_dollars": True, "volume_suspect": suspect})
        if not rows:
            return None
        from alphadesk.ingest.movers import _row, tabs_from_list
        normal = [{**_row(r["symbol"], r["price"], r["change_pct"], r["volume"], name=r["name"], display=r["display"],
                          turnover_is_volume=True), "volume_is_dollars": True, "volume_suspect": r["volume_suspect"]}
                  for r in rows]
        return {"tabs": tabs_from_list(normal), "source": "coingecko"}


register("prices", CoinGeckoPrices.name, CoinGeckoPrices)
register("prices", FmpPrices.name, FmpPrices)
register("prices", PolygonPrices.name, PolygonPrices)
register("prices", FinnhubPrices.name, FinnhubPrices)
register("prices", AlphaVantagePrices.name, AlphaVantagePrices)
