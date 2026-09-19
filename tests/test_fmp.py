"""FMP on a Premium key, as measured 2026-09-14: the calls AlphaDesk makes
answer except etf/holdings (402 Restricted Endpoint, an Ultimate dataset);
analyst-estimates lists quarters newest first reaching two years ahead."""

from datetime import date

from alphadesk.providers.base import EntitlementError
from alphadesk.providers.company_vendors import FmpPrices


def _fmp(responses):
    f = FmpPrices(api_key="k")

    def fake(path, **params):
        v = responses.get(path)
        if isinstance(v, Exception):
            raise v
        return v
    f._get = fake
    return f


def test_a_plan_without_holdings_still_returns_the_fund_profile_and_sectors():
    f = _fmp({"etf/holdings": EntitlementError("HTTP 402: Restricted Endpoint"),
              "etf/info": [{"symbol": "SPY", "assetClass": "Equity", "etfCompany": "SPDR", "expenseRatio": 0.09,
                            "assetsUnderManagement": 799371670000}],
              "etf/sector-weightings": [{"symbol": "SPY", "sector": "Technology", "weightPercentage": 33.1}]})
    got = f.fund_holdings("spy")
    assert got["holdings"] == [] and got["top_weight"] is None
    assert got["family"] == "SPDR" and got["expense_ratio"] == 0.09 and got["sectors"][0]["weight"] == 33.1
    assert got["holdings_needs_key"]["surface"] == "fund_holdings"
    assert got["holdings_needs_key"]["refused"] == ["Financial Modeling Prep"]


def test_a_stock_is_not_a_fund_even_when_holdings_are_refused():
    f = _fmp({"etf/holdings": EntitlementError("HTTP 402"), "etf/info": [], "etf/sector-weightings": []})
    assert f.fund_holdings("AAPL") is None


def test_estimates_start_at_the_current_quarter(monkeypatch):
    import alphadesk.providers.company_vendors as cv

    class _D(cv.date):
        @classmethod
        def today(cls):
            return cv.date(2026, 9, 14)
    monkeypatch.setattr(cv, "date", _D)
    quarters = ["2028-09-27", "2028-06-27", "2028-03-27", "2027-12-27", "2027-09-27", "2027-06-27",
                "2027-03-27", "2026-12-27", "2026-09-27", "2026-06-27", "2026-03-28"]
    f = _fmp({"analyst-estimates": [{"date": d, "epsAvg": 1.0, "numAnalystsEps": 20} for d in quarters]})
    got = f.earnings_insights("AAPL")
    assert [p["period"] for p in got["periods"]] == ["2026-09-27", "2026-12-27", "2027-03-27", "2027-06-27"]
    assert got["periods"][0]["label"] == "Current quarter"


def test_key_stats_carry_shares_and_float():
    f = _fmp({"profile": [{"symbol": "AAPL", "companyName": "Apple Inc.", "range": "235.03-344.57", "marketCap": 4.9e12}],
              "key-metrics-ttm": [{"enterpriseValueTTM": 4.92e12}], "ratios-ttm": [{"priceToEarningsRatioTTM": 37.9}],
              "shares-float": [{"outstandingShares": 14.7e9, "floatShares": 14.6e9}]})
    got = f.key_stats("AAPL")
    assert got["shares_outstanding"] == 14.7e9 and got["float_shares"] == 14.6e9
    assert got["week52_low"] == 235.03 and got["trailing_pe"] == 37.9


# ── rating changes joined to the targets published with them ──────────────
#
# FMP keeps the two apart, and names a firm differently in each ("Truist
# Securities" grading, "Truist Financial" on the target). The names below
# are the ones its records carried for NVDA, AAPL, TSLA, JPM and CRWD on
# 2026-09-15; the join matched 23 of NVDA's 40 changes, 22 of JPM's.

def _target(day, firm, value, title="NVIDIA price target raised", adj=None):
    return {"publishedDate": f"{day}T13:00:00.000Z", "analystCompany": firm,
            "priceTarget": value, "adjPriceTarget": adj if adj is not None else value,
            "newsTitle": title}


def test_a_firm_named_differently_in_each_record_still_matches():
    from alphadesk.providers.company_vendors import firm_key
    for grading, target in [("Truist Securities", "Truist Financial"), ("JP Morgan", "J.P. Morgan"),
                            ("Keybanc", "KeyBanc"), ("DA Davidson", "D.A. Davidson"),
                            ("Mizuho", "Mizuho Securities"), ("Baird", "Robert W. Baird"),
                            ("B of A Securities", "Bank of America Securities"),
                            ("Evercore ISI Group", "Evercore ISI"), ("Stifel", "Stifel Nicolaus")]:
        assert firm_key(grading) == firm_key(target), grading


def test_a_change_takes_its_firms_target_and_the_one_before_it():
    f = _fmp({"grades": [{"date": "2026-08-27", "gradingCompany": "RBC Capital", "newGrade": "Outperform",
                          "previousGrade": "Outperform", "action": "maintain"}],
              "price-target-news": [_target("2026-08-27", "RBC Capital", 330), _target("2026-05-21", "RBC Capital", 300)]})
    row = f.rating_changes("NVDA")[0]
    assert (row["prior_target"], row["target"], row["target_action"]) == (300, 330, "raised")


def test_a_target_published_days_from_the_change_is_not_its_own():
    f = _fmp({"grades": [{"date": "2026-09-04", "gradingCompany": "Needham", "newGrade": "Buy", "action": "maintain"}],
              "price-target-news": [_target("2026-08-27", "Needham", 300)]})
    assert f.rating_changes("NVDA")[0]["target"] is None


def test_a_target_filed_under_the_wrong_firm_is_dropped():
    """AAPL's 2026-03-04 "Jefferies 330" carried an Evercore ISI headline;
    it would otherwise have become Jefferies' prior target."""
    f = _fmp({"grades": [{"date": "2026-08-10", "gradingCompany": "Jefferies", "newGrade": "Underperform",
                          "action": "downgrade"}],
              "price-target-news": [
                  _target("2026-08-10", "Jefferies", 263.66, "Apple downgraded to Underperform at Jefferies"),
                  _target("2026-03-04", "Jefferies", 330, "Evercore ISI Reiterates Outperform Rating on Apple"),
                  _target("2026-01-26", "Jefferies", 276.47, "Apple price target lowered at Jefferies"),
                  _target("2026-03-04", "Evercore ISI", 320, "Evercore ISI Reiterates Outperform Rating on Apple")]})
    row = f.rating_changes("AAPL")[0]
    assert (row["prior_target"], row["target"]) == (276.47, 263.66)


def test_the_company_covered_is_not_read_as_a_mislabelled_firm():
    """Every JPM headline names JPMorgan, which is also a research firm."""
    f = _fmp({"grades": [{"date": "2026-08-14", "gradingCompany": "Wells Fargo", "newGrade": "Overweight",
                          "action": "maintain"}],
              "price-target-news": [_target("2026-08-14", "Wells Fargo", 390, "JPMorgan price target raised at Wells Fargo"),
                                    _target("2026-07-06", "Wells Fargo", 360, "JPMorgan price target raised at Wells Fargo"),
                                    _target("2026-07-15", "Barclays", 420, "JPMorgan price target raised at Barclays")]})
    row = f.rating_changes("JPM")[0]
    assert (row["prior_target"], row["target"], row["target_action"]) == (360, 390, "raised")


def test_a_prior_target_from_before_a_split_is_the_adjusted_one():
    """CRWD's June targets were set on pre-split shares: $730 is $182.50 now."""
    f = _fmp({"grades": [{"date": "2026-09-04", "gradingCompany": "Roth Capital", "newGrade": "Buy", "action": "maintain"}],
              "price-target-news": [_target("2026-09-04", "Roth Capital", 220, "CrowdStrike PT raised at Roth"),
                                    _target("2026-06-04", "Roth Capital", 880, "CrowdStrike PT raised at Roth", adj=220)]})
    row = f.rating_changes("CRWD")[0]
    assert (row["prior_target"], row["target_action"]) == (220, "maintained")


def test_changes_survive_a_plan_that_refuses_the_target_record():
    f = _fmp({"grades": [{"date": "2026-08-27", "gradingCompany": "RBC Capital", "newGrade": "Outperform", "action": "maintain"}],
              "price-target-news": EntitlementError("HTTP 402")})
    assert f.rating_changes("NVDA")[0]["target"] is None


def test_the_target_count_comes_from_the_summary():
    f = _fmp({"price-target-consensus": [{"targetHigh": 515, "targetLow": 270, "targetConsensus": 345.21, "targetMedian": 322.5}],
              "price-target-summary": [{"lastMonthCount": 22, "lastMonthAvgPriceTarget": 341.95, "lastQuarterCount": 23}]})
    got = f.price_targets("NVDA")
    assert got["published_month"] == 22 and got["published_quarter"] == 23 and got["analysts"] is None


def test_a_prior_target_carries_the_day_it_was_set():
    """It can be months before the change it is compared with: NVDA's RBC
    target of 2026-08-27 was measured against one from 2026-05-21."""
    f = _fmp({"grades": [{"date": "2026-08-27", "gradingCompany": "RBC Capital", "newGrade": "Outperform", "action": "maintain"}],
              "price-target-news": [_target("2026-08-27", "RBC Capital", 330), _target("2026-05-21", "RBC Capital", 300)]})
    assert f.rating_changes("NVDA")[0]["prior_target_date"] == "2026-05-21"


def test_the_changes_kept_reach_past_forty():
    rows = [{"date": f"2026-{m:02d}-{d:02d}", "gradingCompany": "UBS", "newGrade": "Buy", "action": "maintain"}
            for m in range(1, 13) for d in range(1, 11)]
    f = _fmp({"grades": rows, "price-target-news": []})
    assert len(f.rating_changes("NVDA")) == 100


def test_the_recent_average_comes_with_its_window():
    f = _fmp({"price-target-consensus": [{"targetHigh": 515, "targetLow": 270, "targetConsensus": 345.21, "targetMedian": 322.5}],
              "price-target-summary": [{"lastMonthCount": 22, "lastMonthAvgPriceTarget": 341.95,
                                        "lastQuarterCount": 23, "lastQuarterAvgPriceTarget": 341.43}]})
    got = f.price_targets("NVDA")
    assert (got["recent_mean"], got["recent_window"]) == (341.95, "month")


def test_a_quiet_month_falls_back_to_the_quarter():
    f = _fmp({"price-target-consensus": [{"targetHigh": 100, "targetLow": 60, "targetConsensus": 80, "targetMedian": 78}],
              "price-target-summary": [{"lastMonthCount": 0, "lastQuarterCount": 4, "lastQuarterAvgPriceTarget": 82.5}]})
    got = f.price_targets("ENTA")
    assert (got["published_month"], got["recent_mean"], got["recent_window"]) == (None, 82.5, "quarter")


def test_the_ratings_history_is_the_monthly_record():
    """FMP carries 24 monthly snapshots on NVDA; Finnhub's free plan four."""
    hist = [{"date": f"2026-{m:02d}-01", "analystRatingsStrongBuy": m, "analystRatingsBuy": 40,
             "analystRatingsHold": 2, "analystRatingsSell": 1, "analystRatingsStrongSell": 0} for m in range(1, 10)]
    f = _fmp({"grades-consensus": [{"strongBuy": 2, "buy": 58, "hold": 16, "sell": 3, "strongSell": 0}],
              "grades-historical": hist})
    got = f.analyst_ratings("NVDA")
    assert [d["period"] for d in got["distribution"][:3]] == ["0m", "-1m", "-2m"]
    assert got["distribution"][0]["as_of"] == "2026-09-01"
    # One record drives both: FMP's live consensus sorts the same analysts
    # into different buckets (2/58/16/3 against 10/49/2/1 on 2026-09-15),
    # so taking the headline from one and the bars from the other would
    # draw a collapse in conviction that never happened.
    assert got["distribution"][0]["strong_buy"] == 9 and got["distribution"][0]["buy"] == 40
    assert got["recommendation"]["analysts"] == 52


def test_without_a_history_the_current_counts_still_show():
    f = _fmp({"grades-consensus": [{"strongBuy": 9, "buy": 40, "hold": 2, "sell": 1, "strongSell": 0}],
              "grades-historical": EntitlementError("HTTP 402")})
    got = f.analyst_ratings("NVDA")
    assert len(got["distribution"]) == 1 and got["distribution"][0]["buy"] == 40
    assert got["distribution"][0]["period"] == "0m"


def test_short_interest_names_only_a_vendor_that_carries_it():
    """FMP's stable API has no short-interest record (404, 2026-09-15)."""
    from alphadesk.providers.catalogue import prompt
    assert [v["name"] for v in prompt("short_interest")["vendors"]] == ["finnhub"]


def test_the_ratings_mix_asks_the_paid_vendor_first():
    """FMP carries two years of monthly counts, Finnhub's free plan four
    months, so a reader with both gets the history (2026-09-15)."""
    from alphadesk.providers.catalogue import SURFACES
    order = [v for v, _ in SURFACES["analyst_ratings"].vendors]
    assert order[0] == "fmp" and "finnhub" in order


def test_the_eps_chart_is_dated_by_the_day_each_report_was_made():
    """Finnhub dates the same reports by a CALENDAR quarter end — NVIDIA's
    quarter ended 2026-07-26, was reported 2026-08-26, and reads 2026-09-30
    there, a period that has not ended (2026-09-15). The figures agree; the
    dating did not, and two panels on one page disagreed."""
    f = _fmp({"earnings": [
        {"date": "2026-11-18", "epsEstimated": 2.47, "epsActual": None},
        {"date": "2026-08-26", "epsEstimated": 2.09, "epsActual": 2.22},
        {"date": "2026-05-20", "epsEstimated": 1.76, "epsActual": 1.87},
        {"date": "2026-02-25", "epsEstimated": 1.54, "epsActual": 1.62},
        {"date": "2025-11-19", "epsEstimated": 1.26, "epsActual": 1.30},
    ]})
    got = f.earnings_context("NVDA")
    assert [r["date"] for r in got["report_history"]] == ["2025-11-19", "2026-02-25", "2026-05-20", "2026-08-26"]
    assert all(r["date_kind"] == "report" for r in got["report_history"])
    assert got["beat_streak"] == "4/4 beats"


def test_a_company_with_no_reported_quarter_has_no_chart():
    f = _fmp({"earnings": [{"date": "2026-11-18", "epsEstimated": 2.47, "epsActual": None}]})
    assert f.earnings_context("NVDA") is None


def test_the_officers_are_the_ones_the_proxy_names():
    """The vendor's executive list runs 17 deep on NVIDIA, down to a
    datacenter product marketing manager; the seven the proxy names carry
    pay (2026-09-15)."""
    f = _fmp({"profile": [{"symbol": "NVDA", "companyName": "NVIDIA Corporation"}],
              "key-executives": [
                  {"name": "Jen-Hsun Huang", "title": "Co-Founder, CEO & Director", "pay": 11543318, "yearBorn": 1963},
                  {"name": "Colette Kress", "title": "EVP & Chief Financial Officer", "pay": 1514979, "yearBorn": 1967},
                  {"name": "Ajay K. Puri", "title": "EVP of Worldwide Field Operations", "pay": 2298337, "yearBorn": 1955},
                  {"name": "Charu Chaubal", "title": "Senior Manager of Datacenter Product Marketing"},
              ]})
    offs = f.company_profile("NVDA")["officers"]
    assert [o["name"] for o in offs] == ["Jen-Hsun Huang", "Ajay K. Puri", "Colette Kress"]
    assert offs[0]["total_pay"] == 11543318 and offs[0]["age"] == date.today().year - 1963


def test_without_pay_on_record_the_title_decides():
    f = _fmp({"profile": [{"symbol": "X", "companyName": "X"}],
              "key-executives": [
                  {"name": "A", "title": "Chief Executive Officer"},
                  {"name": "B", "title": "Senior Manager of Marketing"},
                  {"name": "C", "title": "President"},
              ]})
    assert [o["name"] for o in f.company_profile("X")["officers"]] == ["A", "C"]


def test_a_plan_that_refuses_executives_still_returns_the_profile():
    f = _fmp({"profile": [{"symbol": "X", "companyName": "X"}],
              "key-executives": EntitlementError("HTTP 402")})
    got = f.company_profile("X")
    assert got["name"] == "X" and got["officers"] == []


def test_a_coin_names_only_a_coin_vendor():
    from alphadesk.providers.catalogue import prompt
    assert [v["name"] for v in prompt("coin_profile")["vendors"]] == ["coingecko"]
