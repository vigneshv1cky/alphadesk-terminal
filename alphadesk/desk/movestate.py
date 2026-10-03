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


def move_state(intraday: list[dict], daily: list[dict]) -> dict:
    """Measurements for the symbol's latest session. `intraday` and `daily` are
    {t, o, h, l, c, v} bars, oldest first."""
    day, bars = latest_session(intraday)
    ctx = daily_context(daily, day)
    if not bars:
        return {"session": None, "reliable": False, "note": "no intraday bars", "daily": ctx}
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
    }
