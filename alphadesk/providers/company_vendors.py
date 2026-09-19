"""Company data from the user's vendors — key statistics, comparison metrics,
peers, analyst ratings and targets, rating changes, short interest, fund
holdings, institutional ownership, earnings estimates, the per-symbol
earnings record and calendar, and the company profile (2026-09-13).

Each vendor's payload is mapped here into the ONE shape the pages already
render, so a panel does not care which vendor answered. A method answers
None when the vendor does not carry the surface (the data router then asks
the user's next vendor) and raises EntitlementError when the key's plan
refuses it. Nothing is estimated: a field a vendor lacks stays None.

Payload shapes are each vendor's documented ones, and Finnhub's free
endpoints were read live on 2026-09-13. Alpha Vantage and Financial
Modeling Prep follow their documentation; no key of either was on hand.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from alphadesk.providers.base import EntitlementError, ProviderError

log = logging.getLogger("alphadesk.providers.company")


def _f(v: Any) -> float | None:
    try:
        x = float(str(v).rstrip("%")) if isinstance(v, str) else float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _mul(v: Any, k: float) -> float | None:
    x = _f(v)
    return x * k if x is not None else None


def _pct(v: Any) -> float | None:
    """A fraction (0.0851) as a percent (8.51), rounded so float noise
    (8.510000000000002) never reaches a table."""
    x = _f(v)
    return round(x * 100, 4) if x is not None else None


def _frac(v: Any) -> float | None:
    """A percent (27.6) as a fraction (0.276)."""
    x = _f(v)
    return x / 100 if x is not None else None


def recommendation_summary(sb: int, b: int, h: int, s: int, ss: int) -> dict:
    """The consensus from a rating count, scored the way the quote pages
    score it: 1 strong buy through 5 strong sell, averaged."""
    n = sb + b + h + s + ss
    if not n:
        return {"mean": None, "key": None, "analysts": 0}
    mean = (sb * 1 + b * 2 + h * 3 + s * 4 + ss * 5) / n
    key = ("strong buy" if mean < 1.5 else "buy" if mean < 2.5 else "hold" if mean < 3.5
           else "sell" if mean < 4.5 else "strong sell")
    return {"mean": round(mean, 2), "key": key, "analysts": n}


# Words a research firm's name carries in one FMP record and not the other
# ("Truist Securities" / "Truist Financial", "Mizuho" / "Mizuho Securities").
_FIRM_NOISE = {"securities", "financial", "capital", "markets", "group", "research", "nicolaus", "bank",
               "co", "and", "partners", "llc", "inc", "ltd"}
# Names the two records spell so differently that the words do not line up.
_FIRM_ALIAS = {"b of a": "bankofamerica", "bank of america": "bankofamerica", "bofa": "bankofamerica",
               "robert w baird": "baird", "keefe bruyette": "kbw"}


def firm_key(name: str | None) -> str:
    """A research firm's name reduced to what both of FMP's analyst records
    agree on (measured on NVDA, AAPL, TSLA, JPM and CRWD, 2026-09-15):
    lower case, punctuation gone, the corporate suffix words dropped, the
    rest run together — "J.P. Morgan" and "JP Morgan" are both jpmorgan,
    "Truist Securities" and "Truist Financial" both truist."""
    import re
    raw = " ".join(re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower().replace("&", " ")).split())
    for phrase, key in _FIRM_ALIAS.items():
        if raw.startswith(phrase):
            return key
    return "".join(w for w in raw.split() if w not in _FIRM_NOISE)


def _ny_day(stamp: str | None) -> date | None:
    """A UTC timestamp's New York calendar day."""
    if not stamp:
        return None
    try:
        from zoneinfo import ZoneInfo
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(ZoneInfo("America/New_York")).date()
    except ValueError:
        return None


def attach_targets(changes: list[dict], targets: list[dict], window_days: int = 1) -> list[dict]:
    """Give each rating change the price target the same firm published with
    it. FMP keeps the two apart: its ratings record carries no target, and
    its price-target record carries no rating. A change takes the firm's
    target published within `window_days` of its date (the nearest; a target
    serves one change), its prior target is that firm's previous one with
    the day it was set (months older, sometimes), and the target action says
    whether it rose, fell or held. Targets are the
    split-adjusted figures, so a prior target from before a split compares
    on today's shares. A change with no matching target is left without
    one. Pure."""
    by_firm: dict[str, list[tuple[date, float]]] = {}
    firms = {firm_key(t.get("analystCompany")) for t in targets} - {""}
    titles = [firm_key(t.get("newsTitle")) for t in targets]
    # A firm named in more than half the headlines is the company covered
    # (every JPM headline says JPMorgan), not a sign of a mislabelled row.
    firms -= {f for f in firms if titles and sum(f in x for x in titles) * 2 > len(titles)}
    for t in targets:
        day, value = _ny_day(t.get("publishedDate")), _f(t.get("adjPriceTarget")) or _f(t.get("priceTarget"))
        firm = firm_key(t.get("analystCompany"))
        if not (day and value and firm):
            continue
        # FMP files some targets under the wrong firm: AAPL's 2026-03-04
        # "Jefferies 330" carries an Evercore ISI headline. A headline that
        # names another firm on the record and not this one is dropped, so
        # it cannot become a firm's prior target.
        title = firm_key(t.get("newsTitle"))
        if title and firm not in title and any(f in title for f in firms if f != firm):
            continue
        by_firm.setdefault(firm, []).append((day, value))
    for rows in by_firm.values():
        rows.sort()
    used: set[tuple[str, int]] = set()
    out = []
    for c in changes:
        c = dict(c)
        rows = by_firm.get(firm_key(c.get("firm"))) or []
        try:
            day = date.fromisoformat(str(c.get("date") or ""))
        except ValueError:
            day = None
        best = None
        if day:
            near = [(abs((d - day).days), i) for i, (d, _) in enumerate(rows)
                    if abs((d - day).days) <= window_days and (firm_key(c.get("firm")), i) not in used]
            best = min(near)[1] if near else None
        if best is not None:
            used.add((firm_key(c.get("firm")), best))
            target = rows[best][1]
            prior = rows[best - 1][1] if best > 0 else None
            c["target"], c["prior_target"] = target, prior
            c["prior_target_date"] = rows[best - 1][0].isoformat() if best > 0 else None
            c["target_action"] = (None if prior is None else "raised" if target > prior
                                  else "lowered" if target < prior else "maintained")
        out.append(c)
    return out


def _period_label(period: str) -> str:
    return "now" if period == "0m" else period


# ── Finnhub ───────────────────────────────────────────────────────────────


#: Rating changes kept per symbol. FMP carries NVDA's back to 2012; a
#: hundred reaches about a year, the span FMP's target record (capped at
#: 100 rows) can still be joined to.
CHANGES_KEEP = 100

#: Monthly rating snapshots kept where a vendor carries a history.
RATINGS_MONTHS = 12


class FinnhubCompany:
    """Mixed into FinnhubPrices, which provides `_get(path)`."""

    _company_cache: dict[tuple[str, str], tuple[float, Any]]

    def _cached(self, key: tuple[str, str], ttl: float, fetch):
        cache = self.__dict__.setdefault("_company_cache", {})
        hit = cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        val = fetch()
        if len(cache) > 2048:
            cache.clear()
        cache[key] = (time.time(), val)
        return val

    def _metric(self, sym: str) -> dict:
        return self._cached((sym, "metric"), 3600, lambda: (self._get(f"/stock/metric?symbol={sym}&metric=all") or {}).get("metric") or {})

    def _profile2(self, sym: str) -> dict:
        return self._cached((sym, "profile2"), 86400, lambda: self._get(f"/stock/profile2?symbol={sym}") or {})

    def key_stats(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        m, p = self._metric(sym), self._profile2(sym)
        if not m and not p:
            return None
        shares = _mul(p.get("shareOutstanding"), 1e6)
        mcap = _mul(m.get("marketCapitalization") or p.get("marketCapitalization"), 1e6)
        pfcf = _f(m.get("pfcfShareTTM"))
        return {
            "symbol": sym, "name": p.get("name"), "currency": p.get("currency"), "quote_type": None,
            "sector": p.get("finnhubIndustry"), "exchange": p.get("exchange"),
            "market_cap": mcap, "enterprise_value": _mul(m.get("enterpriseValue"), 1e6),
            "shares_outstanding": shares, "float_shares": _mul(p.get("floatingShare"), 1e6),
            "week52_low": _f(m.get("52WeekLow")), "week52_high": _f(m.get("52WeekHigh")),
            "avg_50d": None, "avg_200d": None,
            "avg_volume": _mul(m.get("3MonthAverageTradingVolume"), 1e6),
            "avg_volume_10d": _mul(m.get("10DayAverageTradingVolume"), 1e6),
            "beta": _f(m.get("beta")),
            "trailing_pe": _f(m.get("peTTM")), "forward_pe": _f(m.get("forwardPE")), "peg": _f(m.get("pegTTM")),
            "price_to_book": _f(m.get("pb") or m.get("pbQuarterly")), "price_to_sales": _f(m.get("psTTM")),
            "ev_to_ebitda": _f(m.get("evEbitdaTTM")),
            "trailing_eps": _f(m.get("epsTTM")), "forward_eps": None,
            "book_value": _f(m.get("bookValuePerShareQuarterly")),
            "dividend_rate": _f(m.get("dividendIndicatedAnnual")),
            "dividend_yield": _f(m.get("dividendYieldIndicatedAnnual")),
            "payout_ratio": _frac(m.get("payoutRatioTTM")),
            "held_insiders": None, "held_institutions": None,
            "revenue": (_f(m.get("revenuePerShareTTM")) or 0) * shares if shares and m.get("revenuePerShareTTM") else None,
            "profit_margin": _frac(m.get("netProfitMarginTTM")), "return_on_equity": _frac(m.get("roeTTM")),
            "total_cash": (_f(m.get("cashPerSharePerShareQuarterly")) or 0) * shares if shares and m.get("cashPerSharePerShareQuarterly") else None,
            "total_debt": None,
            "free_cash_flow": mcap / pfcf if mcap and pfcf else None,
            "ex_dividend_date": None, "earnings_date": None, "fiscal_year_end": None,
            "vendor": "finnhub",
        }

    def compare_metrics(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        m, p = self._metric(sym), self._profile2(sym)
        if not m:
            return None
        shares = _mul(p.get("shareOutstanding"), 1e6)
        mcap = _mul(m.get("marketCapitalization"), 1e6)
        pfcf, pcf = _f(m.get("pfcfShareTTM")), _f(m.get("pcfShareTTM"))
        return {
            "symbol": sym, "name": p.get("name"), "sector": p.get("finnhubIndustry"), "industry": p.get("finnhubIndustry"),
            "market_cap": mcap, "enterprise_value": _mul(m.get("enterpriseValue"), 1e6),
            "pe": _f(m.get("peTTM")), "forward_pe": _f(m.get("forwardPE")), "peg": _f(m.get("pegTTM")),
            "ps": _f(m.get("psTTM")), "pb": _f(m.get("pb") or m.get("pbQuarterly")),
            "ev_sales": _f(m.get("evRevenueTTM")), "ev_ebitda": _f(m.get("evEbitdaTTM")),
            "dividend_yield": _frac(m.get("dividendYieldIndicatedAnnual")), "payout_ratio": _frac(m.get("payoutRatioTTM")),
            "gross_margin": _frac(m.get("grossMarginTTM")), "operating_margin": _frac(m.get("operatingMarginTTM")),
            "ebitda_margin": None, "net_margin": _frac(m.get("netProfitMarginTTM")),
            "roe": _frac(m.get("roeTTM")), "roa": _frac(m.get("roaTTM")),
            "revenue_growth": _frac(m.get("revenueGrowthTTMYoy")), "earnings_growth": _frac(m.get("epsGrowthTTMYoy")),
            "earnings_q_growth": _frac(m.get("epsGrowthQuarterlyYoy")),
            "revenue": (_f(m.get("revenuePerShareTTM")) or 0) * shares if shares and m.get("revenuePerShareTTM") else None,
            "ebitda": (_f(m.get("ebitdPerShareTTM")) or 0) * shares if shares and m.get("ebitdPerShareTTM") else None,
            "eps": _f(m.get("epsTTM")), "forward_eps": None,
            "current_ratio": _f(m.get("currentRatioQuarterly")), "quick_ratio": _f(m.get("quickRatioQuarterly")),
            "debt_to_equity": _f(m.get("totalDebt/totalEquityQuarterly")),
            "total_cash": (_f(m.get("cashPerSharePerShareQuarterly")) or 0) * shares if shares and m.get("cashPerSharePerShareQuarterly") else None,
            "total_debt": None, "free_cash_flow": mcap / pfcf if mcap and pfcf else None,
            "operating_cash_flow": mcap / pcf if mcap and pcf else None,
            "beta": _f(m.get("beta")), "short_pct_float": None, "short_ratio": None,
            "avg_volume": _mul(m.get("3MonthAverageTradingVolume"), 1e6), "employees": None,
            "vendor": "finnhub",
        }

    def peers(self, symbol: str) -> list[str] | None:
        self._need_key()
        sym = symbol.upper()
        got = self._get(f"/stock/peers?symbol={sym}") or []
        out = [str(x).upper() for x in got if isinstance(x, str) and str(x).upper() != sym]
        return out or None

    def analyst_ratings(self, symbol: str) -> dict | None:
        self._need_key()
        rows = self._get(f"/stock/recommendation?symbol={symbol.upper()}") or []
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows:
            return None
        rows.sort(key=lambda r: r.get("period") or "", reverse=True)
        dist = []
        for i, r in enumerate(rows[:4]):
            dist.append({"period": "0m" if i == 0 else f"-{i}m", "as_of": r.get("period"),
                         "strong_buy": int(r.get("strongBuy") or 0), "buy": int(r.get("buy") or 0),
                         "hold": int(r.get("hold") or 0), "sell": int(r.get("sell") or 0),
                         "strong_sell": int(r.get("strongSell") or 0)})
        d = dist[0]
        return {"recommendation": recommendation_summary(d["strong_buy"], d["buy"], d["hold"], d["sell"], d["strong_sell"]),
                "distribution": dist, "vendor": "finnhub"}

    def price_targets(self, symbol: str) -> dict | None:
        self._need_key()
        t = self._get(f"/stock/price-target?symbol={symbol.upper()}") or {}
        if not t.get("targetMean"):
            return None
        return {"low": _f(t.get("targetLow")), "mean": _f(t.get("targetMean")), "median": _f(t.get("targetMedian")),
                "high": _f(t.get("targetHigh")), "analysts": t.get("numberAnalysts"), "as_of": t.get("lastUpdated"),
                "vendor": "finnhub"}

    def rating_changes(self, symbol: str) -> list[dict] | None:
        self._need_key()
        rows = self._get(f"/stock/upgrade-downgrade?symbol={symbol.upper()}") or []
        out = []
        for r in rows[:CHANGES_KEEP]:
            ts = _f(r.get("gradeTime"))
            action = str(r.get("action") or "").lower()
            out.append({"date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else None,
                        "firm": r.get("company"), "to_grade": r.get("toGrade"), "from_grade": r.get("fromGrade"),
                        "action": {"up": "upgrade", "down": "downgrade", "init": "initiated", "main": "maintained",
                                   "reit": "reiterated"}.get(action, action or None),
                        "target_action": None, "target": None, "prior_target": None})
        return out or None

    def short_interest(self, symbol: str) -> dict | None:
        self._need_key()
        to = date.today()
        got = self._get(f"/stock/short-interest?symbol={symbol.upper()}&from={to - timedelta(days=120)}&to={to}") or {}
        rows = sorted((r for r in got.get("data") or [] if r.get("shortInterest") is not None), key=lambda r: r.get("date") or "")
        if not rows:
            return None
        last = rows[-1]
        prior = rows[-2] if len(rows) > 1 else None
        return {"shares_short": _f(last.get("shortInterest")), "prior_month": _f(prior.get("shortInterest")) if prior else None,
                "days_to_cover": None, "pct_float": None, "float_shares": None, "as_of": last.get("date"), "vendor": "finnhub"}

    def fund_holdings(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        h = self._get(f"/etf/holdings?symbol={sym}") or {}
        holdings = h.get("holdings") or []
        if not holdings:
            return None
        prof = (self._get(f"/etf/profile?symbol={sym}") or {}).get("profile") or {}
        sectors = (self._get(f"/etf/sector?symbol={sym}") or {}).get("sectorExposure") or []
        rows = [{"symbol": (r.get("symbol") or None), "name": r.get("name"), "weight": _f(r.get("percent"))}
                for r in sorted(holdings, key=lambda r: -(_f(r.get("percent")) or 0))[:25]]
        return {"symbol": sym, "quote_type": "ETF", "category": prof.get("assetClass"), "family": prof.get("etfCompany"),
                "legal_type": "Exchange Traded Fund", "description": prof.get("description"),
                "expense_ratio": _f(prof.get("expenseRatio")), "turnover": None, "net_assets": _f(prof.get("aum")),
                "holdings": rows, "top_weight": round(sum(r["weight"] or 0 for r in rows), 2),
                "sectors": [{"key": s.get("industry"), "label": s.get("industry"), "weight": _f(s.get("exposure"))} for s in sectors],
                "assets": [], "vendor": "finnhub"}

    def institutional_ownership(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        got = self._get(f"/stock/ownership?symbol={sym}&limit=25") or {}
        rows = got.get("ownership") or []
        if not rows:
            return None
        holders = [{"name": r.get("name"), "date": r.get("filingDate"), "shares": _f(r.get("share")),
                    "change": _f(r.get("change")), "change_pct": None, "value": None} for r in rows]
        return {"symbol": sym, "source": "finnhub", "as_of": max((h["date"] or "" for h in holders), default=None) or None,
                "summary": {}, "holders": holders, "total_holders": None}

    def earnings_insights(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        eps = (self._get(f"/stock/eps-estimate?symbol={sym}&freq=quarterly") or {}).get("data") or []
        rev = (self._get(f"/stock/revenue-estimate?symbol={sym}&freq=quarterly") or {}).get("data") or []
        if not eps and not rev:
            return None
        today = date.today().isoformat()
        by_period: dict[str, dict] = {}
        for r in eps:
            if (r.get("period") or "") >= today:
                by_period.setdefault(r["period"], {})["eps"] = {"analysts": r.get("numberAnalysts"), "avg": _f(r.get("epsAvg")),
                                                              "low": _f(r.get("epsLow")), "high": _f(r.get("epsHigh"))}
        for r in rev:
            if (r.get("period") or "") >= today:
                by_period.setdefault(r["period"], {})["revenue"] = {"analysts": r.get("numberAnalysts"), "avg": _f(r.get("revenueAvg")),
                                                                  "low": _f(r.get("revenueLow")), "high": _f(r.get("revenueHigh"))}
        periods = [{"period": k, "label": "Current quarter" if i == 0 else "Next quarter" if i == 1 else k,
                    "eps": v.get("eps"), "revenue": v.get("revenue")} for i, (k, v) in enumerate(sorted(by_period.items())[:4])]
        return {"symbol": sym, "periods": periods, "vendor": "finnhub"} if periods else None

    def earnings_calendar(self, start: str, end: str, symbol: str | None = None) -> list[dict] | None:
        self._need_key()
        q = f"/calendar/earnings?from={start}&to={end}" + (f"&symbol={symbol.upper()}" if symbol else "")
        rows = (self._get(q) or {}).get("earningsCalendar") or []
        # An EMPTY hour is the vendor saying nothing, not "during the day":
        # Finnhub sends "" for FedEx and General Mills, both of which have
        # reported outside trading hours for years. A silence stays silent
        # so the calendar predicts the session from the company's filing
        # history instead of asserting one (2026-09-15).
        hour = {"bmo": "BMO", "amc": "AMC", "dmh": "DAY"}
        out = []
        for r in rows:
            sym, day = str(r.get("symbol") or "").upper(), r.get("date")
            if not sym or not day:
                continue
            h = str(r.get("hour") or "").lower()
            out.append({"symbol": sym, "report_date": day, "session": hour.get(h),
                        "confirmed": h in hour or r.get("epsActual") is not None,
                        "eps_estimate": _f(r.get("epsEstimate")), "eps_actual": _f(r.get("epsActual")),
                        "revenue_estimate": _f(r.get("revenueEstimate")), "revenue_actual": _f(r.get("revenueActual")),
                        "fiscal_quarter": r.get("quarter"), "fiscal_year": r.get("year"), "source": "finnhub"})
        return out

    def company_profile(self, symbol: str) -> dict | None:
        self._need_key()
        p = self._profile2(symbol.upper())
        if not p:
            return None
        return {"name": p.get("name"), "industry": p.get("finnhubIndustry"), "sector": p.get("finnhubIndustry"),
                "website": p.get("weburl"), "phone": p.get("phone"), "exchange": p.get("exchange"),
                "currency": p.get("currency"), "market_cap": _mul(p.get("marketCapitalization"), 1e6),
                "country": p.get("country"), "ipo_date": p.get("ipo"), "logo": p.get("logo"), "quote_type": "EQUITY",
                "vendor": "finnhub"}


# ── Alpha Vantage ─────────────────────────────────────────────────────────


class AlphaVantageCompany:
    """Mixed into AlphaVantagePrices, which provides `_query(params)`. The
    free tier allows 25 calls a day, so the overview (which answers key
    statistics, comparison metrics, the analyst target and rating counts)
    is fetched once a day per symbol."""

    _OVERVIEW_TTL_S = 86400

    def _overview(self, sym: str) -> dict:
        cache = self.__dict__.setdefault("_overview_cache", {})
        hit = cache.get(sym)
        if hit and time.time() - hit[0] < self._OVERVIEW_TTL_S:
            return hit[1]
        o = self._query(f"function=OVERVIEW&symbol={sym}")
        o = o if o.get("Symbol") else {}
        cache[sym] = (time.time(), o)
        return o

    def key_stats(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        o = self._overview(sym)
        if not o:
            return None
        return {
            "symbol": sym, "name": o.get("Name"), "currency": o.get("Currency"), "quote_type": o.get("AssetType"),
            "sector": o.get("Sector"), "exchange": o.get("Exchange"),
            "market_cap": _f(o.get("MarketCapitalization")), "enterprise_value": None,
            "shares_outstanding": _f(o.get("SharesOutstanding")), "float_shares": _f(o.get("SharesFloat")),
            "week52_low": _f(o.get("52WeekLow")), "week52_high": _f(o.get("52WeekHigh")),
            "avg_50d": _f(o.get("50DayMovingAverage")), "avg_200d": _f(o.get("200DayMovingAverage")),
            "avg_volume": None, "avg_volume_10d": None, "beta": _f(o.get("Beta")),
            "trailing_pe": _f(o.get("TrailingPE") or o.get("PERatio")), "forward_pe": _f(o.get("ForwardPE")),
            "peg": _f(o.get("PEGRatio")), "price_to_book": _f(o.get("PriceToBookRatio")),
            "price_to_sales": _f(o.get("PriceToSalesRatioTTM")), "ev_to_ebitda": _f(o.get("EVToEBITDA")),
            "trailing_eps": _f(o.get("DilutedEPSTTM") or o.get("EPS")), "forward_eps": None,
            "book_value": _f(o.get("BookValue")), "dividend_rate": _f(o.get("DividendPerShare")),
            "dividend_yield": _mul(o.get("DividendYield"), 100), "payout_ratio": None,
            "held_insiders": _frac(o.get("PercentInsiders")), "held_institutions": _frac(o.get("PercentInstitutions")),
            "revenue": _f(o.get("RevenueTTM")), "profit_margin": _f(o.get("ProfitMargin")),
            "return_on_equity": _f(o.get("ReturnOnEquityTTM")), "total_cash": None, "total_debt": None,
            "free_cash_flow": None,
            "ex_dividend_date": o.get("ExDividendDate") if o.get("ExDividendDate") not in (None, "None", "0000-00-00") else None,
            "earnings_date": None, "fiscal_year_end": None, "fiscal_year_end_month": o.get("FiscalYearEnd"),
            "vendor": "alphavantage",
        }

    def compare_metrics(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        o = self._overview(sym)
        if not o:
            return None
        rev, ebitda = _f(o.get("RevenueTTM")), _f(o.get("EBITDA"))
        return {
            "symbol": sym, "name": o.get("Name"), "sector": o.get("Sector"), "industry": o.get("Industry"),
            "market_cap": _f(o.get("MarketCapitalization")), "enterprise_value": None,
            "pe": _f(o.get("TrailingPE") or o.get("PERatio")), "forward_pe": _f(o.get("ForwardPE")), "peg": _f(o.get("PEGRatio")),
            "ps": _f(o.get("PriceToSalesRatioTTM")), "pb": _f(o.get("PriceToBookRatio")),
            "ev_sales": _f(o.get("EVToRevenue")), "ev_ebitda": _f(o.get("EVToEBITDA")),
            "dividend_yield": _f(o.get("DividendYield")), "payout_ratio": None,
            "gross_margin": (_f(o.get("GrossProfitTTM")) or 0) / rev if rev and o.get("GrossProfitTTM") else None,
            "operating_margin": _f(o.get("OperatingMarginTTM")), "ebitda_margin": ebitda / rev if rev and ebitda else None,
            "net_margin": _f(o.get("ProfitMargin")), "roe": _f(o.get("ReturnOnEquityTTM")), "roa": _f(o.get("ReturnOnAssetsTTM")),
            "revenue_growth": _f(o.get("QuarterlyRevenueGrowthYOY")), "earnings_growth": None,
            "earnings_q_growth": _f(o.get("QuarterlyEarningsGrowthYOY")),
            "revenue": rev, "ebitda": ebitda, "eps": _f(o.get("DilutedEPSTTM") or o.get("EPS")), "forward_eps": None,
            "current_ratio": None, "quick_ratio": None, "debt_to_equity": None, "total_cash": None, "total_debt": None,
            "free_cash_flow": None, "operating_cash_flow": None, "beta": _f(o.get("Beta")),
            "short_pct_float": None, "short_ratio": None, "avg_volume": None, "employees": None,
            "vendor": "alphavantage",
        }

    def analyst_ratings(self, symbol: str) -> dict | None:
        self._need_key()
        o = self._overview(symbol.upper())
        keys = ("AnalystRatingStrongBuy", "AnalystRatingBuy", "AnalystRatingHold", "AnalystRatingSell", "AnalystRatingStrongSell")
        counts = [int(_f(o.get(k)) or 0) for k in keys]
        if not o or not sum(counts):
            return None
        sb, b, h, s, ss = counts
        return {"recommendation": recommendation_summary(sb, b, h, s, ss),
                "distribution": [{"period": "0m", "strong_buy": sb, "buy": b, "hold": h, "sell": s, "strong_sell": ss}],
                "vendor": "alphavantage"}

    def price_targets(self, symbol: str) -> dict | None:
        self._need_key()
        o = self._overview(symbol.upper())
        mean = _f(o.get("AnalystTargetPrice"))
        if not mean:
            return None
        return {"low": None, "mean": mean, "median": None, "high": None, "analysts": None, "vendor": "alphavantage"}

    def earnings_insights(self, symbol: str) -> dict | None:
        self._need_key()
        sym = symbol.upper()
        rows = self._query(f"function=EARNINGS_ESTIMATES&symbol={sym}").get("estimates") or []
        today = date.today().isoformat()
        periods = []
        for r in sorted(rows, key=lambda r: r.get("date") or ""):
            if (r.get("date") or "") < today:
                continue
            horizon = str(r.get("horizon") or "")
            periods.append({
                "period": r.get("date"), "label": horizon.replace("fiscal", "").strip().title() or r.get("date"),
                "eps": {"analysts": _f(r.get("eps_estimate_analyst_count")), "avg": _f(r.get("eps_estimate_average")),
                        "low": _f(r.get("eps_estimate_low")), "high": _f(r.get("eps_estimate_high"))},
                "revenue": {"analysts": _f(r.get("revenue_estimate_analyst_count")), "avg": _f(r.get("revenue_estimate_average")),
                            "low": _f(r.get("revenue_estimate_low")), "high": _f(r.get("revenue_estimate_high"))},
            })
        return {"symbol": sym, "periods": periods[:4], "vendor": "alphavantage"} if periods else None

    def fund_holdings(self, symbol: str) -> dict | None:
        """An ETF's holdings, sector weights, net assets and expense ratio
        from ETF_PROFILE (2026-09-18). Checked against the documented demo
        call that day: QQQ answered 120 holdings, each a symbol, a name and a
        weight as a FRACTION in a string ("0.0851"), sector weights the same
        way, and net assets, expense ratio and dividend yield as strings.
        Converted to percent here, which is what the other vendors send.
        A symbol that is not an ETF answers with no holdings: None, so the
        router moves on. One call a symbol; the router caches it six hours,
        which matters on a free key of 25 calls a day."""
        self._need_key()
        sym = symbol.upper()
        got = self._query(f"function=ETF_PROFILE&symbol={sym}")
        rows = [r for r in got.get("holdings") or [] if isinstance(r, dict)]
        if not rows:
            return None
        top = sorted(rows, key=lambda r: -(_f(r.get("weight")) or 0))[:25]
        hold = [{"symbol": (r.get("symbol") or None) if r.get("symbol") not in ("n/a", "") else None,
                 "name": r.get("description"), "weight": _pct(r.get("weight"))} for r in top]
        return {"symbol": sym, "quote_type": "ETF", "category": None, "family": None,
                "legal_type": "Exchange Traded Fund", "description": None,
                "expense_ratio": _pct(got.get("net_expense_ratio")), "turnover": _pct(got.get("portfolio_turnover")),
                "net_assets": _f(got.get("net_assets")),
                "holdings": hold, "top_weight": round(sum(r["weight"] or 0 for r in hold), 2),
                "sectors": [{"key": r.get("sector"), "label": (r.get("sector") or "").title() or None, "weight": _pct(r.get("weight"))}
                            for r in got.get("sectors") or [] if isinstance(r, dict)],
                "assets": [], "as_of": got.get("last_updated"), "vendor": "alphavantage"}

    def earnings_calendar(self, start: str, end: str, symbol: str | None = None) -> list[dict] | None:
        """EARNINGS_CALENDAR is a CSV of the next three months (or one
        symbol's), so it is fetched once and filtered to the window."""
        self._need_key()
        import csv
        import io
        from alphadesk.providers.prices import _get_text
        q = "function=EARNINGS_CALENDAR&horizon=3month" + (f"&symbol={symbol.upper()}" if symbol else "")
        text = _get_text(f"{self._BASE}?{q}&apikey={self.api_key}")
        if text.lstrip().startswith("{"):
            raise ProviderError(f"Alpha Vantage calendar refused: {text[:160]}")
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            day = r.get("reportDate")
            if not day or not (start <= day <= end):
                continue
            t = (r.get("timeOfTheDay") or "").lower()
            out.append({"symbol": (r.get("symbol") or "").upper(), "report_date": day,
                        "session": "BMO" if "pre" in t else "AMC" if "post" in t else None,
                        "confirmed": bool(t), "eps_estimate": _f(r.get("estimate")), "eps_actual": None,
                        "revenue_estimate": None, "revenue_actual": None, "company_name": r.get("name"),
                        "source": "alphavantage"})
        return out

    def company_profile(self, symbol: str) -> dict | None:
        self._need_key()
        o = self._overview(symbol.upper())
        if not o:
            return None
        return {"name": o.get("Name"), "summary": o.get("Description"), "industry": o.get("Industry"),
                "sector": o.get("Sector"), "website": o.get("OfficialSite"), "exchange": o.get("Exchange"),
                "currency": o.get("Currency"), "market_cap": _f(o.get("MarketCapitalization")),
                "country": o.get("Country"), "quote_type": o.get("AssetType"), "vendor": "alphavantage",
                "address": {"street": o.get("Address"), "city": None, "state": None, "zip": None, "country": o.get("Country")}}


# ── Financial Modeling Prep ───────────────────────────────────────────────


class FmpPrices:
    """Financial Modeling Prep's stable API on the user's key. Most of what
    AlphaDesk asks of it sits on paid plans; a refusal is a plan refusal."""

    name = "fmp"
    _BASE = "https://financialmodelingprep.com/stable"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self._etfs: tuple[float, dict[str, str]] | None = None
        # (the rollover it belongs to, {pair: close at that rollover})
        self._fx_bases: tuple[Any, dict[str, float]] | None = None

    def _need_key(self) -> None:
        if not self.api_key:
            raise ProviderError("no Financial Modeling Prep key")

    def _get(self, path: str, **params: Any) -> Any:
        from urllib.parse import urlencode
        from alphadesk.providers.prices import _get_json
        self._need_key()
        q = urlencode({**{k: v for k, v in params.items() if v is not None}, "apikey": self.api_key})
        data = _get_json(f"{self._BASE}/{path}?{q}", {})
        if isinstance(data, dict) and data.get("Error Message"):
            msg = str(data["Error Message"])
            if "premium" in msg.lower() or "subscription" in msg.lower() or "upgrade" in msg.lower():
                raise EntitlementError(f"Financial Modeling Prep: {msg[:160]}")
            raise ProviderError(f"Financial Modeling Prep: {msg[:160]}")
        return data

    def _first(self, path: str, **params: Any) -> dict:
        got = self._get(path, **params)
        return got[0] if isinstance(got, list) and got else (got if isinstance(got, dict) else {})

    def company_profile(self, symbol: str) -> dict | None:
        p = self._first("profile", symbol=symbol.upper())
        if not p.get("symbol"):
            return None
        return {"name": p.get("companyName"), "summary": p.get("description"), "industry": p.get("industry"),
                "sector": p.get("sector"), "employees": p.get("fullTimeEmployees"), "website": p.get("website"),
                "phone": p.get("phone"), "exchange": p.get("exchange"), "currency": p.get("currency"),
                "market_cap": _f(p.get("marketCap")), "country": p.get("country"), "ipo_date": p.get("ipoDate"),
                "quote_type": "ETF" if p.get("isEtf") else "MUTUALFUND" if p.get("isFund") else "EQUITY",
                "address": {"street": p.get("address"), "city": p.get("city"), "state": p.get("state"),
                            "zip": p.get("zip"), "country": p.get("country")},
                "officers": self._officers(symbol), "vendor": "fmp"}

    #: Titles that make someone an officer of the company rather than a
    #: manager in it, for the companies whose pay figures are not on record.
    _OFFICER_TITLE = ("chief", "president", "chairman", "chairwoman", "chair of",
                      "ceo", "cfo", "coo", "cto", "general counsel", "treasurer", "secretary")

    def _officers(self, symbol: str) -> list[dict]:
        """Who runs the company, from the vendor's executive list.

        The list runs deep — 17 people for NVIDIA, down to a datacenter
        product marketing manager — but the ones the proxy statement names
        carry PAY, and those seven are the officers (measured 2026-09-15).
        Where nobody's pay is on record the title decides instead, so a
        company that discloses no compensation still lists its chiefs.
        Empty when the plan refuses the call; nothing else on the profile
        depends on it."""
        try:
            rows = self._get("key-executives", symbol=symbol.upper()) or []
        except (EntitlementError, ProviderError):
            return []
        people = [r for r in rows if isinstance(r, dict) and r.get("name")]
        paid = [r for r in people if _f(r.get("pay"))]
        kept = paid if len(paid) >= 3 else [
            r for r in people if any(t in str(r.get("title") or "").lower() for t in self._OFFICER_TITLE)]
        kept.sort(key=lambda r: -(_f(r.get("pay")) or 0))
        year = date.today().year
        return [{"name": r.get("name"), "title": r.get("title"),
                 "age": (year - int(r["yearBorn"])) if str(r.get("yearBorn") or "").isdigit() else None,
                 "total_pay": _f(r.get("pay"))} for r in kept[:12]]

    def key_stats(self, symbol: str) -> dict | None:
        sym = symbol.upper()
        p = self._first("profile", symbol=sym)
        if not p.get("symbol"):
            return None
        km, ra = self._first("key-metrics-ttm", symbol=sym), self._first("ratios-ttm", symbol=sym)
        try:
            fl = self._first("shares-float", symbol=sym)
        except ProviderError:
            fl = {}
        lo, hi = (str(p.get("range") or "").split("-") + [None, None])[:2]
        return {"symbol": sym, "name": p.get("companyName"), "currency": p.get("currency"),
                "quote_type": "ETF" if p.get("isEtf") else "EQUITY", "sector": p.get("sector"), "exchange": p.get("exchange"),
                "market_cap": _f(p.get("marketCap")), "enterprise_value": _f(km.get("enterpriseValueTTM")),
                "shares_outstanding": _f(fl.get("outstandingShares")), "float_shares": _f(fl.get("floatShares")),
                "week52_low": _f(lo), "week52_high": _f(hi),
                "avg_50d": None, "avg_200d": None, "avg_volume": _f(p.get("averageVolume")), "avg_volume_10d": None,
                "beta": _f(p.get("beta")), "trailing_pe": _f(ra.get("priceToEarningsRatioTTM")), "forward_pe": None,
                "peg": _f(ra.get("priceToEarningsGrowthRatioTTM")), "price_to_book": _f(ra.get("priceToBookRatioTTM")),
                "price_to_sales": _f(ra.get("priceToSalesRatioTTM")), "ev_to_ebitda": _f(km.get("evToEBITDATTM")),
                "trailing_eps": _f(ra.get("netIncomePerShareTTM")), "forward_eps": None,
                "book_value": _f(ra.get("bookValuePerShareTTM")), "dividend_rate": _f(p.get("lastDividend")),
                "dividend_yield": _mul(ra.get("dividendYieldTTM"), 100), "payout_ratio": _f(ra.get("dividendPayoutRatioTTM")),
                "held_insiders": None, "held_institutions": None, "revenue": None,
                "profit_margin": _f(ra.get("netProfitMarginTTM")), "return_on_equity": _f(km.get("returnOnEquityTTM")),
                "total_cash": None, "total_debt": None, "free_cash_flow": None,
                "ex_dividend_date": None, "earnings_date": None, "fiscal_year_end": None, "vendor": "fmp"}

    def peers(self, symbol: str) -> list[str] | None:
        got = self._get("stock-peers", symbol=symbol.upper()) or []
        out = [str(r.get("symbol")).upper() for r in got if isinstance(r, dict) and r.get("symbol")]
        return [s for s in out if s != symbol.upper()] or None

    def analyst_ratings(self, symbol: str) -> dict | None:
        g = self._first("grades-consensus", symbol=symbol.upper())
        counts = [int(_f(g.get(k)) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")]
        if not sum(counts):
            return None
        sb, b, h, s, ss = counts
        # The monthly history — 24 months on NVDA, where Finnhub's free plan
        # stops at four.
        #
        # ONE RECORD DRIVES BOTH the headline and the bars. FMP's two
        # disagree: on 2026-09-15 its live consensus counted 2 strong buy,
        # 58 buy, 16 hold and 3 sell (79) against the history's 10, 49, 2
        # and 1 (62) — the same analysts sorted into the buckets
        # differently. Drawing one as "now" above the other as "last month"
        # would show a collapse in conviction that never happened, so the
        # history answers both when it is there, and the live consensus
        # only when it is not.
        try:
            hist = self._get("grades-historical", symbol=symbol.upper()) or []
        except (EntitlementError, ProviderError):
            hist = []
        rows = sorted((r for r in hist if isinstance(r, dict) and r.get("date")),
                      key=lambda r: str(r.get("date")), reverse=True)[:RATINGS_MONTHS]
        dist = [{"period": f"-{i}m" if i else "0m", "as_of": str(r.get("date"))[:10],
                 "strong_buy": int(_f(r.get("analystRatingsStrongBuy")) or 0),
                 "buy": int(_f(r.get("analystRatingsBuy")) or 0),
                 "hold": int(_f(r.get("analystRatingsHold")) or 0),
                 "sell": int(_f(r.get("analystRatingsSell")) or 0),
                 "strong_sell": int(_f(r.get("analystRatingsStrongSell")) or 0)}
                for i, r in enumerate(rows)]
        if dist:
            d = dist[0]
            return {"recommendation": recommendation_summary(d["strong_buy"], d["buy"], d["hold"],
                                                             d["sell"], d["strong_sell"]),
                    "distribution": dist, "vendor": "fmp"}
        dist = [{"period": "0m", "as_of": None, "strong_buy": sb, "buy": b, "hold": h, "sell": s, "strong_sell": ss}]
        return {"recommendation": recommendation_summary(sb, b, h, s, ss), "distribution": dist, "vendor": "fmp"}

    def price_targets(self, symbol: str) -> dict | None:
        t = self._first("price-target-consensus", symbol=symbol.upper())
        if not t.get("targetConsensus"):
            return None
        # The consensus carries no analyst count; the summary counts the
        # targets published over the last month and quarter.
        try:
            summary = self._first("price-target-summary", symbol=symbol.upper())
        except (EntitlementError, ProviderError):
            summary = {}
        def count(k):
            return int(_f(summary.get(k)) or 0) or None
        # The consensus spans every target on file, including ones no firm
        # has restated in a year (NVDA's $270 low against a $300 lowest of
        # the last month); the summary's recent average says where the
        # current ones sit.
        month, quarter = count("lastMonthCount"), count("lastQuarterCount")
        recent = (_f(summary.get("lastMonthAvgPriceTarget")) if month
                  else _f(summary.get("lastQuarterAvgPriceTarget")) if quarter else None)
        return {"low": _f(t.get("targetLow")), "mean": _f(t.get("targetConsensus")), "median": _f(t.get("targetMedian")),
                "high": _f(t.get("targetHigh")), "analysts": None,
                "published_month": month, "published_quarter": quarter,
                "recent_mean": recent, "recent_window": "month" if month else "quarter" if quarter else None,
                "vendor": "fmp"}

    def rating_changes(self, symbol: str) -> list[dict] | None:
        rows = self._get("grades", symbol=symbol.upper()) or []
        out = [{"date": str(r.get("date") or "")[:10] or None, "firm": r.get("gradingCompany"),
                "to_grade": r.get("newGrade"), "from_grade": r.get("previousGrade"),
                "action": str(r.get("action") or "").lower() or None,
                "target_action": None, "target": None, "prior_target": None} for r in rows[:CHANGES_KEEP] if isinstance(r, dict)]
        if not out:
            return None
        # The targets that went with them live in a separate record. 100
        # reaches back past the 40 changes shown (NVDA: a year of targets
        # against four months of changes); without it the changes still show.
        try:
            targets = self._get("price-target-news", symbol=symbol.upper(), limit=100) or []
        except (EntitlementError, ProviderError):
            targets = []
        return attach_targets(out, [t for t in targets if isinstance(t, dict)])

    def fund_holdings(self, symbol: str) -> dict | None:
        """The fund record. The HOLDINGS list sits on FMP's Ultimate plan
        (measured 2026-09-14 on Premium: etf/holdings 402 "Restricted
        Endpoint", etf/info and etf/sector-weightings 200), so a plan that
        refuses it still returns the profile and sector weights, with
        `holdings_needs_key` saying what the holdings list needs."""
        sym = symbol.upper()
        needs = None
        try:
            rows = self._get("etf/holdings", symbol=sym) or []
        except EntitlementError:
            rows = []
            from alphadesk.providers.catalogue import prompt
            needs = prompt("fund_holdings", refused=["fmp"])
        info = self._first("etf/info", symbol=sym)
        if not rows and not info.get("symbol"):
            return None
        sectors = self._get("etf/sector-weightings", symbol=sym) or []
        top = sorted((r for r in rows if isinstance(r, dict)), key=lambda r: -(_f(r.get("weightPercentage")) or 0))[:25]
        hold = [{"symbol": r.get("asset"), "name": r.get("name"), "weight": _f(r.get("weightPercentage"))} for r in top]
        return {"symbol": sym, "quote_type": "ETF", "category": info.get("assetClass"), "family": info.get("etfCompany"),
                "legal_type": "Exchange Traded Fund", "description": info.get("description"),
                "expense_ratio": _f(info.get("expenseRatio")), "turnover": None, "net_assets": _f(info.get("assetsUnderManagement")),
                "holdings": hold, "top_weight": round(sum(r["weight"] or 0 for r in hold), 2) if hold else None,
                "sectors": [{"key": s.get("sector"), "label": s.get("sector"), "weight": _f(s.get("weightPercentage"))}
                            for s in sectors if isinstance(s, dict)],
                "assets": [], "vendor": "fmp", "holdings_needs_key": needs}

    def corporate_actions(self, symbol: str) -> dict | None:
        sym = symbol.upper()
        divs = self._get("dividends", symbol=sym) or []
        spl = self._get("splits", symbol=sym) or []
        dividends = [{"ex_date": r.get("date"), "amount": _f(r.get("dividend")), "adjusted_amount": _f(r.get("adjDividend")),
                      "currency": None, "declaration_date": r.get("declarationDate") or None,
                      "record_date": r.get("recordDate") or None, "payment_date": r.get("paymentDate") or None}
                     for r in divs if isinstance(r, dict) and r.get("date")]
        splits = [{"date": r.get("date"), "from": _f(r.get("denominator")), "to": _f(r.get("numerator"))}
                  for r in spl if isinstance(r, dict) and r.get("date")]
        if not dividends and not splits:
            return None
        return {"symbol": sym, "dividends": dividends, "splits": splits}

    def earnings_history(self, symbol: str) -> dict | None:
        rows = self._get("earnings", symbol=symbol.upper()) or []
        today = date.today().isoformat()
        reports = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("date"):
                continue
            est, act = _f(r.get("epsEstimated")), _f(r.get("epsActual"))
            reports.append({"date": r["date"], "upcoming": act is None and r["date"] >= today, "eps_estimate": est,
                            "eps_actual": act, "surprise_pct": round(100 * (act - est) / abs(est), 2) if act is not None and est else None,
                            "revenue": _f(r.get("revenueActual")), "revenue_estimate": _f(r.get("revenueEstimated"))})
        reports.sort(key=lambda r: r["date"], reverse=True)
        return {"symbol": symbol.upper(), "reports": reports, "vendor": "fmp"} if reports else None

    def earnings_context(self, symbol: str) -> dict | None:
        """The reported record the EPS chart draws, dated by the day each
        report was made.

        Finnhub carries this too, but dates every row by a CALENDAR quarter
        end: NVIDIA's quarter ended 2026-07-26 and was reported 2026-08-26,
        and Finnhub stamps it 2026-09-30 — a period that has not ended, which
        the panel then labelled as a later quarter than the one reported
        (2026-09-15). The figures agree; only the dating differs, so the
        report-dated record answers first and both panels on the page tell
        the same story."""
        got = self.earnings_history(symbol)
        if not got:
            return None
        history = [{"date": r["date"], "period_end": None, "date_kind": "report",
                    "eps_estimate": r["eps_estimate"], "eps_actual": r["eps_actual"],
                    "surprise_pct": r["surprise_pct"]}
                   for r in got["reports"] if r["eps_actual"] is not None]
        if not history:
            return None
        history.sort(key=lambda r: r["date"])
        recent = [r for r in history[-4:] if r["eps_estimate"] is not None]
        beats = sum(1 for r in recent if r["eps_actual"] >= r["eps_estimate"])
        out: dict = {"symbol": symbol.upper(), "report_history": history, "vendor": "fmp"}
        if recent:
            out["beat_streak"] = f"{beats}/{len(recent)} beats"
        return out

    # FMP's range calendars return at most 4,000 rows and, past that, keep the
    # LATEST dates (measured 2026-09-14: an eight-month earnings request came
    # back holding only Nov 11 onwards, so NB's Sep 9 report vanished). A range
    # is fetched a week at a time, and a week that still fills the cap is
    # split into days.
    _RANGE_CAP = 4000

    def _range(self, path: str, start: str, end: str, step_days: int = 7) -> list:
        from concurrent.futures import ThreadPoolExecutor
        d0, d1 = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
        spans: list[tuple[date, date]] = []
        while d0 <= d1:
            hi = min(d1, d0 + timedelta(days=step_days - 1))
            spans.append((d0, hi))
            d0 = hi + timedelta(days=1)

        def one(span: tuple[date, date]) -> list:
            lo, hi = span
            rows = self._get(path, **{"from": lo.isoformat(), "to": hi.isoformat()}) or []
            if isinstance(rows, list) and len(rows) >= self._RANGE_CAP and step_days > 1:
                rows = self._range(path, lo.isoformat(), hi.isoformat(), step_days=1)
            elif isinstance(rows, list) and len(rows) >= self._RANGE_CAP:
                log.warning("FMP %s returned the %d-row cap for %s; rows may be missing", path, self._RANGE_CAP, lo)
            return rows if isinstance(rows, list) else []

        # Four spans at a time, in order: an earnings-season month is weeks
        # split into days at the cap — 7.3s one after another (2026-09-14).
        out: list = []
        with ThreadPoolExecutor(max_workers=min(4, len(spans) or 1)) as pool:
            for rows in pool.map(one, spans):
                out.extend(rows)
        return out

    def earnings_calendar(self, start: str, end: str, symbol: str | None = None) -> list[dict] | None:
        if symbol:
            # One company: its own record, not the market calendar filtered.
            rows = [r for r in (self._get("earnings", symbol=symbol.upper()) or [])
                    if isinstance(r, dict) and start[:10] <= str(r.get("date") or "")[:10] <= end[:10]]
        else:
            rows = self._range("earnings-calendar", start, end)
        out = []
        seen: set[tuple[str, str]] = set()
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if not sym or (symbol and sym != symbol.upper()) or (sym, r.get("date")) in seen:
                continue
            seen.add((sym, r.get("date")))
            # FMP's calendar carries no session at all; saying nothing is
            # the honest mapping (2026-09-15).
            out.append({"symbol": sym, "report_date": r.get("date"), "session": None, "confirmed": False,
                        "eps_estimate": _f(r.get("epsEstimated")), "eps_actual": _f(r.get("epsActual")),
                        "revenue_estimate": _f(r.get("revenueEstimated")), "revenue_actual": _f(r.get("revenueActual")),
                        "source": "fmp"})
        return out

    def earnings_insights(self, symbol: str) -> dict | None:
        # FMP lists quarters newest first, reaching two years ahead: eight
        # rows stopped short of the current quarter (Apple's 2026-09-27 was
        # the ninth), so enough are asked for to include it.
        rows = self._get("analyst-estimates", symbol=symbol.upper(), period="quarter", limit=40) or []
        today = date.today().isoformat()
        future = sorted((r for r in rows if isinstance(r, dict) and (r.get("date") or "") >= today), key=lambda r: r["date"])[:4]
        periods = [{"period": r["date"], "label": "Current quarter" if i == 0 else "Next quarter" if i == 1 else r["date"],
                    "eps": {"analysts": r.get("numAnalystsEps"), "avg": _f(r.get("epsAvg")), "low": _f(r.get("epsLow")), "high": _f(r.get("epsHigh"))},
                    "revenue": {"analysts": r.get("numAnalystsRevenue"), "avg": _f(r.get("revenueAvg")),
                                "low": _f(r.get("revenueLow")), "high": _f(r.get("revenueHigh"))}}
                   for i, r in enumerate(future)]
        return {"symbol": symbol.upper(), "periods": periods, "vendor": "fmp"} if periods else None

    def press_releases(self, symbol: str, limit: int = 40) -> list[dict] | None:
        """One company's recent press releases, newest first — where it
        announces when it will report."""
        from alphadesk.config import ET
        rows = self._get("news/press-releases", symbols=symbol.upper(), limit=limit) or []
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                # Naive US/Eastern, restated in UTC like every stored article.
                published = datetime.strptime(str(r.get("publishedDate") or ""), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ET).astimezone(timezone.utc)
            except ValueError:
                continue
            out.append({"symbol": str(r.get("symbol") or symbol).upper(), "title": r.get("title") or "",
                        "text": r.get("text") or "", "published_at": published.isoformat(), "url": r.get("url") or "",
                        "source": r.get("site") or r.get("publisher") or None})
        return out

    def dividend_calendar(self, start: str, end: str) -> list[dict] | None:
        """Upcoming and recent dividends across the market. FMP's `date` is
        the ex-dividend date (Apple's 2026-08-10 row: record the same day
        under T+1 settlement, paid the 13th); `yield` is already a percent."""
        rows = self._range("dividends-calendar", start, end)
        return [{"symbol": str(r["symbol"]).upper(), "ex_date": r["date"][:10],
                 "record_date": r.get("recordDate") or None, "payment_date": r.get("paymentDate") or None,
                 "declaration_date": r.get("declarationDate") or None,
                 "amount": _f(r.get("dividend")), "adjusted_amount": _f(r.get("adjDividend")),
                 "yield_pct": _f(r.get("yield")), "frequency": r.get("frequency") or None}
                for r in rows if isinstance(r, dict) and r.get("symbol") and r.get("date")]

    def category_movers(self, category: str, top: int = 20) -> dict | None:
        """Currency movers: the dollar against the majors and emerging
        currencies, and the main crosses (49 pairs), priced from FMP's quotes
        in one request (0.15-0.24s on Premium, 2026-09-15; the all-pairs forex
        endpoint is refused on that plan). Other categories are not carried
        here.

        The day's change runs from the 5pm New York rollover, where the
        currency market's trading day turns (fx_rollover). FMP's own
        previous close is not one moment: measured 2026-09-15 it was the
        5pm price exactly for GBP/USD, but prices from earlier in the
        afternoon for EUR/USD and USD/JPY. So the base is each pair's own
        close at the rollover, read from its 5-minute bars once a trading
        day."""
        if category != "currencies":
            return None
        from alphadesk.providers.prices import CURRENCY_PAIRS, polygon_forex_symbol
        pairs = [(sym[2:], label) for yahoo, label in CURRENCY_PAIRS
                 if (sym := polygon_forex_symbol(yahoo))]
        rows = self._get("batch-quote", symbols=",".join(p for p, _ in pairs))
        if not isinstance(rows, list):
            return None
        quotes = {str(r.get("symbol", "")).upper(): r for r in rows if isinstance(r, dict)}
        bases = self._rollover_closes([p for p, _ in pairs])
        out = []
        for pair, label in pairs:
            q = quotes.get(pair)
            price = _f(q.get("price")) if q else None
            if not price:
                continue
            base = bases.get(pair)
            # FX has no consolidated volume; the figure FMP sends is a tick
            # count from its own feed, so no volume is claimed.
            out.append({"symbol": pair, "display": f"{pair[:3]}/{pair[3:]}", "name": label, "price": price,
                        "change_pct": round(100 * (price / base - 1), 3) if base else None, "volume": 0})
        if not out:
            return None
        changed = [r for r in out if r["change_pct"] is not None]
        return {"tabs": [
            {"id": "all", "label": "All", "rows": out},
            {"id": "gainers", "label": "Gainers", "rows": sorted([r for r in changed if r["change_pct"] > 0], key=lambda r: -r["change_pct"])},
            {"id": "losers", "label": "Losers", "rows": sorted([r for r in changed if r["change_pct"] < 0], key=lambda r: r["change_pct"])},
        ], "source": "fmp", "note": "change since the 5pm New York rollover"}

    def fx_daily_history(self, pairs: list[str], days: int = 21) -> dict[str, list[dict]]:
        """Each pair's last `days` daily closing rates, oldest first, as
        {date, close} — what the currency list's volatility is computed from
        (2026-09-19). One request a pair, eight at a time. The volume FMP
        sends is its own feed's tick count, so none is returned."""
        from concurrent.futures import ThreadPoolExecutor
        from datetime import date, timedelta
        since = (date.today() - timedelta(days=int(days * 1.6) + 7)).isoformat()

        def one(pair: str) -> tuple[str, list[dict]]:
            try:
                got = self._get("historical-price-eod/light", symbol=pair, **{"from": since})
            except ProviderError:
                return pair, []
            rows = [{"date": r["date"], "close": _f(r.get("price"))} for r in got or []
                    if isinstance(r, dict) and r.get("date") and _f(r.get("price"))]
            return pair, sorted(rows, key=lambda r: r["date"])[-days:]

        with ThreadPoolExecutor(max_workers=8) as pool:
            return {p: rows for p, rows in pool.map(one, pairs) if rows}

    def _rollover_closes(self, pairs: list[str]) -> dict[str, float]:
        """Each pair's close at the current trading day's 5pm New York
        rollover, from FMP's 5-minute bars (stamped in New York time), kept
        until the next rollover. Four pairs at a time."""
        from concurrent.futures import ThreadPoolExecutor
        from datetime import datetime
        from alphadesk.config import ET
        from alphadesk.providers.prices import fx_rollover, close_at
        roll = fx_rollover(datetime.now(ET))
        kept = self._fx_bases if self._fx_bases and self._fx_bases[0] == roll else (roll, {})
        missing = [p for p in pairs if p not in kept[1]]

        def one(pair: str) -> tuple[str, float | None]:
            try:
                bars = self._get("historical-chart/5min", symbol=pair)
            except ProviderError:
                return pair, None
            return pair, close_at(bars if isinstance(bars, list) else [], roll, 5)

        if missing:
            # Eight at a time: 49 pairs' bars once a trading day.
            with ThreadPoolExecutor(max_workers=8) as pool:
                for pair, base in pool.map(one, missing):
                    if base:
                        kept[1][pair] = base
        self._fx_bases = kept
        return dict(kept[1])

    def sector_weights(self) -> dict[str, float] | None:
        """Each sector's share of the S&P 500, percent, from SPY's sector
        weightings (one request, 0.13s on Premium, 2026-09-15). Sectors are
        FMP's names ("Technology", "Financial Services"…); cash is left out."""
        rows = self._get("etf/sector-weightings", symbol="SPY")
        if not isinstance(rows, list):
            return None
        out = {str(r["sector"]): float(r["weightPercentage"]) for r in rows
               if isinstance(r, dict) and r.get("sector") and _f(r.get("weightPercentage")) is not None
               and not str(r["sector"]).lower().startswith("cash")}
        return out or None

    def sp500_constituents(self) -> list[dict] | None:
        """The S&P 500's members with sector, sub-sector and SEC CIK (503
        listings in one request, 0.16s on Premium, 2026-09-15). No market cap:
        ask market_caps for it. Share classes are listed separately (GOOG and
        GOOGL) under one CIK."""
        rows = self._get("sp500-constituent")
        if not isinstance(rows, list):
            return None
        out = [{"symbol": str(r["symbol"]).upper(), "name": r.get("name"), "sector": r.get("sector"),
                "industry": r.get("subSector"), "cik": r.get("cik")}
               for r in rows if isinstance(r, dict) and r.get("symbol") and r.get("sector")]
        return out or None

    def sector_companies(self, min_market_cap: float = 2e9) -> list[dict] | None:
        """US-listed companies over `min_market_cap`, with sector, industry and
        market cap, from FMP's screener in one request (2,273 over $2B in
        0.42s, 2026-09-15). The screener also returns foreign listings of the
        same companies (XOM.NE, 0QZA.L) despite the country filter, so only
        NYSE, Nasdaq and NYSE American listings are kept."""
        rows = self._get("company-screener", marketCapMoreThan=int(min_market_cap), country="US",
                         isEtf="false", isFund="false", isActivelyTrading="true", limit=10000)
        if not isinstance(rows, list):
            return None
        out = []
        for r in rows:
            if not isinstance(r, dict) or str(r.get("exchangeShortName") or "").upper() not in ("NYSE", "NASDAQ", "AMEX"):
                continue
            sym = str(r.get("symbol") or "").upper()
            if not sym or not r.get("sector"):
                continue
            out.append({"symbol": sym, "name": r.get("companyName"), "sector": r["sector"],
                        "industry": r.get("industry"), "market_cap": _f(r.get("marketCap")),
                        "avg_volume": _f(r.get("avgVolume"))})
        return out or None

    def fund_names(self) -> dict[str, str] | None:
        """Every fund FMP lists, symbol to name (11,346 on 2026-09-15, one
        request, 0.47s), kept a day. Two things read it: the movers, to tell
        a fund from a stock (Alpaca's asset records do not say), and the
        related-funds panel, which finds a company's own single-stock funds
        by name."""
        import time
        if self._etfs and time.time() - self._etfs[0] < 86400:
            return self._etfs[1]
        rows = self._get("etf-list")
        if not isinstance(rows, list):
            return None
        got = {str(r["symbol"]).upper(): str(r.get("name") or "")
               for r in rows if isinstance(r, dict) and r.get("symbol")}
        self._etfs = (time.time(), got)
        return got

    def etf_symbols(self) -> frozenset[str] | None:
        names = self.fund_names()
        return frozenset(names) if names is not None else None

    def market_caps(self, symbols: list[str]) -> dict[str, float] | None:
        """Today's market capitalisation for many companies, 100 to a request
        (0.15s each, measured 2026-09-14). Share classes are asked the SEC way
        (LEN-B); a company FMP does not know is simply absent."""
        from concurrent.futures import ThreadPoolExecutor
        wanted = sorted({s.upper() for s in symbols if s})
        out: dict[str, float] = {}
        chunks = [wanted[i:i + 100] for i in range(0, len(wanted), 100)]
        # Four at a time: a busy week is ten requests (1.4s one after another).
        with ThreadPoolExecutor(max_workers=min(4, len(chunks) or 1)) as pool:
            for rows in pool.map(lambda c: self._get("market-capitalization-batch", symbols=",".join(c)) or [], chunks):
                for r in rows if isinstance(rows, list) else []:
                    cap = _f(r.get("marketCap")) if isinstance(r, dict) else None
                    if cap and r.get("symbol"):
                        out[str(r["symbol"]).upper()] = cap
        return out

    def split_calendar(self, start: str, end: str) -> list[dict] | None:
        rows = self._range("splits-calendar", start, end)
        return [{"symbol": str(r["symbol"]).upper(), "date": r["date"][:10],
                 "to": _f(r.get("numerator")), "from": _f(r.get("denominator")), "kind": r.get("splitType") or None}
                for r in rows if isinstance(r, dict) and r.get("symbol") and r.get("date")]

    def ipo_calendar(self, start: str, end: str) -> list[dict] | None:
        rows = self._range("ipos-calendar", start, end)
        out = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("date"):
                continue
            lo = hi = None
            nums = [_f(x) for x in str(r.get("priceRange") or "").replace("$", "").split("-")]
            nums = [n for n in nums if n is not None]
            if nums:
                lo, hi = min(nums), max(nums)
            out.append({"symbol": str(r.get("symbol") or "").upper() or None, "date": r["date"][:10],
                        "company": r.get("company") or None, "exchange": r.get("exchange") or None,
                        "status": r.get("actions") or None, "shares": _f(r.get("shares")),
                        "price_low": lo, "price_high": hi, "market_cap": _f(r.get("marketCap"))})
        return out

    def economic_calendar(self, start: str, end: str) -> list[dict] | None:
        rows = self._range("economic-calendar", start, end)
        out = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("event"):
                continue
            t = str(r.get("date") or "")
            out.append({"time": (t[:10] + "T" + t[11:19] + "Z") if len(t) >= 19 else (t or None),
                        "country": (r.get("country") or None), "event": r["event"],
                        "impact": str(r.get("impact") or "").lower() or None,
                        "actual": _f(r.get("actual")), "estimate": _f(r.get("estimate")), "previous": _f(r.get("previous")),
                        "unit": r.get("unit") or None})
        return sorted(out, key=lambda r: r["time"] or "")
