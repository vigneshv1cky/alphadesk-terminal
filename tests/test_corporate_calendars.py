"""Market-wide dividends, splits and IPOs (2026-09-14), from FMP's corporate
calendars on the user's key."""

from datetime import datetime, timedelta, timezone

import pytest

from alphadesk.ingest import corporate_calendars as cc
from alphadesk.ingest import edgar
from alphadesk.providers.base import NeedsKey
from alphadesk.providers.company_vendors import FmpPrices


class _Fmp:
    name = "fmp"
    def dividend_calendar(self, s, e):
        return [{"symbol": "SMALL", "ex_date": "2026-09-15", "amount": 0.1, "yield_pct": 4.2, "frequency": "Quarterly",
                 "record_date": "2026-09-15", "payment_date": "2026-10-01", "declaration_date": None, "adjusted_amount": 0.1},
                {"symbol": "BIG", "ex_date": "2026-09-15", "amount": 0.27, "yield_pct": 0.4, "frequency": "Quarterly",
                 "record_date": "2026-09-15", "payment_date": "2026-09-18", "declaration_date": "2026-07-30", "adjusted_amount": 0.27},
                {"symbol": "CP.TO", "ex_date": "2026-09-15", "amount": 0.2, "yield_pct": 0.8, "frequency": "Quarterly",
                 "record_date": None, "payment_date": None, "declaration_date": None, "adjusted_amount": 0.2},
                {"symbol": "EARLY", "ex_date": "2026-09-01", "amount": 1.0, "yield_pct": 1.0, "frequency": "Annual",
                 "record_date": None, "payment_date": None, "declaration_date": None, "adjusted_amount": 1.0}]
    def split_calendar(self, s, e):
        return [{"symbol": "FRSAF", "date": "2026-09-25", "to": 1.0, "from": 20.0, "kind": "stock-split"},
                {"symbol": "NVDA", "date": "2026-09-16", "to": 10.0, "from": 1.0, "kind": "stock-split"},
                {"symbol": "X.L", "date": "2026-09-16", "to": 2.0, "from": 1.0, "kind": "stock-split"}]
    def ipo_calendar(self, s, e):
        return [{"symbol": "OIG", "date": "2026-09-18", "company": "Orbital Infrastructure Group, Inc.", "exchange": "NASDAQ",
                 "status": "Expected", "shares": 20_000_000.0, "price_low": 15.0, "price_high": 17.0, "market_cap": None},
                {"symbol": None, "date": "2026-09-17", "company": "Unpriced Co", "exchange": "NYSE",
                 "status": "Expected", "shares": None, "price_low": None, "price_high": None, "market_cap": None}]


class _Bars:
    name = "alpaca"
    def daily_history(self, symbols, sessions=21):
        t0 = datetime(2026, 8, 12, tzinfo=timezone.utc)
        mk = lambda px, vol: [{"ts": t0 + timedelta(days=i), "close": px + (i % 2) * 0.5, "volume": vol} for i in range(21)]  # noqa: E731
        return {"BIG": mk(300, 50_000_000), "SMALL": mk(10, 20_000)}


def test_dividends_keep_sec_filers_in_the_window_most_traded_first(vendors, monkeypatch):
    vendors(fmp=_Fmp(), alpaca=_Bars())
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"BIG": "1", "SMALL": "2", "EARLY": "3"})
    monkeypatch.setattr(edgar, "company_title", lambda s: {"BIG": "Big Corp", "SMALL": "Small Co"}.get(s))
    got = cc.dividends("2026-09-14", "2026-09-20")
    assert [r["symbol"] for r in got["rows"]] == ["BIG", "SMALL"]          # CP.TO not an SEC filer; EARLY outside
    big, small = got["rows"]
    assert big["company_name"] == "Big Corp" and big["liquidity"] > 1e9 and big["low_liquidity"] is False
    assert small["low_liquidity"] is True and small["yield_pct"] == 4.2 and got["source"] == "fmp"


def test_dividends_list_the_largest_company_first_and_those_without_a_value_after(vendors, monkeypatch):
    class _FmpCaps(_Fmp):
        def market_caps(self, symbols):
            return {"SMALL": 9e11}                                      # a big company that trades little
    vendors(fmp=_FmpCaps(), alpaca=_Bars())
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"BIG": "1", "SMALL": "2", "EARLY": "3"})
    monkeypatch.setattr(edgar, "company_title", lambda s: s)
    rows = cc.dividends("2026-09-14", "2026-09-20")["rows"]
    assert [(r["symbol"], r["market_cap"]) for r in rows] == [("SMALL", 9e11), ("BIG", None)]


def test_splits_mark_reverse_and_drop_suffixed_listings(vendors, monkeypatch):
    vendors(fmp=_Fmp())
    monkeypatch.setattr(edgar, "company_title", lambda s: None)
    rows = cc.splits("2026-09-14", "2026-09-27")["rows"]
    assert [(r["symbol"], r["reverse"]) for r in rows] == [("NVDA", False), ("FRSAF", True)]


def test_ipos_carry_the_deal_size_at_the_middle_of_the_range(vendors):
    vendors(fmp=_Fmp())
    rows = cc.ipos("2026-09-14", "2026-09-20")["rows"]
    assert [r["company"] for r in rows] == ["Unpriced Co", "Orbital Infrastructure Group, Inc."]
    assert rows[0]["deal_size"] is None and rows[1]["deal_size"] == 320_000_000


def test_no_calendar_vendor_is_a_key_prompt_and_the_route_says_so(vendors, client):
    vendors(alpaca=_Bars())
    with pytest.raises(NeedsKey) as exc:
        cc.dividends()
    assert exc.value.prompt()["vendors"][0]["name"] == "fmp"
    assert client.get("/api/calendars/ipos").status_code == 428
    assert client.get("/api/calendars/mergers").status_code == 404


def test_fmp_adapter_reads_the_measured_shapes():
    f = FmpPrices(api_key="k")
    data = {
        "dividends-calendar": [{"symbol": "CP", "date": "2026-09-25", "recordDate": "2026-09-25", "paymentDate": "2026-10-26",
                                "declarationDate": "2026-07-29", "adjDividend": 0.19368, "dividend": 0.19368,
                                "yield": 0.7992603384511935, "frequency": "Quarterly"}],
        "splits-calendar": [{"symbol": "FRSAF", "date": "2026-09-25", "numerator": 1, "denominator": 20, "splitType": "stock-split"}],
        "ipos-calendar": [{"symbol": "OIG", "date": "2026-09-18", "daa": "2026-09-18T04:00:00.000Z",
                           "company": "Orbital Infrastructure Group, Inc.", "exchange": "NASDAQ", "actions": "Expected",
                           "shares": 20000000, "priceRange": "15.00 - 17.00", "marketCap": None}],
    }
    f._get = lambda path, **p: data[path]
    d = f.dividend_calendar("2026-09-14", "2026-09-27")[0]
    assert d["ex_date"] == "2026-09-25" and d["payment_date"] == "2026-10-26" and round(d["yield_pct"], 2) == 0.8
    s = f.split_calendar("2026-09-14", "2026-09-27")[0]
    assert (s["to"], s["from"]) == (1.0, 20.0)
    i = f.ipo_calendar("2026-09-14", "2026-09-27")[0]
    assert (i["price_low"], i["price_high"], i["status"]) == (15.0, 17.0, "Expected")


class _AlpacaSplits:
    name = "alpaca"
    def split_calendar(self, s, e):
        return [{"symbol": "NVDA", "date": "2026-09-15", "to": 10.0, "from": 1.0, "kind": "forward"},
                {"symbol": "CCUP", "date": "2026-09-16", "to": 1.0, "from": 10.0, "kind": "reverse"}]


def test_a_split_two_vendors_list_is_corroborated_on_the_brokers_date_and_one_vendor_alone_is_not(vendors, monkeypatch):
    vendors(fmp=_Fmp(), alpaca=_AlpacaSplits())
    monkeypatch.setattr(edgar, "company_title", lambda s: None)
    got = cc.splits("2026-09-14", "2026-09-27")
    by = {r["symbol"]: r for r in got["rows"]}
    assert got["vendors"] == ["fmp", "alpaca"]
    assert by["NVDA"]["corroborated"] is True and by["NVDA"]["sources"] == ["fmp", "alpaca"]
    assert by["NVDA"]["date"] == "2026-09-15" and by["NVDA"]["vendor_dates"] == {"fmp": "2026-09-16", "alpaca": "2026-09-15"}
    assert by["FRSAF"]["corroborated"] is False and by["CCUP"]["corroborated"] is False and by["CCUP"]["sources"] == ["alpaca"]


def test_corroboration_needs_the_same_ratio_and_one_vendor_cannot_be_checked():
    one = cc.corroborate_splits([("fmp", [{"symbol": "MGN", "date": "2026-09-17", "to": 1.0, "from": 30.0}])])
    assert one[0]["corroborated"] is None
    two = cc.corroborate_splits([("fmp", [{"symbol": "MGN", "date": "2026-09-08", "to": 1.0, "from": 30.0}]),
                                 ("alpaca", [{"symbol": "MGN", "date": "2026-09-08", "to": 1.0, "from": 40.0}])])
    assert [r["corroborated"] for r in two] == [False, False]
    far = cc.corroborate_splits([("fmp", [{"symbol": "A", "date": "2026-09-01", "to": 2.0, "from": 1.0}]),
                                 ("alpaca", [{"symbol": "A", "date": "2026-09-08", "to": 2.0, "from": 1.0}])])
    assert len(far) == 2
    dup = cc.corroborate_splits([("fmp", [{"symbol": "SBTU", "date": "2026-08-24", "to": 1.0, "from": 10.0},
                                          {"symbol": "SBTU", "date": "2026-08-25", "to": 1.0, "from": 10.0}]),
                                 ("alpaca", [{"symbol": "SBTU", "date": "2026-08-24", "to": 1.0, "from": 10.0}])])
    assert [(r["date"], r["corroborated"]) for r in dup] == [("2026-08-24", True)]


def test_alpaca_split_feed_pages_drops_cusips_and_writes_class_shares_the_sec_way(monkeypatch):
    from alphadesk.providers import prices
    from alphadesk.providers.alpaca import AlpacaPrices
    pages = [
        {"corporate_actions": {"forward_splits": [{"symbol": "BRK.B", "ex_date": "2026-09-15", "new_rate": 2, "old_rate": 1}],
                               "reverse_splits": [{"symbol": "09175M606", "ex_date": "2026-09-15", "new_rate": 1, "old_rate": 5},
                                                  {"symbol": "NBGAX", "ex_date": "2026-09-15", "new_rate": 9.623, "old_rate": 10},
                                                  {"symbol": "OUT", "ex_date": "2026-10-30", "new_rate": 1, "old_rate": 5}]},
         "next_page_token": "p2"},
        {"corporate_actions": {"reverse_splits": [{"symbol": "CCUP", "ex_date": "2026-09-16", "new_rate": 1, "old_rate": 10}]},
         "next_page_token": None},
    ]
    seen = []

    def fake(url, headers, timeout=20.0):
        seen.append(url)
        assert headers["APCA-API-KEY-ID"] == "key-123" and "key-123" not in url
        return pages[len(seen) - 1]
    monkeypatch.setattr(prices, "_get_json", fake)
    rows = AlpacaPrices(api_key="key-123", api_secret="s").split_calendar("2026-09-14", "2026-09-20")
    assert rows == [{"symbol": "BRK-B", "date": "2026-09-15", "to": 2.0, "from": 1.0, "kind": "forward"},
                    {"symbol": "CCUP", "date": "2026-09-16", "to": 1.0, "from": 10.0, "kind": "reverse"}]
    assert "start=2026-09-07" in seen[0] and "page_token=p2" in seen[1]


def test_ipo_rows_say_what_kind_of_listing_they_are():
    assert cc.ipo_kind("Latigo Biotherapeutics Inc.") == "company"
    assert cc.ipo_kind("Pinnacle Acquisition Corp") == "blank_check"
    assert cc.ipo_kind("JAB Acquisition Corp I Rights") == "blank_check"
    assert cc.ipo_kind("Gores Holdings XI, Inc. Class A Ordinary Shares") == "blank_check"
    assert cc.ipo_kind("Roundhill Neocloud ETF") == "fund"
    assert cc.ipo_kind("Robinhood Ventures Fund II") == "fund"
    assert cc.ipo_kind("Adamas Trust, Inc. 9.600% Senior Notes due 2031") == "other_security"
    assert cc.ipo_kind("Eos Energy Enterprises, Inc. Warrant") == "other_security"
    assert cc.ipo_kind("Pelican Acquisition Ii Corp.") == "blank_check"
    assert cc.ipo_kind("Jones Ventures Intl Acquisition1") == "blank_check"
    assert cc.ipo_kind("Cartesian Growth Corp. Iv") == "blank_check"
    assert cc.ipo_kind("B&R Technology Merger Corp. Class A") == "blank_check"
    assert cc.ipo_kind("Direxion Daily CSI 300 China A Share Bear 1X Shares") == "fund"
    assert cc.ipo_kind("Charter Communications, Inc. Series A Cumulative Redeemable Preferred Stock") == "other_security"
    assert cc.ipo_kind("QNB Corp.") == "company" and cc.ipo_kind("Resolution Minerals Ltd. Sponsored ADR") == "company"
    assert cc.ipo_kind(None) == "company"
    assert cc._bar_aliases({"symbol": "OCLTU", "exchange": "NASDAQ"}) == ["OCLTU"]


def test_a_past_listing_is_marked_from_its_first_trade_and_nyse_units_are_found_under_their_suffix():
    d = lambda s: {"ts": datetime.fromisoformat(s + "T04:00:00+00:00"), "close": 10.0, "volume": 1}  # noqa: E731
    rows = [{"symbol": "LTGO", "date": "2026-08-07"}, {"symbol": "PNAQU", "date": "2026-08-07", "exchange": "NYSE"},
            {"symbol": "LEDRU", "date": "2026-08-11"}, {"symbol": "NXH", "date": "2026-08-17"},
            {"symbol": "TRBG", "date": "2026-08-31"}, {"symbol": "OBX", "date": "2026-09-20"}, {"symbol": None, "date": "2026-08-01"}]
    bars = {"LTGO": [d("2026-08-07"), d("2026-08-08")], "PNAQ-U": [d("2026-08-07")],
            "NXH": [d("2026-06-01"), d("2026-08-17")], "TRBG": [d("2026-09-03")], "OBX": [d("2026-09-01")]}
    cc.mark_listings(rows, bars, "2026-09-14")
    got = [(r["symbol"], r["listing"], r["first_trade"]) for r in rows]
    assert got == [("LTGO", "listed", "2026-08-07"), ("PNAQU", "listed", "2026-08-07"), ("LEDRU", "no_trades", None),
                   ("NXH", "already_trading", None), ("TRBG", "listed", "2026-09-03"), ("OBX", None, None), (None, None, None)]


def test_ipos_carry_kind_and_listing_when_a_chart_vendor_answers(vendors, monkeypatch):
    class _Bars2:
        name = "alpaca"
        def daily_history(self, symbols, sessions=21):
            assert "OIG" in symbols and sessions >= 14
            return {"OIG": [{"ts": datetime(2026, 9, 18, 13, tzinfo=timezone.utc), "close": 16.0, "volume": 1}]}
    from alphadesk import config
    monkeypatch.setattr(config, "now_et", lambda: datetime(2026, 9, 21, 12, tzinfo=timezone.utc))
    vendors(fmp=_Fmp(), alpaca=_Bars2())
    got = cc.ipos("2026-09-14", "2026-09-20")
    by = {r["company"]: r for r in got["rows"]}
    assert got["checked"] is True and got["source"] == "fmp"
    assert by["Orbital Infrastructure Group, Inc."]["listing"] == "listed" and by["Orbital Infrastructure Group, Inc."]["kind"] == "company"
    assert by["Unpriced Co"]["listing"] is None                    # no symbol to check
    vendors(fmp=_Fmp())
    assert cc.ipos("2026-09-14", "2026-09-20")["checked"] is False
    monkeypatch.setattr(config, "now_et", lambda: datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
    assert cc.ipos("2026-09-14", "2026-09-20")["checked"] is True           # nothing has passed yet
