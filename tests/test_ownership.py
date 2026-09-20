"""Institutional ownership comes only from a connected vendor that carries
it (the Nasdaq route and the Yahoo holder table are gone, 2026-09-13)."""

import pytest

from alphadesk.ingest import ownership
from alphadesk.providers.base import NeedsKey


class _F:
    name = "finnhub"
    def institutional_ownership(self, s):
        return {"symbol": s, "source": "finnhub", "as_of": "2026-06-30", "summary": {},
                "holders": [{"name": f"Fund {i}", "date": "2026-06-30", "shares": 1e6 * (30 - i), "change": 1e3,
                             "change_pct": None, "value": None} for i in range(30)], "total_holders": None}


def test_holders_are_capped_and_the_tile_shape_follows(vendors):
    vendors(finnhub=_F())
    out = ownership.institutional_holdings("aapl", limit=5)
    assert len(out["holders"]) == 5 and out["source"] == "finnhub"
    tile = ownership.top_holders("aapl")
    assert tile["top_holders"][0]["holder"] == "Fund 0" and len(tile["top_holders"]) == 10


def test_no_vendor_is_a_key_prompt(vendors):
    vendors()
    with pytest.raises(NeedsKey) as exc:
        ownership.institutional_holdings("AAPL")
    # `have` is False for a reader with nothing connected, so the panel
    # offers it (2026-09-20).
    assert exc.value.prompt()["vendors"] == [{"name": "finnhub", "label": "Finnhub", "tier": "paid",
                                              "signup": "https://finnhub.io/register", "needs_secret": False,
                                              "have": False}]
