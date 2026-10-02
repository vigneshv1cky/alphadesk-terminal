# Plan: a read-only REST data API for bots and trading agents

**Goal**: A program on another server reads AlphaDesk's data over plain HTTP with a reader-issued token, on the reader's own vendor keys — including every bar of history — without AlphaDesk gaining any write surface.

**Architecture**: A second front door beside the MCP tool server, under `/api/v1`. One generic GET route looks a tool up by name in the same tool registry the agent door serves, converts the query string to the types the tool declares, and calls the tool's own function. The existing `TokenGate` (token → reader → billing → rate limit) wraps it, so there is one gate to secure. Full-resolution bars are one extra endpoint that reuses the chart route's logic. An optional per-token address allowlist is added to the gate. Design: `docs/plans/2026-10-02-rest-data-api-design.md`.

**Tech Stack**: Python 3.11+, FastAPI/Starlette (a mounted sub-app), the `mcp` 1.30 FastMCP tool registry, SQLite/Postgres store, pytest. Frontend (one small step): React 19 + TypeScript + Vite.

## Status (2026-10-02)

Steps 1–11 are built and committed on branch `claude/dazzling-volta-lj4kmt`; Step 12 (merge, deploy, live check) waits for the owner. What the build found that this plan got wrong, corrected below and recorded here:

- **Step 3**: FastAPI cannot resolve a handler's `Request` annotation from an import local to `build()` when the module uses `from __future__ import annotations` — every call answered 422. The imports are at module level in the real code.
- **Step 7**: the chart route answers **404, not an empty list**, once a walk has gone past the oldest bar. The endpoint turns a 404 *with a cursor* into an empty final page carrying a `note`; without a cursor a 404 stays a 404. The chart's 503 with `Retry-After` is passed through with its header.
- **Step 11**: `quote` with no vendor key answers **422 "no quote available"**, not 428 — the tool absorbs the missing-key case itself (the agent door does the same). `bars` does answer 428. Giving the tools a distinct "no vendor key" error is a follow-up.
- **Step 12, live (2026-10-02, revision `alphadesk-00469-zgj`, commit `79d8d10`)**: verified on the hosted service with real tokens and the owner's own vendor key. The allowlist holds on Cloud Run — a token tied to another address is refused (403), the same token with a forged `X-Forwarded-For` is still refused (403), and a token tied to the caller's real address is accepted (200), so the last forwarded entry is the real client as assumed. `quote` returned a real-time consolidated AAPL price; `bars` returned 2,703 daily bars (2016-01-04 to 2026-10-02) oldest first with no duplicates, and the end-of-history empty page with its note arrived as designed. One first-run miss was a test mistake, not a fault: the first fake-address token was created without an address, which the Account page shows as "from any address".
- Tests that pass on first run (Step 6, and the "404 on the first page" test) were checked by temporarily breaking the code they guard; each failed as intended.

## Ground rules for every step

- **Read-only is the product.** No route accepts anything but GET. No tool or endpoint name may suggest a write (`tests/test_mcp.py` already guards the tools; Step 6 guards this door).
- **Every call runs as exactly one reader**, set by `TokenGate` from the token. Nothing is cached across readers.
- **Test first, and watch it fail for the right reason** before writing code.
- Run tests with: `ALPHADESK_SEMANTIC_SEARCH=off .venv/bin/python -m pytest <path> -q -p no:cacheprovider` from the repo root.
- Commit each step with the owner as author and the assistant as co-author (otherwise the CLA check goes red):
  `git commit --author="Vignesh Murugan <97196163+vigneshv1cky@users.noreply.github.com>" -m "<title>" -m "<why>" -m "Co-authored-by: Claude Sonnet 5.5 <noreply@anthropic.com>"`
- Add files by name. **Never `git add .` or `-A` outside `alphadesk/app/static`** — an untracked `.local-data/` holds the local vault key.
- Pushing or merging to `main`, and deploying, wait for the owner's go-ahead (Step 12).

## Facts the plan relies on (verified 2026-10-02)

- All 50 agent tools are plain **synchronous** functions registered with `@mcp.tool` in `alphadesk/mcp_server.py`. `mcp._tool_manager.list_tools()` returns objects with `.name`, `.description`, `.parameters` (a JSON schema with `properties` and `required`), `.fn`, `.is_async`, `.annotations`.
- Parameter schemas use only `string`, `integer`, `number`, `boolean`, and one union: `anyOf [array of string, string]` (for `quotes`' `symbols`).
- Tools signal bad input with `ValueError`; `NeedsKey` (`alphadesk/providers/base.py`, constructor `NeedsKey(surface, refused=None, signed_in=True, connected=None, failed=None)`, `.prompt()`) propagates for a surface no connected vendor carries; the web app maps it to HTTP 428 with `{"detail": {"needs_key": prompt}}`.
- `TokenGate` in `alphadesk/app/agent_tools.py` verifies `adk_` tokens (`agent_access.resolve`) and OAuth tokens (`agent_oauth.resolve_access`), applies `billing.blocked_user` (402) and `agent_access.limiter` (429), then sets the reader with `identity.set_request_user`.
- The page sign-in gate `is_gated` (`alphadesk/app/auth.py:558`) exempts `/api/agent/tools`; the prewarm middleware in `alphadesk/app/dashboard.py` (`_note_for_prewarm`) records every successful GET under `/api/`.
- `dashboard.api_chart(symbol, days, range, interval, before, source, need)` returns the chart series (`bars` with `t,o,h,l,c,v`, plus indicators and quality fields) and raises `HTTPException` 400 for a bad range or interval.
- Existing token endpoints: `GET/POST /api/agent/access-tokens`, `DELETE /api/agent/access-tokens/{token_id}` (`dashboard.py:607-628`); UI in `alphadesk/ui/src/pages/AccountPage.tsx` (~line 713) and `alphadesk/ui/src/lib/api.ts` (~line 1503).

---

## Step 1: Turn query strings into a tool call

**Files**: create `alphadesk/app/rest_data.py`, create `tests/test_rest_data.py`

### 1a. Write failing test
```python
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
```

### 1b. Run test to verify it fails
`ALPHADESK_SEMANTIC_SEARCH=off .venv/bin/python -m pytest tests/test_rest_data.py -q -p no:cacheprovider` → fails: `ImportError: cannot import name 'rest_data'` (the module is missing — the right reason).

### 1c. Write implementation
```python
"""AlphaDesk's data over plain HTTP (2026-10-02).

The agent tools, served as GET endpoints for programs that are not agents: a
trading bot, an importer, a script. One generic route looks a tool up by name
in the same registry the MCP door serves and calls the tool's own function, so
the two doors cannot drift and neither can write — every tool is a read.
Mounted behind the same TokenGate as the MCP door (app/agent_tools.py).
"""

from __future__ import annotations

PREFIX = "/api/v1"


class BadRequest(ValueError):
    """The query string does not fit the tool's declared inputs."""


_TRUE, _FALSE = {"1", "true", "yes"}, {"0", "false", "no"}


def _coerce(name: str, schema: dict, raw: str):
    kinds = {s.get("type") for s in schema.get("anyOf", [schema])}
    kind = "list" if "array" in kinds else schema.get("type")
    try:
        if kind == "list":
            return [p.strip() for p in raw.split(",") if p.strip()]
        if kind == "integer":
            return int(raw)
        if kind == "number":
            return float(raw)
        if kind == "boolean":
            if raw.lower() in _TRUE:
                return True
            if raw.lower() in _FALSE:
                return False
            raise ValueError
    except ValueError:
        raise BadRequest(f"{name} must be a {kind}") from None
    return raw


def call(tool, query: dict):
    """Run one tool with query-string text for its inputs."""
    props = tool.parameters.get("properties", {})
    unknown = sorted(set(query) - set(props))
    if unknown:
        raise BadRequest(f"unknown parameter: {', '.join(unknown)}")
    missing = [n for n in tool.parameters.get("required", []) if n not in query]
    if missing:
        raise BadRequest(f"missing parameter: {', '.join(missing)}")
    return tool.fn(**{n: _coerce(n, props[n], v) for n, v in query.items()})
```

### 1d. Run test to verify it passes
Same command as 1b → 3 passed.

### 1e. Commit
Files: `alphadesk/app/rest_data.py tests/test_rest_data.py`. Title: `rest: call an agent tool from query-string text`.

---

## Step 2: Say how much of the limit is left

**Files**: modify `alphadesk/app/agent_access.py`, `tests/test_agent_tools.py`

### 2a. Write failing test (append to `tests/test_agent_tools.py`)
```python
def test_the_limiter_reports_how_much_of_the_window_is_left():
    from alphadesk.app.agent_access import RateLimit
    rl = RateLimit(per_min=3, window_s=60.0)
    assert rl.remaining("k", now=0.0) == 3
    rl.check("k", now=1.0)
    rl.check("k", now=2.0)
    assert rl.remaining("k", now=3.0) == 1
    assert rl.remaining("k", now=62.5) == 3        # both hits aged out of the window
    assert rl.remaining("someone-else", now=3.0) == 3
```

### 2b. Run: `... pytest tests/test_agent_tools.py -q -p no:cacheprovider -k remaining_of_the_window` → fails: `AttributeError: 'RateLimit' object has no attribute 'remaining'`.

### 2c. Implement (add to `RateLimit` in `alphadesk/app/agent_access.py`)
```python
    def remaining(self, key: str, now: float | None = None) -> int:
        """Hits this key may still make in the current window."""
        now = now if now is not None else time.monotonic()
        with self._lock:
            live = sum(1 for h in self._hits.get(key, ()) if now - h < self.window_s)
        return max(0, self.per_min - live)
```

### 2d. Run the same command → passes. Then run all of `tests/test_agent_tools.py` → still green.

### 2e. Commit: `rest: the rate limiter says how much of its window is left`.

---

## Step 3: The REST app — spec, errors, validators

**Files**: modify `alphadesk/app/rest_data.py`, `tests/test_rest_data.py`. **Depends on**: Step 1.

### 3a. Write failing test (append)
```python
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
```

### 3b. Run: `... pytest tests/test_rest_data.py -q -p no:cacheprovider -k TestApp` → fails: `AttributeError: module ... has no attribute 'build'`.

### 3c. Implement (add to `alphadesk/app/rest_data.py`)
```python
# Module level, with the other imports at the top of the file (see Status):
# hashlib, json, datetime/timezone, and from fastapi: FastAPI, HTTPException,
# Request, Response, jsonable_encoder, JSONResponse; and from
# alphadesk.providers.base: NeedsKey, ProviderError.


def openapi(tools) -> dict:
    """A machine-readable spec of every endpoint, from the tools' own schemas."""
    paths = {}
    for t in tools:
        props, required = t.parameters.get("properties", {}), set(t.parameters.get("required", []))
        paths[f"/{t.name}"] = {"get": {
            "operationId": t.name, "summary": (t.description or "").strip().splitlines()[0][:120],
            "description": t.description,
            "parameters": [{"name": n, "in": "query", "required": n in required,
                            "schema": {k: v for k, v in p.items() if k not in ("title", "description")}}
                           for n, p in props.items()],
            "security": [{"bearer": []}],
            "responses": {"200": {"description": "The tool's records, as JSON"},
                          "401": {"description": "No valid token"}, "402": {"description": "Trial ended"},
                          "422": {"description": "The inputs were refused, or there is no such data"},
                          "428": {"description": "No connected vendor carries this; the body names them"},
                          "429": {"description": "Rate limit; see Retry-After"},
                          "502": {"description": "A vendor failed"}}}}
    return {"openapi": "3.1.0", "servers": [{"url": PREFIX}],
            "info": {"title": "AlphaDesk data API", "version": "1",
                     "description": "Read-only. Every call runs as the reader who issued the token, on their keys."},
            "paths": paths,
            "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}}


def _reply(request, result):
    body = json.dumps(jsonable_encoder(result), separators=(",", ":")).encode()
    headers = {"ETag": '"' + hashlib.sha256(body).hexdigest()[:16] + '"',
               "X-AlphaDesk-As-Of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


def build(tools=None):
    """The sub-app to mount at PREFIX. `tools` defaults to the live agent tools."""
    if tools is None:
        from alphadesk.mcp_server import mcp
        tools = mcp._tool_manager.list_tools()
    registry = {t.name: t for t in tools}
    api = FastAPI(title="AlphaDesk data API", openapi_url=None, docs_url=None, redoc_url=None)
    api.state.tools = registry

    @api.exception_handler(NeedsKey)
    async def _needs_key(request: Request, exc: NeedsKey):
        # The same body the web app answers (dashboard._needs_key).
        return JSONResponse({"detail": {"needs_key": exc.prompt()}}, status_code=428)

    @api.get("/openapi.json")
    def spec():
        return JSONResponse(openapi(registry.values()))

    @api.get("/{name}")
    def read(name: str, request: Request):
        t = registry.get(name)
        if t is None:
            raise HTTPException(404, f"no such data endpoint: {name}")
        try:
            result = call(t, dict(request.query_params))
        except ValueError as exc:           # bad inputs, or a tool saying there is nothing to return
            raise HTTPException(422, str(exc)) from None
        except ProviderError as exc:        # NeedsKey is a ProviderError too, handled above
            if isinstance(exc, NeedsKey):
                raise
            return JSONResponse({"detail": str(exc)}, status_code=502)
        return _reply(request, result)

    return api
```

### 3d. Run the same command → 4 passed (and the 3 from Step 1).

### 3e. Commit: `rest: the generic read endpoint, its errors, validators and spec`.

---

## Step 4: Rate-limit headers on every gated response

**Files**: modify `alphadesk/app/agent_tools.py`, `tests/test_agent_tools.py`. **Depends on**: Step 2.

### 4a. Write failing test (append to `tests/test_agent_tools.py`; reuse that file's `reader_client` fixture)
```python
def test_a_gated_response_says_how_much_of_the_limit_is_left(reader_client):
    from alphadesk.app import agent_access
    _, token = agent_access.issue(reader_client.uid, "bot")
    r = reader_client.post("/api/agent/tools/mcp", headers={"Authorization": f"Bearer {token}"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.headers["x-ratelimit-limit"] == "120" and r.headers["x-ratelimit-window"] == "60"
    assert 0 <= int(r.headers["x-ratelimit-remaining"]) <= 119
```

### 4b. Run: `... pytest tests/test_agent_tools.py -q -p no:cacheprovider -k how_much_of_the_limit` → fails: `KeyError: 'x-ratelimit-limit'`.

### 4c. Implement — in `TokenGate.__call__`, replace the final `try: await self.app(scope, receive, send)` call:
```python
        remaining = agent_access.limiter.remaining(limit_key)

        async def send_with_limits(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [
                    *message.get("headers", []),
                    (b"x-ratelimit-limit", str(agent_access.limiter.per_min).encode()),
                    (b"x-ratelimit-remaining", str(remaining).encode()),
                    (b"x-ratelimit-window", str(int(agent_access.limiter.window_s)).encode())]}
            await send(message)

        held = set_request_user(uid)
        try:
            await self.app(scope, receive, send_with_limits)
        finally:
            reset_request_user(held)
```

### 4d. Run the same command → passes; run all of `tests/test_agent_tools.py tests/test_agent_oauth.py` → green.

### 4e. Commit: `rest: every gated response carries the limit, what is left and the window`.

---

## Step 5: Mount the door and keep the three other layers out of its way

**Files**: modify `alphadesk/app/dashboard.py`, `alphadesk/app/auth.py`, `tests/test_rest_data.py`. **Depends on**: Steps 3, 4.

### 5a. Write failing test (append)
```python
import uuid


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
```

### 5b. Run: `... pytest tests/test_rest_data.py -q -p no:cacheprovider -k TestMounted` → fails: 404 on `/api/v1/data_sources` (the door is not mounted) and `is_gated` returns True.

### 5c. Implement
- `alphadesk/app/auth.py`, `is_gated`: add `and not path.startswith("/api/v1")` beside the `/api/agent/tools` exemption, and extend its comment: this door carries the same token.
- `alphadesk/app/dashboard.py`, directly after `app.mount(agent_tools.MOUNT, _agent_tools_app)`:
```python
# The same tools as plain GET endpoints for programs that are not agents
# (app/rest_data.py), behind the same token gate. Mounted before the SPA's
# catch-all for the same reason the tool server is.
from alphadesk.app import rest_data  # noqa: E402

app.mount(rest_data.PREFIX, agent_tools.TokenGate(rest_data.build()))
```
- `_note_for_prewarm` in `dashboard.py`: add `and not request.url.path.startswith("/api/v1")` to the condition.

### 5d. Run the same command → 3 passed; then the whole backend suite (`... pytest -q -p no:cacheprovider`) → green.

### 5e. Commit: `rest: mount the data API behind the token gate`.

---

## Step 6: Prove the door is read-only, complete and per-reader

**Files**: modify `tests/test_rest_data.py`. **Depends on**: Step 5. (These are guard tests; they should pass on first run — if any fail, the earlier step is wrong, so fix that, not the test.)

### 6a. Write tests (append)
```python
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
```

### 6b/6d. Run: `... pytest tests/test_rest_data.py -q -p no:cacheprovider` → all pass.

### 6e. Commit: `rest: guard tests — read-only, one endpoint per tool, one reader per call`.

---

## Step 7: Full-resolution bars

**Files**: modify `alphadesk/app/rest_data.py`, `tests/test_rest_data.py`. **Depends on**: Step 5.

First, a 5-minute read-only look (no code): open `dashboard.api_chart` (`alphadesk/app/dashboard.py`, `def api_chart`) and `ingest/prices.py` `page_attempts` and `history_floor`, and note (a) the format `before` is parsed from, (b) what `need` does. Write what you found as a comment above the endpoint in 7c. The endpoint reuses `api_chart` — it does not re-implement vendor selection or interval resolution.

### 7a. Write failing test (append)

*As built (see Status): the end-of-history test expects a 200 empty page with a `note` when `api_chart` raises 404 and a `before` was given; a 404 without `before` stays 404; a 503 keeps its `Retry-After`. The first sketch below assumed an empty list from the chart route, which is not what it does.*
```python
class TestBars:
    def _series(self):
        return {"vendor": "alpaca", "bars": [
            {"t": "2026-09-01T13:30:00+00:00", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "rsi_9": 55.0},
            {"t": "2026-09-02T13:30:00+00:00", "o": 1.5, "h": 2.5, "l": 1, "c": 2, "v": 200, "rsi_9": 60.0}],
            "indicators_reliable": True, "coverage": 1.0}

    def test_bars_come_back_whole_without_indicators_and_with_a_cursor(self, rest, monkeypatch):
        from alphadesk.app import dashboard
        calls = []
        monkeypatch.setattr(dashboard, "api_chart", lambda *a, **k: calls.append((a, k)) or self._series())
        r = rest.get("/api/v1/bars/AAPL?interval=1d&range=MAX&before=2026-09-03T00:00:00Z")
        body = r.json()
        assert r.status_code == 200 and body["symbol"] == "AAPL" and body["vendor"] == "alpaca"
        assert body["bars"][0] == {"t": "2026-09-01T13:30:00+00:00", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}
        assert [b["t"][:10] for b in body["bars"]] == ["2026-09-01", "2026-09-02"]    # oldest first, nothing dropped
        assert body["count"] == 2 and body["next_before"] == "2026-09-01T13:30:00+00:00"
        assert calls[0][1]["interval"] == "1d" and calls[0][1]["before"] == "2026-09-03T00:00:00Z"

    def test_an_empty_page_ends_the_walk(self, rest, monkeypatch):
        from alphadesk.app import dashboard
        monkeypatch.setattr(dashboard, "api_chart", lambda *a, **k: {"vendor": "alpaca", "bars": []})
        body = rest.get("/api/v1/bars/AAPL?interval=1d&range=MAX").json()
        assert body["bars"] == [] and body["count"] == 0 and body["next_before"] is None

    def test_a_bad_interval_is_the_charts_own_400(self, rest, monkeypatch):
        from fastapi import HTTPException
        from alphadesk.app import dashboard
        def refuse(*a, **k): raise HTTPException(400, "interval must be one of 1m, 1d on alpaca")
        monkeypatch.setattr(dashboard, "api_chart", refuse)
        r = rest.get("/api/v1/bars/AAPL?interval=7m")
        assert r.status_code == 400 and "interval must be one of" in r.json()["detail"]
```

### 7b. Run: `... -k TestBars` → fails: 404 `no such data endpoint: bars` (the route does not exist).

### 7c. Implement — in `build()`, **before** the `/{name}` route (route order matters):
```python
    @api.get("/bars/{symbol}")
    def bars(symbol: str, request: Request, interval: str | None = None, range: str | None = None,
             before: str | None = None, need: int | None = None):
        """EVERY BAR, not the agent tools' thinned sample. One page per call,
        oldest first; `next_before` is the oldest bar's time, to pass as
        `before` for the page behind it; an empty page ends the walk. No
        indicators — a program computes its own, and the chart's rule that
        they hide when coverage is thin stays with the chart. One vendor
        serves a whole walk (dashboard.api_chart picks it), never a mix."""
        from alphadesk.app import dashboard
        try:
            series = dashboard.api_chart(symbol, range=range, interval=interval, before=before, need=need)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        out = [{k: b.get(k) for k in ("t", "o", "h", "l", "c", "v")} for b in (series.get("bars") or [])]
        return _reply(request, {"symbol": symbol.upper(), "interval": interval, "vendor": series.get("vendor") or series.get("source"),
                                "bars": out, "count": len(out), "next_before": out[0]["t"] if out else None})
```
(`HTTPException` is already imported in `build`.) Add `bars` to the spec: append an `openapi` path entry for `/bars/{symbol}` with `symbol` in `path` and the four optional query parameters.

### 7d. Run the same command → 3 passed; add one spec assertion (`"/bars/{symbol}" in spec["paths"]`) to `test_the_spec_describes_every_endpoint…` first, watch it fail, then pass.

### 7e. Commit: `rest: full-resolution bars, paged by time, without indicators`.

---

## Step 8: Address allowlist per token — the store and the gate

**Files**: modify `alphadesk/ledger/store.py`, `alphadesk/app/agent_access.py`, `alphadesk/app/agent_tools.py`, `alphadesk/app/dashboard.py`; create `tests/test_token_allowlist.py`. **Depends on**: Step 5. **Runs in parallel with Step 7** (no shared files).

### 8a. Write failing tests
```python
"""A token that may only be used from the addresses its reader named (2026-10-02)."""
import pytest
from alphadesk.app import agent_access, agent_tools


def test_an_address_is_matched_against_single_addresses_and_ranges():
    allow = agent_access.parse_allowlist("203.0.113.7, 198.51.100.0/24")
    assert agent_access.address_allowed("203.0.113.7", allow)
    assert agent_access.address_allowed("198.51.100.200", allow)
    assert not agent_access.address_allowed("203.0.113.8", allow)
    assert agent_access.address_allowed("203.0.113.8", [])            # no list: from anywhere


def test_a_malformed_entry_is_refused_when_the_list_is_set():
    with pytest.raises(ValueError, match="not an address"):
        agent_access.parse_allowlist("203.0.113.7, banana")


def test_the_address_is_the_one_the_front_door_added_not_the_one_the_caller_claimed():
    """Cloud Run APPENDS the real client address to X-Forwarded-For; anything
    before it was sent by the caller and proves nothing."""
    scope = {"headers": [(b"x-forwarded-for", b"1.2.3.4, 203.0.113.7")], "client": ("10.0.0.1", 1234)}
    assert agent_tools.client_address(scope) == "203.0.113.7"
    assert agent_tools.client_address({"headers": [], "client": ("127.0.0.1", 1)}) == "127.0.0.1"


@pytest.fixture()
def gated(store, monkeypatch):
    from fastapi.testclient import TestClient
    from alphadesk.app import dashboard
    store.ensure_local_user()
    uid = dashboard._local_uid()
    monkeypatch.setattr(agent_access, "limiter", agent_access.RateLimit())
    with TestClient(dashboard.app) as c:
        c.uid = uid
        yield c


def test_a_token_refuses_an_address_outside_its_list_and_accepts_one_inside(gated):
    _, token = agent_access.issue(gated.uid, "bot", allowed_ips="203.0.113.7")
    auth = {"Authorization": f"Bearer {token}"}
    outside = gated.get("/api/v1/data_sources", headers={**auth, "X-Forwarded-For": "198.51.100.9"})
    inside = gated.get("/api/v1/data_sources", headers={**auth, "X-Forwarded-For": "203.0.113.7"})
    assert outside.status_code == 403 and "address" in outside.json()["detail"]
    assert inside.status_code == 200


def test_a_token_with_no_list_works_from_anywhere(gated):
    _, token = agent_access.issue(gated.uid, "bot")
    assert gated.get("/api/v1/data_sources", headers={"Authorization": f"Bearer {token}",
                                                      "X-Forwarded-For": "198.51.100.9"}).status_code == 200


def test_the_list_can_be_set_at_creation_over_the_web_api(gated, monkeypatch):
    from alphadesk.app import dashboard
    monkeypatch.setattr(dashboard, "_key_user", lambda request: gated.uid)
    r = gated.post("/api/agent/access-tokens", json={"name": "bot", "allowed_ips": ["203.0.113.7"]})
    assert r.status_code == 200 and r.json()["allowed_ips"] == ["203.0.113.7"]
    assert gated.post("/api/agent/access-tokens", json={"name": "x", "allowed_ips": ["banana"]}).status_code == 422
```

### 8b. Run: `... pytest tests/test_token_allowlist.py -q -p no:cacheprovider` → fails: `AttributeError: ... no attribute 'parse_allowlist'`.

### 8c. Implement
- **Store** (`alphadesk/ledger/store.py`): add `allowed_ips TEXT` to the `agent_access_tokens` CREATE TABLE (~line 410) and append `"ALTER TABLE agent_access_tokens ADD COLUMN allowed_ips TEXT"` to the existing list of `ALTER TABLE … ADD COLUMN` statements (the tuple near line 590, which is run tolerating "duplicate column"). `create_agent_access_token(..., allowed_ips: str = "")` stores it; `list_agent_access_tokens` and `agent_access_token_by_hash` also SELECT it.
- **`agent_access.py`**:
```python
import ipaddress

def parse_allowlist(text: str) -> list:
    """The addresses and ranges a token may be used from. Empty: anywhere."""
    nets = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ValueError(f"{part!r} is not an address or range") from None
    return nets

def address_allowed(address: str, nets: list) -> bool:
    if not nets:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in n for n in nets)
```
  Extend `issue(user_id, name, allowed_ips="")` (validate with `parse_allowlist`, store the normalised text), and add `resolve_row(secret) -> dict | None` returning `token_id`, `user_id`, `allowed_ips`; make `resolve` call it so nothing else changes.
- **`agent_tools.py`**: add
```python
def client_address(scope) -> str:
    """The caller's address as the FRONT DOOR saw it: the last X-Forwarded-For
    entry (Cloud Run appends the real client; earlier entries were sent by the
    caller), else the socket peer."""
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
    forwarded = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return forwarded[-1] if forwarded else (scope.get("client") or ("",))[0]
```
  In `TokenGate.__call__`, for `adk_` tokens use `agent_access.resolve_row`, and after the billing check, before the rate limit: if the row's `allowed_ips` is non-empty and `not address_allowed(client_address(scope), parse_allowlist(...))`, answer 403 `{"detail": "this token cannot be used from this address"}` (a small `_forbidden` helper beside `_refuse`).
- **`dashboard.py`**: `AccessTokenIn` gains `allowed_ips: list[str] = []`; `POST /api/agent/access-tokens` joins them with commas, turns `ValueError` into HTTP 422, passes them to `issue`, and the response and the listing include `allowed_ips` as a list.

### 8d. Run: the same file → all pass; then `tests/test_agent_tools.py tests/test_agent_oauth.py tests/test_rest_data.py` → green.

### 8e. Commit: `tokens: an optional list of addresses a token may be used from`.

---

## Step 9: The allowlist field in the token form

**Files**: modify `alphadesk/ui/src/lib/api.ts`, `alphadesk/ui/src/pages/AccountPage.tsx`; create `alphadesk/ui/src/lib/allowedIps.ts` and `alphadesk/ui/src/lib/__tests__/allowedIps.test.mts`. **Depends on**: Step 8.

### 9a. Write failing test
```ts
import assert from "node:assert/strict"
import test from "node:test"
import { parseAllowedIps } from "../allowedIps.ts"

test("a comma or newline separated list becomes trimmed entries", () => {
  assert.deepEqual(parseAllowedIps("203.0.113.7, 198.51.100.0/24\n 2001:db8::1 "), ["203.0.113.7", "198.51.100.0/24", "2001:db8::1"])
  assert.deepEqual(parseAllowedIps("  "), [])
})
test("an entry that is not an address or range is named", () => {
  assert.throws(() => parseAllowedIps("203.0.113.7, banana"), /banana/)
  assert.throws(() => parseAllowedIps("300.1.1.1"), /300\.1\.1\.1/)
})
```
### 9b. Run `cd alphadesk/ui && pnpm test` → fails: module not found.
### 9c. Implement `allowedIps.ts` (split on `[,\n]`, trim, drop empties; accept a dotted IPv4 with optional `/0-32`, or anything containing `:` with optional `/0-128`; otherwise `throw new Error(\`${entry} is not an address or range\`)`). Then: `api.ts` `createAgentAccessToken(name, allowedIps?)` posts `allowed_ips`; `AccountPage.tsx` token form (~line 713–745) gets an optional field "Only from these addresses (optional)" with help text "Your execution server's address. A leaked token is useless from anywhere else.", parsed with `parseAllowedIps` before sending; each listed token shows its addresses (or "any address"). Use the existing field/button helpers only (`fieldCls`, `btnCls`) — no new sizes.
### 9d. `pnpm test`, `pnpm exec tsc -b`, `pnpm lint` → green with no new warnings in touched files.
### 9e. Commit source (`ui: an optional address list on a new agent token`), then `pnpm build` and commit the rebuilt bundle separately (`git add -A alphadesk/app/static`; `ui: rebuild the bundle with the token address list`).

---

## Step 10: Documentation and an example

**Files**: create `docs/rest-api.md`, `docs/examples/pull_daily_bars.py`; modify `README.md`. **Depends on**: Steps 7, 8.

- `docs/rest-api.md`: what it is and is not (read-only, polling not streaming, slower data); a five-minute quickstart (connect a key, create a token — with the address list for a server, call one endpoint with curl); the endpoint rules (GET only; query-string inputs; the error table 401/402/403/422/428/429/502; the rate-limit and as-of headers; `If-None-Match`); how to walk bars; safety guidance (treat any error or an old `X-AlphaDesk-As-Of` as "do nothing"; orders go through your own broker code); vendor-terms responsibility; self-hosting pointer.
- `docs/examples/pull_daily_bars.py`: standard-library only (`urllib`), reads the token from the environment, walks `/bars/{symbol}` back until an empty page, honours `Retry-After` on 429, and saves the bars as JSON lines. It is an example, not a shipped package.
- `README.md`: add one row for `/api/v1` beside the agent-access section and a link to `docs/rest-api.md`. Update the "50 read-only tools" sentence only if the count changed.
- Verify by running the example's `--help` and reading the doc against the tests' behaviour (no new test: documentation).
- Commit: `docs: the REST data API and a bars example`.

---

## Step 11: Full regression and a real-server check

**Depends on**: Steps 6–10.

1. `ALPHADESK_SEMANTIC_SEARCH=off .venv/bin/python -m pytest -q -p no:cacheprovider` → all green; `cd alphadesk/ui && pnpm test && pnpm exec tsc -b && pnpm lint` → green.
2. Start an **isolated** instance on a spare port with throwaway data (never the owner's local server or `.local-data`): `ALPHADESK_AUTH=off ALPHADESK_DATA=<scratch dir> ALPHADESK_VAULT_KEY=<fresh base64 32 bytes> DASHBOARD_PORT=8001 SEC_USER_AGENT="AlphaDesk verify (<owner email>)" ALPHADESK_SEMANTIC_SEARCH=off .venv/bin/python -m alphadesk.main dashboard`.
3. Create a token with `curl -X POST localhost:8001/api/agent/access-tokens -H 'Content-Type: application/json' -d '{"name":"verify"}'`, then check with `curl -i -H "Authorization: Bearer <token>"`: `/api/v1/data_sources` → 200 with `ETag`, `X-AlphaDesk-As-Of`, `X-RateLimit-*`; the same call with the `ETag` as `If-None-Match` → 304; no token → 401; `POST` → 405; `/api/v1/bars/AAPL?interval=1d&range=MAX` (no vendor key) → 428 naming vendors (`quote` answers 422 "no quote available" — see Status); `/api/v1/openapi.json` → the spec with 51 paths (50 tools plus bars); a loop of 125 calls → the 121st answers 429 with `Retry-After`.
4. Repeat one call with `X-Forwarded-For: 198.51.100.9` against a token created with `allowed_ips: ["203.0.113.7"]` → 403.
5. Stop only the process listening on the spare port; delete the scratch data.

---

## Step 12: Merge, deploy, verify live — end-to-end (needs the owner's go-ahead for each part)

**Depends on**: Step 11.

1. **Merge** the branch to `main` (the owner pushes, or approves the push). Confirm CI (backend including the linter, frontend) is green on `main`.
2. **Deploy** with `scripts/deploy.sh`: it refuses unless on `main` with a clean tree equal to `origin/main` — move the untracked `.local-data/` out of the repo first (checksum it, restore it after, verify the checksums) so the owner's vault key is not uploaded. Confirm the Google account and project with the owner before any `gcloud` command (last used: account `vignesh90085@gmail.com`, project `alphadesk-research`, region `us-east4`, service `alphadesk`).
3. **Verify live** with a real token the owner creates on the Account page (restricted to the execution server's address): `find_symbol`, then `quote` and `/bars/AAPL?interval=1d&range=MAX` with the owner's own vendor key; walk two pages of bars and check there is no overlap and the pages are oldest-first.
4. **Check the one assumption the allowlist rests on**: from an address that is *not* in a token's list, send `X-Forwarded-For: <an address that is in the list>` and confirm the live service still answers 403 (the real client address is the last entry Cloud Run appends). If it answers 200, stop: the allowlist is spoofable on this platform — switch `client_address` to the platform's trusted-hop count before anything relies on it.
5. Report what is live, the revision name, and anything not verified.

---

## Task dependencies

| Group | Steps | Can parallelize | Files touched |
|-------|-------|-----------------|---------------|
| 1 | 1, 2 | Yes | `rest_data.py`, `test_rest_data.py` / `agent_access.py`, `test_agent_tools.py` |
| 2 | 3 | No (needs 1) | `rest_data.py`, `test_rest_data.py` |
| 3 | 4 | No (needs 2) | `agent_tools.py`, `test_agent_tools.py` |
| 4 | 5 | No (needs 3, 4) | `dashboard.py`, `auth.py`, `test_rest_data.py` |
| 5 | 6 | No (needs 5) | `test_rest_data.py` |
| 6 | 7, 8 | Yes (7: `rest_data.py`+its test; 8: store, agent_access, agent_tools, dashboard, new test file) | disjoint |
| 7 | 9 | No (needs 8) | UI files, bundle |
| 8 | 10 | No (needs 7, 8) | docs, `README.md` |
| 9 | 11 | No | none (verification) |
| 10 | 12 | No | none (merge, deploy, live verification) |

## Open risks

- **The allowlist's trusted address** (Step 12.4) is an assumption about Cloud Run's header behaviour; it is verified live before anyone relies on it.
- **Tool errors that mean "no data"** (for example "no daily bars for ZZZ") arrive as `ValueError` and so as HTTP 422, indistinguishable from bad input except by the message. A later step could give the tools a distinct "nothing there" error and map it to 404.
- **Response schemas** are described by example only; typed outputs for the endpoints builders use first are a follow-up once those are known.
- **Capacity**: outside programs spend the server's capacity. The limiter is in memory per Cloud Run instance, so the effective limit grows with the instance count; watch usage before opening this beyond the owner.
