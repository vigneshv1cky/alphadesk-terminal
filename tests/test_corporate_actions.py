"""Dividends and splits from the user's vendors: the first with a record
answers, another connected vendor fills the dates it lacks, nothing is
invented, and a refusing vendor costs nothing (2026-09-11; over the
user's own vendors since 2026-09-13)."""


from alphadesk.ingest import corporate_actions as ca
from alphadesk.ingest.prices import split_ratio_parts
from alphadesk.providers import prices as pp
from alphadesk.providers.base import EntitlementError


class _Primary:
    name = "alphavantage"

    def corporate_actions(self, symbol):
        return {"symbol": symbol, "dividends": [
            {"ex_date": "2026-08-10", "amount": 0.27, "currency": None,
             "declaration_date": None, "record_date": None, "payment_date": None},
            {"ex_date": "2026-05-11", "amount": 0.27, "currency": None,
             "declaration_date": None, "record_date": None, "payment_date": None},
        ], "splits": [{"date": "2020-08-31", "from": 1, "to": 4}]}


class _Helper:
    name = "polygon"
    calls = 0

    def corporate_actions(self, symbol):
        type(self).calls += 1
        return {"symbol": symbol, "dividends": [
            {"ex_date": "2026-08-10", "amount": 0.27, "currency": "USD",
             "declaration_date": "2026-07-30", "record_date": "2026-08-10", "payment_date": "2026-08-13"},
        ], "splits": [{"date": "2020-08-31", "from": 1, "to": 4}]}


def test_split_ratio_parts():
    assert split_ratio_parts(4.0) == (1, 4)
    assert split_ratio_parts(0.5) == (2, 1)
    assert split_ratio_parts(1.5) == (2, 3)
    assert split_ratio_parts(0.1) == (10, 1)


def test_primary_alone_leaves_dates_blank(vendors):
    vendors(alphavantage=_Primary())
    out = ca.corporate_actions("AAPL")
    assert out["sources"] == ["alphavantage"]
    assert out["dividends"][0]["payment_date"] is None
    assert out["splits"] == [{"date": "2020-08-31", "from": 1, "to": 4}]


def test_another_vendor_fills_matching_ex_dates_only(vendors):
    # Catalogue order asks polygon first; give it no record so the
    # alphavantage record is primary and polygon is the filler.
    class _Late(_Helper):
        answered = False
        def corporate_actions(self, symbol):
            if not type(self).answered:
                type(self).answered = True
                return None
            return super().corporate_actions(symbol)
    _Helper.calls = 0
    vendors(alphavantage=_Primary(), polygon=_Late())
    out = ca.corporate_actions("AAPL")
    assert out["sources"] == ["alphavantage", "polygon"]
    aug, may = out["dividends"]
    assert (aug["record_date"], aug["payment_date"], aug["declaration_date"]) == (
        "2026-08-10", "2026-08-13", "2026-07-30")
    assert aug["amount"] == 0.27                      # the primary's amount stands
    assert may["payment_date"] is None                # no match, nothing invented


def test_a_refusing_vendor_costs_nothing(vendors):
    class _Gated:
        name = "finnhub"
        def corporate_actions(self, symbol):
            raise EntitlementError("HTTP 403: premium")
    vendors(alphavantage=_Primary(), finnhub=_Gated())
    out = ca.corporate_actions("AAPL")
    assert out["sources"] == ["alphavantage"]
    assert len(out["dividends"]) == 2


def test_no_fill_asked_when_the_primary_already_has_dates(vendors):
    class _NoCall:
        name = "alphavantage"
        def corporate_actions(self, symbol):
            raise AssertionError("should not be asked")
    vendors(polygon=_Helper(), alphavantage=_NoCall())
    out = ca.corporate_actions("AAPL")
    assert out["sources"] == ["polygon"]


def test_alphavantage_parses_none_dates_and_split_factor(monkeypatch):
    av = pp.AlphaVantagePrices(api_key="k")
    payloads = {
        (("AAPL", "DIVIDENDS")): {"data": [
            {"ex_dividend_date": "2026-08-10", "declaration_date": "2026-07-30",
             "record_date": "None", "payment_date": "2026-08-13", "amount": "0.27"}]},
        (("AAPL", "SPLITS")): {"data": [{"effective_date": "2020-08-31", "split_factor": "4.0"},
                                        {"effective_date": "2014-06-09", "split_factor": "7.0"}]},
    }
    monkeypatch.setattr(av, "_series", lambda params, key: payloads[key])
    out = av.corporate_actions("AAPL")
    d = out["dividends"][0]
    assert (d["amount"], d["record_date"], d["payment_date"]) == (0.27, None, "2026-08-13")
    assert out["splits"] == [{"date": "2020-08-31", "from": 1, "to": 4},
                             {"date": "2014-06-09", "from": 1, "to": 7}]


def test_polygon_maps_reference_rows(monkeypatch):
    pg = pp.PolygonPrices(api_key="k")
    def fake_get(url, headers, timeout=20.0):
        assert headers["Authorization"] == "Bearer k"
        if "/dividends" in url:
            return {"results": [{"ex_dividend_date": "2026-08-10", "cash_amount": 0.27, "currency": "USD",
                                 "declaration_date": "2026-07-30", "record_date": "2026-08-10",
                                 "pay_date": "2026-08-13"}]}
        return {"results": [{"execution_date": "2020-08-31", "split_from": 1, "split_to": 4}]}
    monkeypatch.setattr(pp, "_get_json", fake_get)
    out = pg.corporate_actions("aapl")
    assert out["symbol"] == "AAPL"
    assert out["dividends"][0]["payment_date"] == "2026-08-13"
    assert out["splits"] == [{"date": "2020-08-31", "from": 1, "to": 4}]


def test_route_serves_the_merged_record(client, vendors):
    vendors(alphavantage=_Primary())
    r = client.get("/api/corporate-actions/aapl")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AAPL" and len(body["dividends"]) == 2 and body["sources"] == ["alphavantage"]
    vendors()
    assert client.get("/api/corporate-actions/aapl").status_code == 428


def test_declared_and_adjusted_amounts_derive_through_the_split_chain():
    splits = [{"date": "2020-08-31", "from": 1, "to": 4}, {"date": "2014-06-09", "from": 1, "to": 7},
              {"date": "2005-02-28", "from": 1, "to": 2}, {"date": "1987-06-16", "from": 1, "to": 2}]
    rows = [
        {"ex_date": "2026-08-10", "amount": None, "adjusted_amount": 0.27},      # after every split: same number
        {"ex_date": "2014-05-08", "amount": None, "adjusted_amount": 0.1175},    # Yahoo's figure; ×7×4 -> the $3.29 declared before the 7-for-1
        {"ex_date": "1987-05-11", "amount": None, "adjusted_amount": 0.000536},  # ×2×2×7×4 = 112 -> $0.06, the declared 1987 payout
        {"ex_date": "2019-11-07", "amount": 0.77, "adjusted_amount": None},      # a declared figure (Polygon): ÷4
        {"ex_date": "2019-08-09", "amount": 0.77, "adjusted_amount": 0.1925},    # both given (Finnhub): untouched
        {"ex_date": "2018-05-11", "amount": None, "adjusted_amount": None},      # nothing known stays nothing
    ]
    ca.reconcile_amounts(rows, splits)
    assert rows[0]["amount"] == 0.27
    assert rows[1]["amount"] == 3.29
    assert rows[2]["amount"] == 0.06
    assert rows[3]["adjusted_amount"] == 0.1925
    assert rows[4] == {"ex_date": "2019-08-09", "amount": 0.77, "adjusted_amount": 0.1925}
    assert rows[5]["amount"] is None and rows[5]["adjusted_amount"] is None
    assert ca.split_factor_after("2026-08-10", splits) == 1.0
    assert ca.split_factor_after("1987-05-11", splits) == 112.0
    assert ca.split_factor_after("1987-05-11", []) == 1.0                         # no split record: declared == adjusted


def test_the_route_carries_both_amounts(vendors):
    vendors(alphavantage=_Primary())
    out = ca.corporate_actions("AAPL")
    for r in out["dividends"]:
        assert "adjusted_amount" in r and r["amount"] == 0.27 and r["adjusted_amount"] == 0.27
