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
