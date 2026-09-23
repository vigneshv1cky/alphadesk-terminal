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


# ---------------------------------------------------------------------------
# A REPEATEDLY SPLIT COMPANY (2026-09-23, #65)
#
# Every figure below is the real WHLR record, read from the reader's own FMP
# key on 2026-09-23 while the stock traded at $6.26, up 191% the day after a
# 1-for-9 reverse split.
#
# The point of these tests is the DISTINCTION, not the detection. A vendor
# reporting a $94,608 52-week high is being faithful: a reverse split restates
# every historical per-share figure retroactively, and Wheeler's own SEC
# filings carry a diluted loss of $346,484 a share for 2024. Deleting a true
# figure would be a quieter lie than printing it. What is impossible is a
# NASDAQ-listed REIT with 3,048 shares and a $434M enterprise value.
# ---------------------------------------------------------------------------

WHLR = {
    "market_cap": 16581.0, "enterprise_value": 434384581.0,
    "shares_outstanding": 3048.0, "float_shares": 2420.0,
    "week52_low": 1.65, "week52_high": 94608.0,
    "avg_50d": 19.8473, "avg_200d": 3932.1476,
    "trailing_eps": 8750.645327826536, "book_value": 53284.460505937015,
    "trailing_pe": 0.00011424508047872887, "price_to_book": 0.00013822827983366346,
    "price_to_sales": 0.0001727313449939058, "ev_to_ebitda": 5.69303916069252,
    "beta": 1.084, "avg_volume": 1292118.0,
}
WHLR_QUOTE = {"price": 6.26, "previous_close": 1.87, "day_low": 4.75,
              "day_high": 8.71, "volume": 89182031}


def test_a_restated_figure_is_kept_and_a_contradicted_one_is_withheld():
    from alphadesk.ingest.keystats import merge

    out = merge(WHLR, WHLR_QUOTE)

    # KEPT, because they are true. The vendor restated them to an older share
    # count; that is what the company itself filed.
    assert out["week52_high"] == 94608.0
    assert out["trailing_eps"] == WHLR["trailing_eps"]
    assert out["book_value"] == WHLR["book_value"]
    assert out["avg_200d"] == WHLR["avg_200d"]

    # WITHHELD, because a NASDAQ-listed REIT cannot have 3,048 shares while
    # carrying a $434M enterprise value — the two came from one response.
    assert out["market_cap"] is None
    assert out["shares_outstanding"] is None
    assert out["float_shares"] is None

    # WITHHELD, because each divides today's price by a restated per-share
    # figure. A P/E of 0.000114 is not a cheap stock, it is two different
    # share counts in one fraction.
    assert out["trailing_pe"] is None
    assert out["price_to_book"] is None
    assert out["price_to_sales"] is None

    # UNTOUCHED: the price block is current and correct, and EV/EBITDA is two
    # whole-company totals, so no share count enters it.
    assert out["price"] == 6.26 and out["volume"] == 89182031
    assert out["ev_to_ebitda"] == WHLR["ev_to_ebitda"]


def test_the_range_marker_is_ours_and_must_not_be_drawn_across_a_split():
    """A stock up 191% on the day was drawn sitting at the very bottom of its
    year, because the range it was measured against spans the split. That
    figure is not the vendor's — we computed it."""
    from alphadesk.ingest.keystats import merge

    assert merge(WHLR, WHLR_QUOTE)["week52_position"] is None
    # On a sound record it is still computed, or this "fix" would delete a
    # working feature.
    sound = merge({"week52_low": 100.0, "week52_high": 200.0}, {"price": 150.0})
    assert sound["week52_position"] == 50.0
    assert "basis" not in sound


def test_the_reasons_are_the_measurements_not_a_verdict():
    from alphadesk.ingest.keystats import merge

    # Read from where the reasons are RECORDED, not by re-running the check
    # on the output — by then the contradicted figures are already withheld,
    # so the check would find nothing to complain about.
    found = merge(WHLR, WHLR_QUOTE)["basis"]
    assert any("52-week high is 15,113 times the price" in r for r in found["pre_split"])
    assert any("book value per share is 8,512 times" in r for r in found["pre_split"])
    assert any("26,198 times the market capitalisation" in r for r in found["share_count"])


@pytest.mark.parametrize("label, stats, quote", [
    # A large cap.
    ("large cap", {"market_cap": 3.4e12, "enterprise_value": 3.45e12, "week52_low": 164.0,
                   "week52_high": 260.0, "avg_50d": 230.0, "avg_200d": 222.0,
                   "trailing_eps": 6.60, "book_value": 4.40, "trailing_pe": 38.0},
     {"price": 250.0}),
    # Deep distress: enterprise value 216 times the equity, book above price.
    ("distressed", {"market_cap": 4.2e6, "enterprise_value": 9.1e8, "week52_low": 0.18,
                    "week52_high": 9.40, "avg_50d": 1.10, "avg_200d": 3.80,
                    "trailing_eps": -2.9, "book_value": 1.8, "price_to_book": 0.16},
     {"price": 0.29}),
    # Down 99% in a year with NO split: the 52-week high is 117 times the
    # price and every figure is sound. This is the false positive that would
    # hide a true record, so it is the one that matters most.
    ("down 99%", {"market_cap": 8.0e6, "enterprise_value": 2.4e7, "week52_low": 0.10,
                  "week52_high": 14.0, "avg_50d": 0.30, "avg_200d": 2.60,
                  "trailing_eps": -4.1, "book_value": 0.9, "price_to_book": 0.13},
     {"price": 0.12}),
])
def test_a_sound_record_is_never_touched(label, stats, quote):
    from alphadesk.ingest.keystats import merge

    out = merge(stats, quote)
    assert "basis" not in out, label
    for field, want in stats.items():
        assert out[field] == want, f"{label}: {field}"
