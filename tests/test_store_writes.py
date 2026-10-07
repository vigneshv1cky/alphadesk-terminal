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
