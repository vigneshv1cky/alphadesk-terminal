"""Vendor-neutral price-series helpers (2026-09-13).

What used to live here — Yahoo downloads, the server-wide Alpaca client, the
Nasdaq-armed earnings context, the Yahoo quote and movers — is gone: every
market figure now comes from a vendor the signed-in user connected, through
providers/ (the data router). What remains is the arithmetic every vendor's
bars pass through, so a chart carries the same indicators and the same
coverage verdict whichever vendor served it:

  * build_series_payload — bars to the chart payload: OHLC, RSI-9,
    MACD(12,26,9), thresholds, interval metadata and the coverage verdict.
  * the interval catalogue and range rules (resolve_interval, page_window).
  * _coverage_stats / _daily_coverage — on a sparse feed a "1-minute"
    series can be a handful of prints stretched across days, and it renders
    identically to a real one; `indicators_reliable` is what the UI reads.
  * clip_unbacked_wicks, merge_overnight — bar hygiene.
  * match_report_periods, fill_revenue_estimates, split_ratio_parts — the
    earnings and corporate-action joins.
"""

import logging
import math
from typing import Optional

from alphadesk.config import ET, RSI_CROSS_OVERBOUGHT, RSI_CROSS_OVERSOLD

log = logging.getLogger("alphadesk.prices")


def split_ratio_parts(ratio: float) -> tuple[int, int]:
    """Yahoo records a split as one multiplier — 4.0 for four-for-one, 0.5
    for a one-for-two reverse, 1.5 for three-for-two. As (from, to) shares:
    4.0 -> (1, 4), 0.5 -> (2, 1), 1.5 -> (2, 3)."""
    from fractions import Fraction
    fr = Fraction(ratio).limit_denominator(1000)
    return fr.denominator, fr.numerator


def match_report_periods(report_dates: list[str], period_ends: list[str],
                         max_lag_days: int = 120) -> dict[str, str]:
    """Which fiscal quarter each report covered: the latest period end
    strictly before the report date and within max_lag_days of it (a
    quarter is reported two to eight weeks after it closes). Each period
    is claimed once, by the earliest report after it, so a rescheduled or
    duplicate date cannot borrow a neighbour's quarter."""
    from datetime import date
    def _d(s: str) -> Optional[date]:
        try:
            return date.fromisoformat(s[:10])
        except (TypeError, ValueError):
            return None
    ends = sorted({e for e in (period_ends or []) if _d(e)}, key=_d)
    out: dict[str, str] = {}
    taken: set[str] = set()
    for rd in sorted((r for r in report_dates if _d(r)), key=_d):
        r = _d(rd)
        best = None
        for e in ends:
            if e in taken:
                continue
            ed = _d(e)
            if ed < r and (r - ed).days <= max_lag_days:
                best = e
        if best:
            out[rd] = best
            taken.add(best)
    return out


def fill_revenue_estimates(reports: list[dict], by_date: dict[str, dict]) -> int:
    """Copy a keyed calendar's revenue estimate onto each report that lacks
    one, matching the report date exactly or within three days (vendors
    disagree by a day on when a company reported). Returns the count
    filled. Nothing already present is overwritten."""
    if not by_date:
        return 0
    from datetime import date as _date
    keyed = []
    for k, v in by_date.items():
        try:
            keyed.append((_date.fromisoformat(k), v))
        except ValueError:
            continue
    filled = 0
    for r in reports:
        if r.get("revenue_estimate") is not None:
            continue
        try:
            d = _date.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        best = min(((abs((d - k).days), v) for k, v in keyed), key=lambda t: t[0], default=None)
        if best and best[0] <= 3 and best[1].get("revenue_estimate") is not None:
            r["revenue_estimate"] = best[1]["revenue_estimate"]
            filled += 1
    return filled


class SourceUnavailable(Exception):
    """A bar source FAILED — a rate limit, a timeout, a 5xx — as opposed to
    answering that it has no bars. The two used to look the same (an empty
    list), so one rate-limited page read as the end of the history and was
    remembered as such. This propagates to the endpoint as a 503 with a
    Retry-After; an empty list stays what it is, nothing there."""


# THE OVERNIGHT SESSION (2026-09-11). US equities trade 20:00–04:00 ET on
# the Blue Ocean ATS, Sunday night to Friday morning, and theirs draws that
# session in its own tint. Neither the consolidated tape nor IEX carries
# those prints; Alpaca publishes the Blue Ocean feed ("boats") separately,
# on the free key. Adding it is NOT the tape-mixing the one-tape rule
# forbids: that rule is about the SAME session at two volume scales. The
# overnight session has one venue, and Blue Ocean is the whole of it.
_OVERNIGHT_START_MIN = 20 * 60


_OVERNIGHT_END_MIN = 4 * 60


def _is_overnight(ts) -> bool:
    et = ts.astimezone(ET)
    m = et.hour * 60 + et.minute
    return m >= _OVERNIGHT_START_MIN or m < _OVERNIGHT_END_MIN


def merge_overnight(bars: list[dict], night: list[dict]) -> list[dict]:
    """Union by timestamp, the day sessions' bars winning a collision;
    chronological. Pure, so it can be tested without a socket."""
    if not night:
        return bars
    have = {b["ts"].timestamp() for b in bars}
    out = list(bars) + [b for b in night if b["ts"].timestamp() not in have]
    out.sort(key=lambda x: x["ts"])
    return out


# UNBACKED WICKS (2026-09-11). Yahoo's extended-hours minutes carry OHLC but
# no volume — every pre-market and after-hours bar of NVDA's day came back
# with volume 0 — and a few dozen of them carry a high or low five to seven
# percent away from a body that sits within pennies of its neighbours: an
# out-of-sequence print, which theirs drops by its trade condition. We do
# not see conditions, so the test is the shape: a wick with NO volume
# behind it that departs more than _WICK_TOLERANCE from the bar's own body
# AND from both neighbouring closes — nothing traded there and nothing
# followed — is clipped to the body. A bar with volume is never touched.
#
# UNBACKED BODIES (2026-09-12). Apple's after-hours minutes at 16:53 and
# 16:54 on 2026-09-08 came back with volume 0 and a BODY at 334.03 — a
# price the stock reached three days later — between neighbours at 316.3:
# the whole bar, not a wick, was a stray print, and it drew a 5.6% spike.
# No trade happened (the volume says so), so the price cannot have moved:
# a zero-volume bar whose open or close departs more than the tolerance
# from the previous close, with a close within the next three bars back at
# that previous close, is flattened to the previous close. A move that
# holds — the next closes stay where the bar went — is a move and stays.
_WICK_TOLERANCE = 0.01


_BODY_LOOKAHEAD = 3


def clip_unbacked_wicks(bars: list[dict]) -> int:
    """Clip, in place, the unbacked wicks described above. Returns how many
    bars were clipped. Pure over the list, so it can be tested."""
    clipped = 0
    n = len(bars)
    for i, b in enumerate(bars):
        if (b.get("volume") or 0) > 0:
            continue
        o, h, lo, c = b["open"], b["high"], b["low"], b["close"]
        prev_c = bars[i - 1]["close"] if i > 0 else c
        # The body itself: a stray print with no trade behind it and the
        # price back where it was within a few bars.
        if i > 0 and prev_c > 0 and max(abs(o - prev_c), abs(c - prev_c)) / prev_c > _WICK_TOLERANCE:
            ahead = [bars[j]["close"] for j in range(i + 1, min(n, i + 1 + _BODY_LOOKAHEAD))]
            if any(abs(x - prev_c) / prev_c <= _WICK_TOLERANCE for x in ahead):
                b["open"] = b["high"] = b["low"] = b["close"] = prev_c
                clipped += 1
                continue
        body_hi, body_lo = max(o, c), min(o, c)
        next_c = bars[i + 1]["close"] if i + 1 < n else c
        ceiling = max(body_hi, prev_c, next_c) * (1 + _WICK_TOLERANCE)
        floor = min(body_lo, prev_c, next_c) * (1 - _WICK_TOLERANCE)
        touched = False
        if h > ceiling:
            b["high"] = body_hi
            touched = True
        if lo < floor:
            b["low"] = body_lo
            touched = True
        clipped += touched
    return clipped


# A full US regular session is 390 one-minute bars. The IEX feed prints far
# fewer for illiquid names, so this ratio is the honest measure of whether a
# "1-minute" indicator is really computed on 1-minute data.
BARS_PER_SESSION = 390


def _coverage_stats(bars: list[dict]) -> dict:
    """How real is this "1-minute" series? Returns bar count, sessions
    spanned, the fraction of a full session actually present, the median
    intraday gap, and a single indicators_reliable verdict for the UI.

    Exists because the IEX feed's sparsity is invisible on a rendered chart:
    92 bars stretched across 5 sessions draws exactly like 1950 real ones.
    """
    from alphadesk.config import ET, CHART_MAX_MEDIAN_GAP_MIN, CHART_MIN_COVERAGE
    n = len(bars)
    if n < 2:
        return {"bar_count": n, "sessions": 0, "coverage": 0.0,
                "median_gap_min": None, "indicators_reliable": False}
    ets = [b["ts"].astimezone(ET) for b in bars]
    sessions = len({t.date() for t in ets})
    gaps = sorted(g for g in
                  ((bars[i]["ts"] - bars[i - 1]["ts"]).total_seconds() / 60
                   for i in range(1, n))
                  if g < 240)          # drop overnight/weekend gaps
    median_gap = gaps[len(gaps) // 2] if gaps else None
    # The session the feed actually spans: 390 minutes for a regular-hours
    # feed, 960 (04:00–20:00 ET) once it prints extended hours. Dividing a
    # consolidated day by 390 read 2.4 and let a name printing in a fifth
    # of its minutes pass the floor. Capped at 1.0 — "how much of the
    # session is here" cannot exceed all of it.
    mins = [t.hour * 60 + t.minute for t in ets]
    overnight = any(m >= 20 * 60 or m < 4 * 60 for m in mins)
    extended = overnight or any(m < 9 * 60 + 30 or m >= 16 * 60 for m in mins)
    per_session = 1440 if overnight else 960 if extended else BARS_PER_SESSION
    coverage = round(min(1.0, n / (sessions * per_session)), 3) if sessions else 0.0
    reliable = bool(coverage >= CHART_MIN_COVERAGE
                    and median_gap is not None
                    and median_gap <= CHART_MAX_MEDIAN_GAP_MIN)
    # "bar_count", not "bars" — get_chart_series() merges this dict alongside
    # its OHLC array, which owns the "bars" key.
    return {"bar_count": n, "sessions": sessions, "coverage": coverage,
            "session_minutes": per_session,
            "median_gap_min": round(median_gap, 1) if median_gap is not None else None,
            "indicators_reliable": reliable}


# Bar intervals the chart offers. `unit` is Alpaca's. `max_days` is how far
# back that interval can usefully be fetched — vendors thin minute history,
# so asking for 1-minute bars across five years is not a slow request, it is
# an impossible one.
CHART_INTERVALS: dict[str, dict] = {
    "1m":  {"n": 1,  "unit": "Min",  "max_days": 30,   "label": "1 min"},
    "2m":  {"n": 2,  "unit": "Min",  "max_days": 30,   "label": "2 mins"},
    "5m":  {"n": 5,  "unit": "Min",  "max_days": 60,   "label": "5 mins"},
    "15m": {"n": 15, "unit": "Min",  "max_days": 60,   "label": "15 mins"},
    "30m": {"n": 30, "unit": "Min",  "max_days": 60,   "label": "30 mins"},
    "1h":  {"n": 1,  "unit": "Hour", "max_days": 730,  "label": "1 hour"},
    "4h":  {"n": 4,  "unit": "Hour", "max_days": 730,  "label": "4 hours"},
    "1d":  {"n": 1,  "unit": "Day",  "max_days": None, "label": "1 day"},
    "1wk": {"n": 1,  "unit": "Week", "max_days": None, "label": "1 week"},
    "1mo": {"n": 1,  "unit": "Month","max_days": None, "label": "1 month"},
}


# Roughly how many calendar days each range spans, for deciding whether a
# requested interval can actually cover it.
RANGE_DAYS = {"1D": 1, "5D": 5, "1M": 31, "3M": 93, "6M": 186,
              "YTD": 365, "1Y": 365, "5Y": 1825, "MAX": 20000}


# Sub-daily bars come off Alpaca's intraday feed, and the cost of that fetch
# scales with the SPAN asked for, not with the bars returned. Measured against
# a warm server: 3M of hourly is 0.7s, 6M is 3.5s, and YTD/1Y are 9-14s — and
# a year of hourly is 2,031 points in a 449px tile, 4.5 bars to the pixel, so
# it draws indistinguishably from the daily series that answers in 5ms. The
# terminal was offering all ten intervals for every range and charging seconds
# for resolution the screen cannot show.
#
# 3M is the cut: the last span where intraday is both quick and legible.
INTRADAY_MAX_OFFER_DAYS = 93


# Below this an "interval" is a handful of points, not a chart — 4-hour bars
# over one day is a couple of them, and a monthly bar over a year is twelve.
#
# 13 rather than a rounder number because it sits in a real gap: monthly over
# a year estimates 12 and is genuinely too thin to read, while weekly over a
# quarter estimates 13.3 and is a usable chart. The threshold is calibrated to
# the menu it governs, not chosen for tidiness.
_MIN_OFFERABLE_BARS = 13

#: Bars a range may OPEN on, estimated. The rule is still "the finest bar the
#: range offers" (2026-09-11, the reader's call), but a vendor decides what is
#: on offer, and Alpaca reports every intraday interval as reaching ten years:
#: a month then opened on ONE-MINUTE bars — 28,551 of them, 3.4MB of JSON on
#: every range switch (measured 2026-09-15). The ceiling keeps a day and a
#: week on minutes, where they were, and puts a month on five-minute bars,
#: which is what this module's own docstring already described. A reader who
#: wants minutes over a month still picks them: the OFFER is unchanged.
DEFAULT_MAX_BARS = 5_000


# Intraday bars are fetched over `span + 3` CALENDAR days (see the window built
# in get_chart_series), and the feed prints roughly an eight-hour day once
# extended hours are counted. Two-thirds of calendar days are trading days.
#
# Estimating from RANGE_DAYS alone was wrong in a way that mattered: it read
# the 1D range as one day when the fetch actually covers four, so 1D/1m came
# out as 390 bars against 1,553 served and 30-minute bars looked too sparse to
# offer when they are ~50. Checked against measured counts, this lands within a
# few percent on hourly at every range (1Y: estimates 2,031, serves 2,031).
_INTRADAY_LOOKBACK_PAD_DAYS = 3


_FEED_MINUTES_PER_SESSION = 480


_TRADING_DAY_RATIO = 252 / 365


def _interval_minutes(interval: str, table: dict | None = None) -> Optional[float]:
    """Bar length in minutes, or None for daily and coarser. Fractional for
    second bars — a provider that serves them declares a "Sec" unit."""
    spec = (table or CHART_INTERVALS).get(interval)
    if not spec:
        return None
    unit = str(spec["unit"])
    if unit == "Sec":
        return int(spec["n"]) / 60
    if unit == "Min":
        return int(spec["n"])
    if unit == "Hour":
        return int(spec["n"]) * 60
    return None


def interval_seconds(spec: dict) -> float:
    """A bar's length in seconds, for ordering a table fine → coarse."""
    unit = str(spec.get("unit") or "Day")
    n = int(spec.get("n") or 1)
    return n * {"Sec": 1, "Min": 60, "Hour": 3600, "Day": 86400, "Week": 604800, "Month": 2_629_800}.get(unit, 86400)


def _estimated_bars(span_days: int, interval: str, table: dict | None = None) -> float:
    mins = _interval_minutes(interval, table)
    if mins:
        window = span_days + _INTRADAY_LOOKBACK_PAD_DAYS
        return window * _TRADING_DAY_RATIO * (_FEED_MINUTES_PER_SESSION / mins)
    if interval == "1d":
        return span_days * _TRADING_DAY_RATIO   # trading days, not calendar days
    if interval == "1wk":
        return span_days / 7
    return span_days / 30.4                     # 1mo


def available_intervals(range_key: str, table: dict | None = None) -> list[str]:
    """Which intervals this range should actually OFFER.

    The policy lives here rather than in the UI for the same reason CHART_RANGES
    does: the two must not be able to disagree about what "1Y" can serve. The
    UI renders this list and nothing else, so a combination that would be
    downgraded, or that would cost seconds to draw as an unreadable smear, is
    never presented rather than merely regretted afterwards.
    """
    table = table or CHART_INTERVALS
    span = RANGE_DAYS.get((range_key or "1D").upper(), 1)
    out = []
    for key in sorted(table, key=lambda k: interval_seconds(table[k])):
        intraday = _interval_minutes(key, table) is not None
        # Never offer something that would come back as a different series.
        if resolve_interval(range_key, key, table) != key:
            continue
        if intraday and span > INTRADAY_MAX_OFFER_DAYS:
            continue
        if _estimated_bars(span, key, table) < _MIN_OFFERABLE_BARS:
            continue
        out.append(key)
    return out


def default_interval(range_key: str, table: dict | None = None) -> str:
    """The interval a range opens on when the reader has not chosen one: the
    FINEST bar the range offers (2026-09-11, the reader's call — "the lowest
    of the bar options as default"). On the builtin table that is one minute
    for a day or a week, five minutes for a month, an hour for a quarter,
    daily beyond, because past 93 days no intraday bar is offered at all."""
    table = table or CHART_INTERVALS
    offered = available_intervals(range_key, table)
    span = RANGE_DAYS.get((range_key or "1D").upper(), 1)
    # The ceiling is about MINUTE bars: a daily series is small whatever the
    # span, and a decade of days is the right granularity for a decade.
    fits = [k for k in offered
            if _interval_minutes(k, table) is None or _estimated_bars(span, k, table) <= DEFAULT_MAX_BARS]
    if fits:
        return fits[0]
    if offered:
        return offered[-1]
    return "1m" if span <= 5 and "1m" in table else ("1d" if "1d" in table else next(iter(table)))


def resolve_interval(range_key: str, wanted: str | None, table: dict | None = None) -> str:
    """The finest interval that can actually cover `range_key`.

    Returned rather than enforced silently: the caller reports what it got, so
    a reader who asked for 1-minute bars over a year can see they were served
    daily instead of quietly believing the chart is minute data.

    `table` is the ACTIVE PROVIDER's interval catalogue (2026-09-10) — what it
    serves and how far back each reaches — so a reader whose key carries
    second bars and years of minutes is offered them, and one whose provider
    has neither is not. Absent, the builtin table applies.
    """
    table = table or CHART_INTERVALS
    span = RANGE_DAYS.get((range_key or "1D").upper(), 1)
    want = (wanted or "").lower()
    if want not in table:
        return default_interval(range_key, table)
    cap = table[want]["max_days"]
    if cap is not None and span > cap:
        # The next coarser interval whose reach covers the span.
        for key in sorted(table, key=lambda k: interval_seconds(table[k])):
            if interval_seconds(table[key]) <= interval_seconds(table[want]):
                continue
            c = table[key]["max_days"]
            if c is None or span <= c:
                return key
        return max(table, key=lambda k: interval_seconds(table[k]))
    return want


# The ranges the UI offers, mapped to how each is actually sourced. Kept here
# rather than in the UI so the two can never disagree about what "3M" means.
CHART_RANGES: dict[str, dict] = {
    "1D":  {"kind": "intraday", "days": 1},
    "5D":  {"kind": "intraday", "days": 5},
    "1M":  {"kind": "daily", "period": "1mo"},
    "3M":  {"kind": "daily", "period": "3mo"},
    "6M":  {"kind": "daily", "period": "6mo"},
    "YTD": {"kind": "daily", "period": "ytd"},
    "1Y":  {"kind": "daily", "period": "1y"},
    "5Y":  {"kind": "daily", "period": "5y"},
    "MAX": {"kind": "daily", "period": "max"},
}


def _daily_coverage(bars: list[dict]) -> dict:
    """Coverage for a DAILY series.

    The intraday gate asks "did the feed print in most minutes", which is
    meaningless here — a daily bar per trading day is complete by construction,
    so a daily series is as good as this feed gets.

    It used to also fail the whole series below 35 bars, MACD's 26+9 warm-up.
    That is a real limit but it is MACD's, and applying it to everything hid
    RSI-9 from a 24-bar month that could support it perfectly well — switching
    range to 1M silently dropped every pane the reader had chosen. Warm-up is
    per indicator and is judged where each one is drawn (PANE_INDICATORS'
    minBars); what this flag answers is the question it was invented for,
    whether the FEED can be trusted.
    """
    n = len(bars)
    return {"bar_count": n, "sessions": n, "coverage": 1.0 if n else 0.0,
            "median_gap_min": None, "indicators_reliable": n > 0}


def week52_from_bars(bars: list[dict]) -> tuple[float | None, float | None]:
    """The 52-week high and low from a year of daily bars, from the highs
    and lows where the vendor sends them and the closes otherwise.

    A quote does not always carry the range: Alpaca's carries none at all,
    which left the column empty on every page that shows it. The bars are
    the reader's own, one request for a whole basket, and the figure is a
    plain max and min — no vendor's definition to disagree with. Pure."""
    highs = [b.get("high") if b.get("high") is not None else b.get("close") for b in bars]
    lows = [b.get("low") if b.get("low") is not None else b.get("close") for b in bars]
    hi = [h for h in highs if h is not None]
    lo = [x for x in lows if x is not None]
    return (min(lo) if lo else None, max(hi) if hi else None)


def build_series_payload(sym: str, bars: list[dict], used: str,
                         range_key: str | None = None, interval: str | None = None,
                         stats: dict | None = None, table: dict | None = None) -> Optional[dict]:
    """Bars → the chart payload: OHLC, RSI-9, MACD(12,26,9), thresholds,
    interval metadata and the coverage verdict.

    THE shared assembly, deliberately public: any bar source — the user's Alpaca,
    Polygon, Finnhub or Alpha Vantage key — hands its bars
    here, so every chart carries the same indicator math and passes the same
    data-quality gate. `stats` overrides the minute-density measurement for
    series whose completeness is structural (daily bars); None applies
    `_coverage_stats`. Fewer than two bars is no chart at all.
    """
    # Every bar source passes through here — Alpaca, Polygon,
    # Finnhub, Alpha Vantage — so the unbacked-wick clip applies to all of
    # them. It costs nothing where volume is reported (a bar with volume is
    # never touched) and it is the only place a stray print can be caught
    # for a source that does not filter by trade condition. Intraday only:
    # a daily bar's range is a whole session's.
    if _interval_minutes(used) is not None and bars:
        n = clip_unbacked_wicks(bars)
        if n:
            log.debug("clipped %d unbacked wicks for %s %s", n, sym, used)
    # A bar with no price is not a bar. A vendor's daily frame can open with
    # an all-NaN row (seen on NVDA's 3M range, 2026-09-05), and a NaN close
    # poisons the whole response: the JSON encoder refuses it and the chart
    # 500s. Dropped here, at the one seam every provider passes through.
    bars = [b for b in bars
            if all(isinstance(b.get(k), (int, float)) and math.isfinite(b[k])
                   for k in ("open", "high", "low", "close"))]
    if len(bars) < 2:
        return None
    import pandas as pd
    closes = pd.Series([b["close"] for b in bars])

    delta = closes.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / 9, min_periods=9, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 9, min_periods=9, adjust=False).mean()
    rs = avg_gain / avg_loss.where(avg_loss != 0, other=float("nan"))
    rsi = (100 - 100 / (1 + rs)).where(avg_loss != 0, other=100.0)

    macd_line = (closes.ewm(span=12, adjust=False).mean()
                 - closes.ewm(span=26, adjust=False).mean())
    signal_line = macd_line.ewm(span=9, adjust=False).mean()

    def _pt(v):
        f = float(v)
        return round(f, 4) if math.isfinite(f) else None

    return {
        "symbol": sym,
        "bars": [{"t": b["ts"].isoformat(), "o": b["open"], "h": b["high"],
                  "l": b["low"], "c": b["close"], "v": b.get("volume", 0.0)}
                 for b in bars],
        "rsi_9": [_pt(v) for v in rsi],
        "macd": [_pt(v) for v in macd_line],
        "macd_signal": [_pt(v) for v in signal_line],
        "macd_hist": [_pt(a - b) for a, b in zip(macd_line, signal_line)],
        "thresholds": {"rsi_oversold": RSI_CROSS_OVERSOLD,
                       "rsi_overbought": RSI_CROSS_OVERBOUGHT},
        "interval": used,
        "interval_label": (table or CHART_INTERVALS).get(used, {}).get("label", used),
        "interval_requested": (interval or "").lower() or None,
        "range": (range_key or "").upper() or None,
        # What the toolbar may offer for THIS range, from the provider that
        # served it. Travels with the series so the client never has to hold
        # a copy of the policy.
        "intervals": available_intervals(range_key or "1D", table),
        **(stats if stats is not None else _coverage_stats(bars)),
    }


# How far one HISTORY PAGE reaches back from its cursor, per range: the
# range's own span, so panning left past the first page fetches another
# window of the same size. MAX has no page — the first fetch is everything.
PAGE_DAYS = {"1D": 4, "5D": 8, "1M": 31, "3M": 93, "6M": 186,
             "YTD": 365, "1Y": 365, "5Y": 1826}

#: A page below this many bars is not worth drawing: the chart's left edge
#: grows by a sliver and the reader pans again straight away. Measured on
#: VEEA at one-minute bars (2026-09-15): four calendar days produced 62, then
#: 83, then 39 bars, so panning out crawled. A liquid name reaches the floor
#: on the first window and never widens.
PAGE_MIN_BARS = 600

#: The ceiling on one page, whatever the chart asks for: a page is a
#: response a reader waits on, and 6,000 bars is already a wide screen twice
#: over. Beyond it the chart asks again from its new edge.
PAGE_MAX_BARS = 6_000

#: How many times a page may widen before it is sent as it stands. Each
#: widening doubles the span, so the last attempt reaches 16 range-spans
#: back — a thin one-minute name gets about two months in one page.
PAGE_WIDENINGS = 4

#: HOW FAR LEFT A BAR SIZE GOES (2026-09-16). Scrolling left does not go on
#: for ever: each bar size has a reach, and at its end the chart says so
#: rather than fetching a thinner and thinner trickle of intraday bars from
#: years ago. This is the behaviour the reader asked for, and the one every
#: charting terminal has — the bar size is what carries the limit, not the
#: range button, so a minute chart stops sooner than an hourly one and the
#: way to see more is a longer range, which is served by a coarser bar.
#: None means no ceiling of ours: the vendor's own earliest bar ends it.
HISTORY_REACH_DAYS: dict[str, int | None] = {
    "1s": 7, "5s": 7, "15s": 14, "30s": 14,
    "1m": 60, "2m": 60, "5m": 180, "15m": 365, "30m": 365,
    "1h": 730, "2h": 730, "4h": 1_095,
    "1d": None, "1wk": None, "1mo": None,
}


def history_floor(interval: str, now):
    """The earliest instant this bar size may be asked for, or None where
    only the vendor's own reach ends it. Pure."""
    from datetime import timedelta
    days = HISTORY_REACH_DAYS.get((interval or "").lower(), None)
    return None if days is None else now - timedelta(days=days)


def page_window(range_key: str, before, attempt: int = 0, floor=None) -> tuple | None:
    """(start, end) for the history page ending at `before`, or None when the
    range has no further pages. `attempt` doubles the depth each step, for a
    caller filling a page that came back too thin to draw; `floor` is the
    earliest instant this bar size reaches, and a window never digs past it."""
    from datetime import timedelta
    days = PAGE_DAYS.get((range_key or "1D").upper())
    if days is None:
        return None
    start = before - timedelta(days=days * (2 ** max(0, attempt)))
    if floor is not None:
        if before <= floor:
            return None
        start = max(start, floor)
    return start, before


def page_attempts(range_key: str, before, floor=None) -> list[tuple]:
    """The widening windows for one history page, shallowest first. Empty
    when the range has no further pages, or when the cursor already sits at
    the end of this bar size's reach. A window clipped by the floor is the
    last one: reaching further asks the vendor for the same bars twice."""
    out: list[tuple] = []
    for attempt in range(PAGE_WIDENINGS + 1):
        window = page_window(range_key, before, attempt, floor)
        if window is None:
            return []
        out.append(window)
        if floor is not None and window[0] <= floor:
            break
    return out


def page_wanted(need: int | None = None) -> int:
    """How many bars one page should carry: what the chart asked for, never
    below a page worth drawing and never above what one response should
    make a reader wait for."""
    return min(max(int(need or PAGE_MIN_BARS), PAGE_MIN_BARS), PAGE_MAX_BARS)


def page_is_thin(bars, need: int | None = None) -> bool:
    """True when this page leaves the chart still waiting — fewer bars than
    the blank space it asked to fill (or than a page worth drawing). The
    caller reaches further back and asks the vendor again."""
    return len(bars or []) < page_wanted(need)


def page_trim(bars, need: int | None = None) -> list:
    """The NEWEST bars of an overshooting page. A window widens by doubling,
    so the last one can reach far past what was asked for — a fifteen-minute
    page came back with 9,334 bars and a megabyte of JSON (measured
    2026-09-16). The bars nearest the cursor are the ones that join what the
    chart already holds; the rest are fetched again if the reader keeps
    going. Pure."""
    rows = list(bars or [])
    want = page_wanted(need)
    return rows[-want:] if len(rows) > want else rows


#: How far back the overnight session is rebuilt from prints rather than
#: taken as the vendor's bars. Every trade on the overnight feed is
#: overnight by nature, so the request is self-limiting, but a liquid name
#: still prints tens of thousands of times a week: NVDA measured 11,818
#: trades over one night (0.36s) and 51,261 over five (1.58s) on
#: 2026-09-16. One and five days are the ranges where the night is visible
#: bar by bar, so that is where it is worth rebuilding.
TRADE_NIGHT_MAX_DAYS = 5

#: Beyond it the feed's own bars are used: reading every print of a busy
#: name over a week took 2.28s (NVDA, eight nights), which is not worth it
#: for nights drawn a few pixels wide.


def bars_from_trades(trades, seconds: int) -> list[dict]:
    """Bars of `seconds` each, built from raw prints: (timestamp, price,
    size) in, the usual bar dicts out, oldest first.

    WHY THIS EXISTS (2026-09-16). A vendor's own bars leave out odd lots,
    which is the right convention for the consolidated tape — an odd lot
    does not set the last sale. Overnight it is the wrong picture: measured
    on CrowdStrike, 466 of 540 prints between 20:00 and 02:00 were odd lots,
    so the vendor's bars covered 38 of the 135 minutes that actually traded
    and the chart drew a scattering of dashes where the reader's other
    terminal drew a continuous session. Built from the prints themselves,
    including the odd lots, the same night fills 279 minutes. Pure."""
    from datetime import datetime, timezone
    if seconds <= 0:
        return []
    clean = []
    for ts, price, size in trades:
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        if ts is None or p <= 0:
            continue
        clean.append((ts, p, float(size or 0)))
    # In time order, so the open is the first print of the bar and the close
    # the last however the feed delivered them.
    clean.sort(key=lambda t: t[0])
    buckets: dict[int, dict] = {}
    for ts, p, v in clean:
        k = int(ts.timestamp()) // seconds * seconds
        bar = buckets.get(k)
        if bar is None:
            buckets[k] = {"ts": datetime.fromtimestamp(k, tz=timezone.utc),
                          "open": p, "high": p, "low": p, "close": p, "volume": v}
            continue
        bar["high"] = max(bar["high"], p)
        bar["low"] = min(bar["low"], p)
        bar["close"] = p
        bar["volume"] += v
    return [buckets[k] for k in sorted(buckets)]


def _is_tradeable_symbol(sym: str) -> bool:
    """Exclude warrants, rights and units — they carry suffixes that make them
    look like enormous movers while being untradeable in any normal sense."""
    s = sym.upper()
    return not (s.endswith("W") and len(s) > 4) and not s.endswith(("WW", "R", "U"))


def history_reach_note(interval: str, source: str | None = None) -> str:
    """One sentence for the reader who has panned to the end of what the
    vendor holds at this interval."""
    label = CHART_INTERVALS.get(interval, {}).get("label", interval)
    return f"No older {label} bars from this vendor."


def history_ceiling_note(interval: str) -> str:
    """One sentence for the reader who has scrolled to the end of what THIS
    BAR SIZE shows. The way further back is a coarser bar, which is what a
    longer range serves, so the sentence says that rather than leaving the
    edge looking broken."""
    label = CHART_INTERVALS.get(interval, {}).get("label", interval)
    days = HISTORY_REACH_DAYS.get((interval or "").lower())
    if not days:
        return f"No older {label} bars from this vendor."
    span = f"{days // 365} years" if days >= 365 else (f"{days // 30} months" if days >= 60 else f"{days} days")
    return f"{label} bars go back {span}. A longer range shows more, on a larger bar."
