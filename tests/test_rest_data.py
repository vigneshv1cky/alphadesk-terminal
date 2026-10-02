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
