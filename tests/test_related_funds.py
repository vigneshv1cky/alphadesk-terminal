"""The funds built on one company, matched from FMP's fund listing as it
stood on 2026-09-15: 23 US-listed funds carry NVIDIA's name, 26 Tesla's,
16 MicroStrategy's and 2 CrowdStrike's."""

from alphadesk.ingest.related_funds import company_word, fund_kind, single_stock_funds

LISTING = {
    "NVDL": "GraniteShares 2x Long NVDA Daily ETF",
    "NVDU": "Direxion Daily NVDA Bull 2X ETF",
    "NVDX": "T-REX 2X Long NVIDIA Daily Target ETF",
    "NVD": "GraniteShares 2x Short NVDA Daily ETF",
    "NVDD": "Direxion Daily NVDA Bear 1X ETF",
    "NVDS": "Tradr 1.5X Short NVDA Daily ETF",
    "NVDY": "YieldMax NVDA Option Income Strategy ETF",
    "NVIB": "Direxion Shares ETF Trust - Direxion NVDA Defined Income Boost ETF",
    "LAYS": "STKd 100% NVDA & 100% AMD ETF",
    "NVD2.L": "Leverage Shares - 2x NVIDIA",
    "NVHE.TO": "Harvest NVIDIA Enhanced High Income Shares ETF",
    "NVDA": "NVIDIA Corporation",
    "SOXL": "Direxion Daily Semiconductor Bull 3X Shares",
    "CONVEY": "A fund whose name merely contains nvda inside a word",
}


def test_the_funds_built_on_a_company_are_grouped_by_what_they_do():
    rows = single_stock_funds(LISTING, "NVDA", "NVIDIA Corporation")
    kinds = {r["symbol"]: r["kind"] for r in rows}
    assert kinds["NVDL"] == "leveraged" and kinds["NVD"] == "inverse"
    assert kinds["NVDY"] == "income" and kinds["NVIB"] == "buffered" and kinds["LAYS"] == "paired"
    # Leveraged before inverse before income; the bigger multiple first.
    assert [r["symbol"] for r in rows[:3]] == ["NVDL", "NVDU", "NVDX"]
    assert rows[3]["symbol"] == "NVD" and rows[3]["leverage"] == -2.0


def test_a_ticker_inside_a_word_is_not_a_match():
    rows = {r["symbol"] for r in single_stock_funds(LISTING, "NVDA", "NVIDIA Corporation")}
    assert "CONVEY" not in rows and "SOXL" not in rows and "NVDA" not in rows


def test_foreign_listings_are_left_out():
    """A London or Toronto line cannot be priced or charted on the reader's
    keys, so a name with no figures would be all it showed."""
    rows = {r["symbol"] for r in single_stock_funds(LISTING, "NVDA", "NVIDIA Corporation")}
    assert "NVD2.L" not in rows and "NVHE.TO" not in rows


def test_the_company_name_matches_where_the_ticker_does_not():
    rows = {r["symbol"] for r in single_stock_funds(LISTING, "NVDA", "NVIDIA Corporation")}
    assert "NVDX" in rows          # "T-REX 2X Long NVIDIA Daily Target ETF"


def test_a_company_word_too_common_is_not_evidence():
    """MicroStrategy renamed itself Strategy, a word 232 unrelated funds
    use; its funds are found by ticker alone."""
    assert company_word("Strategy Inc") is None
    assert company_word("NVIDIA Corporation") == "nvidia"
    assert company_word("Tesla, Inc.") == "tesla"
    listing = {"MSTU": "T-REX 2X Long MSTR Daily Target ETF",
               "CEW": "WisdomTree Emerging Currency Strategy Fund"}
    assert [r["symbol"] for r in single_stock_funds(listing, "MSTR", "Strategy Inc")] == ["MSTU"]


def test_the_kind_is_read_from_the_name():
    assert fund_kind("GraniteShares 2x Long CRWD Daily ETF") == "leveraged"
    assert fund_kind("Direxion Daily TSLA Bear 1X ETF") == "inverse"
    assert fund_kind("Tradr 1.5X Short NVDA Daily ETF") == "inverse"
    assert fund_kind("Roundhill Investments - AAPL WeeklyPay ETF") == "income"
    assert fund_kind("FT Vest NVDA & Target Income ETF") == "buffered"
    assert fund_kind("GraniteShares Autocallable PLTR ETF") == "other"


def test_a_fund_has_no_funds_built_on_it():
    """CRWC is "Corgi CRWD 2x Daily ETF". Read as a company its first word
    is the issuer, which matched every Corgi fund listed (2026-09-15)."""
    assert company_word("Corgi ETF Trust I - Corgi CRWD 2x Daily ETF") is None
    assert company_word("GraniteShares 2x Long NVDA Daily ETF") is None
    listing = {"CRWC": "Corgi ETF Trust I - Corgi CRWD 2x Daily ETF",
               "AMDC": "Corgi ETF Trust I - Corgi AMD 2x Daily ETF"}
    assert single_stock_funds(listing, "CRWC", "Corgi CRWD 2x Daily ETF") == []


class _Router:
    """A reader's connected vendors: the fund listing, a quote, and the
    basket prices — which carry the session's share count."""
    answered_by = "fmp"

    def __init__(self, quotes=None, quotes_raise=False):
        self._quotes, self._raise = quotes, quotes_raise
        self.asked: list[str] = []

    def get(self, surface, symbol):
        return {"name": "NVIDIA Corporation"} if surface == "quote" else None

    def ask(self, surface, arg=None):
        self.asked.append(surface)
        if surface == "fund_names":
            # The vendor's listing is funds only — NVDA itself is in the
            # fixture above to prove the company is never matched as one.
            return {k: v for k, v in LISTING.items() if k != "NVDA"}
        if surface == "quotes":
            if self._raise:
                raise RuntimeError("the basket failed")
            return self._quotes
        return None


def test_each_fund_carries_what_traded(monkeypatch):
    """How much of the fund changed hands, which is what says whether a line
    is usable: NVDX and NVDU were within a tenth of each other in size on
    2026-09-17 and traded $68m against $19m."""
    from alphadesk.ingest import related_funds as rf
    router = _Router(quotes={
        "NVDX": {"price": 19.19, "change_pct": 5.09, "volume": 3_545_488},
        "NVDU": {"price": 135.50, "change_pct": 4.92, "volume": 137_509},
    })
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: router)
    rows = {r["symbol"]: r for r in rf.related_funds("NVDA")["funds"]}
    assert rows["NVDX"]["volume"] == 3_545_488
    assert rows["NVDU"]["volume"] == 137_509
    # No extra vendor call: the count rides the quote the price came from.
    assert router.asked.count("quotes") == 1 and "market_caps" not in router.asked
    # A fund the basket did not price still lists, with nothing traded shown.
    assert rows["NVDY"]["volume"] is None and rows["NVDY"]["price"] is None


def test_a_basket_that_fails_still_lists_the_funds(monkeypatch):
    """The listing is the panel; prices and volumes are what decorate it."""
    from alphadesk.ingest import related_funds as rf
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: _Router(quotes_raise=True))
    rows = rf.related_funds("NVDA")["funds"]
    assert rows and all(r["volume"] is None and r["price"] is None for r in rows)
