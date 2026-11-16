"""2026-11-10: nothing that can wait runs on the event loop.

Every request passes through the one event loop before it reaches a worker,
so a store write made there stalls every request at once. Live, every request
arriving between 08:44:13 and 08:44:15 UTC finished together 64 seconds later
while background threads kept logging. Reproduced here before the fix: a
background writer holding the store's lock for 3 seconds held a page request
2.91 seconds and an unrelated health check 2.41 seconds; after it, 0.01 and
0.00."""
import asyncio
import logging
import threading
import time


def test_a_held_store_lock_does_not_stall_requests(store):
    from fastapi.testclient import TestClient

    from alphadesk.app import dashboard
    from alphadesk.ledger import db
    timings = {}
    with TestClient(dashboard.app) as client:
        client.get("/healthz")                 # a running server has found its account already
        dashboard._seen_stamped.clear()        # so the next request writes its "last seen" stamp

        def hold():
            with db.lock:                      # a background writer holding the store's write lock
                time.sleep(2.0)

        def page():
            t0 = time.perf_counter()
            client.get("/api/themes")
            timings["page"] = time.perf_counter() - t0

        def health():
            time.sleep(0.3)
            t0 = time.perf_counter()
            client.get("/healthz")
            timings["health"] = time.perf_counter() - t0

        holder = threading.Thread(target=hold)
        holder.start()
        time.sleep(0.1)
        workers = [threading.Thread(target=page), threading.Thread(target=health)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        holder.join()
    assert timings["page"] < 1.0 and timings["health"] < 1.0, timings


def _watch_a_blocked_loop(caplog, monkeypatch, env=None):
    from alphadesk import loopwatch
    if env:
        monkeypatch.setenv("ALPHADESK_LOOP_WATCHDOG", env)
    caplog.set_level(logging.WARNING, logger="alphadesk.loopwatch")
    loop = asyncio.new_event_loop()
    started = {}

    def _blocking_here():
        time.sleep(0.9)

    async def main():
        started["stop"] = loopwatch.start(asyncio.get_running_loop(), stall_s=0.2, check_s=0.05)
        await asyncio.sleep(0.1)
        _blocking_here()                       # the loop is held right here
        await asyncio.sleep(0.4)

    loop.run_until_complete(main())
    if started["stop"] is not None:
        started["stop"].set()
    loop.close()
    return started["stop"], [r.getMessage() for r in caplog.records]


def test_the_watchdog_names_the_line_a_blocked_loop_is_on(caplog, monkeypatch):
    stop, messages = _watch_a_blocked_loop(caplog, monkeypatch)
    blocked = [m for m in messages if m.startswith("event loop blocked")]
    assert len(blocked) == 1 and "_blocking_here" in blocked[0] and "time.sleep(0.9)" in blocked[0]
    assert any(m.startswith("event loop free again after") for m in messages)


def test_the_watchdog_can_be_switched_off(caplog, monkeypatch):
    stop, messages = _watch_a_blocked_loop(caplog, monkeypatch, env="off")
    assert stop is None and messages == []
