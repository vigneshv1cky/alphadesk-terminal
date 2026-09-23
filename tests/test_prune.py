"""store.prune_vendor_data: vendor data is kept only as long as a feature
reads it (2026-09-18)."""
from datetime import datetime, timedelta, timezone


def _iso(now, **kw):
    return (now - timedelta(**kw)).isoformat()


def test_prune_keeps_what_features_read_and_drops_the_rest(store):
    now = datetime.now(timezone.utc)
    rows = [
        # (id, published, ingested, body)
        ("fresh", _iso(now, hours=2), _iso(now, hours=2), "text"),
        ("in-margin", _iso(now, days=5), _iso(now, days=5), "old text"),
        ("stale", _iso(now, days=9), _iso(now, days=9), None),
        ("older-page-today", _iso(now, days=30), _iso(now, hours=2), None),
        ("older-page-yesterday", _iso(now, days=30), _iso(now, hours=30), None),
    ]
    with store._lock, store._connect() as conn:
        for aid, pub, ing, body in rows:
            conn.execute("INSERT INTO news_articles (owner, article_id, title, published_at, ingested_at, body)"
                         " VALUES ('u1', ?, 't', ?, ?, ?)", (aid, pub, ing, body))
        today = now.date()
        conn.execute("INSERT INTO earnings_announcements (owner, symbol, url, published_at, report_date)"
                     " VALUES ('u1','OLD','x', ?, ?)", (_iso(now, days=60), (today - timedelta(days=45)).isoformat()))
        conn.execute("INSERT INTO earnings_announcements (owner, symbol, url, published_at, report_date)"
                     " VALUES ('u1','NEW','y', ?, ?)", (_iso(now, days=2), (today + timedelta(days=5)).isoformat()))
        conn.execute("INSERT INTO release_habits (owner, symbol, computed_at) VALUES ('u1','A', ?)", (_iso(now, days=4),))
        conn.execute("INSERT INTO release_habits (owner, symbol, computed_at) VALUES ('u1','B', ?)", (_iso(now, days=1),))
        conn.execute("INSERT INTO press_release_checks (owner, symbol, checked_at) VALUES ('u1','A', ?)", (_iso(now, days=2),))
        conn.execute("INSERT INTO reader_dollar_pools (owner, vendor, symbols, built_at) VALUES ('u1','alpaca','[]', ?)",
                     (int((now - timedelta(days=10)).timestamp()),))
        conn.execute("INSERT INTO earnings_forecasts (owner, vendor, symbol, captured_on, report_date)"
                     " VALUES ('u1','fmp','A', ?, ?)", ((today - timedelta(days=200)).isoformat(), (today - timedelta(days=199)).isoformat()))
        conn.execute("INSERT INTO earnings_forecasts (owner, vendor, symbol, captured_on, report_date)"
                     " VALUES ('u1','fmp','B', ?, ?)", ((today - timedelta(days=10)).isoformat(), (today - timedelta(days=9)).isoformat()))
        conn.execute("INSERT INTO earnings (symbol, report_date) VALUES ('ZZ', '2026-01-01')")

    out = store.prune_vendor_data(now)

    with store._connect() as conn:
        left = {r["article_id"]: r["body"] for r in conn.execute("SELECT article_id, body FROM news_articles")}
        assert set(left) == {"fresh", "in-margin", "older-page-today"}
        assert left["fresh"] == "text" and left["in-margin"] is None        # text only inside the window
        assert [r["symbol"] for r in conn.execute("SELECT symbol FROM earnings_announcements")] == ["NEW"]
        assert [r["symbol"] for r in conn.execute("SELECT symbol FROM release_habits")] == ["B"]
        assert conn.execute("SELECT COUNT(*) AS n FROM press_release_checks").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM reader_dollar_pools").fetchone()["n"] == 0
        assert [r["symbol"] for r in conn.execute("SELECT symbol FROM earnings_forecasts")] == ["B"]
        assert conn.execute("SELECT COUNT(*) AS n FROM earnings").fetchone()["n"] == 0
    assert out["news"] == 2 and out["news_bodies"] == 1
    assert all(v == 0 for v in store.prune_vendor_data(now).values())   # idempotent


def test_removing_a_key_deletes_what_it_fetched(store):
    with store._lock, store._connect() as conn:
        for aid, feeds in (("only-poly", "polygon"), ("both", "alpaca,polygon"), ("only-alpaca", "alpaca")):
            conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds) VALUES ('u1', ?, 't', ?)", (aid, feeds))
        conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds) VALUES ('u2', 'other', 't', 'polygon')")
        conn.execute("INSERT INTO earnings_forecasts (owner, vendor, symbol, captured_on, report_date) VALUES ('u1','fmp','A','2026-09-01','2026-09-02')")
        conn.execute("INSERT INTO earnings_forecasts (owner, vendor, symbol, captured_on, report_date) VALUES ('u1','finnhub','A','2026-09-01','2026-09-02')")
    assert store.purge_vendor_data("u1", "news", "polygon")["news"] == 1
    assert store.purge_vendor_data("u1", "prices", "fmp")["forecasts"] == 1
    with store._connect() as conn:
        news = {r["article_id"]: r["feeds"] for r in conn.execute("SELECT owner, article_id, feeds FROM news_articles WHERE owner='u1'")}
        assert news == {"both": "alpaca", "only-alpaca": "alpaca"}
        assert conn.execute("SELECT COUNT(*) AS n FROM news_articles WHERE owner='u2'").fetchone()["n"] == 1
        assert [r["vendor"] for r in conn.execute("SELECT vendor FROM earnings_forecasts")] == ["finnhub"]


def test_the_key_route_purges(client, store, monkeypatch):
    import uuid

    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    uid = uuid.uuid4().hex
    store.create_user(uid, "r@example.com", auth.hash_password("a-long-password"))
    assert client.post("/api/auth/login", json={"email": "r@example.com", "password": "a-long-password"}).status_code == 200
    store.set_user_key(uid, "news", "polygon", "sealed", "…abcd")
    with store._lock, store._connect() as conn:
        conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds) VALUES (?, 'x', 't', 'polygon')", (uid,))
    assert client.delete("/api/keys/news/polygon").status_code == 200
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM news_articles WHERE owner=?", (uid,)).fetchone()["n"] == 0


def test_stories_from_a_feed_you_no_longer_hold_are_named(client, store, monkeypatch):
    """A feed removed BEFORE the purge landed (2026-09-18) left its stories
    behind, and they showed up in the news list under publishers the reader
    could not account for — an aggregating feed carries dozens of them, so
    "why do I see thirty sources on one feed?" had no answer on the page.
    They are named on the Account page instead, with what becomes of them."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    uid = uuid.uuid4().hex
    store.create_user(uid, "orphan@example.com", auth.hash_password("a-long-password"))
    assert client.post("/api/auth/login", json={"email": "orphan@example.com",
                                                "password": "a-long-password"}).status_code == 200
    store.set_user_key(uid, "news", "alpaca", "sealed", "…abcd")
    fresh = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    with store._lock, store._connect() as conn:
        # One story from the feed they still hold, two from one they do not.
        conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds, ingested_at)"
                     " VALUES (?, 'a', 't', 'alpaca', ?)", (uid, fresh))
        conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds, ingested_at)"
                     " VALUES (?, 'b', 't', 'alphavantage', ?)", (uid, old))
        conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds, ingested_at)"
                     " VALUES (?, 'c', 't', 'alphavantage', ?)", (uid, old))
    body = client.get("/api/keys").json()
    assert body["orphan_feeds"] == [{"provider": "alphavantage", "stories": 2}]
    # The feed they DO hold is never called an orphan of itself.
    assert all(o["provider"] != "alpaca" for o in body["orphan_feeds"])
    # And the page can say when they go, rather than leaving it a mystery.
    assert body["news_keep_days"] > 0


def test_a_reader_with_only_feeds_they_hold_has_no_orphans(client, store, monkeypatch):
    import uuid
    from datetime import datetime, timezone

    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    uid = uuid.uuid4().hex
    store.create_user(uid, "clean@example.com", auth.hash_password("a-long-password"))
    assert client.post("/api/auth/login", json={"email": "clean@example.com",
                                                "password": "a-long-password"}).status_code == 200
    store.set_user_key(uid, "news", "alpaca", "sealed", "…abcd")
    with store._lock, store._connect() as conn:
        conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds, ingested_at)"
                     " VALUES (?, 'a', 't', 'alpaca', ?)", (uid, datetime.now(timezone.utc).isoformat()))
    assert client.get("/api/keys").json()["orphan_feeds"] == []
