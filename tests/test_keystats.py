"""Key statistics from the user's vendors: the vendor's figures with the
quote's price block laid over, the 52-week position, and the key prompt
when no connected vendor carries them (2026-09-13)."""

import pytest

from alphadesk.ingest import keystats
from alphadesk.providers.base import NeedsKey


class _Stats:
    name = "finnhub"
    def key_stats(self, s):
        return {"symbol": s, "name": "Apple Inc", "market_cap": 4.85e12, "week52_low": 235.03, "week52_high": 344.57,
                "trailing_pe": 37.6, "dividend_yield": 0.5, "vendor": "finnhub"}


class _Quote:
    name = "alpaca"
    def quote(self, s):
        return {"symbol": s, "price": 332.27, "previous_close": 326.57, "volume": 50_906_905}


def test_merge_lays_the_price_block_over_and_computes_the_position():
    out = keystats.merge({"week52_low": 235.03, "week52_high": 344.57, "price": None}, {"price": 332.27, "open": 327.45})
    assert out["price"] == 332.27 and out["open"] == 327.45 and out["day_low"] is None
    assert out["week52_position"] == 88.8


def test_key_stats_from_the_connected_vendors(vendors):
    vendors(finnhub=_Stats(), alpaca=_Quote())
    out = keystats.key_stats("aapl")
    assert out["symbol"] == "AAPL" and out["vendor"] == "finnhub"
    assert out["price"] == 332.27 and out["market_cap"] == 4.85e12 and out["week52_position"] == 88.8


def test_no_vendor_is_a_key_prompt(vendors):
    vendors(alpaca=_Quote())
    with pytest.raises(NeedsKey) as exc:
        keystats.key_stats("AAPL")
    p = exc.value.prompt()
    assert p["surface"] == "key_stats" and [v["name"] for v in p["vendors"]][:2] == ["fmp", "finnhub"]   # a paid vendor with the fuller record first


def test_route_answers_428_without_a_vendor(client, vendors):
    vendors()
    r = client.get("/api/stats/AAPL")
    assert r.status_code == 428 and r.json()["detail"]["needs_key"]["label"] == "Key statistics"
