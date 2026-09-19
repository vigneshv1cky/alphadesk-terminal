"""Ledger round-trips. The store had no coverage at all before this."""


def test_init_drops_the_retired_trading_tables(store):
    """A pre-existing ledger loses its trading tables on first init.

    This is DESTRUCTIVE by design — the execution layer is gone and these
    outlived the code that wrote them — so it is worth a test that says so out
    loud rather than leaving it as a surprise.
    """
    import sqlite3

    dead = ["picks", "runs", "funnel", "skips", "price_daily", "earnings_reactions"]
    con = sqlite3.connect(store._DB)
    for t in dead:
        con.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY, junk TEXT)")
        con.execute(f"INSERT INTO {t} (junk) VALUES ('legacy row')")
    con.commit()
    con.close()

    store.init()

    con = sqlite3.connect(store._DB)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert not (set(dead) & names), f"still present after init: {set(dead) & names}"
    # and the tables the terminal actually uses survived
    assert {"news_articles", "earnings", "filings", "filing_text_cache"} <= names


def test_articles_round_trip_and_group_by_ticker(store):
    store.save_articles([
        {"id": "a1", "title": "Apple beats", "summary": "s", "source": "Reuters",
         "url": "https://x/1", "published_at": "2026-08-18T10:00:00Z",
         "tickers": ["AAPL", "MSFT"]},
        {"id": "a2", "title": "Msft news", "summary": "", "source": "BBG",
         "url": "https://x/2", "published_at": "2026-08-18T09:00:00Z", "tickers": ["MSFT"]},
    ])
    by_ticker = store.recent_articles_by_ticker("2026-08-01T00:00:00Z")
    assert set(by_ticker) == {"AAPL", "MSFT"}
    # a multi-ticker article shows up under EVERY symbol it mentions — the
    # screener window depends on this
    assert len(by_ticker["MSFT"]) == 2
    assert by_ticker["MSFT"][0]["title"] == "Apple beats"   # newest first


def test_saving_the_same_article_twice_does_not_duplicate(store):
    art = {"id": "dupe", "title": "t", "summary": "", "source": "s", "url": "u",
           "published_at": "2026-08-18T10:00:00Z", "tickers": ["AAPL"]}
    store.save_articles([art])
    store.save_articles([art])
    assert len(store.recent_articles_by_ticker("2026-01-01T00:00:00Z")["AAPL"]) == 1


def test_filing_text_round_trips(store):
    store.save_filings([{"accession": "0001", "symbol": "AAPL", "cik": "0000320193",
                         "form": "10-Q", "filing_date": "2026-07-31",
                         "report_date": "2026-06-30", "primary_doc": "d.htm",
                         "url": "https://sec/d.htm"}])
    assert store.get_filings("AAPL")[0]["form"] == "10-Q"
    assert store.get_filing_meta("0001")["url"] == "https://sec/d.htm"
    store.save_filing_text("0001", "the filing text")
    assert store.get_filing_text("0001") == "the filing text"


def test_reading_list_carries_the_article_extras(store):
    store.save_articles([
        {"id": "rich", "title": "T", "summary": "s", "source": "Src",
         "url": "https://x/r", "published_at": "2026-08-18T10:00:00Z",
         "tickers": ["MSFT", "AAPL"], "image_url": "https://img/x.jpg",
         "author": "A Writer", "body": "Full text.\n\nSecond paragraph."},
    ])
    arts = store.recent_articles("2026-08-01T00:00:00Z")
    assert len(arts) == 1
    a = arts[0]
    # one row per STORY, with the full ticker list decoded and sorted
    assert a["tickers"] == ["AAPL", "MSFT"]
    assert a["image_url"] == "https://img/x.jpg"
    assert a["author"] == "A Writer"
    assert a["body"].startswith("Full text.")


def test_a_story_from_two_feeds_is_one_row_that_names_both(store):
    """2026-09-14: which of the reader's feeds delivered a story is recorded,
    and a later feed delivering the same URL joins the row instead of
    storing the story twice."""
    polygon = {"id": "p1", "title": "t", "summary": "", "source": "Benzinga", "url": "https://x.com/a?utm=1",
               "published_at": "2026-09-14T10:00:00Z", "tickers": ["AAPL"], "feeds": ["polygon"]}
    assert store.save_articles([polygon], owner="u1") == []
    alpaca = {**polygon, "id": "a9", "url": "https://x.com/a/", "feeds": ["alpaca"]}
    assert store.save_articles([alpaca], owner="u1") == ["a9"]            # folded into p1
    assert store.save_articles([polygon], owner="u1") == []               # re-delivered: nothing new
    rows = store.recent_articles("2026-01-01T00:00:00Z", owner="u1")
    assert [(r["article_id"], r["feeds"]) for r in rows] == [("p1", ["alpaca", "polygon"])]
    assert store.feed_counts("u1", "2000-01-01") == {"alpaca": 1, "polygon": 1}
    # another reader's copy is theirs alone
    store.save_articles([alpaca], owner="u2")
    assert [r["feeds"] for r in store.recent_articles("2026-01-01T00:00:00Z", owner="u2")] == [["alpaca"]]
