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
        ef.edgar._json_cache.clear()                    # the SEC documents are shared now: one URL, one copy
        from alphadesk.ledger import store              # and kept (2026-10-07): the next answer is a new filing
        with store._lock, store._connect() as conn:
            conn.execute("DELETE FROM sec_documents")
        monkeypatch.setattr(ef.edgar, "cik_for", lambda s: "0000000001")
        monkeypatch.setattr(ef.edgar, "_get", lambda *a, **k: json.dumps(payload).encode())
        return ef._facts("X")

    got = facts({"facts": {"us-gaap": {"a": 1, "b": 2}, "ifrs-full": {"c": 3}}})
    assert got["taxonomy"] == "us-gaap" and set(got["tags"]) == {"a", "b"}

    got = facts({"facts": {"us-gaap": {"a": 1}, "ifrs-full": {"c": 3, "d": 4, "e": 5}}})
    assert got["taxonomy"] == "ifrs-full" and set(got["tags"]) == {"c", "d", "e"}
    ef._cache.clear()


def test_a_full_year_filed_on_a_6_K_is_read():
    """NOVO NORDISK FILES FULL YEARS ON A 6-K (2026-09-29) — it announces
    annual results there before the 20-F lands, twelve of them at 364 and 365
    days. The form was excluded on the claim that a 6-K carries only
    half-years, which is true of Inventiva, TSMC and WEBUY and false of Novo;
    excluding it discarded four years of its history.

    Measured with the form in and out, across seven filers: Novo went from 7
    annual points to 11 and NOT ONE existing value changed anywhere.
    """
    assert "6-K" in ef._FORMS and "6-K/A" in ef._FORMS
    rows = [{"form": "6-K", "start": "2018-01-01", "end": "2018-12-31", "val": 111_780_000_000.0},
            {"form": "6-K", "start": "2018-07-01", "end": "2018-12-31", "val": 56_000_000_000.0}]
    _q, y = ef.series_from_rows(rows)
    # The full year is taken; the half-year is neither a quarter nor a year and
    # lands in no window, which is what made the original claim look true.
    assert y == {"2018-12-31": 111_780_000_000.0}


def test_a_half_year_is_not_mistaken_for_either_window():
    """180 days is not a quarter (80-100) and not a year (350-380). A 6-K that
    carries only half-years adds nothing rather than adding something wrong."""
    rows = [{"form": "6-K", "start": "2024-01-01", "end": "2024-06-30", "val": 9_198_000.0}]
    q, y = ef.series_from_rows(rows)
    assert q == {} and y == {}


def test_a_half_year_gets_its_own_grain():
    """A HALF-YEAR IS NEITHER (2026-09-29). Inventiva, TSMC and WEBUY file
    six-month interim figures on a 6-K -- 180 and 181 days -- which fell
    outside both windows, so those rows contributed nothing at all. Folding
    them into either would be worse than dropping them: a half-year's revenue
    beside a full year's reads as a collapse, beside a quarter's as a
    doubling."""
    rows = [
        {"form": "6-K", "start": "2025-01-01", "end": "2025-06-30", "val": 4_454_000.0},
        {"form": "20-F", "start": "2024-01-01", "end": "2024-12-31", "val": 9_198_000.0},
        {"form": "10-Q", "start": "2025-01-01", "end": "2025-03-31", "val": 1_000.0},
    ]
    q, h, y = ef._series_by_grain(rows)
    assert h == {"2025-06-30": 4_454_000.0}
    assert y == {"2024-12-31": 9_198_000.0}
    # AND Q2 FALLS OUT OF IT. The half-year and the first quarter share a
    # start, so the existing cumulative-difference machinery reads the second
    # quarter as H1 minus Q1 -- 4,454,000 less 1,000. That is the machinery
    # working rather than a leak: a filer reporting both genuinely has told you
    # its second quarter. Inventiva files no 10-Q at all, so it has no Q1 to
    # difference against and lands on the half-year grain, which is what the
    # live data shows.
    assert q == {"2025-03-31": 1_000.0, "2025-06-30": 4_453_000.0}


def test_the_grain_is_picked_by_which_is_fresher_not_by_rule(monkeypatch):
    """MEASURED, and it is why there is no fixed order: Inventiva's newest
    half-year ends 2025-06-30 against an annual 2024-12-31 -- six months
    older -- while WEBUY's annual (2025-12-31) is newer than its half
    (2025-06-30). A rule either way shows one of them stale figures."""
    def series(sym, period="quarterly", **k):
        data = {
            "IVA": {"quarterly": {}, "half": {"2025-06-30": 1.0}, "annual": {"2024-12-31": 2.0}},
            "WBUY": {"quarterly": {}, "half": {"2025-06-30": 1.0}, "annual": {"2025-12-31": 2.0}},
            "NTWK": {"quarterly": {"2026-06-30": 3.0}, "half": {"2025-12-31": 1.0},
                     "annual": {"2026-06-30": 2.0}},
        }[sym][period]
        return {"period": period, "series": ({"revenue": [{"t": t, "v": v} for t, v in data.items()]}
                                             if data else {})}

    monkeypatch.setattr(ef, "fundamentals_series", series)
    assert ef.best_series("IVA")["period"] == "half"        # the half-year is fresher
    assert ef.best_series("WBUY")["period"] == "annual"     # here the year is
    assert ef.best_series("NTWK")["period"] == "quarterly"  # quarters always win


def test_a_filer_with_nothing_at_any_grain_still_answers(monkeypatch):
    monkeypatch.setattr(ef, "fundamentals_series",
                        lambda sym, period="quarterly", **k: {"period": period, "series": {}})
    out = ef.best_series("X")
    assert out["series"] == {} and out["period"] == "quarterly"
