"""Store writes that run on every agent call (2026-10-06)."""


def test_a_filing_list_writes_only_filings_not_stored_yet(store, monkeypatch):
    rows = [{"accession": f"0000-26-{i:06d}", "symbol": "eaf", "cik": "1", "form": "8-K",
             "filing_date": "2026-09-01", "report_date": None, "primary_doc": "a.htm", "url": "u"} for i in range(40)]
    store.save_filings(rows)
    assert len(store.get_filings("EAF", limit=100)) == 40
    writes: list[str] = []
    real = store._connect

    class _Spy:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            c = self.conn.__enter__()
            outer = self

            class _C:
                def execute(self, sql, *a):
                    if sql.lstrip().upper().startswith("INSERT"):
                        writes.append(sql)
                    return c.execute(sql, *a)

                def __getattr__(self, k):
                    return getattr(c, k)
            outer._c = _C()
            return outer._c

        def __exit__(self, *e):
            return self.conn.__exit__(*e)

    monkeypatch.setattr(store, "_connect", lambda: _Spy(real()))
    store.save_filings(rows)                                   # all stored already: nothing written
    assert writes == []
    store.save_filings(rows + [{**rows[0], "accession": "0000-26-999999"}])
    assert len(writes) == 1
    monkeypatch.undo()
    assert len(store.get_filings("EAF", limit=100)) == 41


def test_a_companys_figures_file_is_kept_and_read_after_a_restart(store, monkeypatch):
    import json
    from alphadesk.ingest import edgar
    asked: list[str] = []
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: asked.append(url) or json.dumps({"facts": {"x": 1}}).encode())
    url = edgar._FACTS_URL.format(cik10="0000000001")
    assert edgar.get_json(url, "facts")["facts"] == {"x": 1}
    edgar._sec_writer.submit(lambda: None).result(timeout=5)   # the kept copy is written on its own thread
    edgar._json_cache.clear()                                  # a restart: memory is empty
    assert edgar.get_json(url, "facts")["facts"] == {"x": 1}
    assert len(asked) == 1                                     # the second read is the kept copy


def test_a_stale_figures_file_is_still_served_when_edgar_cannot_be_reached(store, monkeypatch):
    import json
    from alphadesk.ingest import edgar
    url = edgar._FACTS_URL.format(cik10="0000000002")
    store.sec_document_put(url, "facts", json.dumps({"facts": {"old": 1}}).encode())
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE sec_documents SET fetched_at=0 WHERE url=?", (url,))   # far past fresh

    def down(*a, **k):
        raise edgar.EdgarRateLimited("paused")
    monkeypatch.setattr(edgar, "_get", down)
    edgar._json_cache.clear()
    assert edgar.get_json(url, "facts")["facts"] == {"old": 1}


def test_each_form_4_is_fetched_once(store, monkeypatch):
    from alphadesk.ingest import edgar, insider
    xml = (b"<ownershipDocument><reportingOwner><reportingOwnerId><rptOwnerName>A B</rptOwnerName></reportingOwnerId>"
           b"</reportingOwner><nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>2026-09-01</value>"
           b"</transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding><transactionAmounts>"
           b"<transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>10</value>"
           b"</transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>"
           b"</transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>")
    fetched: list[str] = []
    monkeypatch.setattr(edgar, "cik_for", lambda s: "0000000003")
    monkeypatch.setattr(edgar, "get_json", lambda url, kind="submissions", timeout=15.0: {"filings": {"recent": {
        "form": ["4", "4"], "accessionNumber": ["0001-26-000001", "0001-26-000002"],
        "primaryDocument": ["xslF345X06/a.xml", "xslF345X06/b.xml"], "filingDate": ["2026-09-02", "2026-09-01"]}}})
    monkeypatch.setattr(edgar, "_get", lambda url, timeout=15.0: fetched.append(url) or xml)
    first = insider.get_insider_trades("ZZZ")
    insider._insider_cache.clear()                             # a restart
    again = insider.get_insider_trades("ZZZ")
    assert first == again and len(fetched) == 2                # two filings, each fetched once in all


def test_the_share_count_and_succession_readers_read_the_saved_filing(store, monkeypatch):
    """Both downloaded their filings afresh every call (2026-10-07 audit); they
    now read the saved whole copy, cut to the same opening they read before."""
    from alphadesk.ingest import edgar
    fetched: list[str] = []
    monkeypatch.setattr(edgar, "fetch_filing_with_exhibits",
                        lambda url, max_chars=60_000: fetched.append(url) or ("A" * 50_000 + "B" * 50_000))
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm"
    first = edgar.saved_filing_text("0000000001-26-000001", url, 30_000)
    again = edgar.saved_filing_text("0000000001-26-000001", url, 40_000)
    assert first == "A" * 30_000 and again == "A" * 40_000
    assert fetched == [url]                                    # downloaded once, then the saved copy


def test_a_slow_list_is_kept_reused_and_served_when_the_vendor_fails(store):
    from alphadesk.ledger.keptlists import kept
    calls: list[int] = []
    assert kept("u1", "alpaca", "asset_listing", 3600, lambda: calls.append(1) or [["AAPL", "Apple", "NASDAQ"]]) \
        == [["AAPL", "Apple", "NASDAQ"]]
    assert kept("u1", "alpaca", "asset_listing", 3600, lambda: calls.append(1) or [["X", None, None]]) \
        == [["AAPL", "Apple", "NASDAQ"]] and len(calls) == 1         # fresh: the kept copy, no fetch

    def down():
        raise RuntimeError("vendor down")
    assert kept("u1", "alpaca", "asset_listing", 0, down) == [["AAPL", "Apple", "NASDAQ"]]   # stale, but the vendor failed
    assert kept("u1", "fmp", "fund_names", 0, lambda: None) is None   # empty is an answer, never replaced by an old copy


def test_a_quarter_release_check_is_asked_of_edgar_once(store, monkeypatch):
    from alphadesk.ingest import earnings_calendar as ec, edgar
    asked: list[str] = []
    filings = [{"form": "8-K", "filing_date": "2026-10-01", "items": "2.02", "accession": "a"}]
    monkeypatch.setattr(edgar, "recent_filings", lambda sym, forms=None, limit=40: asked.append(sym) or filings)
    first = ec.quarter_release("ZZZ", "2026-10-01")
    ec._periodic_cache.clear()                                 # a restart
    assert ec.quarter_release("ZZZ", "2026-10-01") == first
    assert asked == ["ZZZ"]


def test_an_unreadable_filing_list_is_not_kept(store, monkeypatch):
    from alphadesk.ingest import earnings_calendar as ec, edgar
    monkeypatch.setattr(edgar, "recent_filings", lambda sym, forms=None, limit=40: [])
    ec.quarter_release("YYY", "2026-10-01")
    assert store.quarter_release_get("YYY", "2026-10-01") is None


def test_alpha_vantage_requests_are_paced_one_a_second_per_key(monkeypatch):
    import time
    import pytest
    from alphadesk.providers import avpace
    from alphadesk.providers.base import ProviderError
    monkeypatch.setattr(avpace, "MIN_INTERVAL_S", 0.2)
    monkeypatch.setattr(avpace, "MAX_WAIT_S", 0.5)
    avpace._next_slot.clear()
    t0 = time.monotonic()
    avpace.wait_turn("k1")
    avpace.wait_turn("k1")
    avpace.wait_turn("other")                                  # another key has its own slot
    assert 0.18 <= time.monotonic() - t0 < 0.4
    avpace._next_slot["k1"] = time.monotonic() + 2.0           # a backlog of callers already queued on the key
    with pytest.raises(ProviderError):                         # past the longest wait: refused, the next vendor answers
        avpace.wait_turn("k1")
    avpace._next_slot.clear()


def test_the_boards_option_chains_are_kept_once_after_the_close(store):
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    from alphadesk.ingest import chainsnap
    store.save_board("u-chain", ["NVDA", "BTC-USD", "AAPL"], "NVDA")
    asked: list[tuple] = []

    class _V:
        name = "alpaca"
        def option_expirations(self, sym):
            return ["2026-10-09", "2026-10-16", "2027-06-18"]           # the last is past 60 days
        def option_chain(self, sym, exp):
            asked.append((sym, exp))
            return {"symbol": sym, "expiry": exp, "calls": [{"strike": 100, "bid": 1.0, "ask": 1.1}], "puts": []}

    class _R:
        owner = "u-chain"
        def vendor_for(self, s, m):
            return _V()

    ny = ZoneInfo("America/New_York")
    before = datetime(2026, 10, 7, 15, 59, tzinfo=ny)
    after = datetime(2026, 10, 7, 16, 30, tzinfo=ny)
    assert chainsnap.record_chains_close(_R(), before) == 0             # the session is not over
    assert chainsnap.record_chains_close(_R(), after) == 2              # NVDA and AAPL; the coin has no chain
    assert chainsnap.record_chains_close(_R(), after) == 0              # once a day
    assert sorted(asked) == [("AAPL", "2026-10-09"), ("AAPL", "2026-10-16"), ("NVDA", "2026-10-09"), ("NVDA", "2026-10-16")]
    kept = store.get_option_chain_day("u-chain", "NVDA", "2026-10-07")
    assert set(kept["chains"]) == {"2026-10-09", "2026-10-16"} and kept["chains"]["2026-10-09"]["calls"][0]["bid"] == 1.0
    assert chainsnap.nearest_expiries(["2026-10-01", "2026-10-09"], date(2026, 10, 7)) == ["2026-10-09"]


def test_a_saved_option_chain_is_read_back_for_a_past_day(store, monkeypatch):
    import pytest
    from alphadesk import mcp_server
    import alphadesk.providers as providers
    monkeypatch.setattr(providers, "get_prices", lambda: type("R", (), {"owner": "u-past"})())
    calls = [{"strike": float(s), "bid": 1.0, "ask": 1.2} for s in range(80, 130, 5)]
    store.save_option_chain_day("u-past", "NVDA", "2026-10-07", "alpaca",
                                {"symbol": "NVDA", "day": "2026-10-07", "spot": 101.0, "saved_at": "2026-10-07T20:30:00+00:00",
                                 "chains": {"2026-10-09": {"calls": calls, "puts": [], "vendor": "alpaca"}}})
    listed = mcp_server.option_chain("NVDA", on="2026-10-07")
    assert listed["saved"] and listed["expiries"] == ["2026-10-09"] and listed["spot"] == 101.0
    got = mcp_server.option_chain("NVDA", expiry="2026-10-09", strikes=2, on="2026-10-07")
    assert [r["strike"] for r in got["calls"]] == [95.0, 100.0, 105.0, 110.0]   # cut around the saved price
    assert got["as_of"] == "that day's close"
    missing = mcp_server.option_chain("NVDA", on="2026-10-06")
    assert missing["saved"] is False and missing["saved_days"] == ["2026-10-07"]
    with pytest.raises(ValueError, match="saved expiries: 2026-10-09"):
        mcp_server.option_chain("NVDA", expiry="2026-10-16", on="2026-10-07")
