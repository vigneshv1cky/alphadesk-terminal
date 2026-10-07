"""End-of-day option chains, kept (2026-10-07, the owner's call).

An option chain is a live answer and is never kept as the current one — a
stale quote is worse than none. But a past day's chain can never be asked of
any vendor afterwards, so each trading day, once the session has closed, the
chains of the stock symbols on the reader's board are saved as they stood: the
nearest few expiries, every contract's bid, ask, last, volume, open interest
and implied volatility, compressed, one row per symbol per day, kept for good.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("alphadesk.chainsnap")

#: After the 4pm close, so the closing quotes and the day's volume are in.
RECORD_AFTER = (16, 15)
MAX_SYMBOLS = 20
MAX_EXPIRIES = 6
WITHIN_DAYS = 60


def board_stocks(owner: str) -> list[str]:
    """The reader's board, stocks only (a coin has no option chain)."""
    from alphadesk.ledger import store
    symbols = (store.get_board(owner) or {}).get("symbols") or []
    return [s.upper() for s in symbols if s and "-" not in s][:MAX_SYMBOLS]


def nearest_expiries(expiries: list[str], today: date) -> list[str]:
    """The nearest MAX_EXPIRIES expiries from today within WITHIN_DAYS. Pure."""
    last = (today + timedelta(days=WITHIN_DAYS)).isoformat()
    return sorted(e for e in expiries or [] if today.isoformat() <= e <= last)[:MAX_EXPIRIES]


def record_chains_close(router, now: Optional[datetime] = None) -> int:
    """Save today's chains for the board's stocks once the session has closed;
    returns how many symbols were saved. Only between 4:15pm and midnight New
    York on a trading day, once per symbol and day."""
    from alphadesk.desk.sessions import is_session
    from alphadesk.ledger import store
    if not router.owner:
        return 0
    ny = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    day = ny.date()
    if not is_session(day) or (ny.hour, ny.minute) < RECORD_AFTER:
        return 0
    try:
        vendor = router.vendor_for("options", "option_chain")
    except Exception:
        return 0
    have = set(store.recorded_option_chain_symbols(router.owner, day.isoformat()))
    saved = 0
    for sym in board_stocks(router.owner):
        if sym in have:
            continue
        try:
            expiries = nearest_expiries(vendor.option_expirations(sym) or [], day)
        except Exception as exc:
            log.info("option expiries for %s not read: %s", sym, exc)
            continue
        chains = {}
        for exp in expiries:
            try:
                got = vendor.option_chain(sym, exp)
            except Exception as exc:
                log.info("option chain %s %s not read: %s", sym, exp, exc)
                continue
            if got and (got.get("calls") or got.get("puts")):
                chains[exp] = got
        if not chains:
            continue
        # The stock's price at the save, so a past day's chain can be cut
        # around the money the way a live one is.
        try:
            spot = (router.quote(sym) or {}).get("price")
        except Exception:
            spot = None
        try:
            store.save_option_chain_day(router.owner, sym, day.isoformat(), getattr(vendor, "name", "unknown"),
                                        {"symbol": sym, "day": day.isoformat(), "spot": spot, "chains": chains,
                                         "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            saved += 1
        except Exception as exc:
            log.warning("option chains for %s not saved: %s", sym, exc)
    return saved
