"""Options flow: the day's big orders on the board's underlyings (2026-09-14).

The reader's own options feed (Alpaca, OPRA on a paid plan) supplies the most
active contracts, their trades, their quotes NOW, and the stock's minute
prices. It keeps no quote history for options, so whether an order hit the
ask or the bid is only knowable when it is seen within seconds of its quote.
The page polls; each poll reads the trades since the last one and the quotes
at that moment, and an order no older than LIVE_WINDOW_S is classified
against them and remembered. Orders from before the page first asked keep an
unknown side — shown as such, never guessed (the owner chose this over a paid
flow vendor, 2026-09-14).

AN ORDER, NOT A PRINT. Trades on one contract in the same millisecond are
one order split across exchanges — 396 such groups on two NVDA contracts in
one session — and are merged: total size, average price, the exchanges it
touched. Two or more exchanges, or an intermarket-sweep condition, is a
SWEEP. The OPRA condition code names the rest (multi-leg, auction, cross,
floor, tied to a stock trade, extended hours); cancelled prints are dropped.

State is per reader and per underlying, in memory, and resets each session:
a reader's orders and the sides seen on their key are theirs.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

ACTIVE_CONTRACTS = 40
ACTIVE_REFRESH_S = 300.0
LIVE_WINDOW_S = 30.0
KEEP_MIN_PREMIUM = 5_000.0        # smaller orders are not kept as rows
KEEP_ORDERS = 600
MAX_STATES = 200
MAX_SYMBOLS = 8
ROWS_PER_SYMBOL = 150

_OCC = re.compile(r"^([A-Z.]+?)(\d{6})([CP])(\d{8})$")
log = logging.getLogger("alphadesk.options_flow")
_lock = threading.Lock()
_states: dict[tuple[str, str], dict] = {}
#: Symbols whose first capture is running on a background thread (warm()).
_warming: set[str] = set()

# OPRA trade conditions (Alpaca /v1beta1/options/meta/conditions/trade).
CANCELLED = set("ACEG")
LATE = set("BDFH")
SWEEP = {"S", "b", "d"}                              # ISO executions
MULTI_LEG = set("fghijlmt")
AUCTION = set("abgklr")
CROSS = set("cdho")
FLOOR = set("eimpst")
STOCK_TIED = set("nopqrs")
EXTENDED = {"v"}
CODE_LABEL = {"I": "auto", "S": "ISO", "a": "auction", "b": "auction ISO", "c": "cross", "d": "cross ISO",
              "e": "floor", "f": "multi-leg", "g": "multi-leg auction", "h": "multi-leg cross", "i": "multi-leg floor",
              "j": "multi-leg vs single", "k": "stock-option auction", "l": "multi-leg auction vs single",
              "m": "multi-leg floor vs single", "n": "stock-option", "o": "stock-option cross", "p": "stock-option floor",
              "q": "stock-option vs single", "r": "stock-option auction vs single", "s": "stock-option floor vs single",
              "t": "multi-leg floor", "u": "compression", "v": "extended hours",
              "B": "late", "D": "late", "F": "late opening", "H": "late opening"}


def parse_occ(occ: str) -> dict | None:
    """NVDA260918P00205000 → underlying, expiry, call/put, strike. Pure."""
    m = _OCC.match(occ or "")
    if not m:
        return None
    yy, mm, dd = m.group(2)[:2], m.group(2)[2:4], m.group(2)[4:]
    return {"underlying": m.group(1), "expiry": f"20{yy}-{mm}-{dd}",
            "type": "call" if m.group(3) == "C" else "put", "strike": int(m.group(4)) / 1000}


def classify(price: float, bid: float | None, ask: float | None) -> tuple[str | None, float | None]:
    """("ask" | "bid" | "mid", where the fill sits in the spread 0..1). Pure."""
    if bid is None or ask is None or ask <= 0 or ask < bid:
        return None, None
    spread = ask - bid
    fill = 0.5 if spread <= 0 else max(0.0, min(1.0, (price - bid) / spread))
    if price >= ask:
        return "ask", fill
    if price <= bid:
        return "bid", fill
    return "mid", fill


def flags_for(conditions: set[str], exchanges: int, size: int | None, open_interest: int | None) -> list[str]:
    """The order's labels, most telling first. Pure."""
    out = []
    if exchanges >= 2 or conditions & SWEEP:
        out.append("sweep")
    if conditions & MULTI_LEG:
        out.append("multi-leg")
    if conditions & STOCK_TIED:
        out.append("stock-tied")
    if conditions & (AUCTION - MULTI_LEG - STOCK_TIED):
        out.append("auction")
    if conditions & (CROSS - MULTI_LEG - STOCK_TIED):
        out.append("cross")
    if conditions & (FLOOR - MULTI_LEG - STOCK_TIED):
        out.append("floor")
    if conditions & EXTENDED:
        out.append("extended")
    if conditions & LATE:
        out.append("late")
    # This order alone is larger than last night's open interest: at least
    # part of it opened new positions. (Day volume above open interest was
    # measured first and fired on 170 of 191 orders — short-dated contracts
    # routinely trade more than they carry, so it said nothing.)
    if size and open_interest is not None and size > open_interest:
        out.append("size>OI")
    return out


def group_orders(trades: list[dict]) -> list[dict]:
    """Prints → orders: one per contract per millisecond, cancelled prints
    dropped. Pure."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for tr in trades:
        if (tr.get("condition") or "") in CANCELLED or tr.get("price") is None or not tr.get("size"):
            continue
        groups.setdefault((tr["symbol"], (tr.get("t") or "")[:23]), []).append(tr)
    orders = []
    for (occ, ms), rows in groups.items():
        size = sum(r["size"] for r in rows)
        notional = sum(r["price"] * r["size"] for r in rows)
        orders.append({"symbol": occ, "t": rows[0]["t"], "ms": ms, "size": size, "price": round(notional / size, 4),
                       "premium": round(notional * 100, 2),
                       "exchanges": sorted({r.get("exchange") or "" for r in rows} - {""}),
                       "conditions": sorted({r.get("condition") or "" for r in rows} - {""}), "prints": len(rows)})
    return orders


def _session_start(now: datetime) -> datetime:
    """09:30 New York on the latest weekday at or before now."""
    from zoneinfo import ZoneInfo
    ny = now.astimezone(ZoneInfo("America/New_York"))
    d = ny.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    start = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    if ny < start:
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        start = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    return start.astimezone(timezone.utc)


def _trade_time(t: str | None) -> datetime | None:
    if not t:
        return None
    try:
        # Nanosecond timestamps: keep microseconds.
        base, _, frac = t.rstrip("Z").partition(".")
        return datetime.fromisoformat(f"{base}.{(frac + '000000')[:6]}" if frac else base).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _state(owner: str, sym: str, now: datetime) -> dict:
    key = (owner, sym)
    with _lock:
        state = _states.get(key)
        # A new session starts a new capture: yesterday's orders are not today's flow.
        if state is not None and _session_start(now) > state["session"]:
            state = None
        if state is None:
            if len(_states) >= MAX_STATES:
                _states.pop(min(_states, key=lambda k: _states[k]["touched"]))
            start = _session_start(now)
            state = _states[key] = {"since": start, "session": start, "live_since": now, "orders": {}, "recent": {},
                                    "share": {}, "minutes": {}, "active": None, "active_at": 0.0, "touched": time.time()}
        state["touched"] = time.time()
    return state


def capture(vendor, owner: str, symbol: str, now: datetime | None = None) -> dict:
    """Advance one underlying's capture by a poll; returns its state."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    sym = symbol.upper()
    state = _state(owner, sym, now)
    if state["active"] is None or time.time() - state["active_at"] > ACTIVE_REFRESH_S:
        state["active"] = vendor.option_active_contracts(sym, top=ACTIVE_CONTRACTS) or {"contracts": []}
        state["active_at"] = time.time()
    occs = sorted(c["symbol"] for c in state["active"].get("contracts") or [])
    if not occs:
        return state

    since = state["since"]
    trades = vendor.option_trades(occs, since.isoformat().replace("+00:00", "Z")) or []
    quotes = vendor.option_latest_quotes(occs) or {}
    # The stock's minute prices since the last minute read (re-reading that
    # minute, whose bar may have grown).
    try:
        last = max(state["minutes"]) if state["minutes"] else None
        start = datetime.fromisoformat(last + ":00+00:00") if last else state["session"]
        state["minutes"].update(vendor.stock_minute_closes(sym, start) or {})
    except Exception:
        pass
    # Days to expiry from New York's date: after 20:00 ET the UTC date is
    # already tomorrow, which showed Friday's contracts as 3d on a Monday.
    ny_today = now.astimezone(ZoneInfo("America/New_York")).date()

    # Prints re-read from the last second are skipped by their identity.
    recent = state["recent"]
    fresh = []
    newest = since
    for tr in trades:
        at = _trade_time(tr.get("t"))
        if at is None:
            continue
        newest = max(newest, at)
        tid = (tr["symbol"], tr.get("t"), tr.get("price"), tr.get("size"), tr.get("exchange"), tr.get("condition"))
        if tid in recent:
            continue
        recent[tid] = at
        fresh.append(tr)
    for tid in [k for k, at in recent.items() if at < newest - timedelta(seconds=5)]:
        del recent[tid]

    for order in group_orders(fresh):
        at = _trade_time(order["t"])
        if at is None:
            continue
        q = quotes.get(order["symbol"]) or {}
        live = (now - at).total_seconds() <= LIVE_WINDOW_S and at >= state["live_since"] - timedelta(seconds=LIVE_WINDOW_S)
        side, fill = classify(order["price"], q.get("bid"), q.get("ask")) if live else (None, None)
        if side:
            # Every order seen live counts toward the contract's ask/bid
            # share, whatever its size.
            share = state["share"].setdefault(order["symbol"], {"ask": 0, "bid": 0, "mid": 0})
            share[side] += order["size"]
        key = (order["symbol"], order["ms"])
        existing = state["orders"].get(key)
        if existing is not None:
            # The rest of an order whose first prints came in the last poll.
            size = existing["size"] + order["size"]
            notional = existing["price"] * existing["size"] + order["price"] * order["size"]
            existing.update(size=size, price=round(notional / size, 4), premium=round(notional * 100, 2),
                            prints=existing["prints"] + order["prints"],
                            exchanges=sorted(set(existing["exchanges"]) | set(order["exchanges"])),
                            conditions=sorted(set(existing["conditions"]) | set(order["conditions"])))
            continue
        if order["premium"] < KEEP_MIN_PREMIUM:
            continue
        meta = parse_occ(order["symbol"]) or {}
        state["orders"][key] = {
            "t": at.isoformat().replace("+00:00", "Z"), "contract": order["symbol"], **meta,
            "dte": (date.fromisoformat(meta["expiry"]) - ny_today).days if meta.get("expiry") else None,
            "price": order["price"], "size": order["size"], "premium": order["premium"],
            "exchanges": order["exchanges"], "conditions": order["conditions"], "prints": order["prints"],
            "side": side, "fill": round(fill, 3) if fill is not None else None,
            "bid": q.get("bid") if live else None, "ask": q.get("ask") if live else None,
        }
    # Re-read the last second next time: prints can land with the same stamp.
    state["since"] = newest - timedelta(seconds=1) if newest > since else since
    if len(state["orders"]) > KEEP_ORDERS:
        for key in sorted(state["orders"], key=lambda k: state["orders"][k]["t"])[:len(state["orders"]) - KEEP_ORDERS]:
            del state["orders"][key]
    return state


def _rows(sym: str, state: dict, min_premium: float) -> list[dict]:
    by_occ = {c["symbol"]: c for c in (state["active"] or {}).get("contracts") or []}
    minutes = state["minutes"]
    ordered_minutes = sorted(minutes)
    rows = []
    for o in state["orders"].values():
        if o["premium"] < min_premium:
            continue
        c = by_occ.get(o["contract"]) or {}
        share = state["share"].get(o["contract"])
        total = sum(share.values()) if share else 0
        # The stock's price at the order's minute, or the last minute before it.
        minute = o["t"][:16]
        stock = minutes.get(minute)
        if stock is None and ordered_minutes:
            earlier = [m for m in ordered_minutes if m <= minute]
            stock = minutes[earlier[-1]] if earlier else None
        rows.append({**o, "ticker": sym, "stock": stock, "volume": c.get("volume"), "open_interest": c.get("open_interest"),
                     "flags": flags_for(set(o["conditions"]), len(o["exchanges"]), o["size"], c.get("open_interest")),
                     "code": ", ".join(CODE_LABEL.get(x, x) for x in o["conditions"]),
                     "ask_share": round(share["ask"] / total, 3) if total else None,
                     "bid_share": round(share["bid"] / total, 3) if total else None,
                     "share_contracts": total})
    return rows


def started(owner: str, symbol: str, now: datetime | None = None) -> bool:
    """Whether this owner's capture of `symbol` is already running for this
    session — a second call is incremental and fast."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        state = _states.get((owner, symbol.upper()))
        return state is not None and _session_start(now) <= state["session"]


def warm(vendor, owner: str, symbols: list[str] | str) -> list[str]:
    """Start a capture for symbols that have none, on a background thread,
    and answer which ones are warming.

    THE FIRST call for a symbol reads every print since the opening bell
    across the active contracts — 6s on a quiet name mid-session, ~28s on a
    busy one — and every call after it is incremental (0.3s). A caller that
    cannot wait (the MCP tool: an agent's call should not hang for half a
    minute) starts the capture here and asks again once it is up."""
    import contextvars
    import threading
    syms = [s.upper() for s in ([symbols] if isinstance(symbols, str) else symbols) if s][:MAX_SYMBOLS]
    cold = [s for s in syms if not started(owner, s)]
    for sym in cold:
        with _lock:
            if sym in _warming:
                continue
            _warming.add(sym)

        def run(sym: str = sym) -> None:
            try:
                capture(vendor, owner, sym)
            except Exception as exc:                  # the next call reports it
                log.info("options flow warm-up for %s: %s", sym, exc)
            finally:
                with _lock:
                    _warming.discard(sym)
        # A copy of this request's context: the vendor is the reader's, and a
        # bare thread would run as nobody.
        threading.Thread(target=contextvars.copy_context().run, args=(run,),
                         name=f"flow-warm-{sym}", daemon=True).start()
    return cold


def flow(vendor, owner: str, symbols: list[str] | str, min_premium: float = 25_000.0, now: datetime | None = None) -> dict:
    """{symbols, trades, live_since, contracts, feed, session, min_premium,
    errors}: the kept orders at or above `min_premium` across `symbols`,
    newest first. Each call advances every symbol's capture, in parallel."""
    from concurrent.futures import ThreadPoolExecutor
    syms = list(dict.fromkeys(s.upper() for s in ([symbols] if isinstance(symbols, str) else symbols) if s))[:MAX_SYMBOLS]
    now = now or datetime.now(timezone.utc)
    states: dict[str, dict] = {}
    errors: dict[str, str] = {}

    def one(sym: str):
        try:
            return sym, capture(vendor, owner, sym, now), None
        except Exception as exc:
            return sym, None, str(exc)[:200]

    with ThreadPoolExecutor(max_workers=min(4, len(syms) or 1)) as pool:
        for sym, state, err in pool.map(one, syms):
            if state is not None:
                states[sym] = state
            else:
                errors[sym] = err or "failed"
    # The newest ROWS_PER_SYMBOL of each stock: one cap across all of them let
    # the busiest stock push a quieter one off the list.
    rows = [r for sym, st in states.items()
            for r in sorted(_rows(sym, st, min_premium), key=lambda r: r["t"], reverse=True)[:ROWS_PER_SYMBOL]]
    rows.sort(key=lambda r: r["t"], reverse=True)
    live = [st["live_since"] for st in states.values()]
    actives = [st["active"] or {} for st in states.values()]
    return {"symbols": syms, "trades": rows,
            "live_since": min(live).isoformat().replace("+00:00", "Z") if live else None,
            "contracts": sum(len(a.get("contracts") or []) for a in actives),
            "feed": next((a.get("feed") for a in actives if a.get("feed")), None),
            "session": next((a.get("session") for a in actives if a.get("session")), None),
            "min_premium": min_premium, "errors": errors}
