"""Movers from the user's vendors (2026-09-13): each category asks the
connected vendor that carries it, statistics come from the user's daily
bars, floors apply, Treasury yields are keyless public data, and a
category no connected vendor serves is a key prompt."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from alphadesk.ingest import movers
from alphadesk.providers.base import NeedsKey
from alphadesk.providers.prices import CoinGeckoPrices, PolygonPrices


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    movers.reset_cache()
    # Rebuilds run inline so a test sees the rebuilt payload.
    def inline(router, key, cat, top, mp, floors):
        movers._build(router, key, cat, top, mp, floors)
        done = threading.Event()
        done.set()
        return done
    monkeypatch.setattr(movers, "_refresh_async", inline)


def _bars(close, volume, n=21):
    t0 = datetime(2026, 8, 12, tzinfo=timezone.utc)
    return [{"ts": t0 + timedelta(days=i), "close": close * (1 + 0.01 * ((-1) ** i)), "volume": volume} for i in range(n)]


class _Alpaca:
    name = "alpaca"
    def category_movers(self, category, top=20):
        if category != "stocks":
            return None
        return {"tabs": [
            {"id": "most_active", "label": "Active", "rows": [
                {"symbol": "KHC", "name": "Kraft Heinz", "price": 24.6, "change_pct": 0.86, "volume": 123_719_348},
                {"symbol": "TRUG", "name": "TruGolf", "price": 0.65, "change_pct": 76.1, "volume": 434_453_794}]},
            {"id": "gainers", "label": "Gainers", "rows": [
                {"symbol": "ACVA", "name": "ACV Auctions", "price": 10.41, "change_pct": 44.18, "volume": 115_460_361},
                {"symbol": "THIN", "name": "Thin", "price": 9.0, "change_pct": 12.0, "volume": 20_000}]},
            {"id": "losers", "label": "Losers", "rows": []}]}
    def daily_history(self, symbols, sessions=21):
        return {"KHC": _bars(24.5, 30_000_000), "ACVA": _bars(10, 8_000_000)}


def test_stocks_from_the_vendor_with_floors_and_statistics(vendors):
    vendors(alpaca=_Alpaca())
    out = movers.category_movers("stocks")
    tabs = {t["id"]: t["rows"] for t in out["tabs"]}
    assert out["source"] == "alpaca" and out["change_label"] == "1D"
    assert [r["symbol"] for r in tabs["most_active"]] == ["KHC"]         # TRUG under $5
    assert [r["symbol"] for r in tabs["gainers"]] == ["ACVA"]            # THIN under $1M turnover
    khc = tabs["most_active"][0]
    assert khc["liquidity"] and khc["volatility"] is not None and khc["turnover"] == pytest.approx(24.6 * 123_719_348)
    assert out["note"] == "≥ $5 · ≥ $1M turnover"


def test_the_reader_can_move_the_floors(vendors):
    vendors(alpaca=_Alpaca())
    out = movers.category_movers("stocks", min_price=0, min_turnover=0)
    assert {r["symbol"] for r in out["tabs"][0]["rows"]} == {"KHC", "TRUG"}
    deep = movers.category_movers("stocks", min_liquidity=500_000_000)
    assert [r["symbol"] for r in deep["tabs"][0]["rows"]] == ["KHC"]


def test_a_category_no_vendor_carries_is_a_key_prompt(vendors):
    vendors(alpaca=_Alpaca())
    with pytest.raises(NeedsKey) as exc:
        movers.category_movers("currencies")
    assert [v["name"] for v in exc.value.prompt()["vendors"]] == ["fmp", "polygon"]
    with pytest.raises(KeyError):
        movers.category_movers("futures")            # removed: no vendor implemented carries it


def test_one_users_payload_is_not_served_to_another(vendors):
    from alphadesk.providers import registry
    import alphadesk.providers as pkg
    vendors(alpaca=_Alpaca())
    movers.category_movers("stocks")
    other = registry.DataRouter("someone-else", {})
    pkg.get_prices = lambda: other                  # restored by the vendors fixture's monkeypatch
    with pytest.raises(NeedsKey):
        movers.category_movers("stocks")


def test_treasury_rows_state_the_yield_and_the_change_in_basis_points():
    csv_text = ('Date,"1 Mo","2 Yr","10 Yr","30 Yr"\n'
                "09/11/2026,3.93,4.63,4.96,5.35\n"
                "09/10/2026,3.91,4.56,4.95,5.37\n")
    rows = {r["display"]: r for r in movers.treasury_rows(csv_text)}
    assert rows["10 Yr"]["price"] == 4.96 and rows["10 Yr"]["change_pct"] == 1.0
    assert rows["30 Yr"]["change_pct"] == -2.0 and rows["2 Yr"]["name"] == "2-year note"
    assert rows["1 Mo"]["as_of"] == "2026-09-11"


def test_bonds_need_no_key(vendors, monkeypatch):
    vendors()
    monkeypatch.setattr(movers, "_treasury", lambda: {"tabs": movers.tabs_from_list(movers.treasury_rows(
        'Date,"10 Yr"\n09/11/2026,4.96\n09/10/2026,4.95\n'), with_active=False), "source": "treasury"})
    out = movers.category_movers("bonds")
    assert out["source"] == "treasury" and out["change_label"] == "1D bp"
    assert out["tabs"][0]["rows"][0]["price"] == 4.96


def test_coingecko_markets_on_the_users_key(monkeypatch):
    from alphadesk.providers import prices as pp
    seen = {}
    def get_json(url, headers, timeout=20.0):
        seen.update(url=url, headers=headers)
        return [{"symbol": "btc", "name": "Bitcoin", "current_price": 77300.0, "price_change_percentage_24h": 0.4, "total_volume": 2.1e10},
                {"symbol": "eth", "name": "Ethereum", "current_price": 2508.0, "price_change_percentage_24h": -0.5, "total_volume": 9e9}]
    monkeypatch.setattr(pp, "_get_json", get_json)
    out = CoinGeckoPrices(api_key="CG-key").category_movers("crypto", 20)
    assert seen["headers"] == {"x-cg-demo-api-key": "CG-key"}
    assert [r["symbol"] for r in out["tabs"][0]["rows"]] == ["BTC-USD", "ETH-USD"]
    assert out["tabs"][0]["rows"][0]["turnover"] == 2.1e10
    assert CoinGeckoPrices(api_key="k").category_movers("stocks") is None


def test_polygon_option_movers_from_the_chain_snapshot(monkeypatch):
    from alphadesk.providers import prices as pp
    payload = {"results": [
        {"details": {"ticker": "O:SPY260918P00750000", "contract_type": "put", "expiration_date": "2026-09-18", "strike_price": 750},
         "day": {"volume": 100_820, "close": 1.8, "change_percent": -59.4}, "implied_volatility": 0.182, "open_interest": 186_670},
        {"details": {"ticker": "O:SPY260918C00800000", "contract_type": "call", "expiration_date": "2026-09-18", "strike_price": 800},
         "day": {"volume": 0, "close": 0.5, "change_percent": 3.0}}]}
    monkeypatch.setattr(pp, "_get_json", lambda url, headers, timeout=20.0: payload)
    poly = PolygonPrices(api_key="k")
    monkeypatch.setattr(PolygonPrices, "OPTION_UNDERLYINGS", ("SPY",))
    out = poly.category_movers("options", 5)
    row = out["tabs"][0]["rows"][0]
    assert row["display"] == "SPY 750P 09-18" and row["volatility"] == 18.2 and row["liquidity"] == round(100_820 * 1.8 * 100)
    assert len(out["tabs"][0]["rows"]) == 1                    # no volume, no row


def test_alpaca_crypto_volume_is_in_coins_so_turnover_is_price_times_volume():
    got = {"tabs": [{"id": "all", "label": "All", "rows": [{"symbol": "SHIB-USD", "price": 5.25e-06, "change_pct": -0.76, "volume": 3.8e13}]}]}
    row = movers._normalize_tabs(got, "crypto")[0]["rows"][0]
    assert row["turnover"] == pytest.approx(5.25e-06 * 3.8e13) and row["display"] == "SHIB"


def test_a_list_past_its_lifetime_comes_back_rebuilt_not_a_cycle_late(vendors, monkeypatch):
    """The tile asks every 30 seconds; answering with the old copy and
    rebuilding behind it put every list a whole cycle behind."""
    monkeypatch.undo()                    # the real background rebuild
    movers.reset_cache()
    alpaca = _Alpaca()
    vendors(alpaca=alpaca)
    first = movers.category_movers("stocks")
    key = next(iter(movers._cache))
    stamp, payload = movers._cache[key]
    movers._cache[key] = (stamp - movers.TTL_S["stocks"] - 1, payload)
    old_as_of = payload["as_of"]
    time.sleep(1.1)                       # as_of has whole-second resolution
    again = movers.category_movers("stocks")
    assert again["as_of"] != old_as_of and first["tabs"] == again["tabs"]


def test_a_slow_rebuild_still_answers_with_the_old_list(vendors, monkeypatch):
    monkeypatch.undo()
    movers.reset_cache()
    vendors(alpaca=_Alpaca())
    movers.category_movers("stocks")
    key = next(iter(movers._cache))
    stamp, payload = movers._cache[key]
    movers._cache[key] = (stamp - 999, payload)
    release = threading.Event()
    real_build = movers._build
    monkeypatch.setattr(movers, "_build", lambda *a: (release.wait(5), real_build(*a))[1])
    monkeypatch.setattr(movers, "REFRESH_WAIT_S", 0.05)
    assert movers.category_movers("stocks") is payload
    release.set()


def test_the_dollar_volume_tab_keeps_its_vendor_figure_and_its_floors(vendors):
    class _WithDollars(_Alpaca):
        def category_movers(self, category, top=20):
            got = super().category_movers(category, top)
            if got:
                got["tabs"].insert(1, {"id": "dollar_volume", "label": "Dollar volume", "rows": [
                    {"symbol": "KHC", "name": "Kraft Heinz", "price": 24.6, "change_pct": 0.86, "volume": 1_000_000, "turnover": 30_000_000.0},
                    {"symbol": "TRUG", "name": "TruGolf", "price": 0.65, "change_pct": 76.1, "volume": 434_453_794, "turnover": 280_000_000.0}]})
            return got
    vendors(alpaca=_WithDollars())
    out = movers.category_movers("stocks")
    assert [t["id"] for t in out["tabs"]] == ["most_active", "dollar_volume", "gainers", "losers"]
    dollars = out["tabs"][1]["rows"]
    assert [r["symbol"] for r in dollars] == ["KHC"]            # TRUG under the $5 floor
    assert dollars[0]["turnover"] == 30_000_000.0               # not price × volume


class _MixedScreener(_Alpaca):
    """Alpaca's most-active list as it is: leveraged funds among the stocks."""
    def category_movers(self, category, top=20):
        rows = [
            {"symbol": "NVDA", "name": "NVIDIA Corporation Common Stock", "price": 212.0, "change_pct": 0.6, "volume": 90_000_000},
            {"symbol": "SOXL", "name": "Direxion Daily Semiconductor Bull 3X ETF", "price": 103.0, "change_pct": 1.9, "volume": 80_000_000},
            {"symbol": "QQQ", "name": "Invesco QQQ Trust, Series 1", "price": 705.0, "change_pct": -0.5, "volume": 40_000_000},
            {"symbol": "BMNR", "name": "BitMine Immersion Technologies, Inc. Common Stock", "price": 24.4, "change_pct": -5.3, "volume": 30_000_000},
        ]
        funds = {"stocks": "exclude", "etfs": "only"}.get(category)
        return {"tabs": [{"id": "most_active", "label": "Active", "rows": rows}], "source": "alpaca", "funds": funds} if funds else None


class _FundList:
    name = "fmp"
    def __init__(self):
        self.asked = 0
    def etf_symbols(self):
        self.asked += 1
        return frozenset({"SOXL", "QQQ", "SPY"})


def test_funds_leave_the_stock_list_and_make_the_etf_list_by_the_vendors_fund_list(vendors):
    """2026-09-15: about half of Alpaca's most-active rows were leveraged funds."""
    fmp = _FundList()
    vendors(alpaca=_MixedScreener(), fmp=fmp)
    stocks = movers.category_movers("stocks")["tabs"][0]["rows"]
    etfs = movers.category_movers("etfs")["tabs"][0]["rows"]
    assert [r["symbol"] for r in stocks] == ["NVDA", "BMNR"]
    assert [r["symbol"] for r in etfs] == ["SOXL", "QQQ"]
    assert fmp.asked == 1                                  # kept per reader, not asked per list


def test_without_a_fund_list_a_funds_name_decides(vendors):
    vendors(alpaca=_MixedScreener())
    assert [r["symbol"] for r in movers.category_movers("stocks")["tabs"][0]["rows"]] == ["NVDA", "BMNR"]
    assert [r["symbol"] for r in movers.category_movers("etfs")["tabs"][0]["rows"]] == ["SOXL", "QQQ"]
    assert movers.is_fund({"symbol": "RKT", "name": "Rocket Companies, Inc. Class A Common Stock"}, None) is False
    assert movers.is_fund({"symbol": "IBIT", "name": "iShares Bitcoin Trust ETF"}, None) is True



class _AlpacaCoins:
    """Alpaca's crypto: volume from its own venue only."""
    name = "alpaca"
    def category_movers(self, category, top=20):
        if category != "crypto":
            return None
        rows = [{"symbol": "BTC-USD", "name": "BTC", "price": 76283.0, "change_pct": -2.4, "volume": 16},
                {"symbol": "ETH-USD", "name": "ETH", "price": 2413.0, "change_pct": -4.0, "volume": 9},
                {"symbol": "SOL-USD", "name": "SOL", "price": 99.0, "change_pct": 1.1, "volume": 135}]
        return {"tabs": [{"id": "all", "label": "All", "rows": rows},
                         {"id": "gainers", "label": "Gainers", "rows": [rows[2]]}], "source": "alpaca", "venue_volume": True}


def test_one_venues_crypto_volume_sets_no_default_turnover_floor(vendors):
    """2026-09-15: the $1M default left Alpaca's crypto list one row, since
    its volume counts only Alpaca's own venue."""
    vendors(alpaca=_AlpacaCoins())
    out = movers.category_movers("crypto")
    assert [r["symbol"] for r in out["tabs"][0]["rows"]] == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert [r["symbol"] for r in out["tabs"][1]["rows"]] == ["SOL-USD"]
    assert out["floors"]["min_turnover"] == 0 and out["floors"]["default_min_turnover"] == 0
    assert all(r["liquidity"] is None for r in out["tabs"][0]["rows"])   # one venue's turnover is not liquidity
    # The reader's own floor still applies.
    assert [r["symbol"] for r in movers.category_movers("crypto", min_turnover=1_000_000)["tabs"][0]["rows"]] == ["BTC-USD"]


def test_option_rows_keep_the_underlying_and_expiry_a_click_opens(vendors):
    class _Opts:
        name = "alpaca"
        def category_movers(self, category, top=20):
            if category != "options":
                return None
            return {"tabs": [{"id": "most_active", "label": "Active", "rows": [
                {"symbol": "SPY260918C00760000", "display": "SPY 760C 09-18", "name": "SPY 2026-09-18 call 760",
                 "price": 2.1, "change_pct": 5.0, "volume": 90_000, "volatility": 14.2, "liquidity": 18_900_000,
                 "turnover": 18_900_000, "underlying": "SPY", "expiry": "2026-09-18"}]}], "source": "alpaca"}
    vendors(alpaca=_Opts())
    row = movers.category_movers("options")["tabs"][0]["rows"][0]
    assert row["underlying"] == "SPY" and row["expiry"] == "2026-09-18" and row["turnover"] == 18_900_000


def test_a_coins_impossible_volume_is_discarded_without_dropping_the_coin(vendors, monkeypatch):
    """2026-09-15: CoinGecko sent Ethereum's 24h volume as ~$1.19e19 beside a
    ~$290B market cap; the tile printed $11,899,776.32T as its liquidity."""
    from alphadesk.providers import prices as pp
    assert pp.coingecko_volume(3.47e10, 1.5e12) == (3.47e10, False)
    assert pp.coingecko_volume(1.19e19, 2.9e11) == (0.0, True)
    assert pp.coingecko_volume(5e6, None) == (5e6, False)          # no cap to judge by
    monkeypatch.setattr(pp, "_get_json", lambda url, headers, timeout=20.0: [
        {"symbol": "btc", "name": "Bitcoin", "current_price": 76219.0, "price_change_percentage_24h": -3.3,
         "total_volume": 3.475e10, "market_cap": 1.5e12},
        {"symbol": "eth", "name": "Ethereum", "current_price": 2415.8, "price_change_percentage_24h": -4.6,
         "total_volume": 1.19e19, "market_cap": 2.9e11},
    ])
    vendors(coingecko=CoinGeckoPrices(api_key="CG-key"))
    rows = {r["symbol"]: r for r in movers.category_movers("crypto")["tabs"][0]["rows"]}
    assert set(rows) == {"BTC-USD", "ETH-USD"}                     # the $1M floor keeps ETH
    assert rows["ETH-USD"]["liquidity"] is None and rows["BTC-USD"]["liquidity"] == 3.475e10


def test_a_coingecko_list_is_rebuilt_every_two_minutes_not_thirty_seconds(vendors, monkeypatch):
    """The free Demo key allows 10,000 calls a month."""
    from alphadesk.providers import prices as pp
    calls = []
    monkeypatch.setattr(pp, "_get_json", lambda url, headers, timeout=20.0: calls.append(url) or [
        {"symbol": "btc", "name": "Bitcoin", "current_price": 76219.0, "price_change_percentage_24h": -3.3,
         "total_volume": 3.475e10, "market_cap": 1.5e12}])
    vendors(coingecko=CoinGeckoPrices(api_key="CG-key"))
    movers.category_movers("crypto")
    key = next(iter(movers._cache))
    stamp, payload = movers._cache[key]
    movers._cache[key] = (stamp - 60, payload)                      # a minute old: past crypto's 30s
    movers.category_movers("crypto")
    assert len(calls) == 1
    movers._cache[key] = (stamp - 121, payload)
    movers.category_movers("crypto")
    assert len(calls) == 2


def test_the_currency_day_turns_at_5pm_new_york_and_skips_the_weekend():
    from datetime import datetime
    from alphadesk.config import ET
    from alphadesk.providers.prices import close_at, fx_rollover
    at = lambda *a: datetime(*a, tzinfo=ET)  # noqa: E731
    assert fx_rollover(at(2026, 9, 15, 13, 48)) == at(2026, 9, 14, 17)   # Tuesday afternoon: Monday's 5pm
    assert fx_rollover(at(2026, 9, 15, 17, 1)) == at(2026, 9, 15, 17)    # just past Tuesday's 5pm
    assert fx_rollover(at(2026, 9, 18, 18, 0)) == at(2026, 9, 17, 17)    # Friday evening: still Friday's day
    assert fx_rollover(at(2026, 9, 19, 12, 0)) == at(2026, 9, 17, 17)    # Saturday
    assert fx_rollover(at(2026, 9, 20, 17, 30)) == at(2026, 9, 20, 17)   # Sunday's open begins Monday's day
    bars = [{"date": "2026-09-14 16:50:00", "close": 1.15498}, {"date": "2026-09-14 16:55:00", "close": 1.15504},
            {"date": "2026-09-14 17:00:00", "close": 1.15508}]
    assert close_at(bars, at(2026, 9, 14, 17), 5) == 1.15504           # the bar ending at 5pm
    assert close_at(bars, at(2026, 9, 14, 16, 50), 5) is None


def test_fmp_currency_change_runs_from_each_pairs_rollover_close(monkeypatch):
    from alphadesk.providers.company_vendors import FmpPrices
    f = FmpPrices(api_key="k")
    asked = []

    def get(path, **q):
        asked.append(path)
        if path == "batch-quote":
            return [{"symbol": "EURUSD", "price": 1.15376, "changePercentage": -0.16}, {"symbol": "USDJPY", "price": 155.168}]
        return [{"date": "2026-01-01 00:00:00", "close": 1.0}] if q["symbol"] == "EURUSD" else []
    monkeypatch.setattr(f, "_get", get)
    got = f.category_movers("currencies")
    rows = {r["symbol"]: r for r in got["tabs"][0]["rows"]}
    assert rows["EURUSD"]["change_pct"] == round(100 * (1.15376 - 1), 3)   # FMP's own -0.16% is not used
    assert rows["USDJPY"]["change_pct"] is None                            # no rollover close: no change
    assert got["note"] == "change since the 5pm New York rollover"
    charts = asked.count("historical-chart/5min")
    f.category_movers("currencies")
    assert asked.count("historical-chart/5min") == charts * 2 - 1           # the kept EURUSD base is not asked again
