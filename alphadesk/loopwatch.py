"""The event-loop stall watchdog (2026-11-10).

EVERY REQUEST PASSES THROUGH ONE EVENT LOOP before it reaches a worker
thread, so a single blocking call made on that loop stalls every request at
once while background threads carry on. That is what the live site did on
2026-11-10: every request arriving between 08:44:13 and 08:44:15 UTC — the
sign-in check and the saved layouts among them — finished together at
08:45:18, 64 seconds later, while prewarm kept logging. The middleware was
writing to the store on the loop, and a background writer held the store's
lock (reproduced locally: a 3-second hold stalled an unrelated health check
by 2.4 seconds).

This thread asks the loop to run a no-op every CHECK_S seconds. When one has
not run for STALL_S, it logs the loop thread's own stack ONCE — the line the
loop is stuck on — and logs again when the loop is free, with how long it was
held. It never touches the loop beyond that one callback, so it cannot cause
what it watches for. ALPHADESK_LOOP_WATCHDOG=off turns it off.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback

log = logging.getLogger("alphadesk.loopwatch")

#: How long the loop may go without running a callback before it is reported.
STALL_S = 2.0
#: How often the loop is asked to run one.
CHECK_S = 0.5


def enabled() -> bool:
    return os.environ.get("ALPHADESK_LOOP_WATCHDOG", "on").strip().lower() not in ("off", "0", "false", "no")


def start(loop, stall_s: float = STALL_S, check_s: float = CHECK_S) -> threading.Event | None:
    """Watch `loop`; call this ON the loop's own thread. Returns the event that
    stops the watch, or None when the watchdog is switched off."""
    if not enabled():
        return None
    loop_thread = threading.get_ident()
    stop = threading.Event()
    last = {"ran": time.monotonic()}

    def ran() -> None:
        last["ran"] = time.monotonic()

    def watch() -> None:
        held_since = None
        while not stop.wait(check_s):
            try:
                loop.call_soon_threadsafe(ran)
            except RuntimeError:                        # the loop has closed
                return
            lag = time.monotonic() - last["ran"]
            if lag > stall_s + check_s and held_since is None:
                held_since = last["ran"]
                frame = sys._current_frames().get(loop_thread)
                where = "".join(traceback.format_stack(frame)[-12:]) if frame else "(no frame)"
                log.warning("event loop blocked for %.1fs and counting; every request is waiting. "
                            "The loop is in:\n%s", lag, where)
            elif held_since is not None and lag <= check_s * 2:
                log.warning("event loop free again after %.1fs", last["ran"] - held_since)
                held_since = None

    threading.Thread(target=watch, name="loopwatch", daemon=True).start()
    return stop
