"""The company behind a symbol: who it is, what it does, where it is.

PRIMARY SOURCE FIRST. EDGAR's submissions record carries the registrant's
legal name, SIC code, state of incorporation, fiscal year end, filer
category, phone, business and mailing addresses and former names — the
facts a company files under oath. The latest 10-K carries the two sections
that answer "what does it do" and "where is it": Item 1 (Business) and
Item 2 (Properties). Both are returned VERBATIM with the accession of the
filing they came from; nothing here paraphrases a filing.

The user's own profile vendor (Financial Modeling Prep, Alpha Vantage or
Finnhub) fills what EDGAR does not structure — the plain-English business
summary, headcount, website, sector and industry.

"How many locations" is not a structured fact anywhere. The 10-K Properties
section is the company's own statement of its sites and square footage;
the profile shows that statement rather than inventing a count from it.
Nothing here polls.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from alphadesk.ingest import coingecko, edgar, secfacts

log = logging.getLogger(__name__)

_TTL_S = 86_400
_cache: dict[str, tuple[float, dict | None]] = {}
_lock = threading.Lock()

# A 10-K's Properties section can sit past 100k characters of Business and
# Risk Factors; the Q&A path's cap (FILING_MAX_CHARS) is sized for an LLM
# context, not for reaching Item 2.
TENK_MAX_CHARS = 900_000
BUSINESS_MAX = 9_000
PROPERTIES_MAX = 7_000


def _headings(pat: str, text: str, pos: int = 0):
    """Matches of a heading pattern that are not quoted in prose — a
    cross-reference reads 'see “Item 4. Information About SAP – …”'."""
    for m in re.compile(pat, re.I).finditer(text, pos):
        if not re.search(r"[“\"][^”\"]{0,80}$", text[max(0, m.start() - 80): m.start()]):
            yield m


def extract_item(text: str, start_pat: str, end_pat: str, cap: int,
                 min_len: int = 400) -> tuple[str, bool] | None:
    """The body of a 10-K item between two headings.

    The table of contents lists every heading once before the body does, so
    the FIRST match is usually a one-line entry. Every start is tried and the
    longest span to the next heading wins — the body is the one with pages
    behind it. Returns (excerpt, truncated) or None when the headings are
    not found or the span is too short to be a section."""
    # A heading quoted in prose ("see “Item 4. Information About SAP –
    # Description of Property”") is a cross-reference, not the section; its
    # span to the next quoted "Item 5" once outran SAP's real one.
    # The same holds for the closing heading: Alibaba's Item 4 quotes "Item
    # 5" two thousand characters in, and its real section was cut there
    # while a cross-reference ran on through the risk factors.
    starts = [(m.start(), m.end()) for m in _headings(start_pat, text)]
    if not starts:
        return None
    closed, open_ = "", ""
    for s, e in starts:
        # The end heading is searched from the end of THIS heading, so a
        # table-of-contents entry closes on the very next line and loses.
        m = next(_headings(end_pat, text, e), None)
        if m:
            seg = text[s: m.start()]
            if len(seg) > len(closed):
                closed = seg
        else:
            seg = text[s: s + cap * 3]
            if len(seg) > len(open_):
                open_ = seg
    # A span that ENDS at the next item's heading is the section; one that
    # runs on to the cap is a cross-reference in prose ("Item 1 Business and
    # Note 15 of the Notes…" deep in Alphabet's 10-K, 2026-09-19), and wins
    # only when no heading closes.
    best = (closed if len(closed.strip()) >= min_len else open_).strip()
    if len(best) < min_len:
        return None
    return (best[:cap].rstrip() + ("…" if len(best) > cap else ""), len(best) > cap)


def spaced(phrase: str) -> str:
    """A heading phrase as a pattern that tolerates one stray space INSIDE a
    word. Filers style headings in small capitals or letter-spacing, and the
    extracted text splits the word: Microsoft's 10-K reads "ITEM 1. B USINESS"
    and "ITEM 1A. RIS K FACTORS" (2026-09-19), so a plain "business" never
    matched and its Profile had no business section. Pure."""
    return r"\s+".join(r"\s?".join(re.escape(c) for c in word) for word in phrase.split())


BUSINESS_START = r"item\s*1\s*[.:\-–—]?\s*" + spaced("business") + r"\b"
BUSINESS_END = r"item\s*1a\s*[.:\-–—]?\s*" + spaced("risk factors")
# "Item 2. Description of Properties" is Berkshire's wording.
PROPERTIES_START = (r"item\s*2\s*[.:\-–—]?\s*(?:" + spaced("description of") + r"\s+)?"
                    + spaced("properties") + r"\b")
#: A properties section can be one short paragraph (Alphabet's is ~300
#: characters); a table-of-contents line is ~30.
PROPERTIES_MIN = 150
PROPERTIES_END = r"item\s*3\s*[.:\-–—]?\s*" + spaced("legal proceedings")

# A FOREIGN PRIVATE ISSUER files a 20-F, where the same two sections carry
# other numbers: Item 4 is the business and Item 4.D the property (TSMC and
# Alibaba both read as blank until this was added, 2026-09-15). The form
# decides which headings to look for, and the citation names the form.
FORM_ITEMS = {
    "10-K": {"form": "10-K", "business": ("Item 1, Business", BUSINESS_START, BUSINESS_END),
             "properties": ("Item 2, Properties", PROPERTIES_START, PROPERTIES_END)},
    "20-F": {"form": "20-F",
             "business": ("Item 4, Information on the Company",
                          # SAP's reads "Item 4. Information about SAP".
                          r"item\s*4\s*[.:\-–—]?\s*" + spaced("information") + r"\s+(?:on|about)\s+(?=\S)",
                          r"item\s*4a\s*[.:\-–—]?\s*" + spaced("unresolved") + r"|item\s*5\s*[.:\-–—]?\s*" + spaced("operating")),
             "properties": ("Item 4.D, Property, Plants and Equipment",
                            r"(?:item\s*4\.?\s*)?d\s*[.:\-–—]?\s*" + spaced("property,") + r"?\s*" + spaced("plants") + r"?\s+" + spaced("and equipment")
                            + r"|\b" + spaced("description of property") + r"\b",
                            r"item\s*4a\s*[.:\-–—]?\s*" + spaced("unresolved") + r"|item\s*5\s*[.:\-–—]?\s*" + spaced("operating"))},
}
#: Newest first: a company that has filed both is read as a domestic filer.
ANNUAL_FORMS = ("10-K", "20-F")

# A 20-F follows the form's item order only if the filer chooses to; many
# write their own report and file a cross-reference table instead. TSMC's
# has no "Item 4.D" heading at all: its property is under "Our Semiconductor
# Facilities" inside Item 4 (2026-09-19). So when no Item 4.D heading is
# found, a Title Case heading naming facilities or properties is read, CASE-
# SENSITIVELY — a heading is capitalised where a sentence mentioning "our
# facilities" is not — and not where it is quoted as a cross-reference.
_FACILITIES_HEADING = re.compile(
    r"(?<![“\"–—-] )(?<![“\"])\b((?:Our |Principal )?(?:[A-Z][a-z]+ ){0,2}(?:Facilities|Properties))"
    r" (?=(?:We|Our|The|As|In|[A-Z][a-z]+ (?:currently|operates?|owns?|leases?|has|have))\b)")


def facilities_section(text: str) -> tuple[str, tuple[str, bool]] | None:
    """(heading, (excerpt, truncated)) for a 20-F's property section under a
    heading of the filer's own, or None. The section's end is not marked in
    flattened text, so the excerpt runs to the properties cap. Pure."""
    for m in _FACILITIES_HEADING.finditer(text or ""):
        body = text[m.start(): m.start() + PROPERTIES_MAX * 3].strip()
        if len(body) < PROPERTIES_MIN:
            continue
        return m.group(1), (body[:PROPERTIES_MAX].rstrip() + ("…" if len(body) > PROPERTIES_MAX else ""),
                            len(body) > PROPERTIES_MAX)
    return None


def clean_category(raw: str | None) -> str | None:
    """EDGAR's filer category is a fragment of HTML — "Large accelerated
    filer<br>Emerging growth company", or just "<br>Emerging growth company"
    — with a line-break tag between the parts. Tags become separators;
    empty parts are dropped."""
    if not raw:
        return None
    parts = [p.strip() for p in re.split(r"<[^>]+>", raw)]
    parts = [p for p in parts if p]
    return " · ".join(parts) or None


# REFERENCE NOTES for the instruments on the cross-asset board that no feed
# describes: an index, a futures contract or a currency pair has a name,
# an exchange and a price in the profile feed and nothing else. These are
# authored here — what the thing measures, and where to read further: the
# publisher's or exchange's own page first, then the central bank or agency
# that fixes or reports the price where there is one, then a neutral
# reference. The page labels them as reference notes, not as fetched facts.
# Keyed by the conventional index, futures and currency symbols.
REFERENCE: dict[str, dict] = {
    "^GSPC": {"name": "S&P 500",
              "what": "The S&P 500 tracks 500 large US companies, weighted by float-adjusted market capitalisation; it is the benchmark most US equity funds are measured against.",
              "publisher": "S&P Dow Jones Indices", "url": "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
              "sources": [{"label": "S&P Dow Jones Indices", "url": "https://www.spglobal.com/spdji/en/indices/equity/sp-500/"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/s/sp500.asp"}]},
    "^DJI": {"name": "Dow Jones Industrial Average",
              "what": "The Dow Jones Industrial Average is a price-weighted average of 30 large US companies — the oldest continuously published US equity index, dating to 1896.",
              "publisher": "S&P Dow Jones Indices", "url": "https://www.spglobal.com/spdji/en/indices/equity/dow-jones-industrial-average/",
              "sources": [{"label": "S&P Dow Jones Indices", "url": "https://www.spglobal.com/spdji/en/indices/equity/dow-jones-industrial-average/"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/d/djia.asp"}]},
    "^IXIC": {"name": "Nasdaq Composite",
              "what": "The Nasdaq Composite covers essentially every stock listed on the Nasdaq exchange, weighted by market capitalisation, and is heavy in technology.",
              "publisher": "Nasdaq", "url": "https://www.nasdaq.com/market-activity/index/comp",
              "sources": [{"label": "Nasdaq", "url": "https://www.nasdaq.com/market-activity/index/comp"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/n/nasdaqcompositeindex.asp"}]},
    "^RUT": {"name": "Russell 2000",
              "what": "The Russell 2000 tracks the 2,000 smallest companies in the Russell 3000 — the standard gauge of US small-cap stocks.",
              "publisher": "FTSE Russell", "url": "https://www.lseg.com/en/ftse-russell/indices/russell-us",
              "sources": [{"label": "FTSE Russell", "url": "https://www.lseg.com/en/ftse-russell/indices/russell-us"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/r/russell2000.asp"}]},
    "^VIX": {"name": "Cboe Volatility Index",
              "what": "The Cboe Volatility Index measures the market's expectation of 30-day S&P 500 volatility, derived from the prices of S&P 500 index options.",
              "publisher": "Cboe Global Markets", "url": "https://www.cboe.com/tradable_products/vix/",
              "sources": [{"label": "Cboe Global Markets", "url": "https://www.cboe.com/tradable_products/vix/"}, {"label": "Cboe VIX white paper", "url": "https://cdn.cboe.com/resources/vix/vixwhite.pdf"}]},
    "^TNX": {"name": "10-year Treasury yield",
              "what": "The Cboe 10-year Treasury note yield index quotes the yield on the on-the-run US 10-year Treasury note, in percent times ten (a reading of 45.0 means 4.50%).",
              "publisher": "Cboe Global Markets", "url": "https://www.cboe.com/tradable_products/vix/vix_options/",
              "sources": [{"label": "Cboe Global Markets", "url": "https://www.cboe.com/tradable_products/vix/vix_options/"}, {"label": "US Treasury daily yield curve", "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/1/10-yeartreasury.asp"}]},
    "CL=F": {"name": "WTI crude oil futures",
              "what": "WTI crude oil futures: contracts for 1,000 barrels of West Texas Intermediate crude, delivered at Cushing, Oklahoma. The front-month contract is the price quoted here.",
              "publisher": "CME Group contract specs", "url": "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html",
              "sources": [{"label": "CME Group contract specs", "url": "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html"}, {"label": "US Energy Information Administration", "url": "https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm"}]},
    "GC=F": {"name": "Gold futures",
              "what": "Gold futures: contracts for 100 troy ounces of gold, deliverable at COMEX-approved depositories. The front-month contract is the price quoted here.",
              "publisher": "CME Group contract specs", "url": "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html",
              "sources": [{"label": "CME Group contract specs", "url": "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html"}, {"label": "LBMA gold price", "url": "https://www.lbma.org.uk/prices-and-data/precious-metal-prices"}]},
    "SI=F": {"name": "Silver futures",
              "what": "Silver futures: contracts for 5,000 troy ounces of silver. The front-month contract is the price quoted here.",
              "publisher": "CME Group contract specs", "url": "https://www.cmegroup.com/markets/metals/precious/silver.contractSpecs.html",
              "sources": [{"label": "CME Group contract specs", "url": "https://www.cmegroup.com/markets/metals/precious/silver.contractSpecs.html"}, {"label": "LBMA silver price", "url": "https://www.lbma.org.uk/prices-and-data/precious-metal-prices"}]},
    "EURUSD=X": {"name": "EUR/USD",
              "what": "The euro against the US dollar: how many dollars one euro buys. The most traded currency pair in the world; quoted from the interbank market, which has no exchange.",
              "publisher": "European Central Bank reference rate", "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/eurofxref-graph-usd.en.html",
              "sources": [{"label": "European Central Bank reference rate", "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/eurofxref-graph-usd.en.html"}, {"label": "Federal Reserve H.10 rates", "url": "https://www.federalreserve.gov/releases/h10/current/"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/e/eur-usd-euro-us-dollar-currency-pair.asp"}]},
    "GBPUSD=X": {"name": "GBP/USD",
              "what": "The British pound against the US dollar: how many dollars one pound buys, quoted from the interbank market.",
              "publisher": "Bank of England spot rates", "url": "https://www.bankofengland.co.uk/boeapps/database/Rates.asp?Travel=NIxAZx&into=USD",
              "sources": [{"label": "Bank of England spot rates", "url": "https://www.bankofengland.co.uk/boeapps/database/Rates.asp?Travel=NIxAZx&into=USD"}, {"label": "Federal Reserve H.10 rates", "url": "https://www.federalreserve.gov/releases/h10/current/"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/g/gbp-usd-british-pound-us-dollar-currency-pair.asp"}]},
    "JPY=X": {"name": "USD/JPY",
              "what": "The US dollar against the Japanese yen: how many yen one dollar buys, quoted from the interbank market.",
              "publisher": "Bank of Japan FX rates", "url": "https://www.boj.or.jp/en/statistics/market/forex/index.htm",
              "sources": [{"label": "Bank of Japan FX rates", "url": "https://www.boj.or.jp/en/statistics/market/forex/index.htm"}, {"label": "Federal Reserve H.10 rates", "url": "https://www.federalreserve.gov/releases/h10/current/"}, {"label": "Investopedia", "url": "https://www.investopedia.com/terms/u/usd-jpy-us-dollar-japanese-yen-currency-pair.asp"}]},
}


def _address(a: dict | None) -> dict | None:
    if not a or not a.get("street1"):
        return None
    return {
        "street": " ".join(x for x in (a.get("street1"), a.get("street2")) if x),
        "city": a.get("city"),
        "state": a.get("stateOrCountryDescription") or a.get("stateOrCountry"),
        "zip": a.get("zipCode"),
        "country": a.get("country"),
    }


#: A registrant's EDGAR record, kept a day. PUBLIC DATA, SO ONE SHARED ENTRY
#: (2026-09-16): the equity overview asks for the fiscal year end on every
#: quote, and each ask fetched the company's whole submissions record through
#: EDGAR's process-wide rate limiter — a fifth of a second per stock, queued
#: behind every other stock on the page, for a date that changes when a
#: company changes its fiscal calendar. The invariant that keys vendor caches
#: by reader does not apply: EDGAR is keyless and the same for everyone.
_facts_cache: dict[str, tuple[float, dict | None]] = {}
FACTS_KEEP_S = 86_400


def _edgar_facts(symbol: str) -> dict | None:
    import time as _time
    key = (symbol or "").upper()
    hit = _facts_cache.get(key)
    if hit and _time.time() - hit[0] < FACTS_KEEP_S:
        return hit[1]
    got = _edgar_facts_fetch(key)
    # A failed fetch is not remembered, so the next ask can succeed.
    if got is not None:
        if len(_facts_cache) > 5_000:
            _facts_cache.clear()
        _facts_cache[key] = (_time.time(), got)
    return got


def _edgar_facts_fetch(symbol: str) -> dict | None:
    cik10 = edgar.cik_for(symbol)
    if not cik10:
        return None
    try:
        d = json.loads(edgar._get(edgar._SUBMISSIONS_URL.format(cik10=cik10)))
    except Exception as exc:
        log.warning("EDGAR submissions fetch failed for %s: %s", symbol, exc)
        return None
    fye = d.get("fiscalYearEnd") or ""
    addrs = d.get("addresses") or {}
    # A foreign private issuer files 20-F or 40-F annual reports instead of
    # a 10-K; on a US exchange its listing is an American depositary
    # receipt, and the page should say so rather than "company".
    forms = (d.get("filings") or {}).get("recent", {}).get("form") or []
    foreign = any(f in ("20-F", "40-F", "20-F/A", "40-F/A") for f in forms[:400])
    return {
        "foreign_private_issuer": foreign,
        "cik": cik10,
        "legal_name": d.get("name"),
        "sic": d.get("sic"),
        "sic_description": d.get("sicDescription"),
        "state_of_incorporation": d.get("stateOfIncorporationDescription") or d.get("stateOfIncorporation"),
        "fiscal_year_end": f"{fye[:2]}-{fye[2:]}" if len(fye) == 4 else None,
        "entity_type": d.get("entityType"),
        "filer_category": clean_category(d.get("category")),
        "phone": d.get("phone"),
        "website": d.get("website") or None,
        "investor_website": d.get("investorWebsite") or None,
        "exchanges": d.get("exchanges") or [],
        "tickers": d.get("tickers") or [],
        "former_names": [
            {"name": f.get("name"), "from": (f.get("from") or "")[:10] or None, "to": (f.get("to") or "")[:10] or None}
            for f in (d.get("formerNames") or []) if f.get("name")
        ],
        "business_address": _address(addrs.get("business")),
        "mailing_address": _address(addrs.get("mailing")),
    }


def _vendor_profile(symbol: str) -> tuple[dict | None, list[dict]]:
    """The profile block from whichever vendor the user connected carries a
    company profile (2026-09-13 — the Yahoo profile is gone). Officers come
    from no free vendor, so the list is empty unless one supplies it."""
    from alphadesk.providers import get_prices
    got = get_prices().get("company_profile", symbol.upper())
    if not got:
        return None, []
    addr = got.get("address") or {}
    prof = {
        "name": got.get("name"), "summary": got.get("summary"), "description": got.get("description"),
        "circulating_supply": None, "start_date": got.get("ipo_date"), "expiry": None, "open_interest": None,
        "underlying": None, "sector": got.get("sector"), "industry": got.get("industry"),
        "employees": got.get("employees"), "website": got.get("website"), "investor_website": None,
        "phone": got.get("phone"),
        "address": {"street": addr.get("street"), "city": addr.get("city"), "state": addr.get("state"),
                    "zip": addr.get("zip"), "country": addr.get("country") or got.get("country")},
        "exchange": got.get("exchange"), "currency": got.get("currency"), "market_cap": got.get("market_cap"),
        "quote_type": got.get("quote_type"), "vendor": got.get("vendor"),
    }
    return prof, list(got.get("officers") or [])


#: Bump when extract_item changes, so kept sections are read again.
SECTION_READER_VERSION = 4   # 4: a 20-F's facilities heading; hidden XBRL block dropped


def _tenk(symbol: str) -> dict | None:
    """The company's latest annual report, and the two sections it quotes:
    a 10-K's Business and Properties, or a 20-F's Item 4 and Item 4.D."""
    rows = edgar.recent_filings(symbol, forms=ANNUAL_FORMS, limit=1)
    pred = None
    if not rows:
        # A ticker that moved to a successor registrant (XOM, 2026-07-01)
        # has no annual report under it until the successor files one; the
        # predecessor's report is the company's own, and is cited as the
        # predecessor's.
        pred = edgar.predecessor_of(symbol)
        if pred:
            rows = edgar.filings_for_cik(pred["cik"], symbol, ANNUAL_FORMS, limit=1)
    if not rows:
        return None
    f = rows[0]
    items = FORM_ITEMS.get((f.get("form") or "10-K").upper().replace("/A", ""))
    if items is None:
        return None
    # A filed annual report never changes: its sections are read once and
    # kept by accession (2026-09-19 — reading them was 2–3.6s on every
    # profile view). A newer report has a new accession and is read afresh.
    from alphadesk.ledger import store
    kept = store.get_annual_report_sections(f["accession"])
    if kept and kept.get("reader") == SECTION_READER_VERSION:
        return {**kept, "predecessor": pred}
    text = edgar.fetch_filing_text(f["url"], max_chars=TENK_MAX_CHARS)
    out = {"accession": f["accession"], "filing_date": f["filing_date"], "url": f["url"],
           "form": items["form"], "business_item": items["business"][0],
           "properties_item": items["properties"][0],
           "business": None, "business_truncated": False,
           "properties": None, "properties_truncated": False}
    if not text:
        return {**out, "predecessor": pred}
    b = extract_item(text, items["business"][1], items["business"][2], BUSINESS_MAX)
    p = extract_item(text, items["properties"][1], items["properties"][2], PROPERTIES_MAX, PROPERTIES_MIN)
    if not p and items["form"] == "20-F":
        found = facilities_section(text)
        if found:
            heading, p = found
            out["properties_item"] = f"Item 4, “{heading}”"
    if b:
        out["business"], out["business_truncated"] = b
    if p:
        out["properties"], out["properties_truncated"] = p
    # Kept even when a section was not found: re-reading the same filing
    # finds the same nothing. The reader version re-reads them once the
    # section reader improves.
    out["reader"] = SECTION_READER_VERSION
    store.save_annual_report_sections(f["accession"], out)
    return {**out, "predecessor": pred}


def _sources(sym: str, name: str, facts: dict | None, prof: dict | None) -> list[dict]:
    """Where to read further about ANY profile, not only the reference notes:
    the SEC's filing index for a registrant, the official site and the
    investor page where the feed has them, the coin trackers for a
    cryptocurrency, and a neutral reference for everything. Search links,
    where a direct page cannot be known, are labelled as searches."""
    from urllib.parse import quote_plus
    out: list[dict] = []
    if facts and facts.get("cik"):
        out.append({"label": "SEC EDGAR filings",
                    "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={facts['cik']}&owner=include&count=40"})
    site = (prof or {}).get("website") or (facts or {}).get("website")
    if site:
        host = site.replace("https://", "").replace("http://", "").rstrip("/")
        out.append({"label": f"Official site ({host})", "url": site})
    ir = (prof or {}).get("investor_website") or (facts or {}).get("investor_website")
    if ir and ir != site:
        out.append({"label": "Investor relations", "url": ir})
    qt = ((prof or {}).get("quote_type") or "").upper()
    if qt == "CRYPTOCURRENCY":
        base = sym.split("-")[0]
        out.append({"label": "CoinGecko (search)", "url": f"https://www.coingecko.com/en/search?query={quote_plus(base)}"})
        out.append({"label": "CoinMarketCap (search)", "url": f"https://coinmarketcap.com/search/?q={quote_plus(base)}"})
    return out


def _crypto_key() -> str | None:
    """The user's own CoinGecko key from their market-data vendors, or None
    — without it no coin profile is fetched (2026-09-13: no keyless calls)."""
    try:
        from alphadesk.providers import get_prices
        vendor = get_prices().vendors.get("coingecko")
        inner = getattr(vendor, "_inner", vendor)
        return (getattr(inner, "api_key", "") or "").strip() or None
    except Exception:
        return None


def _coin(sym: str) -> dict | None:
    from alphadesk.providers.alpaca import coin_pair
    key = _crypto_key()
    if not coin_pair(sym) or not key:
        return None
    return coingecko.coin(sym, key)


def _financials(sym: str, facts: dict | None) -> dict | None:
    """The SEC's structured facts for the registrant; for a successor with
    none tagged yet (XOM's holding company), its predecessor's, said so."""
    if not facts or not facts.get("cik"):
        return None
    got = secfacts.facts(facts["cik"])
    if got and got.get("items"):
        return got
    pred = edgar.predecessor_of(sym)
    if pred:
        theirs = secfacts.facts(pred["cik"])
        if theirs and theirs.get("items"):
            # The successor's own share count is the current one.
            if got and got.get("shares_outstanding"):
                theirs = {**theirs, "shares_outstanding": got["shares_outstanding"]}
            return {**theirs, "predecessor": pred}
    return got


def profile(symbol: str) -> dict | None:
    """{symbol, name, edgar, profile, officers, tenk, financials, coin,
    reference, sources} — None only when no source knows the symbol."""
    sym = symbol.upper()
    # Not cached here: the vendor half is the user's (the per-user vendor
    # memo holds it) and the EDGAR half caches itself.
    facts = _edgar_facts(sym)
    prof, officers = _vendor_profile(sym)
    # A coin has no company record and no reference entry; its CoinGecko
    # record alone makes the page (2026-09-19: with the key connected, a
    # coin still showed "needs a data key", because the coin was only
    # looked up after a company record had been found).
    coin = _coin(sym)
    out: dict | None
    if not facts and not prof and sym not in REFERENCE and not coin:
        out = None
    else:
        name = ((prof or {}).get("name") or (facts or {}).get("legal_name") or REFERENCE.get(sym, {}).get("name")
                or (coin or {}).get("name") or sym)
        out = {
            "symbol": sym,
            "name": name,
            "edgar": facts,
            "profile": prof,
            "officers": officers,
            "tenk": _tenk(sym) if facts else None,
            "reference": REFERENCE.get(sym),
            "sources": _sources(sym, name, facts, prof),
            # The outside sources that are FETCHED, not only cited: the
            # SEC's structured facts for a registrant, CoinGecko's record
            # for a coin.
            "financials": _financials(sym, facts),
            "coin": coin,
        }
    return out
