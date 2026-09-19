"""Alpaca's plan, noticed from its own refusals (2026-09-13, measured on a
free key): recent SIP is refused with "subscription does not permit querying
recent SIP data", OPRA with "OPRA agreement is not signed". A paid key gets
both, and quotes, charts and chains then come off the real-time feeds."""

from types import SimpleNamespace

from alphadesk.providers.alpaca import AlpacaPrices


class _Refused(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.status_code = 403


class _Stock:
    def __init__(self, paid):
        self.paid, self.probes, self.snapshot_feeds = paid, 0, []

    def get_stock_latest_trade(self, req):
        self.probes += 1
        if not self.paid:
            raise _Refused('{"message":"subscription does not permit querying recent SIP data"}')
        return {"SPY": SimpleNamespace(price=500.0)}

    def get_stock_snapshot(self, req):
        self.snapshot_feeds.append(req.feed.value)
        return {}


class _Option:
    """Stands in for the options snapshot endpoint."""
    def __init__(self, paid):
        self.paid, self.feeds = paid, []

    def snapshots(self, sym, feed, **filters):
        self.feeds.append(feed)
        if feed == "opra" and not self.paid:
            raise _Refused('{"message":"OPRA agreement is not signed"}')
        return {}


def _vendor(paid):
    a = AlpacaPrices(api_key="k", api_secret="s")
    a._clients["stock"], a._clients["option"] = _Stock(paid), _Option(paid)
    a._option_snapshots = a._clients["option"].snapshots
    return a


def test_a_free_key_is_iex_and_asked_once(monkeypatch):
    monkeypatch.setattr("alphadesk.providers.alpaca.time.sleep", lambda s: None)
    a = _vendor(paid=False)
    assert a.stock_feed() == "iex" and a.stock_feed() == "iex"
    assert a._clients["stock"].probes == 3                                  # refused on every try, then held
    assert a.plan() == {"realtime": False, "stocks": "iex", "options": None, "chart_delay_minutes": 15}
    assert a._snapshots(["AAPL"], a.stock_feed())[1] == "iex"
    assert a._clients["stock"].snapshot_feeds == ["iex"]


def test_a_paid_key_is_sip_for_snapshots():
    a = _vendor(paid=True)
    assert a.stock_feed() == "sip" and a.plan()["realtime"] is True and a._recent_sip is True
    assert a._snapshots(["AAPL"], a.stock_feed())[1] == "sip"
    assert a._clients["stock"].snapshot_feeds == ["sip"]


def test_the_chain_tries_opra_once_then_stays_indicative():
    a = _vendor(paid=False)
    assert a._chain_snapshots("SPY", "2026-09-18")[1] == "indicative"
    assert a._chain_snapshots("SPY", "2026-09-18")[1] == "indicative"
    assert a._clients["option"].feeds == ["opra", "indicative", "indicative"]
    assert a.plan()["options"] == "indicative"
    paid = _vendor(paid=True)
    assert paid._chain_snapshots("SPY", "2026-09-18")[1] == "opra"


def test_the_chart_delay_is_only_named_while_the_tape_prints():
    from datetime import datetime
    from alphadesk.config import ET
    from alphadesk.providers.alpaca import sip_session_open
    assert sip_session_open(datetime(2026, 9, 14, 10, 0, tzinfo=ET))          # Monday morning
    assert sip_session_open(datetime(2026, 9, 14, 4, 0, tzinfo=ET))
    assert not sip_session_open(datetime(2026, 9, 14, 20, 30, tzinfo=ET))     # overnight is Blue Ocean's, live
    assert not sip_session_open(datetime(2026, 9, 13, 12, 0, tzinfo=ET))      # Sunday



class _Flaky(_Stock):
    """A paid key minutes after the upgrade: the first `refusals` SIP calls
    are refused, the rest answer."""
    def __init__(self, refusals):
        super().__init__(paid=True)
        self.refusals = refusals

    def _maybe_refuse(self):
        if self.refusals > 0:
            self.refusals -= 1
            raise _Refused('{"message":"subscription does not permit querying recent SIP data"}')

    def get_stock_latest_trade(self, req):
        self.probes += 1
        self._maybe_refuse()
        return {"SPY": SimpleNamespace(price=500.0)}

    def get_stock_snapshot(self, req):
        self.snapshot_feeds.append(req.feed.value)
        if req.feed.value == "sip":
            self._maybe_refuse()
        return {}


def test_a_lone_refusal_on_a_paid_key_is_retried_not_believed(monkeypatch):
    monkeypatch.setattr("alphadesk.providers.alpaca.time.sleep", lambda s: None)
    a = AlpacaPrices(api_key="k", api_secret="s")
    a._clients["stock"] = _Flaky(refusals=2)
    assert a.stock_feed() == "sip"                                          # third try answered
    a._clients["stock"] = _Flaky(refusals=1)
    assert a._snapshots(["AAPL"], "sip")[1] == "sip"


def test_snapshots_refused_on_every_try_fall_back_to_iex_for_that_call(monkeypatch):
    monkeypatch.setattr("alphadesk.providers.alpaca.time.sleep", lambda s: None)
    a = AlpacaPrices(api_key="k", api_secret="s")
    a._clients["stock"] = _Flaky(refusals=3)
    snaps, feed = a._snapshots(["AAPL"], "sip")
    assert feed == "iex" and a._clients["stock"].snapshot_feeds == ["sip", "sip", "sip", "iex"]


def test_a_delayed_series_carries_iex_closes_after_its_last_bar_and_nothing_else(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from alphadesk.providers import alpaca as mod
    a = AlpacaPrices(api_key="k", api_secret="s")
    t0 = datetime(2026, 9, 14, 14, 0, tzinfo=timezone.utc)
    sip = [{"ts": t0 + timedelta(minutes=i), "open": 100, "high": 101, "low": 99, "close": 100 + i * 0.1, "volume": 5000} for i in range(40)]
    iex_rows = [{"ts": t0 + timedelta(minutes=i), "open": 1, "high": 1, "low": 1, "close": 200 + i, "volume": 3} for i in range(38, 45)]
    asked = []

    def fake_bars(symbols, spec, start, end=None, feed="sip"):
        asked.append(feed)
        if feed == "iex":
            return {"AAPL": iex_rows}, 0
        if feed == "sip":
            return {"AAPL": sip}, 15
        return {"AAPL": []}, 0
    monkeypatch.setattr(a, "stock_bars", fake_bars)
    monkeypatch.setattr(mod, "sip_session_open", lambda now: True)
    out = a.chart_series("AAPL", range_key="1D", interval="1m")
    assert out["delay_minutes"] == 15 and out["realtime"] is False
    last = out["bars"][-1]["t"]
    assert [p["t"] > last for p in out["provisional"]] == [True] * 5            # 39 is the last bar; 40..44 follow
    assert set(out["provisional"][0]) == {"t", "c"} and out["provisional"][0]["c"] == 240
    assert "iex" in asked

    monkeypatch.setattr(mod, "sip_session_open", lambda now: False)
    out = a.chart_series("AAPL", range_key="1D", interval="1m")
    assert "provisional" not in out and "delay_minutes" not in out


def test_daily_history_translates_share_classes_and_drops_what_alpaca_does_not_list(monkeypatch):
    from datetime import datetime, timezone
    from alphadesk.providers.base import ProviderError
    a = AlpacaPrices(api_key="k", api_secret="s")
    asked = []

    def fake_bars(symbols, spec, start, end=None, feed="sip"):
        asked.append(list(symbols))
        if "ACP.PA" in symbols:
            raise ProviderError('alpaca bars failed: {"message":"invalid symbol: ACP.PA"}')
        bar = {"ts": datetime(2026, 9, 11, tzinfo=timezone.utc), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
        return {s: [bar] for s in symbols}, 0
    monkeypatch.setattr(a, "stock_bars", fake_bars)
    got = a.daily_history(["LEN-B", "ACP-PA", "AAPL", "ACP.PA"])
    assert sorted(got) == ["AAPL", "LEN-B"]                                  # keyed as asked
    # the preferred series is never asked; a symbol Alpaca still refuses is dropped and the batch asked again
    assert asked == [["AAPL", "ACP.PA", "LEN.B"], ["AAPL", "LEN.B"]]


class _Trading:
    """The trading API: one listing of every asset, or one asset at a time."""

    def __init__(self, listed):
        self.listed, self.listings, self.lookups = listed, 0, []

    def get(self, path, params):
        assert path == "/assets" and params == {"status": "active", "asset_class": "us_equity"}
        self.listings += 1
        return [{"symbol": s, "name": n, "exchange": "NASDAQ"} for s, n in self.listed.items()]

    def get_asset(self, sym):
        self.lookups.append(sym)
        return SimpleNamespace(name=f"{sym} Inc", exchange=SimpleNamespace(value="NYSE"))


def _named(listed):
    p = AlpacaPrices(api_key="k", api_secret="s")
    trading = _Trading(listed)
    p._clients["paper"] = trading
    return p, trading


def test_a_long_list_is_named_from_one_listing_not_a_request_per_symbol():
    """2026-09-15: ~140 movers symbols looked up one by one took 6.7s on a
    fresh process and ran past the trading API's 200 requests a minute."""
    listed = {f"S{i}": f"Company {i}" for i in range(200)}
    p, trading = _named(listed)
    got = p.names([f"s{i}" for i in range(140)])
    assert trading.listings == 1 and trading.lookups == []
    assert got["S7"] == ("Company 7", "NASDAQ")
    p.names([f"S{i}" for i in range(140, 200)])          # already listed: no request
    assert trading.listings == 1 and trading.lookups == []


def test_a_few_symbols_look_up_alone_and_an_unlisted_one_in_a_long_list_is_not_chased():
    p, trading = _named({f"S{i}": f"Company {i}" for i in range(20)})
    assert p.names(["NVDA"]) == {"NVDA": ("NVDA Inc", "NYSE")}
    assert trading.listings == 0 and trading.lookups == ["NVDA"]
    got = p.names([f"S{i}" for i in range(20)] + ["GONE"])
    assert trading.listings == 1 and got["GONE"] == (None, None) and trading.lookups == ["NVDA"]


def test_two_lists_asking_at_once_share_one_listing():
    import threading
    listed = {f"S{i}": f"Company {i}" for i in range(100)}
    p, trading = _named(listed)
    slow = trading.get
    trading.get = lambda path, params: (__import__("time").sleep(0.1), slow(path, params))[1]
    threads = [threading.Thread(target=p.names, args=([f"S{i}" for i in range(k, k + 50)],)) for k in (0, 50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert trading.listings == 1


def test_the_pool_is_the_most_dollars_traded_lately_not_the_most_shares():
    from alphadesk.providers.alpaca import rank_dollar_volume
    bars = {
        "CHEAP": [{"c": 6.0, "v": 100_000_000}] * 5,        # $600M a day, most shares
        "DEAR": [{"c": 900.0, "v": 5_000_000}] * 5,          # $4.5B a day
        "MID": [{"c": 50.0, "v": 20_000_000}] * 3,           # $1B a day, three sessions
        "EMPTY": [],
    }
    assert rank_dollar_volume(bars, 5, 700e6, 10) == ["DEAR", "MID"]       # a floor, not a count
    assert rank_dollar_volume(bars, 5, 0, 1) == ["DEAR"]                    # and at most max_size
    # Only the last `sessions` bars count: an old busy day does not carry it.
    bars["FADED"] = [{"c": 100.0, "v": 90_000_000}] + [{"c": 100.0, "v": 1_000}] * 5
    assert "FADED" not in rank_dollar_volume(bars, 5, 1e6, 10)
    # A liquid leveraged fund below the old top-1,000 cut (~$117M) is in (2026-09-15: CRWL ~$32M).
    bars["CRWL"] = [{"c": 87.0, "v": 365_000}] * 5
    assert "CRWL" in rank_dollar_volume(bars, 5, 10e6, 4000)


def test_rows_rank_by_todays_dollars_and_a_session_not_yet_open_stands_whole():
    from datetime import date
    from alphadesk.providers.alpaca import snapshot_dollar_rows
    snaps = {
        "NVDA": {"latestTrade": {"p": 212.5}, "dailyBar": {"t": "2026-09-15T04:00:00Z", "c": 212.0, "v": 36_000_000, "vw": 211.0},
                 "prevDailyBar": {"c": 218.29}},
        "VEEA": {"latestTrade": {"p": 5.5}, "dailyBar": {"t": "2026-09-15T04:00:00Z", "c": 5.4, "v": 150_000_000, "vw": 5.0},
                 "prevDailyBar": {"c": 2.29}},
        # Yesterday's bar before today's open: its close and change, not the premarket print.
        "OLD": {"latestTrade": {"p": 11.0}, "dailyBar": {"t": "2026-09-14T04:00:00Z", "c": 10.0, "v": 10_000_000, "vw": 10.0},
                "prevDailyBar": {"c": 8.0}},
        "NOVOL": {"latestTrade": {"p": 1.0}, "dailyBar": {"t": "2026-09-15T04:00:00Z", "c": 1.0, "v": 0}},
    }
    rows = snapshot_dollar_rows(snaps, date(2026, 9, 15))
    assert [r["symbol"] for r in rows] == ["NVDA", "VEEA", "OLD"]
    assert rows[0]["turnover"] == 211.0 * 36_000_000 and rows[0]["price"] == 212.5
    assert rows[0]["change_pct"] == round(100 * (212.5 / 218.29 - 1), 2)
    assert rows[2]["price"] == 10.0 and rows[2]["change_pct"] == 25.0


def test_etf_movers_are_market_wide_once_the_pool_is_priced_and_the_fixed_list_until_then():
    p = AlpacaPrices(api_key="k", api_secret="s")
    pool = [
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "price": 757.0, "change_pct": -0.5, "volume": 12_000_000, "turnover": 9.1e9},
        {"symbol": "NVD", "name": "GraniteShares 2x Short NVDA Daily ETF", "price": 4.2, "change_pct": -1.2, "volume": 95_000_000, "turnover": 4.0e8},
    ]
    p.pool_movers = lambda: pool
    got = p.category_movers("etfs")
    assert got["funds"] == "only"
    tabs = {t["id"]: [r["symbol"] for r in t["rows"]] for t in got["tabs"]}
    assert tabs["most_active"] == ["NVD", "SPY"] and tabs["dollar_volume"] == ["SPY", "NVD"]
    assert tabs["losers"] == ["NVD", "SPY"] and tabs["gainers"] == []

    p.pool_movers = lambda: None
    p.listed_quotes = lambda universe: [{"symbol": "SPY", "price": 757.0, "change_pct": -0.5, "volume": 1, "name": "S&P 500"}]
    fixed = p.category_movers("etfs")
    assert "funds" not in fixed and [t["id"] for t in fixed["tabs"]][0] == "all"


def test_bars_are_split_adjusted_at_every_interval():
    """2026-09-15: CRWD's 4-for-1 split drew as a cliff on intraday charts,
    which were asked unadjusted while daily bars were adjusted."""
    seen = []

    class _Bars:
        def get_stock_bars(self, req):
            seen.append((req.timeframe.unit_value.value if hasattr(req.timeframe, "unit_value") else str(req.timeframe), req.adjustment))
            return SimpleNamespace(data={})

    p = AlpacaPrices(api_key="k", api_secret="s")
    p._clients["stock"] = _Bars()
    p._recent_sip = True
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc) - timedelta(days=5)
    for iv in ("1m", "1h", "1d"):
        p.stock_bars("CRWD", p._INTERVALS[iv], start, feed="sip")
    assert [str(adj.value if hasattr(adj, "value") else adj) for _, adj in seen] == ["split", "split", "split"]



def test_option_mover_rows_count_only_todays_session_and_price_the_premium():
    from alphadesk.providers.alpaca import option_mover_rows
    snaps = {
        "SPY260918C00760000": {"dailyBar": {"t": "2026-09-15T04:00:00Z", "v": 90000, "c": 2.0}, "prevDailyBar": {"c": 1.6},
                               "latestTrade": {"p": 2.1}, "impliedVolatility": 0.142},
        "SPY260918P00700000": {"dailyBar": {"t": "2026-09-12T04:00:00Z", "v": 5000, "c": 0.5}, "latestTrade": {"p": 0.5}},   # last traded Friday
        "SPY260918P00740000": {"dailyBar": {"t": "2026-09-15T04:00:00Z", "v": 0, "c": 1.0}},                              # no trades today
        "NOTANOCC": {"dailyBar": {"t": "2026-09-15T04:00:00Z", "v": 10, "c": 1.0}},
    }
    rows = option_mover_rows("SPY", snaps)
    assert [r["symbol"] for r in rows] == ["SPY260918C00760000"]
    r = rows[0]
    assert r["display"] == "SPY 760C 09-18" and r["underlying"] == "SPY" and r["expiry"] == "2026-09-18"
    assert r["turnover"] == 90000 * 2.1 * 100 and r["volatility"] == 14.2 and r["change_pct"] == 31.25


def test_crypto_runs_largest_coins_first_and_says_its_volume_is_one_venues():
    p = AlpacaPrices(api_key="k", api_secret="s")
    p._trading = lambda call: [SimpleNamespace(symbol=s, tradable=True) for s in ("DOGE/USD", "BTC/USD", "ZZZ/USD", "ETH/USD")]
    p.quotes = lambda syms: {s: {"price": 1.0, "change_pct": 0.5, "volume": 1} for s in syms}
    p._client = lambda kind: (_ for _ in ()).throw(RuntimeError("no bars in this test"))
    got = p.category_movers("crypto")
    assert got["venue_volume"] is True
    assert [r["symbol"] for r in got["tabs"][0]["rows"]] == ["BTC-USD", "ETH-USD", "DOGE-USD", "ZZZ-USD"]


def test_crypto_change_is_over_the_last_24_hours_not_since_the_daily_close():
    from datetime import datetime, timedelta, timezone
    from alphadesk.providers.alpaca import rolling_change
    now = datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc)
    bars = [{"ts": now - timedelta(hours=26) + timedelta(minutes=15 * i), "close": 100.0 + i} for i in range(104)]
    # The bar ending exactly 24 hours ago started at 16:45 yesterday: i = 7, close 107.
    assert rolling_change(107.0 * 1.1, bars, now, 15) == 10.0
    assert rolling_change(50.0, [], now, 15) is None                        # no bar ended in time
    assert rolling_change(None, bars, now, 15) is None
    late = [b for b in bars if b["ts"] >= now - timedelta(hours=20)]      # a coin with no trade before
    assert rolling_change(120.0, late, now, 15) is None


def test_option_movers_read_the_index_funds_and_todays_most_traded_names():
    from alphadesk.providers.alpaca import option_underlyings
    pool = [{"symbol": s} for s in ("SPY", "MU", "NVDA", "QQQ", "META", "COIN", "TSLA")]
    assert option_underlyings(pool, 4) == ["SPY", "QQQ", "IWM", "MU", "NVDA", "META", "COIN"]


def test_option_movers_fall_back_to_the_fixed_markets_until_the_pool_is_priced():
    from alphadesk.providers.prices import OPTION_UNDERLYINGS
    p = AlpacaPrices(api_key="k", api_secret="s")
    asked = []
    p.pool_movers = lambda: None
    p._chain_snapshots = lambda u, **f: (asked.append(u), ({}, "opra"))[1]
    assert p.option_movers() is None                        # no contracts traded in this test
    assert asked and set(asked) == set(OPTION_UNDERLYINGS)
    asked.clear()
    p.pool_movers = lambda: [{"symbol": "MU"}, {"symbol": "COIN"}]
    p.option_movers()
    assert set(asked) == {"SPY", "QQQ", "IWM", "MU", "COIN"}


def test_gainers_and_losers_take_the_pool_and_the_screeners_rows_together():
    """2026-09-15: from Alpaca's top 50 alone, five gainers survived the floors."""
    from alphadesk.providers.alpaca import merge_movers
    screener = [{"symbol": "VEEA", "change_pct": 150.0}, {"symbol": "TINY", "change_pct": 90.0}, {"symbol": "NVDA", "change_pct": 0.4}]
    pool = [{"symbol": "DELL", "change_pct": 8.2, "turnover": 3e9}, {"symbol": "NVDA", "change_pct": 0.42, "turnover": 7.8e9},
            {"symbol": "MSFT", "change_pct": -1.1, "turnover": 2.5e9}]
    gainers = merge_movers(screener, pool, up=True)
    assert [r["symbol"] for r in gainers] == ["VEEA", "TINY", "DELL", "NVDA"]
    assert next(r for r in gainers if r["symbol"] == "NVDA")["turnover"] == 7.8e9      # the pool's row wins
    assert [r["symbol"] for r in merge_movers([], pool, up=False)] == ["MSFT"]


def test_nasdaq_fifth_letter_share_types_are_not_common_stock():
    from alphadesk.providers.alpaca import common_stock_symbol
    assert all(common_stock_symbol(s) for s in ("NVDA", "VEEA", "GOOGL", "F"))
    assert not any(common_stock_symbol(s) for s in ("ACMEW", "ACMER", "ACMEU", "NFEGP", "ABCDQ", "BRK.B"))


def test_option_movers_ask_each_chain_for_strikes_near_the_price_to_45_days():
    """2026-09-15: every strike to 45 days was ~76,000 contracts and 5-8s a build."""
    from datetime import date, timedelta
    import alphadesk.providers.alpaca as al
    p = AlpacaPrices(api_key="k", api_secret="s")
    asked = {}
    p.pool_movers = lambda: [{"symbol": "COIN", "price": 200.0}]
    p._chain_snapshots = lambda u, **f: (asked.__setitem__(u, f), ({}, "opra"))[1]
    p.option_movers()
    assert asked["COIN"]["strike_price_gte"] == 150.0 and asked["COIN"]["strike_price_lte"] == 250.0
    assert asked["COIN"]["expiration_date_lte"] == (date.today() + timedelta(days=al.OPTION_MOVERS_DAYS)).isoformat()
    assert "strike_price_gte" not in asked["SPY"]                    # no price in hand: the whole chain


def test_a_share_class_is_spelled_with_a_dot_for_options():
    """Alpaca refuses BRK-A outright — "invalid underlying symbols" — and
    the Options page answered 500 for every dash-class ticker (2026-09-15)."""
    from alphadesk.providers.alpaca import option_underlying
    assert option_underlying("BRK-B") == "BRK.B"
    assert option_underlying("brk-a") == "BRK.A"
    assert option_underlying("SPY") == "SPY"


def test_a_symbol_the_vendor_lists_no_options_for_is_not_a_failure():
    from alphadesk.providers.alpaca import _invalid_symbol
    assert _invalid_symbol(Exception('{"code":42210000,"message":"invalid underlying symbols: BRK-A"}')) == "BRK-A"
    assert _invalid_symbol(Exception('{"message":"invalid symbol: ACP-PA"}')) == "ACP-PA"
    assert _invalid_symbol(Exception("some other failure")) is None


def test_a_thin_history_page_reaches_further_back_until_it_can_fill_the_screen(monkeypatch):
    """Zoomed out, the chart's left side grew by a sliver at a time: a page
    was one range-span of CALENDAR time, and a thinly traded name has only
    dozens of minute bars in four days (VEEA: 62, then 83, then 39, measured
    2026-09-15). The page now widens until it covers the blank the chart
    asked about."""
    from datetime import datetime, timedelta, timezone
    a = AlpacaPrices(api_key="k", api_secret="s")
    cursor = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)
    windows = []

    def fake_bars(symbols, spec, start, end=None, feed="sip"):
        if feed != "sip":
            return {"VEEA": []}, 0
        windows.append(round((cursor - start).total_seconds() / 86400))
        # About 20 bars a day: four calendar days is a sliver, 32 is a page.
        span = (cursor - start).days
        rows = [{"ts": start + timedelta(minutes=i * 7), "open": 1, "high": 1,
                 "low": 1, "close": 1, "volume": 10} for i in range(span * 20)]
        return {"VEEA": rows}, 0
    monkeypatch.setattr(a, "stock_bars", fake_bars)

    out = a.chart_series("VEEA", range_key="1D", interval="1m", before=cursor, need=600)
    # 4 days is thin, so is 8 and 16; 32 days clears the 600-bar floor.
    assert windows[:4] == [4, 8, 16, 32]
    assert len(out["bars"]) >= 600

    windows.clear()
    a.chart_series("VEEA", range_key="1D", interval="1m", before=cursor, need=40)
    assert windows == [4, 8, 16, 32]          # never below the floor of a drawable page

    # A liquid name is answered by the first window and asked nothing more.
    def dense_bars(symbols, spec, start, end=None, feed="sip"):
        if feed != "sip":
            return {"NVDA": []}, 0
        windows.append(round((cursor - start).total_seconds() / 86400))
        return {"NVDA": [{"ts": start + timedelta(minutes=i), "open": 1, "high": 1,
                          "low": 1, "close": 1, "volume": 9} for i in range(2400)]}, 0
    monkeypatch.setattr(a, "stock_bars", dense_bars)
    windows.clear()
    a.chart_series("NVDA", range_key="1D", interval="1m", before=cursor, need=1_800)
    assert windows == [4]


def test_a_vendor_at_its_floor_is_not_asked_five_times(monkeypatch):
    """A window reaching past the feed's earliest bar answers the same rows
    however far back it asks: that is the end of the history, not a reason
    to keep widening."""
    from datetime import datetime, timedelta, timezone
    a = AlpacaPrices(api_key="k", api_secret="s")
    cursor = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)
    t0 = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)
    tries = []

    def floored(symbols, spec, start, end=None, feed="sip"):
        if feed != "sip":
            return {"VEEA": []}, 0
        tries.append(start)
        return {"VEEA": [{"ts": t0 + timedelta(minutes=i), "open": 1, "high": 1,
                          "low": 1, "close": 1, "volume": 2} for i in range(30)]}, 0
    monkeypatch.setattr(a, "stock_bars", floored)
    out = a.chart_series("VEEA", range_key="1D", interval="1m", before=cursor, need=2_000)
    assert len(tries) == 2                    # the second brought nothing new
    assert len(out["bars"]) == 30
