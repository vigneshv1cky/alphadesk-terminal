"""The agent's tools, served as a reader (2026-09-17).

The tool server used to have no reader identity, so an agent pointed at it
could only reach EDGAR and the Treasury curve. It now sits inside the app
behind a token the reader authorised, and a call runs as that reader. These
tests hold the things that must never slip: no call reaches a tool without a
live token, and a call with one really does run as that reader — the part a
background task could silently lose.
"""

import base64
import json
import os

import pytest

MASTER = base64.b64encode(b"k" * 32).decode()


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", MASTER)


# ── credentials ───────────────────────────────────────────────────────────


def _token_for(store, uid):
    """A reader-issued access token for `uid`, creating the account if needed."""
    from alphadesk.app import agent_access
    if store.get_user_by_email(f"{uid}@example.com") is None:
        store.create_user(uid, f"{uid}@example.com", "x")
    return agent_access.issue(uid, "test")[1]


def test_bearer_reads_only_a_bearer_header():
    from alphadesk.app.agent_access import bearer
    assert bearer("Bearer abc.def") == "abc.def"
    assert bearer("bearer   abc.def ") == "abc.def"
    assert bearer("Basic xyz") is None
    assert bearer(None) is None
    assert bearer("Bearer ") is None


# ── the gate, end to end ──────────────────────────────────────────────────


def _mcp(client, token=None, method="tools/list", params=None, host="127.0.0.1:8000"):
    headers = {"content-type": "application/json",
               "accept": "application/json, text/event-stream",
               "host": host}
    if token:
        headers["authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/api/agent/tools/mcp", headers=headers, content=json.dumps(body))


def _payload(resp):
    """A streamable-HTTP reply is JSON or a single server-sent event."""
    text = resp.text
    if text.lstrip().startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise AssertionError(f"no JSON-RPC payload in: {text[:200]}")


@pytest.fixture()
def tools_client(store):
    from fastapi.testclient import TestClient

    from alphadesk.app import dashboard
    with TestClient(dashboard.app) as c:
        yield c


def test_no_token_never_reaches_a_tool(tools_client):
    resp = _mcp(tools_client)
    assert resp.status_code == 401
    assert "bearer" in resp.headers.get("www-authenticate", "").lower()


def test_a_bad_token_never_reaches_a_tool(tools_client):
    assert _mcp(tools_client, token="not.a-token").status_code == 401
    assert _mcp(tools_client, token="adk_" + "x" * 43).status_code == 401
    assert _mcp(tools_client, token="ado_" + "x" * 43).status_code == 401


def test_a_valid_token_lists_the_terminals_tools(tools_client, store):
    resp = _mcp(tools_client, token=_token_for(store, "user-42"))
    assert resp.status_code == 200, resp.text[:300]
    names = {tool["name"] for tool in _payload(resp)["result"]["tools"]}
    # The terminal's own tools, as this reader.
    assert {"quote", "market_today", "symbol_news", "filing_text"} <= names


def test_a_tool_call_runs_as_the_reader_the_token_names(tools_client, monkeypatch, store):
    """The failure this guards against is silent: the MCP library runs a tool
    in a task of its own, and an identity set on the request can be lost on
    the way there — the tool would then run as nobody, on no keys, and
    answer from public data as if that were all there is."""
    from alphadesk import mcp_server
    from alphadesk.identity import request_user

    seen = {}

    def fake_tape():
        seen["user"] = request_user()
        return [{"symbol": "SPY"}]

    class FakeRouter:
        def ask(self, name, *a, **k):
            return fake_tape()

    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: FakeRouter())
    resp = _mcp(tools_client, token=_token_for(store, "reader-7"), method="tools/call",
                params={"name": "index_board", "arguments": {}})
    assert resp.status_code == 200, resp.text[:300]
    assert seen.get("user") == "reader-7"
    assert mcp_server is not None


def test_two_readers_calls_never_share_an_identity(tools_client, monkeypatch, store):
    from alphadesk.identity import request_user

    seen = []

    class FakeRouter:
        def ask(self, name, *a, **k):
            seen.append(request_user())
            return []

    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: FakeRouter())
    tokens = {uid: _token_for(store, uid) for uid in ("alice", "bob")}
    for uid in ("alice", "bob", "alice"):
        _mcp(tools_client, token=tokens[uid], method="tools/call",
             params={"name": "index_board", "arguments": {}})
    assert seen == ["alice", "bob", "alice"]
    # And nothing is left behind on the request that follows without a token.
    assert _mcp(tools_client).status_code == 401


def test_the_tool_server_does_not_answer_a_public_hostname(tools_client, store):
    """Only loopback and the instance's own public address are answered; a
    request naming any other host is refused, token or no token."""
    resp = _mcp(tools_client, token=_token_for(store, "user-42"), host="alphadesk.example.com")
    assert resp.status_code in (400, 403, 421)


def test_the_page_login_gate_leaves_the_tool_server_to_its_own_credential():
    from alphadesk.app.auth import is_gated
    assert not is_gated("/api/agent/tools/mcp")
    assert is_gated("/api/agent/modes")          # everything else stays gated
    assert os.environ.get("ALPHADESK_VAULT_KEY") == MASTER


# ── access tokens a reader issues for their own agent ─────────────────────


@pytest.fixture()
def reader_client(store, monkeypatch):
    """The app with every keys-page call acting for one signed-in reader."""
    from fastapi.testclient import TestClient

    from alphadesk.app import agent_access, dashboard
    store.ensure_local_user()
    uid = dashboard._local_uid()
    monkeypatch.setattr(dashboard, "_key_user", lambda request: uid)
    monkeypatch.setattr(agent_access, "limiter", agent_access.RateLimit())
    with TestClient(dashboard.app) as c:
        c.uid = uid
        yield c


def test_an_issued_token_is_shown_once_and_stored_only_as_a_hash(reader_client, store):
    resp = reader_client.post("/api/agent/access-tokens", json={"name": "Claude Code"})
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    token = body["token"]
    assert token.startswith("adk_") and len(token) > 40
    assert body["url"].endswith("/api/agent/tools/mcp")
    listed = reader_client.get("/api/agent/access-tokens").json()["tokens"]
    assert [t["name"] for t in listed] == ["Claude Code"]
    assert listed[0]["hint"] == token[-4:]
    assert "token" not in listed[0] and "token_hash" not in listed[0]
    with store._connect() as conn:
        dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM agent_access_tokens")])
    assert token not in dump


def test_an_issued_token_runs_tool_calls_as_its_reader(reader_client, monkeypatch, store):
    from alphadesk.identity import request_user
    seen = []

    class FakeRouter:
        def ask(self, name, *a, **k):
            seen.append(request_user())
            return []

    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: FakeRouter())
    token = reader_client.post("/api/agent/access-tokens", json={"name": "a"}).json()["token"]
    resp = _mcp(reader_client, token=token, method="tools/call",
                params={"name": "index_board", "arguments": {}})
    assert resp.status_code == 200, resp.text[:300]
    assert seen == [reader_client.uid]
    listed = reader_client.get("/api/agent/access-tokens").json()["tokens"]
    assert listed[0]["last_used_at"]


def test_a_revoked_token_stops_at_once(reader_client):
    body = reader_client.post("/api/agent/access-tokens", json={"name": "a"}).json()
    assert _mcp(reader_client, token=body["token"]).status_code == 200
    assert reader_client.delete(f"/api/agent/access-tokens/{body['token_id']}").status_code == 200
    assert _mcp(reader_client, token=body["token"]).status_code == 401
    assert reader_client.get("/api/agent/access-tokens").json()["tokens"] == []
    assert reader_client.delete(f"/api/agent/access-tokens/{body['token_id']}").status_code == 404


def test_a_made_up_access_token_is_refused(reader_client):
    assert _mcp(reader_client, token="adk_" + "x" * 43).status_code == 401


def test_a_reader_cannot_revoke_someone_elses_token(reader_client, store):
    from alphadesk.app import agent_access
    body = reader_client.post("/api/agent/access-tokens", json={"name": "a"}).json()
    assert store.revoke_agent_access_token("someone-else", body["token_id"]) is False
    assert agent_access.resolve(body["token"])[1] == reader_client.uid


def test_live_tokens_are_capped_per_reader(reader_client):
    from alphadesk.app import agent_access
    for i in range(agent_access.MAX_TOKENS):
        assert reader_client.post("/api/agent/access-tokens", json={"name": f"t{i}"}).status_code == 200
    assert reader_client.post("/api/agent/access-tokens", json={"name": "one more"}).status_code == 422


def test_a_looping_agent_is_slowed_down(reader_client, monkeypatch):
    from alphadesk.app import agent_access
    monkeypatch.setattr(agent_access, "limiter", agent_access.RateLimit(per_min=3))
    token = reader_client.post("/api/agent/access-tokens", json={"name": "a"}).json()["token"]
    codes = [_mcp(reader_client, token=token).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    last = _mcp(reader_client, token=token)
    assert last.status_code == 429 and int(last.headers["retry-after"]) >= 1


def test_the_rate_window_slides():
    from alphadesk.app.agent_access import RateLimit
    rl = RateLimit(per_min=2)
    assert rl.check("k", now=0) == 0 and rl.check("k", now=1) == 0
    assert rl.check("k", now=30) > 0
    assert rl.check("other", now=30) == 0
    assert rl.check("k", now=60.5) == 0


def test_the_public_address_is_answered_and_nothing_else(store, monkeypatch):
    from fastapi.testclient import TestClient

    from alphadesk.app import dashboard
    monkeypatch.setenv("ALPHADESK_BASE_URL", "https://alphadesk.example.com")
    with TestClient(dashboard.app) as c:
        tok = _token_for(store, "user-42")
        assert _mcp(c, token=tok, host="alphadesk.example.com").status_code == 200
        assert _mcp(c, token=tok, host="evil.example.net").status_code in (400, 403, 421)


def test_the_limiter_reports_how_much_of_the_window_is_left():
    from alphadesk.app.agent_access import RateLimit
    rl = RateLimit(per_min=3, window_s=60.0)
    assert rl.remaining("k", now=0.0) == 3
    rl.check("k", now=1.0)
    rl.check("k", now=2.0)
    assert rl.remaining("k", now=3.0) == 1
    assert rl.remaining("k", now=62.5) == 3        # both hits aged out of the window
    assert rl.remaining("someone-else", now=3.0) == 3


def test_a_gated_response_says_how_much_of_the_limit_is_left(reader_client):
    token = reader_client.post("/api/agent/access-tokens", json={"name": "a"}).json()["token"]
    r = _mcp(reader_client, token=token)
    assert r.status_code == 200
    assert r.headers["x-ratelimit-limit"] == "120" and r.headers["x-ratelimit-window"] == "60"
    assert r.headers["x-ratelimit-remaining"] == "119"        # this call is counted
    assert _mcp(reader_client, token=token).headers["x-ratelimit-remaining"] == "118"


# ── what agents ask and how it went (2026-10-03) ────────────────────────────


def test_a_tool_call_is_filed_with_its_task_and_how_it_ended(tools_client, monkeypatch, store):
    from alphadesk.ledger import store as ledger

    class FakeRouter:
        def ask(self, name, *a, **k):
            return [{"symbol": "SPY"}]
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: FakeRouter())
    token = _token_for(store, "reader-9")
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream",
               "host": "127.0.0.1:8000", "authorization": f"Bearer {token}",
               "x-agent-task": "task-77", "x-agent-intent": "why did GRML move on Sep 21"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "index_board", "arguments": {}}}
    resp = tools_client.post("/api/agent/tools/mcp", headers=headers, content=json.dumps(body))
    assert resp.status_code == 200, resp.text[:300]
    rows = [r for r in ledger.agent_calls_since("2000-01-01") if r["tool"] == "index_board"]
    assert len(rows) == 1
    row = rows[0]
    assert row["task_id"] == "task-77" and row["intent"] == "why did GRML move on Sep 21"
    assert row["outcome"] == "answered" and row["user_id"] == "reader-9" and row["ms"] is not None
    assert row["token_id"] and token not in json.dumps(row)                 # a token never reaches the log


def test_a_caller_can_say_a_result_was_useful_or_what_it_was_missing(tools_client, store):
    from alphadesk.ledger import store as ledger
    token = _token_for(store, "reader-10")
    url = "/api/agent/tools/feedback"
    base = {"host": "127.0.0.1:8000", "content-type": "application/json"}
    assert tools_client.post(url, headers=base, content="{}").status_code == 401              # no token, no feedback
    auth = {**base, "authorization": f"Bearer {token}", "x-agent-task": "t1"}
    ok = tools_client.post(url, headers=auth, content=json.dumps(
        {"tool": "what_moved", "useful": "no", "note": "no story for the big day", "missing": "social post for that morning"}))
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    assert tools_client.post(url, headers=auth, content=json.dumps({"useful": "maybe"})).status_code == 400
    assert tools_client.post(url, headers=auth, content="not json").status_code == 400
    assert tools_client.post(url, headers={**auth, "host": "evil.example"}, content=json.dumps({"useful": "yes"})).status_code != 200
    got = ledger.agent_feedback_since("2000-01-01")
    assert len(got) == 1 and got[0]["tool"] == "what_moved" and got[0]["rating"] == -1
    assert got[0]["task_id"] == "t1" and got[0]["missing"] == "social post for that morning"


def test_outcomes_are_told_apart():
    from alphadesk import agent_log as al
    from alphadesk.providers.base import NeedsKey
    assert al.classify({"rows": [1]}, None) == ("answered", None)
    assert al.classify({"rows": []}, None) == ("empty", None)
    assert al.classify([], None) == ("empty", None)
    assert al.classify({"count": 0, "candidates": []}, None) == ("empty", None)
    assert al.classify({"rows": [1], "unavailable": {"news": "no feed"}}, None) == ("incomplete", None)
    assert al.classify({"reliable": False}, None) == ("incomplete", None)
    assert al.classify(None, NeedsKey("analyst_ratings", [], connected=["finnhub"])) == ("error", "no_coverage")
    assert al.classify(None, NeedsKey("analyst_ratings", ["finnhub"], connected=["finnhub"])) == ("error", "plan_limit")
    assert al.classify(None, NeedsKey("analyst_ratings")) == ("error", "no_key")
    assert al.classify(None, ValueError("no daily bars for XYZ")) == ("error", "no_data")
    assert al.classify(None, ValueError("range must be one of 1M")) == ("error", "rejected")


def test_the_report_groups_calls_into_tasks_and_finds_what_to_fix():
    from alphadesk import agent_log as al

    def call(sec, tool, outcome="answered", ms=100, task=None, token="t", kind=None):
        return {"id": f"{sec}{tool}", "at": f"2026-10-03T12:{sec // 60:02d}:{sec % 60:02d}+00:00", "token_id": token, "user_id": "u",
                "task_id": task, "intent": None, "tool": tool, "args": "{}", "ms": ms, "outcome": outcome,
                "error_kind": kind, "bytes": 500}
    rows = [call(0, "news_search"), call(5, "news_story"), call(9, "list_filings"),          # one task: gaps under a minute
            call(300, "news_search"), call(304, "news_story"), call(309, "list_filings"),      # another, the same chain
            call(400, "analyst_view", "error", kind="no_coverage"), call(401, "analyst_view", "error", kind="no_coverage"),
            call(402, "analyst_view", "error", kind="no_coverage"), call(500, "price_chart", ms=9000)]
    rep = al.summarize(rows, known_tools=["news_search", "news_story", "list_filings", "analyst_view", "price_chart", "peers"],
                       feedback=[{"at": "2026-10-03T12:09:00+00:00", "tool": "news_search", "rating": -1, "note": "thin",
                                  "missing": "second news feed"}])
    assert rep["calls"] == 10 and rep["tasks"] == 4
    assert rep["never_called"] == ["peers"]
    assert rep["worst"] == ["analyst_view"]
    assert rep["slowest"] == ["price_chart"]
    assert rep["repeated_chains"] == [{"chain": "news_search → news_story → list_filings", "times": 2}]
    tool = {t["tool"]: t for t in rep["tools"]}
    assert tool["analyst_view"]["error_kinds"] == {"no_coverage": 3}
    assert tool["news_search"]["feedback"] == {"n": 1, "useful": 0, "partly": 0, "not_useful": 1}
    assert rep["feedback"]["not_useful_tools"] == ["news_search"] and rep["feedback"]["missing"][0]["missing"] == "second news feed"
    given = al.assign_tasks([call(0, "a", task="x"), call(500, "b", task="x")])
    assert given[0]["task"] == given[1]["task"]                                                 # a task id beats the time gap
