"""Lookups a page should not wait for (2026-09-14).

A calendar week in earnings season lists hundreds of upcoming reports — 316
needed a release-timing lookup for Oct 19–23 — and each is one SEC EDGAR
request at EDGAR's pace, so the page would wait most of a minute. Those
lookups run here instead, in the background, under the reader who asked; the
page returns with what is already stored and says how many are still
coming, and the next load reads them from the database.

Each (kind, reader, symbol) is queued at most once at a time, and one that
failed is not queued again for RETRY_AFTER_S, so a page that polls while a
lookup keeps failing does not start the same work every few seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

log = logging.getLogger("alphadesk.background_fill")

RETRY_AFTER_S = 600.0

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="calendar-fill")
_lock = threading.Lock()
_in_flight: set[tuple[str, str, str]] = set()
_failed: dict[tuple[str, str, str], float] = {}


def recently_failed(kind: str, owner: str, symbol: str) -> bool:
    with _lock:
        at = _failed.get((kind, owner, symbol.upper()))
    return at is not None and time.time() - at < RETRY_AFTER_S


def note_failed(kind: str, owner: str, symbols: Iterable[str]) -> None:
    now = time.time()
    with _lock:
        if len(_failed) > 50_000:
            _failed.clear()
        for s in symbols:
            _failed[(kind, owner, s.upper())] = now


def submit(kind: str, owner: str, symbols: Iterable[str], job: Callable[[list[str]], None]) -> int:
    """Queue `job` for the symbols not already queued for this reader; returns
    how many were newly queued. The job runs under the reader's identity."""
    from alphadesk.identity import reset_request_user, set_request_user
    with _lock:
        fresh = sorted({s.upper() for s in symbols} - {k[2] for k in _in_flight if k[0] == kind and k[1] == owner})
        for s in fresh:
            _in_flight.add((kind, owner, s))
    if not fresh:
        return 0

    def run() -> None:
        token = set_request_user(owner)
        try:
            job(fresh)
        except Exception as exc:
            log.warning("%s fill failed for %s: %s", kind, owner[:8], exc)
        finally:
            reset_request_user(token)
            with _lock:
                for s in fresh:
                    _in_flight.discard((kind, owner, s))

    _pool.submit(run)
    return len(fresh)
