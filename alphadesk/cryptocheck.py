"""Does every crypto pair the Alpaca account trades show up properly? (2026-10-05)

For each pair: can a reader find it by typing its coin's ticker, does it have
price bars to chart, and is it on the crypto movers list. Read-only. The
answers come from the app's own search, chart and movers code, so it finds
what a reader would find, not what a table says should be there.
"""

from __future__ import annotations


def report(pairs: list[str], search, bars: dict, movers: set[str]) -> dict:
    """`search(text)` -> symbols a search for that text offers; `bars` maps a
    symbol to its daily bars; `movers` is the symbols on the movers list.
    Pure given those."""
    rows = []
    for pair in sorted(pairs):
        sym = pair.replace("/", "-")
        base = sym.split("-")[0]
        found = sym in search(base)
        n = len(bars.get(sym) or [])
        rows.append({"pair": pair, "symbol": sym, "searchable": found, "bars": n, "has_bars": n > 0,
                     "in_movers": sym in movers})
    return {
        "pairs": len(rows),
        "problems": {
            "not_searchable": [r["symbol"] for r in rows if not r["searchable"]],
            "no_bars": [r["symbol"] for r in rows if not r["has_bars"]],
            "not_in_movers": [r["symbol"] for r in rows if not r["in_movers"]],
        },
        "rows": rows,
    }
