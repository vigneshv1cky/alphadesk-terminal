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
