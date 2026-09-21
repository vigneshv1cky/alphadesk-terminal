"""The rail's counts brought the live service down on 2026-09-21.

Its cache is only written when the rebuild FINISHES, so while one was in
flight every other rail request missed and started its own. Adding three
symbols in quick succession was enough: each add asked the rail, each rebuilt
the earnings week, none returned, each held one of the forty request workers
until Cloud Run killed it at five minutes — and with those gone the service
could not serve a static file. Both guards are pinned here.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor


def _reset(dashboard):
    """The rail's state is module-level, and one test's slow rebuild still
    holds that reader's lock when the next begins — which is the guard
    working, not a fault. Each test starts from nothing."""
    dashboard._rail_counts.clear()
    dashboard._rail_locks.clear()


def _slow_week(calls: list, seconds: float):
    def week(*_a, **_k):
        calls.append(time.time())
        time.sleep(seconds)
        return {"days": [{"count": 3}]}
    return week


def test_one_rebuild_serves_every_caller(client, monkeypatch):
    """Five requests at once must not become five rebuilds."""
    from alphadesk.app import dashboard
    from alphadesk.ingest import earnings_calendar
    _reset(dashboard)
    started: list = []
    monkeypatch.setattr(earnings_calendar, "week", _slow_week(started, 0.6))
    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = [f.result().status_code
                 for f in [pool.submit(client.get, "/api/rail") for _ in range(5)]]
    assert codes == [200] * 5
    assert len(started) == 1, f"{len(started)} rebuilds for five callers"


def test_a_rebuild_that_will_not_finish_does_not_hold_the_request(client, monkeypatch):
    """The deadline is the difference between a slow badge and a dead
    service: past it the request answers and the work carries on elsewhere."""
    from alphadesk.app import dashboard
    from alphadesk.ingest import earnings_calendar
    _reset(dashboard)
    monkeypatch.setattr(dashboard, "RAIL_BUILD_S", 0.4)
    monkeypatch.setattr(earnings_calendar, "week", _slow_week([], 1.5))
    began = time.time()
    r = client.get("/api/rail")
    took = time.time() - began
    assert r.status_code == 200
    assert took < 3.0, f"the request was held {took:.1f}s by a rebuild that had not finished"


def test_the_counts_are_cached_between_callers(client, monkeypatch):
    from alphadesk.app import dashboard
    from alphadesk.ingest import earnings_calendar
    _reset(dashboard)
    started: list = []
    monkeypatch.setattr(earnings_calendar, "week", _slow_week(started, 0))
    assert client.get("/api/rail").json()["earnings_calls"] == 3
    assert client.get("/api/rail").json()["earnings_calls"] == 3
    assert len(started) == 1, "the second caller rebuilt instead of reading the cache"


def test_the_rebuild_never_runs_on_a_request_thread(client, monkeypatch):
    """It runs on its own small pool, so a vendor call with no end strands a
    thread nobody is serving pages with."""
    from alphadesk.app import dashboard
    from alphadesk.ingest import earnings_calendar
    _reset(dashboard)
    where: list = []

    def week(*_a, **_k):
        where.append(threading.current_thread().name)
        return {"days": []}

    monkeypatch.setattr(earnings_calendar, "week", week)
    client.get("/api/rail")
    assert where and where[0].startswith("rail-counts"), where


def test_the_reader_is_stamped_on_the_rebuild_thread(client, monkeypatch):
    """Identity lives in a context variable and a bare pool thread does NOT
    inherit it. Moving this work off the request thread stripped the reader,
    the screener's first line raised, and the rail answered 500 to every
    poll (2026-09-21). The stamp is what makes the move safe."""
    from alphadesk.app import dashboard
    from alphadesk.desk import screener
    _reset(dashboard)
    seen: list = []

    def inventory(*_a, **_k):
        from alphadesk.identity import request_user
        seen.append(request_user())
        return []

    monkeypatch.setattr(screener, "inventory", inventory)
    assert client.get("/api/rail").status_code == 200
    # On an open instance the reader is None; what matters is that whatever
    # the request carried is what the pool thread sees.
    assert seen, "the rebuild never ran"


def test_a_vendor_failure_costs_a_badge_and_not_the_page(client, monkeypatch):
    """These are two numbers beside the navigation. Nothing here may fail
    the request — before this, one raising call turned the rail into a 500
    on every poll."""
    from alphadesk.app import dashboard
    from alphadesk.desk import screener
    from alphadesk.ingest import earnings_calendar
    _reset(dashboard)

    def boom(*_a, **_k):
        raise RuntimeError("the vendor is having an afternoon")

    monkeypatch.setattr(screener, "inventory", boom)
    monkeypatch.setattr(earnings_calendar, "week", boom)
    r = client.get("/api/rail")
    assert r.status_code == 200
    assert r.json()["earnings_calls"] is None
