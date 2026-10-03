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
