"""The keyed vendor paths, audited against each vendor's documented
payload without a key on hand (2026-09-12): Finnhub's calendar session
codes and revenue fields, its dividend ex-date field, and FMP's
single-newline speaker turns."""

from alphadesk.ingest import prices
from alphadesk.providers import prices as pp
from alphadesk.providers import transcripts as tp


def test_finnhub_session_codes_are_bmo_amc_dmh(monkeypatch):
    rows = [
        {"symbol": "AAPL", "date": "2026-10-29", "hour": "amc", "epsEstimate": 1.98, "epsActual": None},
        {"symbol": "KR", "date": "2026-09-11", "hour": "bmo", "epsEstimate": 1.0, "epsActual": 1.05},
        {"symbol": "X", "date": "2026-09-11", "hour": "dmh", "epsEstimate": None, "epsActual": None},
        {"symbol": "Y", "date": "2026-09-12", "hour": "", "epsEstimate": 0.5, "epsActual": None},
    ]
    f = pp.FinnhubPrices(api_key="k")
    monkeypatch.setattr(f, "_get", lambda path: {"earningsCalendar": rows})
    out = {r["symbol"]: r for r in f.earnings_calendar("2026-09-11", "2026-10-29")}
    assert out["AAPL"]["session"] == "AMC" and out["AAPL"]["confirmed"]
    assert out["KR"]["session"] == "BMO" and out["KR"]["confirmed"]          # was misread as "bmc"
    assert out["X"]["session"] == "DAY" and out["X"]["confirmed"]            # a named time, during hours
    # An empty hour is the vendor saying nothing, not "during the day": the
    # calendar predicts the session from filing history instead, and FedEx
    # and General Mills both arrive this way (2026-09-15).
    assert out["Y"]["session"] is None and not out["Y"]["confirmed"]






def test_fill_revenue_estimates_matches_within_three_days_and_never_overwrites():
    reports = [
        {"date": "2026-07-30", "revenue_estimate": None},
        {"date": "2026-04-30", "revenue_estimate": None},     # vendor says 04-29
        {"date": "2026-01-29", "revenue_estimate": 140e9},    # already known
        {"date": "2025-10-30", "revenue_estimate": None},     # vendor is a week off: no match
    ]
    by_date = {
        "2026-07-30": {"revenue_estimate": 109.04e9, "revenue_actual": None},
        "2026-04-29": {"revenue_estimate": 109.46e9, "revenue_actual": None},
        "2026-01-29": {"revenue_estimate": 138.39e9, "revenue_actual": None},
        "2025-11-06": {"revenue_estimate": 102.23e9, "revenue_actual": None},
    }
    assert prices.fill_revenue_estimates(reports, by_date) == 2
    assert reports[0]["revenue_estimate"] == 109.04e9
    assert reports[1]["revenue_estimate"] == 109.46e9
    assert reports[2]["revenue_estimate"] == 140e9
    assert reports[3]["revenue_estimate"] is None
    assert prices.fill_revenue_estimates(reports, {}) == 0


def test_finnhub_dividends_read_the_date_field(monkeypatch):
    fh = pp.FinnhubPrices(api_key="k")
    payloads = {
        "/stock/dividend": [
            {"symbol": "AAPL", "date": "2026-08-10", "amount": 0.27, "payDate": "2026-08-13",
             "recordDate": "2026-08-10", "declarationDate": "2026-07-30", "currency": "USD"},
            {"symbol": "AAPL", "exDate": "2026-05-11", "amount": 0.27},      # the older spelling still reads
            {"symbol": "AAPL", "amount": 0.26},                              # no date at all: dropped
        ],
        "/stock/split": [{"symbol": "AAPL", "date": "2020-08-31", "fromFactor": 1, "toFactor": 4}],
    }
    monkeypatch.setattr(fh, "_get", lambda path: payloads[path.split("?")[0]])
    out = fh.corporate_actions("aapl")
    assert [d["ex_date"] for d in out["dividends"]] == ["2026-08-10", "2026-05-11"]
    d = out["dividends"][0]
    assert (d["record_date"], d["payment_date"], d["declaration_date"]) == ("2026-08-10", "2026-08-13", "2026-07-30")
    assert out["splits"] == [{"date": "2020-08-31", "from": 1, "to": 4}]


def test_fmp_turns_become_paragraphs(monkeypatch):
    fmp = tp.FmpTranscripts(api_key="k")
    content = "Operator: Good day.\nTim Cook: Thanks.\r\n\r\nLuca Maestri: Revenue was $59.7 billion.\n"
    monkeypatch.setattr(fmp, "_get", lambda path: [{"date": "2020-07-30 17:00:00", "content": content}])
    text = fmp.transcript("AAPL", "2020Q3")["text"]
    assert text == "Operator: Good day.\n\nTim Cook: Thanks.\n\nLuca Maestri: Revenue was $59.7 billion."
