"""A few seconds of memory for composite reads (2026-10-03).

The screener's inventory and the market-today digest are rebuilt from the whole
news window, the earnings calendar and several vendors on EVERY call — about
800 ms by the code's own measurement — and the page, the agent and the prewarm
replay all ask within the same minute. This remembers a finished answer per key
for a short while, with askers who arrive during a rebuild sharing it instead of
starting their own. A failed rebuild is never remembered.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_MAX = 256
_cache: dict[tuple, tuple[float, object]] = {}
_guard = threading.Lock()
_locks: dict[tuple, threading.Lock] = {}


def cached(key: tuple, ttl_s: float, build: Callable[[], T]) -> T:
    now = time.monotonic()
    with _guard:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl_s:
            return hit[1]                                    # type: ignore[return-value]
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        with _guard:
            hit = _cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl_s:
                return hit[1]                                # type: ignore[return-value]
        value = build()
        with _guard:
            if len(_cache) >= _MAX:
                stale = time.monotonic() - ttl_s
                for k in [k for k, (at, _) in _cache.items() if at < stale]:
                    _cache.pop(k, None)
                if len(_cache) >= _MAX:
                    _cache.clear()
            _cache[key] = (time.monotonic(), value)
        return value


def clear() -> None:
    with _guard:
        _cache.clear()
