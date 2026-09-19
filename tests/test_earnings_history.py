"""The report record (2026-09-11): every report, revenue joined to the
quarter it covered, the next scheduled report on top with estimates only,
and the partial providers' EPS-only record in the same shape."""

from alphadesk.ingest.prices import match_report_periods
from alphadesk.providers import prices as pp


def test_reports_claim_the_quarter_they_cover():
    link = match_report_periods(
        ["2026-10-29", "2026-07-30", "2026-04-30", "2026-01-29"],
        ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"])
    assert link == {"2026-07-30": "2026-06-30", "2026-04-30": "2026-03-31",
                    "2026-01-29": "2025-12-31"}
    assert "2026-10-29" not in link          # its quarter has no statement yet


def test_a_period_is_claimed_once_and_only_within_the_lag():
    # Two report dates after one period end: the earlier claims it, the
    # later gets nothing rather than the same quarter twice.
    link = match_report_periods(["2026-02-01", "2026-02-20"], ["2025-12-31"])
    assert link == {"2026-02-01": "2025-12-31"}
    # A period that closed a year before a report is not "the quarter it covered".
    assert match_report_periods(["2026-07-30"], ["2025-06-30"]) == {}
    assert match_report_periods(["bad"], ["2025-06-30"]) == {}


def test_partial_provider_record_derives_from_its_context(monkeypatch):
    fh = pp.FinnhubPrices(api_key="k")
    monkeypatch.setattr(fh, "earnings_context", lambda sym: {"symbol": "AAPL", "report_history": [
        {"date": "2026-04-30", "eps_estimate": 1.94, "eps_actual": 2.01, "surprise_pct": 3.46},
        {"date": "2099-10-29", "eps_estimate": 1.98, "eps_actual": None, "surprise_pct": None},
        {"date": "2026-07-30", "eps_estimate": 1.89, "eps_actual": 2.02, "surprise_pct": 6.74},
    ]})
    out = fh.earnings_history("AAPL")
    dates = [r["date"] for r in out["reports"]]
    assert dates == ["2099-10-29", "2026-07-30", "2026-04-30"]
    assert out["reports"][0]["upcoming"] is True
    assert out["reports"][1]["upcoming"] is False
    assert all(r["revenue"] is None for r in out["reports"])    # EPS-only feed, nothing invented


def test_no_context_means_no_record(monkeypatch):
    av = pp.AlphaVantagePrices(api_key="k")
    monkeypatch.setattr(av, "earnings_context", lambda sym: None)
    assert av.earnings_history("AAPL") is None


def test_route_joins_filed_revenue_by_period_end(client, vendors, monkeypatch):
    from alphadesk.ingest import edgar

    class _F:
        name = "finnhub"
        def earnings_history(self, sym):
            return {"symbol": sym, "reports": [
                {"date": "2026-06-30", "period_end": "2026-06-30", "date_kind": "period_end", "upcoming": False,
                 "eps_estimate": 1.93, "eps_actual": 1.91, "surprise_pct": -0.89, "revenue": None, "revenue_estimate": None}]}
    vendors(finnhub=_F())
    monkeypatch.setattr(edgar, "quarterly_revenue", lambda s: {"2026-06-27": 109_417_000_000.0, "2026-03-28": 111_184_000_000.0})
    r = client.get("/api/earnings/history/aapl")
    body = r.json()
    assert r.status_code == 200 and body["vendor"] == "finnhub"
    assert body["reports"][0]["revenue"] == 109_417_000_000.0     # the Apple 52/53-week quarter, 3 days off
    vendors()
    assert client.get("/api/earnings/history/aapl").status_code == 428


def test_filed_revenue_reads_quarters_and_derives_the_fourth(monkeypatch):
    """A 52/53-week filer: three 10-Q quarters, the 10-K year, the fourth
    quarter as the difference — and a year missing a quarter derives nothing."""
    import json
    from alphadesk.ingest import edgar
    edgar._facts_cache.clear()
    facts = {"facts": {"us-gaap": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
        {"form": "10-Q", "start": "2024-09-29", "end": "2024-12-28", "val": 124.3},
        {"form": "10-Q", "start": "2024-09-29", "end": "2025-03-29", "val": 219.7},   # six months: ignored
        {"form": "10-Q", "start": "2024-12-29", "end": "2025-03-29", "val": 95.4},
        {"form": "10-Q", "start": "2025-03-30", "end": "2025-06-28", "val": 94.0},
        {"form": "10-K", "start": "2024-09-29", "end": "2025-09-27", "val": 416.2},
        {"form": "10-K", "start": "2023-10-01", "end": "2024-09-28", "val": 391.0},   # its quarters absent
        {"form": "8-K", "start": "2025-06-29", "end": "2025-09-27", "val": 1.0},      # not a statement
    ]}}}}}
    monkeypatch.setattr(edgar, "cik_for", lambda s: "0000320193")
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: json.dumps(facts).encode())
    q = edgar.quarterly_revenue("AAPL")
    assert q["2024-12-28"] == 124.3 and q["2025-03-29"] == 95.4 and q["2025-06-28"] == 94.0
    assert round(q["2025-09-27"], 1) == 102.5
    assert "2024-09-28" not in q
    assert list(q) == sorted(q)


def test_filed_revenue_is_empty_without_a_cik(monkeypatch):
    from alphadesk.ingest import edgar
    edgar._facts_cache.clear()
    monkeypatch.setattr(edgar, "cik_for", lambda s: None)
    assert edgar.quarterly_revenue("ZZZZ") == {}
