"""The transcript seam (2026-09-11): the free release from EDGAR, keyed
calls from a vendor, the reader's slot, and a guidance table that keeps
only what the document literally says."""

import pytest

from alphadesk.desk import transcripts as tx
from alphadesk.providers import base, registry
from alphadesk.providers import transcripts as tp


@pytest.fixture(autouse=True)
def _fresh():
    registry.reset_cache()
    yield
    registry.reset_cache()


def test_providers_satisfy_the_protocol():
    for cls in (tp.EdgarReleases, tp.FinnhubTranscripts, tp.FmpTranscripts):
        assert isinstance(cls(api_key="k"), base.TranscriptProvider)
    assert registry.available("transcripts")["transcripts"] == ["edgar", "finnhub", "fmp"]


def test_quarter_labels():
    assert tp.quarter_end_before("2026-07-30").isoformat() == "2026-06-30"
    assert tp.quarter_end_before("2026-01-29").isoformat() == "2025-12-31"
    assert tp.quarter_end_before("junk") is None
    assert tp._quarter_end(2025, 4) == "2025-12-31"
    assert tp._quarter_end("2025", "x") is None


def test_edgar_lists_only_results_releases_and_picks_the_exhibit(monkeypatch):
    from alphadesk.ingest import edgar
    filings = [
        {"accession": "A1", "form": "8-K", "items": "2.02,9.01", "filing_date": "2026-07-30",
         "report_date": "2026-07-30", "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/aapl-20260730.htm"},
        {"accession": "A2", "form": "8-K", "items": "5.02", "filing_date": "2026-06-01",
         "report_date": "2026-06-01", "url": "https://www.sec.gov/x/y/other.htm"},
    ]
    monkeypatch.setattr(edgar, "recent_filings", lambda sym, forms=None, limit=40: filings)
    index = """<table><tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
      <tr><td>1</td><td>8-K</td><td><a href="/Archives/edgar/data/320193/000032019326000018/aapl-20260730.htm">aapl-20260730.htm</a></td><td>8-K</td><td>26457</td></tr>
      <tr><td>3</td><td>EX-99.2</td><td><a href="/Archives/edgar/data/320193/000032019326000018/cfo.htm">cfo.htm</a></td><td>EX-99.2</td><td>256881</td></tr>
      <tr><td>2</td><td>EX-99.1</td><td><a href="/Archives/edgar/data/320193/000032019326000018/q3fy26pr.htm">q3fy26pr.htm</a></td><td>EX-99.1</td><td>341113</td></tr>
      <tr><td>7</td><td>LOGO</td><td><a href="/Archives/edgar/data/320193/000032019326000018/logo.jpg">logo.jpg</a></td><td>GRAPHIC</td><td>13441</td></tr>
    </table>"""
    fetched = []
    asked = []
    def fake_get(url, timeout=15.0):
        asked.append(url)
        return index.encode()
    monkeypatch.setattr(edgar, "_get", fake_get)
    monkeypatch.setattr(edgar, "fetch_filing_text", lambda url, max_chars=60000: fetched.append(url) or "Apple today announced … We expect revenue to grow.")
    prov = tp.EdgarReleases()
    rows = prov.list_transcripts("AAPL")
    assert [r["id"] for r in rows] == ["A1"]
    assert rows[0]["title"] == "Results release · quarter ended Jun 2026"
    assert rows[0]["period_end"] == "2026-06-30"
    doc = prov.transcript("AAPL", "A1")
    assert asked == ["https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/0000320193-26-000018-index.html"]
    assert doc["url"].endswith("/q3fy26pr.htm")        # EX-99.1 by TYPE, not by name
    assert fetched == [doc["url"]]
    assert "expect revenue" in doc["text"]


def test_exhibit_from_index_prefers_99_1_then_any_99():
    only_992 = '<tr><td>3</td><td>x</td><td><a href="/a/b/cfo.htm">cfo.htm</a></td><td>EX-99.2</td><td>1</td></tr>'
    assert tp.exhibit_from_index(only_992) == "cfo.htm"
    none = '<tr><td>1</td><td>x</td><td><a href="/a/b/k.htm">k.htm</a></td><td>8-K</td><td>1</td></tr>'
    assert tp.exhibit_from_index(none) is None


def test_finnhub_call_becomes_speaker_paragraphs(monkeypatch):
    fh = tp.FinnhubTranscripts(api_key="k")
    payloads = {
        "/stock/transcripts/list?symbol=NVDA": {"transcripts": [
            {"id": "NVDA_1", "title": "Q3 2025 Earnings Call", "time": "2024-11-20 17:00:00", "year": 2025, "quarter": 3}]},
        "/stock/transcripts?id=NVDA_1": {"title": "Q3 2025 Earnings Call", "time": "2024-11-20 17:00:00",
            "year": 2025, "quarter": 3, "transcript": [
                {"name": "Operator", "speech": ["Good afternoon.", "Welcome."]},
                {"name": "Colette Kress", "speech": ["Revenue is expected to be $37.5 billion, plus or minus 2%."]}]},
    }
    monkeypatch.setattr(fh, "_get", lambda path: payloads[path])
    rows = fh.list_transcripts("nvda")
    assert rows == [{"id": "NVDA_1", "date": "2024-11-20", "title": "Q3 2025 Earnings Call",
                     "period_end": "2025-09-30", "url": None}]
    doc = fh.transcript("NVDA", "NVDA_1")
    assert doc["text"].startswith("Operator: Good afternoon. Welcome.\n\nColette Kress: Revenue is expected")


def test_fmp_ids_are_year_quarter(monkeypatch):
    fmp = tp.FmpTranscripts(api_key="k")
    payloads = {
        "/earning-call-transcript-dates?symbol=AAPL": [{"quarter": 3, "fiscalYear": 2025, "date": "2025-07-31"}],
        "/earning-call-transcript?symbol=AAPL&year=2025&quarter=3": [{"date": "2025-07-31 17:00:00", "content": "Operator: hello"}],
    }
    monkeypatch.setattr(fmp, "_get", lambda path: payloads[path])
    assert fmp.list_transcripts("AAPL")[0]["id"] == "2025Q3"
    assert fmp.transcript("AAPL", "2025Q3")["text"] == "Operator: hello"
    assert fmp.transcript("AAPL", "nope") is None


def test_vendor_without_key_refuses():
    with pytest.raises(base.ProviderError):
        tp.FinnhubTranscripts(api_key="").list_transcripts("AAPL")


def test_guidance_keeps_only_verbatim_figures():
    text = ("Outlook. Revenue is expected to be $37.5 billion, plus or minus 2%. "
            "GAAP and non-GAAP gross margins are expected to be 73.0% and 73.5%, respectively, "
            "plus or minus 50 basis points.")
    items = [
        {"metric": "Revenue", "period": "Q4 FY2025", "value": "$37.5 billion ± 2%",
         "quote": "Revenue is expected to be $37.5 billion, plus or minus 2%."},
        {"metric": "GAAP gross margin", "period": "Q4 FY2025", "value": "73.0%",
         "quote": "GAAP and non-GAAP gross margins are expected to be 73.0% and 73.5%"},
        # invented: the quote is not in the document
        {"metric": "Operating expenses", "period": "Q4", "value": "$4.8 billion",
         "quote": "Operating expenses are expected to be $4.8 billion."},
        # a real quote but the value is not in it
        {"metric": "Tax rate", "period": "Q4", "value": "16.5%",
         "quote": "Revenue is expected to be $37.5 billion, plus or minus 2%."},
        "garbage",
    ]
    kept, dropped = tx.verify_guidance(items, text)
    assert [k["metric"] for k in kept] == ["Revenue", "GAAP gross margin"]
    assert dropped == 3


class _Src:
    name = "edgar"
    kind = "release"
    calls = 0

    def list_transcripts(self, symbol):
        return [{"id": "A1", "date": "2026-07-30", "title": "Results release · quarter ended Jun 2026",
                 "period_end": "2026-06-30", "url": "https://sec.gov/a1"}]

    def transcript(self, symbol, id):
        type(self).calls += 1
        if id != "A1":
            return None
        return {"id": id, "symbol": symbol, "date": "2026-07-30", "period_end": "2026-06-30",
                "title": "Results release · quarter ended Jun 2026", "url": "https://sec.gov/ex991",
                "text": "We expect revenue to grow 10% to 12% next quarter."}


def test_routes_list_read_and_cache_without_touching_the_filings_table(client, monkeypatch):
    _Src.calls = 0
    monkeypatch.setattr(tx, "get_transcripts", lambda: _Src())
    r = client.get("/api/transcripts/aapl")
    assert r.status_code == 200
    assert r.json()["kind"] == "release" and r.json()["transcripts"][0]["id"] == "A1"
    r = client.get("/api/transcripts/aapl/A1")
    assert r.status_code == 200 and "expect revenue" in r.json()["text"]
    client.get("/api/transcripts/aapl/A1")
    assert _Src.calls == 1                                   # the second read came from the ledger
    from alphadesk.ledger import store
    assert store.get_filings("AAPL") == []                   # never a filings row
    assert client.get("/api/transcripts/aapl/ZZ").status_code == 404
    # The guidance extraction went with the in-app model (2026-09-17).
    assert client.post("/api/transcripts/guidance",
                       json={"symbol": "AAPL", "id": "A1"}).status_code in (404, 405)


def test_keys_route_accepts_the_transcripts_seam(client, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    r = client.put("/api/keys/transcripts", json={"provider": "finnhub", "api_key": "x" * 20})
    # Anonymous in the suite: the seam name passes validation and the call
    # stops at the sign-in gate, not at "unknown seam".
    assert r.status_code == 401


def test_exhibit_header_is_stripped():
    assert tp.strip_exhibit_header("EX-99.1 2 q2fy27pr.htm EX-99.1 Document NVIDIA Announces Financial Results") == "NVIDIA Announces Financial Results"
    assert tp.strip_exhibit_header("Apple today announced") == "Apple today announced"
