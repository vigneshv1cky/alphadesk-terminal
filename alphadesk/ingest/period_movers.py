"""Gainers, losers and most active over a CALENDAR WEEK or MONTH (2026-11-04).

The session list answers "what moved on one day". This answers "what moved
this week" and "what moved in October": the whole market, ranked by each
stock's return over the period — close of the last session BEFORE the period
against the close of its last session — not one day's move and not daily
lists added together.

CALENDAR, NOT ROLLING (the owner's call). A week is Monday to Friday, a month
is its first to last trading day, and the reader names one by any date inside
it. The base is the close before the period opened, so a Monday gap counts
toward the week it happened in — the same close-to-close rule the session
list follows. A period still under way ends at its last FINISHED session and
says so (`complete: false`, change label WTD or MTD); today's session is never
counted, because its bars can still change.

HOW IT IS WORKED OUT, cheaply and checked:

1. SCREEN from two whole-market closes — the base session and the end
   session — the same recorded snapshots the session list reads. Two days,
   whatever the period's length.
2. MEASURE the candidates (both ends of the screen and the most traded) from
   their own per-symbol daily bars, split-adjusted on one basis. A split
   inside a month is likely, and a snapshot saved before it sits on another
   basis: every ranked figure comes from the bars, not the snapshots. The
   same bars give each row its period volume and AVERAGE DAILY dollars
   traded, so the turnover floor reads the whole period and one busy day
   cannot carry a thin stock past it.
3. MARK corporate actions inside the period the way the session list does:
   a spin-off ranks on what a holder made, and the feed's actions are named.

A row whose bars cannot be read keeps its screened figure only below the
split-check threshold, marked `checked: false`; an unverifiable large move
is left out and counted in the note.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from alphadesk.desk import sessions as cal
from alphadesk.ingest import movers as mv

log = logging.getLogger("alphadesk.period_movers")

PERIODS = ("week", "month")
PERIOD_CATEGORIES = ("stocks", "etfs")
CHANGE_LABEL = {("week", True): "1W", ("week", False): "WTD",
                ("month", True): "1M", ("month", False): "MTD"}

#: How many rows from each end of the screen (and from the most traded) are
#: measured from their own bars, at least. Three times the list asked for:
#: enough that a split that pushed a real mover a few places down the screen
#: is still measured, few enough to be one batched request.
POOL_MIN = 60
POOL_MULTIPLE = 3
#: The screen's turnover cut is this share of the reader's floor, applied to
#: the mean of the two ends' dollars traded. Loose on purpose: the exact floor
#: is applied afterwards on the period's own average, and a stock that traded
#: thinly on both end days but heavily between them is rare, while a cut too
#: tight would drop it unseen.
SCREEN_TURNOVER_SHARE = 0.5
#: How far back a period may end. `daily_history` answers the sessions ending
#: NOW, so measuring an old period means asking for every session since; past
#: about a year that is the vendor's whole history and the list is not offered.
MAX_SESSIONS_BACK = 260

_NY = ZoneInfo("America/New_York")


# ── the calendar ──────────────────────────────────────────────────────────

def period_window(period: str, anchor: date, today: date) -> dict:
    """The sessions of the calendar week or month holding `anchor`. Pure.

    {period, label, first_day, last_day, sessions: [all sessions in the period],
     base: the session before the first, end: the last FINISHED session in it
     (None when none has finished), complete: whether `end` is the period's
     last session}. A Saturday or Sunday belongs to the week just ended.
    Raises ValueError for an unknown period or a period that has not begun.
    """
    p = (period or "").strip().lower()
    if p not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")
    if p == "week":
        first = anchor - timedelta(days=anchor.weekday())
        last = first + timedelta(days=4)
        label = f"Week of {first.strftime('%b')} {first.day}, {first.year}"
    else:
        first = anchor.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        last = nxt - timedelta(days=1)
        label = first.strftime("%B %Y")
    if first > today:
        raise ValueError(f"the {p} of {anchor.isoformat()} has not begun")
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    sessions = [d for d in days if cal.is_session(d)]
    finished = [d for d in sessions if d < today]
    end = finished[-1] if finished else None
    return {"period": p, "label": label, "first_day": first.isoformat(), "last_day": last.isoformat(),
            "sessions": [d.isoformat() for d in sessions],
            "base": cal.previous_session(sessions[0]).isoformat() if sessions else None,
            "end": end.isoformat() if end else None,
            "complete": bool(sessions) and end == sessions[-1]}


def sessions_between(after: str, through: date) -> int:
    """How many sessions fall after `after` up to and including `through`. Pure."""
    d, n = date.fromisoformat(after), 0
    while d < through:
        d = cal.next_session(d)
        if d <= through:
            n += 1
    return n


# ── the list ──────────────────────────────────────────────────────────────

def _bar_day(b: dict) -> str:
    ts = b.get("ts")
    return ts.astimezone(_NY).date().isoformat() if ts else ""


def measure(bars: list[dict], base: str, end: str) -> Optional[dict]:
    """A symbol's period from its own daily bars: the change from the base
    session's close to the end session's, the shares traded and the mean
    dollars a day over the period's sessions (base excluded, end included).
    None when either end is missing. Pure."""
    series = {_bar_day(b): b for b in bars if b.get("close")}
    was, now = series.get(base), series.get(end)
    if not was or not now:
        return None
    inside = [b for d, b in series.items() if base < d <= end]
    dollars = [b["close"] * (b.get("volume") or 0) for b in inside]
    return {"price": now["close"], "base_price": was["close"],
            "change_pct": round((now["close"] - was["close"]) / was["close"] * 100.0, 2),
            "volume": int(sum(b.get("volume") or 0 for b in inside)),
            "turnover": (sum(dollars) / len(dollars)) if dollars else 0.0,
            "sessions_traded": len(inside)}


def _payload(cat: str, win: dict, **extra) -> dict:
    complete = bool(win.get("complete"))
    out = {"category": cat, "label": mv.CATEGORIES[cat],
           "change_label": CHANGE_LABEL[(win["period"], complete)],
           "period": win["period"], "period_label": win["label"],
           "period_first_day": win["first_day"], "period_last_day": win["last_day"],
           "base_session": win.get("base"), "session": win.get("end"),
           "previous_session": win.get("base"), "complete": complete,
           "sessions": len([d for d in win["sessions"] if win.get("end") and d <= win["end"]]),
           "historical": True, "extended": False, "session_label": None, "official": True,
           "filling": False, "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tabs": []}
    out.update(extra)
    return out


def period_movers(category: str, period: str, anchor: Optional[str] = None, top: int = 20,
                  min_price: Optional[float] = None, min_turnover: Optional[float] = None,
                  min_liquidity: Optional[float] = None, min_volatility: Optional[float] = None,
                  router=None) -> dict:
    """Most active, gainers and losers over the calendar week or month that
    holds `anchor` (YYYY-MM-DD, default today in New York), in the session
    list's shape. `turnover` is the period's AVERAGE DAILY dollars traded, so
    the default $1M floor means what it means on one day; `volume` is the
    period's total shares, which ranks the Active tab."""
    from alphadesk.providers.alpaca import common_stock_symbol
    from alphadesk.providers.base import NeedsKey
    cat = (category or "").strip().lower()
    if cat not in PERIOD_CATEGORIES:
        raise KeyError(cat)
    if router is None:
        from alphadesk.providers import get_prices
        router = get_prices()
    today = datetime.now(_NY).date()
    at = date.fromisoformat(anchor) if anchor else today
    win = period_window(period, at, today)
    top = max(1, min(int(top), 50))
    mp, mt, ml, mvol, d_price, d_turn = mv._floors_asked(cat, min_price, min_turnover, min_liquidity, min_volatility)
    floors = {"min_price": mp, "min_turnover": mt, "min_liquidity": ml, "min_volatility": mvol,
              "default_min_price": d_price, "default_min_turnover": d_turn}

    if not win["end"]:
        return _payload(cat, win, not_started=True, source="unknown", floors=floors,
                        note=f"no session of {win['label']} has finished yet")
    base, end = win["base"], win["end"]
    back = sessions_between(base, today)
    if back > MAX_SESSIONS_BACK:
        return _payload(cat, win, unavailable=True, source="unknown", floors=floors,
                        note=f"{win['label']} is too far back: periods ending within about a year are offered")

    key = (f"period|{router.owner}|{','.join(getattr(router, 'connected', []) or [])}|"
           f"{cat}:{win['period']}:{win['first_day']}:{end}:{top}:{mp:g}:{mt:g}:{ml:g}:{mvol:g}")
    with mv._lock:
        hit = mv._cache.get(key)
    if hit and time.time() - hit[0] < mv.SESSION_TTL_S:
        return hit[1]
    fkey = f"{mv.FINISHED_VERSION}|{win['period']}:{win['first_day']}|{end}|{top}|{mp:g}|{mt:g}|{ml:g}|{mvol:g}"
    if win["complete"]:
        saved = mv._finished_get(router, cat, fkey)
        if saved:
            with mv._lock:
                mv._cache[key] = (time.time(), saved)
            return saved

    if not (router.owner and mv._recorded(router.owner, base) and mv._recorded(router.owner, end)):
        if not router.vendor_for("market_day", "market_day"):
            raise NeedsKey("market_day")
    try:
        last = mv._market_day(router, end)
        first = mv._market_day(router, base)
    except mv.VendorRefused as exc:
        said = mv._unavailable(cat, end, str(exc))     # the session list's words for a refusal
        return _payload(cat, win, unavailable=True, source="unknown", floors=floors,
                        note=said["note"], rate_limited=said["rate_limited"])
    if not last or not first:
        missing = end if not last else base
        return _payload(cat, win, unavailable=True, source="unknown", floors=floors,
                        note=f"the vendor returned no whole-market close for {missing}")

    # 1. The screen, from the two snapshots.
    funds = mv.fund_list(router) or frozenset()
    screen: list[dict] = []
    for sym, bar in last.items():
        if not common_stock_symbol(sym) or mv._TEST_SYMBOL.match(sym):
            continue
        if (cat == "etfs") != (sym in funds or bool(mv._FUND_NAME.search(sym))):
            continue
        was = first.get(sym) or {}
        close, wclose = bar.get("close"), was.get("close")
        if not close or not wclose or close < mp:
            continue
        ends = (close * (bar.get("volume") or 0) + wclose * (was.get("volume") or 0)) / 2.0
        if mt > 0 and ends < mt * SCREEN_TURNOVER_SHARE:
            continue
        screen.append({"symbol": sym, "change_pct": (close - wclose) / wclose * 100.0,
                       "price": close, "end_dollars": close * (bar.get("volume") or 0)})
    pool_n = max(POOL_MIN, POOL_MULTIPLE * top)
    by_change = sorted(screen, key=lambda r: r["change_pct"])
    pool = {r["symbol"]: r for r in (by_change[:pool_n] + by_change[-pool_n:]
                                     + sorted(screen, key=lambda r: -r["end_dollars"])[:pool_n])}

    # 2. Measure the pool from its own bars.
    want = back + 1 + mv.SESSION_STATS_SLACK
    syms = sorted(pool)
    try:
        bars = router.get("daily_history", syms, want) or {}
    except Exception as exc:                          # no bars is not a verdict on the list
        log.info("period movers: no per-symbol bars (%s)", exc)
        bars = {}
    bars = mv.adjust_for_spin_offs(router, bars) if bars else bars
    rows: list[dict] = []
    unverified = 0
    for sym, s in pool.items():
        m = measure(bars.get(sym) or [], base, end)
        if m:
            r = mv._row(sym, m["price"], m["change_pct"], m["volume"])
            r.update(turnover=m["turnover"], base_price=m["base_price"], checked=True)
        elif abs(s["change_pct"]) < mv._SPLIT_CHECK_PCT:
            r = mv._row(sym, s["price"], s["change_pct"], 0)
            r.update(turnover=s["end_dollars"], base_price=None, checked=False)
        else:
            unverified += 1
            continue
        rows.append(r)

    # 3. Corporate actions inside the period.
    big = [r["symbol"] for r in rows if abs(r.get("change_pct") or 0) >= mv._SPLIT_CHECK_PCT]
    if big:
        adjusted = mv._adjusted_history(router, big, want)
        events = mv._feed_events(router, big, base, end)
        for i, r in enumerate(rows):
            if r["symbol"] in big:
                r = mv._corporate_event(r, adjusted.get(r["symbol"]) or [], base, end)
                rows[i] = mv._named_event(r, events, base, end, last)

    tabs = [t for t in mv.tabs_from_list(rows) if t["id"] != "all"]
    mv.apply_floors(tabs, mp, mt)
    for t in tabs:
        t["rows"] = t["rows"][:max(top, 50) if (ml > 0 or mvol > 0) else top]
    # The statistics from the bars already read, which reach back to the base
    # however old the period; the shared helper fills any row still empty.
    for t in tabs:
        for r in t["rows"]:
            kept = [b for b in (bars.get(r["symbol"]) or []) if b.get("close") and _bar_day(b) <= end]
            if kept:
                st = mv.stats_from_bars([b["close"] for b in kept], [b.get("volume") or 0 for b in kept])
                r["volatility"], r["liquidity"] = st["volatility"], st["liquidity"]
    mv._enrich_session_stats(router, tabs, end)
    mv.apply_floors(tabs, 0.0, 0.0, ml, mvol)
    for t in tabs:
        t["rows"] = t["rows"][:top]
        for r in t["rows"]:
            r["turnover"] = round(r["turnover"] or 0)
    mv.fill_names(router, tabs)

    unchecked = sum(1 for t in tabs for r in t["rows"] if not r.get("checked"))
    events_n = sum(1 for t in tabs for r in t["rows"] if r.get("corporate_action"))
    span = f"{base} close to {end} close"
    note = (f"{win['label']}: {span}"
            + ("" if win["complete"] else f", to date (the {win['period']} is not over)") + ". "
            + "Turnover is the average dollars traded a day over the period; volume is its total. "
            + f"Volatility and liquidity are the twenty sessions ending {end}."
            + (f" {unverified} large move{'s' if unverified != 1 else ''} left out: no per-symbol bars to check "
               f"{'them' if unverified != 1 else 'it'} against." if unverified else "")
            + (f" {unchecked} row{'s' if unchecked != 1 else ''} measured from the whole-market closes only "
               f"(`checked: false`)." if unchecked else "")
            + (f" {events_n} move{'s' if events_n != 1 else ''} with a corporate action in the period, marked."
               if events_n else ""))
    result = _payload(cat, win, source=mv._day_vendor.get((router.owner, end), "unknown"),
                      note=note, floors=floors, tabs=tabs)
    if win["complete"]:
        mv._finished_put(router, cat, fkey, result)
    with mv._lock:
        if len(mv._cache) > 2048:
            mv._cache.clear()
        mv._cache[key] = (time.time(), result)
    return result
