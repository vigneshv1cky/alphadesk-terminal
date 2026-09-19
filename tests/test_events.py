"""Earnings markers are 8-K Item 2.02 filings — nothing else on EDGAR, and
nothing from a calendar vendor."""
from datetime import date

from alphadesk.ingest import events


def test_earnings_are_item_202_filings_only(monkeypatch):
    rows = [
        {"accession": "a1", "filing_date": "2026-08-27", "items": "2.02,9.01", "url": "u1"},
        {"accession": "a2", "filing_date": "2026-07-01", "items": "5.02", "url": "u2"},
        {"accession": "a3", "filing_date": "2026-05-28", "items": "2.02", "url": "u3"},
        {"accession": "a4", "filing_date": "2020-01-01", "items": "2.02", "url": "u4"},
    ]
    monkeypatch.setattr(events.edgar, "recent_filings", lambda *a, **k: rows)
    out = events._earnings("NVDA", date(2026, 1, 1))
    assert [e["accession"] for e in out] == ["a1", "a3"]
    assert out[0]["url"] == "u1"


def test_events_shape_and_cache(monkeypatch):
    monkeypatch.setattr(events, "_earnings", lambda s, since: [{"date": "2026-08-27", "accession": "a", "url": "u"}])
    monkeypatch.setattr(events, "_actions", lambda s, since: ([{"date": "2026-06-10", "amount": 0.01}], []))
    events._cache.clear()
    first = events.events("nvda", days=100)
    assert first["symbol"] == "NVDA"
    assert first["earnings"][0]["accession"] == "a"
    assert first["dividends"][0]["amount"] == 0.01
    assert first["splits"] == []
    # The second call is the cached object — the sources are not asked again.
    monkeypatch.setattr(events, "_earnings", lambda s, since: (_ for _ in ()).throw(AssertionError("asked again")))
    assert events.events("NVDA", days=100) is first
