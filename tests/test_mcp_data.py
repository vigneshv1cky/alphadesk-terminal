"""Raw data tools for a reader's own agent (2026-09-17).

The *_ask tools need a model key stored in AlphaDesk; these hand the agent
the data instead. What is held here is the part that is ours rather than a
passthrough: the price-history summary, filing text paging, the batch-quote
limit, and HTTP refusals surfacing as plain tool errors.
"""

from datetime import date, timedelta

import pytest

from alphadesk import mcp_server


def _bars(n, start=100.0, step=1.0):
    d0 = date(2025, 1, 1)
    return [{"t": f"{(d0 + timedelta(days=i)).isoformat()}T04:00:00+00:00", "o": start + i * step,
             "h": start + i * step + 2, "l": start + i * step - 2, "c": start + i * step, "v": 1000 + i}
            for i in range(n)]


def test_history_summary_reports_returns_extremes_and_dates():
    bars = _bars(300)
    out = mcp_server.summarize_history("NVDA", "1Y", bars, "alpaca")
    last = bars[-1]["c"]
    assert out["last"] == {"date": bars[-1]["t"][:10], "close": last}
    assert out["returns_pct"]["1w"] == round(100 * (last / bars[-6]["c"] - 1), 2)
    assert out["returns_pct"]["1y"] == round(100 * (last / bars[-253]["c"] - 1), 2)
    assert out["high"] == {"date": bars[-1]["t"][:10], "price": last + 2}
    assert out["low"] == {"date": bars[0]["t"][:10], "price": bars[0]["c"] - 2}
    assert out["change_pct"] == round(100 * (last / bars[0]["c"] - 1), 2)


def test_a_long_history_is_thinned_but_keeps_its_last_close():
    bars = _bars(1300)
    out = mcp_server.summarize_history("NVDA", "5Y", bars, "alpaca")
    assert len(out["points"]) <= mcp_server._MAX_POINTS + 1
    assert out["points"][-1]["date"] == bars[-1]["t"][:10]
    assert out["thinned_every"] > 1
    short = mcp_server.summarize_history("NVDA", "1M", _bars(21), "alpaca")
    assert "1y" not in short["returns_pct"] and short["thinned_every"] == 1 and len(short["points"]) == 21


def test_price_history_refuses_an_unknown_range():
    with pytest.raises(ValueError, match="range must be"):
        mcp_server.price_history("NVDA", range="2W")


def test_price_history_turns_an_http_refusal_into_a_tool_error(monkeypatch):
    from fastapi import HTTPException

    from alphadesk.app import dashboard

    def refuse(*a, **k):
        raise HTTPException(503, "alpaca: rate limited")
    monkeypatch.setattr(dashboard, "api_chart", refuse)
    with pytest.raises(ValueError, match="rate limited"):
        mcp_server.price_history("NVDA")


def test_filing_text_pages_through_the_document(monkeypatch):
    text = "A" * 20_000 + "B" * 20_000 + "C" * 5
    monkeypatch.setattr(mcp_server, "_filing_document", lambda acc: text if acc == "0001-26-000001" else None)
    first = mcp_server.filing_text("0001-26-000001")
    assert first["pages"] == 3 and first["page"] == 1 and set(first["text"]) == {"A"}
    last = mcp_server.filing_text("0001-26-000001", page=99)
    assert last["page"] == 3 and last["text"] == "CCCCC"
    with pytest.raises(ValueError, match="not available"):
        mcp_server.filing_text("0009-26-000009")


def test_quotes_asks_for_one_basket_with_the_extra_fields(monkeypatch):
    from alphadesk.app import dashboard
    seen = {}

    def fake(symbols="", fill=""):
        seen.update(symbols=symbols, fill=fill)
        return {"quotes": {}}
    monkeypatch.setattr(dashboard, "api_quotes", fake)
    mcp_server.quotes([f"s{i}" for i in range(60)] + ["", " "])
    assert len(seen["symbols"].split(",")) == 50 and seen["symbols"].startswith("S0,S1")
    assert seen["fill"] == "range,cap"
    with pytest.raises(ValueError):
        mcp_server.quotes([])


def test_filing_text_reads_the_whole_document_not_the_qa_cache(monkeypatch):
    from alphadesk.desk import filings
    from alphadesk.ledger import store
    monkeypatch.setattr(store, "get_filing_meta", lambda acc: {"url": "https://www.sec.gov/x.htm"})
    monkeypatch.setattr(mcp_server, "_full_filing_text", lambda url: "F" * 90_000)
    monkeypatch.setattr(filings, "get_text", lambda acc, url=None: "Q" * 60_000)
    assert mcp_server.filing_text("0001-26-000001")["characters"] == 90_000
    monkeypatch.setattr(mcp_server, "_full_filing_text", lambda url: None)      # SEC unreachable
    assert mcp_server.filing_text("0001-26-000001")["characters"] == 60_000


# ── the reader's board, and a story's own text ────────────────────────────


def test_the_board_is_mirrored_per_reader_and_normalised(store, monkeypatch):
    from fastapi.testclient import TestClient

    from alphadesk.app import dashboard
    store.ensure_local_user()
    uid = dashboard._local_uid()
    monkeypatch.setattr(dashboard, "_key_user", lambda request: uid)
    with TestClient(dashboard.app) as c:
        assert c.get("/api/board").json() == {"symbols": [], "active": "", "updated_at": None}
        c.put("/api/board", json={"symbols": ["nvda", "NVDA", " crwd ", "!!"], "active": "crwd"})
        got = c.get("/api/board").json()
        assert got["symbols"] == ["NVDA", "CRWD"] and got["active"] == "CRWD"
        # An active symbol that is not on the board falls back to the first.
        c.put("/api/board", json={"symbols": ["AAPL"], "active": "TSLA"})
        assert c.get("/api/board").json() == {**c.get("/api/board").json(), "symbols": ["AAPL"], "active": "AAPL"}
    assert store.get_board("someone-else") is None


def test_my_board_answers_with_quotes_or_says_there_is_none(store, monkeypatch):
    from alphadesk import identity as llm
    from alphadesk.app import dashboard
    store.create_user("b1", "b1@example.com", "sso-only")
    monkeypatch.setattr(dashboard, "api_quotes", lambda symbols="", fill="": {"quotes": {s: {"price": 1.0} for s in symbols.split(",")}})
    held = llm.set_request_user("b1")
    try:
        assert mcp_server.my_board()["symbols"] == [] and "no board saved" in mcp_server.my_board()["note"]
        store.save_board("b1", ["NVDA", "CRWD"], "CRWD")
        out = mcp_server.my_board()
        assert out["symbols"] == ["NVDA", "CRWD"] and out["active"] == "CRWD"
        assert set(out["quotes"]) == {"NVDA", "CRWD"}
    finally:
        llm.reset_request_user(held)


def test_a_story_body_becomes_plain_text_in_pages(monkeypatch):
    from alphadesk.ingest import news
    body = "<p>" + "word " * 4000 + "</p><script>ignore()</script><p>End.</p>"
    monkeypatch.setattr(news, "full_story", lambda uid, aid: {
        "article_id": aid, "title": "T", "url": "https://b/x", "source": "Benzinga",
        "published_at": "2026-09-17T10:00:00+00:00", "tickers": ["NVDA"], "summary": "s", "body": body})
    from alphadesk import identity as llm
    held = llm.set_request_user("b1")
    try:
        first = mcp_server.news_story("n1")
        assert first["pages"] >= 2 and first["page"] == 1 and first["full_text"] is True
        assert "<p>" not in first["text"] and first["text"].startswith("word")
        last = mcp_server.news_story("n1", page=99)
        assert last["page"] == last["pages"] and last["text"].endswith("End.")
    finally:
        llm.reset_request_user(held)


def test_a_story_that_is_not_the_readers_is_an_honest_error(monkeypatch):
    from alphadesk import identity as llm
    from alphadesk.ingest import news
    monkeypatch.setattr(news, "full_story", lambda uid, aid: None)
    held = llm.set_request_user("b1")
    try:
        with pytest.raises(ValueError, match="no such story"):
            mcp_server.news_story("nope")
    finally:
        llm.reset_request_user(held)


def test_strip_markup_keeps_plain_text_and_drops_tags():
    assert mcp_server.strip_markup("Plain text.") == "Plain text."
    assert mcp_server.strip_markup("<p>One</p>\n\n<p>Two</p>") == "One\nTwo"
    assert mcp_server.strip_markup("") == ""


# ── calendars, sectors, options, transcripts ──────────────────────────────


def test_only_the_asked_country_and_a_readable_date_error(monkeypatch):
    from alphadesk.ingest import economic
    monkeypatch.setattr(economic, "calendar", lambda s, e: {"start": s, "end": e, "source": "fmp", "rows": [
        {"time": "2026-09-17T12:30:00Z", "country": "US", "event": "Jobless claims", "impact": "high"},
        {"time": "2026-09-17T08:00:00Z", "country": "USA", "event": "Housing starts", "impact": "medium"},
        {"time": "2026-09-17T09:00:00Z", "country": "DE", "event": "Ifo", "impact": "low"}]})
    rows = mcp_server.economic_calendar()["rows"]
    assert [r["event"] for r in rows] == ["Housing starts", "Jobless claims"]     # US and USA, by time
    assert len(mcp_server.economic_calendar(country="")["rows"]) == 3
    with pytest.raises(ValueError, match="ISO date"):
        mcp_server.economic_calendar(start="last tuesday")


def test_corporate_calendar_names_its_three_kinds(monkeypatch):
    from alphadesk.ingest import corporate_calendars as cc
    monkeypatch.setattr(cc, "splits", lambda s, e: {"start": s, "end": e, "source": "fmp",
                                                    "rows": [{"symbol": f"S{i}"} for i in range(50)]})
    got = mcp_server.corporate_calendar("Splits", limit=5)
    assert got["kind"] == "splits" and got["total"] == 50 and len(got["rows"]) == 5
    with pytest.raises(ValueError, match="dividends, splits or ipos"):
        mcp_server.corporate_calendar("buybacks")


def test_an_option_chain_comes_back_around_the_money():
    rows = [{"strike": float(s), "bid": 1.0, "ask": 1.1, "open_interest": 5, "junk": "dropped"}
            for s in range(100, 300, 5)]
    near = mcp_server.near_the_money(rows, spot=219.0, strikes=3)
    assert [r["strike"] for r in near] == [205.0, 210.0, 215.0, 220.0, 225.0, 230.0]
    assert "junk" not in near[0]
    # No spot (a vendor that does not price the underlying): the first rows.
    assert len(mcp_server.near_the_money(rows, spot=None, strikes=3)) == 6
    assert mcp_server.near_the_money([], spot=219.0, strikes=3) == []


def test_option_chain_insists_on_an_expiry():
    with pytest.raises(ValueError, match="expiry is required"):
        mcp_server.option_chain("NVDA", expiry="")


def test_sector_lists_are_ordered_by_todays_move(monkeypatch):
    from alphadesk.ingest import sectors as sec
    monkeypatch.setattr(sec, "sectors", lambda: {
        "as_of": "t", "source": "alpaca", "benchmark": {"symbol": "SPY", "change_pct": 1.0},
        "sectors": [{"symbol": "XLF", "label": "Financials", "change_pct": 0.1, "bases": {"w1": 1}},
                    {"symbol": "XLK", "label": "Tech", "change_pct": 2.2}],
        "industries": [{"symbol": "SMH", "label": "Semis", "change_pct": 3.0}]})
    got = mcp_server.sector_performance()
    assert [r["symbol"] for r in got["sectors"]] == ["XLK", "XLF"]
    assert "bases" not in got["sectors"][1]


def test_a_transcript_is_paged_and_a_missing_one_says_so(monkeypatch):
    from alphadesk.desk import transcripts as tr
    monkeypatch.setattr(tr, "get_transcript", lambda sym, id: None if id == "nope" else {
        "symbol": sym, "id": id, "date": "2026-08-26", "title": "Q2", "provider": "edgar",
        "text": "T" * 30_000})
    got = mcp_server.transcript_text("NVDA", "0001-26-000073", page=2)
    assert got["pages"] == 2 and got["characters"] == 30_000 and len(got["text"]) == 10_000
    with pytest.raises(ValueError, match="not available"):
        mcp_server.transcript_text("NVDA", "nope")


def test_a_cold_options_flow_symbol_warms_instead_of_hanging(monkeypatch):
    """The first capture reads every print since the opening bell — 6s on a
    quiet name, ~28s on a busy one. An agent's call must not sit through it."""
    from alphadesk.ingest import options_flow
    from alphadesk.app import dashboard
    started = []

    class Router:
        owner = "r1"
        def vendor_for(self, surface, method):
            return "vendor"
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: Router())
    monkeypatch.setattr(options_flow, "warm", lambda vendor, owner, syms: (started.extend(syms), list(syms))[1])
    monkeypatch.setattr(dashboard, "api_option_flow", lambda **k: pytest.fail("must not fetch a cold symbol"))

    out = mcp_server.options_flow(["nvda"])
    assert out["warming"] == ["NVDA"] and out["trades"] == [] and "ask again" in out["note"]
    assert started == ["NVDA"]

    # Warm now: the flow is fetched and the reply says nothing is warming.
    monkeypatch.setattr(options_flow, "warm", lambda vendor, owner, syms: [])
    monkeypatch.setattr(dashboard, "api_option_flow", lambda **k: {
        "symbols": ["NVDA"], "session": "2026-09-17", "feed": "opra", "live_since": "t",
        "min_premium": 50_000.0, "trades": [{"t": "1", "contract": "C", "premium": 90_000.0, "junk": "dropped"}],
        "errors": {}})
    warmed = mcp_server.options_flow(["NVDA"])
    assert warmed["warming"] == [] and [t["contract"] for t in warmed["trades"]] == ["C"]
    assert "junk" not in warmed["trades"][0]


def test_warm_starts_one_capture_per_cold_symbol(monkeypatch):
    """Two calls in the same moment must not start the same capture twice."""
    import threading
    import time as _t

    from alphadesk.ingest import options_flow
    options_flow._states.clear()
    options_flow._warming.clear()
    calls = []
    release = threading.Event()

    def slow_capture(vendor, owner, sym, now=None):
        calls.append(sym)
        release.wait(2)
        return {}
    monkeypatch.setattr(options_flow, "capture", slow_capture)
    assert options_flow.warm("v", "r1", ["NVDA", "AMD"]) == ["NVDA", "AMD"]
    _t.sleep(0.2)
    assert options_flow.warm("v", "r1", ["NVDA"]) == ["NVDA"]      # still cold, still warming
    release.set()
    _t.sleep(0.3)
    assert sorted(calls) == ["AMD", "NVDA"]                        # started once each
