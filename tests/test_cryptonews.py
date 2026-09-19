"""A coin's news: all crypto and what moves it (alphadesk/cryptonews.py)."""

from alphadesk import cryptonews

STOCKS = frozenset({"COIN", "MSTR"})


def a(title="", summary="", tickers=()):
    return {"title": title, "summary": summary, "tickers": list(tickers)}


def test_any_coin_tag_in_any_spelling():
    for t in ("BTCUSD", "X:ETHUSD", "SOL-USD", "DOGEUSDT"):
        assert cryptonews.why(a(tickers=[t]), STOCKS) == "coin", t


def test_crypto_stocks_by_their_tag():
    assert cryptonews.why(a("Q3 results", tickers=["MSTR"]), STOCKS) == "crypto stock"


def test_crypto_and_rates_by_the_words():
    assert cryptonews.why(a("Stablecoin bill clears the Senate"), STOCKS) == "crypto"
    assert cryptonews.why(a("Powell signals a rate cut"), STOCKS) == "rates"
    # Rates by the headline only, and not the generic words.
    assert cryptonews.why(a("Dividend picks", "Inflation can drive dividends; Powell spoke"), STOCKS) is None
    assert cryptonews.why(a("Inflation Can Drive Dividends"), STOCKS) is None


def test_unrelated_stories_and_near_misses_stay_out():
    assert cryptonews.why(a("Nike beats on revenue", tickers=["NKE"]), STOCKS) is None
    # Whole words: "whether" is not "ether", "inflationary" is not a stem match.
    assert cryptonews.why(a("Whether the ethos holds"), STOCKS) is None
    # An equity ticker that merely ends in letters is not a coin tag.
    assert cryptonews.why(a(tickers=["AAPL"]), STOCKS) is None


def test_select_keeps_order_and_limit_and_marks_why():
    got = cryptonews.select([a("Bitcoin rallies"), a("Nike"), a("CPI hotter than expected"), a("Ether ETF flows")], 2)
    assert [g["why"] for g in got] == ["crypto", "rates"]


def test_the_curated_crypto_baskets_are_found():
    s = cryptonews.crypto_stocks()
    assert {"MSTR", "COIN", "IBIT", "CRCL"} <= s
    assert not {"HOOD", "PYPL", "XYZ"} & s
