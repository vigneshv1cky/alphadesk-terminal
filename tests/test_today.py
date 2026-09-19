"""Today's market for a reader's agent (2026-09-17).

One call answering "what's trending": these tests hold its contract — lists
ordered only by the number shown, a missing vendor costing one section and
never the reply, and every section running as the reader who asked, even on
the worker threads that fetch the sections in parallel.
"""

import base64
from datetime import datetime, timedelta, timezone

import pytest

from alphadesk.desk import today


@pytest.fixture(autouse=True)
def _vault(monkeypatch):
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", base64.b64encode(b"k" * 32).decode())


def _story(aid, title, tickers, minutes_ago):
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"id": aid, "title": title, "summary": "", "source": "Benzinga", "url": f"https://b/{aid}",
            "published_at": at, "tickers": tickers, "image_url": "", "author": "", "body": ""}


@pytest.fixture()
def as_reader(store):
    from alphadesk import identity as llm
    from alphadesk.ledger import vault
    store.create_user("r1", "r1@example.com", "sso-only")
    store.set_user_key("r1", "news", "polygon", vault.encrypt({"api_key": "x"}), "xxxx")
    held = llm.set_request_user("r1")
    yield store
    llm.reset_request_user(held)


def _stub_market(monkeypatch, seen=None):
    """Replace the vendor-backed sections with fixed data; record who asked."""
    from alphadesk.identity import request_user

    def who(value):
        def fn(*a, **k):
            if seen is not None:
                seen.append(request_user())
            return value
        return fn
    monkeypatch.setattr(today, "_tape", who([{"symbol": "SPY", "price": 1.0, "change_pct": 0.5}]))
    monkeypatch.setattr(today, "_movers", who({"gainers": [], "losers": [], "most_active": []}))
    monkeypatch.setattr(today, "_sectors", who([]))
    monkeypatch.setattr(today, "_earnings", who([]))
    monkeypatch.setattr(today, "_economic", who([]))


def test_news_is_ordered_by_story_count_with_the_count_shown(as_reader, monkeypatch):
    as_reader.save_articles([
        _story("a", "NVDA one", ["NVDA"], 30),
        _story("b", "NVDA and AMD", ["NVDA", "AMD"], 20),
        _story("c", "AAPL one", ["AAPL"], 15),
        _story("d", "AMD newest", ["AMD"], 5),
        _story("e", "TSLA", ["TSLA"], 1),
    ], owner="r1")
    _stub_market(monkeypatch)
    out = today.market_today(top=3)
    news = out["news"]
    assert news["stories_today"] == 5
    # Most stories first; a tie falls back to alphabetical, never to a score.
    assert [(r["symbol"], r["stories"]) for r in news["most_covered"]] == [("AMD", 2), ("NVDA", 2), ("AAPL", 1)]
    assert news["most_covered"][0]["newest"]["title"] == "AMD newest"
    assert news["most_covered"][0]["newest"]["url"] == "https://b/d"
    assert [a["title"] for a in news["latest"]] == ["TSLA", "AMD newest", "AAPL one"]
    assert out["unavailable"] == {}


def test_a_missing_vendor_costs_one_section_not_the_reply(as_reader, monkeypatch):
    from alphadesk.providers.base import NeedsKey
    _stub_market(monkeypatch)

    def no_calendar(*a, **k):
        raise NeedsKey("earnings_calendar", [])

    def broken(*a, **k):
        raise RuntimeError("vendor timed out")
    monkeypatch.setattr(today, "_earnings", no_calendar)
    monkeypatch.setattr(today, "_sectors", broken)
    out = today.market_today()
    assert "earnings_today" not in out and "sectors" not in out
    assert "needs a key" in out["unavailable"]["earnings_today"]
    assert out["unavailable"]["sectors"] == "could not be loaded right now"   # the reason, never a stack
    assert out["tape"][0]["symbol"] == "SPY"


def test_without_a_news_key_the_news_section_names_the_key(store, monkeypatch):
    from alphadesk import identity as llm
    store.create_user("r2", "r2@example.com", "sso-only")
    _stub_market(monkeypatch)
    held = llm.set_request_user("r2")
    try:
        out = today.market_today()
    finally:
        llm.reset_request_user(held)
    assert "news" not in out and "needs a key" in out["unavailable"]["news"]


def test_every_section_runs_as_the_reader_who_asked(as_reader, monkeypatch):
    """The sections run on worker threads; a bare thread would run as nobody,
    on no keys, and quietly answer empty."""
    seen = []
    _stub_market(monkeypatch, seen)
    today.market_today()
    assert seen and set(seen) == {"r1"}


def test_movers_and_sectors_keep_only_the_shown_fields_and_measured_order(monkeypatch):
    class Router:
        def ask(self, what, **kw):
            assert what == "movers"
            rows = [{"symbol": f"S{i}", "name": "n", "price": 1.0, "change_pct": 10 - i,
                     "volume": 100, "extra": "dropped"} for i in range(30)]
            return {"gainers": rows, "losers": rows, "most_active": rows}
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: Router())
    got = today._movers(5)
    assert [r["symbol"] for r in got["gainers"]] == ["S0", "S1", "S2", "S3", "S4"]
    assert "extra" not in got["gainers"][0]

    from alphadesk.ingest import sectors
    monkeypatch.setattr(sectors, "sectors", lambda: {"sectors": [
        {"symbol": "XLK", "label": "Tech", "change_pct": 0.4, "w1": 1},
        {"symbol": "XLE", "label": "Energy", "change_pct": 1.2},
        {"symbol": "XLU", "label": "Utilities", "change_pct": None},
    ]})
    assert [r["symbol"] for r in today._sectors()] == ["XLE", "XLK", "XLU"]
