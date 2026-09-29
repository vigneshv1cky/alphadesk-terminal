"""Reading a foreign private issuer's filings — the IFRS taxonomy, and the
currency it reports in."""
from alphadesk.ingest import edgar_financials as ef


def _units(**by_unit):
    return {"units": {u: [{"form": "20-F", "start": "2024-01-01", "end": "2024-12-31", "val": v}]
                      for u, v in by_unit.items()}}


def test_the_reporting_currency_is_counted_not_assumed():
    """THE ROW COUNT SETTLES IT, and it has to: SAP files 27 EUR rows against
    ONE in USD, so preferring dollars would draw a one-point chart. Measured
    on the four filers this was built against —
        TSMC   TWD 26 / USD 9      SAP     EUR 27 / USD 1
        Alibaba CNY 47 / USD 16    VinFast VND 11 / USD 4
    """
    tags = {"Revenue": {"units": {
        "EUR": [{"val": 1}] * 27,
        "USD": [{"val": 1}] * 1,
    }}}
    assert ef._currency(tags, ["Revenue"]) == "EUR"


def test_a_filer_with_no_usd_at_all_is_not_called_dollars():
    """Novo Nordisk files only DKK and Inventiva only EUR. Assuming USD would
    print kroner behind a dollar sign — off by an order of magnitude and
    stated as something the company never filed."""
    assert ef._currency({"Revenue": _units(DKK=309_064_000_000.0)}, ["Revenue"]) == "DKK"
    assert ef._currency({"Revenue": _units(EUR=9_198_000.0)}, ["Revenue"]) == "EUR"


def test_a_domestic_filer_is_dollars_and_an_empty_one_defaults_to_them():
    assert ef._currency({"Revenues": _units(USD=1.0)}, ["Revenues"]) == "USD"
    assert ef._currency({}, ["Revenues"]) == "USD"
    assert ef._currency({"Revenues": {"units": {}}}, ["Revenues"]) == "USD"


def test_a_per_share_unit_is_read_as_its_currency():
    """EPS is filed under "<currency>/shares" — DKK/shares, TWD/shares. The
    currency is the part before the slash, not a separate unit."""
    tags = {"Revenue": {"units": {"DKK/shares": [{"val": 1}] * 5}}}
    assert ef._currency(tags, ["Revenue"]) == "DKK"


def test_the_ifrs_concepts_cover_every_metric_the_panels_show():
    """Checked against TSMC, SAP, Novo Nordisk and Inventiva before the map was
    written. A metric with no IFRS concept would silently vanish for every
    foreign filer, which is the failure this whole reader exists to end."""
    money = {"revenue", "gross_profit", "operating_income", "net_income",
             "diluted_eps", "ocf", "capex"}
    assert money <= set(ef.IFRS_TAGS), money - set(ef.IFRS_TAGS)
    # Operating income is the IFRS statement's own subtotal, not an alias of
    # the US-GAAP concept: the two are not defined identically.
    assert ef.IFRS_TAGS["operating_income"][0] == "ProfitLossFromOperatingActivities"
    assert ef.IFRS_TAGS["net_income"][0] == "ProfitLoss"


def test_the_larger_taxonomy_wins_and_is_named(monkeypatch):
    """A filer tags one taxonomy or the other, never a useful mix. The answer
    says which so the concepts can be matched to it — Alibaba and VinFast file
    US-GAAP despite being foreign, and must not be read as IFRS."""
    import json

    def facts(payload):
        ef._cache.clear()
        monkeypatch.setattr(ef.edgar, "cik_for", lambda s: "0000000001")
        monkeypatch.setattr(ef.edgar, "_get", lambda *a, **k: json.dumps(payload).encode())
        return ef._facts("X")

    got = facts({"facts": {"us-gaap": {"a": 1, "b": 2}, "ifrs-full": {"c": 3}}})
    assert got["taxonomy"] == "us-gaap" and set(got["tags"]) == {"a", "b"}

    got = facts({"facts": {"us-gaap": {"a": 1}, "ifrs-full": {"c": 3, "d": 4, "e": 5}}})
    assert got["taxonomy"] == "ifrs-full" and set(got["tags"]) == {"c", "d", "e"}
    ef._cache.clear()
