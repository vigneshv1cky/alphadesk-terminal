"""The REST door over the agent tools (2026-10-02): one generic GET route per
tool, behind the same gate as the MCP door. Read-only by construction."""
from types import SimpleNamespace

import pytest

from alphadesk.app import rest_data


def tool(name, props, fn, required=()):
    return SimpleNamespace(
        name=name, description=f"{name} " * 12, fn=fn, is_async=False,
        parameters={"type": "object", "properties": props, "required": list(required)})


class TestCall:
    def test_query_text_becomes_the_types_the_tool_declares(self):
        seen = {}

        def fn(symbol, days=2, strict=False, ratio=1.0):
            seen.update(symbol=symbol, days=days, strict=strict, ratio=ratio)
            return {"ok": True}

        t = tool("t", {"symbol": {"type": "string"}, "days": {"type": "integer"},
                       "strict": {"type": "boolean"}, "ratio": {"type": "number"}}, fn, ["symbol"])
        assert rest_data.call(t, {"symbol": "AAPL", "days": "5", "strict": "true", "ratio": "0.5"}) == {"ok": True}
        assert seen == {"symbol": "AAPL", "days": 5, "strict": True, "ratio": 0.5}

    def test_a_list_or_text_parameter_takes_comma_separated_names(self):
        got = []
        t = tool("quotes", {"symbols": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]}},
                 lambda symbols: got.append(symbols) or {}, ["symbols"])
        rest_data.call(t, {"symbols": "AAPL, MSFT,,NVDA"})
        assert got == [["AAPL", "MSFT", "NVDA"]]

    def test_unknown_missing_and_mistyped_parameters_are_refused_by_name(self):
        t = tool("t", {"days": {"type": "integer"}, "symbol": {"type": "string"}}, lambda **k: {}, ["symbol"])
        with pytest.raises(rest_data.BadRequest, match="unknown parameter: nope"):
            rest_data.call(t, {"symbol": "A", "nope": "1"})
        with pytest.raises(rest_data.BadRequest, match="missing parameter: symbol"):
            rest_data.call(t, {"days": "3"})
        with pytest.raises(rest_data.BadRequest, match="days must be a integer"):
            rest_data.call(t, {"symbol": "A", "days": "three"})


from fastapi.testclient import TestClient

from alphadesk.providers.base import NeedsKey, ProviderError


def _client(*tools):
    return TestClient(rest_data.build(list(tools)))


class TestApp:
    def test_a_tool_is_a_get_endpoint_with_a_validator_and_an_as_of_time(self):
        c = _client(tool("data_sources", {}, lambda: {"sources": [1, 2]}))
        r = c.get("/data_sources")
        assert r.status_code == 200 and r.json() == {"sources": [1, 2]}
        assert r.headers["etag"].startswith('"') and r.headers["x-alphadesk-as-of"].endswith("+00:00")
        again = c.get("/data_sources", headers={"If-None-Match": r.headers["etag"]})
        assert again.status_code == 304 and again.content == b""

    def test_every_refusal_has_its_own_status(self):
        def needs(): raise NeedsKey("chart")
        def refuses(): raise ValueError("no daily bars for ZZZ")
        def vendor_down(): raise ProviderError("polygon is unreachable")
        c = _client(tool("needs", {}, needs), tool("refuses", {}, refuses), tool("down", {}, vendor_down),
                    tool("q", {"n": {"type": "integer"}}, lambda n: {}, ["n"]))
        assert c.get("/needs").status_code == 428 and "needs_key" in c.get("/needs").json()["detail"]
        assert c.get("/refuses").status_code == 422 and "ZZZ" in c.get("/refuses").json()["detail"]
        assert c.get("/down").status_code == 502
        assert c.get("/q?n=x").status_code == 422 and c.get("/q").status_code == 422
        assert c.get("/nothing").status_code == 404

    def test_nothing_but_get_is_accepted(self):
        c = _client(tool("data_sources", {}, lambda: {}))
        for method in ("post", "put", "patch", "delete"):
            assert getattr(c, method)("/data_sources").status_code == 405

    def test_the_spec_describes_every_endpoint_and_its_inputs(self):
        c = _client(tool("quote", {"symbol": {"type": "string"}}, lambda symbol: {}, ["symbol"]))
        spec = c.get("/openapi.json").json()
        op = spec["paths"]["/quote"]["get"]
        assert op["operationId"] == "quote" and op["parameters"][0] == {
            "name": "symbol", "in": "query", "required": True, "schema": {"type": "string"}}
        assert spec["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"


@pytest.fixture()
def rest(store, monkeypatch):
    """The real app with a token-bearing client for the local reader."""
    from alphadesk.app import agent_access, dashboard
    store.ensure_local_user()
    uid = dashboard._local_uid()
    monkeypatch.setattr(agent_access, "limiter", agent_access.RateLimit())
    _, token = agent_access.issue(uid, "bot")
    with TestClient(dashboard.app) as c:
        c.uid, c.token = uid, token
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


class TestMounted:
    def test_no_token_is_a_401_and_a_token_is_a_200(self, rest):
        assert rest.get("/api/v1/data_sources", headers={"Authorization": ""}).status_code == 401
        r = rest.get("/api/v1/data_sources")
        assert r.status_code == 200 and "x-ratelimit-remaining" in r.headers and "etag" in r.headers

    def test_the_page_login_gate_leaves_this_door_to_its_token(self):
        from alphadesk.app.auth import is_gated
        assert not is_gated("/api/v1/quote") and is_gated("/api/keys")

    def test_a_read_here_is_never_noted_for_prewarm(self, rest, monkeypatch):
        """Prewarm replays a page's reads without credentials; a replayed API
        read would only be refused. This door is not a page."""
        from alphadesk import prewarm
        noted = []
        monkeypatch.setattr(prewarm, "note", lambda *a, **k: noted.append(a))
        assert rest.get("/api/v1/data_sources").status_code == 200
        assert noted == []


class TestGuards:
    def test_every_data_tool_has_exactly_one_endpoint(self):
        from alphadesk.mcp_server import mcp
        built = rest_data.build()
        assert set(built.state.tools) == {t.name for t in mcp._tool_manager.list_tools()}

    def test_no_route_on_this_door_accepts_anything_but_get(self):
        from fastapi.routing import APIRoute
        for route in rest_data.build().routes:
            if isinstance(route, APIRoute):
                assert route.methods <= {"GET", "HEAD"}, route.path

    def test_a_write_verb_is_refused_on_the_mounted_door(self, rest):
        for method in ("post", "put", "patch", "delete"):
            assert getattr(rest, method)("/api/v1/data_sources").status_code == 405

    def test_two_readers_never_see_each_other(self, rest, store, monkeypatch):
        from alphadesk.app import agent_access
        from alphadesk.identity import request_user
        from alphadesk.mcp_server import mcp
        store.create_user("u2", "other@example.com", "sso-only")
        _, other = agent_access.issue("u2", "bot")
        monkeypatch.setattr(mcp._tool_manager.get_tool("data_sources"), "fn", lambda: {"who": request_user()})
        mine = rest.get("/api/v1/data_sources").json()["who"]
        theirs = rest.get("/api/v1/data_sources", headers={"Authorization": f"Bearer {other}"}).json()["who"]
        assert (mine, theirs) == (rest.uid, "u2")

    def test_a_revoked_token_stops_at_once(self, rest, store):
        row = store.list_agent_access_tokens(rest.uid)[0]
        assert store.revoke_agent_access_token(rest.uid, row["token_id"])
        assert rest.get("/api/v1/data_sources").status_code == 401

    def test_the_limit_ends_in_a_429_with_a_retry_time(self, rest, monkeypatch):
        from alphadesk.app import agent_access
        monkeypatch.setattr(agent_access, "limiter", agent_access.RateLimit(per_min=2))
        assert [rest.get("/api/v1/data_sources").status_code for _ in range(2)] == [200, 200]
        r = rest.get("/api/v1/data_sources")
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


class TestBars:
    """Every bar, not the agent tools' thinned sample. The endpoint reuses the
    chart route (dashboard.api_chart), so vendor choice, interval resolution
    and the history floor are the chart's own."""

    def _series(self):
        return {"vendor": "alpaca", "bars": [
            {"t": "2026-09-01T13:30:00+00:00", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "rsi_9": 55.0},
            {"t": "2026-09-02T13:30:00+00:00", "o": 1.5, "h": 2.5, "l": 1, "c": 2, "v": 200, "rsi_9": 60.0}],
            "indicators_reliable": True, "coverage": 1.0}

    def test_bars_come_back_whole_without_indicators_and_with_a_cursor(self, rest, monkeypatch):
        from alphadesk.app import dashboard
        calls = []
        monkeypatch.setattr(dashboard, "api_chart", lambda *a, **k: calls.append((a, k)) or self._series())
        r = rest.get("/api/v1/bars/aapl?interval=1d&range=MAX&before=2026-09-03T00:00:00Z")
        body = r.json()
        assert r.status_code == 200 and body["symbol"] == "AAPL" and body["vendor"] == "alpaca"
        assert body["bars"][0] == {"t": "2026-09-01T13:30:00+00:00", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}
        assert [b["t"][:10] for b in body["bars"]] == ["2026-09-01", "2026-09-02"]    # oldest first, nothing dropped
        assert body["count"] == 2 and body["next_before"] == "2026-09-01T13:30:00+00:00"
        assert calls[0][1]["interval"] == "1d" and calls[0][1]["before"] == "2026-09-03T00:00:00Z"
        assert "etag" in r.headers and "x-alphadesk-as-of" in r.headers

    def test_the_end_of_history_is_a_clean_empty_page_not_an_error(self, rest, monkeypatch):
        """The chart route answers 404 once a walk has gone past the oldest bar.
        A bot walking back would meet that error at the end of every walk."""
        from fastapi import HTTPException
        from alphadesk.app import dashboard

        def end(*a, **k): raise HTTPException(404, "daily bars reach back to 1999")
        monkeypatch.setattr(dashboard, "api_chart", end)
        r = rest.get("/api/v1/bars/AAPL?interval=1d&before=1999-01-01T00:00:00Z")
        assert r.status_code == 200
        assert r.json() == {"symbol": "AAPL", "interval": "1d", "vendor": None, "bars": [], "count": 0,
                            "next_before": None, "note": "daily bars reach back to 1999"}

    def test_a_404_on_the_first_page_is_still_a_404(self, rest, monkeypatch):
        """No cursor means no walk: nothing for the symbol is a real not-found."""
        from fastapi import HTTPException
        from alphadesk.app import dashboard

        def none(*a, **k): raise HTTPException(404, "no bars for ZZZZ")
        monkeypatch.setattr(dashboard, "api_chart", none)
        assert rest.get("/api/v1/bars/ZZZZ?interval=1d").status_code == 404

    def test_the_charts_own_refusals_pass_through_with_their_headers(self, rest, monkeypatch):
        from fastapi import HTTPException
        from alphadesk.app import dashboard

        def slow(*a, **k): raise HTTPException(503, "alpaca: rate limited", headers={"Retry-After": "15"})
        monkeypatch.setattr(dashboard, "api_chart", slow)
        r = rest.get("/api/v1/bars/AAPL?interval=1d")
        assert r.status_code == 503 and r.headers["retry-after"] == "15" and "rate limited" in r.json()["detail"]

        def bad(*a, **k): raise HTTPException(400, "interval must be one of 1m, 1d on alpaca")
        monkeypatch.setattr(dashboard, "api_chart", bad)
        r = rest.get("/api/v1/bars/AAPL?interval=7m")
        assert r.status_code == 400 and "interval must be one of" in r.json()["detail"]

    def test_the_spec_lists_the_bars_endpoint_with_its_path_and_query_inputs(self):
        spec = TestClient(rest_data.build([])).get("/openapi.json").json()
        op = spec["paths"]["/bars/{symbol}"]["get"]
        assert op["operationId"] == "bars"
        by_name = {p["name"]: p for p in op["parameters"]}
        assert by_name["symbol"]["in"] == "path" and by_name["symbol"]["required"] is True
        assert {"interval", "range", "before", "need"} <= set(by_name)
        assert all(by_name[n]["in"] == "query" and by_name[n]["required"] is False
                   for n in ("interval", "range", "before", "need"))
