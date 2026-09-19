"""The Nasdaq calendar pull: a failed fetch proves nothing, an empty day is
an answer, and a row says whether the company named its time."""
from alphadesk.ingest import earnings as cal






def _row(sym, date, **kw):
    base = {"symbol": sym, "report_date": date, "session": "DAY", "confirmed": False,
            "eps_estimate": None, "eps_actual": None, "estimate_count": None,
            "market_cap": None, "company_name": None}
    base.update(kw)
    return base


class TestUnion:
    def test_a_company_nasdaq_lacks_is_added_with_its_source(self):
        out = cal.union_calendars([_row("KR", "2026-09-11")],
                                  [dict(_row("ALOT", "2026-09-10"), source="finnhub")])
        by = {r["symbol"]: r for r in out}
        assert by["KR"]["sources"] == "nasdaq"
        assert by["ALOT"]["sources"] == "finnhub" and by["ALOT"]["report_date"] == "2026-09-10"

    def test_the_same_event_within_three_days_is_not_doubled(self):
        out = cal.union_calendars([_row("KR", "2026-09-11")],
                                  [dict(_row("KR", "2026-09-12", confirmed=True, session="BMO", eps_estimate=1.05), source="finnhub")])
        assert len(out) == 1
        r = out[0]
        assert r["report_date"] == "2026-09-11"          # Nasdaq's date stands
        assert r["sources"] == "finnhub,nasdaq"
        assert r["confirmed"] is True and r["session"] == "BMO" and r["eps_estimate"] == 1.05

    def test_a_different_quarter_is_a_second_row(self):
        out = cal.union_calendars([_row("GNS", "2026-09-10")],
                                  [dict(_row("GNS", "2026-10-01"), source="finnhub")])
        assert sorted(r["report_date"] for r in out) == ["2026-09-10", "2026-10-01"]





class TestMovedReports:
    def test_a_company_on_two_dates_within_three_days_keeps_one(self):
        kept, dropped = cal.collapse_moved([_row("CMCM", "2026-09-10"), _row("CMCM", "2026-09-11")])
        assert [r["report_date"] for r in kept] == ["2026-09-11"]      # the later date, a postponement
        assert dropped == [("CMCM", "2026-09-10")]

    def test_a_named_time_outranks_a_later_date(self):
        kept, dropped = cal.collapse_moved([_row("KR", "2026-09-11", confirmed=True, session="BMO"), _row("KR", "2026-09-12")])
        assert [r["report_date"] for r in kept] == ["2026-09-11"] and dropped == [("KR", "2026-09-12")]

    def test_two_quarters_apart_are_two_reports(self):
        kept, dropped = cal.collapse_moved([_row("GNS", "2026-09-10"), _row("GNS", "2026-10-01")])
        assert len(kept) == 2 and dropped == []



class TestFreshness:
    def test_a_source_with_the_actual_fills_a_row_that_lacks_it(self):
        out = cal.union_calendars([_row("KR", "2026-09-11", eps_estimate=1.05)],
                                  [dict(_row("KR", "2026-09-11", eps_actual=1.09), source="finnhub")])
        r = out[0]
        assert r["eps_actual"] == 1.09 and r["surprise_pct"] == 3.81 and r["confirmed"] is True




def test_edgar_acceptance_time_is_eastern_despite_the_z():
    from alphadesk.ingest.edgar import _accepted_at
    assert _accepted_at("2026-09-11T10:59:48.000Z") == "2026-09-11T06:59:48-04:00"   # Kroger, 6:59 AM ET
    assert _accepted_at("2026-09-10T20:06:14.000Z") == "2026-09-10T16:06:14-04:00"   # Adobe, after the close
    assert _accepted_at("2026-01-15T21:05:23.000Z") == "2026-01-15T16:05:23-05:00"   # winter offset
    assert _accepted_at(None) is None and _accepted_at("garbage") is None
