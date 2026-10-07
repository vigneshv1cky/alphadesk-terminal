"""Records every session's close, for good (2026-10-05).

A finished session's whole-market daily bars never change, so each one is
saved the first time it can be read and served from AlphaDesk's own store
afterwards. The same goes for each session's option movers list, recorded
after the close (no vendor keeps a past day's), and each finished day of coin
bars. Past-session movers read the store first; a vendor is asked only
for a day not yet recorded. On a fresh start the last two weeks of sessions
are filled in, then each new close is added once the market has shut.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("alphadesk.closes")

CHECK_EVERY_S = 1800.0
BACKFILL_SESSIONS = 15
_started = False


def run_once() -> int:
    """Record what is missing for every active reader. Returns days saved."""
    from alphadesk import identity, prewarm
    from alphadesk.ingest import movers
    from alphadesk.providers import get_prices
    saved = 0
    for user_id, _email in prewarm._owners():
        token = identity.set_request_user(user_id)
        try:
            router = get_prices()
            saved += movers.record_closes(router, BACKFILL_SESSIONS)
            # The option list exists only as recorded, once each session closes;
            # coin days are computed from bars and kept like the stock closes.
            saved += int(movers.record_options_close(router))
            # Each board stock's option chains as they stood at the close: a
            # past day's chain cannot be asked of any vendor again.
            from alphadesk.ingest import chainsnap
            saved += chainsnap.record_chains_close(router)
            saved += movers.record_crypto_days(router, BACKFILL_SESSIONS)
            # The finished lists of the days the stepper offers, so opening
            # one asks no vendor anything.
            saved += movers.prebuild_finished_lists(router)
        except Exception as exc:
            log.warning("recording closes for a reader failed: %s", exc)
        finally:
            identity.reset_request_user(token)
    return saved


def _loop() -> None:
    time.sleep(90)                               # after the server is up and the keys are loaded
    while True:
        try:
            n = run_once()
            if n:
                log.info("closes: recorded %d session(s)", n)
        except Exception as exc:
            log.warning("closes: %s", exc)
        time.sleep(CHECK_EVERY_S)


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="closes", daemon=True).start()
