"""The company profile pulls the 10-K's Business and Properties sections
from the BODY of the filing, not its table of contents, and returns them
verbatim."""
from alphadesk.ingest import company


TENK = (
    "TABLE OF CONTENTS PART I Item 1. Business 3 Item 1A. Risk Factors 12 "
    "Item 2. Properties 30 Item 3. Legal Proceedings 31 PART I "
    "Item 1. Business Our Company We design chips. " + ("We sell them worldwide. " * 40) +
    "Item 1A. Risk Factors Risks abound. " + ("Risk. " * 50) +
    "Item 2. Properties Our headquarters is in Santa Clara, California, in owned buildings of 1.2 million square feet. "
    + ("We also lease offices in Austin, Texas and Tel Aviv, Israel. " * 12) +
    "Item 3. Legal Proceedings None material."
)


def test_business_comes_from_the_body_not_the_toc():
    got = company.extract_item(TENK, company.BUSINESS_START, company.BUSINESS_END, 9_000)
    assert got is not None
    text, truncated = got
    assert text.startswith("Item 1. Business Our Company We design chips.")
    assert "Item 1A" not in text
    assert truncated is False


def test_properties_span_and_cap():
    got = company.extract_item(TENK, company.PROPERTIES_START, company.PROPERTIES_END, 200)
    assert got is not None
    text, truncated = got
    assert text.startswith("Item 2. Properties Our headquarters is in Santa Clara")
    assert truncated is True and text.endswith("…")


def test_missing_section_is_none():
    assert company.extract_item("nothing here", company.PROPERTIES_START, company.PROPERTIES_END, 100) is None


def test_profile_shape_and_cache(monkeypatch):
    monkeypatch.setattr(company, "_edgar_facts", lambda s: {"cik": "0000001", "legal_name": "ACME CORP",
                                                             "business_address": {"city": "Austin"}})
    monkeypatch.setattr(company, "_vendor_profile", lambda s: ({"name": "Acme Corporation", "employees": 12}, [{"name": "A. Person", "title": "CEO"}]))
    monkeypatch.setattr(company, "_tenk", lambda s: {"accession": "x", "business": "Item 1. Business …", "properties": None})
    monkeypatch.setattr(company.secfacts, "facts", lambda cik: None)
    p = company.profile("acme")
    assert p["symbol"] == "ACME" and p["name"] == "Acme Corporation"
    assert p["edgar"]["legal_name"] == "ACME CORP"
    assert p["officers"][0]["title"] == "CEO"
    assert p["tenk"]["business"].startswith("Item 1")
    assert p["coin"] is None


def test_unknown_symbol_is_none(monkeypatch):
    monkeypatch.setattr(company, "_edgar_facts", lambda s: None)
    monkeypatch.setattr(company, "_vendor_profile", lambda s: (None, []))
    assert company.profile("ZZZZ") is None


def test_filer_category_html_is_cleaned():
    assert company.clean_category("<br>Emerging growth company") == "Emerging growth company"
    assert company.clean_category("Large accelerated filer<br>Emerging growth company") == "Large accelerated filer · Emerging growth company"
    assert company.clean_category("Large accelerated filer") == "Large accelerated filer"
    assert company.clean_category("") is None and company.clean_category(None) is None


def test_foreign_private_issuer_flag(monkeypatch):
    import json
    payload = {"name": "TAIWAN SEMI", "fiscalYearEnd": "1231", "addresses": {},
               "filings": {"recent": {"form": ["6-K", "20-F", "6-K"]}}}
    monkeypatch.setattr(company.edgar, "cik_for", lambda s: "0001046179")
    monkeypatch.setattr(company.edgar, "_get", lambda url, timeout=15.0: json.dumps(payload).encode())
    assert company._edgar_facts("TSM")["foreign_private_issuer"] is True
    payload["filings"]["recent"]["form"] = ["10-K", "8-K"]
    assert company._edgar_facts("NVDA")["foreign_private_issuer"] is False




def test_reference_symbol_has_a_profile_without_any_feed(monkeypatch):
    monkeypatch.setattr(company, "_edgar_facts", lambda s: None)
    monkeypatch.setattr(company, "_vendor_profile", lambda s: (None, []))
    p = company.profile("CL=F")
    assert p is not None and p["name"] == "WTI crude oil futures"
    assert p["reference"]["sources"][0]["label"].startswith("CME Group")


def test_profile_endpoint_accepts_board_symbols(monkeypatch):
    from fastapi.testclient import TestClient
    from alphadesk.app import dashboard
    from alphadesk.ingest import company as c
    seen = []
    monkeypatch.setattr(c, "profile", lambda s: (seen.append(s), {"symbol": s, "name": s, "edgar": None, "profile": None, "officers": [], "tenk": None, "reference": c.REFERENCE.get(s)})[1])
    client = TestClient(dashboard.app)
    for raw, want in (("^GSPC", "^GSPC"), ("CL=F", "CL=F"), ("EURUSD=X", "EURUSD=X"), ("btc-usd", "BTC-USD")):
        r = client.get(f"/api/company/{raw}")
        assert r.status_code == 200, raw
        assert r.json()["symbol"] == want
    assert client.get("/api/company/%5EGSPC").json()["reference"]["publisher"] == "S&P Dow Jones Indices"


def test_every_profile_cites_outside_sources():
    reg = company._sources("NVDA", "NVIDIA Corporation", {"cik": "0001045810"}, {"website": "https://www.nvidia.com", "investor_website": "https://investor.nvidia.com", "quote_type": "EQUITY"})
    labels = [x["label"] for x in reg]
    assert labels[0] == "SEC EDGAR filings" and "CIK=0001045810" in reg[0]["url"]
    assert "Official site (www.nvidia.com)" in labels and "Investor relations" in labels
    coin = company._sources("BTC-USD", "Bitcoin USD", None, {"website": "https://bitcoin.org", "quote_type": "CRYPTOCURRENCY"})
    assert [x["label"] for x in coin] == ["Official site (bitcoin.org)", "CoinGecko (search)", "CoinMarketCap (search)"]
    assert "query=BTC" in coin[1]["url"]


# ── a foreign private issuer files a 20-F, not a 10-K ────────────────────
#
# TSMC's and Alibaba's pages read blank until the 20-F's own item numbers
# were added: Item 4 is the business where a 10-K's Item 1 is (2026-09-15).

def test_the_twenty_f_business_section_is_found():
    from alphadesk.ingest.company import FORM_ITEMS, extract_item
    items = FORM_ITEMS["20-F"]
    text = ("TABLE OF CONTENTS Item 4. Information on the Company 12 "
            + "Item 4. Information on the Company Our History and Structure. " + ("We make chips. " * 60)
            + " Item 5. Operating and Financial Review and Prospects")
    got = extract_item(text, items["business"][1], items["business"][2], 9000)
    assert got and "Our History and Structure" in got[0] and "Operating and Financial" not in got[0]


def test_each_form_names_its_own_item_in_the_citation():
    from alphadesk.ingest.company import FORM_ITEMS
    assert FORM_ITEMS["10-K"]["business"][0] == "Item 1, Business"
    assert FORM_ITEMS["20-F"]["business"][0].startswith("Item 4")


def test_an_annual_reports_sections_are_read_once(monkeypatch, tmp_path):
    """A filed 10-K never changes: its sections are read once and kept by
    accession (2026-09-19 — reading them was 2–3.6s on every profile view)."""
    from alphadesk.ledger import store
    monkeypatch.setenv("ALPHADESK_DATA", str(tmp_path))
    store.init()
    fetched = []
    monkeypatch.setattr(company.edgar, "recent_filings", lambda s, forms=None, limit=1: [
        {"accession": "0000-99-000001", "form": "10-K", "filing_date": "2026-02-01", "url": "https://x/10k.htm"}])
    monkeypatch.setattr(company.edgar, "fetch_filing_text",
                        lambda url, max_chars=0: fetched.append(url) or
                        "Item 1. Business\\nWe make chips.\\nItem 1A. Risk Factors\\nRisks.\\n"
                        "Item 2. Properties\\nOffices.\\nItem 3. Legal Proceedings\\n")
    first = company._tenk("TEST")
    second = company._tenk("TEST")
    assert len(fetched) == 1
    assert second == first and second["reader"] == company.SECTION_READER_VERSION


def test_a_heading_word_split_by_styling_still_matches():
    # Microsoft's 10-K: small capitals come out as "B USINESS" / "RIS K".
    body = "ITEM 1. B USINESS GENERAL " + "Microsoft is a technology company. " * 30 + "ITEM 1A. RIS K FACTORS Risks."
    got = company.extract_item(body, company.BUSINESS_START, company.BUSINESS_END, 5000)
    assert got and got[0].startswith("ITEM 1. B USINESS") and "RIS K" not in got[0]


def test_a_cross_reference_in_prose_does_not_beat_the_real_section():
    # Alphabet's 10-K cites "Item 1 Business and Note 15" deep in the report,
    # with no Item 1A after it: the span that CLOSES at Item 1A is the section.
    text = ("ITEM 1. BUSINESS Overview " + "We build products. " * 40 + "ITEM 1A. RISK FACTORS Risks. "
            + "Unrelated text. " * 50 + "Item 1 Business and Note 15 of the Notes. " + "Numbers. " * 400)
    got = company.extract_item(text, company.BUSINESS_START, company.BUSINESS_END, 5000)
    assert got and got[0].startswith("ITEM 1. BUSINESS Overview")


def test_description_of_properties_and_a_short_section_are_found():
    brk = "Item 2. Descriptio n of Properties " + "Berkshire owns plants. " * 20 + "Item 3. Legal Proceedings"
    assert company.extract_item(brk, company.PROPERTIES_START, company.PROPERTIES_END, 5000, company.PROPERTIES_MIN)
    goog = "ITEM 2. PROPERTIES Our headquarters are in Mountain View, California. " * 3 + "ITEM 3. LEGAL PROCEEDINGS"
    assert company.extract_item(goog, company.PROPERTIES_START, company.PROPERTIES_END, 5000, company.PROPERTIES_MIN)
    toc = "Item 2. Properties 24 Item 3. Legal Proceedings 25"
    assert company.extract_item(toc, company.PROPERTIES_START, company.PROPERTIES_END, 5000, company.PROPERTIES_MIN) is None


def test_a_quoted_heading_neither_opens_nor_closes_a_section():
    # SAP: 'see “Item 4. Information About SAP – Description of Property.”'
    # early on; Alibaba quotes "Item 5" inside its own Item 4.
    items = company.FORM_ITEMS["20-F"]
    text = ("Risks. See “Item 4. Information About SAP – Description of Property.” " + "Risk text. " * 300
            + "ITEM 4. INFORMATION ABOUT SAP Our legal name is SAP SE. " + "We sell software. " * 20
            + "See “Item 5. Operating and Financial Review”. " + "More business. " * 20
            + "Description of Property Our principal office is in Walldorf. " + "Offices. " * 20
            + "ITEM 4A. UNRESOLVED STAFF COMMENTS None.")
    b = company.extract_item(text, items["business"][1], items["business"][2], 20_000)
    assert b and b[0].startswith("ITEM 4. INFORMATION ABOUT SAP") and "More business" in b[0]
    p = company.extract_item(text, items["properties"][1], items["properties"][2], 20_000, company.PROPERTIES_MIN)
    assert p and p[0].startswith("Description of Property Our principal office")


def test_a_twenty_f_facilities_heading_is_the_property_section():
    # TSMC's 20-F has no "Item 4.D" heading: its property sits under
    # "Our Semiconductor Facilities" inside Item 4 (2026-09-19).
    text = ("see “– Our Semiconductor Facilities” for more. " + "Filler. " * 40
            + "Our Semiconductor Facilities We currently operate one 150mm wafer fab. " + "Land leases. " * 30)
    heading, (body, _) = company.facilities_section(text)
    assert heading == "Our Semiconductor Facilities"
    assert body.startswith("Our Semiconductor Facilities We currently operate")
    assert company.facilities_section("we expand our facilities as demand grows. " * 20) is None


def test_the_hidden_xbrl_block_is_not_read(monkeypatch):
    html = (b"<html><body><div style='display:none'><ix:header><ix:hidden>9999 facts</ix:hidden>"
            b"</ix:header></div><p>Item 1. Business</p></body></html>")
    monkeypatch.setattr(company.edgar, "_get", lambda url, timeout=30.0: html)
    assert company.edgar.fetch_filing_text("https://x") == "Item 1. Business"


def test_the_predecessor_is_named_in_the_succession_filing():
    from alphadesk.ingest import edgar
    text = ("On July 1, 2026, Exxon Mobil Corporation, a New Jersey corporation and the predecessor "
            "registrant (“ExxonMobil”), completed its previously announced redomiciliation.")
    assert edgar.predecessor_name(text) == "Exxon Mobil Corporation"
    assert edgar.predecessor_name("A routine 8-K about a dividend.") is None
    hits = [{"_source": {"display_names": ["IMPERIAL OIL LTD  (IMO)  (CIK 0000049938)"]}},
            {"_source": {"display_names": ["EXXON MOBIL CORP  (XOM)  (CIK 0000034088)"]}}]
    assert edgar.pick_predecessor(hits, "Exxon Mobil Corporation", "XOM", "0002115436") == \
        {"cik": "0000034088", "name": "EXXON MOBIL CORP"}
    # The successor itself is never its own predecessor.
    assert edgar.pick_predecessor(hits[1:], "Exxon Mobil Corporation", "XOM", "0000034088") is None


def test_a_moved_ticker_reads_the_predecessors_annual_report(monkeypatch, tmp_path):
    from alphadesk.ledger import store
    monkeypatch.setenv("ALPHADESK_DATA", str(tmp_path))
    store.init()
    pred = {"cik": "0000034088", "name": "EXXON MOBIL CORP"}
    monkeypatch.setattr(company.edgar, "recent_filings", lambda s, forms=None, limit=1: [])
    monkeypatch.setattr(company.edgar, "predecessor_of", lambda s: pred)
    monkeypatch.setattr(company.edgar, "filings_for_cik", lambda cik, s, forms, limit=1: [
        {"accession": "0000034088-26-000010", "form": "10-K", "filing_date": "2026-02-18", "url": "https://x/xom.htm"}])
    monkeypatch.setattr(company.edgar, "fetch_filing_text", lambda url, max_chars=0:
                        "Item 1. Business " + "We produce oil. " * 40 + "Item 1A. Risk Factors")
    got = company._tenk("XOM")
    assert got["predecessor"] == pred and got["business"].startswith("Item 1. Business")
    assert company._tenk("XOM")["predecessor"] == pred    # also from the kept sections


def test_a_share_class_is_looked_up_in_the_secs_spelling(monkeypatch):
    # Vendors write "BRK.B"; the SEC list writes "BRK-B" (2026-09-19).
    from alphadesk.ingest import edgar
    assert edgar.sec_ticker("brk.b") == "BRK-B"
    assert edgar.sec_ticker("BF/B") == "BF-B"
    assert edgar.sec_ticker("BTC/USD") == "BTC/USD" and edgar.sec_ticker("AAPL") == "AAPL"
    monkeypatch.setattr(edgar, "_ticker_cik_cache", {"BRK-B": "0001067983"})
    assert edgar.cik_for("BRK.B") == "0001067983"
