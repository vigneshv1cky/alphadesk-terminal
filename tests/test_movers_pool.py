"""Gainers and losers from their first answer (2026-09-17).

Alpaca's own top 50 gainers and losers are mostly penny stocks and
warrants; after the $5 and $1M floors a handful are left, so the full lists
come from the dollar-volume pool (every listed stock trading $10M+ a day).
That pool took ~5 s to build after every restart — and on every new server
instance — and until it landed the tile showed 7 gainers and 3 losers for
30 s or more. Two fixes, held here: the pool is saved per reader and adopted
on start, and a reply built before it exists says it is still filling in,
so it is kept for seconds rather than a full lifetime.
"""

import threading
import time

from alphadesk.ingest import movers
from alphadesk.providers.alpaca import AlpacaPrices


# ── the saved pool ────────────────────────────────────────────────────────


def test_a_saved_pool_belongs_to_one_reader(store):
    store.save_dollar_pool("r1", "alpaca", ["NVDA", "AAPL"], 1_000)
    assert store.get_dollar_pool("r1", "alpaca") == (1_000, ["NVDA", "AAPL"])
    assert store.get_dollar_pool("r2", "alpaca") is None
    store.save_dollar_pool("r1", "alpaca", ["MSFT"], 2_000)
    assert store.get_dollar_pool("r1", "alpaca") == (2_000, ["MSFT"])


def _provider(reader="r1"):
    p = AlpacaPrices(api_key="k", api_secret="s")
    p.reader_id = reader
    p.stock_feed = lambda: "sip"
    return p


def test_a_fresh_instance_adopts_its_readers_saved_pool(store):
    store.save_dollar_pool("r1", "alpaca", ["NVDA", "AAPL"], int(time.time()) - 3600)
    p = _provider("r1")
    p._load_saved_pool()
    assert p._pool is not None and p._pool[1] == ["NVDA", "AAPL"]
    assert not p.pool_filling()

    other = _provider("r2")
    other._load_saved_pool()
    assert other._pool is None                      # never another reader's


def test_a_very_old_saved_pool_is_not_adopted(store):
    from alphadesk.providers import alpaca
    store.save_dollar_pool("r1", "alpaca", ["NVDA"], int(time.time() - alpaca.POOL_SAVED_MAX_AGE_S - 60))
    p = _provider("r1")
    p._load_saved_pool()
    assert p._pool is None


def test_a_built_pool_is_saved_under_its_reader(store, monkeypatch):
    from alphadesk.providers import alpaca
    p = _provider("r1")
    p._listing = lambda: {"NVDA": ("NVIDIA", "NASDAQ"), "TINY": ("Tiny", "NASDAQ")}

    def bars(path, **params):
        day = {"c": 200.0, "v": 1_000_000}
        return {"bars": {"NVDA": [day] * alpaca.POOL_SESSIONS, "TINY": [{"c": 1.0, "v": 10}] * 5}}
    p._data_get = bars
    p._pool_building = True
    p._build_pool()
    assert p._pool[1] == ["NVDA"] and not p._pool_building
    saved = store.get_dollar_pool("r1", "alpaca")
    assert saved and saved[1] == ["NVDA"]


# ── a reply built before the pool exists ──────────────────────────────────


def test_movers_before_the_pool_say_they_are_filling_in():
    p = _provider()
    p._pool_loaded = True                           # nothing saved
    p._pool_building = True                         # first build running

    class Screener:
        def get_most_actives(self, req):
            return type("R", (), {"most_actives": []})()

        def get_market_movers(self, req):
            return type("R", (), {"gainers": [], "losers": []})()
    p._client = lambda kind: Screener()
    p.pool_movers = lambda: None
    got = p.movers(20)
    assert got["filling"] is True
    assert p.category_movers("stocks")["filling"] is True

    p._pool = (time.time(), ["NVDA"])               # built: no longer filling
    assert "filling" not in p.movers(20)


class _Filling:
    """A vendor whose first answer is thin and says so, then full."""
    name = "alpaca"

    def __init__(self):
        self.calls = 0

    def category_movers(self, category, top=20):
        self.calls += 1
        rows = [{"symbol": f"S{i}", "price": 10.0, "change_pct": 5.0 - i * 0.1, "volume": 1_000_000}
                for i in range(3 if self.calls == 1 else 20)]
        return {"tabs": [{"id": "gainers", "label": "Gainers", "rows": rows}], "source": "alpaca",
                "filling": self.calls == 1}


def test_a_filling_list_is_replaced_in_seconds_not_a_full_lifetime(vendors, monkeypatch):
    movers.reset_cache()
    monkeypatch.setattr(movers, "_enrich_stats", lambda router, tabs, cat, venue=False: None)

    def inline(router, key, cat, top, mp, floors):
        movers._build(router, key, cat, top, mp, floors)
        done = threading.Event()
        done.set()
        return done
    monkeypatch.setattr(movers, "_refresh_async", inline)
    vendor = _Filling()
    vendors(alpaca=vendor)
    first = movers.category_movers("stocks", min_turnover=0)
    assert first["filling"] is True and len(first["tabs"][0]["rows"]) == 3

    # Within the category's 30 s lifetime, but past the filling lifetime.
    key = next(iter(movers._cache))
    stamp, payload = movers._cache[key]
    movers._cache[key] = (stamp - movers.FILLING_TTL_S - 0.1, payload)
    again = movers.category_movers("stocks", min_turnover=0)
    assert again["filling"] is False and len(again["tabs"][0]["rows"]) == 20


def test_the_per_reader_memo_does_not_hold_a_filling_answer():
    from alphadesk.providers import registry

    class Inner:
        name = "alpaca"
        n = 0

        def category_movers(self, category, top=20):
            Inner.n += 1
            return {"tabs": [], "filling": Inner.n == 1}
    cached = registry._CachedPrices(Inner())
    assert cached.category_movers("stocks")["filling"] is True
    key = next(iter(cached._memo))
    at, ttl, val = cached._memo[key]
    assert ttl <= registry._FILLING_TTL_S
    cached._memo[key] = (at - ttl - 0.1, ttl, val)
    assert cached.category_movers("stocks")["filling"] is False


# ── coins' volatility and liquidity (2026-09-19) ──

class _CoinRouter:
    def __init__(self, bars):
        self.bars = bars

    def get(self, method, syms, days):
        assert method == "crypto_daily_history"
        return {s: self.bars[s] for s in syms if s in self.bars}


def _coin_tabs():
    return [{"id": "all", "label": "All", "rows": [
        movers._row("BTC-USD", 100.0, 1.0, 2, turnover_is_volume=False),
        movers._row("USDG-USD", 1.0, None, 0)]}]


def test_coin_volatility_is_annualised_over_365_days():
    closes = [100, 102, 99, 101, 103, 100, 104, 102]
    stock = movers.stats_from_bars(closes, [1] * len(closes))
    coin = movers.stats_from_bars(closes, [1] * len(closes), periods=365)
    # Both are rounded to a tenth of a point, so the ratio holds to about 1%.
    assert abs(coin["volatility"] / stock["volatility"] - (365 / 252) ** 0.5) < 0.01


def test_venue_liquidity_is_the_twenty_day_figure_not_one_days_turnover():
    bars = [{"close": 100.0 + i, "volume": 10.0} for i in range(21)]
    tabs = _coin_tabs()
    movers._enrich_coins(_CoinRouter({"BTC-USD": bars}), tabs, venue=True)
    btc, usdg = tabs[0]["rows"]
    want = movers.stats_from_bars([b["close"] for b in bars], [b["volume"] for b in bars], periods=365)
    assert btc["volatility"] == want["volatility"] and btc["liquidity"] == want["liquidity"]
    # A coin with no bars shows neither, never its turnover.
    assert usdg["volatility"] is None and usdg["liquidity"] is None


def test_worldwide_volume_keeps_its_turnover_as_liquidity():
    tabs = _coin_tabs()
    movers._enrich_coins(_CoinRouter({}), tabs, venue=False)
    assert tabs[0]["rows"][0]["liquidity"] == tabs[0]["rows"][0]["turnover"]


# ── currencies and Treasury yields (2026-09-19) ──

def test_yield_volatility_is_basis_points_a_year():
    # Alternating +2bp / -2bp changes: a standard deviation just over 2bp a day.
    ys = [4.00 + (0.02 if i % 2 else 0.0) for i in range(21)]
    v = movers.yield_volatility(ys)
    assert 2.0 * 252 ** 0.5 < v < 2.2 * 252 ** 0.5
    assert movers.yield_volatility([4.0, 4.01, 4.02]) is None


def test_bars_a_year_are_read_from_the_dates():
    weekdays = [f"2026-09-{d:02d}" for d in (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15)]
    assert 240 < movers.periods_a_year(weekdays) < 270
    daily = [f"2026-09-{d:02d}" for d in range(1, 21)]
    assert movers.periods_a_year(daily) == 365
    assert movers.periods_a_year([]) == 252


def test_currencies_get_volatility_and_no_liquidity():
    class R:
        def get(self, method, pairs, days):
            assert method == "fx_daily_history"
            return {"EURUSD": [{"date": f"2026-09-{d:02d}", "close": 1.10 + 0.001 * (d % 3)} for d in range(1, 22)]}
    tabs = [{"id": "all", "label": "All", "rows": [movers._row("EURUSD", 1.1, 0.1), movers._row("USDJPY", 150.0, 0.2)]}]
    movers._enrich_stats(R(), tabs, "currencies")
    eur, jpy = tabs[0]["rows"]
    assert eur["volatility"] > 0 and eur["liquidity"] is None
    assert jpy["volatility"] is None and jpy["liquidity"] is None


def test_a_coingecko_list_keeps_only_coins_alpaca_trades():
    class R:
        def get(self, method):
            assert method == "crypto_symbols"
            return frozenset({"BTC", "ETH"})
    tabs = [{"id": "all", "label": "All", "rows": [
        movers._row("BTC-USD", 1.0, 1.0, display="BTC"), movers._row("BNB-USD", 1.0, 1.0, display="BNB"),
        movers._row("FIGR_HELOC-USD", 1.0, 1.0, display="FIGR_HELOC"), movers._row("ETH-USD", 1.0, 1.0, display="ETH")]}]
    got: dict = {}
    movers.only_tradable_coins(R(), tabs, got)
    assert [r["display"] for r in tabs[0]["rows"]] == ["BTC", "ETH"]
    assert got["note"] == "coins you can trade on Alpaca"


def test_without_alpaca_the_coin_list_stands():
    class R:
        def get(self, method):
            return None
    tabs = [{"id": "all", "label": "All", "rows": [movers._row("BNB-USD", 1.0, 1.0, display="BNB")]}]
    movers.only_tradable_coins(R(), tabs, {})
    assert len(tabs[0]["rows"]) == 1


def test_a_coin_with_only_a_coingecko_record_still_has_a_profile(monkeypatch):
    from alphadesk.ingest import company
    monkeypatch.setattr(company, "_edgar_facts", lambda s: None)
    monkeypatch.setattr(company, "_vendor_profile", lambda s: (None, []))
    monkeypatch.setattr(company, "_coin", lambda s: {"name": "Tezos", "market_cap_rank": 126})
    got = company.profile("XTZ-USD")
    assert got and got["name"] == "Tezos" and got["coin"]["market_cap_rank"] == 126
    monkeypatch.setattr(company, "_coin", lambda s: None)
    assert company.profile("XTZ-USD") is None
