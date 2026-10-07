"""Slow-changing lists kept in the store (2026-10-07).

A vendor's asset list, a fund list, the S&P 500's members and sector weights
change slowly but lived only in the memory of the process that fetched them,
so every restart asked again — Alpaca's ~14,000-row asset list among them.
`kept` reads the store's copy while it is fresh, fetches (and keeps) when it
is not, and falls back to the copy however old when the fetch FAILS. An empty
answer is not a failure — the vendor may simply not carry that list — so it is
returned as it is and not kept. The
caller still keeps its own memory copy; this only spares the vendor after a
restart and answers when the vendor is down.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger("alphadesk.keptlists")


def kept(owner: Optional[str], vendor: str, name: str, fresh_s: float, fetch: Callable[[], Any]) -> Any:
    """The list from the store while younger than `fresh_s`, else `fetch()`
    (kept when it answers), else, when `fetch` raises, the stored copy however
    old. `fetch`'s answer
    must be JSON (lists, dicts, strings, numbers); without an owner nothing is
    kept and `fetch()` is simply called."""
    if not owner:
        return fetch()
    from alphadesk.ledger import store
    method = f"list:{name}"
    stored = None
    try:
        stored = store.vendor_cache_get(owner, vendor, method, "")
    except Exception as exc:
        log.debug("kept list %s unreadable: %s", name, exc)
    age = None
    if stored:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(stored[1])).total_seconds()
        except ValueError:
            age = None
        if age is not None and age < fresh_s:
            try:
                return json.loads(stored[0])
            except ValueError:
                pass
    try:
        got = fetch()
    except Exception:
        if not stored:
            raise
        log.info("list %s from the kept copy (%.0f h old): the vendor failed", name, (age or 0) / 3600)
        return json.loads(stored[0])
    if got is None or got == {} or got == []:
        return got
    try:
        store.vendor_cache_put(owner, vendor, method, "", json.dumps(got, separators=(",", ":")))
    except Exception as exc:
        log.debug("list %s not kept: %s", name, exc)
    return got

