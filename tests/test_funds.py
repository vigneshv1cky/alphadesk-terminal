"""Fund holdings come only from a connected vendor that carries them; the
Finnhub and FMP payloads map into the one shape the fund panels draw."""

import pytest

from alphadesk.ingest import funds
from alphadesk.providers.base import NeedsKey
from alphadesk.providers.company_vendors import FmpPrices


def test_fmp_holdings_map(monkeypatch):
    fmp = FmpPrices(api_key="k")
    payloads = {
        "etf/holdings": [{"asset": "NVDA", "name": "NVIDIA Corp", "weightPercentage": 8.08},
                         {"asset": "AAPL", "name": "Apple Inc", "weightPercentage": 7.03}],
        "etf/info": [{"expenseRatio": 0.0945, "assetsUnderManagement": 5.1e11, "etfCompany": "SPDR", "assetClass": "Equity"}],
        "etf/sector-weightings": [{"sector": "Technology", "weightPercentage": 38.7}],
    }
    monkeypatch.setattr(fmp, "_get", lambda path, **p: payloads[path])
    out = fmp.fund_holdings("spy")
    assert out["holdings"][0] == {"symbol": "NVDA", "name": "NVIDIA Corp", "weight": 8.08}
    assert out["top_weight"] == 15.11 and out["family"] == "SPDR" and out["sectors"][0]["label"] == "Technology"


def test_the_route_needs_a_vendor(vendors):
    vendors()
    with pytest.raises(NeedsKey) as exc:
        funds.fund_profile("SPY")
    assert exc.value.prompt()["surface"] == "fund_holdings"


# Alpha Vantage's ETF_PROFILE, shaped as the documented demo call answered on
# 2026-09-18 (QQQ): every number a string, every weight a FRACTION.
AV_QQQ = {
    "net_assets": "489000000000", "net_expense_ratio": "0.0018", "portfolio_turnover": "n/a",
    "dividend_yield": "0.0041", "inception_date": "1999-03-10", "last_updated": "2026-09-18 00:01 UTC",
    "leveraged": "NO",
    "sectors": [{"sector": "INFORMATION TECHNOLOGY", "weight": "0.569"}],
    "holdings": [{"symbol": "AAPL", "description": "APPLE INC", "weight": "0.0741"},
                 {"symbol": "NVDA", "description": "NVIDIA CORP", "weight": "0.0851"}],
}


def _av(payload):
    from alphadesk.providers.prices import AlphaVantagePrices
    av = AlphaVantagePrices(api_key="k")
    av._query = lambda params: payload
    return av


def test_alpha_vantage_etf_profile_maps_fractions_to_percent():
    out = _av(AV_QQQ).fund_holdings("qqq")
    # Largest first, fractions as percent, no float noise.
    assert out["holdings"][0] == {"symbol": "NVDA", "name": "NVIDIA CORP", "weight": 8.51}
    assert out["top_weight"] == 15.92
    assert out["expense_ratio"] == 0.18 and out["net_assets"] == 489e9
    assert out["turnover"] is None  # "n/a" is not a number
    assert out["sectors"][0] == {"key": "INFORMATION TECHNOLOGY", "label": "Information Technology", "weight": 56.9}
    assert out["as_of"] == "2026-09-18 00:01 UTC" and out["vendor"] == "alphavantage"


def test_a_symbol_that_is_not_an_etf_is_not_answered():
    assert _av({}).fund_holdings("NVDA") is None


def test_a_refused_holdings_list_is_filled_from_alpha_vantage(vendors, monkeypatch):
    # FMP Premium answers the profile and sectors but not the list.
    fmp = FmpPrices(api_key="k")
    monkeypatch.setattr(fmp, "fund_holdings", lambda s: {
        "symbol": s, "quote_type": "ETF", "family": "Invesco", "description": "Tracks the Nasdaq-100",
        "expense_ratio": 0.2, "net_assets": 3.9e11, "holdings": [], "top_weight": None,
        "sectors": [{"key": "Technology", "label": "Technology", "weight": 58.0}],
        "assets": [], "vendor": "fmp", "holdings_needs_key": {"surface": "fund_holdings"}})
    vendors(fmp=fmp, alphavantage=_av(AV_QQQ))
    out = funds.fund_profile("QQQ")
    # FMP's record stays; the list comes from Alpha Vantage and says so.
    assert out["vendor"] == "fmp" and out["family"] == "Invesco" and out["expense_ratio"] == 0.2
    assert out["holdings_vendor"] == "alphavantage" and out["holdings"][0]["symbol"] == "NVDA"
    assert out["holdings_needs_key"] is None
    assert out["sectors"][0]["label"] == "Technology"  # the first answer's sectors are kept


def test_without_a_second_source_the_refusal_still_shows(vendors, monkeypatch):
    fmp = FmpPrices(api_key="k")
    monkeypatch.setattr(fmp, "fund_holdings", lambda s: {
        "symbol": s, "holdings": [], "sectors": [], "vendor": "fmp", "holdings_needs_key": {"surface": "fund_holdings"}})
    vendors(fmp=fmp)
    out = funds.fund_profile("QQQ")
    assert out["holdings"] == [] and out["holdings_needs_key"] == {"surface": "fund_holdings"}
    assert "holdings_vendor" not in out
