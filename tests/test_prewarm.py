"""Keeping an owner's panels warm (alphadesk/prewarm.py)."""

import time

from alphadesk import prewarm


def test_only_market_data_reads_are_kept():
    assert prewarm.worth_keeping("/api/movers/stocks?top=50")
    assert prewarm.worth_keeping("/api/insider/AAPL")
    for p in ("/api/stream?trades=AAPL", "/api/auth/me", "/api/admin/users", "/api/agent/tools/mcp",
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
