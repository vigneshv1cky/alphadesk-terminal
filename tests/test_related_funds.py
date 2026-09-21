"""The funds built on one company, matched from FMP's fund listing as it
stood on 2026-09-15: 23 US-listed funds carry NVIDIA's name, 26 Tesla's,
16 MicroStrategy's and 2 CrowdStrike's."""

import pytest

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


def test_two_positions_joined_by_the_word_and_are_a_paired_fund():
    """ELOL, live on 2026-09-20, read as "other": the test for a paired fund
    looked only for an ampersand, and this name spells the word."""
    from alphadesk.ingest.related_funds import fund_kind
    assert fund_kind("Leverage Shares 100% TSLA AND 100% SPCX Daily ETF") == "paired"
    assert fund_kind("STKd 100% NVDA & 100% AMD ETF") == "paired"
    # One position is not a pair, whatever else the name says.
    assert fund_kind("iShares 100% Treasury Bond ETF") == "other"


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


# ── a company named after its industry (SPCX, 2026-09-20) ───────────────────

SPACE_LISTING = {
    "SPCH": "Leverage Shares 2X Long SPCX Daily ETF",
    "SPCQ": "Tidal Trust II - Defiance Daily Target 2X Short SPCX ETF",
    "YSPC": "YIELDMAX SPCX OPTION INCOME STRATEGY ETF",
    "ELOL": "Leverage Shares 100% TSLA AND 100% SPCX Daily ETF",
    "SPCL": "Defiance Pure Space Daily 2X Strategy ETF",
    "ARKX": "ARK Space & Defense Innovation ETF",
    "UFO": "Procure Space ETF",
    "WARP": "VanEck Space ETF",
    "SPCI": "Tuttle Capital Space Industry Income Blast ETF",
    "SPCX": "Space Exploration Technologies Corp. Class A Common Stock",
}
SPACE_COMPANY = "Space Exploration Technologies Corp. Class A Common Stock"


def test_sector_funds_sharing_the_company_word_are_left_out():
    """The company's distinctive word is "space", which every space-sector
    ETF also uses: twelve of them joined SPCX's panel (2026-09-20). A
    name-only match now has to declare what it does to a single stock."""
    from alphadesk.ingest.related_funds import company_word
    assert company_word(SPACE_COMPANY) == "space"
    rows = {r["symbol"] for r in single_stock_funds(SPACE_LISTING, "SPCX", SPACE_COMPANY)}
    assert {"SPCH", "SPCQ", "YSPC", "ELOL"} <= rows          # the ticker is proof
    assert not {"ARKX", "UFO", "WARP"} & rows                # plain sector baskets
    assert "SPCL" in rows                                     # declares "2X", so it stays


def test_the_classifier_settles_what_the_name_cannot():
    """A verdict from fundclass.py overrules the fallback either way: it
    keeps a sector-worded single-stock fund and drops an income-worded
    basket."""
    verdicts = {SPACE_LISTING["SPCI"]: "sector", SPACE_LISTING["ARKX"]: "single"}
    rows = {r["symbol"] for r in single_stock_funds(SPACE_LISTING, "SPCX", SPACE_COMPANY, verdicts=verdicts)}
    assert "SPCI" not in rows and "ARKX" in rows
    # NVIDIA is untouched: its word is its own, so nothing needs a verdict.
    assert len(single_stock_funds(LISTING, "NVDA", "NVIDIA Corporation")) == 9


def test_what_belongs_in_the_panel():
    from alphadesk.ingest.related_funds import keep_fund
    assert keep_fund("ticker", "other", None)                 # the ticker is proof
    assert not keep_fund("name", "other", None)               # a bare sector basket
    assert keep_fund("name", "leveraged", None)               # declares a single-stock bet
    assert keep_fund("name", "other", "single")               # the classifier says so
    assert not keep_fund("name", "leveraged", "sector")       # …and can overrule the name
    assert keep_fund("name", "income", "unclear")             # undecided falls back


def test_the_classifier_keeps_quiet_when_it_cannot_tell():
    from alphadesk import fundclass
    assert fundclass.verdict_for(0.05) == "single"
    assert fundclass.verdict_for(-0.05) == "sector"
    assert fundclass.verdict_for(0.001) is None
    assert fundclass.verdict_for(-0.001) is None


def test_verdicts_are_stored_once_per_fund_name(store):
    store.queue_fund_names(["Leverage Shares 2X Long SPCX Daily ETF"], verdict="single", model="ticker")
    store.queue_fund_names(["ARK Space & Defense Innovation ETF", "Procure Space ETF"])
    assert store.fund_verdicts(["Leverage Shares 2X Long SPCX Daily ETF"]) == {
        "Leverage Shares 2X Long SPCX Daily ETF": "single"}
    pending = store.pending_fund_names(10)
    assert set(pending) == {"ARK Space & Defense Innovation ETF", "Procure Space ETF"}
    store.save_fund_verdicts("test-model", [("Procure Space ETF", "sector", -0.04, "AAAA")])
    assert store.fund_verdicts(["Procure Space ETF"]) == {"Procure Space ETF": "sector"}
    assert store.pending_fund_names(10) == ["ARK Space & Defense Innovation ETF"]
    assert store.fund_examples("single") == [("Leverage Shares 2X Long SPCX Daily ETF", None)]
    assert store.fund_examples("sector") == [("Procure Space ETF", "AAAA")]


def test_a_names_numbers_are_kept_so_a_centre_costs_nothing_twice(store, monkeypatch):
    """The centre of the known single-stock names is an average over stored
    numbers. Every name is read through the model once, ever — the first
    version re-read up to four hundred of them each time the set grew."""
    import numpy as np

    from alphadesk import fundclass, semantic
    names = [f"Leverage Shares 2X Long AB{i} Daily ETF" for i in range(24)]
    store.queue_fund_names(names, verdict="single", model="ticker")
    asked: list[str] = []

    def fake_encode(texts):
        asked.extend(texts)
        return [np.asarray([0.6, 0.8, 0.0, 0.0], dtype=np.float32) for _ in texts]

    monkeypatch.setattr(semantic, "encode", fake_encode)
    monkeypatch.setattr(fundclass, "NEW_EXAMPLES_PER_TURN", len(names))
    first = fundclass._positive_centre()
    assert first is not None and sorted(asked) == sorted(names)
    asked.clear()
    second = fundclass._positive_centre()
    assert asked == []                                  # read once, kept for good
    assert np.allclose(first, second, atol=1e-3)


def test_the_classifier_reads_nothing_until_it_has_enough_examples(store, monkeypatch):
    """Below the floor it stays silent rather than guessing, and does not
    spend the processor finding that out."""
    from alphadesk import fundclass, semantic
    store.queue_fund_names(["Leverage Shares 2X Long AB Daily ETF"], verdict="single", model="ticker")
    monkeypatch.setattr(semantic, "encode", lambda texts: pytest.fail("read the model too early"))
    assert fundclass._positive_centre() is None


# ── what a fund says it is, in its own words (2026-09-20) ───────────────────

def test_what_a_funds_own_description_says_it_is():
    """A name states the STRUCTURE — daily, twice, through swaps — and not
    the SUBJECT. The vendor's description states the subject."""
    from alphadesk.fundclass import verdict_from_description as read
    assert read("The Fund seeks 2X the daily performance of a concentrated basket of three to "
                "ten space economy companies, generally equal-weighted.") == "sector"
    assert read("The Fund seeks daily investment results of 200% of the daily percentage change "
                "of the common stock of Tesla, Inc.") == "single"
    assert read("A synthetic covered call strategy on the reference asset.") is None
    assert read(None) is None and read("") is None


def test_reading_the_record_settles_what_the_name_could_not(store, monkeypatch):
    from alphadesk import fundclass
    said = {"SPCL": "2X the daily performance of a basket of space economy companies",
            "TSLT": "200% of the daily change of the common stock of Tesla, Inc."}

    class Router:
        uid = "u1"

        def get(self, surface, symbol):
            return {"description": said.get(symbol)}

    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: Router())
    queued = {"Defiance Pure Space Daily 2X Strategy ETF": "SPCL",
              "T-REX 2X Long TSLA Daily Target ETF": "TSLT"}
    store.queue_fund_names(list(queued))
    assert fundclass.read_records(queued) == 2
    assert store.fund_verdicts(list(queued)) == {
        "Defiance Pure Space Daily 2X Strategy ETF": "sector",
        "T-REX 2X Long TSLA Daily Target ETF": "single"}


def test_a_record_that_says_neither_hands_the_name_straight_on(store, monkeypatch):
    from alphadesk import fundclass

    class Router:
        uid = "u1"

        def get(self, surface, symbol):
            return {"description": "A synthetic covered call strategy on the reference asset."}

    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: Router())
    store.queue_fund_names(["YieldMax Something Option Income ETF"])
    assert store.pending_fund_names(10, grace_s=600) == []      # its record is still coming
    assert fundclass.read_records({"YieldMax Something Option Income ETF": "YMAX"}) == 0
    # Read and undecided: the name classifier takes it at once, not in ten minutes.
    assert store.pending_fund_names(10, grace_s=600) == ["YieldMax Something Option Income ETF"]


def test_a_fund_read_against_its_own_documents_is_dropped(store, monkeypatch):
    """SPCL is 2x daily on a basket of three to ten space companies, read
    from its profile on 2026-09-20. Its name declares a multiple and is
    worded like the single-stock products it sits among, so the fallback
    kept it and the centroids agreed — a verified verdict outranks both."""
    from alphadesk.ingest import related_funds as rf

    class Router:
        answered_by = "fmp"
        uid = None

        def get(self, surface, symbol):
            return {"name": SPACE_COMPANY} if surface == "quote" else None

        def ask(self, surface, arg=None):
            return {k: v for k, v in SPACE_LISTING.items() if k != "SPCX"} if surface == "fund_names" else None

    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: Router())
    rows = {r["symbol"] for r in rf.related_funds("SPCX")["funds"]}
    assert "SPCL" not in rows
    assert {"SPCH", "SPCQ", "YSPC", "ELOL"} <= rows          # the ticker is still proof


# ── how common a word is, counted rather than listed (2026-09-21) ───────────

def test_a_word_the_whole_listing_uses_is_not_evidence():
    """"Strategy" was refused by a hand-written list. Counting the vendor's
    own listing refuses a word nobody thought to add."""
    from alphadesk.ingest.related_funds import WORD_TOO_COMMON, company_word, word_uses
    # A made-up word no hand list would carry, in more funds than the floor.
    listing = {f"F{i}": f"Issuer {i} Vibranium Daily ETF" for i in range(WORD_TOO_COMMON + 1)}
    assert word_uses("vibranium", listing) == WORD_TOO_COMMON + 1
    assert company_word("Vibranium Mining Corp", listing) is None
    # Under the threshold it stands: a company's own funds must not refuse it.
    few = {f"F{i}": f"Issuer {i} Vibranium Daily ETF" for i in range(WORD_TOO_COMMON)}
    assert company_word("Vibranium Mining Corp", few) == "vibranium"


def test_counting_does_not_replace_reading_the_fund():
    """A count CANNOT tell a company named after its industry from that
    industry's funds: "space" is in about as many fund names as "nvidia".
    Both stand here, and what SPCX's look-alikes are is settled by their own
    descriptions (fundclass.py), not by this."""
    from alphadesk.ingest.related_funds import company_word
    listing = dict(SPACE_LISTING)
    listing.update(LISTING)
    assert company_word(SPACE_COMPANY, listing) == "space"
    assert company_word("NVIDIA Corporation", listing) == "nvidia"


def test_without_a_listing_the_hand_list_still_applies():
    from alphadesk.ingest.related_funds import company_word
    assert company_word("Strategy Inc") is None
    assert company_word("NVIDIA Corporation") == "nvidia"
