"""The live-trade stream's bookkeeping.

Everything here runs without a socket. What is worth testing is not that
Alpaca can push a trade — it can — but that the process holds exactly one
upstream subscription per symbol somebody is watching, and none at all for
symbols nobody is. The free tier allows a single concurrent connection, so a
leaked reference is not a tidiness problem: it is a subscription that outlives
its reader and a connection slot that cannot be reclaimed.
"""

import time
from types import SimpleNamespace

import pytest

from alphadesk.ingest import stream as stream_mod


class FakeStream:
    """Stands in for alpaca-py's StockDataStream, recording what it was told."""

    def __init__(self):
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    def subscribe_trades(self, handler, *symbols):
        self.subscribed.extend(symbols)

    def unsubscribe_trades(self, *symbols):
        self.unsubscribed.extend(symbols)


@pytest.fixture
def market(monkeypatch):
    """A stream whose upstream is a fake and which never starts a thread."""
    m = stream_mod._MarketStream()
    fake = FakeStream()
    monkeypatch.setattr(m, "_ensure_running", lambda: (setattr(m, "_stream", fake) or True)
                        if m._stream is None else True)
    m._fake = fake                     # type: ignore[attr-defined]
    return m


class TestSubscriptionRefcount:
    def test_first_reader_subscribes_upstream(self, market):
        assert market.acquire("nvda") is True
        assert market._fake.subscribed == ["NVDA"]
        assert market.status()["symbols"] == {"NVDA": 1}

    def test_second_reader_does_not_resubscribe(self, market):
        # Two panels on one board share the upstream subscription; asking
        # twice must not send a second subscribe.
        market.acquire("NVDA")
        market.acquire("NVDA")
        assert market._fake.subscribed == ["NVDA"]
        assert market.status()["symbols"] == {"NVDA": 2}

    def test_upstream_survives_until_the_last_reader_goes(self, market):
        market.acquire("NVDA")
        market.acquire("NVDA")
        market.release("NVDA")
        assert market._fake.unsubscribed == []      # one reader is still here
        assert market.status()["symbols"] == {"NVDA": 1}
        market.release("NVDA")
        assert market._fake.unsubscribed == ["NVDA"]
        assert market.status()["symbols"] == {}

    def test_releasing_something_never_acquired_is_harmless(self, market):
        market.release("NVDA")                      # e.g. a disconnect after a failed acquire
        assert market.status()["symbols"] == {}

    def test_symbols_are_normalised(self, market):
        market.acquire("nvda")
        market.release("NvDa")
        assert market.status()["symbols"] == {}

    def test_releasing_drops_the_cached_tick(self, market):
        market.acquire("NVDA")
        market._last["NVDA"] = {"symbol": "NVDA", "price": 1.0, "received": time.time()}
        market.release("NVDA")
        # Otherwise the next reader of that symbol is handed a price from
        # whenever the previous one was last looking.
        assert market.latest("NVDA") is None


class TestTickFreshness:
    def test_unseen_symbol_reports_nothing(self, market):
        # None is the honest answer on a feed that prints a few percent of
        # volume — not an error, and not a reason to show a stale number.
        assert market.latest("NVDA") is None

    def test_a_fresh_tick_is_not_stale(self, market):
        market._last["NVDA"] = {"symbol": "NVDA", "price": 1.0, "received": time.time()}
        tick = market.latest("NVDA")
        assert tick and tick["stale"] is False and tick["age_s"] < 1

    def test_an_old_tick_is_marked_stale_rather_than_hidden(self, market):
        old = time.time() - stream_mod.TICK_STALE_AFTER_S - 1
        market._last["NVDA"] = {"symbol": "NVDA", "price": 1.0, "received": old}
        tick = market.latest("NVDA")
        # Still returned: the caller decides whether to show it greyed or drop
        # it, and "the last print was two minutes ago" is itself information.
        assert tick and tick["stale"] is True


class TestUnavailableUpstream:
    def test_no_credentials_means_no_live_data_not_an_error(self, monkeypatch):
        m = stream_mod._MarketStream()
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
        assert m.acquire("NVDA") is False
        assert m.status() == {"connected": False, "feed": "iex", "available": False, "symbols": {}}

    def test_a_failed_start_is_not_retried_on_every_request(self, monkeypatch):
        m = stream_mod._MarketStream()
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        m.acquire("NVDA")
        calls = []
        monkeypatch.setattr(stream_mod.log, "info", lambda *a, **k: calls.append(a))
        for _ in range(5):
            assert m.acquire("NVDA") is False
        # Already known to be unavailable; it must not re-probe (and re-log)
        # once per reader per reconnect.
        assert calls == []


class TestReconnectBackoff:
    """The SDK retries a refused connection with no delay; the wrapper puts
    one in — doubling, capped, reset on success — and quiets the SDK's
    per-attempt tracebacks meanwhile."""

    def test_schedule_doubles_from_two_seconds_and_caps_at_sixty(self):
        assert stream_mod.backoff_delay(0, jitter=False) == 0.0
        assert [stream_mod.backoff_delay(n, jitter=False) for n in (1, 2, 3, 4, 5)] == [2, 4, 8, 16, 32]
        assert stream_mod.backoff_delay(6, jitter=False) == 60
        assert stream_mod.backoff_delay(40, jitter=False) == 60

    def test_jitter_stays_within_a_quarter_either_way(self):
        for _ in range(200):
            d = stream_mod.backoff_delay(3)
            assert 6.0 <= d <= 10.0

    def test_start_ws_waits_after_failures_and_resets_on_success(self, monkeypatch):
        import asyncio
        pytest.importorskip("alpaca.data.live")
        cls = stream_mod._stream_class()
        s = cls("key", "secret")
        slept: list[float] = []

        async def fake_sleep(d):
            slept.append(d)
        monkeypatch.setattr(stream_mod.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(stream_mod, "backoff_delay", lambda n, jitter=True: float(n))

        outcomes = iter([ValueError("connection limit exceeded"), ValueError("connection limit exceeded"), None])

        async def base_start(self_):
            r = next(outcomes)
            if r:
                raise r
        parent = cls.__mro__[1]
        monkeypatch.setattr(parent, "_start_ws", base_start)

        for _ in range(2):
            with pytest.raises(ValueError):
                asyncio.run(s._start_ws())
        assert s.failures == 2
        assert s._quiet.suppressing is True
        assert slept == [1.0]                      # nothing before the first try, 1s before the second
        asyncio.run(s._start_ws())                 # third attempt connects
        assert slept == [1.0, 2.0]
        assert s.failures == 0
        assert s._quiet.suppressing is False

    def test_quiet_filter_drops_only_the_sdk_retry_noise(self):
        import logging
        q = stream_mod._QuietRetries()
        rec = lambda m: logging.LogRecord("alpaca.data.live.websocket", logging.ERROR, "", 0, m, None, None)
        assert q.filter(rec("error during websocket communication: connection limit exceeded")) is True
        q.suppressing = True
        assert q.filter(rec("error during websocket communication: connection limit exceeded")) is False
        assert q.filter(rec("data websocket error, restarting connection: HTTP 429")) is False
        assert q.filter(rec("starting data websocket connection")) is False
        assert q.filter(rec("something else entirely")) is True


class TestLiveMux:
    """2026-09-15: every live surface of a tab on one connection."""

    @staticmethod
    def _markets(monkeypatch):
        stock, crypto = stream_mod._MarketStream(), stream_mod._MarketStream(kind="crypto")
        for m in (stock, crypto):
            fake = FakeStream()
            fake.subscribe_quotes = lambda handler, *s: None
            fake.unsubscribe_quotes = lambda *s: None
            monkeypatch.setattr(m, "_ensure_running", lambda m=m, fake=fake: (setattr(m, "_stream", fake) or True)
                                if m._stream is None else True)
        return stock, crypto

    @staticmethod
    def _tick(market, sym, price, at):
        market._last[sym] = {"symbol": sym, "price": price, "size": 1, "at": at, "received": time.time()}

    def test_symbols_are_cleaned_deduplicated_and_ordered(self):
        from alphadesk.app.dashboard import stream_symbols
        assert stream_symbols("nvda, aapl,NVDA,brk.b,$$$,,aapl")[0] == ["NVDA", "AAPL", "BRK.B"]
        assert stream_symbols("btc/usd,eth-usd", extra="/")[0] == ["BTC/USD", "ETH-USD"]

    def test_one_connection_carries_trades_quotes_and_coins(self, monkeypatch):
        from alphadesk.providers.alpaca import coin_pair
        stock, crypto = self._markets(monkeypatch)
        mux = stream_mod.LiveMux(stock, crypto, ["NVDA", "BTC-USD"], ["AAPL", "NVDA"], ["ETH-USD", "NOTACOIN"],
                                 panel_push_s=5.0, coin_push_s=2.0, pair_of=coin_pair)
        hello = mux.open()
        assert hello["trades"] == {"NVDA": True, "BTC-USD": True}
        assert hello["quotes"]["symbols"] == ["AAPL", "NVDA"] and hello["crypto"]["products"] == ["ETH-USD"]
        # NVDA is charted AND a row: two references, one upstream subscription.
        assert stock.status()["symbols"] == {"NVDA": 2, "AAPL": 1}
        assert set(crypto.status()["symbols"]) == {"BTC/USD", "ETH/USD"}

        self._tick(stock, "NVDA", 212.5, "t1")
        self._tick(stock, "AAPL", 230.0, "t1")
        self._tick(crypto, "ETH/USD", 4000.0, "t1")
        frames = mux.frames(100.0)
        assert [f.split("\n")[0] for f in frames] == ["event: trade", "event: quotes", "event: crypto"]
        assert '"symbol": "NVDA"' in frames[0] and '"symbol": "ETH-USD"' in frames[2]

        # A new print is a new trade frame at once; the rows wait out their pace.
        self._tick(stock, "NVDA", 212.6, "t2")
        assert [f.split("\n")[0] for f in mux.frames(101.0)] == ["event: trade"]
        assert [f.split("\n")[0] for f in mux.frames(106.0)] == ["event: quotes"]
        assert mux.frames(107.0) == []                    # nothing new

    def test_quotes_past_the_cap_are_reported_not_refused(self, monkeypatch):
        from alphadesk.providers.alpaca import coin_pair
        stock, crypto = self._markets(monkeypatch)
        many = [f"S{i}" for i in range(stream_mod.LIVE_QUOTES_MAX + 5)]
        mux = stream_mod.LiveMux(stock, crypto, [], many, [], panel_push_s=5.0, coin_push_s=2.0, pair_of=coin_pair)
        hello = mux.open()
        assert len(hello["quotes"]["symbols"]) == stream_mod.LIVE_QUOTES_MAX
        assert hello["quotes"]["skipped"] == many[stream_mod.LIVE_QUOTES_MAX:]

    def test_close_hands_back_every_reference_and_no_key_is_not_live(self, monkeypatch):
        from alphadesk.providers.alpaca import coin_pair
        stock, crypto = self._markets(monkeypatch)
        mux = stream_mod.LiveMux(stock, crypto, ["NVDA"], ["NVDA", "AAPL"], ["BTC-USD"],
                                 panel_push_s=5.0, coin_push_s=2.0, pair_of=coin_pair)
        mux.open()
        released = []
        mux.close(lambda market, sym: (released.append(sym), market.release(sym)))
        assert sorted(released) == ["AAPL", "BTC/USD", "NVDA", "NVDA"]
        assert stock.status()["symbols"] == {} and crypto.status()["symbols"] == {}
        keyless = stream_mod.LiveMux(None, None, ["NVDA"], ["AAPL"], ["BTC-USD"],
                                     panel_push_s=5.0, coin_push_s=2.0, pair_of=coin_pair)
        hello = keyless.open()
        assert hello["trades"] == {"NVDA": False} and not hello["quotes"]["live"] and not hello["crypto"]["live"]
        assert keyless.frames(0.0) == []


class TestPlanFeed:
    """2026-09-13: a paid Alpaca key streams SIP; a free one IEX. The account
    holds one connection, so a plan change replaces the stream rather than
    opening a second one beside it."""

    def test_a_plan_change_replaces_the_accounts_one_connection(self, monkeypatch):
        stream_mod._streams.clear()
        closed = []
        monkeypatch.setattr(stream_mod._MarketStream, "shutdown", lambda self: closed.append(self.feed))
        free = stream_mod.for_key("k", "s", "stock", "iex")
        assert stream_mod.for_key("k", "s", "stock", "iex") is free
        paid = stream_mod.for_key("k", "s", "stock", "sip")
        assert paid is not free and paid.feed == "sip"
        import time as _t
        for _ in range(50):
            if closed:
                break
            _t.sleep(0.01)
        assert closed == ["iex"]
        stream_mod._streams.clear()


class TestLiveNews:
    """2026-09-15: the reader's real-time news on the tab's one connection."""

    def test_the_news_channel_tells_the_tab_when_stories_arrive(self, monkeypatch):
        from alphadesk.providers.alpaca import coin_pair
        news_market = stream_mod._MarketStream(kind="news")
        fake = SimpleNamespace(subscribe_news=lambda h, *s: None, unsubscribe_news=lambda *s: None)
        monkeypatch.setattr(news_market, "_ensure_running",
                            lambda: (setattr(news_market, "_stream", fake) or True) if news_market._stream is None else True)
        seq = {"u1": 4}
        mux = stream_mod.LiveMux(None, None, [], [], [], panel_push_s=5.0, coin_push_s=2.0, pair_of=coin_pair,
                                 news=news_market, news_owner="u1", news_seq=lambda owner: seq[owner])
        assert mux.open()["news"] is True
        assert news_market._owners == {"u1": 1} and news_market.status()["symbols"] == {"*": 1}
        assert mux.frames(0.0) == []                                   # nothing new since the tab opened
        seq["u1"] = 5
        frames = mux.frames(1.0)
        assert frames and frames[0].startswith("event: news") and '"seq": 5' in frames[0]
        assert mux.frames(2.0) == []
        mux.close(lambda market, sym: market.release(sym))
        assert news_market._owners == {} and news_market.status()["symbols"] == {}

    def test_a_streamed_story_is_delivered_to_every_watching_reader(self, monkeypatch):
        import asyncio
        from datetime import datetime, timezone
        from alphadesk.ingest import news
        delivered = []
        monkeypatch.setattr(news, "ingest_streamed", lambda owner, art: delivered.append((owner, art.id)))
        monkeypatch.setattr(stream_mod.threading, "Thread",
                            lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))
        m = stream_mod._MarketStream(kind="news")
        m.add_owner("u1")
        m.add_owner("u2")
        m.drop_owner("u2")
        story = SimpleNamespace(id=41, headline="Crude hits $106", url="https://x/41", symbols=["USO"],
                                created_at=datetime.now(timezone.utc), summary="", source="benzinga",
                                author="", content="<p>text</p>", images=[])
        asyncio.run(m._on_news(story))
        assert delivered == [("u1", "41")]


class TestHeldNewsConnection:
    """2026-09-17: the news socket is held for every active reader, with no
    browser tab. Held only while a tab subscribed, a reader away from the
    terminal saw a story no sooner than the next poll cycle."""

    @pytest.fixture
    def held(self, monkeypatch):
        made: dict[str, object] = {}

        def fake_for_user(uid):
            if uid == "nokey":
                return None                       # no Alpaca key: the poll is their feed
            m = made.get(uid)
            if m is None:
                m = stream_mod._MarketStream(kind="news")
                fake = SimpleNamespace(subscribe_news=lambda h, *s: None, unsubscribe_news=lambda *s: None)
                monkeypatch.setattr(m, "_ensure_running",
                                    lambda m=m, fake=fake: (setattr(m, "_stream", fake) or True)
                                    if m._stream is None else True)
                made[uid] = m
            return m

        monkeypatch.setattr(stream_mod, "news_for_user", fake_for_user)
        stream_mod._news_holds.clear()
        yield made
        stream_mod._news_holds.clear()

    def test_an_active_reader_is_subscribed_without_a_tab(self, held):
        assert stream_mod.hold_news_for(["u1"]) == (1, 0)
        market = held["u1"]
        assert market._owners == {"u1": 1} and market.status()["symbols"] == {"*": 1}

    def test_holding_again_takes_no_second_reference(self, held):
        stream_mod.hold_news_for(["u1"])
        stream_mod.hold_news_for(["u1"])
        stream_mod.hold_news_for(["u1"])
        market = held["u1"]
        assert market._owners == {"u1": 1} and market.status()["symbols"] == {"*": 1}

    def test_a_dropped_socket_comes_back_on_the_next_cycle(self, held):
        stream_mod.hold_news_for(["u1"])
        market = held["u1"]
        market._stream = None                     # the socket went away
        stream_mod.hold_news_for(["u1"])
        assert market._stream is not None
        assert market.status()["symbols"] == {"*": 1}      # and no extra reference

    def test_a_reader_gone_inactive_is_released(self, held):
        stream_mod.hold_news_for(["u1", "u2"])
        market1, market2 = held["u1"], held["u2"]
        assert stream_mod.hold_news_for(["u2"]) == (1, 1)
        assert market1._owners == {} and market1.status()["symbols"] == {}
        assert market2._owners == {"u2": 1}

    def test_a_reader_without_an_alpaca_key_is_not_held(self, held):
        assert stream_mod.hold_news_for(["nokey"]) == (0, 0)
        assert stream_mod._news_holds == {}

    def test_streaming_unavailable_leaves_no_dangling_owner(self, held, monkeypatch):
        market = stream_mod._MarketStream(kind="news")
        monkeypatch.setattr(market, "_ensure_running", lambda: False)   # no SDK, no keys
        monkeypatch.setattr(stream_mod, "news_for_user", lambda uid: market)
        assert stream_mod.hold_news_for(["u1"]) == (0, 0)
        assert market._owners == {}
