"""The Nasdaq calendar pull: a failed fetch proves nothing, an empty day is
an answer, and a row says whether the company named its time."""
from alphadesk.ingest import earnings as cal
from alphadesk.ingest import earnings_calendar as ec






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


# ── Evidence ordering (2026-09-27, the owner: "order by correctness") ───────

def _ev_row(sym, **kw):
    r = {"symbol": sym, "report_date": "2026-09-30", "sources": "fmp"}
    r.update(kw)
    return r


def test_a_filed_report_outranks_every_forecast():
    """A report the SEC already has is not a forecast. Whatever any calendar
    said about the day, it happened."""
    filed = _ev_row("AAA", date_from_edgar=True, sources="fmp")
    announced = _ev_row("BBB", announcement={"date": "2026-09-30"}, sources="fmp,finnhub,alphavantage")
    assert ec.evidence_of(filed) == ec.EVIDENCE_REPORTED
    assert ec.evidence_rank(filed) < ec.evidence_rank(announced)


def test_the_company_outranks_its_calendars():
    announced = _ev_row("AAA", announcement={"date": "2026-09-30"})
    three = _ev_row("BBB", sources="fmp,finnhub,alphavantage")
    assert ec.evidence_of(announced) == ec.EVIDENCE_ANNOUNCED
    assert ec.evidence_rank(announced) < ec.evidence_rank(three)


def test_one_vendors_confirmed_does_not_beat_two_vendors_agreeing():
    """MEASURED on a live week: AMTD Digital, Tudor Gold and Scottie Resources
    all arrived marked confirmed from FMP ALONE. One vendor's flag is a claim;
    two independent calendars agreeing is corroboration."""
    claimed = _ev_row("HKD", confirmed=True, sources="fmp")
    agreed = _ev_row("MTN", confirmed=False, sources="finnhub,alphavantage")
    assert ec.evidence_of(claimed) == ec.EVIDENCE_SINGLE
    assert ec.evidence_of(agreed) == ec.EVIDENCE_CORROBORATED
    assert ec.evidence_rank(agreed) < ec.evidence_rank(claimed)


def test_vendor_count_reads_the_joined_sources():
    assert ec.vendor_count(_ev_row("A", sources="fmp,finnhub, alphavantage")) == 3
    assert ec.vendor_count(_ev_row("A", sources="fmp,fmp")) == 1
    assert ec.vendor_count(_ev_row("A", sources="")) == 0
    assert ec.vendor_count({"symbol": "A"}) == 0


def test_an_untraded_second_class_cannot_head_a_day():
    """The fault this replaced: McCormick's non-voting class ($13.2B, $1.1M a
    day) outranked McCormick itself and sat above AEHR ($3.4B, $254M a day).
    A second class is exactly the row one vendor lists alone, so evidence
    sinks it with no special case for share classes."""
    rows = [
        _ev_row("MKC-V", market_cap=13.2e9, liquidity=1.1e6, sources="fmp"),
        _ev_row("AEHR", market_cap=3.4e9, liquidity=253.8e6, sources="fmp,finnhub"),
    ]
    rows.sort(key=lambda r: (r["report_date"], ec.evidence_rank(r),
                             r.get("market_cap") is None, -(r.get("market_cap") or 0),
                             -(r.get("liquidity") or 0), r["symbol"]))
    assert [r["symbol"] for r in rows] == ["AEHR", "MKC-V"]


def test_size_still_orders_inside_a_tier():
    """The 2026-09-14 call is kept where it works: among equally evidenced
    reports, the biggest company is still read first."""
    rows = [
        _ev_row("SMALL", market_cap=1e9, sources="fmp,finnhub"),
        _ev_row("BIG", market_cap=100e9, sources="fmp,finnhub"),
    ]
    rows.sort(key=lambda r: (r["report_date"], ec.evidence_rank(r),
                             r.get("market_cap") is None, -(r.get("market_cap") or 0),
                             -(r.get("liquidity") or 0), r["symbol"]))
    assert [r["symbol"] for r in rows] == ["BIG", "SMALL"]


def test_an_actual_in_hand_counts_as_reported():
    """CAUGHT ON SCREEN (2026-09-28). The first version tested only for a
    joined 8-K, so Inventiva sat ELEVENTH on its own report day carrying a
    -42.52% surprise — below three companies that had not reported at all —
    and NETSOL fourteenth with +357%. A vendor's actual arrives before the
    filing is found, and a number in hand is not a forecast."""
    reported = _ev_row("IVA", eps_actual=-0.29, surprise_pct=-42.52, sources="fmp")
    pending = _ev_row("MTN", sources="fmp,finnhub,alphavantage")
    assert ec.evidence_of(reported) == ec.EVIDENCE_REPORTED
    assert ec.evidence_rank(reported) < ec.evidence_rank(pending)


def test_a_placeholder_actual_is_not_a_report():
    """A placeholder is moved to placeholder_actual upstream and eps_actual
    set back to None, so the tier cannot be fooled by one."""
    ghost = _ev_row("NB", eps_actual=None, placeholder_actual=0.15, sources="fmp")
    assert ec.evidence_of(ghost) == ec.EVIDENCE_SINGLE
