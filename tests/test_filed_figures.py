"""The filed-figures panel: the company's own XBRL, never a verdict."""
from alphadesk.ingest import filed_figures as ff


def test_a_swing_through_zero_has_no_percentage():
    """A company that lost money and now earns it did not improve by some
    percent of a negative base -- that arithmetic reads as a collapse. The
    direction survives where the percentage cannot."""
    assert ff._change(3_759_920, -2_357_288) is None
    assert ff._direction(3_759_920, -2_357_288) == "up"
    # Both negative: a smaller loss is still an improvement, still no percent.
    assert ff._change(-0.39, -0.67) is None
    assert ff._direction(-0.39, -0.67) == "up"
    # Ordinary growth keeps its percentage.
    assert ff._change(20_725_107, 19_484_721) == 6.37
    assert ff._direction(20_725_107, 19_484_721) == "up"
    assert ff._direction(5, 5) == "flat"
    assert ff._change(5, 0) is None
    assert ff._change(None, 5) is None


def test_the_year_ago_quarter_is_matched_by_date_not_by_counting_back():
    """Counting back four rows breaks on a company that skipped or restated a
    filing -- it would silently compare the wrong pair. A 52/53-week fiscal
    calendar also moves the end date a few days a year, so the match is the
    nearest end within tolerance."""
    from datetime import date

    ends = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
    assert ff._nearest(ends, date(2025, 6, 30), ff.YEAR_AGO_TOLERANCE_DAYS) == "2025-06-30"
    # A 52/53-week filer whose quarter ended a few days out still matches.
    assert ff._nearest(["2025-07-03"], date(2026, 7, 1), ff.YEAR_AGO_TOLERANCE_DAYS) is None
    assert ff._nearest(["2025-07-03"], date(2025, 6, 30), ff.YEAR_AGO_TOLERANCE_DAYS) == "2025-07-03"
    # Nothing within a year: no pair rather than a wrong pair.
    assert ff._nearest(["2020-06-30"], date(2025, 6, 30), ff.YEAR_AGO_TOLERANCE_DAYS) is None


def test_a_quarter_too_old_for_the_report_is_marked_not_dressed_up(monkeypatch):
    """MEASURED on thirteen companies that had just reported: eight had the
    quarter on file at 87-90 days, EON Resources' newest was 271 days old and
    Incannex's 452. Showing those beside a fresh report would say the company
    filed figures it has not filed."""
    fake = {"metrics": [{"id": "revenue", "label": "Revenue", "unit": "currency"}],
            "series": {"revenue": [{"t": "2024-12-31", "v": 3_710_679.0},
                                   {"t": "2025-12-31", "v": 3_424_477.0}]}}
    monkeypatch.setattr("alphadesk.ingest.edgar_financials.fundamentals_series",
                        lambda *a, **k: fake)

    stale = ff.filed_quarter("EONR", "2026-09-28")
    assert stale["period_end"] == "2025-12-31"
    assert stale["prior_end"] == "2024-12-31"
    assert stale["lag_days"] == 271
    assert stale["covers_report"] is False
    assert "not filed yet" in stale["note"]
    # The figures are still returned -- with the period named, they are true.
    assert stale["metrics"][0]["value"] == 3_424_477.0

    fresh = ff.filed_quarter("EONR", "2026-01-31")
    assert fresh["covers_report"] is True and fresh["note"] is None


def test_an_ifrs_filer_says_so_rather_than_reading_as_silent(monkeypatch):
    """VinFast, Inventiva and NioCorp carry no US-GAAP revenue tag. An empty
    answer must say the SEC holds no US-GAAP figures for this filer, never
    that the company reported nothing (invariant 8's rule about empty panels,
    applied to a keyless source)."""
    monkeypatch.setattr("alphadesk.ingest.edgar_financials.fundamentals_series",
                        lambda *a, **k: {"metrics": [], "series": {}})
    out = ff.filed_quarter("IVA", "2026-09-28")
    assert out["metrics"] == []
    # BOTH GRAINS ARE TRIED before this message can fire, so it is now a narrow
    # claim rather than a catch-all: a 20-F filer reporting in US-GAAP is
    # answered with its annual series (see the test below), and only a genuine
    # IFRS filer or a company that has filed nothing reaches here.
    assert "IFRS" in out["note"] and "annual or quarterly" in out["note"]
    assert out["period_end"] is None


def test_a_filer_with_no_quarters_is_answered_with_its_YEARS(monkeypatch):
    """A FOREIGN PRIVATE ISSUER FILES NO QUARTERS (2026-09-28, found on WEBUY
    Global, whose panels were empty while the SEC held 265 us-gaap tags for
    it). It reports once a year on a 20-F. Asking only for quarters found
    nothing and the panel blamed IFRS for it — which was simply false."""
    annual = {"metrics": [{"id": "revenue", "label": "Revenue", "unit": "currency"}],
              "series": {"revenue": [{"t": "2024-12-31", "v": 50_869_812.0},
                                     {"t": "2025-12-31", "v": 18_834_099.0}]}}

    def series(sym, period="quarterly", **k):
        return {"metrics": [], "series": {}} if period == "quarterly" else annual

    monkeypatch.setattr("alphadesk.ingest.edgar_financials.fundamentals_series", series)
    out = ff.filed_quarter("WBUY", "2026-09-28")
    assert out["period"] == "annual"
    assert out["period_end"] == "2025-12-31" and out["prior_end"] == "2024-12-31"
    assert out["metrics"][0]["change_pct"] == -62.98
    # Its newest filed period is a year old BY DESIGN, so the quarterly window
    # would mark every 20-F filer stale and say its figures were missing.
    assert out["covers_report"] is True and out["note"] is None


def test_a_quarterly_filer_is_not_switched_to_annual(monkeypatch):
    """The fallback fires only where there is no quarterly series at all — a
    10-Q filer must keep its quarters."""
    q = {"metrics": [{"id": "revenue", "label": "Revenue", "unit": "currency"}],
         "series": {"revenue": [{"t": "2025-06-30", "v": 1.0}, {"t": "2026-06-30", "v": 2.0}]}}
    calls = []

    def series(sym, period="quarterly", **k):
        calls.append(period)
        return q if period == "quarterly" else {"metrics": [], "series": {}}

    monkeypatch.setattr("alphadesk.ingest.edgar_financials.fundamentals_series", series)
    out = ff.filed_quarter("NTWK", "2026-09-28")
    assert out["period"] == "quarterly"
    assert calls == ["quarterly"]          # annual is never asked for


def test_margins_move_in_percentage_points_and_only_off_positive_revenue(monkeypatch):
    """A change between two percentages is percentage POINTS. Stated as a
    percent of a percent, a margin going 2% -> 4% becomes '+100%'."""
    fake = {"metrics": [{"id": "revenue", "label": "Revenue", "unit": "currency"},
                        {"id": "net_income", "label": "Net Income", "unit": "currency"}],
            "series": {"revenue": [{"t": "2025-06-30", "v": 100.0}, {"t": "2026-06-30", "v": 200.0}],
                       "net_income": [{"t": "2025-06-30", "v": 2.0}, {"t": "2026-06-30", "v": 8.0}]}}
    monkeypatch.setattr("alphadesk.ingest.edgar_financials.fundamentals_series",
                        lambda *a, **k: fake)
    out = ff.filed_quarter("X", "2026-09-28")
    margin = next(m for m in out["metrics"] if m["id"] == "net_income_margin")
    assert margin["value"] == 4.0 and margin["prior"] == 2.0
    assert margin["change_pp"] == 2.0      # points, not "+100%"
    assert margin["change_pct"] is None
    assert margin["filed"] is False        # derived, and marked as derived
    assert next(m for m in out["metrics"] if m["id"] == "revenue")["filed"] is True


def test_no_verdict_field_is_ever_returned(monkeypatch):
    """Invariant 1, pinned. The panel states figures and their direction; it
    never scores the report. Screener ranking was removed on 2026-08-18 for
    exactly this reason -- if a verdict key appears here, that decision is
    being reversed by accident."""
    fake = {"metrics": [{"id": "revenue", "label": "Revenue", "unit": "currency"}],
            "series": {"revenue": [{"t": "2025-06-30", "v": 1.0}, {"t": "2026-06-30", "v": 2.0}]}}
    monkeypatch.setattr("alphadesk.ingest.edgar_financials.fundamentals_series",
                        lambda *a, **k: fake)
    out = ff.filed_quarter("X", "2026-09-28")
    # "label" is not listed: a metric's display name is legitimately a label.
    banned = {"verdict", "sentiment", "score", "rating", "catalyst", "signal",
              "positive", "negative", "grade", "recommendation"}
    assert not banned & set(out)
    for m in out["metrics"]:
        assert not banned & set(m)
    # And direction is a comparison of two filed figures, not an opinion:
    # the only values it may take are the three arithmetic ones.
    assert {m["direction"] for m in out["metrics"]} <= {"up", "down", "flat", None}


def test_free_cash_flow_is_marked_derived_like_the_margins(monkeypatch):
    """NO COMPANY TAGS FREE CASH FLOW (2026-09-29). It is operating cash flow
    less capital expenditure, computed upstream — and it rode in the filed list
    marked as filed, which said the company reported a figure it never did."""
    fake = {"metrics": [{"id": m, "label": m, "unit": "currency"}
                        for m in ("revenue", "ocf", "fcf")],
            "series": {m: [{"t": "2025-06-30", "v": 10.0}, {"t": "2026-06-30", "v": 20.0}]
                       for m in ("revenue", "ocf", "fcf")}}
    monkeypatch.setattr("alphadesk.ingest.edgar_financials.fundamentals_series",
                        lambda *a, **k: fake)
    out = ff.filed_quarter("X", "2026-09-29")
    by = {m["id"]: m for m in out["metrics"]}
    assert by["fcf"]["filed"] is False
    assert by["revenue"]["filed"] is True and by["ocf"]["filed"] is True
