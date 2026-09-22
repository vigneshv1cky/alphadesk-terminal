"""The MCP surface.

Tools are checked by shape and contract rather than by calling upstreams: the
point of these tests is that the tool list, its descriptions and its wiring
stay correct, not that Yahoo is up.
"""

import pytest

from alphadesk import mcp_server


@pytest.fixture()
def tools():
    import asyncio
    return {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}


EXPECTED = {
    "market_tape", "quote", "movers", "price_chart",
    "screener_window", "symbol_news", "news_search", "market_today", "find_symbol",
    "list_filings",
    "earnings_calendar", "recently_reported",
    "quotes", "price_history", "key_stats", "analyst_view", "ownership", "insider_activity",
    "earnings_history", "company_profile", "fund_profile", "financial_statements", "filing_text", "my_board", "news_story",
    "economic_calendar", "corporate_calendar", "sector_performance", "sector_breadth",
    "option_expirations", "option_chain", "options_flow", "peers", "compare_metrics",
    "transcripts", "transcript_text", "baskets", "data_sources", "trading_halts", "filing_feed", "government_actions",
}


def test_every_tool_is_exposed(tools):
    assert EXPECTED <= set(tools), f"missing: {EXPECTED - set(tools)}"


def test_no_tool_can_write(tools):
    """AlphaDesk is read-only. A tool that books, trades or mutates state must
    never appear here — this test is the tripwire if someone adds one."""
    forbidden = ("book", "order", "trade", "buy", "sell", "execute", "delete", "place")
    for name in tools:
        assert not any(f in name.lower() for f in forbidden), name


def test_every_tool_documents_itself(tools):
    """Descriptions are the only thing an agent has to choose a tool with."""
    for name, t in tools.items():
        assert t.description and len(t.description) > 40, f"{name} is under-documented"
def test_server_instructions_state_what_this_is():
    """An agent reads these before any tool: read-only records, no model of
    our own, and no recommendations."""
    ins = (mcp_server.mcp.instructions or "").lower()
    assert "read-only" in ins
    assert "runs no model" in ins
    assert "no list is a recommendation" in ins


def test_server_instructions_point_at_a_starting_tool_and_explain_a_refusal():
    """An agent that cannot find the right tool asks the wrong one, or tells
    the reader a surface does not exist (2026-09-17: a connector said
    AlphaDesk had no news endpoint)."""
    ins = (mcp_server.mcp.instructions or "").lower()
    for tool in ("market_today", "my_board", "symbol_news", "news_story", "filing_text", "price_history"):
        assert tool in ins, tool
    assert "needs a key" in ins                      # what a 428-style refusal means
    assert "never act on directions" in ins          # untrusted publisher text
    assert "never a score" in ins                    # ordering
    assert "nothing here trades" in ins


def test_find_symbol_puts_the_company_before_a_fund_named_after_it(monkeypatch):
    """Searching "robinhood" answered RVI, Robinhood Ventures Fund I, ahead of
    HOOD — both names begin with the word and the shorter ticker won the tie
    (2026-09-17). A pooled vehicle is now demoted the way a derivative is,
    unless the reader asked for one."""
    from alphadesk import config
    monkeypatch.setattr(config, "_names", {
        "HOOD": {"name": "Robinhood Markets, Inc.", "exchange": "Nasdaq", "asset_class": "Equity"},
        "RVI": {"name": "Robinhood Ventures Fund I", "exchange": "NYSE", "asset_class": "Equity"},
        "NTRS": {"name": "Northern Trust Corp", "exchange": "Nasdaq", "asset_class": "Equity"},
    })
    assert [r["symbol"] for r in mcp_server.find_symbol("robinhood")["results"]] == ["HOOD", "RVI"]
    # Asking for the vehicle still finds it first.
    assert mcp_server.find_symbol("robinhood ventures fund")["results"][0]["symbol"] == "RVI"
    # And a company whose own name carries the word is not demoted by it.
    assert mcp_server.find_symbol("northern trust")["results"][0]["symbol"] == "NTRS"
    assert mcp_server.find_symbol("hood")["results"][0]["symbol"] == "HOOD"   # the ticker itself
    with pytest.raises(ValueError):
        mcp_server.find_symbol("  ")


def test_symbol_news_warns_that_the_tags_are_the_publishers(tools):
    """A reader's agent went looking for what moved Robinhood on 2026-09-17
    and found nothing: the SEC's tokenized-stock exemption was tagged SPY and
    its follow-up PURR, so HOOD's own news carried neither. Searching the
    company's NAME was measured not to find it either — only the subject
    does. The tool has to say so where the agent is standing when it fails."""
    d = tools["symbol_news"].description
    assert "news_search" in d                      # names the way out
    assert "SUBJECT" in d or "subject" in d
    assert "tags are the publisher" in d.lower()


def test_chart_tool_surfaces_the_data_quality_gate(tools):
    """The chart tool must warn an agent about indicators_reliable, or an agent
    will happily describe RSI computed on a handful of prints."""
    d = tools["price_chart"].description
    assert "indicators_reliable" in d
    assert "coverage" in d


class _Intraday:
    """A router whose chart_series returns n one-minute bars with indicators
    aligned to them, the shape ingest/prices.build_series_payload produces."""

    def __init__(self, n=780):
        self.n = n

    def chart_series(self, symbol, days=2):
        bars = [{"t": f"2026-09-17T{9 + i // 60:02d}:{i % 60:02d}:00-04:00",
                 "o": 100 + i * 0.01, "h": 100 + i * 0.01, "l": 100 + i * 0.01,
                 "c": 100 + i * 0.01, "v": 1000 + i} for i in range(self.n)]
        return {"symbol": symbol.upper(), "bars": bars, "bar_count": len(bars), "sessions": 2,
                "coverage": 0.98, "median_gap_min": 1.0, "indicators_reliable": True,
                "interval": "1m",
                "rsi_9": [None] * 9 + [50.0 + i * 0.01 for i in range(self.n - 9)],
                "macd": [round(i * 0.001, 4) for i in range(self.n)],
                "macd_signal": [round(i * 0.0009, 4) for i in range(self.n)]}


def test_price_chart_hands_over_the_series_not_just_its_ends(monkeypatch):
    """An agent reported that this tool gave it first bar, last bar and the
    latest indicator values only, so the SHAPE of the move was unreadable
    (2026-09-17). The bars come back thinned, with the indicators computed on
    the full series aligned to each sample."""
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: _Intraday(780))
    out = mcp_server.price_chart("nvda")
    rows = out["bars_sampled"]
    assert out["bar_count"] == 780 and out["thinned_every"] == 7
    assert 100 < len(rows) <= 120
    assert rows[0]["t"].startswith("2026-09-17T09:00") and rows[-1]["c"] == out["last_bar"]["c"]
    assert all({"t", "o", "h", "l", "c", "v", "rsi_9", "macd", "macd_signal"} <= set(r) for r in rows)
    # Indicators are the full series' values at those bars, not recomputed.
    assert rows[-1]["macd"] == round(779 * 0.001, 4)
    # The summary an agent already relied on is still there.
    assert out["indicators_reliable"] is True and out["coverage"] == 0.98
    assert out["rsi_9_last"] is not None and out["first_bar"]["c"] == 100


def test_price_chart_never_thins_a_short_series_and_caps_a_greedy_one(monkeypatch):
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: _Intraday(40))
    small = mcp_server.price_chart("nvda", points=400)
    assert small["thinned_every"] == 1 and len(small["bars_sampled"]) == 40   # every bar, untouched
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: _Intraday(5000))
    big = mcp_server.price_chart("nvda", points=99_999)
    assert len(big["bars_sampled"]) <= 401                                    # the cap, not the ask
    assert big["bars_sampled"][-1]["c"] == big["last_bar"]["c"]               # the last bar always lands


class _PastDay:
    """A router whose page is stamped in UTC, as the real one is: a New York
    session on the 15th runs into the 16th in UTC."""

    def __init__(self):
        self.asked = {}

    def chart_series(self, symbol, days=2, range_key=None, interval=None, before=None, need=None):
        self.asked = {"days": days, "range_key": range_key, "before": before, "need": need}
        # 13:30 UTC on the 15th (09:30 New York) through 01:00 UTC on the 16th
        # (21:00 New York the same evening), plus an hour of the 14th before it.
        stamps = ([f"2026-09-14T2{h}:00:00+00:00" for h in (2, 3)]
                  + [f"2026-09-15T{h:02d}:00:00+00:00" for h in range(13, 24)]
                  + ["2026-09-16T00:00:00+00:00", "2026-09-16T01:00:00+00:00"])
        bars = [{"t": t, "o": 1.0, "h": 1.0, "l": 1.0, "c": float(i), "v": 10} for i, t in enumerate(stamps)]
        return {"symbol": symbol.upper(), "bars": bars, "bar_count": len(bars), "sessions": 1,
                "coverage": 0.9, "median_gap_min": 1.0, "indicators_reliable": True, "interval": "1m",
                "rsi_9": [50.0 + i for i in range(len(bars))],
                "macd": [0.1 * i for i in range(len(bars))], "macd_signal": [0.0] * len(bars)}


def test_price_chart_can_read_one_past_session_in_new_york_time(monkeypatch):
    """A date is the NEW YORK calendar day (2026-09-17). The bars are stamped
    UTC, so comparing the stamp's date would keep the previous evening and
    drop the afternoon."""
    router = _PastDay()
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: router)
    out = mcp_server.price_chart("nvda", date="2026-09-15", points=50)
    stamps = [r["t"] for r in out["bars_sampled"]]
    assert out["date"] == "2026-09-15"
    # 13:00-23:00 UTC on the 15th plus 00:00 and 01:00 UTC on the 16th, which
    # are that same New York evening; the 14th's bars are not in it.
    assert stamps[0] == "2026-09-15T13:00:00+00:00"
    assert stamps[-1] == "2026-09-16T01:00:00+00:00"
    assert out["bar_count"] == len(stamps) == 13
    assert not any(t.startswith("2026-09-14") for t in stamps)
    # The indicators are sliced with the bars, so they still line up.
    assert out["bars_sampled"][0]["rsi_9"] == 52.0
    # The page ends at the next New York midnight and asks for well over a
    # day of bars: a default page is 600, which covers ten hours at a minute.
    assert router.asked["range_key"] == "1D" and router.asked["need"] >= 1440
    assert router.asked["before"].isoformat().startswith("2026-09-16T00:00")


def test_price_chart_says_so_when_a_date_has_no_bars(monkeypatch):
    """Saturday has none: the overnight market closes Friday evening and
    reopens Sunday evening, which is why Sunday DOES have bars."""
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: _PastDay())
    with pytest.raises(ValueError, match="no bars for NVDA on 2026-09-12"):
        mcp_server.price_chart("nvda", date="2026-09-12")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        mcp_server.price_chart("nvda", date="last tuesday")


def test_a_bare_string_is_a_symbol_not_four_of_them():
    """options_flow("HOOD") warmed captures for H, O, O and D and told the
    caller to ask again in thirty seconds, forever (2026-09-17). A list is
    the documented shape; a bare string is the obvious mistake and must not
    fail silently."""
    assert mcp_server._symbols("HOOD") == ["HOOD"]
    assert mcp_server._symbols("hood, nvda amd") == ["HOOD", "NVDA", "AMD"]
    assert mcp_server._symbols(["hood", "nvda"]) == ["HOOD", "NVDA"]
    assert mcp_server._symbols([]) == [] and mcp_server._symbols(None) == []


def test_options_flow_says_it_has_the_whole_session_and_asserts_no_side(tools):
    """Its description claimed it held only what it had watched since
    starting, while the capture in fact reads from that day's opening bell —
    an agent was told to distrust data that was complete (2026-09-17)."""
    d = tools["options_flow"].description
    assert "opening bell" in d
    assert "side" in d.lower()


def test_bounded_params_are_clamped(monkeypatch):
    """An agent asking for 10000 movers must not become a 10000-row request."""
    seen = {}

    class FakePrices:
        name = "fake"

        def movers(self, top=20):
            seen["top"] = top
            return {"most_active": [], "gainers": [], "losers": []}

    from alphadesk.providers import registry
    import alphadesk.providers as pkg
    router = registry.DataRouter("u", {"alpaca": FakePrices()})
    monkeypatch.setattr(pkg, "get_prices", lambda: router)

    mcp_server.movers(top=10_000)
    assert seen["top"] == 50
    mcp_server.movers(top=-1)
    assert seen["top"] == 1


# ── news for agents: a small window and one symbol's stories ──────────────


def _story(aid, title, tickers, minutes_ago, summary=""):
    from datetime import datetime, timedelta, timezone
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"id": aid, "title": title, "summary": summary, "source": "Benzinga",
            "url": f"https://www.benzinga.com/{aid}", "published_at": at,
            "tickers": tickers, "image_url": "", "author": "", "body": "full text"}


@pytest.fixture()
def reader(store, monkeypatch):
    """A reader with a news key and a few stored stories, acting as them."""
    import base64

    from alphadesk import identity as llm
    from alphadesk.ledger import vault
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", base64.b64encode(b"k" * 32).decode())
    store.create_user("r1", "r1@example.com", "sso-only")
    store.set_user_key("r1", "news", "polygon", vault.encrypt({"api_key": "x"}), "xxxx")
    store.save_articles([
        _story("n1", "Nvidia one", ["NVDA"], 30),
        _story("n2", "Nvidia and AMD", ["AMD", "NVDA"], 20, summary="word " * 400),
        _story("n3", "Ford only", ["F", "FORD"], 10),
        _story("n4", "Nvidia newest", ["nvda"], 5),
    ], owner="r1")
    store.save_articles([_story("x1", "someone else's Nvidia", ["NVDA"], 1)], owner="r2")
    held = llm.set_request_user("r1")
    yield store
    llm.reset_request_user(held)


def test_symbol_news_returns_that_symbols_stories_newest_first_with_links(reader, monkeypatch):
    from alphadesk import config
    monkeypatch.setattr(config, "_names", {"NVDA": {"name": "NVIDIA CORP", "exchange": "Nasdaq"}})
    out = mcp_server.symbol_news("nvda")
    assert out["symbol"] == "NVDA"
    # The company's own name travels with the stories, so an agent that needs
    # to widen the search does not have to guess what NVDA is called.
    assert out["company"] == "NVIDIA CORP"
    assert [a["title"] for a in out["articles"]] == ["Nvidia newest", "Nvidia and AMD", "Nvidia one"]
    assert all(a["url"].startswith("https://www.benzinga.com/") for a in out["articles"])
    assert "someone else's Nvidia" not in {a["title"] for a in out["articles"]}   # another reader's feed
    assert out["next_before"] is None
    # A long summary is cut at a word, the full text stays behind the link.
    long = out["articles"][1]["summary"]
    assert len(long) <= 601 and long.endswith("…")
    assert "body" not in out["articles"][0]


def test_news_search_finds_stories_by_word_across_symbols(reader):
    """The question that has no ticker: a theme, a person, a product. The
    match runs over headline, summary and tickers, newest first."""
    out = mcp_server.news_search("nvidia")
    assert out["query"] == "nvidia"
    assert [a["title"] for a in out["articles"]] == ["Nvidia newest", "Nvidia and AMD", "Nvidia one"]
    # A ticker is a word too, and it reaches a story whose headline omits it.
    assert [a["title"] for a in mcp_server.news_search("ford")["articles"]] == ["Ford only"]
    assert mcp_server.news_search("nothing written about this")["articles"] == []


def test_news_search_stays_inside_the_reader_own_window(reader):
    titles = {a["title"] for a in mcp_server.news_search("nvidia", limit=50)["articles"]}
    assert "someone else's Nvidia" not in titles          # another reader's feed


def test_news_search_pages_backwards_and_cuts_a_long_summary(reader):
    first = mcp_server.news_search("nvidia", limit=2)
    assert [a["title"] for a in first["articles"]] == ["Nvidia newest", "Nvidia and AMD"]
    assert first["next_before"]
    rest = mcp_server.news_search("nvidia", limit=2, before=first["next_before"])
    assert [a["title"] for a in rest["articles"]] == ["Nvidia one"] and rest["next_before"] is None
    long = first["articles"][1]["summary"]
    assert len(long) <= 601 and long.endswith("…")


def test_news_search_refuses_an_empty_query(reader):
    with pytest.raises(ValueError):
        mcp_server.news_search("   ")


def test_symbol_news_pages_backwards(reader):
    first = mcp_server.symbol_news("NVDA", limit=2)
    assert [a["title"] for a in first["articles"]] == ["Nvidia newest", "Nvidia and AMD"]
    assert first["next_before"]
    rest = mcp_server.symbol_news("NVDA", limit=2, before=first["next_before"])
    assert [a["title"] for a in rest["articles"]] == ["Nvidia one"] and rest["next_before"] is None


def test_a_short_symbol_does_not_match_a_longer_one(reader):
    assert [a["title"] for a in mcp_server.symbol_news("F")["articles"]] == ["Ford only"]
    assert mcp_server.symbol_news("FO")["articles"] == []


def test_symbol_news_without_a_news_key_names_the_key(store):
    from alphadesk import identity as llm
    from alphadesk.providers.base import NeedsKey
    store.create_user("r9", "r9@example.com", "sso-only")
    held = llm.set_request_user("r9")
    try:
        with pytest.raises(NeedsKey):
            mcp_server.symbol_news("NVDA")
    finally:
        llm.reset_request_user(held)


def test_the_window_is_small_and_pages(reader, monkeypatch):
    from alphadesk.desk import screener
    rows = [{"symbol": s, "report_date": None, "session": None, "article_count": 1,
             "headlines": [{"title": "t", "url": "u"}] * 5} for s in ("AAPL", "AMD", "MSFT", "NVDA", "TSLA")]
    monkeypatch.setattr(screener, "inventory", lambda: rows)
    first = mcp_server.screener_window(limit=2)
    assert first["total"] == 5
    assert [r["symbol"] for r in first["symbols"]] == ["AAPL", "AMD"]
    assert "headlines" not in first["symbols"][0]
    second = mcp_server.screener_window(limit=2, after=first["next_after"])
    third = mcp_server.screener_window(limit=2, after=second["next_after"])
    assert [r["symbol"] for r in second["symbols"] + third["symbols"]] == ["MSFT", "NVDA", "TSLA"]
    assert third["next_after"] is None


def test_baskets_list_find_by_member_and_open_one(monkeypatch):
    """The baskets are the app's own editorial groups, handed to the agent so
    it can find what moves with a name (2026-09-18)."""
    import alphadesk.config as config
    monkeypatch.setattr(config, "THEMES", [
        {"id": "crypto-stocks", "label": "Crypto stocks", "symbols": ["COIN", "MSTR", "HOOD"]},
        {"id": "fintech", "label": "Payments & fintech", "symbols": ["V", "HOOD"]},
        {"id": "semis", "label": "Semiconductors", "symbols": ["NVDA"]},
    ])
    monkeypatch.setattr(config, "company_name", lambda s: {"COIN": "Coinbase Global, Inc."}.get(s))
    assert len(mcp_server.baskets()["baskets"]) == 3
    # A member names every group it sits in: its likely co-movers.
    assert [b["id"] for b in mcp_server.baskets(symbol="hood")["baskets"]] == ["crypto-stocks", "fintech"]
    # One basket by label, any case; members in the order written.
    one = mcp_server.baskets(basket="CRYPTO STOCKS")
    assert [m["symbol"] for m in one["members"]] == ["COIN", "MSTR", "HOOD"]
    assert one["members"][0]["name"] == "Coinbase Global, Inc." and "quotes" not in one
    assert "error" in mcp_server.baskets(basket="nope")


def test_every_default_basket_is_well_formed():
    from alphadesk.config import _DEFAULT_THEMES
    ids = [t["id"] for t in _DEFAULT_THEMES]
    assert len(ids) == len(set(ids)) and len(ids) >= 30
    # Every ticker has one home (2026-09-18, the owner's call): no two
    # curated baskets share a member.
    homes: dict[str, str] = {}
    for t in _DEFAULT_THEMES:
        for s in t["symbols"]:
            assert s not in homes, f"{s} is in both {homes.get(s)} and {t['id']}"
            homes[s] = t["id"]
    for t in _DEFAULT_THEMES:
        assert t["label"] and t["symbols"] and all(s == s.upper() for s in t["symbols"])
        assert len(t["symbols"]) == len(set(t["symbols"])), t["id"]
    # Every basket says what moves it, in one wording (2026-09-18); the page
    # shows it above the members.
    assert all(t.get("why", "").startswith("These ") and "move up or down based on" in t["why"]
               for t in _DEFAULT_THEMES)


def test_every_data_surface_the_app_has_is_reachable_by_an_agent():
    """The agent sees what the screen sees (2026-09-21). Six panels had no
    tool: the funds built on a company, a symbol's events, its reported
    record, the crypto list, the cross-asset board, and the calendar's own
    accuracy against the SEC."""
    from alphadesk import mcp_server
    named = {t for t in dir(mcp_server) if not t.startswith("_")}
    for tool in ("related_funds", "symbol_events", "earnings_context",
                 "crypto_movers", "index_board", "calendar_accuracy"):
        assert tool in named, tool


def test_the_funds_tool_answers_the_opposite_question_to_fund_profile():
    """One says what a fund holds; the other says what is built on a stock.
    Confusing them is the easy mistake, so both descriptions say which."""
    from alphadesk import mcp_server
    built_on = (mcp_server.related_funds.__doc__ or "").lower()
    holds = (mcp_server.fund_profile.__doc__ or "").lower()
    assert "built on" in built_on and "fund_profile" in built_on
    assert "hold" in holds


def test_the_publisher_and_the_delivering_feed_are_separate_fields(reader):
    """An agent reading a merged window has to be able to tell WHO WROTE a
    story from WHICH OF THE READER'S FEEDS carried it (2026-09-22). One
    `source` string answered neither reliably: it holds the publisher where
    the feed named one and the feed's own name where it did not, so a story
    with no stated publisher read as "Alpaca". A story two connected feeds
    both delivered names both — the only corroboration signal here."""
    from alphadesk.ledger import store
    both = {**_story("n5", "Carried twice", ["NVDA"], 1), "feeds": ["alpaca", "polygon"]}
    alone = {**_story("n6", "Carried once", ["NVDA"], 2, ), "source": "", "feeds": ["polygon"]}
    store.save_articles([both, alone], owner="r1")

    rows = {a["title"]: a for a in mcp_server.symbol_news("nvda")["articles"]}
    assert rows["Carried twice"]["feeds"] == ["alpaca", "polygon"]
    assert rows["Carried twice"]["source"] == "Benzinga"        # who wrote it
    assert rows["Carried once"]["feeds"] == ["polygon"]
    # A story stored before the feeds were recorded says nothing rather than
    # naming a feed it was never known to have come from.
    assert rows["Nvidia newest"]["feeds"] == []

    found = {a["title"]: a for a in mcp_server.news_search("carried")["articles"]}
    assert found["Carried twice"]["feeds"] == ["alpaca", "polygon"]

    one = mcp_server.news_story(found["Carried twice"]["article_id"])
    assert one["feeds"] == ["alpaca", "polygon"] and one["source"] == "Benzinga"


def test_every_news_tool_says_the_two_fields_apart(tools):
    """The distinction is useless if the agent is not told it exists."""
    for name in ("symbol_news", "news_search", "news_story", "market_today"):
        d = tools[name].description
        assert "feeds" in d and "publisher" in d.lower(), name
