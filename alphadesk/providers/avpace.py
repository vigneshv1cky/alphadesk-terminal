"""One request a second per Alpha Vantage key (2026-10-07).

The free plan refuses a request that comes within a second of the last one on
the same key ("please consider spreading out your free API requests more
sparingly (1 request per second)"), and the price data and the news feed
asked independently, often several at once, so key statistics came back
refused. Each request now reserves the key's next free slot and waits for it.
A request that would wait longer than MAX_WAIT_S is refused at once instead,
so the router moves on to the reader's next vendor rather than holding a page.
"""
from __future__ import annotations

import threading
import time

from alphadesk.providers.base import ProviderError

#: Slightly over a second: the vendor counts on its own clock.
MIN_INTERVAL_S = 1.1
MAX_WAIT_S = 4.0

_lock = threading.Lock()
_next_slot: dict[str, float] = {}


def wait_turn(api_key: str) -> None:
    """Block until this key may send its next request; ProviderError when the
    wait would pass MAX_WAIT_S (the slot is not taken)."""
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_slot.get(api_key, 0.0))
        if slot - now > MAX_WAIT_S:
            raise ProviderError("Alpha Vantage: busy — its free plan answers one request a second on this key")
        _next_slot[api_key] = slot + MIN_INTERVAL_S
    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)
