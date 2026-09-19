"""The Sectors page's figures (2026-09-15): returns from daily closes and
today's quote, relative to SPY, and where each group stands against it."""

from datetime import date, datetime, timedelta, timezone

import pytest

from alphadesk.ingest import sectors
from alphadesk.providers.base import NeedsKey

TODAY = date(2026, 9, 15)


def _bars(closes_by_days_ago: dict[int, float]):
    return [{"ts": datetime.combine(TODAY - timedelta(days=n), datetime.min.time(), timezone.utc),
             "close": c, "high": c * 1.01, "low": c * 0.99, "volume": 1}
            for n, c in sorted(closes_by_days_ago.items(), reverse=True)]


def test_returns_run_from_the_live_price_to_the_close_on_or_before_each_date():
    bars = _bars({400: 50.0, 365: 80.0, 260: 90.0, 91: 100.0, 30: 110.0, 8: 118.0, 7: 120.0, 1: 125.0})
    row = sectors.fund_row("XLK", "Technology", bars, {"price": 132.0, "change_pct": 1.2, "volume": 1_000_000}, TODAY)
    assert row["price"] == 132.0 and row["change_pct"] == 1.2
    assert row["w1"] == 10.0                      # 132 / 120, the close a week back
    assert row["m1"] == 20.0 and row["m3"] == 32.0 and row["y1"] == 65.0
    assert row["ytd"] == round((132 / 90 - 1) * 100, 2)   # the last close of 2025 (day 260 is 2025-12-29)
    assert row["high_52w"] == pytest.approx(126.25) and row["turnover"] == 132_000_000.0


def test_without_a_quote_the_last_close_stands_and_missing_history_is_none():
    row = sectors.fund_row("XLE", "Energy", _bars({5: 90.0, 1: 99.0}), None, TODAY)
    assert row["price"] == 99.0 and row["change_pct"] is None
    assert row["w1"] is None and row["y1"] is None and row["turnover"] is None


def test_relative_returns_subtract_the_benchmark_and_name_the_quadrant():
    bench = {"m1": 2.0, "m3": 5.0}
    row = sectors.fund_row("XLU", "Utilities", _bars({91: 100.0, 30: 100.0, 1: 101.0}), {"price": 101.0}, TODAY, bench)
    assert row["rel_m1"] == -1.0 and row["rel_m3"] == -4.0
    assert sectors.rotation(3.0, 4.0) == "leading"
    assert sectors.rotation(-1.0, 4.0) == "weakening"
    assert sectors.rotation(-1.0, -4.0) == "lagging"
    assert sectors.rotation(1.0, -4.0) == "improving"
    assert sectors.rotation(None, 1.0) is None


def test_the_page_is_one_bars_request_and_one_quotes_request_on_the_readers_vendor(vendors):
    sectors.reset_cache()
    asked = {}

    class _Alpaca:
        name = "alpaca"
        def daily_history(self, symbols, sessions=21):
            asked["bars"] = (list(symbols), sessions)
            return {s: _bars({91: 100.0, 30: 100.0, 1: 100.0}) for s in symbols}
        def quotes(self, symbols):
            asked["quotes"] = asked.get("quotes", 0) + 1
            return {s: {"price": 110.0 if s == "XLK" else 102.0, "change_pct": 0.5, "volume": 10} for s in symbols}

    vendors(alpaca=_Alpaca())
    out = sectors.sectors()
    assert asked["bars"][0][0] == "SPY" and len(asked["bars"][0]) == 1 + len(sectors.SECTORS) + len(sectors.INDUSTRIES)
    assert asked["bars"][1] == sectors.SESSIONS and asked["quotes"] == 1
    xlk = next(r for r in out["sectors"] if r["symbol"] == "XLK")
    assert xlk["rel_m1"] == 8.0 and xlk["rotation"] == "leading"
    sectors.sectors()
    assert asked["quotes"] == 1                    # kept a minute per reader


def test_no_vendor_with_daily_bars_is_a_key_prompt(vendors):
    sectors.reset_cache()
    vendors()
    with pytest.raises(NeedsKey):
        sectors.sectors()


def test_rows_carry_the_closes_their_returns_run_from():
    bars = _bars({400: 50.0, 365: 80.0, 260: 90.0, 91: 100.0, 30: 110.0, 7: 120.0, 1: 125.0})
    row = sectors.fund_row("XLK", "Technology", bars, {"price": 132.0, "change_pct": 1.2, "previous_close": 130.4}, TODAY)
    assert row["bases"] == {"w1": 120.0, "m1": 110.0, "m3": 100.0, "ytd": 90.0, "y1": 80.0, "d1": 130.4}
    derived = sectors.fund_row("XLE", "Energy", bars, {"price": 110.0, "change_pct": 10.0}, TODAY)
    assert derived["bases"]["d1"] == pytest.approx(100.0)          # from the price and the change


def test_breadth_counts_each_company_once_and_lists_the_largest():
    companies = [
        {"symbol": "XOM", "name": "Exxon Mobil Corporation", "sector": "Energy", "market_cap": 7e11, "avg_volume": 1.5e7},
        {"symbol": "CVX", "name": "Chevron Corporation", "sector": "Energy", "market_cap": 4.3e11, "avg_volume": 8e6},
        {"symbol": "SO", "name": "The Southern Company", "sector": "Utilities", "market_cap": 1e11, "avg_volume": 5e6},
        {"symbol": "SOJE", "name": "The Southern Company", "sector": "Utilities", "market_cap": 1e11, "avg_volume": 4e4},
        {"symbol": "BRK-A", "name": "Berkshire Hathaway Inc.", "sector": "Financial Services", "market_cap": 1e12, "avg_volume": 300},
        {"symbol": "BRK-B", "name": "Berkshire Hathaway Inc.", "sector": "Financial Services", "market_cap": 1e12, "avg_volume": 4e6},
        {"symbol": "ACME", "name": "Acme", "sector": "Conglomerates", "market_cap": 5e9},
    ]
    changes = {"XOM": {"price": 169.3, "change_pct": 2.5}, "CVX": {"price": 216.9, "change_pct": -0.2},
               "SO": {"price": 90.0, "change_pct": 0.0}, "BRK-B": {"price": 480.0, "change_pct": -0.1}}
    g = sectors.breadth_and_leaders(companies, changes)
    assert (g["XLE"]["up"], g["XLE"]["down"], g["XLE"]["companies"]) == (1, 1, 2)
    assert [l["symbol"] for l in g["XLE"]["leaders"]] == ["XOM", "CVX"]
    assert [l["symbol"] for l in g["XLU"]["leaders"]] == ["SO"] and g["XLU"]["flat"] == 1
    assert [l["symbol"] for l in g["XLF"]["leaders"]] == ["BRK-B"] and g["XLF"]["companies"] == 1
    assert set(g) == set(sectors.FMP_SECTOR)                          # an unknown sector is not a group


def test_weights_map_fmp_sectors_to_the_funds_and_breadth_needs_a_screener(vendors):
    sectors.reset_cache()

    class _Fmp:
        name = "fmp"
        def sector_weights(self):
            return {"Technology": 38.69, "Energy": 3.48, "Cash & Others": 0.01}

    router = vendors(fmp=_Fmp())
    assert sectors.sector_weights(router) == {"XLK": 38.69, "XLE": 3.48}
    with pytest.raises(NeedsKey):
        sectors.breadth()


def test_drivers_rank_by_the_market_value_moved_not_the_percent():
    assert sectors.value_change(5.0e12, 0.4) == round(5.0e12 - 5.0e12 / 1.004)
    assert sectors.value_change(1e9, None) is None and sectors.value_change(None, 3.0) is None
    companies = [
        {"symbol": "NVDA", "name": "NVIDIA", "sector": "Technology", "market_cap": 5.13e12},
        {"symbol": "SMOL", "name": "Small Co", "sector": "Technology", "market_cap": 5e9},
        {"symbol": "MSFT", "name": "Microsoft", "sector": "Technology", "market_cap": 3.7e12},
        {"symbol": "QUIET", "name": "Quiet Co", "sector": "Technology", "market_cap": 9e11},
    ]
    changes = {"NVDA": {"change_pct": 0.45}, "SMOL": {"change_pct": 20.0}, "MSFT": {"change_pct": -1.45}}
    g = sectors.breadth_and_leaders(companies, changes)["XLK"]
    assert [d["symbol"] for d in g["drivers"]] == ["MSFT", "NVDA", "SMOL"]      # QUIET has no change today
    assert g["drivers"][0]["value_change"] < 0 and g["drivers"][1]["value_change"] > 0
    assert [l["symbol"] for l in g["leaders"]] == ["NVDA", "MSFT", "QUIET", "SMOL"]


def test_the_session_is_the_latest_day_most_companies_traded_in():
    before_open = {f"S{i}": {"session": "2026-09-14"} for i in range(95)}
    before_open.update({f"E{i}": {"session": "2026-09-15"} for i in range(5)})   # a few early prints
    assert sectors.latest_session(before_open) == "2026-09-14"
    opened = {f"S{i}": {"session": "2026-09-15"} for i in range(40)}
    opened.update({f"Q{i}": {"session": "2026-09-14"} for i in range(60)})       # most not yet traded
    assert sectors.latest_session(opened) == "2026-09-15"
    assert sectors.latest_session({}) is None


def test_breadth_counts_the_sp500_members_once_per_company_with_their_caps(vendors):
    """2026-09-15: the funds hold only S&P members; the US screener over $2B
    counted 271 technology companies against the index's 85."""
    sectors.reset_cache()

    class _Fmp:
        name = "fmp"
        def sp500_constituents(self):
            return [{"symbol": "GOOGL", "name": "Alphabet Inc. (Class A)", "sector": "Communication Services", "cik": "0001652044"},
                    {"symbol": "GOOG", "name": "Alphabet Inc. (Class C)", "sector": "Communication Services", "cik": "0001652044"},
                    {"symbol": "LIN", "name": "Linde plc", "sector": "Basic Materials", "cik": "0001707925"}]
        def market_caps(self, symbols):
            return {"GOOGL": 3.9e12, "GOOG": 3.9e12, "LIN": 2.2e11}
        def sector_companies(self, min_market_cap=2e9):
            raise AssertionError("the screener is not asked when members are listed")

    class _Alpaca:
        name = "alpaca"
        def day_changes(self, symbols):
            return {"GOOGL": {"price": 320.0, "change_pct": -1.6, "session": "2026-09-15", "turnover": 3.0e9},
                    "GOOG": {"price": 321.0, "change_pct": -1.6, "session": "2026-09-15", "turnover": 2.1e9},
                    "LIN": {"price": 470.0, "change_pct": -0.5, "session": "2026-09-15", "turnover": 4.0e8}}

    vendors(fmp=_Fmp(), alpaca=_Alpaca())
    out = sectors.breadth()
    assert out["universe"] == "S&P 500 companies"
    xlc = out["groups"]["XLC"]
    assert xlc["companies"] == 1 and [l["symbol"] for l in xlc["leaders"]] == ["GOOGL"]    # the class traded more today
    assert out["groups"]["XLB"]["leaders"][0]["market_cap"] == 2.2e11                      # a member abroad keeps its cap


def test_without_a_member_list_breadth_falls_back_to_the_screener(vendors):
    sectors.reset_cache()

    class _Fmp:
        name = "fmp"
        def sector_companies(self, min_market_cap=2e9):
            return [{"symbol": "XOM", "name": "Exxon Mobil", "sector": "Energy", "market_cap": 7e11}]

    class _Alpaca:
        name = "alpaca"
        def day_changes(self, symbols):
            return {"XOM": {"price": 169.0, "change_pct": 2.5, "session": "2026-09-15"}}

    vendors(fmp=_Fmp(), alpaca=_Alpaca())
    out = sectors.breadth()
    assert out["universe"] == "US companies over $2B" and out["groups"]["XLE"]["up"] == 1
