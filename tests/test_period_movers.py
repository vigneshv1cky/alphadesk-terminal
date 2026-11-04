"""Calendar-week and calendar-month movers (2026-11-04).

The calendar is checked against real weeks with holidays in them, and the
list against the two mistakes a longer window invites: a split inside the
period read as a move, and one busy end day carrying a thin stock past the
turnover floor.
"""

import datetime as dt
from datetime import date

import pytest

from alphadesk.ingest import movers, period_movers as pm


# ── the calendar ──────────────────────────────────────────────────────────

def test_a_finished_week_is_monday_to_friday_against_the_friday_before():
    w = pm.period_window("week", date(2026, 10, 28), today=date(2026, 11, 4))
    assert w["first_day"] == "2026-10-26" and w["last_day"] == "2026-10-30"
    assert w["sessions"] == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    assert w["base"] == "2026-10-23" and w["end"] == "2026-10-30" and w["complete"]


def test_the_current_week_ends_at_its_last_finished_session():
    # Wednesday before the open: Monday and Tuesday are done, today is not.
    w = pm.period_window("week", date(2026, 11, 4), today=date(2026, 11, 4))
    assert w["base"] == "2026-10-30" and w["end"] == "2026-11-03"
    assert not w["complete"]


def test_a_weekend_belongs_to_the_week_just_ended():
    w = pm.period_window("week", date(2026, 10, 31), today=date(2026, 11, 4))
    assert w["first_day"] == "2026-10-26" and w["complete"]


def test_a_holiday_is_not_a_session_of_its_week():
    w = pm.period_window("week", date(2026, 11, 25), today=date(2026, 12, 15))
    assert "2026-11-26" not in w["sessions"]          # Thanksgiving
    assert w["end"] == "2026-11-27" and w["complete"]


def test_a_month_runs_from_the_close_before_its_first_session_to_its_last():
    m = pm.period_window("month", date(2026, 10, 15), today=date(2026, 11, 4))
    assert m["label"] == "October 2026"
    assert m["base"] == "2026-09-30" and m["end"] == "2026-10-30" and m["complete"]


def test_a_month_that_opens_on_a_holiday_starts_at_its_first_session():
    m = pm.period_window("month", date(2027, 1, 20), today=date(2027, 3, 1))
    assert m["sessions"][0] == "2027-01-04"           # New Year's Day observed, then the weekend
    assert m["base"] == "2026-12-31"


def test_a_period_that_has_not_begun_is_refused():
    with pytest.raises(ValueError):
        pm.period_window("month", date(2026, 12, 3), today=date(2026, 11, 4))
    with pytest.raises(ValueError):
        pm.period_window("quarter", date(2026, 10, 3), today=date(2026, 11, 4))


def test_a_monday_before_the_open_has_no_finished_session_in_its_week():
    w = pm.period_window("week", date(2026, 11, 2), today=date(2026, 11, 2))
    assert w["end"] is None and not w["complete"]


# ── measuring one symbol ──────────────────────────────────────────────────

def _bar(day: str, close: float, volume: float = 1_000_000.0) -> dict:
    return {"ts": dt.datetime.fromisoformat(day + "T04:00:00+00:00"), "open": close, "high": close,
            "low": close, "close": close, "volume": volume}


def test_the_period_is_measured_close_to_close_with_average_daily_dollars():
    bars = [_bar("2026-10-23", 100.0, 9e9),           # the base: its volume is NOT the period's
            _bar("2026-10-26", 102.0, 1000), _bar("2026-10-27", 104.0, 1000),
            _bar("2026-10-28", 106.0, 1000), _bar("2026-10-29", 108.0, 1000), _bar("2026-10-30", 110.0, 1000)]
    m = pm.measure(bars, "2026-10-23", "2026-10-30")
    assert m["change_pct"] == pytest.approx(10.0)
    assert m["volume"] == 5000 and m["sessions_traded"] == 5
    assert m["turnover"] == pytest.approx(106_000.0)
    assert pm.measure(bars, "2026-10-22", "2026-10-30") is None


# ── the list ──────────────────────────────────────────────────────────────

BASE, END = "2026-10-23", "2026-10-30"
WEEK = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", END]


class _Router:
    """Two whole-market closes and per-symbol bars, no vendor reached."""
    owner = None
    connected = ["alpaca"]
    answered_by = "alpaca"

    def __init__(self, days: dict, bars: dict, funds=()):
        self.days, self.bars, self.funds = days, bars, funds
        self.history_asks: list[list[str]] = []

    def vendor_for(self, *_):
        return "alpaca"

    def ask(self, method, day):
        assert method == "market_day"
        return self.days.get(day, {})

    def get(self, method, *args, **kwargs):
        if method == "daily_history":
            self.history_asks.append(list(args[0]))
            return {s: self.bars[s] for s in args[0] if s in self.bars}
        if method == "etf_symbols":
            return list(self.funds)
        return None


def _steady(start: float, end: float, volume: float) -> list[dict]:
    step = (end - start) / len(WEEK)
    return [_bar(BASE, start, volume)] + [_bar(d, start + step * (i + 1), volume) for i, d in enumerate(WEEK)]


@pytest.fixture()
def market(monkeypatch):
    monkeypatch.setattr("alphadesk.ingest.edgar.company_title", lambda s: None)
    monkeypatch.setattr(pm, "datetime", type("D", (dt.datetime,), {
        "now": staticmethod(lambda tz=None: dt.datetime(2026, 11, 4, 6, 0, tzinfo=tz))}))
    movers._cache.clear()
    bars = {
        "UP": _steady(20.0, 30.0, 1_000_000),          # +50% over the week, liquid
        "DOWN": _steady(50.0, 40.0, 1_000_000),        # -20%
        "FLAT": _steady(10.0, 10.1, 5_000_000),
        # Split 2:1 mid-week: the saved base snapshot is pre-split (80), the
        # bars are adjusted (40) — really +10%, the snapshots say -45%.
        "SPLT": _steady(40.0, 44.0, 1_000_000),
        # Busy on the two end days only, thin between: the week's average
        # is under the $1M floor even though both ends clear it.
        "THIN": [_bar(BASE, 10.0, 200_000)] + [_bar(d, 13.0, 1_000) for d in WEEK[:-1]] + [_bar(END, 13.0, 200_000)],
        "SPY": _steady(700.0, 710.0, 50_000_000),
    }
    days = {
        BASE: {"UP": {"close": 20.0, "volume": 1e6}, "DOWN": {"close": 50.0, "volume": 1e6},
               "FLAT": {"close": 10.0, "volume": 5e6}, "SPLT": {"close": 80.0, "volume": 5e5},
               "THIN": {"close": 10.0, "volume": 2e5}, "SPY": {"close": 700.0, "volume": 5e7},
               "GHOST": {"close": 5.0, "volume": 1e7}},
        END: {"UP": {"close": 30.0, "volume": 1e6}, "DOWN": {"close": 40.0, "volume": 1e6},
              "FLAT": {"close": 10.1, "volume": 5e6}, "SPLT": {"close": 44.0, "volume": 1e6},
              "THIN": {"close": 13.0, "volume": 2e5}, "SPY": {"close": 710.0, "volume": 5e7},
              # +300% in the snapshots and no bars to check it against.
              "GHOST": {"close": 20.0, "volume": 1e7}},
    }
    return _Router(days, bars, funds=("SPY",))


def _tab(result, tab):
    return {r["symbol"]: r for t in result["tabs"] if t["id"] == tab for r in t["rows"]}


def test_a_finished_week_ranks_the_week_not_a_day(market):
    got = pm.period_movers("stocks", "week", "2026-10-28", router=market)
    assert got["change_label"] == "1W" and got["complete"]
    assert got["base_session"] == BASE and got["session"] == END and got["sessions"] == 5
    gainers = _tab(got, "gainers")
    assert list(gainers)[0] == "UP" and gainers["UP"]["change_pct"] == pytest.approx(50.0)
    assert _tab(got, "losers")["DOWN"]["change_pct"] == pytest.approx(-20.0)


def test_a_split_inside_the_period_is_measured_from_the_adjusted_bars(market):
    got = pm.period_movers("stocks", "week", "2026-10-28", router=market)
    assert "SPLT" not in _tab(got, "losers")
    assert _tab(got, "gainers")["SPLT"]["change_pct"] == pytest.approx(10.0)
    assert _tab(got, "gainers")["SPLT"]["checked"] is True


def test_the_turnover_floor_reads_the_whole_period(market):
    got = pm.period_movers("stocks", "week", "2026-10-28", router=market)
    assert "THIN" not in _tab(got, "gainers")
    loose = pm.period_movers("stocks", "week", "2026-10-28", min_turnover=0, router=market)
    assert "THIN" in _tab(loose, "gainers")


def test_an_unverifiable_large_move_is_left_out_and_counted(market):
    got = pm.period_movers("stocks", "week", "2026-10-28", router=market)
    assert "GHOST" not in _tab(got, "gainers")
    assert "1 large move left out" in got["note"]


def test_funds_and_stocks_are_kept_apart(market):
    stocks = pm.period_movers("stocks", "week", "2026-10-28", router=market)
    funds = pm.period_movers("etfs", "week", "2026-10-28", router=market)
    assert "SPY" not in _tab(stocks, "gainers")
    assert list(_tab(funds, "gainers")) == ["SPY"]


def test_the_week_under_way_is_labelled_to_date(market):
    market.days["2026-11-03"] = market.days.pop(END)
    market.days["2026-10-30"] = market.days.pop(BASE)
    got = pm.period_movers("stocks", "week", None, router=market)
    assert got["change_label"] == "WTD" and not got["complete"]
    assert got["base_session"] == "2026-10-30" and got["session"] == "2026-11-03"
    assert "to date" in got["note"]


def test_a_month_is_offered_and_a_quarter_is_not(market):
    with pytest.raises(ValueError):
        pm.period_movers("stocks", "quarter", "2026-10-28", router=market)
    with pytest.raises(KeyError):
        pm.period_movers("crypto", "week", "2026-10-28", router=market)
