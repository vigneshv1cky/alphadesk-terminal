"""A past session's movers (2026-09-26, #87).

Both tests here exist because the first working version shipped a wrong
number to the TOP of a gainers list, which is the worst place for one.
"""

from datetime import date, timedelta

import pytest

from alphadesk.ingest import movers


@pytest.fixture(autouse=True)
def _isolated_ledger(store):
    """Finished sessions are recorded now, so no test may write to a real ledger."""


class _Bar(dict):
    """A daily bar shaped as the router hands it over."""
    def __init__(self, day: str, close: float, volume: float = 1000.0):
        import datetime as dt
        super().__init__(ts=dt.datetime.fromisoformat(day + "T04:00:00+00:00"),
                         open=close, high=close, low=close, close=close, volume=volume)


class _Router:
    owner = "test"
    connected = ["polygon"]

    def __init__(self, bars=None):
        self._bars = bars or {}

    def get(self, method, *args, **kwargs):
        if method == "daily_history":
            return {s: self._bars.get(s, []) for s in args[0]}
        return None


def test_exchange_test_symbols_are_not_securities():
    # ZVZZT closed at 25.12 with an 89% "gain" and sat third among the day's
    # gainers in the first list this produced. It is Nasdaq's test ticker.
    for sym in ("ZVZZT", "ZWZZT", "ZXZZT", "ZEXIT", "ATEST", "NTEST"):
        assert movers._TEST_SYMBOL.match(sym), sym
    for sym in ("ZM", "Z", "ZS", "ZTS", "AAPL", "ZIM", "ZUMZ"):
        assert not movers._TEST_SYMBOL.match(sym), sym


def test_a_move_below_the_threshold_is_never_second_guessed():
    # The check costs a vendor call, so an ordinary session must not pay it.
    rows = [movers._row("AAPL", 250.0, 1.4, 1_000_000)]
    out, dropped = movers._verify_extremes(_Router(), rows, "2026-09-24", "2026-09-25")
    assert out == rows and dropped == 0


def test_a_split_basis_error_is_corrected_from_the_second_source():
    # Tutor Perini, measured: the whole-market day said +406.45% because its
    # previous close was on a pre-split basis. Its real move was 83.32 to
    # 83.97, and the per-symbol bars carry that.
    rows = [movers._row("TPC", 83.97, 406.45, 224_651)]
    router = _Router({"TPC": [_Bar("2026-09-24", 83.32), _Bar("2026-09-25", 83.97)]})
    out, dropped = movers._verify_extremes(router, rows, "2026-09-24", "2026-09-25")
    assert dropped == 0
    assert out[0]["change_pct"] == pytest.approx(0.78, abs=0.05)


def test_a_real_move_survives_the_check_unchanged():
    # Dropping every large move would have deleted the day's real ones.
    rows = [movers._row("MSGY", 8.07, 309.64, 56_134_191)]
    router = _Router({"MSGY": [_Bar("2026-09-24", 1.97), _Bar("2026-09-25", 8.07)]})
    out, dropped = movers._verify_extremes(router, rows, "2026-09-24", "2026-09-25")
    assert dropped == 0 and out[0]["change_pct"] == pytest.approx(309.64, abs=0.5)


def test_an_unverifiable_extreme_is_dropped():
    # No second source for a 400% claim means it does not go near the top of
    # a list someone reads for what moved.
    rows = [movers._row("WEIRD", 50.0, 402.0, 10_000)]
    out, dropped = movers._verify_extremes(_Router(), rows, "2026-09-24", "2026-09-25")
    assert out == [] and dropped == 1


def test_a_vendor_failure_is_not_a_verdict():
    class _Angry(_Router):
        def get(self, *a, **k):
            raise RuntimeError("vendor down")
    rows = [movers._row("MSGY", 8.07, 309.64, 1000)]
    out, dropped = movers._verify_extremes(_Angry(), rows, "2026-09-24", "2026-09-25")
    assert out == rows and dropped == 0


def test_a_weekend_is_never_asked_for():
    """Stepping back must not spend a request on a day that cannot be one."""
    asked: list[str] = []

    class _Counting(_Router):
        def get(self, method, *args, **kwargs):
            if method == "market_day":
                asked.append(args[0])
            return None

    # From a Monday, the first candidate is Sunday and the second Saturday.
    monday = date(2026, 9, 21)
    movers._cache.clear()
    movers.previous_session(_Counting(), monday.isoformat())
    for day in asked:
        assert date.fromisoformat(day).weekday() < 5, f"asked about a weekend: {day}"


def test_which_categories_can_be_asked_about_a_past_session():
    # Indices, currencies and bonds come from today-only endpoints.
    assert movers.SESSION_CATEGORIES == ("stocks", "etfs", "options", "crypto")
    with pytest.raises(KeyError):
        movers.session_movers("currencies", (date.today() - timedelta(days=1)).isoformat())


def test_a_refused_request_is_never_a_closed_market():
    """The reader's actual bug: Polygon's free plan allows five requests a
    minute and answers the sixth with 429. That arrived as a None, which the
    router reads as "does not carry this surface", which this module printed
    as "the market did not open on 2026-09-23" — a Wednesday. The reader
    concluded the history stopped there."""
    from alphadesk.providers.base import NeedsKey

    class _RateLimited:
        owner = "test"
        connected = ["polygon"]

        def ask(self, method, *a, **k):
            raise NeedsKey("market_day", failed={"polygon": "HTTP 429 Too Many Requests"})

    movers._cache.clear()
    with pytest.raises(movers.VendorRefused) as exc:
        movers._market_day(_RateLimited(), "2026-09-23")
    assert "429" in str(exc.value)


def test_a_refusal_is_not_cached():
    """A minute's rate limit must not become six hours of a day that looks
    shut, so the failure path must never write to the cache."""
    from alphadesk.providers.base import NeedsKey

    class _Flaky:
        owner = "test"
        connected = ["polygon"]

        def __init__(self):
            self.calls = 0

        def ask(self, method, *a, **k):
            self.calls += 1
            if self.calls == 1:
                raise NeedsKey("market_day", failed={"polygon": "HTTP 429"})
            return {"AAPL": {"close": 1.0, "volume": 1}}

    movers._cache.clear()
    r = _Flaky()
    with pytest.raises(movers.VendorRefused):
        movers._market_day(r, "2026-09-23")
    assert movers._market_day(r, "2026-09-23") == {"AAPL": {"close": 1.0, "volume": 1}}


def test_no_vendor_at_all_still_asks_for_a_key():
    """A refusal and an absence are different, and so are their answers."""
    from alphadesk.providers.base import NeedsKey

    class _Unkeyed:
        owner = "test"
        connected = []

        def ask(self, method, *a, **k):
            raise NeedsKey("market_day")

    movers._cache.clear()
    with pytest.raises(NeedsKey):
        movers._market_day(_Unkeyed(), "2026-09-23")


def test_a_shut_market_is_an_empty_answer_not_a_missing_one():
    class _Holiday:
        owner = "test"
        connected = ["polygon"]

        def ask(self, method, *a, **k):
            return {}

    movers._cache.clear()
    assert movers._market_day(_Holiday(), "2026-12-25") == {}


def _rows_as_tabs(symbol: str) -> list[dict]:
    return [{"id": "gainers", "rows": [movers._row(symbol, 100.0, 1.0, 1000)]}]


def test_a_past_session_is_measured_on_its_own_twenty_days():
    """THE WHOLE POINT OF THE COLUMN (2026-09-27, the reader: "in stock and
    etf movers, liquidity and volatility are blank — for previous").

    Bars are fetched ending NOW, so a past session's window has to be cut
    back to it. Here the sessions up to the 24th are dead flat and the ones
    after it swing 100%: measured correctly the volatility is nil, and a
    window that leaked past the day would be enormous."""
    flat = [_Bar(f"2026-09-{d:02d}", 100.0, 1000) for d in range(11, 25)]
    wild = [_Bar("2026-09-25", 200.0, 1000), _Bar("2026-09-26", 100.0, 1000),
            _Bar("2026-09-29", 200.0, 1000), _Bar("2026-09-30", 100.0, 1000)]
    tabs = _rows_as_tabs("FLAT")
    movers._enrich_session_stats(_Router({"FLAT": flat + wild}), tabs, "2026-09-24")
    row = tabs[0]["rows"][0]
    assert row["volatility"] == 0.0, row["volatility"]
    assert row["liquidity"] == 100_000


def test_the_day_itself_is_inside_the_window():
    """`<= day`, not `< day`: the session being read is the last bar of its
    own twenty, which is what "ending on that day" means."""
    bars = [_Bar(f"2026-09-{d:02d}", 100.0, 1000) for d in range(11, 24)]
    bars.append(_Bar("2026-09-24", 150.0, 4000))
    tabs = _rows_as_tabs("LAST")
    movers._enrich_session_stats(_Router({"LAST": bars}), tabs, "2026-09-24")
    # The 24th's own bar moved the price and carried four times the volume,
    # so both figures have to reflect it.
    assert tabs[0]["rows"][0]["volatility"] > 0
    assert tabs[0]["rows"][0]["liquidity"] > 100_000


def test_a_stats_vendor_failure_never_costs_the_list():
    """The reader asked for the day's movers; the two statistics ride along.
    A vendor refusing them leaves dashes, never an error."""
    class _Angry(_Router):
        def get(self, *a, **k):
            raise RuntimeError("vendor down")

    tabs = _rows_as_tabs("AAPL")
    movers._enrich_session_stats(_Angry(), tabs, "2026-09-24")
    assert tabs[0]["rows"][0]["volatility"] is None
    assert tabs[0]["rows"][0]["liquidity"] is None
    assert tabs[0]["rows"][0]["symbol"] == "AAPL"


def test_a_symbol_with_no_bars_before_the_day_shows_a_dash():
    """A listing that had barely traded by then gets None, like the live
    column — not a figure computed from two closes."""
    tabs = _rows_as_tabs("NEW")
    movers._enrich_session_stats(_Router({"NEW": [_Bar("2026-09-30", 10.0, 500)]}),
                                 tabs, "2026-09-24")
    assert tabs[0]["rows"][0]["volatility"] is None


def test_enough_bars_are_asked_for_to_reach_back():
    """Asking for exactly twenty would leave none on or before a past day."""
    asked: list[int] = []

    class _Counting(_Router):
        def get(self, method, *args, **kwargs):
            if method == "daily_history":
                asked.append(args[1])
            return {}

    movers._enrich_session_stats(_Counting(), _rows_as_tabs("AAPL"), "2026-09-24")
    assert asked and asked[0] > movers.STATS_DAYS + 1


# RECORDED CLOSES (2026-10-05) ------------------------------------------------

def test_a_finished_session_is_recorded_and_then_read_without_the_vendor(store):
    class _Once:
        owner = "reader-1"
        connected = ["alpaca"]
        calls = 0

        def ask(self, method, *a, **k):
            self.calls += 1
            return {"AAPL": {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}}

        def vendor_for(self, surface, method):
            return type("V", (), {"name": "alpaca"})()

    movers._cache.clear()
    r = _Once()
    first = movers._market_day(r, "2020-01-02")
    movers._cache.clear()                      # a restart: the memo is gone, the store is not
    again = movers._market_day(r, "2020-01-02")
    assert first == again and r.calls == 1
    assert "2020-01-02" in store.recorded_session_days("reader-1")


def test_today_is_never_recorded(store):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    class _Live:
        owner = "reader-1"
        connected = ["alpaca"]

        def ask(self, method, *a, **k):
            return {"AAPL": {"close": 1.0, "volume": 1}}

    movers._cache.clear()
    movers._market_day(_Live(), today)
    assert store.recorded_session_days("reader-1") == set()


def test_a_recorded_day_outlives_the_vendor_key(store):
    store.save_session_day("reader-1", "2020-01-02", "alpaca", {"AAPL": {"close": 3.0, "volume": 1}})

    class _NoKey:
        owner = "reader-1"
        connected: list = []

        def ask(self, *a, **k):
            from alphadesk.providers.base import NeedsKey
            raise NeedsKey("market_day")

    movers._cache.clear()
    assert movers._market_day(_NoKey(), "2020-01-02") == {"AAPL": {"close": 3.0, "volume": 1}}


def test_closes_are_recorded_oldest_first_and_only_once(store, monkeypatch):
    monkeypatch.setattr(movers, "trading_sessions", lambda router, count=15: ["2020-01-03", "2020-01-02"])
    asked: list[str] = []

    class _R:
        owner = "reader-1"

        def vendor_for(self, s, m):
            return type("V", (), {"name": "alpaca"})()

        def ask(self, method, day):
            asked.append(day)
            return {"AAPL": {"close": 1.0, "volume": 1}}

    assert movers.record_closes(_R()) == 2
    assert asked == ["2020-01-02", "2020-01-03"]
    assert movers.record_closes(_R()) == 0


# OPTIONS AND CRYPTO DAYS (2026-10-05) ----------------------------------------

def _opt_row(sym, vol, chg):
    return {"symbol": sym, "display": sym, "name": None, "price": 1.0, "change_pct": chg, "volume": vol,
            "turnover": vol * 100.0, "volatility": None, "liquidity": None, "spark": []}


def test_an_option_list_is_recorded_after_the_close_and_read_back(store, monkeypatch):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    tabs = [{"id": "most_active", "label": "Active", "rows": [_opt_row("SPY260105C00600000", 9000, 12.0)]}]
    built: list[str] = []

    def fake_build(router, key, cat, top, mp, floors):
        built.append(cat)
        return {"tabs": tabs, "source": "alpaca", "as_of": "2026-10-05T21:00:00+00:00"}

    monkeypatch.setattr(movers, "_build", fake_build)

    class _R:
        owner = "reader-1"

    ny = ZoneInfo("America/New_York")
    before = datetime(2026, 10, 5, 15, 59, tzinfo=ny).astimezone(timezone.utc)
    after = datetime(2026, 10, 5, 16, 30, tzinfo=ny).astimezone(timezone.utc)
    sunday = datetime(2026, 10, 4, 18, 0, tzinfo=ny).astimezone(timezone.utc)
    assert movers.record_options_close(_R(), before) is False      # the session is not over
    assert movers.record_options_close(_R(), sunday) is False      # not a session
    assert movers.record_options_close(_R(), after) is True
    assert movers.record_options_close(_R(), after) is False       # once
    assert built == ["options"]

    out = movers._options_session(_R(), "2026-10-05", 20, None, None, None, None)
    assert out["tabs"][0]["rows"][0]["symbol"] == "SPY260105C00600000" and not out.get("not_recorded")
    assert movers.past_days(_R(), "options", 5) == ["2026-10-05"]


def test_an_unrecorded_option_day_says_so(store):
    class _R:
        owner = "reader-1"

    out = movers._options_session(_R(), "2026-09-01", 20, None, None, None, None)
    assert out["not_recorded"] is True and out["tabs"] == []
    assert "recorded" in out["note"]


def test_a_coin_day_is_close_against_the_day_before_and_recorded(store):
    asked: list[str] = []

    class _R:
        owner = "reader-1"
        answered_by = "alpaca"

        def ask(self, method, day):
            asked.append(day)
            return {"BTC-USD": {"close": 110.0, "prev_close": 100.0, "volume": 0.5},
                    "ETH-USD": {"close": 90.0, "prev_close": 100.0, "volume": 3.0},
                    "USDC-USD": {"close": 1.0, "prev_close": 0.999, "volume": 1e6}}

    movers._cache.clear()
    out = movers._crypto_session(_R(), "2020-01-02", 20, None, None, None, None)
    tabs = {t["id"]: t["rows"] for t in out["tabs"]}
    assert [r["symbol"] for r in tabs["gainers"]] == ["BTC-USD"]
    assert tabs["gainers"][0]["change_pct"] == 10.0
    assert tabs["gainers"][0]["turnover"] == 55.0               # fractions of a coin count
    assert [r["symbol"] for r in tabs["losers"]] == ["ETH-USD"]
    assert all(r["symbol"] != "USDC-USD" for r in tabs["gainers"] + tabs["losers"] + tabs["most_active"])
    assert out["previous_session"] == "2020-01-01"
    movers._cache.clear()
    movers._crypto_session(_R(), "2020-01-02", 20, None, None, None, None)
    assert asked == ["2020-01-02"]                              # the second read is the record


def test_a_coin_day_not_yet_finished_is_never_recorded(store):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()

    class _R:
        owner = "reader-1"
        answered_by = "alpaca"

        def ask(self, method, day):
            return {"BTC-USD": {"close": 1.0, "prev_close": 1.0, "volume": 1.0}}

    movers._cache.clear()
    movers._crypto_session(_R(), today, 20, None, None, None, None)
    assert store.recorded_movers_days("reader-1", "crypto") == []
    assert today not in movers.crypto_days(5)


def test_a_coin_day_measures_volatility_and_liquidity_on_the_days_ending_it(store):
    import datetime as dt
    day = "2020-01-25"
    end = dt.datetime(2020, 1, 25, tzinfo=dt.timezone.utc)
    # Twenty-five calm days up to the 25th, then a wild week after it that
    # must not leak into the figure.
    hist = [{"ts": end - dt.timedelta(days=24 - i), "close": 100.0 + (i % 2), "volume": 2.0} for i in range(25)]
    hist += [{"ts": end + dt.timedelta(days=i), "close": 100.0 * (3 if i % 2 else 1), "volume": 2.0} for i in range(1, 8)]

    class _R:
        owner = "reader-1"
        answered_by = "alpaca"

        def ask(self, method, d):
            return {"BTC-USD": {"close": 101.0, "prev_close": 100.0, "volume": 2.0}}

        def get(self, method, syms, days):
            assert method == "crypto_daily_history"
            return {"BTC-USD": hist}

    movers._cache.clear()
    out = movers._crypto_session(_R(), day, 20, None, None, None, None)
    row = next(t for t in out["tabs"] if t["id"] == "gainers")["rows"][0]
    calm = movers.stats_from_bars([b["close"] for b in hist[:25]], [b["volume"] for b in hist[:25]], periods=365)
    assert row["volatility"] == calm["volatility"] and row["volatility"] is not None
    assert row["liquidity"] == calm["liquidity"]


# FINISHED LISTS (2026-10-05) -------------------------------------------------

def test_a_finished_coin_list_is_kept_and_read_back_without_any_vendor(store):
    import datetime as dt
    end = dt.datetime(2020, 1, 25, tzinfo=dt.timezone.utc)
    hist = [{"ts": end - dt.timedelta(days=24 - i), "close": 100.0 + (i % 2), "volume": 2.0} for i in range(25)]
    calls: list[str] = []

    class _R:
        owner = "reader-1"
        answered_by = "alpaca"

        def ask(self, method, d):
            calls.append(method)
            return {"BTC-USD": {"close": 101.0, "prev_close": 100.0, "volume": 2.0}}

        def get(self, method, syms, days):
            calls.append(method)
            return {"BTC-USD": hist}

    movers._cache.clear()
    first = movers._crypto_session(_R(), "2020-01-25", 50, None, None, None, None)
    n = len(calls)
    movers._cache.clear()
    again = movers._crypto_session(_R(), "2020-01-25", 50, None, None, None, None)
    assert again == first and len(calls) == n            # nothing asked the second time


def test_a_list_whose_statistics_failed_is_not_kept():
    rows = [{"symbol": s, "volatility": None} for s in ("A", "B", "C", "D", "E")]
    assert not movers.finished_list_complete({"tabs": [{"rows": rows}]})
    rows[0]["volatility"] = rows[1]["volatility"] = rows[2]["volatility"] = rows[3]["volatility"] = 30.0
    assert movers.finished_list_complete({"tabs": [{"rows": rows}]})
    assert not movers.finished_list_complete({"tabs": [{"rows": rows}], "unavailable": True})


def test_a_kept_stock_list_answers_before_any_vendor_is_touched(store, monkeypatch):
    import alphadesk.providers as providers

    class _Untouchable:
        owner = "reader-1"
        connected = ["alpaca"]

        def __getattr__(self, name):
            raise AssertionError(f"a vendor was asked: {name}")

    kept = {"category": "stocks", "session": "2020-01-02", "source": "alpaca",
            "tabs": [{"id": "gainers", "label": "Gainers", "rows": [{"symbol": "AAPL", "volatility": 20.0}]}]}
    owner_only = type("R", (), {"owner": "reader-1"})()
    d_price, d_turn = movers.DEFAULT_FLOORS["stocks"]
    movers._finished_put(owner_only, "stocks", movers._finished_key("2020-01-02", 50, d_price, d_turn, 0.0, 0.0), kept)
    monkeypatch.setattr(providers, "get_prices", lambda: _Untouchable())
    movers._cache.clear()
    assert movers.session_movers("stocks", "2020-01-02", top=50) == kept


# CORPORATE EVENTS AND THE REAL SOURCE (2026-10-05) ---------------------------

class _WithAdjusted(_Router):
    def __init__(self, split_bars, adjusted_bars):
        super().__init__(split_bars)
        self._adjusted = adjusted_bars

    def get(self, method, *args, **kwargs):
        if method == "adjusted_daily_history":
            return {s: self._adjusted.get(s, []) for s in args[0]}
        return super().get(method, *args, **kwargs)


def test_a_spin_off_stays_on_the_list_ranked_by_what_a_holder_made():
    # Corteva, 2026-10-01: the chart fell 77.62 to 12.57 (-83.8%) as the
    # spun-off company went to holders; adjusted for it, the parent moved -1%.
    rows = [movers._row("CTVA", 12.57, -83.81, 88_375_542)]
    router = _WithAdjusted({"CTVA": [_Bar("2026-09-30", 77.62), _Bar("2026-10-01", 12.57)]},
                           {"CTVA": [_Bar("2026-09-30", 12.70), _Bar("2026-10-01", 12.57)]})
    out, dropped = movers._verify_extremes(router, rows, "2026-09-30", "2026-10-01")
    assert dropped == 0 and len(out) == 1
    row = out[0]
    assert row["corporate_action"] is True
    assert row["change_pct"] == pytest.approx(-1.02, abs=0.05)
    assert row["price_change_pct"] == pytest.approx(-83.81, abs=0.05)


def test_a_real_crash_is_not_called_a_corporate_event():
    rows = [movers._row("WYY", 2.0, -50.6, 1_000_000)]
    bars = {"WYY": [_Bar("2026-09-24", 4.05), _Bar("2026-09-25", 2.0)]}
    out, _ = movers._verify_extremes(_WithAdjusted(bars, bars), rows, "2026-09-24", "2026-09-25")
    assert not out[0].get("corporate_action") and out[0]["change_pct"] == pytest.approx(-50.6, abs=0.1)


def test_a_past_list_names_the_vendor_that_served_it(store):
    class _Served:
        owner = "reader-1"
        connected = ["alpaca", "polygon"]
        answered_by = "alpaca"

        def ask(self, method, *a, **k):
            return {"AAPL": {"close": 1.0, "volume": 1}}

    movers._cache.clear()
    movers._day_vendor.clear()
    movers._market_day(_Served(), "2020-01-02")
    assert movers._day_vendor[("reader-1", "2020-01-02")] == "alpaca"
    assert store.session_day_vendor("reader-1", "2020-01-02") == "alpaca"
    movers._cache.clear()
    movers._day_vendor.clear()
    movers._market_day(_Served(), "2020-01-02")             # read back from the record
    assert movers._day_vendor[("reader-1", "2020-01-02")] == "alpaca"


def test_a_day_recorded_before_the_vendor_was_kept_says_unknown(store):
    store.save_session_day("reader-1", "2020-01-03", "polygon", {"AAPL": {"close": 1.0, "volume": 1}})
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE session_days SET saved_at=? WHERE day=?", (store.SESSION_VENDOR_TRUSTED_FROM - 60, "2020-01-03"))
    assert store.session_day_vendor("reader-1", "2020-01-03") is None
    assert movers._recorded_vendor("reader-1", "2020-01-03") == "unknown"
