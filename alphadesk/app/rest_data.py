"""AlphaDesk's data over plain HTTP (2026-10-02).

The agent tools, served as GET endpoints for programs that are not agents: a
trading bot, an importer, a script. One generic route looks a tool up by name
in the same registry the MCP door serves and calls the tool's own function, so
the two doors cannot drift and neither can write — every tool is a read.
Mounted behind the same TokenGate as the MCP door (app/agent_tools.py).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

# Module level on purpose: with postponed annotations FastAPI resolves a
# handler's `Request` by name from this module, and an import local to
# build() is invisible to it — the request then reads as a required query
# parameter and every call is refused with a 422.
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from alphadesk.providers.base import NeedsKey, ProviderError

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
