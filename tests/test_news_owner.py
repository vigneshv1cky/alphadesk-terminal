"""Per-user news feeds (phase 3): window ownership, the activity-gated poll
roster, the per-user poll cycle billing the reader, and the primary-key
rebuild migration that carries a pre-phase-3 database's articles into the
shared feed."""

import base64
from datetime import datetime, timezone

import pytest

from alphadesk import identity as ai_llm
from alphadesk.ingest import news
from alphadesk.ledger import vault
from alphadesk.providers import registry
from alphadesk.providers.base import Article

MASTER = base64.b64encode(b"\x07" * 32).decode()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", MASTER)
    news._user_news_provider.cache_clear()
    news._seen_ids.clear()
    yield
    news._user_news_provider.cache_clear()
    news._seen_ids.clear()


def _article(aid, title, symbols, owner_note=""):
    return {"id": aid, "title": title, "summary": owner_note, "source": "T",
            "url": f"https://x/{aid}", "published_at": datetime.now(timezone.utc).isoformat(),
            "tickers": symbols, "image_url": "", "author": "", "body": ""}


def _since():
    return "2000-01-01T00:00:00+00:00"


class TestOwnership:
    def test_windows_are_disjoint_by_owner(self, store):
        store.save_articles([_article("a1", "shared story", ["NVDA"])])
        store.save_articles([_article("a2", "their story", ["NVDA"])], owner="u1")
        shared = store.recent_articles(_since())
        mine = store.recent_articles(_since(), owner="u1")
        assert [a["article_id"] for a in shared] == ["a1"]
        assert [a["article_id"] for a in mine] == ["a2"]
        assert set(store.recent_articles_by_ticker(_since(), owner="u1")["NVDA"][0]["article_id"]) \
            == set("a2")

    def test_the_same_story_can_live_in_both_feeds(self, store):
        store.save_articles([_article("dup", "story", ["AAPL"])])
        store.save_articles([_article("dup", "story", ["AAPL"])], owner="u1")
        assert len(store.recent_articles(_since())) == 1
        assert len(store.recent_articles(_since(), owner="u1")) == 1

    def test_every_user_owns_their_own_window(self, store):
        # No server feed (2026-09-13): a signed-in user's window is theirs,
        # with or without a key; anonymous owns nothing.
        assert news.news_owner("u1") == "u1"
        assert news.news_owner(None) not in ("", "u1")

    def test_old_single_key_table_rebuilds_into_the_shared_feed(self, store):
        from alphadesk.ledger import db
        with store._connect() as conn:
            conn.execute("DROP TABLE news_articles")
            conn.execute(
                "CREATE TABLE news_articles ("
                " article_id TEXT PRIMARY KEY, title TEXT, summary TEXT, source TEXT,"
                " url TEXT, published_at TEXT, tickers TEXT, ingested_at TEXT,"
                " image_url TEXT, author TEXT, body TEXT)")
            conn.execute(
                "INSERT INTO news_articles (article_id, title, tickers, published_at)"
                " VALUES (?,?,?,?)", ("legacy1", "old story", '["NVDA"]', "2026-09-01T00:00:00+00:00"))
        store.init()
        with store._connect() as conn:
            assert "owner" in db.table_columns(conn, "news_articles")
        rows = store.recent_articles(_since())
        assert [a["article_id"] for a in rows] == ["legacy1"]


class TestPollRoster:
    def test_only_active_keyed_enabled_users_poll(self, store):
        for uid, email in (("u1", "a@x.y"), ("u2", "b@x.y"), ("u3", "c@x.y"), ("u4", "d@x.y")):
            store.create_user(uid, email, "sso-only")
        sealed = vault.encrypt({"api_key": "k-abcd1234"})
        store.set_user_key("u1", "news", "polygon", sealed, "1234")   # active + key
        store.set_user_key("u2", "news", "polygon", sealed, "1234")   # key, never seen
        store.set_user_key("u4", "news", "polygon", sealed, "1234")   # key, disabled
        store.touch_user_seen("u1")
        store.touch_user_seen("u3")                                    # active, no key
        store.touch_user_seen("u4")
        with store._connect() as conn:
            conn.execute("UPDATE users SET disabled=1 WHERE user_id=?", ("u4",))
        assert store.news_poll_users() == ["u1"]


class _FakeNews:
    name = "fake-news"
    capabilities = ("summaries",)
    built: list = []

    def __init__(self, *, api_key=None, api_secret=None):
        self.api_key = api_key
        _FakeNews.built.append(self)

    def fetch(self, since, limit=200):
        return [Article(id="n1", title="their headline", url="https://x/n1",
                        published_at=datetime.now(timezone.utc).isoformat(),
                        symbols=["NVDA"], summary="s")]
class TestPollUser:
    @pytest.fixture(autouse=True)
    def _fakes(self, monkeypatch):
        _FakeNews.built = []
        registry.register("news", _FakeNews.name, _FakeNews)
        registry.reset_cache()
        yield
        registry.reset_cache()

    def test_the_readers_key_fetches_owns_and_bills(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "news", _FakeNews.name,
                           vault.encrypt({"api_key": "news-key-9876"}), "9876")
        n = news.poll_user("u1", datetime.now(timezone.utc))
        assert n == 1
        assert _FakeNews.built[-1].api_key == "news-key-9876"
        assert store.recent_articles(_since()) == []                       # shared feed untouched
        assert [a["article_id"] for a in store.recent_articles(_since(), owner="u1")] == ["n1"]
        assert store.get_user_key("u1", "news")["last_used_at"] is not None

    def test_a_user_without_a_key_polls_nothing(self, store):
        store.create_user("u2", "b@c.d", "sso-only")
        assert news.poll_user("u2", datetime.now(timezone.utc)) == 0
        assert _FakeNews.built == []

    def test_the_screener_window_follows_the_request_user(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "news", _FakeNews.name,
                           vault.encrypt({"api_key": "news-key-9876"}), "9876")
        store.save_articles([_article("shared1", "operator story", ["TSLA"])])
        news.poll_user("u1", datetime.now(timezone.utc))
        from alphadesk.desk import screener
        anon = {r["symbol"] for r in screener.inventory() if r["article_count"]}
        token = ai_llm.set_request_user("u1")
        try:
            theirs = {r["symbol"] for r in screener.inventory() if r["article_count"]}
        finally:
            ai_llm.reset_request_user(token)
        assert anon == set()                                  # anonymous owns no window
        assert "NVDA" in theirs and "TSLA" not in theirs


class TestRealtimeAndHistory:
    """2026-09-15: stories streamed as they publish, the header's freshness
    per reader, and pages of older news."""

    def test_the_freshness_readout_is_the_readers_own_feed(self, store):
        store.save_articles([_article("s1", "shared story from before the change", ["NVDA"])])
        store.save_articles([_article("u1a", "their story", ["NVDA"])], owner="u1")
        mine, nobody = store.news_health("u1"), store.news_health("u2")
        assert mine["last_article_at"] is not None and mine["articles_today"] == 1
        assert nobody["last_article_at"] is None and nobody["articles_today"] == 0

    def test_a_streamed_story_is_stored_as_the_readers_and_counted(self, store, monkeypatch):
        refills = []
        monkeypatch.setattr(news.threading, "Timer",
                            lambda delay, fn, args: type("T", (), {"daemon": False, "start": lambda self: refills.append((delay, args))})())
        store.create_user("u1", "a@b.c", "sso-only")
        before = news.stream_seq("u1")
        story = Article(id="live-1", title="Crude oil hits $106", url="https://x/live-1",
                        published_at=datetime.now(timezone.utc).isoformat(), symbols=["USO"], summary="s")
        assert news.ingest_streamed("u1", story) is True
        assert news.stream_seq("u1") == before + 1
        rows = store.recent_articles(_since(), owner="u1")
        assert [r["article_id"] for r in rows] == ["live-1"] and rows[0]["feeds"] == ["alpaca"]
        assert refills == [(news.STREAM_TEXT_RETRY_S, ("u1", "live-1"))]         # no text yet: asked again later
        assert news.ingest_streamed("u1", story) is False               # the same story again stores nothing
        assert news.stream_seq("u1") == before + 1

    def test_a_search_word_has_to_begin_a_word(self, store):
        """The reader searched "hood" for Robinhood's ticker and got a
        neighborhood store network and the likelihood of lung cancer
        (2026-09-17). A query now starts a word; it may still stop part-way
        through one, because a filter box is typed a prefix at a time."""
        store.create_user("u1", "a@b.c", "sso-only")
        store.save_articles([
            dict(_article("h1", "Amazon may need its own neighborhood store network", ["AMZN"]),
                 published_at="2026-09-17T18:00:00+00:00"),
            dict(_article("h2", "Patent granted for predicting the likelihood of lung cancer", ["BIAF"]),
                 published_at="2026-09-17T15:00:00+00:00"),
            dict(_article("h3", "Why Is Robinhood Markets Stock Falling Wednesday?", ["HOOD"]),
                 published_at="2026-09-17T11:00:00+00:00"),
        ], owner="u1")
        found = lambda q: [r["article_id"] for r in store.articles_before("u1", "9999-01-01", 10, q)]
        assert found("hood") == ["h3"]                  # the ticker, not the two words containing it
        assert found("robin") == ["h3"]                 # a prefix still finds it
        assert found("neighborhood") == ["h1"]
        assert found("store network") == ["h1"]         # a phrase, in order
        assert found("network store") == []
        assert found("zzz") == []

    def test_older_pages_and_search_read_the_store_then_the_feed(self, store, monkeypatch):
        store.create_user("u1", "a@b.c", "sso-only")
        old = [dict(_article(f"o{i}", f"story {i} about oil" if i % 2 else f"story {i}", ["XOM"]),
                    published_at=f"2026-09-1{i}T12:00:00+00:00") for i in range(1, 5)]
        store.save_articles(old, owner="u1")
        page = store.articles_before("u1", "2026-09-14T00:00:00+00:00", limit=10)
        assert [r["article_id"] for r in page] == ["o3", "o2", "o1"]
        assert [r["article_id"] for r in store.articles_before("u1", "9999-01-01", 10, "OIL")] == ["o3", "o1"]

        asked = []

        class _Back:
            name = "back-news"
            def __init__(self, *, api_key=None, api_secret=None):
                pass
            def fetch(self, since, limit=200, until=None):
                asked.append((since, until))
                return [Article(id="b1", title="older from the feed", url="https://x/b1",
                                published_at="2026-09-05T09:00:00+00:00", symbols=["XOM"])]

        registry.register("news", _Back.name, _Back)
        store.set_user_key("u1", "news", _Back.name, vault.encrypt({"api_key": "k"}), "k")
        got = news.older_articles("u1", "2026-09-12T00:00:00+00:00", limit=5)
        assert [r["article_id"] for r in got] == ["o1", "b1"]                # the store short of a page: the feed fills it
        assert asked and asked[0][1].isoformat().startswith("2026-09-12")
        asked.clear()
        news.older_articles("u1", "2026-09-12T00:00:00+00:00", limit=5, query="oil")
        assert asked == []                                               # a search never reaches back to the feed


class TestFullStory:
    """2026-09-15: Alpaca delivers Benzinga's full text only when asked; every
    stored story had arrived without it."""

    def test_a_story_redelivered_with_its_text_gains_it_and_nothing_else_changes(self, store):
        store.save_articles([{**_article("t1", "Red Cat rises", ["RCAT"]), "body": ""}], owner="u1")
        store.save_articles([{**_article("t1", "a different title", ["RCAT"]), "body": "Red Cat Holdings Inc. shares…"}], owner="u1")
        row = store.article("u1", "t1")
        assert row["body"] == "Red Cat Holdings Inc. shares…" and row["title"] == "Red Cat rises"
        store.save_articles([{**_article("t1", "Red Cat rises", ["RCAT"]), "body": "another text"}], owner="u1")
        assert store.article("u1", "t1")["body"] == "Red Cat Holdings Inc. shares…"   # stored text is never replaced

    def test_escaped_headlines_read_as_written(self, store):
        store.save_articles([{**_article("e1", "Maker&#39;s Q2 &amp; more", ["RCAT"]), "summary": "the drone maker&#39;s miss"}], owner="u1")
        row = store.recent_articles(_since(), owner="u1")[0]
        assert row["title"] == "Maker's Q2 & more" and row["summary"] == "the drone maker's miss"
        from types import SimpleNamespace
        from alphadesk.providers.news import alpaca_article
        art = alpaca_article(SimpleNamespace(id=7, headline="It&#39;s up", summary="maker&#39;s", url="u", symbols=["X"],
                                             created_at=None, source="benzinga", author="", content="<p>a&#8217;b</p>", images=[]))
        assert (art.title, art.summary, art.body) == ("It's up", "maker's", "a’b")

    def test_a_story_without_text_is_fetched_once_from_the_readers_alpaca_key(self, store, monkeypatch):
        from alphadesk.providers import news as provider_news
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "news", "alpaca", vault.encrypt({"api_key": "k", "api_secret": "s"}), "k")
        store.save_articles([{**_article("41", "Red Cat rises", ["RCAT"]), "feeds": ["alpaca"]}], owner="u1")
        calls = []

        def body(key, secret, article_id, symbol, published_at):
            calls.append((key, article_id, symbol))
            return Article(id=article_id, title="Red Cat rises", url="u", published_at=published_at,
                           symbols=[symbol], body="Full text of the story.")
        monkeypatch.setattr(provider_news, "alpaca_story_body", body)
        assert news.full_story("u1", "41")["body"] == "Full text of the story."
        assert news.full_story("u1", "41")["body"] == "Full text of the story."
        assert calls == [("k", "41", "RCAT")]                                       # stored, not asked again
        assert news.full_story("u1", "missing") is None


def test_the_news_list_carries_no_article_text_but_says_which_stories_have_it(client, store, monkeypatch):
    """2026-09-15: with full stories stored, 300 of them ran to ~1.5MB on a
    poll every minute; the reader fetches a story's text when it opens."""
    from alphadesk import identity as llm
    from alphadesk.app import dashboard
    monkeypatch.setattr(llm, "request_user", lambda: "u1")
    store.create_user("u1", "a@b.c", "sso-only")
    store.set_user_key("u1", "news", "alpaca", vault.encrypt({"api_key": "k", "api_secret": "s"}), "k")
    store.save_articles([{**_article("full", "with text", ["RCAT"]), "body": "The whole story."},
                         {**_article("short", "summary only", ["RCAT"])}], owner="u1")
    monkeypatch.setattr(dashboard, "_since_iso", lambda: _since(), raising=False)
    from alphadesk.desk import screener
    monkeypatch.setattr(screener, "_since_iso", lambda: _since())
    rows = {a["article_id"]: a for a in client.get("/api/news").json()["articles"]}
    assert "body" not in rows["full"] and rows["full"]["has_body"] is True and rows["short"]["has_body"] is False
    assert client.get("/api/news/full/story").json()["body"] == "The whole story."


def test_one_symbols_news_is_its_whole_window_not_the_shared_lists_newest(client, store, monkeypatch):
    """2026-09-18: the symbol panel filtered the shared list — the newest 500
    stories of every feed, a few hours — so a quiet name showed three of its
    two days. `symbol=` asks for that name's stories over the window."""
    from datetime import datetime, timedelta, timezone

    from alphadesk import identity as llm
    from alphadesk.desk import screener
    monkeypatch.setattr(llm, "request_user", lambda: "u1")
    store.create_user("u1", "a@b.c", "sso-only")
    store.set_user_key("u1", "news", "alpaca", vault.encrypt({"api_key": "k", "api_secret": "s"}), "k")
    now = datetime.now(timezone.utc)
    at = lambda h: (now - timedelta(hours=h)).isoformat()  # noqa: E731
    store.save_articles([
        {**_article("x1", "XLK story today", ["XLK"]), "published_at": at(1)},
        {**_article("x2", "XLK story yesterday", ["XLK"]), "published_at": at(30)},
        {**_article("x3", "XLK story last week", ["XLK"]), "published_at": at(24 * 6)},
        {**_article("n1", "an NVDA story", ["NVDA"]), "published_at": at(2)},
    ], owner="u1")
    monkeypatch.setattr(screener, "_since_iso", lambda: at(48))
    from alphadesk.app import dashboard
    monkeypatch.setattr(dashboard, "_since_iso", lambda: at(48), raising=False)
    ids = [a["article_id"] for a in client.get("/api/news?symbol=xlk").json()["articles"]]
    assert ids == ["x1", "x2"]                      # both days, newest first; nothing older, no other symbol
    older = client.get(f"/api/news?symbol=XLK&before={at(40)}").json()["articles"]
    assert [a["article_id"] for a in older] == ["x3"]  # the next page reaches past the window


def test_a_search_word_is_a_whole_word_so_a_ticker_finds_itself():
    """2026-09-18: "ARM" returned an arms sale and Senator Armstrong. A word
    must be whole; only a last word of five or more may stop part-way. The
    app's lib/newsMatch.ts runs the same rule."""
    from alphadesk.ledger.store import matches_query
    assert not matches_query("ARM", "Shaheen Has Blocked An Arms Sale To Israel")
    assert not matches_query("ARM", "Sen. Alan Armstrong Bought Williams Stock")
    assert matches_query("ARM", "AMD ARM NVDA") and matches_query("ARM", "Arm Holdings Rises")
    assert not matches_query("hood", "a neighborhood store network") and matches_query("hood", "HOOD MS")
    assert matches_query("robin", "Why Is Robinhood Falling") and not matches_query("benz", "benzinga")
    assert matches_query("jobless claims", "US Weekly Jobless Claims Fall")
    assert not matches_query("claims jobless", "US Weekly Jobless Claims Fall")
    assert matches_query("", "anything")
