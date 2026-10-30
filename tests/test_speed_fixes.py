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
    monkeypatch.setenv("ALPHADESK_DATABASE_URL", "postgresql://localhost:5432/alphadesk")
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.setenv("USER", "someone")
    db._raw_connect()
    assert seen["user"] == "someone" and seen["database"] == "alphadesk" and seen["port"] == 5432
    monkeypatch.setenv("PGUSER", "pguser")
    db._raw_connect()
    assert seen["user"] == "pguser"
    monkeypatch.setenv("ALPHADESK_DATABASE_URL", "postgresql://named@localhost/alphadesk")
    db._raw_connect()
    assert seen["user"] == "named"                                   # a user in the URL always wins


def _heavy_tool(monkeypatch, slots, wait_s, hold_s):
    """A stand-in `what_moved` behind the real tool wrapper, with `slots` heavy
    slots and a `wait_s` limit; it records how many run at once."""
    import time
    from alphadesk import agent_log, mcp_server
    monkeypatch.setattr(mcp_server, "_heavy_slots", threading.BoundedSemaphore(slots))
    monkeypatch.setattr(mcp_server, "HEAVY_WAIT_S", wait_s)
    monkeypatch.setattr(agent_log, "record", lambda *a, **k: None)
    running, peak = [0], [0]
    lock = threading.Lock()

    def what_moved():
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(hold_s)
        with lock:
            running[0] -= 1
        return "ok"

    return mcp_server._threaded(what_moved), peak


def test_heavy_agent_tools_run_a_few_at_a_time(monkeypatch):
    """A burst of heavy calls waits its turn instead of all running at once
    (2026-10-06: four what_moved calls in one second slowed every page)."""
    import anyio
    from alphadesk import mcp_server
    tool, peak = _heavy_tool(monkeypatch, slots=2, wait_s=10, hold_s=0.15)
    got = []

    async def burst():
        async with anyio.create_task_group() as tg:
            for _ in range(6):
                tg.start_soon(lambda: _append(got, tool))
    anyio.run(burst)
    assert got == ["ok"] * 6 and peak[0] == 2
    assert "what_moved" in mcp_server.HEAVY_TOOLS and "quote" not in mcp_server.HEAVY_TOOLS


async def _append(out, tool):
    out.append(await tool())


def test_a_queued_heavy_call_holds_no_worker_and_is_answered_busy(monkeypatch):
    """2026-10-30: an agent's burst queued for up to 319 s each INSIDE the
    worker threads the pages run on, and the front page took 23 s. A waiting
    call now holds no worker, and past the limit it is told the server is busy
    and given its slot back to nobody — nothing was read."""
    import anyio
    from alphadesk import mcp_server
    tool, peak = _heavy_tool(monkeypatch, slots=1, wait_s=0.3, hold_s=0.8)
    borrowed, outcomes = [], []

    async def call():
        try:
            outcomes.append(await tool())
        except mcp_server.HeavyBusy as exc:
            outcomes.append(str(exc))

    async def scenario():
        async with anyio.create_task_group() as tg:
            for _ in range(4):
                tg.start_soon(call)
            await anyio.sleep(0.15)
            # One call runs on a worker; the three waiting hold none.
            borrowed.append(anyio.to_thread.current_default_thread_limiter().borrowed_tokens)
    anyio.run(scenario)
    assert borrowed == [1]
    assert outcomes.count("ok") == 1 and peak[0] == 1
    busy = [o for o in outcomes if o != "ok"]
    assert len(busy) == 3 and all("busy" in b and "Nothing was read" in b for b in busy)
    # The slot came back exactly once: the next call takes it at once, and a
    # busy answer released nothing it never held (a bounded semaphore would
    # have raised).
    assert mcp_server._heavy_slots.acquire(blocking=False)
    mcp_server._heavy_slots.release()


def test_database_connections_are_capped_and_always_given_back(monkeypatch):
    """2026-10-30: nothing bounded how many connections were open, and a burst
    met Cloud SQL's limit ("remaining connection slots are reserved"). Past the
    cap a caller waits for one to close; a failed connect, a with-block and a
    dropped connection all give their place back."""
    import gc
    import pytest
    from alphadesk.ledger import db

    class Raw:
        closed = 0

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            Raw.closed += 1

    monkeypatch.setattr(db, "_open", threading.BoundedSemaphore(2))
    monkeypatch.setattr(db, "CONNECT_WAIT_S", 0.2)
    monkeypatch.setattr(db, "_raw_connect", Raw)
    a, b = db._pg_connect(), db._pg_connect()
    with pytest.raises(db.ConnectionsBusy):
        db._pg_connect()
    with a:
        pass                                      # a with-block closes and gives back
    c = db._pg_connect()
    del b, c
    gc.collect()                                  # dropped without a with-block: given back
    d, e = db._pg_connect(), db._pg_connect()
    with d, e:
        pass

    def refused():
        raise ConnectionError("refused")
    monkeypatch.setattr(db, "_raw_connect", refused)
    for _ in range(3):                            # a failed connect never keeps a place
        with pytest.raises(ConnectionError):
            db._pg_connect()
    assert Raw.closed == 5
