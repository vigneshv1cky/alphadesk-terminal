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


def test_candidates_collect_dated_evidence_and_mark_what_already_moved():
    today = date(2026, 10, 5)
    rows = candidates.rank(
        earnings=[{"symbol": "AAA", "report_date": "2026-10-06", "eps_estimate": 1.2},
                  {"symbol": "BBB", "report_date": "2026-10-08"},
                  {"symbol": "OLD", "report_date": "2026-10-01"}],
        filings=[{"symbols": ["AAA"], "form": "8-K", "items": [{"item": "1.01"}], "filed_at": "2026-10-05T08:00:00-04:00"},
                 {"symbols": ["CCC"], "form": "SCHEDULE 13D", "items": [], "filed_at": "2026-10-04T10:00:00-04:00", "role": "subject"},
                 {"symbols": ["DDD"], "form": "10-Q", "items": [], "filed_at": "2026-10-04T10:00:00-04:00"}],
        halts=[{"symbol": "EEE", "today": True, "resumed": False, "reason_code": "T1", "halted_at": "2026-10-05T10:00"}],
        movers=[{"symbol": "AAA", "change_pct": 12.5}],
        board=["CCC", "ZZZ"], today=today, horizon_days=3)
    got = {r["symbol"]: r for r in rows}
    assert set(got) == {"AAA", "BBB", "CCC", "EEE"}              # a 10-Q is no catalyst; a past report is not upcoming
    assert got["AAA"]["evidence_weight"] == 5 and got["AAA"]["already_moved_pct"] == 12.5
    assert got["BBB"]["evidence_weight"] == 2                    # three days out: inside the horizon, not "soon"
    assert got["CCC"]["on_board"] is True and got["CCC"]["evidence_weight"] == 3
    assert [r["symbol"] for r in rows][0] == "AAA"


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
