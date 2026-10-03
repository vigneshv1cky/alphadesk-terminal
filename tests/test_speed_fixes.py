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
