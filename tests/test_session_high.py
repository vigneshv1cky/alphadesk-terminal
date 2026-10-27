"""2026-10-27: has the day's high been put in — measurements around the session
high, never a verdict. A fresh high, a stock well off its high, and too little
to read."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from alphadesk.desk import movestate

NY = ZoneInfo("America/New_York")


def _intraday(prices, day="2026-09-30", start=(9, 30), step=1, vol=1000, rsi=None, hist=None):
    t = datetime(*map(int, day.split("-")), *start, tzinfo=NY)
    out = []
    for i, p in enumerate(prices):
        b = {"t": (t + timedelta(minutes=i * step)).astimezone(timezone.utc).isoformat(),
             "o": p, "h": p * 1.001, "l": p * 0.999, "c": p, "v": vol}
        if rsi is not None:
            b["_rsi"] = rsi[i]
        if hist is not None:
            b["_macd_hist"] = hist[i]
        out.append(b)
    return out


def _daily(closes, end="2026-09-29"):
    d, rows = date.fromisoformat(end) - timedelta(days=len(closes) - 1), []
    for c in closes:
        rows.append({"t": d.isoformat(), "o": c, "h": c * 1.02, "l": c * 0.98, "c": c, "v": 10_000})
        d += timedelta(days=1)
    return rows


def _past_sessions(high_times, first="2026-09-10"):
    """Five-minute regular-hours bars for one past session per entry, each
    peaking at its given HH:MM."""
    out, d = [], date.fromisoformat(first)
    for hm in high_times:
        peak = int(hm[:2]) * 60 + int(hm[3:])
        prices = [100 + (5 if 9 * 60 + 30 + i * 5 == peak else 0) for i in range(78)]
        out += _intraday(prices, day=d.isoformat(), step=5)
        d += timedelta(days=1)
    return out


def test_a_fresh_high_is_the_last_bar_with_new_highs_still_coming():
    prices = [100 + i * 0.05 for i in range(150)]
    s = movestate.move_state(_intraday(prices), _daily([100] * 25))["session_high"]
    assert s["reliable"] is True
    assert s["at_session_high"] is True and s["minutes_since_high"] == 0
    assert s["down_from_high_pct"] > -0.2            # the last close, a tick under its own bar's high
    assert s["new_highs"]["last_30min"] >= 29 and s["new_highs"]["last_60min"] >= 59
    assert s["volume"]["since_high"]["bars"] == 0
    assert s["vwap"]["last_vs_vwap_pct"] > 0           # a steady climb sits above its own average


def test_a_stock_well_off_its_high_sets_no_new_highs_and_sells_on_volume():
    up = [100 + i * 0.1 for i in range(120)]
    down = [111.9 - i * 0.12 for i in range(1, 121)]
    bars = _intraday(up + down)
    for b in bars[120:]:
        b["v"] = 3000 if b["c"] < 108 else 1000
    s = movestate.move_state(bars, _daily([100] * 25))["session_high"]
    assert s["at_session_high"] is False and s["minutes_since_high"] >= 115
    assert s["down_from_high_pct"] < -10
    assert s["new_highs"]["last_60min"] == 0 and s["new_highs"]["last_30min"] == 0
    since = s["volume"]["since_high"]
    assert since["down_bars"] > since["up_bars"] and since["up_to_down_volume"] == 0.0
    assert s["vwap"]["last_vs_vwap_pct"] < 0
    assert s["range"]["session_range_in_typical_ranges"] is not None


def test_momentum_that_peaked_before_price_is_flagged_and_one_that_did_not_is_not():
    prices = [100 + i * 0.1 for i in range(120)]
    faded = [60 + i * 0.5 if i <= 60 else 90 - (i - 60) * 0.3 for i in range(120)]   # 90 at 10:30, 72.3 at the high
    s = movestate.move_state(_intraday(prices, rsi=faded, hist=faded), _daily([100] * 25),
                             indicators_reliable=True)["session_high"]["momentum"]
    assert s["reliable"] is True
    assert s["rsi_9"]["peaked_before_price"] is True and s["rsi_9"]["earlier_peak_at"] == "10:30"
    assert s["macd_hist"]["peaked_before_price"] is True
    rising = [60 + i * 0.2 for i in range(120)]
    s = movestate.move_state(_intraday(prices, rsi=rising, hist=rising), _daily([100] * 25),
                             indicators_reliable=True)["session_high"]["momentum"]
    assert s["rsi_9"]["peaked_before_price"] is False and s["macd_hist"]["peaked_before_price"] is False


def test_momentum_is_withheld_when_the_feed_fails_the_coverage_gate():
    prices = [100 + i * 0.1 for i in range(120)]
    s = movestate.move_state(_intraday(prices, rsi=prices, hist=prices), _daily([100] * 25),
                             indicators_reliable=False)["session_high"]["momentum"]
    assert s == {"reliable": False, "note": s["note"]} and "coverage" in s["note"]


def test_too_few_bars_withholds_the_whole_block():
    s = movestate.move_state(_intraday([100, 101, 102]), _daily([100] * 25))["session_high"]
    assert s["reliable"] is False and set(s) == {"reliable", "note"}
    assert movestate.move_state([], _daily([100] * 5))["session_high"]["reliable"] is False


def test_the_usual_time_of_the_high_counts_sessions_that_peaked_later_than_now():
    history = _past_sessions(["10:00"] * 8 + ["15:00"] * 4)
    prices = [100 + i * 0.01 for i in range(150)]                 # this session reaches 11:59
    s = movestate.move_state(_intraday(prices), _daily([100] * 25), history=history)["session_high"]
    habit = s["usual_high_time"]
    assert habit["reliable"] is True and habit["sessions"] == 12
    assert habit["compared_with"] == "11:59" and habit["set_later_than_now"] == 4
    assert habit["median_high_at"] == "10:00"
    assert habit["highs"][0] == {"date": "2026-09-10", "high_at": "10:00"}


def test_too_little_intraday_history_withholds_the_usual_time():
    history = _past_sessions(["10:00"] * 5)
    s = movestate.move_state(_intraday([100 + i * 0.01 for i in range(150)]), _daily([100] * 25),
                             history=history)["session_high"]
    assert s["usual_high_time"]["reliable"] is False and s["usual_high_time"]["sessions"] == 5
    # Without a history request the field is simply absent of a reading.
    s = movestate.move_state(_intraday([100 + i * 0.01 for i in range(150)]), _daily([100] * 25))["session_high"]
    assert s["usual_high_time"] is None


def test_no_field_names_a_verdict():
    s = movestate.move_state(_intraday([100 + i * 0.05 for i in range(150)]), _daily([100] * 25),
                             history=_past_sessions(["10:00"] * 12), indicators_reliable=True)

    def keys(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from keys(v)
        elif isinstance(x, list):
            for v in x:
                yield from keys(v)
    banned = ("verdict", "score", "rating", "signal", "recommend", "peaked_yes", "is_top")
    assert not [k for k in keys(s) if any(b in k for b in banned)]


def test_indicator_arrays_ride_on_their_own_bars():
    series = {"bars": [{"t": "a", "c": 1}, {"t": "b", "c": 2}], "rsi_9": [None, 55.0], "macd_hist": [0.1]}
    got = movestate.with_indicators(series)
    assert got[1]["_rsi"] == 55.0 and got[1]["_macd_hist"] is None and got[0]["_macd_hist"] == 0.1
