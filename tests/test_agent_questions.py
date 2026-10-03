"""2026-10-03: the three tools for "has it died down", "which could move" and
"is it priced in" — measurements and evidence, never a verdict."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from alphadesk.desk import candidates, movestate, pricedin

NY = ZoneInfo("America/New_York")


def _intraday(prices, day="2026-09-30", start=(9, 30), vol=1000):
    t = datetime(*map(int, day.split("-")), *start, tzinfo=NY)
    out = []
    for i, p in enumerate(prices):
        out.append({"t": (t + timedelta(minutes=i)).astimezone(timezone.utc).isoformat(),
                    "o": p, "h": p * 1.001, "l": p * 0.999, "c": p, "v": vol})
    return out


def _daily(closes, end="2026-09-29"):
    d, rows = date.fromisoformat(end) - timedelta(days=len(closes) - 1), []
    for c in closes:
        rows.append({"t": d.isoformat(), "o": c, "h": c * 1.02, "l": c * 0.98, "c": c, "v": 10_000})
        d += timedelta(days=1)
    return rows


def test_a_spike_that_gave_back_most_of_its_run_reads_as_faded_and_turned():
    up = [100 + i * 0.1 for i in range(120)]          # 100 -> 111.9 over two hours
    down = [111.9 - i * 0.12 for i in range(1, 121)]  # then back to 97.5
    s = movestate.move_state(_intraday(up + down), _daily([100] * 25))
    assert s["reliable"] and s["session"] == "2026-09-30"
    assert s["prices"]["prev_close"] == 100
    assert s["given_back_from_high_pct"] > 90
    assert s["direction"]["session"] == "down" and s["direction"]["last_60min"] == "down"
    assert s["minutes_since_high"] >= 115


def test_a_last_hour_against_the_day_is_flagged():
    prices = [100 + i * 0.05 for i in range(200)] + [110 - i * 0.05 for i in range(1, 100)]
    s = movestate.move_state(_intraday(prices), _daily([100] * 25))
    assert s["direction"]["session"] == "up" and s["direction"]["last_60min"] == "down"
    assert s["direction"]["last_hour_runs_against_session"] is True


def test_too_few_bars_is_not_read():
    s = movestate.move_state(_intraday([100, 101, 102]), _daily([100] * 25))
    assert s["reliable"] is False


def test_no_bars_gives_the_daily_footing_only():
    s = movestate.move_state([], _daily([100, 101, 103, 106]))
    assert s["session"] is None and s["daily"]["consecutive_closes"] == 3


def test_the_next_session_skips_weekends_and_holidays_and_follows_the_clock():
    from alphadesk.desk import sessions as cal
    ny = ZoneInfo("America/New_York")
    at = lambda *a: datetime(*a, tzinfo=ny)  # noqa: E731
    assert cal.upcoming_session(at(2026, 10, 2, 19, 0)) == date(2026, 10, 5)     # Friday evening -> Monday
    assert cal.upcoming_session(at(2026, 10, 3, 12, 0)) == date(2026, 10, 5)     # Saturday -> Monday
    assert cal.upcoming_session(at(2026, 10, 5, 8, 0)) == date(2026, 10, 5)      # Monday before the open -> today
    assert cal.upcoming_session(at(2026, 10, 5, 10, 0)) == date(2026, 10, 6)     # Monday after the open -> tomorrow
    assert cal.next_session(date(2026, 11, 25)) == date(2026, 11, 27)            # Thanksgiving closed
    assert cal.next_session(date(2026, 7, 2)) == date(2026, 7, 6)                # July 4 is a Saturday: Friday the 3rd closed
    assert not cal.is_session(date(2026, 4, 3)) and not cal.is_session(date(2026, 12, 25))   # Good Friday, Christmas
    assert cal.is_session(date(2027, 12, 31))                                    # a Saturday New Year's closes nothing
    assert cal.last_close(at(2026, 10, 3, 12, 0)) == at(2026, 10, 2, 16, 0)


def test_candidates_collect_dated_evidence_for_the_next_session():
    monday = [date(2026, 10, 5)]
    rows = candidates.rank(
        earnings=[{"symbol": "AAA", "report_date": "2026-10-05", "time": "bmo", "eps_estimate": 1.2},     # before the open Monday
                  {"symbol": "FRI", "report_date": "2026-10-02", "time": "amc"},                          # after Friday's close -> Monday
                  {"symbol": "FRIB", "report_date": "2026-10-02", "time": "bmo"},                         # Friday morning: already traded
                  {"symbol": "UNK", "report_date": "2026-10-02"},                                         # no timing: could be Monday
                  {"symbol": "TUE", "report_date": "2026-10-06", "time": "bmo"}],                         # a later session
        filings=[{"symbols": ["AAA"], "form": "8-K", "items": [{"item": "1.01"}], "filed_at": "2026-10-02T17:00:00-04:00"},
                 {"symbols": ["CCC"], "form": "SCHEDULE 13D", "items": [], "filed_at": "2026-10-02T18:00:00-04:00", "role": "subject"},
                 {"symbols": ["DDD"], "form": "10-Q", "items": [], "filed_at": "2026-10-02T18:00:00-04:00"}],
        halts=[{"symbol": "EEE", "today": True, "resumed": False, "reason_code": "T1", "halted_at": "2026-10-02T10:00"}],
        movers=[{"symbol": "AAA", "change_pct": 12.5}],
        board=["CCC", "ZZZ"], target_sessions=monday)
    got = {r["symbol"]: r for r in rows}
    assert set(got) == {"AAA", "FRI", "UNK", "CCC", "EEE"}          # FRIB already traded; TUE is a later session; a 10-Q is no catalyst
    assert got["AAA"]["evidence_weight"] == 5 and got["AAA"]["already_moved_pct"] == 12.5
    assert "timing not stated" in got["UNK"]["evidence"][0]["detail"]
    assert got["CCC"]["on_board"] is True and got["CCC"]["evidence_weight"] == 3
    assert rows[0]["symbol"] == "AAA"
    two = candidates.rank(earnings=[{"symbol": "TUE", "report_date": "2026-10-06", "time": "bmo"}], filings=[], halts=[],
                          movers=[], board=[], target_sessions=[date(2026, 10, 5), date(2026, 10, 6)])
    assert two[0]["evidence"][0]["kind"] == "earnings_in_horizon"   # in the window, but not the first session


def test_report_reactions_measure_the_move_across_each_report():
    closes = [100.0] * 30 + [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
    daily = _daily(closes, end="2026-09-29")                      # flat tape ...
    by_day = {b["t"]: b for b in daily}
    report_day = "2026-09-10"
    for k in range(daily.index(by_day[report_day]), len(daily)):  # ... that steps +10% on the report day
        daily[k]["c"] = 110.0
    reports = [{"date": report_day, "surprise_pct": 5.0}, {"date": "2026-12-01", "upcoming": True}]
    past = pricedin.report_reactions(reports, daily, today="2026-10-01")
    assert len(past) == 1 and past[0]["reaction_two_session_pct"] == 10.0 and past[0]["report_day_pct"] == 10.0
    view = pricedin.priced_in_view("XYZ", reports, daily, "2026-10-01", since="2026-09-09",
                                   targets={"low": 90, "mean": 121, "high": 140})
    assert view["typical_report_move_pct"] == 10.0
    assert view["move_since_pct"] == 10.0 and view["move_since_in_typical_report_moves"] == 1.0
    assert view["next_report"] == {"date": "2026-12-01", "days_away": 61}
    assert view["analyst_targets"]["mean_vs_last_pct"] == 10.0
    assert "expectations" in view["what_this_cannot_tell"]


def test_a_gainer_is_laid_beside_its_own_news_filings_and_shape():
    from alphadesk.desk import focus
    mover = {"symbol": "AAA", "name": "Alpha Inc", "change_pct": 31.0, "price": 5.1, "volume": 900000}
    articles = [
        {"published_at": "2026-10-02T13:00:00+00:00", "title": "Alpha wins contract", "kind": "release", "tickers": ["AAA"]},
        {"published_at": "2026-10-02T14:00:00+00:00", "title": "Alpha prices offering", "kind": "offering", "tickers": ["AAA"]},
        {"published_at": "2026-10-02T15:00:00+00:00", "title": "12 Industrials Moving", "kind": "movers", "tickers": list("ABCDEFGHIJKL")},
    ]
    filings = [{"form": "424B5", "filed_at": "2026-10-02T09:00:00-04:00"}, {"form": "8-K", "filed_at": "2026-10-02T08:00:00-04:00"}]
    shape = {"reliable": True, "given_back_from_high_pct": 62.0, "last_60min_change_pct": -3.0,
             "direction": {"last_60min": "down"}, "volume": {"vs_median_daily": 3.4}}
    row = focus.build_row(mover, articles, filings, halted=True, shape=shape)
    assert row["news"]["own"] == 2 and row["news"]["named_in_lists"] == 1
    assert row["news"]["by_kind"] == {"release": 1, "offering": 1}
    assert {"story_of_its_own", "named_in_list_stories", "offering_story", "offering_filing", "material_8k", "halted_today",
            "given_back_over_half_of_swing", "last_hour_down", "volume_over_2x_usual"} <= set(row["flags"])
    assert "still_near_the_high" not in row["flags"]


def test_a_gainer_with_no_news_and_an_unreliable_shape_says_only_what_it_knows():
    from alphadesk.desk import focus
    row = focus.build_row({"symbol": "BBB", "change_pct": 18.0}, [], [], halted=False,
                          shape={"reliable": False, "given_back_from_high_pct": 90})
    assert row["flags"] == ["no_story_of_its_own"]              # a shape that is not reliable raises no flag


def test_the_news_scan_groups_by_name_and_skips_list_stories():
    from alphadesk.desk import focus
    arts = [
        {"article_id": "1", "published_at": "2026-10-02T13:00:00+00:00", "title": "Alpha prices offering", "kind": "offering", "tickers": ["AAA"]},
        {"article_id": "2", "published_at": "2026-10-02T15:00:00+00:00", "title": "Alpha wins contract", "kind": "release", "tickers": ["AAA", "BBB"]},
        {"article_id": "3", "published_at": "2026-10-02T14:00:00+00:00", "title": "Beta upgraded", "kind": "rating", "tickers": ["BBB"]},
        {"article_id": "4", "published_at": "2026-10-02T16:00:00+00:00", "title": "12 Industrials Moving", "kind": "movers", "tickers": list("ABCDEFGHIJKL")},
    ]
    got = focus.scan_news(arts)
    assert [r["symbol"] for r in got] == ["AAA", "BBB"]               # two stories each, the same newest time: insertion order holds
    assert got[0]["stories"] == 2 and got[0]["by_kind"] == {"release": 1, "offering": 1}
    assert [r["symbol"] for r in focus.scan_news(arts, kinds={"offering"})] == ["AAA"]
    assert focus.scan_news(arts, min_stories=3) == []
    assert all(r["symbol"] not in set("CDEFGHIJKL") for r in got)       # the list story names none of them


def test_pre_trade_facts_are_plain_arithmetic():
    from alphadesk.desk import tradecontext as tc
    assert tc.spread(10.00, 10.10) == {"bid": 10.0, "ask": 10.1, "spread": 0.1, "spread_pct": 0.995}
    assert tc.spread(10.1, 10.0) is None and tc.spread(None, 10) is None          # crossed or missing: no spread claimed
    daily = [{"c": 10.0, "v": 100_000}] * 25
    liq = tc.liquidity(daily, 10.0, today_volume=250_000)
    assert liq["median_daily_shares"] == 100_000 and liq["median_daily_dollars"] == 1_000_000
    assert liq["today_vs_median"] == 2.5 and liq["shares_per_1pct_of_median_day"] == 1000
    bars = [{"c": 10, "h": 10, "l": 10, "v": 100}, {"c": 12, "h": 12, "l": 12, "v": 300}]
    assert tc.vwap(bars) == 11.5
    lv = tc.levels(11.0, vwap=10.0, none=None)
    assert lv == {"vwap": {"price": 10.0, "last_vs_level_pct": 10.0}}
    assert tc.size_for(20.0, 100, 5) == {"risk_dollars": 100, "stop_distance_pct": 5, "loss_per_share": 1.0,
                                         "shares": 100, "position_dollars": 2000.0}
    assert tc.size_for(20.0, 0, 5) is None and tc.size_for(None, 100, 5) is None
