"""The plugin seam: registration, discovery, selection, failure."""

import pytest

from alphadesk.providers import base, registry
from alphadesk.providers.base import Article, ProviderError
class FakeNews:
    name = "fake-news"
    capabilities = ("summaries",)

    def fetch(self, since, limit=200):
        return [Article(id="1", title="t", url="u", published_at="2026-01-01T00:00:00Z",
                        symbols=["AAPL"])]


def test_fakes_satisfy_the_protocols():
    # runtime_checkable Protocols are the contract a third-party provider has
    # to meet without importing anything from AlphaDesk.
    assert isinstance(FakeNews(), base.NewsProvider)


def test_builtins_are_registered():
    got = registry.available()
    assert {"polygon", "alpaca"} <= set(got["news"])
    assert "builtin" not in got["prices"] and {"alpaca", "finnhub", "polygon"} <= set(got["prices"])


def test_build_constructs_from_explicit_config():
    prov = registry.build("news", "polygon", api_key="k")
    assert prov.name == "polygon"


def test_unknown_provider_names_what_is_available():
    with pytest.raises(ProviderError) as exc:
        registry.build("news", "nope", api_key="k")
    msg = str(exc.value)
    # the error has to be actionable: what you asked for AND what exists
    assert "nope" in msg and "polygon" in msg


def test_registering_an_existing_name_overrides_it():
    class Replacement(FakeNews):
        name = "polygon"
        def __init__(self, **kw): pass

    registry.register("news", "polygon", Replacement)
    try:
        assert isinstance(registry.build("news", "polygon", api_key="k"), Replacement)
    finally:
        from alphadesk.providers import news as _news
        registry.register("news", "polygon", _news.PolygonNews)


def test_bad_plugin_module_does_not_kill_startup(monkeypatch):
    monkeypatch.setenv("ALPHADESK_PLUGINS", "alphadesk.does_not_exist")
    registry._loaded = False
    registry.available()          # must not raise


class TestNewsCapabilities:
    """The feed declares what it delivers; the UI frames itself on that.
    Declarations must match the feed's real payload — an optimistic one is a
    broken promise on the settings screen."""

    def test_builtin_declarations(self):
        from alphadesk.providers.news import AlpacaNews, PolygonNews
        # Verified against live payloads 2026-08-31: polygon has no body
        # field at any tier; alpaca (Benzinga) ships full content.
        assert "full_bodies" not in PolygonNews.capabilities
        assert "full_bodies" in AlpacaNews.capabilities
        for caps in (PolygonNews.capabilities, AlpacaNews.capabilities):
            assert set(caps) <= {"summaries", "full_bodies", "images", "bylines"}

    def test_body_sanitation_strips_markup_and_script(self):
        from alphadesk.providers.news import _strip_html
        text = _strip_html(
            "<p>First.</p><script>alert(1)</script><p>Second &amp; third.</p>")
        assert "First." in text and "Second & third." in text
        assert "<" not in text and "alert" not in text
        # block closers become paragraph breaks, so prose keeps its shape
        assert "\n\n" in text


class TestFinnhubNews:
    """The general firehose, tagged items only — untagged stories cannot back
    a screener that groups by symbol."""

    def _payload(self):
        return [
            {"id": 1, "datetime": 4102444800, "headline": "NVDA ships", "related": "NVDA",
             "summary": "s", "source": "Reuters", "url": "https://x/a", "image": "https://x/i.png"},
            {"id": 2, "datetime": 4102444800, "headline": "Macro musings", "related": "",
             "summary": "s", "source": "Reuters", "url": "https://x/b", "image": ""},
            {"id": 3, "datetime": 100, "headline": "Ancient", "related": "AAPL",
             "summary": "s", "source": "Reuters", "url": "https://x/c", "image": ""},
        ]

    def test_fetch_shapes_filters_and_headers(self, monkeypatch):
        from datetime import datetime, timezone

        from alphadesk.providers import news as news_mod
        seen = {}
        def fake_get(url, headers=None, timeout=20.0):
            seen["url"], seen["headers"] = url, headers or {}
            return self._payload()
        monkeypatch.setattr(news_mod, "_get_json", fake_get)
        arts = news_mod.FinnhubNews(api_key="fk").fetch(
            datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert [a.id for a in arts] == ["finnhub-1"]      # untagged + stale dropped
        assert arts[0].symbols == ["NVDA"]
        assert "token" not in seen["url"]                  # the key travels as a header
        assert seen["headers"].get("X-Finnhub-Token") == "fk"

    def test_missing_key_is_a_provider_error(self):
        import pytest as _pytest

        from alphadesk.providers.news import FinnhubNews
        from alphadesk.providers.base import ProviderError
        with _pytest.raises(ProviderError):
            FinnhubNews(api_key="").fetch(__import__("datetime").datetime.now())


class TestBenzingaNews:
    def test_fetch_parses_stocks_dates_and_bodies(self, monkeypatch):
        from datetime import datetime, timezone

        from alphadesk.providers import news as news_mod
        payload = [[
            {"id": 9, "created": "Fri, 01 Jan 2100 12:00:00 -0400", "title": "Both move",
             "teaser": "<p>lead</p>", "body": "<p>one</p><p>two</p>",
             "url": "https://bz/a", "author": "A. Writer",
             "image": [{"size": "small", "url": "https://bz/i.png"}],
             "stocks": [{"name": "nvda"}, {"name": "AMD"}]},
            {"id": 10, "created": "Thu, 01 Jan 1970 12:00:00 -0400", "title": "Old",
             "teaser": "", "body": "", "url": "https://bz/b", "stocks": [{"name": "T"}]},
        ], []]
        calls = []
        def fake_get(url, headers=None, timeout=20.0):
            calls.append(url)
            return payload[len(calls) - 1]
        monkeypatch.setattr(news_mod, "_get_json", fake_get)
        arts = news_mod.BenzingaNews(api_key="bk").fetch(
            datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert len(calls) == 1                              # desc order: aged-out stops paging
        assert [a.id for a in arts] == ["benzinga-9"]
        assert arts[0].symbols == ["NVDA", "AMD"]
        assert arts[0].body == "one\n\ntwo"
        assert arts[0].summary == "lead"
        assert arts[0].published_at.startswith("2100-01-01T16:00:00")


class TestPolygonPrices:
    """The second prices implementation — partial by design, charts through
    the SAME assembler as the builtin so the data-quality gate applies."""

    def _aggs_payload(self, n=40):
        base = 4102444800000  # 2100-01-01 in ms
        return {"results": [
            {"t": base + i * 60_000, "o": 100 + i, "h": 101 + i,
             "l": 99 + i, "c": 100.5 + i, "v": 1000}
            for i in range(n)
        ]}

    def test_chart_series_uses_the_shared_assembler(self, monkeypatch):
        from alphadesk.providers import prices as prices_mod
        monkeypatch.setattr(prices_mod, "_get_json",
                            lambda url, headers, timeout=20.0: self._aggs_payload())
        out = prices_mod.PolygonPrices(api_key="pk").chart_series("NVDA", range_key="1D")
        assert out is not None
        assert len(out["bars"]) == 40
        for k in ("rsi_9", "macd", "macd_signal", "indicators_reliable",
                  "coverage", "intervals", "interval"):
            assert k in out
        assert out["symbol"] == "NVDA"

    def test_snapshot_backs_context_and_quote(self, monkeypatch):
        from alphadesk.providers import prices as prices_mod
        snap = {"ticker": {"ticker": "NVDA", "todaysChangePerc": 1.4,
                           "lastTrade": {"p": 227.5},
                           "day": {"o": 225.0, "h": 228.0, "l": 224.0, "v": 5_000_000},
                           "prevDay": {"c": 224.4}}}
        monkeypatch.setattr(prices_mod, "_get_json",
                            lambda url, headers, timeout=20.0: snap)
        p = prices_mod.PolygonPrices(api_key="pk")
        ctx = p.context("nvda")
        assert ctx["price"] == 227.5 and ctx["prev_close"] == 224.4
        q = p.quote("nvda")
        assert q["previous_close"] == 224.4 and q["source"] == "Polygon"

    def test_movers_filters_the_informationally_empty(self, monkeypatch):
        from alphadesk.providers import prices as prices_mod
        data = {"tickers": [
            {"ticker": "GOOD", "todaysChangePerc": 9.0,
             "lastTrade": {"p": 50.0}, "day": {"v": 400_000}},
            {"ticker": "PENNY", "todaysChangePerc": 90.0,
             "lastTrade": {"p": 0.4}, "day": {"v": 10_000_000}},
            {"ticker": "THIN", "todaysChangePerc": 30.0,
             "lastTrade": {"p": 60.0}, "day": {"v": 100}},
        ]}
        monkeypatch.setattr(prices_mod, "_get_json",
                            lambda url, headers, timeout=20.0: data)
        out = prices_mod.PolygonPrices(api_key="pk").movers()
        assert [r["symbol"] for r in out["gainers"]] == ["GOOD"]
        assert out["most_active"] == []

    def test_the_absent_surfaces_answer_honestly(self):
        from alphadesk.providers.prices import PolygonPrices
        p = PolygonPrices(api_key="pk")
        assert p.fundamentals("NVDA") is None
        # Not carried answers None, so the data router asks the next vendor.
        assert p.market_tape() is None
        assert p.option_chain("NVDA", "2100-01-01") is None

    def test_missing_key_is_a_provider_error(self, monkeypatch):
        import pytest as _pytest

        from alphadesk.providers.base import ProviderError
        from alphadesk.providers.prices import PolygonPrices
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        with _pytest.raises(ProviderError):
            PolygonPrices(api_key="").chart_series("NVDA")
class TestFinnhubPrices:
    """Polygon's complement: strong readouts, premium-gated candles."""

    def _provider(self, monkeypatch, router):
        from alphadesk.providers import prices as prices_mod
        def fake_get(url, headers, timeout=20.0):
            assert headers.get("X-Finnhub-Token") == "fk"
            assert "token=" not in url
            for frag, payload in router.items():
                if frag in url:
                    return payload() if callable(payload) else payload
            raise AssertionError(f"unrouted url {url}")
        monkeypatch.setattr(prices_mod, "_get_json", fake_get)
        return prices_mod.FinnhubPrices(api_key="fk")

    def test_candles_ride_the_shared_assembler_and_state_the_served_interval(self, monkeypatch):
        base = 4102444800
        candle = {"s": "ok",
                  "t": [base + i * 3600 for i in range(40)],
                  "o": [100 + i for i in range(40)], "h": [101 + i for i in range(40)],
                  "l": [99 + i for i in range(40)], "c": [100.5 + i for i in range(40)],
                  "v": [1000] * 40}
        p = self._provider(monkeypatch, {"/stock/candle": candle})
        out = p.chart_series("NVDA", range_key="3M", interval="4h")
        assert out is not None and len(out["bars"]) == 40
        # 4h isn't a finnhub resolution: hourly served, and SAID.
        assert out["interval"] == "1h" and out["interval_requested"] == "4h"
        assert "rsi_9" in out and "indicators_reliable" in out

    def test_premium_locked_candles_answer_none(self, monkeypatch):
        from alphadesk.providers import prices as prices_mod
        from alphadesk.providers.base import ProviderError
        def deny(url, headers, timeout=20.0):
            raise ProviderError("HTTP 403 Forbidden")
        monkeypatch.setattr(prices_mod, "_get_json", deny)
        assert prices_mod.FinnhubPrices(api_key="fk").chart_series("NVDA") is None

    def test_quote_merges_the_profile(self, monkeypatch):
        p = self._provider(monkeypatch, {
            "/quote": {"c": 227.5, "dp": 1.4, "pc": 224.4, "o": 225.0,
                       "h": 228.0, "l": 224.0},
            "/stock/profile2": {"name": "NVIDIA Corp", "currency": "USD",
                                "exchange": "NASDAQ", "marketCapitalization": 5_500_000},
        })
        q = p.quote("nvda")
        assert q["name"] == "NVIDIA Corp" and q["previous_close"] == 224.4
        assert q["market_cap"] == 5.5e12                # millions, scaled

    def test_earnings_history_becomes_the_report_record(self, monkeypatch):
        p = self._provider(monkeypatch, {"/stock/earnings": [
            {"period": "2026-08-26", "estimate": 2.09, "actual": 2.22, "surprisePercent": 6.2},
            {"period": "2026-05-20", "estimate": 1.77, "actual": 1.87, "surprisePercent": 5.5},
            {"period": "2026-02-25", "estimate": 1.54, "actual": 1.5, "surprisePercent": -2.6},
        ]})
        ctx = p.earnings_context("NVDA")
        assert [r["date"] for r in ctx["report_history"]] == [
            "2026-02-25", "2026-05-20", "2026-08-26"]
        assert ctx["beat_streak"] == "2/3 beats"

    def test_fundamentals_map_percentages_down(self, monkeypatch):
        p = self._provider(monkeypatch, {
            "/stock/metric": {"metric": {"peTTM": 27.5, "netProfitMarginTTM": 48.8,
                                         "revenueGrowthTTMYoy": 62.0,
                                         "marketCapitalization": 5_500_000}},
            "/stock/profile2": {"finnhubIndustry": "Semiconductors"},
        })
        f = p.fundamentals("NVDA")
        assert f["profit_margin"] == 0.488 and f["revenue_growth"] == 0.62
        assert f["industry"] == "Semiconductors"

    def test_missing_key_is_a_provider_error(self, monkeypatch):
        import pytest as _pytest

        from alphadesk.providers.base import ProviderError
        from alphadesk.providers.prices import FinnhubPrices
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        with _pytest.raises(ProviderError):
            FinnhubPrices(api_key="").quote("NVDA")
class TestTiingoNews:
    def test_fetch_filters_and_authenticates_by_header(self, monkeypatch):
        from datetime import datetime, timezone

        from alphadesk.providers import news as news_mod
        seen = {}
        payload = [
            {"id": 7, "title": "NVDA ships", "url": "https://t/a",
             "publishedDate": "2100-01-02T09:00:00Z", "tickers": ["nvda", "amd"],
             "description": "d", "source": "reuters.com"},
            {"id": 8, "title": "Untagged musings", "url": "https://t/b",
             "publishedDate": "2100-01-02T09:00:00Z", "tickers": [],
             "description": "d", "source": "x.com"},
            {"id": 9, "title": "Stale", "url": "https://t/c",
             "publishedDate": "1999-01-01T00:00:00Z", "tickers": ["aapl"],
             "description": "d", "source": "x.com"},
        ]
        def fake_get(url, headers=None, timeout=20.0):
            seen["url"], seen["headers"] = url, headers or {}
            return payload
        monkeypatch.setattr(news_mod, "_get_json", fake_get)
        arts = news_mod.TiingoNews(api_key="tk").fetch(
            datetime(2100, 1, 1, tzinfo=timezone.utc))
        assert [a.id for a in arts] == ["tiingo-7"]
        assert arts[0].symbols == ["NVDA", "AMD"]
        assert seen["headers"].get("Authorization") == "Token tk"
        assert "token=" not in seen["url"]

    def test_missing_key_is_a_provider_error(self, monkeypatch):
        import pytest as _pytest

        from alphadesk.providers.base import ProviderError
        from alphadesk.providers.news import TiingoNews
        monkeypatch.delenv("TIINGO_API_KEY", raising=False)
        with _pytest.raises(ProviderError):
            TiingoNews(api_key="").fetch(__import__("datetime").datetime.now())


class TestAlphaVantageNews:
    def _feed(self):
        return {"feed": [
            {"title": "Both move", "url": "https://av/a",
             "time_published": "21000102T090000",
             "summary": "s", "source": "Zacks", "banner_image": "https://av/i.png",
             "authors": ["A. Writer"],
             "ticker_sentiment": [
                 {"ticker": "NVDA", "relevance_score": "0.9"},
                 {"ticker": "AMD", "relevance_score": "0.4"},
                 {"ticker": "MSFT", "relevance_score": "0.02"},
                 {"ticker": "CRYPTO:BTC", "relevance_score": "0.8"},
             ]},
            {"title": "Barely about anything", "url": "https://av/b",
             "time_published": "21000102T090000", "summary": "s", "source": "Zacks",
             "ticker_sentiment": [{"ticker": "TSLA", "relevance_score": "0.05"}]},
        ]}

    def test_relevance_floor_and_prefixed_tickers(self, monkeypatch):
        from datetime import datetime, timezone

        from alphadesk.providers import news as news_mod
        monkeypatch.setattr(news_mod, "_get_json",
                            lambda url, headers=None, timeout=20.0: self._feed())
        arts = news_mod.AlphaVantageNews(api_key="ak").fetch(
            datetime(2100, 1, 1, tzinfo=timezone.utc))
        assert len(arts) == 1                       # the low-relevance-only item dropped
        assert arts[0].symbols == ["NVDA", "AMD"]   # floor + prefix filters, order by relevance
        assert arts[0].author == "A. Writer"

    def test_a_throttle_note_is_an_error_not_an_empty_feed(self, monkeypatch):
        from datetime import datetime, timezone

        import pytest as _pytest

        from alphadesk.providers import news as news_mod
        from alphadesk.providers.base import ProviderError
        monkeypatch.setattr(
            news_mod, "_get_json",
            lambda url, headers=None, timeout=20.0: {
                "Information": "API rate limit is 25 requests per day"})
        with _pytest.raises(ProviderError, match="refused"):
            news_mod.AlphaVantageNews(api_key="ak").fetch(
                datetime(2100, 1, 1, tzinfo=timezone.utc))

    def test_missing_key_is_a_provider_error(self, monkeypatch):
        import pytest as _pytest

        from alphadesk.providers.base import ProviderError
        from alphadesk.providers.news import AlphaVantageNews
        monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
        with _pytest.raises(ProviderError):
            AlphaVantageNews(api_key="").fetch(__import__("datetime").datetime.now())


class TestMarketauxNews:
    def test_equity_entities_only_ordered_by_match(self, monkeypatch):
        from datetime import datetime, timezone

        from alphadesk.providers import news as news_mod
        payload = {"data": [
            {"uuid": "u1", "title": "Both move", "url": "https://mx/a",
             "published_at": "2100-01-02T09:00:00.000000Z",
             "description": "d", "source": "wire",
             "entities": [
                 {"symbol": "AMD", "type": "equity", "match_score": 10.0},
                 {"symbol": "NVDA", "type": "equity", "match_score": 22.5},
                 {"symbol": "SPX", "type": "index", "match_score": 50.0},
             ]},
            {"uuid": "u2", "title": "Index only", "url": "https://mx/b",
             "published_at": "2100-01-02T09:00:00.000000Z", "description": "d",
             "entities": [{"symbol": "SPX", "type": "index", "match_score": 9.0}]},
        ]}
        seen = {}
        def fake_get(url, headers=None, timeout=20.0):
            seen["url"] = url
            return payload
        monkeypatch.setattr(news_mod, "_get_json", fake_get)
        arts = news_mod.MarketauxNews(api_key="mk").fetch(
            datetime(2100, 1, 1, tzinfo=timezone.utc))
        assert [a.id for a in arts] == ["marketaux-u1"]
        assert arts[0].symbols == ["NVDA", "AMD"]      # match-score order, equities only
        assert "published_after=2100-01-01" in seen["url"]

    def test_missing_key_is_a_provider_error(self, monkeypatch):
        import pytest as _pytest

        from alphadesk.providers.base import ProviderError
        from alphadesk.providers.news import MarketauxNews
        monkeypatch.delenv("MARKETAUX_API_KEY", raising=False)
        with _pytest.raises(ProviderError):
            MarketauxNews(api_key="").fetch(__import__("datetime").datetime.now())


class TestFMPNews:
    def test_single_symbol_items_and_eastern_timestamps(self, monkeypatch):
        from datetime import datetime, timezone

        from alphadesk.providers import news as news_mod
        payload = [
            {"symbol": "NVDA", "publishedDate": "2100-01-02 09:00:00",
             "title": "Ships", "url": "https://fmp/a", "text": "t", "site": "wire",
             "image": "https://fmp/i.png"},
            {"symbol": "AAPL", "publishedDate": "1999-01-01 09:00:00",
             "title": "Stale", "url": "https://fmp/b", "text": "t", "site": "wire"},
            {"symbol": "", "publishedDate": "2100-01-02 09:00:00",
             "title": "Untagged", "url": "https://fmp/c", "text": "t", "site": "wire"},
        ]
        monkeypatch.setattr(news_mod, "_get_json",
                            lambda url, headers=None, timeout=20.0: payload)
        arts = news_mod.FMPNews(api_key="fk").fetch(
            datetime(2100, 1, 1, tzinfo=timezone.utc))
        assert [a.symbols for a in arts] == [["NVDA"]]
        # 09:00 US/Eastern restated in UTC (14:00 in January).
        assert arts[0].published_at.startswith("2100-01-02T14:00:00")

    def test_missing_key_is_a_provider_error(self, monkeypatch):
        import pytest as _pytest

        from alphadesk.providers.base import ProviderError
        from alphadesk.providers.news import FMPNews
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        with _pytest.raises(ProviderError):
            FMPNews(api_key="").fetch(__import__("datetime").datetime.now())


class TestAlphaVantagePrices:
    """The widest free surface behind the harshest budget."""

    def _provider(self, monkeypatch, router):
        from alphadesk.providers import prices as prices_mod
        def fake_get(url, headers, timeout=20.0):
            for frag, payload in router.items():
                if frag in url:
                    return payload
            raise AssertionError(f"unrouted url {url}")
        monkeypatch.setattr(prices_mod, "_get_json", fake_get)
        return prices_mod.AlphaVantagePrices(api_key="ak")

    def test_intraday_stamps_restate_eastern_and_say_the_served_interval(self, monkeypatch):
        rows = {f"2100-01-0{d} 10:{m:02d}:00":
                {"1. open": "100", "2. high": "101", "3. low": "99",
                 "4. close": "100.5", "5. volume": "1000"}
                for d in (1, 2) for m in range(0, 60, 3)}
        p = self._provider(monkeypatch, {
            "TIME_SERIES_INTRADAY": {"Time Series (5min)": rows}})
        out = p.chart_series("NVDA", range_key="1D", interval="2m")
        assert out is not None and len(out["bars"]) == 40
        assert out["interval"] == "5m" and out["interval_requested"] == "2m"
        # 10:00 US/Eastern restated with the offset, not left naive.
        assert out["bars"][0]["t"].endswith("-05:00")

    def test_a_throttle_note_answers_none_not_an_error_page(self, monkeypatch):
        p = self._provider(monkeypatch, {
            "TIME_SERIES_INTRADAY": {"Note": "25 requests per day"}})
        assert p.chart_series("NVDA", range_key="1D") is None

    def test_quote_merges_the_overview(self, monkeypatch):
        p = self._provider(monkeypatch, {
            "GLOBAL_QUOTE": {"Global Quote": {
                "05. price": "227.50", "10. change percent": "1.40%",
                "08. previous close": "224.40", "03. high": "228.00",
                "04. low": "224.00", "06. volume": "5000000"}},
            "OVERVIEW": {"Symbol": "NVDA", "Name": "NVIDIA Corp",
                         "MarketCapitalization": "5500000000000",
                         "PERatio": "27.5", "Currency": "USD"},
        })
        q = p.quote("nvda")
        assert q["price"] == 227.5 and q["change_pct"] == 1.4
        assert q["name"] == "NVIDIA Corp" and q["pe_trailing"] == 27.5

    def test_movers_parse_percent_strings_and_filter(self, monkeypatch):
        p = self._provider(monkeypatch, {"TOP_GAINERS_LOSERS": {
            "top_gainers": [
                {"ticker": "GOOD", "price": "50.0", "change_percentage": "9.1%",
                 "volume": "400000"},
                {"ticker": "PENNY", "price": "0.40", "change_percentage": "90.0%",
                 "volume": "10000000"}],
            "top_losers": [], "most_actively_traded": []}})
        out = p.movers()
        assert [r["symbol"] for r in out["gainers"]] == ["GOOD"]
        assert out["gainers"][0]["change_pct"] == 9.1

    def test_earnings_history_and_streak(self, monkeypatch):
        p = self._provider(monkeypatch, {"function=EARNINGS": {
            "quarterlyEarnings": [
                {"reportedDate": "2100-08-26", "estimatedEPS": "2.09",
                 "reportedEPS": "2.22", "surprisePercentage": "6.2"},
                {"reportedDate": "2100-05-20", "estimatedEPS": "1.77",
                 "reportedEPS": "1.5", "surprisePercentage": "-15.0"},
            ]}})
        ctx = p.earnings_context("NVDA")
        assert [r["date"] for r in ctx["report_history"]] == ["2100-05-20", "2100-08-26"]
        assert ctx["beat_streak"] == "1/2 beats"

    def test_missing_key_is_a_provider_error(self, monkeypatch):
        import pytest as _pytest

        from alphadesk.providers.base import ProviderError
        from alphadesk.providers.prices import AlphaVantagePrices
        monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
        with _pytest.raises(ProviderError):
            AlphaVantagePrices(api_key="").quote("NVDA")
class TestIntervalCatalogue:
    """The interval policy takes the ACTIVE provider's catalogue, so a key
    that carries second bars is offered them and one that does not is not."""

    def test_polygon_catalogue_offers_seconds_on_a_day_and_not_on_a_month(self):
        from alphadesk.ingest import prices as ip
        from alphadesk.providers import prices as prices_mod
        table = prices_mod.PolygonPrices._INTERVALS
        day = ip.available_intervals("1D", table)
        assert day[:3] == ["1s", "5s", "10s"] and "3m" in day and "2h" not in day  # 2h: too few bars in a day
        month = ip.available_intervals("1M", table)
        assert not any(k.endswith("s") for k in month) and "10m" in month and "1d" in month

    def test_resolve_downgrades_within_the_provider_table(self):
        from alphadesk.ingest import prices as ip
        from alphadesk.providers import prices as prices_mod
        table = prices_mod.PolygonPrices._INTERVALS
        assert ip.resolve_interval("1D", "1s", table) == "1s"
        # 1s reaches one day; over a week the next coarser bar that covers
        # five days is 30s — not the builtin table's 1h.
        assert ip.resolve_interval("5D", "1s", table) == "30s"
        # A year of minutes: Polygon's 1m reaches 60 days, 10m reaches 365.
        assert ip.resolve_interval("1Y", "1m", table) == "10m"
        # The builtin table still caps a year of minutes at hourly.
        assert ip.resolve_interval("1Y", "1m") == "1h"

    def test_finnhub_menu_never_offers_a_substitution(self):
        from alphadesk.ingest import prices as ip
        from alphadesk.providers import prices as prices_mod
        table = prices_mod.FinnhubPrices._INTERVALS
        assert "2m" not in table and "4h" not in table
        assert "2m" not in ip.available_intervals("1D", table)

    def test_capabilities_route_and_interval_validation(self, monkeypatch):
        from alphadesk.providers import prices as prices_mod
        from fastapi.testclient import TestClient
        from alphadesk.app import dashboard
        from alphadesk.providers import registry
        poly = prices_mod.PolygonPrices(api_key="pk")
        monkeypatch.setattr(registry, "get_prices", lambda: registry.DataRouter("u", {"polygon": poly}))
        import alphadesk.providers as pkg
        monkeypatch.setattr(pkg, "get_prices", lambda: registry.DataRouter("u", {"polygon": poly}))
        client = TestClient(dashboard.app)
        caps = client.get("/api/chart/capabilities").json()
        assert caps["provider"] == "polygon"
        ids = [x["id"] for x in caps["intervals"]]
        assert ids[0] == "1s" and ids[-1] == "1mo" and ids.index("1m") > ids.index("30s")
        # An interval the ACTIVE provider lacks is refused with the list.
        r = client.get("/api/chart/NVDA?range=1D&interval=7m")
        assert r.status_code == 400 and "polygon" in r.json()["detail"]
