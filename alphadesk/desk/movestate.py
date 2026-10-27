"""What a move is doing now: measurements of one symbol's latest session against
its own recent history (2026-10-03).

Answers the questions "has it died down", "has it changed direction", "is it
holding": how far the price has given back from its high, whether the last hour
ran against the day, whether volume is thinning, and how big the move is next to
what the symbol normally does. Plain arithmetic on bars. NO VERDICT: nothing
here says a move is over or will continue; each field is a measurement a reader
can weigh.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)
FLAT_PCT = 0.2          # a change smaller than this is called flat
MIN_BARS = 20           # fewer intraday bars than this and the shape is not read


def _at(iso) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(NY) if t.tzinfo else t.replace(tzinfo=NY)


def _sign(pct: float | None) -> str | None:
    if pct is None:
        return None
    return "flat" if abs(pct) < FLAT_PCT else ("up" if pct > 0 else "down")


def _pct(new, old) -> float | None:
    return round(100 * (new / old - 1), 2) if new and old else None


def latest_session(bars: list[dict]) -> tuple[str | None, list[dict]]:
    """(date, bars) of the newest session in `bars` (oldest first, stamped in
    any zone), regular hours only where that leaves a usable series, else all
    of that day's bars (a 24-hour market has no regular hours)."""
    stamped = [(b, _at(b.get("t"))) for b in bars if b.get("c") is not None]
    stamped = [(b, t) for b, t in stamped if t is not None]
    if not stamped:
        return None, []
    day = stamped[-1][1].date()
    today = [(b, t) for b, t in stamped if t.date() == day]
    regular = [(b, t) for b, t in today if OPEN <= t.time() < CLOSE]
    use = regular if len(regular) >= MIN_BARS else today
    return day.isoformat(), [{**b, "_t": t} for b, t in use]


def daily_context(daily: list[dict], session_date: str | None) -> dict:
    """The session's footing in daily terms: the close before it, the usual
    daily range, the run it is part of, and the last sessions side by side."""
    rows = [b for b in daily if b.get("c")]
    done = [b for b in rows if str(b["t"])[:10] < (session_date or "9999")]
    prev_close = done[-1]["c"] if done else None
    window = done[-20:]
    ranges = [100 * (b["h"] - b["l"]) / done[i - 1]["c"]
              for i, b in enumerate(done) if i and b.get("h") and b.get("l") and done[i - 1]["c"]][-20:]
    atr = round(sum(ranges) / len(ranges), 2) if ranges else None
    vols = sorted(b["v"] for b in window if b.get("v"))
    streak = 0
    for prev, cur in zip(reversed(done[:-1]), reversed(done[1:])):
        step = 1 if cur["c"] > prev["c"] else -1 if cur["c"] < prev["c"] else 0
        if step == 0 or (streak and (step > 0) != (streak > 0)):
            break
        streak += step
    hi20 = max((b.get("h") or b["c"] for b in window), default=None)
    lo20 = min((b.get("l") or b["c"] for b in window), default=None)
    recent = []
    prev = None
    for b in rows[-6:]:
        if prev:
            recent.append({"date": str(b["t"])[:10], "change_pct": _pct(b["c"], prev["c"]),
                           "range_pct": round(100 * (b["h"] - b["l"]) / prev["c"], 2) if b.get("h") and b.get("l") else None,
                           "volume": b.get("v")})
        prev = b
    return {"prev_close": prev_close, "typical_daily_range_pct": atr,
            "median_daily_volume": median(vols) if vols else None,
            "consecutive_closes": streak,         # + up, − down, ending at the last full session
            "high_20d": hi20, "low_20d": lo20,
            "recent_sessions": recent}


def move_state(intraday: list[dict], daily: list[dict], history: list[dict] | None = None,
               indicators_reliable: bool = False) -> dict:
    """Measurements for the symbol's latest session. `intraday` and `daily` are
    {t, o, h, l, c, v} bars, oldest first; intraday bars may carry `_rsi` and
    `_macd_hist` (see with_indicators). `history` is a month of intraday bars
    for the usual time of the high, or None to skip it."""
    day, bars = latest_session(intraday)
    ctx = daily_context(daily, day)
    if not bars:
        return {"session": None, "reliable": False, "note": "no intraday bars", "daily": ctx,
                "session_high": session_high([])}
    prev_close = ctx["prev_close"]
    first, last = bars[0], bars[-1]
    hi = max(bars, key=lambda b: b.get("h") if b.get("h") is not None else b["c"])
    lo = min(bars, key=lambda b: b.get("l") if b.get("l") is not None else b["c"])
    hi_p = hi.get("h") if hi.get("h") is not None else hi["c"]
    lo_p = lo.get("l") if lo.get("l") is not None else lo["c"]
    open_p = first.get("o") if first.get("o") is not None else first["c"]
    now = last["_t"]

    def since(minutes):
        edge = now - timedelta(minutes=minutes)
        part = [b for b in bars if b["_t"] >= edge]
        base = part[0].get("o") if part and part[0].get("o") is not None else (part[0]["c"] if part else None)
        return part, base

    hour, hour_base = since(60)
    half, half_base = since(30)
    total_v = sum(b.get("v") or 0 for b in bars)
    hour_v = sum(b.get("v") or 0 for b in hour)
    span_min = max(1.0, (now - first["_t"]).total_seconds() / 60)
    pace = None
    if total_v and hour_v and span_min > 75:
        pace = round((hour_v / min(60.0, span_min)) / (total_v / span_min), 2)   # last hour's pace vs the session's
    gaps = sorted((b["_t"] - a["_t"]).total_seconds() / 60 for a, b in zip(bars, bars[1:]))
    gap = round(median(gaps), 1) if gaps else None
    reliable = len(bars) >= MIN_BARS and (gap is not None and gap <= 5)
    change = _pct(last["c"], prev_close) if prev_close else _pct(last["c"], open_p)
    hour_change = _pct(last["c"], hour_base)
    swing = hi_p - lo_p
    day_dir, hour_dir = _sign(change), _sign(hour_change)
    ctx_range = ctx["typical_daily_range_pct"]
    return {
        "session": day, "bars": len(bars), "median_gap_min": gap, "reliable": reliable,
        "prices": {"prev_close": prev_close, "open": open_p, "high": hi_p, "low": lo_p, "last": last["c"]},
        "change_pct": change,
        "gap_at_open_pct": _pct(open_p, prev_close) if prev_close else None,
        "change_since_open_pct": _pct(last["c"], open_p),
        "high_at": hi["_t"].strftime("%H:%M"), "low_at": lo["_t"].strftime("%H:%M"),
        "minutes_since_high": int((now - hi["_t"]).total_seconds() // 60),
        "minutes_since_low": int((now - lo["_t"]).total_seconds() // 60),
        # How much of the session's swing has been given back from the high:
        # 0 at the high, 100 at the low.
        "given_back_from_high_pct": round(100 * (hi_p - last["c"]) / swing, 1) if swing else None,
        "down_from_high_pct": _pct(last["c"], hi_p),
        "up_from_low_pct": _pct(last["c"], lo_p),
        "last_60min_change_pct": hour_change,
        "last_30min_change_pct": _pct(last["c"], half_base),
        "direction": {"session": day_dir, "last_60min": hour_dir,
                      "last_hour_runs_against_session": bool(day_dir in ("up", "down") and hour_dir in ("up", "down")
                                                             and day_dir != hour_dir)},
        "volume": {"session_total": total_v or None,
                   "vs_median_daily": round(total_v / ctx["median_daily_volume"], 2)
                   if total_v and ctx["median_daily_volume"] else None,
                   # Above 1: the last hour traded faster than the session's average pace; below 1, slower.
                   "last_hour_pace_vs_session": pace},
        "size_vs_normal": {"typical_daily_range_pct": ctx_range,
                           "session_range_pct": _pct(hi_p, lo_p),
                           "move_in_typical_ranges": round(abs(change) / ctx_range, 1) if change is not None and ctx_range else None},
        "daily": ctx,
        "session_high": session_high(bars, prev_close=prev_close, typical_range_pct=ctx_range,
                                     reliable=reliable, indicators_reliable=indicators_reliable,
                                     history=history, session_date=day),
    }


# ── Has the day's high been put in (2026-10-27, the owner's "daily peaks") ──
#
# The session high, read more closely than the block above: whether new highs
# are still being set, the price against the session's volume-weighted
# average, whether momentum peaked BEFORE the price did, how the volume split
# between rising and falling bars either side of the high, and when this
# stock's daily high has usually come. Every figure is a measurement; nothing
# here says the high is in. A flag that can read "yes" can as easily read
# "no", and each one carries the readings it was made from.

MOMENTUM_RSI_MARGIN = 5.0   # RSI points: a smaller shortfall at the high is not flagged
LEAD_IN_MIN = 30            # the minutes leading into the high whose volume is compared
HABIT_SESSIONS = 20         # past sessions read for the usual time of the high
HABIT_MIN_SESSIONS = 10     # fewer usable past sessions and the habit is withheld
HABIT_MIN_BARS = 20         # a past session with fewer regular-hours bars is skipped


def _h(b) -> float:
    return b["h"] if b.get("h") is not None else b["c"]


def _l(b) -> float:
    return b["l"] if b.get("l") is not None else b["c"]


def _updown(part: list[dict], prior: float | None) -> dict:
    """Volume on bars that closed above the previous bar's close against bars
    that closed below it. An unchanged bar counts on neither side."""
    up = down = 0.0
    n_up = n_down = 0
    prev = prior
    for b in part:
        v = b.get("v") or 0
        if prev is not None:
            if b["c"] > prev:
                up, n_up = up + v, n_up + 1
            elif b["c"] < prev:
                down, n_down = down + v, n_down + 1
        prev = b["c"]
    return {"bars": len(part), "up_bars": n_up, "down_bars": n_down,
            "up_volume": up, "down_volume": down,
            # Above 1: more volume traded on rising bars than on falling ones.
            "up_to_down_volume": round(up / down, 2) if down else None}


def _momentum(bars: list[dict], hi_i: int, key: str, margin: float) -> dict | None:
    at = bars[hi_i].get(key)
    earlier = [(b[key], b["_t"]) for b in bars[:hi_i] if b.get(key) is not None]
    if at is None:
        return None
    if not earlier:
        return {"at_high": at, "earlier_peak": None, "earlier_peak_at": None,
                "peaked_before_price": None}
    peak, when = max(earlier, key=lambda x: x[0])
    return {"at_high": at, "earlier_peak": peak, "earlier_peak_at": when.strftime("%H:%M"),
            # True: momentum's highest reading came earlier and was higher than
            # at the price high. False: momentum was as high or higher at the
            # price high. Both readings are here to check it.
            "peaked_before_price": bool(peak - at > margin)}


def high_habit(history: list[dict], session_date: str | None, now_hm: str) -> dict:
    """When this stock's regular-session high was set in each of the last
    HABIT_SESSIONS sessions before `session_date`, and how many of them came
    later than `now_hm` (HH:MM New York). Withheld below HABIT_MIN_SESSIONS."""
    days: dict[str, list[dict]] = {}
    for b in history:
        t = _at(b.get("t"))
        if t is None or b.get("c") is None or not (OPEN <= t.time() < CLOSE):
            continue
        d = t.date().isoformat()
        if session_date and d >= session_date:
            continue
        days.setdefault(d, []).append({**b, "_t": t})
    usable = [(d, bs) for d, bs in sorted(days.items()) if len(bs) >= HABIT_MIN_BARS][-HABIT_SESSIONS:]
    if len(usable) < HABIT_MIN_SESSIONS:
        return {"sessions": len(usable), "reliable": False,
                "note": f"only {len(usable)} past sessions with enough intraday bars; "
                        f"{HABIT_MIN_SESSIONS} are needed"}
    times = []
    for d, bs in usable:
        top = max(bs, key=_h)       # the first bar at the session's highest price
        times.append({"date": d, "high_at": top["_t"].strftime("%H:%M")})
    mins = sorted(int(x["high_at"][:2]) * 60 + int(x["high_at"][3:]) for x in times)
    mid = int(median(mins))
    return {"sessions": len(times), "reliable": True,
            "window": f"the {len(times)} sessions from {times[0]['date']} to {times[-1]['date']}",
            "median_high_at": f"{mid // 60:02d}:{mid % 60:02d}",
            "compared_with": now_hm,
            # How many of those sessions set their high LATER in the day than
            # the time this session has reached.
            "set_later_than_now": sum(1 for x in times if x["high_at"] > now_hm),
            "highs": times}


def session_high(bars: list[dict], *, prev_close: float | None = None,
                 typical_range_pct: float | None = None, reliable: bool = True,
                 indicators_reliable: bool = False, history: list[dict] | None = None,
                 session_date: str | None = None) -> dict:
    """Measurements around the session high. `bars` are the session's bars as
    latest_session returns them, optionally carrying `_rsi` and `_macd_hist`.
    Withheld whole when the session's bars are too thin to read a shape."""
    if not bars or not reliable:
        return {"reliable": False,
                "note": "the session's intraday bars are too few or too sparse to read where the high was set"}
    now = bars[-1]["_t"]
    last = bars[-1]["c"]
    run, hi_i, new_highs = _h(bars[0]), 0, []
    for i, b in enumerate(bars[1:], 1):
        if _h(b) > run:
            run, hi_i = _h(b), i
            new_highs.append(b["_t"])
    hi_p, lo_p = run, min(_l(b) for b in bars)
    at = bars[hi_i]

    vol = sum(b.get("v") or 0 for b in bars)
    vwap = (sum((_h(b) + _l(b) + b["c"]) / 3 * (b.get("v") or 0) for b in bars) / vol) if vol else None

    lead = [b for b in bars[:hi_i + 1] if b["_t"] >= at["_t"] - timedelta(minutes=LEAD_IN_MIN)]
    lead_start = bars.index(lead[0]) if lead else 0
    lead_prior = bars[lead_start - 1]["c"] if lead_start else None

    rng = (100 * (hi_p - lo_p) / prev_close) if prev_close else None
    regular = all(OPEN <= b["_t"].time() < CLOSE for b in bars)

    out = {
        "reliable": True,
        "high": hi_p, "high_at": at["_t"].strftime("%H:%M"),
        "minutes_since_high": int((now - at["_t"]).total_seconds() // 60),
        "down_from_high_pct": _pct(last, hi_p),
        "at_session_high": hi_i == len(bars) - 1,
        "new_highs": {"last_30min": sum(1 for t in new_highs if t > now - timedelta(minutes=30)),
                      "last_60min": sum(1 for t in new_highs if t > now - timedelta(minutes=60)),
                      "session": len(new_highs)},
        "vwap": {"session_vwap": round(vwap, 4) if vwap else None,
                 "last_vs_vwap_pct": _pct(last, vwap) if vwap else None,
                 "high_vs_vwap_pct": _pct(hi_p, vwap) if vwap else None},
        "volume": {"since_high": _updown(bars[hi_i + 1:], at["c"]),
                   f"last_{LEAD_IN_MIN}min_into_high": _updown(lead, lead_prior)},
        "range": {"session_range_pct": round(rng, 2) if rng is not None else None,
                  "typical_daily_range_pct": typical_range_pct,
                  # The session's low-to-high range in units of the stock's
                  # typical daily range over the last 20 sessions.
                  "session_range_in_typical_ranges": round(rng / typical_range_pct, 2)
                  if rng is not None and typical_range_pct else None},
    }
    if indicators_reliable:
        out["momentum"] = {"reliable": True,
                           "rsi_9": _momentum(bars, hi_i, "_rsi", MOMENTUM_RSI_MARGIN),
                           "macd_hist": _momentum(bars, hi_i, "_macd_hist", 0.0),
                           "rsi_margin_points": MOMENTUM_RSI_MARGIN}
    else:
        out["momentum"] = {"reliable": False,
                           "note": "the intraday feed fails the chart's coverage gate, so RSI and MACD are not read"}
    if history is None:
        out["usual_high_time"] = None
    elif not regular:
        out["usual_high_time"] = {"reliable": False, "note": "no regular session to compare (round-the-clock market)"}
    else:
        now_hm = min(now.strftime("%H:%M"), "15:59")
        out["usual_high_time"] = high_habit(history, session_date, now_hm)
    return out


def with_indicators(series: dict) -> list[dict]:
    """The intraday series' bars with each bar's own RSI-9 and MACD histogram
    attached, so the session's slice keeps them."""
    bars = series.get("bars") or []
    rsi = series.get("rsi_9") or []
    hist = series.get("macd_hist") or []
    out = []
    for i, b in enumerate(bars):
        out.append({**b, "_rsi": rsi[i] if i < len(rsi) else None,
                    "_macd_hist": hist[i] if i < len(hist) else None})
    return out


def for_symbol(sym: str, history: bool = True) -> dict:
    """Fetch the reader's bars through the price router and measure: the
    latest session's minute bars, three months of daily bars and, with
    `history`, a month of five-minute bars for the usual time of the high."""
    from alphadesk.app import dashboard
    from alphadesk.providers import get_prices
    series = get_prices().chart_series(sym, days=5) or {}
    daily = dashboard.api_chart(sym, range="3M", interval="1d").get("bars") or []
    past = None
    if history:
        try:
            past = dashboard.api_chart(sym, range="1M", interval="5m").get("bars") or []
        except Exception:            # the habit is withheld, the rest still answers
            past = []
    return move_state(with_indicators(series), daily, history=past,
                      indicators_reliable=bool(series.get("indicators_reliable")))
