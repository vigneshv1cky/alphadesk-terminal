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
                 {"symbols": ["BANK"], "form": "424B2", "items": [], "filed_at": "2026-10-02T17:00:00-04:00", "role": "filer"},   # a structured note
                 {"symbols": ["OFFR"], "form": "424B5", "items": [], "filed_at": "2026-10-02T17:00:00-04:00", "role": "filer"},
                 {"symbols": ["CCC"], "form": "SCHEDULE 13D", "items": [], "filed_at": "2026-10-02T18:00:00-04:00", "role": "subject"},
                 {"symbols": ["DDD"], "form": "10-Q", "items": [], "filed_at": "2026-10-02T18:00:00-04:00"}],
        halts=[{"symbol": "EEE", "today": True, "resumed": False, "reason_code": "T1", "halted_at": "2026-10-02T10:00"}],
        movers=[{"symbol": "AAA", "change_pct": 12.5}],
        board=["CCC", "ZZZ"], target_sessions=monday)
    got = {r["symbol"]: r for r in rows}
    assert set(got) == {"AAA", "FRI", "UNK", "CCC", "EEE", "OFFR"}           # a bank's 424B2 note prospectus is no catalyst          # FRIB already traded; TUE is a later session; a 10-Q is no catalyst
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


def test_the_data_plan_is_stated_in_plain_terms():
    from alphadesk.mcp_server import freshness_from_plan
    free = freshness_from_plan({"realtime": False, "stocks": "iex", "chart_delay_minutes": 15})
    assert free["known"] and free["realtime"] is False and "IEX" in free["note"] and free["chart_delay_minutes"] == 15
    paid = freshness_from_plan({"realtime": True, "stocks": "sip", "chart_delay_minutes": 0})
    assert paid["realtime"] is True and "consolidated" in paid["note"]
    assert freshness_from_plan(None)["known"] is False


def test_parallel_calls_keep_the_calling_readers_identity_and_the_order():
    from alphadesk.identity import request_user, reset_request_user, set_request_user
    from alphadesk.mcp_server import _parallel
    held = set_request_user("reader-1")
    try:
        got = _parallel(lambda n: (n, request_user()), [3, 1, 2])
        assert got == [(3, "reader-1"), (1, "reader-1"), (2, "reader-1")]
        bad = _parallel(lambda n: 1 / n, [1, 0, 2])
        assert bad[0] == 1.0 and isinstance(bad[1], ZeroDivisionError) and bad[2] == 0.5   # one failure does not stop the rest
    finally:
        reset_request_user(held)


def test_every_daily_history_request_asks_for_daily_bars():
    """2026-10-03: a chart range opens on its FINEST bar (5-minute for a month,
    hourly for a quarter), so tools that treated the answer as daily sessions
    computed ranges, volumes and "sessions" from intraday bars (SVRN's 90 days
    read as 1,171 sessions). Each daily-history request must say interval 1d."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "alphadesk" / "mcp_server.py").read_text()
    calls = re.findall(r"dashboard\.api_chart,[^\n]*", src)
    assert calls and all('interval="1d"' in c for c in calls), calls


def test_price_history_asks_for_daily_bars(monkeypatch):
    from alphadesk import mcp_server
    from alphadesk.app import dashboard
    seen = {}

    def fake_chart(symbol, days=2, range=None, interval=None, **kw):
        seen["interval"] = interval
        return {"bars": [{"t": f"2026-09-{d:02d}T00:00:00+00:00", "c": 10.0 + d, "h": 11.0 + d, "l": 9.0 + d, "v": 1000}
                         for d in (1, 2, 3, 4, 5, 6, 7)], "vendor": "fake"}
    monkeypatch.setattr(dashboard, "api_chart", fake_chart)
    got = mcp_server.price_history("SVRN", "1M")
    assert seen["interval"] == "1d" and got["sessions"] == 7


def test_the_agent_door_answers_to_every_name_the_server_is_given(monkeypatch):
    from alphadesk.app import agent_access
    monkeypatch.setenv("ALPHADESK_BASE_URL", "https://one.example.app")
    monkeypatch.setenv("ALPHADESK_ALLOWED_HOSTS", "two.example.app, three.example.app:8443")
    hosts, origins = agent_access.allowed_hosts()
    assert {"one.example.app", "two.example.app", "two.example.app:*", "three.example.app:8443"} <= set(hosts)
    assert "https://two.example.app" in origins and "https://one.example.app" in origins


def test_a_companys_own_words_name_the_crypto_it_holds_and_the_companies_it_mentions():
    from alphadesk.desk import related
    text = ("OceanPal Inc. (NASDAQ: SVRN) operates the first publicly traded NEAR Protocol treasury, accumulating NEAR tokens, "
            "generating yield through staking. The sale to Sezali Inc. (NASDAQ: SEZL) was settled in securities; "
            "no NEAR was sold. The word sui generis is not a coin.")
    got = related.extract_related([{"source": "0000-26-1", "text": text}], "SVRN", ["OceanPal"])
    assets = {c["asset"]: c for c in got["crypto"]}
    assert "NEAR" in assets and assets["NEAR"]["mentions"] >= 2 and assets["NEAR"]["first_source"] == "0000-26-1"
    assert "SUI" not in assets                                           # "sui generis" is not the coin
    assert [c["ticker"] for c in got["companies"]] == ["SEZL"]           # its own ticker is left out
    assert related.extract_related([{"source": "x", "text": "ABC treasury is a heading."}], "SVRN")["crypto"] == []
    lst = related.extract_related([{"source": "story:1", "text": "Here are 20 stocks: Foo Inc. (NASDAQ: FOO) rose."}], "SVRN")
    assert lst["companies"] == []                                        # a story's tickers are a movers list, not a tie
