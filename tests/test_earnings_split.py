"""/api/earnings: released is released, a stale sibling is not "soon", and
soon means within a week."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from alphadesk.app import dashboard
from alphadesk.config import ET


def _rows(now):
    d = lambda n: (now + timedelta(days=n)).date().isoformat()  # noqa: E731
    return [
        # Released early: an actual on a row dated tomorrow.
        {"symbol": "EARLY", "report_date": d(1), "session": "DAY", "eps_actual": 1.0, "eps_estimate": 0.9},
        # Reported yesterday, plus a stale projected sibling for tomorrow.
        {"symbol": "STALE", "report_date": d(-1), "session": "AMC", "eps_actual": 0.5},
        {"symbol": "STALE", "report_date": d(1), "session": "DAY"},
        # Out per EDGAR (an 8-K accepted), no number yet, dated today.
        {"symbol": "OUT", "report_date": d(0), "session": "BMO", "released_at": "2026-09-11T12:31:00Z"},
        # Genuinely soon, and genuinely far.
        {"symbol": "SOON", "report_date": d(3), "session": "BMO"},
        {"symbol": "FAR", "report_date": d(12), "session": "DAY"},
    ]


def test_released_stale_and_far_rows_are_kept_out_of_upcoming(monkeypatch):
    now = datetime(2026, 9, 11, 12, 0, tzinfo=ET)
    monkeypatch.setattr("alphadesk.config.now_et", lambda: now)
    from alphadesk.ingest import earnings_calendar
    monkeypatch.setattr(earnings_calendar, "rows_between", lambda start, end, stats=True: _rows(now))
    r = TestClient(dashboard.app).get("/api/earnings")
    assert r.status_code == 200
    body = r.json()
    up = [(e["symbol"], e["report_date"]) for e in body["upcoming"]]
    rep = {e["symbol"] for e in body["reported"]}
    assert up == [("SOON", (now + timedelta(days=3)).date().isoformat())]
    assert "EARLY" in rep and "STALE" in rep and "OUT" in rep
