"""The calendar's forward accuracy log (2026-09-14): what each vendor said
ahead of a report, scored against EDGAR's release day and clock."""

from alphadesk.ingest import calendar_accuracy as ca
from alphadesk.ingest import earnings_calendar as uc
from alphadesk.ingest import edgar, edgar_releases


def test_forecast_rows_keep_four_weeks_ahead_one_per_company():
    rows = [{"symbol": "KR", "report_date": "2026-09-11", "confirmed": False},
            {"symbol": "KR", "report_date": "2026-09-12", "confirmed": True, "session": "BMO"},
            {"symbol": "OLD", "report_date": "2026-09-01"},
            {"symbol": "FAR", "report_date": "2026-11-30"},
            {"symbol": "ADBE", "report_date": "2026-09-10"},
            {"symbol": "ADBE", "report_date": "2026-09-17"}]
    got = {r["symbol"]: r["report_date"] for r in uc.forecast_rows(rows, "2026-09-10")}
    assert got == {"KR": "2026-09-12", "ADBE": "2026-09-10"}          # confirmed beats earlier; earliest otherwise


def test_fmp_dates_lead_and_finnhub_supplies_the_session():
    fmp = [{"symbol": "OCC", "report_date": "2026-09-09", "session": "DAY", "confirmed": False, "eps_estimate": 0.2, "eps_actual": None}]
    fin = [{"symbol": "OCC", "report_date": "2026-09-08", "session": "BMO", "confirmed": True, "eps_estimate": 0.202, "eps_actual": None}]
    [row] = uc.combine([("fmp", fmp), ("finnhub", fin)])
    assert row["report_date"] == "2026-09-09" and row["session"] == "BMO" and row["confirmed"] is True
    from alphadesk.providers.catalogue import SURFACES
    assert [n for n, _ in SURFACES["earnings_calendar"].vendors][:2] == ["fmp", "finnhub"]


def test_scores_date_and_session_at_each_horizon():
    truth = {"OCC": ("2026-09-09", "BMO"), "KR": ("2026-09-11", "BMO"), "NEW": ("2026-09-10", "AMC")}
    fc = [
        # a week out finnhub had OCC a day early and KR right; a day out both right
        {"vendor": "finnhub", "symbol": "OCC", "captured_on": "2026-09-01", "report_date": "2026-09-08", "session": "BMO", "confirmed": 1},
        {"vendor": "finnhub", "symbol": "KR", "captured_on": "2026-09-01", "report_date": "2026-09-11", "session": "AMC", "confirmed": 1},
        {"vendor": "finnhub", "symbol": "OCC", "captured_on": "2026-09-08", "report_date": "2026-09-09", "session": "BMO", "confirmed": 1},
        {"vendor": "finnhub", "symbol": "KR", "captured_on": "2026-09-08", "report_date": "2026-09-11", "session": "BMO", "confirmed": 1},
    ]
    days = {"finnhub": ["2026-09-01", "2026-09-08"]}
    got = ca.score(truth, fc, days, horizons=(1, 7))["finnhub"]
    week = got[7]                                    # OCC and KR have a capture a week out; NEW (9/10) does not until 9/3 → 9/1
    assert week["counted"] == 3 and week["listed"] == 2 and week["date_exact"] == 1 and week["date_within_1"] == 2
    assert week["session_named"] == 2 and week["session_right"] == 1
    day = got[1]
    assert day["counted"] == 3 and day["listed"] == 2 and day["date_exact"] == 2 and day["session_right"] == 2


def test_truth_keeps_same_day_common_stock_releases_with_a_clock():
    rel = {"OCC": [{"file_date": "2026-09-11", "event_date": "2026-09-09", "accepted_at": "2026-09-11T16:15:22-04:00", "accession": "a"}],
           "ADBE": [{"file_date": "2026-09-10", "event_date": "2026-09-10", "accepted_at": "2026-09-10T16:06:14-04:00", "accession": "b"}],
           "KR": [{"file_date": "2026-09-11", "event_date": "2026-09-11", "accepted_at": "2026-09-11T06:59:48-04:00", "accession": "c"}],
           "BNCWZ": [{"file_date": "2026-09-11", "event_date": "2026-09-11", "accepted_at": "2026-09-11T07:00:00-04:00", "accession": "d", "cik": "9"}],
           "BNC": [{"file_date": "2026-09-11", "event_date": "2026-09-11", "accepted_at": "2026-09-11T16:03:00-04:00", "accession": "d", "cik": "9"}]}
    # OCC filed late (no clock); BNCWZ is BNC's warrant, scored once as BNC
    assert ca.truth_from_releases(rel, "2026-09-01", "2026-09-14") == {
        "ADBE": ("2026-09-10", "AMC"), "KR": ("2026-09-11", "BMO"), "BNC": ("2026-09-11", "AMC")}


class _Fmp:
    name = "fmp"
    def earnings_calendar(self, start, end, symbol=None):
        return [{"symbol": "ADBE", "report_date": "2026-09-17", "session": "DAY", "confirmed": False, "eps_estimate": 5.0, "eps_actual": None}]


class _Fin:
    name = "finnhub"
    def earnings_calendar(self, start, end, symbol=None):
        return [{"symbol": "ADBE", "report_date": "2026-09-17", "session": "AMC", "confirmed": True, "eps_estimate": 5.1, "eps_actual": None}]


def test_building_the_calendar_records_each_vendor_and_the_merged_view(store, vendors, monkeypatch):
    import alphadesk.config as config
    from datetime import datetime
    uc._captured.clear()
    vendors(fmp=_Fmp(), finnhub=_Fin())
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"ADBE": "1"})
    monkeypatch.setattr(edgar, "company_title", lambda s: "Adobe")
    monkeypatch.setattr(edgar_releases, "releases_by_symbol", lambda a, b: {})
    monkeypatch.setattr(config, "now_et", lambda: datetime(2026, 9, 14, 9, 0, tzinfo=config.ET))
    uc.rows_between("2026-09-13", "2026-09-19", stats=False)
    got = {r["vendor"]: (r["report_date"], r["session"], r["confirmed"]) for r in store.forecasts_for("u-test", "2026-09-01", "2026-09-30")}
    assert got == {"fmp": ("2026-09-17", "DAY", 0), "finnhub": ("2026-09-17", "AMC", 1), "calendar": ("2026-09-17", "AMC", 1)}
    assert store.forecast_capture_days("u-test") == {"calendar": ["2026-09-14"], "finnhub": ["2026-09-14"], "fmp": ["2026-09-14"]}
    uc._captured.clear()


def test_the_accuracy_route_answers_for_the_reader(client):
    r = client.get("/api/earnings/accuracy?days=14")
    assert r.status_code == 200 and r.json()["horizons"] == [1, 3, 7]


def test_daily_capture_covers_active_readers_with_a_calendar_vendor(store):
    from datetime import datetime, timedelta, timezone
    store.create_user("fresh", "a@b.c", "sso-only")
    store.create_user("away", "d@e.f", "sso-only")
    store.create_user("nokey", "g@h.i", "sso-only")
    store.create_user("alpaca-only", "j@k.l", "sso-only")
    store.set_user_key("fresh", "prices", "fmp", "sealed", "xxxx")
    store.set_user_key("away", "prices", "finnhub", "sealed", "xxxx")
    store.set_user_key("alpaca-only", "prices", "alpaca", "sealed", "xxxx")
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE users SET last_seen_at = ? WHERE user_id IN ('fresh', 'nokey', 'alpaca-only')",
                     (datetime.now(timezone.utc).isoformat(),))
        conn.execute("UPDATE users SET last_seen_at = ? WHERE user_id = 'away'", (old,))
    assert store.forecast_capture_users(168) == ["fresh"]


def test_capture_daily_records_each_vendor_under_the_reader(store, vendors, monkeypatch):
    import alphadesk.config as config
    from datetime import datetime
    vendors(fmp=_Fmp(), finnhub=_Fin())
    monkeypatch.setattr(config, "now_et", lambda: datetime(2026, 9, 14, 7, 0, tzinfo=config.ET))
    warmed = []
    monkeypatch.setattr(uc, "rows_between", lambda s, e, stats=True: warmed.append((s, e)) or [])
    counts = uc.capture_daily("u-test")
    assert warmed == [("2026-09-13", "2026-09-19")]                 # this week warmed after the capture
    assert counts == {"fmp": 1, "finnhub": 1, "calendar": 1}
    got = {r["vendor"]: r["session"] for r in store.forecasts_for("u-test", "2026-09-01", "2026-09-30")}
    assert got == {"fmp": "DAY", "finnhub": "AMC", "calendar": "AMC"}
    vendors()                                            # no calendar vendor: nothing, no error
    assert uc.capture_daily("u-test") == {}
