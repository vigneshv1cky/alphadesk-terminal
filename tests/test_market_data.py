"""The shapes the markets board renders from.

Both additions here are things the UI draws per row or per bar, dozens of
times, so a silently-missing field is a page full of holes rather than one
visible error. These pin the contract without touching the network.
"""

from datetime import datetime, timedelta


from alphadesk.config import ET
from alphadesk.ingest import prices


class FakeBar:
    def __init__(self, i: int, px: float):
        self.timestamp = datetime(2026, 8, 19, 10, 0, tzinfo=ET) + timedelta(minutes=i)
        self.open = px
        self.high = px + 0.5
        self.low = px - 0.5
        self.close = px + 0.2
        self.volume = 1000 + i


class FakeResp:
    def __init__(self, data):
        self.data = data










class TestIntervalResolution:
    """A too-fine interval for the span is DOWNGRADED, not refused — and the
    response says what was actually served, so nobody reads an hourly chart
    believing it is minute data."""

    def test_a_short_range_keeps_the_fine_interval(self):
        assert prices.resolve_interval("1D", "1m") == "1m"

    def test_minute_bars_over_a_year_fall_back(self):
        got = prices.resolve_interval("1Y", "1m")
        assert got == "1h", "the finest interval that actually covers a year"

    def test_a_five_year_range_falls_all_the_way_to_daily(self):
        assert prices.resolve_interval("5Y", "15m") == "1d"

    def test_no_preference_picks_by_span(self):
        assert prices.resolve_interval("1D", None) == "1m"
        assert prices.resolve_interval("1Y", None) == "1d"

    def test_an_unknown_interval_is_treated_as_no_preference(self):
        assert prices.resolve_interval("1D", "banana") == "1m"



class TestOfferableIntervals:
    """Which intervals a range is allowed to OFFER.

    Distinct from resolve_interval, which answers what a request gets served.
    This decides what may be asked for at all, and it exists because the
    answers differ wildly in cost: measured warm, 3M of hourly returns in 0.7s
    while 1Y of hourly takes 9-14s and draws 2,031 points into a 449px tile.
    """

    def test_every_range_offers_its_own_default(self):
        # The toolbar shows the served interval as the current value, so a
        # default missing from its own menu would render a selection that
        # cannot be re-selected.
        for rng in ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"):
            served = prices.resolve_interval(rng, None)
            assert served in prices.available_intervals(rng), f"{rng} omits {served}"

    def test_nothing_offered_would_be_downgraded(self):
        # The whole point: an offered interval must come back as itself, so the
        # "showing X instead" notice becomes unreachable rather than routine.
        for rng in ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"):
            for iv in prices.available_intervals(rng):
                assert prices.resolve_interval(rng, iv) == iv, f"{rng}/{iv} downgrades"

    def test_intraday_stops_after_three_months(self):
        # The expensive band. 6M/YTD/1Y hourly cost seconds and are unreadable
        # at tile width, so they are not offered at all.
        for rng in ("6M", "YTD", "1Y", "5Y", "MAX"):
            for iv in prices.available_intervals(rng):
                assert prices._interval_minutes(iv) is None, f"{rng} still offers {iv}"

    def test_three_months_keeps_hourly(self):
        # Deliberately retained: 0.7s, 1.25 bars per pixel, and the only route
        # to intraday structure in an older period is zooming a longer series.
        assert "1h" in prices.available_intervals("3M")

    def test_no_range_offers_a_handful_of_bars(self):
        for rng in ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"):
            span = prices.RANGE_DAYS[rng]
            for iv in prices.available_intervals(rng):
                assert prices._estimated_bars(span, iv) >= prices._MIN_OFFERABLE_BARS

    def test_every_range_offers_something(self):
        for rng in ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"):
            assert prices.available_intervals(rng), f"{rng} offers nothing"

    def test_unknown_range_is_treated_as_a_day(self):
        assert prices.available_intervals("nonsense") == prices.available_intervals("1D")

    def test_estimate_tracks_the_window_actually_fetched(self):
        # Intraday is fetched over `span + 3` CALENDAR days, not over the
        # range's nominal length. Estimating from the nominal length read 1D as
        # a single session and made 30-minute bars look too sparse to offer
        # when they are ~50. Measured hourly counts, which the estimate must
        # stay close to:
        for rng, served in (("1M", 197), ("3M", 560), ("6M", 1094), ("1Y", 2031)):
            est = prices._estimated_bars(prices.RANGE_DAYS[rng], "1h")
            assert 0.75 * served <= est <= 1.25 * served, f"{rng}: est {est} vs {served}"

    def test_one_day_still_offers_its_finer_intervals(self):
        # The regression the estimator fix exists to prevent.
        offered = prices.available_intervals("1D")
        for iv in ("15m", "30m"):
            assert iv in offered, f"1D dropped {iv}"

    def test_monthly_bars_need_more_than_a_year(self):
        # Twelve points is not a chart. Five years of them is.
        for rng in ("YTD", "1Y"):
            assert "1mo" not in prices.available_intervals(rng)
        for rng in ("5Y", "MAX"):
            assert "1mo" in prices.available_intervals(rng)

    def test_four_hour_bars_survive_a_month(self):
        # ~59 bars: roughly two a session. Thin-looking but perfectly readable,
        # and the floor must not be raised so far that it takes this with it.
        assert "4h" in prices.available_intervals("1M")


class TestDailyCoverage:
    """What `indicators_reliable` means on a DAILY series.

    It answers whether the FEED can be trusted, and a daily bar per trading day
    is complete by construction. It used to also fail the whole series below 35
    bars — MACD's 26+9 warm-up — which is a real limit but MACD's alone.
    Applying it to everything hid RSI-9 from a 24-bar month that supports it
    fine, so switching range to 1M silently dropped every pane the reader had
    chosen. Warm-up is per indicator and lives with each one (PANE_INDICATORS'
    minBars).
    """

    def _bars(self, n):
        return [{"close": 1.0 + i} for i in range(n)]

    def test_a_short_daily_series_is_still_a_trustworthy_feed(self):
        # 24 bars: too few for MACD, ample for RSI-9. The flag must not be the
        # thing that decides that.
        assert prices._daily_coverage(self._bars(24))["indicators_reliable"] is True

    def test_coverage_is_complete_by_construction(self):
        cov = prices._daily_coverage(self._bars(10))
        assert cov["coverage"] == 1.0
        assert cov["median_gap_min"] is None
        assert cov["bar_count"] == 10 and cov["sessions"] == 10

    def test_an_empty_series_is_not_reliable(self):
        cov = prices._daily_coverage([])
        assert cov["indicators_reliable"] is False
        assert cov["coverage"] == 0.0




class TestThemes:
    """Curated baskets. The parsing matters more than it looks: THEMES feeds the
    sidebar, so a bad override does not fail loudly — it silently empties the
    navigation."""

    def _load(self, monkeypatch, raw):
        import importlib
        from alphadesk import config
        if raw is None:
            monkeypatch.delenv("THEMES_JSON", raising=False)
        else:
            monkeypatch.setenv("THEMES_JSON", raw)
        return importlib.reload(config).THEMES

    def test_defaults_are_non_empty_and_uniquely_keyed(self, monkeypatch):
        themes = self._load(monkeypatch, None)
        assert themes
        ids = [t["id"] for t in themes]
        assert len(ids) == len(set(ids))
        for t in themes:
            assert t["label"] and t["symbols"]

    def test_override_replaces_the_defaults(self, monkeypatch):
        themes = self._load(
            monkeypatch, '[{"id":"x","label":"X","symbols":["aapl","msft"]}]')
        assert [t["id"] for t in themes] == ["x"]
        # Symbols are upper-cased on the way in, so a lowercase config does not
        # produce quote requests that miss the cache the rest of the app shares.
        assert themes[0]["symbols"] == ["AAPL", "MSFT"]

    def test_malformed_override_falls_back_rather_than_emptying_the_nav(self, monkeypatch):
        for bad in ("not json at all", "[]", '[{"id":"","label":"","symbols":[]}]',
                    '[{"id":"x"}]'):
            themes = self._load(monkeypatch, bad)
            assert themes, f"{bad!r} emptied THEMES"

    def test_entries_without_symbols_are_dropped_not_kept_empty(self, monkeypatch):
        themes = self._load(
            monkeypatch,
            '[{"id":"a","label":"A","symbols":["NVDA"]},'
            ' {"id":"b","label":"B","symbols":[]}]')
        assert [t["id"] for t in themes] == ["a"]






