"""THE MARKET'S FILINGS AS THEY LAND (2026-09-22): EDGAR's own feed of what
was just filed, with the acceptance time on each row. Keyless public data,
so every rule here is about reading it truthfully."""

from alphadesk.ingest import edgar_feed

FEED = """<feed>
 <entry>
   <title>8-K - OLD DOMINION FREIGHT LINE, INC. (0000878927) (Filer)</title>
   <updated>2026-09-22T14:15:28-04:00</updated>
   <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/878927/000087892726000101/0000878927-26-000101-index.htm"/>
 </entry>
 <entry>
   <title>SCHEDULE 13D - BUYER CAPITAL LP (0001111111) (Filed by)</title>
   <updated>2026-09-22T13:40:05-04:00</updated>
   <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/1111111/000111111126000001/0001111111-26-000001-index.htm"/>
 </entry>
 <entry>
   <title>SCHEDULE 13D - CYABRA, INC. (0001865506) (Subject)</title>
   <updated>2026-09-22T13:40:05-04:00</updated>
   <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/1111111/000111111126000001/0001111111-26-000001-index.htm"/>
 </entry>
</feed>"""


def test_a_filing_carries_the_secs_own_clock():
    """The acceptance time is the one fact this feed has that a company's
    filing list does not, and it is stated in New York with its offset."""
    rows = edgar_feed.parse_entries(FEED)
    assert len(rows) == 3
    first = rows[0]
    assert first["form"] == "8-K"
    assert first["company"] == "OLD DOMINION FREIGHT LINE, INC."
    assert first["cik"] == "0000878927"
    assert first["filed_at"] == "2026-09-22T14:15:28-04:00"
    assert first["role"] == "filer"
    assert first["accession"] == "0000878927-26-000101"


def test_a_stake_is_kept_under_the_company_whose_stock_moves(monkeypatch):
    """EDGAR lists a 13D twice — once under the buyer, once under the company
    bought into. They share an accession, so they are ONE filing, and the
    SUBJECT is the row worth having: that is the stock that moves."""
    edgar_feed.reset_cache()
    monkeypatch.setattr(edgar_feed, "_group",
                        lambda name: (edgar_feed.parse_entries(FEED), 1.0, None))
    monkeypatch.setattr(edgar_feed, "_tickers_by_cik", lambda: {})
    out = edgar_feed.recent(groups=["stakes"], listed_only=False)
    thirteen_d = [r for r in out["filings"] if r["form"] == "SCHEDULE 13D"]
    assert len(thirteen_d) == 1, "one accession is one filing"
    assert thirteen_d[0]["company"] == "CYABRA, INC."
    assert thirteen_d[0]["role"] == "subject"


def test_a_group_that_could_not_be_read_is_not_a_quiet_group(monkeypatch):
    """EDGAR answers bursts with 503s. A feed of what just happened must
    never report a failure as an absence of news."""
    edgar_feed.reset_cache()
    monkeypatch.setattr(edgar_feed, "_group",
                        lambda name: ([], None, "HTTP Error 503") if name == "stakes"
                        else (edgar_feed.parse_entries(FEED)[:1], 1.0, None))
    monkeypatch.setattr(edgar_feed, "_tickers_by_cik", lambda: {})
    out = edgar_feed.recent(groups=["events", "stakes"], listed_only=False)
    assert "stakes" in out["unavailable"] and "503" in out["unavailable"]["stakes"]
    assert out["unavailable"].get("events") is None
    assert out["read_at"]["stakes"] is None and out["read_at"]["events"]


def test_hiding_unlisted_filers_is_counted_not_silent(monkeypatch):
    """Securitisation trusts and Federal Home Loan Banks file constantly and
    trade nowhere, so the default keeps listed registrants — but a shorter
    list must never be mistaken for a quieter market."""
    edgar_feed.reset_cache()
    monkeypatch.setattr(edgar_feed, "_group",
                        lambda name: (edgar_feed.parse_entries(FEED), 1.0, None))
    monkeypatch.setattr(edgar_feed, "_tickers_by_cik", lambda: {"0000878927": ["ODFL"]})
    out = edgar_feed.recent(groups=["events"], listed_only=True)
    assert [r["symbols"] for r in out["filings"]] == [["ODFL"]]
    assert out["unlisted_hidden"] == 1
    every = edgar_feed.recent(groups=["events"], listed_only=False)
    assert every["unlisted_hidden"] == 0 and len(every["filings"]) == 2


def test_the_default_leaves_out_the_firehose():
    """424B structured-note prospectuses were about 60% of a page of EDGAR's
    whole feed, several a minute from a few bank issuers. Defaulting to them
    would bury every real catalyst."""
    assert edgar_feed.DEFAULT_GROUPS == ("events", "stakes")
    assert "offerings" in edgar_feed.GROUPS and "offerings" not in edgar_feed.DEFAULT_GROUPS


def test_a_malformed_entry_is_skipped_not_fatal():
    rows = edgar_feed.parse_entries("<feed><entry><title>no dash here</title>"
                                    "<updated>2026-09-22T10:00:00-04:00</updated></entry>"
                                    "<entry><title>8-K - A CO (0000000123) (Filer)</title></entry></feed>")
    assert rows == []


def test_the_market_feed_route_is_not_eaten_by_the_symbol_route(client):
    """ROUTE ORDER (2026-09-23). "/api/filings/{symbol}" was declared first,
    so "/api/filings/feed" matched it and "feed" was read as a ticker: the
    market feed answered with one company's filings for a company called
    FEED, and the tile that read it crashed on the shape it got back. The
    feed route is declared first now."""
    body = client.get("/api/filings/feed?limit=3").json()
    # The feed's own shape, not the per-symbol one.
    assert "filings" in body and "unlisted_hidden" in body and "groups" in body
    assert "symbol" not in body, "this is the per-symbol route's shape"
    for row in body["filings"]:
        assert "symbols" in row, "every row carries the tickers, as a list"
        assert "filed_at" in row


def test_one_companys_filings_still_answer(client):
    body = client.get("/api/filings/NVDA").json()
    assert body.get("symbol") == "NVDA"
