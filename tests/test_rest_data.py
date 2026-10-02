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
