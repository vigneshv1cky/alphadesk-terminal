"""Speed changes from the 2026-10-03 review."""
import asyncio
import threading


def test_sync_mcp_tools_run_off_the_event_loop():
    from alphadesk import mcp_server

    seen = {}

    @mcp_server.mcp.tool()
    def _probe_thread() -> str:
        """Probe: records the thread it runs on."""
        seen["thread"] = threading.current_thread()
        return "ok"

    assert mcp_server._run_tools_in_threads() >= 1               # the new sync tool is moved
    assert mcp_server._run_tools_in_threads() == 0               # idempotent

    async def go():
        main = threading.current_thread()
        await mcp_server.mcp.call_tool("_probe_thread", {})
        return main

    main = asyncio.run(go())
    assert seen["thread"] is not main


def test_every_tool_is_still_there_after_the_move():
    from alphadesk import mcp_server
    assert len(mcp_server.mcp._tool_manager._tools) >= 50


def test_the_news_owner_index_exists(store):
    with store._connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_news_owner_published" in names


def test_a_repeated_query_is_embedded_once(monkeypatch):
    from alphadesk import semantic
    calls = []
    monkeypatch.setattr(semantic, "_embed_query_uncached", lambda q: calls.append(q) or [1.0, 2.0])
    semantic._QUERY_MEMO.clear()
    assert semantic.embed_query("rates") == [1.0, 2.0]
    assert semantic.embed_query("rates") == [1.0, 2.0]
    semantic.embed_query("oil")
    assert calls == ["rates", "oil"]


def test_news_lists_can_skip_the_article_text(store):
    import uuid
    from datetime import datetime, timedelta, timezone

    uid = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    store.save_articles([
        {"id": "with", "title": "has text", "url": "https://x/1", "published_at": now.isoformat(),
         "tickers": ["AAPL"], "body": "a long story " * 50, "feeds": ["alpaca"]},
        {"id": "without", "title": "no text", "url": "https://x/2", "published_at": (now - timedelta(minutes=1)).isoformat(),
         "tickers": ["AAPL"], "feeds": ["alpaca"]},
    ], owner=uid)
    since = (now - timedelta(days=1)).isoformat()
    full = {a["article_id"]: a for a in store.recent_articles(since, owner=uid)}
    assert full["with"]["body"].startswith("a long story")
    light = {a["article_id"]: a for a in store.recent_articles(since, owner=uid, body=False)}
    assert "body" not in light["with"] and light["with"]["has_body"] is True and light["without"]["has_body"] is False
    sym = {a["article_id"]: a for a in store.articles_for_symbol(uid, "AAPL", limit=10, body=False)}
    assert sym["with"]["has_body"] is True and "body" not in sym["with"]
    older = {a["article_id"]: a for a in store.articles_before(uid, (now + timedelta(days=1)).isoformat(), 10, body=False)}
    assert older["without"]["has_body"] is False


def test_a_composite_read_is_remembered_and_shared(monkeypatch):
    import threading
    import time

    from alphadesk.desk import memo
    memo.clear()
    built = []

    def slow():
        built.append(1)
        time.sleep(0.05)
        return {"n": len(built)}

    out = []
    ts = [threading.Thread(target=lambda: out.append(memo.cached(("k",), 5.0, slow))) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(built) == 1 and all(o == {"n": 1} for o in out)
    assert memo.cached(("k",), 5.0, slow) == {"n": 1}
    assert memo.cached(("k",), 0.0, slow) == {"n": 2}                  # expired: rebuilt
    memo.clear()


def test_a_failed_rebuild_is_not_remembered():
    import pytest

    from alphadesk.desk import memo
    memo.clear()
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("down")
        return "fine"

    with pytest.raises(RuntimeError):
        memo.cached(("f",), 5.0, flaky)
    assert memo.cached(("f",), 5.0, flaky) == "fine"
    memo.clear()


def test_a_symbols_news_comes_from_the_side_table(store):
    import uuid
    from datetime import datetime, timedelta, timezone

    uid = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    store.save_articles([
        {"id": f"s{i}", "title": f"t{i}", "url": f"https://x/{i}", "published_at": (now - timedelta(minutes=i)).isoformat(),
         "tickers": ["SVRN", "NVDA"] if i % 2 == 0 else ["NVDA"], "feeds": ["alpaca"]} for i in range(6)
    ], owner=uid)
    got = store.articles_for_symbol(uid, "svrn", limit=10)
    assert [a["article_id"] for a in got] == ["s0", "s2", "s4"]            # newest first, only that symbol
    older = store.articles_for_symbol(uid, "SVRN", before_iso=(now - timedelta(minutes=1)).isoformat(), limit=10)
    assert [a["article_id"] for a in older] == ["s2", "s4"]
    assert store.articles_for_symbol(uid, "F", limit=10) == []             # a substring of another symbol never slips in
    with store._lock, store._connect() as conn:                            # stories gone: their ticker rows go with them
        conn.execute("DELETE FROM news_articles WHERE owner=? AND article_id='s0'", (uid,))
        conn.execute(store._ORPHAN_TICKERS)
    assert [a["article_id"] for a in store.articles_for_symbol(uid, "SVRN", limit=10)] == ["s2", "s4"]


def test_stories_stored_before_the_side_table_are_filled_in_once(store):
    import json
    import uuid

    uid = uuid.uuid4().hex
    with store._lock, store._connect() as conn:
        conn.execute("DELETE FROM news_tickers")
        conn.execute("INSERT INTO news_articles (owner, article_id, title, published_at, tickers, feeds)"
                     " VALUES (?, 'old1', 't', '2026-09-01T00:00:00+00:00', ?, 'alpaca')", (uid, json.dumps(["AAPL", "MSFT"])))
    store.init()
    assert [a["article_id"] for a in store.articles_for_symbol(uid, "MSFT", limit=5)] == ["old1"]
    store.init()                                                           # a second start adds nothing
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM news_tickers WHERE owner=?", (uid,)).fetchone()["n"] == 2


def test_search_indexes_are_only_made_on_postgres(store, monkeypatch):
    from alphadesk.ledger import db
    assert store.ensure_search_indexes() == 0                       # SQLite: nothing to make

    seen = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, *a):
            seen.append(sql)

    monkeypatch.setattr(db, "backend", lambda: "postgres")
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    assert store.ensure_search_indexes() == len(store._POSTGRES_SEARCH_DDL)
    assert seen[0] == "CREATE EXTENSION IF NOT EXISTS pg_trgm"
    # each index sits on the same expression the search queries use
    joined = " ".join(seen)
    for expr in ("lower(title)", "lower(coalesce(summary, ''))", "lower(tickers)", "lower(coalesce(source, ''))"):
        assert expr in joined


def test_a_missing_extension_does_not_break_start_up(store, monkeypatch):
    from alphadesk.ledger import db

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, *a):
            raise RuntimeError("permission denied to create extension")

    monkeypatch.setattr(db, "backend", lambda: "postgres")
    monkeypatch.setattr(store, "_connect", lambda: Conn())
    assert store.ensure_search_indexes() == 0                        # logged, not raised


def test_a_postgres_url_without_a_user_connects_as_the_os_user(monkeypatch):
    """A Homebrew Postgres has your login as its superuser and no role called postgres."""
    import pg8000.dbapi

    from alphadesk.ledger import db
    seen = {}
    monkeypatch.setattr(pg8000.dbapi, "connect", lambda **kw: seen.update(kw) or object())
    monkeypatch.setattr(db, "_PgConn", lambda raw: raw)
    monkeypatch.setenv("ALPHADESK_DATABASE_URL", "postgresql://localhost:5432/alphadesk")
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.setenv("USER", "someone")
    db._pg_connect()
    assert seen["user"] == "someone" and seen["database"] == "alphadesk" and seen["port"] == 5432
    monkeypatch.setenv("PGUSER", "pguser")
    db._pg_connect()
    assert seen["user"] == "pguser"
    monkeypatch.setenv("ALPHADESK_DATABASE_URL", "postgresql://named@localhost/alphadesk")
    db._pg_connect()
    assert seen["user"] == "named"                                   # a user in the URL always wins
