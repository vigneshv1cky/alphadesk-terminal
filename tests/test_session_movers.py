"""A past session's movers (2026-09-26, #87).

Both tests here exist because the first working version shipped a wrong
number to the TOP of a gainers list, which is the worst place for one.
"""

from datetime import date, timedelta

import pytest

from alphadesk.ingest import movers


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


def test_only_stocks_and_etfs_can_be_asked_about_a_past_session():
    # Every other category's movers come from a today-only vendor endpoint.
    assert movers.SESSION_CATEGORIES == ("stocks", "etfs")
    with pytest.raises(KeyError):
        movers.session_movers("crypto", (date.today() - timedelta(days=1)).isoformat())
