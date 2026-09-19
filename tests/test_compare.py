"""Comparison metrics and peers from the user's vendors: order kept, the
symbols no vendor answers named as missing, peers never guessed."""

import pytest

from alphadesk.ingest import compare
from alphadesk.providers.base import NeedsKey


class _F:
    name = "finnhub"
    def compare_metrics(self, s):
        return None if s == "ZZZZ" else {"symbol": s, "pe": {"AAPL": 37.6, "MSFT": 27.5}.get(s)}
    def peers(self, s):
        return ["AAPL", "DELL", "HPQ"] if s == "AAPL" else None


def test_compare_keeps_order_and_names_the_missing(vendors):
    vendors(finnhub=_F())
    out = compare.compare(["msft", "aapl", "zzzz", "msft"])
    assert [r["symbol"] for r in out["rows"]] == ["MSFT", "AAPL"] and out["missing"] == ["ZZZZ"]
    assert out["vendor"] == "finnhub"


def test_peers_drop_the_company_itself(vendors):
    vendors(finnhub=_F())
    assert compare.peers("aapl") == {"symbol": "AAPL", "peers": ["DELL", "HPQ"], "source": "finnhub"}


def test_no_vendor_is_a_key_prompt(vendors):
    vendors()
    with pytest.raises(NeedsKey):
        compare.compare(["AAPL", "MSFT"])
    with pytest.raises(NeedsKey):
        compare.peers("AAPL")
