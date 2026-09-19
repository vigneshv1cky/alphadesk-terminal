"""The filings list is EDGAR's own list, not a curated subset (2026-09-11):
the ownership forms show beside the narrative ones, and only the narrative
ones are readable by the Q&A. Apple's 8-K/A of 2026-09-01 and its weekly
Form 4s were the rows the old 10-K/10-Q/8-K filter dropped."""

import json

from alphadesk.ingest import edgar


_SUBMISSIONS = {"filings": {"recent": {
    "form":              ["4",          "8-K/A",      "144",        "10-Q",       "SC 13G/A",   "S-8"],
    "filingDate":        ["2026-09-10", "2026-09-01", "2026-08-11", "2026-07-31", "2026-02-10", "2026-01-05"],
    "accessionNumber":   ["0001-26-1",  "0001-26-2",  "0001-26-3",  "0000-26-4",  "0001-26-5",  "0000-26-6"],
    "primaryDocument":   ["xslF345X05/a.xml", "b.htm", "c.pdf", "d.htm", "e.htm", "f.htm"],
    "reportDate":        ["2026-09-08", "2026-07-30", "", "2026-06-27", "2025-12-31", ""],
    "items":             ["", "2.02,9.01", "", "", "", ""],
    "acceptanceDateTime": ["2026-09-10T22:30:31.000Z"] * 6,
}}}


def _stub_edgar(monkeypatch):
    monkeypatch.setattr(edgar, "cik_for", lambda sym: "0000320193")
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: json.dumps(_SUBMISSIONS).encode())


def test_default_list_matches_edgar_with_readable_flags(monkeypatch):
    _stub_edgar(monkeypatch)
    rows = edgar.recent_filings("AAPL")
    forms = [r["form"] for r in rows]
    # Every ownership form and the amendment are listed; the S-8 (a
    # registration statement, neither readable nor an ownership form) is not.
    assert forms == ["4", "8-K/A", "144", "10-Q", "SC 13G/A"]
    readable = {r["form"]: r["readable"] for r in rows}
    assert readable == {"4": False, "8-K/A": True, "144": False, "10-Q": True, "SC 13G/A": False}


def test_explicit_forms_still_narrow(monkeypatch):
    """Callers that ask for one form (the events feed's 8-Ks, the company
    profile's latest 10-K) keep an exact match — an amendment is not an 8-K."""
    _stub_edgar(monkeypatch)
    assert [r["form"] for r in edgar.recent_filings("AAPL", forms=("8-K",))] == []
    assert [r["form"] for r in edgar.recent_filings("AAPL", forms=("10-Q",))] == ["10-Q"]


def test_list_filings_stamps_readable_on_stored_rows(monkeypatch, store):
    from alphadesk.desk import filings
    _stub_edgar(monkeypatch)
    rows = filings.list_filings("AAPL")
    by_acc = {r["accession"]: r for r in rows}
    assert by_acc["0001-26-2"]["readable"] is True      # the 8-K/A
    assert by_acc["0001-26-1"]["readable"] is False     # the Form 4
    assert all(r["cik"] == "0000320193" for r in rows)
