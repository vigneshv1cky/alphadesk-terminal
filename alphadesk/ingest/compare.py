"""Comparison analysis — one company's record beside its peers', from the
user's own vendors (2026-09-13): each symbol's metrics from whichever
connected vendor carries comparison metrics, and the peer list from one
that carries peers. A symbol no vendor answers is listed as missing; no
peer is ever guessed from a sector label.
"""

from __future__ import annotations

import logging

from alphadesk.providers.base import NeedsKey

log = logging.getLogger("alphadesk.compare")

MAX_SYMBOLS = 12


def compare(symbols: list[str]) -> dict:
    """{rows, missing, vendor}, in the order asked, at most MAX_SYMBOLS.
    Raises NeedsKey when no connected vendor carries comparison metrics."""
    from alphadesk.providers import get_prices
    router = get_prices()
    seen: list[str] = []
    for s in symbols:
        u = (s or "").strip().upper()
        if u and u not in seen:
            seen.append(u)
    seen = seen[:MAX_SYMBOLS]
    rows: list[dict] = []
    missing: list[str] = []
    vendor = None
    for i, s in enumerate(seen):
        try:
            m = router.ask("compare_metrics", s)
            vendor = vendor or router.answered_by
        except NeedsKey:
            if i == 0 and not router.vendors:
                raise
            m = None
        (rows if m else missing).append(m if m else s)
    if not rows and seen:
        router.ask("compare_metrics", seen[0])      # raises the prompt when no vendor carries it
    return {"rows": rows, "missing": missing, "vendor": vendor}


def peers(symbol: str, limit: int = 10) -> dict:
    from alphadesk.providers import get_prices
    router = get_prices()
    sym = symbol.upper()
    got = router.ask("peers", sym) or []
    return {"symbol": sym, "peers": [p for p in got if p != sym][:limit], "source": router.answered_by}
