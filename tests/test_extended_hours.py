"""The vendor-neutral series helpers: history pages, coverage over an
extended session, default intervals, the overnight union and the unbacked
wick clip."""
from datetime import datetime, timedelta, timezone


from alphadesk.ingest import prices as prices_mod

from alphadesk.config import ET

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=ET)




def _bar(iso: str, c: float = 100.0, v: float = 1.0) -> dict:
    ts = datetime.fromisoformat(iso).astimezone(timezone.utc)
    return {"ts": ts, "open": c, "high": c, "low": c, "close": c, "volume": v}






class TestHistoryPages:
    def test_a_page_is_one_range_span_before_the_cursor(self):
        start, end = prices_mod.page_window("5D", NOW)
        assert end == NOW and (end - start).days == 8

    def test_max_has_no_pages(self):
        assert prices_mod.page_window("MAX", NOW) is None

    def test_each_attempt_reaches_twice_as_far(self):
        spans = [(NOW - w[0]).days for w in prices_mod.page_attempts("1D", NOW)]
        assert spans == [4, 8, 16, 32, 64]
        assert all(w[1] == NOW for w in prices_mod.page_attempts("1D", NOW))

    def test_max_offers_no_attempt(self):
        assert prices_mod.page_attempts("MAX", NOW) == []


    def test_scrolling_left_stops_where_the_bar_size_runs_out(self):
        floor = prices_mod.history_floor("1m", NOW)
        assert (NOW - floor).days == 60
        assert prices_mod.history_floor("1h", NOW) is not None
        assert prices_mod.history_floor("1d", NOW) is None          # only the vendor ends a daily chart

    def test_a_window_never_digs_past_the_bar_size_reach(self):
        floor = prices_mod.history_floor("1m", NOW)
        cursor = floor + timedelta(days=3)
        spans = prices_mod.page_attempts("1D", cursor, floor)
        # Three days above the ceiling, a four-day window is clipped to it —
        # and there is nothing left to widen into, so that is the only one.
        assert spans == [(floor, cursor)]

    def test_a_cursor_at_the_ceiling_has_no_window_at_all(self):
        floor = prices_mod.history_floor("1m", NOW)
        assert prices_mod.page_attempts("1D", floor, floor) == []
        assert prices_mod.page_window("1D", floor - timedelta(days=1), 0, floor) is None

    def test_the_ceiling_sentence_points_at_the_way_further_back(self):
        note = prices_mod.history_ceiling_note("1m")
        assert "2 months" in note and "longer range" in note
        assert "vendor" in prices_mod.history_ceiling_note("1d")     # no ceiling of ours there

    def test_an_overshooting_page_keeps_the_bars_nearest_the_cursor(self):
        page = [_bar("2026-09-09T10:00", c=float(i)) for i in range(9_334)]
        kept = prices_mod.page_trim(page, 2_000)
        assert len(kept) == 2_000 and kept[-1] is page[-1]           # the newest end joins the chart
        assert len(prices_mod.page_trim(page, 99_000)) == prices_mod.PAGE_MAX_BARS
        assert len(prices_mod.page_trim(page[:300], 2_000)) == 300   # a short page is left alone

    def test_a_page_is_thin_until_it_fills_what_was_asked_for(self):
        page = [_bar("2026-09-09T10:00")] * 700
        # Nothing asked for: the floor decides, and 700 clears it.
        assert not prices_mod.page_is_thin(page)
        assert prices_mod.page_is_thin(page[:100])
        # A screen that needs 2,000 bars is still waiting on 700.
        assert prices_mod.page_is_thin(page, 2_000)
        assert not prices_mod.page_is_thin(page, 300)      # never below the floor
        # Nothing is asked for beyond the ceiling on one page.
        assert not prices_mod.page_is_thin([_bar("2026-09-09T10:00")] * 6_000, 99_000)







class TestCoverage:
    def test_a_consolidated_day_is_measured_against_its_own_session(self):
        # 960 one-minute bars, 04:00–20:00 ET on one day: all of the session.
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        t0 = dt(2026, 9, 9, 4, 0, tzinfo=et)
        bars = [{"ts": t0 + timedelta(minutes=m), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for m in range(960)]
        st = prices_mod._coverage_stats(bars)
        assert st["session_minutes"] == 960 and st["coverage"] == 1.0 and st["indicators_reliable"]

    def test_a_regular_hours_feed_keeps_the_390_yardstick(self):
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        t0 = dt(2026, 9, 9, 9, 30, tzinfo=et)
        bars = [{"ts": t0 + timedelta(minutes=m), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for m in range(0, 390, 2)]
        st = prices_mod._coverage_stats(bars)
        assert st["session_minutes"] == 390 and st["coverage"] == 0.5



class TestDefaultInterval:
    def test_a_range_opens_on_the_finest_bar_that_is_not_megabytes(self):
        """The finest bar the range offers, up to a ceiling on how many
        that is. A vendor decides the offer, and Alpaca reports every
        intraday interval as reaching ten years: a month opened on
        one-minute bars, 28,551 of them and 3.4MB of JSON on every range
        switch (2026-09-15)."""
        d = prices_mod.default_interval
        assert d("1D") == "1m" and d("5D") == "1m"
        assert d("1M") == prices_mod.available_intervals("1M")[0]
        assert d("3M") == prices_mod.available_intervals("3M")[0]
        assert d("1Y") == "1d" and d("MAX") == "1d"

    def test_a_vendor_that_reaches_ten_years_does_not_open_a_month_on_minutes(self):
        table = {k: {**v, "max_days": None if v["unit"] == "Day" else 3650}
                 for k, v in prices_mod.CHART_INTERVALS.items()}
        d = prices_mod.default_interval
        assert d("1D", table) == "1m" and d("5D", table) == "1m"      # where they were
        assert d("1M", table) == "5m"                                 # not 1m: 28,551 bars
        assert prices_mod._estimated_bars(31, "5m", table) <= prices_mod.DEFAULT_MAX_BARS
        assert "1m" in prices_mod.available_intervals("1M", table)    # still offered, if asked for

    def test_resolve_without_a_preference_is_the_default(self):
        for r in ("1D", "1M", "3M", "6M", "1Y"):
            assert prices_mod.resolve_interval(r, None) == prices_mod.default_interval(r)


class TestOvernight:
    def test_the_night_is_added_to_the_day_and_never_duplicated(self):
        # 22:00 ET on the 9th is 02:00Z on the 10th.
        day = [_bar("2026-09-09T13:30:00+00:00", v=100), _bar("2026-09-10T02:00:00+00:00", v=1)]
        night = [_bar("2026-09-10T02:00:00+00:00", v=9), _bar("2026-09-10T03:00:00+00:00", v=2)]
        out = prices_mod.merge_overnight(day, night)
        assert [b["volume"] for b in out] == [100, 1, 2]          # the day's copy wins the collision

    def test_only_overnight_minutes_count_as_the_night(self):
        from datetime import datetime as dt
        et = prices_mod.ET
        assert prices_mod._is_overnight(dt(2026, 9, 9, 20, 0, tzinfo=et))
        assert prices_mod._is_overnight(dt(2026, 9, 10, 3, 59, tzinfo=et))
        assert not prices_mod._is_overnight(dt(2026, 9, 10, 4, 0, tzinfo=et))
        assert not prices_mod._is_overnight(dt(2026, 9, 10, 15, 0, tzinfo=et))



    def test_a_day_with_overnight_prints_is_a_24_hour_session(self):
        from datetime import datetime as dt
        et = prices_mod.ET
        # One calendar day, midnight to midnight ET, every other minute.
        t0 = dt(2026, 9, 9, 0, 0, tzinfo=et)
        bars = [{"ts": t0 + timedelta(minutes=m), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for m in range(0, 1440, 2)]
        st = prices_mod._coverage_stats(bars)
        assert st["session_minutes"] == 1440 and st["coverage"] == 0.5


class TestUnbackedWicks:
    def _bar(self, o, h, l, c, v):
        return {"open": o, "high": h, "low": l, "close": c, "volume": v}

    def test_a_spike_with_no_volume_and_no_follow_through_is_clipped(self):
        bars = [self._bar(218.4, 218.5, 218.3, 218.4, 0),
                self._bar(218.4, 230.1, 218.3, 218.4, 0),      # NVDA 16:25 on 2026-09-11, as served
                self._bar(218.4, 218.5, 218.3, 218.4, 0)]
        assert prices_mod.clip_unbacked_wicks(bars) == 1
        assert bars[1]["high"] == 218.4 and bars[1]["low"] == 218.3

    def test_a_low_spike_is_clipped_the_same_way(self):
        bars = [self._bar(218.4, 218.5, 218.3, 218.4, 0),
                self._bar(218.4, 218.4, 208.1, 218.4, 0),
                self._bar(218.4, 218.5, 218.3, 218.4, 0)]
        assert prices_mod.clip_unbacked_wicks(bars) == 1
        assert bars[1]["low"] == 218.4

    def test_a_real_move_with_follow_through_is_kept(self):
        # The bar ran to 222 and the NEXT bar closed there: not an artefact.
        bars = [self._bar(218.4, 218.5, 218.3, 218.4, 0),
                self._bar(218.4, 222.0, 218.3, 221.5, 0),
                self._bar(221.5, 222.2, 221.0, 221.8, 0)]
        assert prices_mod.clip_unbacked_wicks(bars) == 0

    def test_a_bar_with_volume_is_never_touched(self):
        bars = [self._bar(218.4, 218.5, 218.3, 218.4, 100),
                self._bar(218.4, 230.1, 218.3, 218.4, 5),
                self._bar(218.4, 218.5, 218.3, 218.4, 100)]
        assert prices_mod.clip_unbacked_wicks(bars) == 0

    def test_a_stray_body_with_no_volume_is_flattened_to_the_last_trade(self):
        # Apple 2026-09-08 16:53 and 16:54 as served: two zero-volume bars whose
        # open/close sat at 334.03 between neighbours at 316.3.
        bars = [self._bar(316.3, 316.4, 316.2, 316.33, 0),
                self._bar(334.03, 334.03, 316.26, 316.3, 0),
                self._bar(316.3, 334.03, 316.23, 334.03, 0),
                self._bar(316.3, 316.4, 316.2, 316.3, 0)]
        assert prices_mod.clip_unbacked_wicks(bars) == 2
        for b in bars[1:3]:
            assert b["open"] == b["high"] == b["low"] == b["close"] == 316.33
        assert bars[3]["close"] == 316.3                                   # the real bars are untouched

    def test_a_stray_body_that_holds_is_a_move(self):
        # The bar jumped and the next three closes stayed there: not a stray print.
        bars = [self._bar(316.3, 316.4, 316.2, 316.3, 0),
                self._bar(320.5, 320.6, 320.4, 320.5, 0),
                self._bar(320.5, 320.7, 320.4, 320.6, 0),
                self._bar(320.6, 320.8, 320.5, 320.7, 0),
                self._bar(320.7, 320.9, 320.6, 320.8, 0)]
        assert prices_mod.clip_unbacked_wicks(bars) == 0

    def test_a_stray_body_with_volume_is_kept(self):
        bars = [self._bar(316.3, 316.4, 316.2, 316.3, 0),
                self._bar(334.0, 334.0, 316.2, 316.3, 12),                  # traded: not ours to flatten
                self._bar(316.3, 316.4, 316.2, 316.3, 0)]
        assert prices_mod.clip_unbacked_wicks(bars) == 0

    def test_a_small_wick_inside_the_tolerance_is_kept(self):
        bars = [self._bar(218.4, 218.5, 218.3, 218.4, 0),
                self._bar(218.4, 220.0, 218.3, 218.4, 0),      # +0.7%: inside the 1% tolerance
                self._bar(218.4, 218.5, 218.3, 218.4, 0)]
        assert prices_mod.clip_unbacked_wicks(bars) == 0


def test_the_clip_applies_at_the_shared_seam_for_every_source():
    """A provider that hands bars to build_series_payload gets the same clip
    as the builtin tape; a daily series is left alone."""
    from datetime import datetime, timezone, timedelta
    t0 = datetime(2026, 9, 11, 20, 25, tzinfo=timezone.utc)
    mk = lambda i, h, l, v: {"ts": t0 + timedelta(minutes=i), "open": 218.4, "high": h, "low": l, "close": 218.4, "volume": v}  # noqa: E731
    bars = [mk(0, 218.5, 218.3, 0), mk(1, 230.1, 218.3, 0), mk(2, 218.5, 218.3, 0)]
    out = prices_mod.build_series_payload("NVDA", bars, "1m", range_key="1D", interval="1m", stats=None)
    assert out["bars"][1]["h"] == 218.4                       # clipped at the seam
    daily = [dict(mk(0, 218.5, 218.3, 0), ts=t0 - timedelta(days=2)), dict(mk(0, 230.1, 218.3, 0), ts=t0 - timedelta(days=1)), dict(mk(0, 218.5, 218.3, 0), ts=t0)]
    outd = prices_mod.build_series_payload("NVDA", daily, "1d", range_key="1M", interval="1d", stats={"bar_count": 3, "sessions": 3, "coverage": 1.0, "median_gap_min": None, "indicators_reliable": True})
    assert outd["bars"][1]["h"] == 230.1                      # a daily range is a session's


class TestNightFromPrints:
    """The overnight session built from its own prints. A vendor's bars leave
    out odd lots — correct for the consolidated tape, wrong for a session
    that is mostly odd lots: CrowdStrike printed 540 times between 20:00 and
    02:00 on 2026-09-16, 466 of them odd lots, and the vendor's bars covered
    38 of the 135 minutes that traded."""

    def _t(self, iso, price, size):
        return (datetime.fromisoformat(iso).astimezone(timezone.utc), price, size)

    def test_prints_in_one_minute_become_one_bar(self):
        trades = [self._t("2026-09-15T21:00:10-04:00", 241.10, 5),
                  self._t("2026-09-15T21:00:41-04:00", 241.50, 10),
                  self._t("2026-09-15T21:00:59-04:00", 240.90, 2),
                  self._t("2026-09-15T21:01:02-04:00", 241.00, 100)]
        bars = prices_mod.bars_from_trades(trades, 60)
        assert len(bars) == 2
        first = bars[0]
        assert (first["open"], first["high"], first["low"], first["close"]) == (241.10, 241.50, 240.90, 240.90)
        assert first["volume"] == 17                       # odd lots counted, which is the point
        assert bars[1]["volume"] == 100

    def test_prints_out_of_order_still_open_and_close_truthfully(self):
        trades = [self._t("2026-09-15T21:00:41-04:00", 241.50, 1),
                  self._t("2026-09-15T21:00:10-04:00", 241.10, 1)]
        bar = prices_mod.bars_from_trades(trades, 60)[0]
        assert bar["open"] == 241.10 and bar["close"] == 241.50

    def test_a_five_minute_bucket_gathers_five_minutes(self):
        trades = [self._t(f"2026-09-15T21:0{m}:30-04:00", 240 + m, 1) for m in range(6)]
        bars = prices_mod.bars_from_trades(trades, 300)
        assert len(bars) == 2 and bars[0]["low"] == 240 and bars[0]["high"] == 244

    def test_junk_prints_are_dropped_not_drawn(self):
        trades = [self._t("2026-09-15T21:00:10-04:00", 0, 5),
                  self._t("2026-09-15T21:00:20-04:00", None, 5),
                  self._t("2026-09-15T21:00:30-04:00", 241.0, None)]
        bars = prices_mod.bars_from_trades(trades, 60)
        assert len(bars) == 1 and bars[0]["close"] == 241.0 and bars[0]["volume"] == 0

    def test_no_prints_is_no_bars(self):
        assert prices_mod.bars_from_trades([], 60) == []
        assert prices_mod.bars_from_trades([self._t("2026-09-15T21:00:10-04:00", 1, 1)], 0) == []
