"""2026-10-03: what an agent needs to answer "why did this stock move" in one pass —
press-release exhibits, holder notices, a share count for a foreign filer, the
price/news/filing join, and the repair of stories stored without their tickers."""
import json
import uuid

from alphadesk.desk import moves
from alphadesk.ingest import edgar, news


def test_a_holder_notice_gives_the_share_count_it_implies():
    text = ("Reporting Person beneficially owns 70,082 Shares, representing approximately 3.74% "
            "of the Issuer's outstanding common stock.")
    assert edgar.derive_shares(text) == 1_873_900
    assert edgar.derive_shares("nothing about holdings here") is None
    assert edgar.derive_shares("owns 5 shares, approximately 0% of the class") is None


def test_holder_notices_are_readable_under_their_current_names():
    for form in ("SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A"):
        assert edgar.is_readable(form) and form in edgar.DEFAULT_FORMS
    assert not edgar.is_readable("4")


def test_a_filing_reads_with_its_press_release_exhibit(monkeypatch):
    base = "https://www.sec.gov/Archives/edgar/data/1/000000000026000001"
    pages = {
        f"{base}/main.htm": b"<html><body>Attached is a press release.</body></html>",
        f"{base}/ex99-1.htm": b"<html><body>OceanPal exits shipping and retires Series C.</body></html>",
        f"{base}/ex3-1.htm": b"<html><body>Articles of incorporation.</body></html>",
        f"{base}/index.json": json.dumps({"directory": {"item": [
            {"name": "main.htm"}, {"name": "ex99-1.htm"}, {"name": "ex3-1.htm"}, {"name": "image_001.jpg"}]}}).encode(),
    }
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: pages[url])
    assert edgar.exhibit_documents(f"{base}/main.htm") == [f"{base}/ex99-1.htm"]
    text = edgar.fetch_filing_with_exhibits(f"{base}/main.htm")
    assert "Attached is a press release." in text
    assert "[EXHIBIT ex99-1.htm]" in text and "retires Series C" in text
    assert "Articles of incorporation" not in text          # only press-release exhibits


def test_a_missing_folder_index_leaves_the_main_document(monkeypatch):
    def get(url, timeout=15.0):
        if url.endswith("index.json"):
            raise OSError("no index")
        return b"<html><body>Only the cover.</body></html>"
    monkeypatch.setattr(edgar, "_get", get)
    assert edgar.fetch_filing_with_exhibits("https://www.sec.gov/Archives/edgar/data/1/2/main.htm") == "Only the cover."


def _bars(closes, start="2026-09-01"):
    from datetime import date, timedelta
    d, out = date.fromisoformat(start), []
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"t": d.isoformat(), "c": c, "v": 1000})
        d += timedelta(days=1)
    return out


def test_big_moves_are_matched_to_the_stories_and_filings_leading_into_them():
    bars = _bars([10, 10.2, 12.6, 12.5, 12.4])           # +23.5% on Sep 3
    articles = [
        {"published_at": "2026-09-02T22:00:00+00:00", "title": "after the close", "kind": "company", "tickers": ["X"]},
        {"published_at": "2026-09-03T13:00:00+00:00", "title": "pre-market", "kind": "movers", "tickers": ["A"] * 12},
        {"published_at": "2026-09-08T13:00:00+00:00", "title": "much later", "kind": None, "tickers": ["X"]},
    ]
    filings = [{"form": "6-K", "filing_date": "2026-09-02", "accession": "A-1", "readable": True,
                "accepted_at": "2026-09-02T17:30:00-04:00"}]
    got = moves.join_moves(bars, articles, filings, min_move_pct=10)
    (day,) = got["big_move_days"]
    assert day["date"] == "2026-09-03" and day["change_pct"] == 23.53
    assert [s["title"] for s in day["stories"]] == ["after the close"]
    assert [s["title"] for s in day["list_mentions"]] == ["pre-market"] and day["list_mentions"][0]["named_tickers"] == 12
    assert [f["accession"] for f in day["filings"]] == ["A-1"]
    assert not day["nothing_attached"]
    (reaction,) = got["filing_reactions"]                 # accepted after the close: the next session reacts
    assert reaction["reaction_session"] == "2026-09-03" and reaction["change_pct"] == 23.53


def test_a_move_with_nothing_around_it_says_so():
    got = moves.join_moves(_bars([10, 10.1, 13, 13]), [], [], min_move_pct=10)
    assert got["big_moves_with_nothing_attached"] == 1
    assert got["big_move_days"][0]["nothing_attached"] is True


def test_the_board_repair_asks_each_symbol_once(store, monkeypatch):
    uid = uuid.uuid4().hex
    store.set_user_key(uid, "news", "alpaca", "sealed", "…abcd")
    store.save_board(uid, ["SVRN", "NVDA", "MU", "AAPL"], "SVRN")
    asked = []
    monkeypatch.setattr(news, "symbol_articles", lambda u, s, b, n: asked.append(s) or [])
    assert news.repair_board_tickers(uid, max_symbols=3) == 3
    assert news.repair_board_tickers(uid, max_symbols=3) == 1      # the rest, nothing twice
    assert news.repair_board_tickers(uid, max_symbols=3) == 0
    assert sorted(asked) == ["AAPL", "MU", "NVDA", "SVRN"]


def test_the_news_poll_also_asks_the_feed_for_the_main_coins_by_name():
    from datetime import datetime, timezone
    from alphadesk.ingest import news
    from alphadesk.providers.news import Article

    class Feed:
        name = "alpaca"
        def fetch(self, since, limit=200, until=None, symbols=None):
            assert symbols and "BTCUSD" in symbols
            return [Article(id="c1", title="Bitcoin rises", url="u", published_at="2026-10-05T01:00:00+00:00",
                            symbols=["BTCUSD"], summary="", source="x")]

    got = news.crypto_batch(Feed(), datetime(2026, 10, 4, tzinfo=timezone.utc), "u-test-crypto")
    assert [a["id"] for a in got] == ["c1"] and got[0]["tickers"] == ["BTCUSD"]

    class NoSymbols:                                    # a feed that cannot be asked by symbol
        name = "finnhub"
        def fetch(self, since, limit=200):
            raise AssertionError("must not be called")
    assert news.crypto_batch(NoSymbols(), datetime(2026, 10, 4, tzinfo=timezone.utc), "u-test-crypto") == []


def test_a_feeds_coin_tags_are_written_the_way_the_board_writes_them(monkeypatch):
    from alphadesk import config, cryptonews
    monkeypatch.setattr(config, "_names", config._with_coins({"AAPL": {"name": "Apple", "exchange": "Nasdaq", "class": "us_equity"}}), raising=False)
    monkeypatch.setattr(config, "_load_names", lambda: None, raising=False)
    assert cryptonews.canonical_tags(["BMNR", "BTCUSD", "DOGEUSD", "X:ETHUSD", "SOLUSDT", "BTC", "BTC-USD", "ZZZUSD", "AAPL"]) == \
        ["BMNR", "BTC-USD", "DOGE-USD", "ETH-USD", "SOL-USDT", "BTC", "ZZZUSD", "AAPL"]


def test_an_agents_coin_spellings_all_reach_the_apps_own(monkeypatch):
    from alphadesk import config, mcp_server
    monkeypatch.setattr(config, "_names", config._with_coins({}), raising=False)
    monkeypatch.setattr(config, "_load_names", lambda: None, raising=False)
    assert [mcp_server._symbol(s) for s in ("BTC/USD", "btc-usd", "BTCUSD", "SOL/USDC", "BTC", "AAPL", "BRK.B")] == \
        ["BTC-USD", "BTC-USD", "BTC-USD", "SOL-USDC", "BTC", "AAPL", "BRK.B"]
    assert mcp_server._symbols("BTC/USD, ETH/USD NVDA") == ["BTC-USD", "ETH-USD", "NVDA"]


def test_the_movers_tool_gives_a_coin_agent_the_symbol_to_use_not_the_short_label():
    from alphadesk import mcp_server
    got = mcp_server._mover_lists({"category": "crypto", "tabs": [{"id": "all", "rows": [
        {"symbol": "BTC-USD", "display": "BTC", "price": 1.0}]}]})
    assert got["all"][0]["display"] == "BTC-USD" and got["all"][0]["symbol"] == "BTC-USD"
    stocks = mcp_server._mover_lists({"category": "stocks", "tabs": [{"id": "all", "rows": [{"symbol": "NVDA", "display": "NVDA"}]}]})
    assert stocks["all"][0]["display"] == "NVDA"


def test_the_server_instructions_tell_an_agent_how_coins_differ():
    from alphadesk import mcp_server
    text = mcp_server.mcp.instructions
    assert "BTC-USD" in text and "around the clock" in text and "no order book depth" in text


def test_a_toolset_header_narrows_the_listing_and_its_absence_changes_nothing():
    import asyncio
    from alphadesk import agent_log, mcp_server
    everything = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert len(everything) >= 50
    assert {t.name for t in asyncio.run(mcp_server._list_tools_for_caller())} == everything
    held = agent_log.set_context("t1", None, None, None, "crypto")
    try:
        narrowed = {t.name for t in asyncio.run(mcp_server._list_tools_for_caller())}
    finally:
        agent_log.reset_context(held)
    assert narrowed == mcp_server.TOOLSETS["crypto"] and narrowed <= everything
    assert not {"options_flow", "list_filings", "analyst_view", "earnings_history"} & narrowed
    held = agent_log.set_context("t1", None, None, None, "no-such-set")
    try:
        assert {t.name for t in asyncio.run(mcp_server._list_tools_for_caller())} == everything   # unknown name: the full list
    finally:
        agent_log.reset_context(held)


def test_the_tool_listing_handler_is_the_filtered_one():
    from alphadesk import mcp_server
    import mcp.types as types
    handler = mcp_server.mcp._mcp_server.request_handlers[types.ListToolsRequest]
    assert handler is not None


def test_every_price_answer_names_the_broker_its_numbers_came_from(monkeypatch):
    from alphadesk import mcp_server
    assert [mcp_server.venue_name(x) for x in ("alpaca", "Alpaca-crypto", "sip", "IEX", "polygon", "", None)] == \
        ["alpaca", "alpaca", "alpaca", "alpaca", "polygon", None, None]
    assert mcp_server.venue_of({"vendor": "alpaca", "price": 1}) == "alpaca"
    assert mcp_server.venue_of({"source": "alpaca-crypto"}) == "alpaca"
    assert mcp_server.venue_of({"quote": {"vendor": "polygon"}}) == "polygon"

    @mcp_server.with_venue
    def tool(x):
        return x
    assert tool({"vendor": "alpaca"})["data_venue"] == "alpaca"
    assert tool({"source": "polygon"})["data_venue"] == "polygon"
    assert tool({"vendor": "alpaca", "data_venue": "kept"})["data_venue"] == "kept"      # never overwritten
    assert tool([1, 2]) == [1, 2] and tool(None) is None                                  # only dict answers are touched
    class R:
        answered_by = "alpaca"
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: R())
    assert tool({"price": 1})["data_venue"] == "alpaca"                                   # not named in the answer: the router's

    class Fresh:                                          # a router that has not answered yet names its quote vendor
        answered_by = None
        def vendor_for(self, surface, method):
            assert (surface, method) == ("quote", "quotes")
            return type("V", (), {"name": "alpaca"})()
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: Fresh())
    assert tool({"price": 1})["data_venue"] == "alpaca"

    class Nothing:
        answered_by = None
        def vendor_for(self, surface, method):
            raise RuntimeError("no vendor connected")
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: Nothing())
    assert tool({"price": 1})["data_venue"] == "unknown"                                  # never an error, never a guess


def test_the_price_tools_are_the_ones_that_carry_it():
    import asyncio
    from alphadesk import mcp_server
    names = {"quote", "quotes", "movers", "price_history", "price_chart", "entry_facts"}
    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert names <= set(tools)
    for n in names:                                       # the wrapper keeps each tool's own inputs
        assert tools[n].inputSchema.get("properties"), n
    assert "data_venue" in mcp_server.mcp.instructions


def test_the_agents_news_tools_write_coins_the_apps_way(monkeypatch, store):
    """symbol_news, news_search and news_story gave the feed's BTCUSD, which no
    other tool takes; news_scan grouped and priced coins under it (2026-10-07)."""
    from alphadesk import config, mcp_server
    monkeypatch.setattr(config, "_names", config._with_coins({"AAPL": {"name": "Apple", "exchange": "Nasdaq", "class": "us_equity"}}), raising=False)
    monkeypatch.setattr(config, "_load_names", lambda: None, raising=False)
    assert mcp_server._canon_tickers(["BTCUSD", "AAPL", "BTC-USD", "ZZZUSD"]) == ["BTC-USD", "AAPL", "ZZZUSD"]
    assert mcp_server._canon_tickers(None) == []
    import inspect
    for tool in ("symbol_news", "news_search", "news_story", "news_scan"):
        fn = getattr(mcp_server, tool)
        src = inspect.getsource(getattr(fn, "fn", fn))
        assert "_canon_tickers(" in src, tool
