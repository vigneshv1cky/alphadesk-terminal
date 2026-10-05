"""Keeping an owner's panels warm (alphadesk/prewarm.py)."""

import time

from alphadesk import prewarm


def test_only_market_data_reads_are_kept():
    assert prewarm.worth_keeping("/api/movers/stocks?top=50")
    assert prewarm.worth_keeping("/api/insider/AAPL")
    for p in ("/api/stream?trades=AAPL", "/api/auth/me", "/api/agent/tools/mcp",
              "/api/keys", "/api/account/delete", "/api/board", "/api/news?q=tariffs",
              "/api/news?before=2026-09-18", "/api/news/related?q=chips", "/healthz"):
        assert not prewarm.worth_keeping(p), p


def test_fast_changing_data_refreshes_every_minute():
    assert prewarm.interval("/api/movers/crypto?top=50") == prewarm.FAST_S
    assert prewarm.interval("/api/chart/NVDA?range=1D&interval=1m") == prewarm.FAST_S
    assert prewarm.interval("/api/news") == prewarm.FAST_S
    assert prewarm.interval("/api/chart/NVDA?range=5Y") == prewarm.SLOW_S
    assert prewarm.interval("/api/calendars/dividends?start=2026-09-14&end=2026-09-18") == prewarm.SLOW_S


def test_a_tick_replays_only_what_is_due(monkeypatch):
    now = time.time()
    monkeypatch.setattr(prewarm, "_owners", lambda: [("u1", "me@example.com")])
    monkeypatch.setattr(prewarm, "_load", lambda uid: {"/api/movers/stocks?top=50": now, "/api/insider/AAPL": now})
    replayed = []
    monkeypatch.setattr(prewarm, "_replay", lambda uid, email, path: replayed.append(path))
    prewarm._replayed.clear()
    prewarm._replayed[("u1", "/api/insider/AAPL")] = now - 60        # slow panel, refreshed a minute ago
    assert prewarm.tick() == 1
    assert replayed == ["/api/movers/stocks?top=50"]
    assert prewarm.tick() == 0                                          # nothing due straight after


def test_reading_a_panel_postpones_its_replay(monkeypatch):
    monkeypatch.setattr(prewarm, "enabled", lambda: True)
    monkeypatch.setattr("alphadesk.ledger.store.note_warm_path", lambda uid, path: None)
    prewarm._replayed.clear()
    prewarm.note("u2", "/api/sectors")
    assert time.time() - prewarm._replayed[("u2", "/api/sectors")] < 1


def test_a_fast_panel_the_owner_has_not_read_for_hours_drops_to_the_slow_rhythm():
    from alphadesk import prewarm
    assert prewarm.interval("/api/movers/stocks", 60) == prewarm.FAST_S
    assert prewarm.interval("/api/movers/stocks", prewarm.FAST_IDLE_S + 1) == prewarm.SLOW_S
    assert prewarm.interval("/api/company/NVDA", 0) == prewarm.SLOW_S


def test_a_tick_refreshes_at_most_a_few_panels_with_a_pause_between(monkeypatch):
    from alphadesk import prewarm
    monkeypatch.setattr(prewarm, "_owners", lambda: [("u", "e@x")])
    now = __import__("time").time()
    monkeypatch.setattr(prewarm, "_load", lambda uid: {f"/api/quote/S{i}": now for i in range(40)})
    sent, slept = [], []
    monkeypatch.setattr(prewarm, "_replay", lambda uid, email, path: sent.append(path))
    monkeypatch.setattr(prewarm.time, "sleep", lambda s: slept.append(s))
    prewarm._replayed.clear()
    monkeypatch.setattr(prewarm, "_booted", 0.0)                    # long after start-up
    assert prewarm.tick() == prewarm.MAX_PER_TICK == len(sent)
    assert slept and all(s == prewarm.PAUSE_S for s in slept)


def test_just_after_a_start_everything_due_is_refreshed_at_once(monkeypatch):
    from alphadesk import prewarm
    monkeypatch.setattr(prewarm, "_owners", lambda: [("u", "e@x")])
    now = __import__("time").time()
    monkeypatch.setattr(prewarm, "_load", lambda uid: {f"/api/quote/S{i}": now for i in range(40)})
    sent, slept = [], []
    monkeypatch.setattr(prewarm, "_replay", lambda uid, email, path: sent.append(path))
    monkeypatch.setattr(prewarm.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(prewarm, "_booted", now - 30)
    prewarm._replayed.clear()
    assert prewarm.tick() == 40 and slept == []
