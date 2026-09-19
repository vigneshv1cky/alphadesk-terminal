"""The news search rule (alphadesk/newsquery.py), shared by the app's filter
box, "Search all" and the agent's news_search — no model."""

from alphadesk import newsquery
from alphadesk.newsquery import expand, matches, stem


def test_word_forms_match_but_a_capitalised_ticker_stays_exact():
    assert stem("tariffs") == "tariff" and stem("companies") == "company" and stem("crashes") == "crash"
    assert stem("news") == "news" and stem("gas") == "gas"
    assert matches("tariff", "New tariffs on steel") and matches("rate cut", "Fed rate cuts loom")
    assert matches("arm", "an arms sale")            # lower case: the word
    assert not matches("ARM", "an arms sale")        # capitals: the ticker
    assert not matches("ARM", "Sen. Alan Armstrong bought stock")
    assert matches("robin", "Why Is Robinhood Falling") and not matches("hood", "a neighborhood network")


def test_a_company_the_query_names_widens_it(monkeypatch):
    import alphadesk.config as config
    table = {
        "robinhood": [{"symbol": "HOOD", "name": "Robinhood Markets, Inc."}],
        "HOOD": [{"symbol": "HOOD", "name": "Robinhood Markets, Inc."}],
        "fed": [{"symbol": "FEDU", "name": "Four Seasons Education"}, {"symbol": "FDX", "name": "FEDEX CORP"}],
        "google": [{"symbol": "GOOGL", "name": "Alphabet Inc."}],
    }
    monkeypatch.setattr(config, "search_symbols", lambda q, limit=12: table.get(q, []))
    assert expand("robinhood") == {"tickers": ["HOOD"], "names": ["robinhood"]}
    assert expand("HOOD") == {"tickers": ["HOOD"], "names": ["robinhood"]}
    assert expand("fed") == {"tickers": [], "names": []}   # FedEx is not "fed"
    assert expand("google")["tickers"][:2] == ["GOOGL", "GOOG"]  # the alias list
    hood = expand("HOOD")
    assert matches("HOOD", "Robinhood Rallies", tickers=tuple(hood["tickers"]), names=tuple(hood["names"]))
    assert matches("robinhood", "Shares jump", tags=["HOOD"], tickers=("HOOD",))
    assert not matches("robinhood", "Apple rallies", tags=["AAPL"], tickers=("HOOD",))


def test_search_all_reaches_a_companys_tagged_stories(store, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(newsquery, "expand", lambda q: {"tickers": ["HOOD"], "names": []} if q == "robinhood"
                        else {"tickers": [], "names": []})
    now = datetime.now(timezone.utc).isoformat()
    base = {"summary": "", "source": "T", "image_url": "", "author": "", "body": "", "published_at": now}
    store.save_articles([
        {**base, "id": "h1", "title": "Shares jump on a new product", "url": "u1", "tickers": ["HOOD"]},
        {**base, "id": "t1", "title": "New tariffs on steel", "url": "u2", "tickers": []},
        {**base, "id": "x1", "title": "Apple rallies", "url": "u3", "tickers": ["AAPL"]},
    ], owner="u1")
    ids = lambda q: [a["article_id"] for a in store.articles_before("u1", "9999-12-31T00:00:00+00:00", 20, q)]  # noqa: E731
    assert ids("robinhood") == ["h1"]      # tagged HOOD, the word never appears
    assert ids("tariff") == ["t1"]         # the plural
    assert ids("companies") == []


def test_a_capitalised_ticker_skips_the_word_in_a_summary():
    """"HOOD" had matched a summary saying "under the hood"."""
    assert not matches("HOOD", "SCHD vs. VIG", "They diverge under the hood", tickers=("HOOD",), names=("robinhood",))
    assert matches("HOOD", "Robinhood Stock Rises", tickers=("HOOD",), names=("robinhood",))
    assert matches("ARM", "Arm vs. Intel", tickers=("ARM",), names=("arm",))
    assert not matches("ARM", "Senate Blocks Arms Sale", tickers=("ARM",), names=("arm",))
