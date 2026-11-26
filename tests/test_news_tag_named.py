"""A tag is kept only when the story names the company that owns the ticker
(2026-11-26, the owner: "Fix wrong-company tags"). The cases are the stories
that showed the fault on the live server that day."""
from alphadesk.newsquery import tag_is_named


def test_a_foreign_company_with_the_same_code_is_not_the_us_company():
    # Danish RTX A/S's results, tagged with RTX Corp's ticker.
    assert tag_is_named("RTX", "RTX Corp", "RTX A/S Reports Financial Results for the Quarter Ended September 30, 2026", "") is False


def test_the_us_company_itself_is_kept():
    assert tag_is_named("RTX", "RTX Corp", "Analysts Update Coverage and Price Targets for RTX Corporation", "") is True
    assert tag_is_named("RTX", "RTX Corp", "RTX's Pratt & Whitney Awarded $2.53 Billion U.S. Navy Contract", "") is True


def test_a_story_that_never_names_the_company_loses_the_tag():
    # Danone's Paris code is BN, which in New York is Brookfield.
    assert tag_is_named("BN", "BROOKFIELD Corp /ON/", "Chobani Fails to Dismiss Danone's Cold-Brew Coffee Lawsuit", "") is False


def test_the_summary_counts_as_well_as_the_headline():
    assert tag_is_named("MS", "MORGAN STANLEY", "Bilibili Price Targets Cut",
                        "Morgan Stanley and Deutsche Bank lowered their targets.") is True


def test_how_headlines_write_names():
    assert tag_is_named("NVDA", "NVIDIA CORP", "Democrats Open Probe Into Nvidia Influence", "") is True
    assert tag_is_named("DIS", "Walt Disney Co", "Disney Bets Big on Streaming", "") is True
    assert tag_is_named("MCD", "MCDONALDS CORP", "McDonald's has found a new way to sell burgers", "") is True
    assert tag_is_named("GOOGL", "Alphabet Inc.", "Google launches a new model", "", ("google",)) is True


def test_a_foreign_form_already_in_the_sec_name_is_the_same_company():
    assert tag_is_named("HSBC", "HSBC HOLDINGS PLC", "HSBC Holdings plc Announces Share Repurchase", "") is True


def test_what_cannot_be_judged_is_not_judged():
    assert tag_is_named("SPY", "SPDR S&P 500 ETF TRUST", "Fed cuts rates", "") is None
    assert tag_is_named("BTC-USD", None, "Bitcoin falls", "") is None


def test_brand_names_headlines_use():
    assert tag_is_named("RY", "ROYAL BANK OF CANADA", "RBC Releases Fall 2026 Financial Flexibility Poll Results", "") is True
    assert tag_is_named("ON", "ON SEMICONDUCTOR CORP", "Vadzo Launches a Camera Using onsemi AR0234 Sensor", "") is True
    assert tag_is_named("CART", "Maplebear Inc.", "DoorDash Secures Financing for Instacart Acquisition", "") is True


def test_a_two_letter_name_is_matched_in_capitals_only():
    assert tag_is_named("HPQ", "HP INC", "HP Inc. Reports Fiscal 2026 Fourth Quarter Results", "") is True
    assert tag_is_named("HPQ", "HP INC", "Engine output rises to 400 hp", "") is False


def test_a_german_merck_is_not_merck_and_co():
    assert tag_is_named("MRK", "Merck & Co., Inc.", "Merck KGaA Commences Tender Offer for Rapid Micro Biosystems", "") is False
