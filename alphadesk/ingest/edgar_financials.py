"""Financial-statement series as FILED, from the SEC's company-facts feed —
public government data, no key (2026-09-13: this replaces the Yahoo
statement series behind the chart's Metrics menu and the earnings bars).

For each metric, every value a registrant tagged in a 10-Q or 10-K:

  * quarterly — a three-month duration where one is filed; where only the
    year-to-date figure is (cash flows are filed cumulatively), the quarter
    is that figure minus the previous cumulative figure with the same start;
    the fourth quarter is the fiscal year minus the three quarters inside it.
  * annual — the fiscal-year duration from the 10-K.

Companies tag the same line under different concepts, so each metric tries
a short list and the newest concept wins where two overlap. A metric the
company never tags is simply absent — the menu does not offer an empty line.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date

from alphadesk.ingest import edgar

log = logging.getLogger("alphadesk.edgar_financials")

METRICS: dict[str, dict] = {
    "revenue": {"label": "Revenue", "group": "Income statement", "unit": "currency",
                "tags": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                         "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                         "RevenuesNetOfInterestExpense"]},
    "gross_profit": {"label": "Gross Profit", "group": "Income statement", "unit": "currency", "tags": ["GrossProfit"]},
    "operating_income": {"label": "Operating Income", "group": "Income statement", "unit": "currency",
                         "tags": ["OperatingIncomeLoss"]},
    "net_income": {"label": "Net Income", "group": "Income statement", "unit": "currency",
                   "tags": ["NetIncomeLoss", "ProfitLoss"]},
    "diluted_eps": {"label": "Diluted EPS", "group": "Income statement", "unit": "eps",
                    "tags": ["EarningsPerShareDiluted"], "units": "USD/shares"},
    "ocf": {"label": "Operating Cash Flow", "group": "Cash flow", "unit": "currency",
            "tags": ["NetCashProvidedByUsedInOperatingActivities"]},
    "capex": {"label": "Capital Expenditure", "group": "Cash flow", "unit": "currency",
              "tags": ["PaymentsToAcquirePropertyPlantAndEquipment"], "negate": True},
}

# THE SAME LINES UNDER THE IFRS TAXONOMY (2026-09-29, the owner). A foreign
# private issuer files a 20-F tagged `ifrs-full`, not `us-gaap` — the SEC holds
# 229 concepts for Inventiva, 253 for Novo Nordisk, 334 for TSMC and 368 for
# SAP, and reading one namespace out of two is why their panels were empty.
#
# Checked against all four before writing it: every metric below is present on
# each, bar gross profit for Inventiva (a clinical-stage biotech with no
# product revenue, so genuinely absent) and capex under this tag for SAP.
#
# THESE ARE NOT TRANSLATIONS OF THE US-GAAP CONCEPTS but the IFRS statement's
# own lines, which is why operating income is ProfitLossFromOperatingActivities
# rather than an OperatingIncomeLoss alias: IFRS states it as a subtotal of
# profit, and the two are not defined identically. What they share is the row a
# reader is looking for.
IFRS_TAGS: dict[str, list[str]] = {
    "revenue": ["Revenue", "RevenueFromContractsWithCustomers", "RevenueFromSaleOfGoods"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["ProfitLossFromOperatingActivities", "OperatingIncomeLoss"],
    "net_income": ["ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "diluted_eps": ["DilutedEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare"],
    "ocf": ["CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
}

_cache: dict[str, tuple[float, dict | None]] = {}
_TTL_S = 6 * 3600
# A FOREIGN PRIVATE ISSUER'S ANNUAL REPORT COUNTS (2026-09-28, the reader:
# "why wbuy is empty"). This was the domestic forms alone, so every fact a
# foreign filer tagged was discarded on the FORM NAME before its concept or
# its period was ever looked at. WEBUY Global is the case that found it: the
# SEC holds 265 us-gaap tags for it, including the exact Revenues and
# NetIncomeLoss concepts asked for below, over 364- and 365-day periods that
# sit inside the annual window -- and the panel showed nothing at all, while
# blaming IFRS for it. 20-F is the annual report of a foreign private issuer
# and 40-F the Canadian equivalent; both carry US-GAAP XBRL when the filer
# reports in it.
#
# 6-K IS HERE TOO, AND THE REASON IT WAS NOT IS WORTH CORRECTING (2026-09-29).
# It was excluded on the claim that a 6-K carries only half-years, which fall
# in no window here, being neither a quarter nor a year. That is true of three
# of the four filers measured -- Inventiva, TSMC and WEBUY file 180- and
# 181-day periods on it -- and simply false of the fourth: NOVO NORDISK FILES
# FULL YEARS ON A 6-K, twelve of them at 364 and 365 days, because it announces
# annual results there before the 20-F lands. Excluding the form discarded
# every one.
#
# THE OVERLAP WAS CHECKED BEFORE ADDING IT, because a preliminary announcement
# overwriting an audited figure is the obvious risk: on both years where Novo
# files the same period on a 6-K and a 20-F, the values agree EXACTLY. Nothing
# to choose between, so nothing to get wrong.
#
# A 6-K still has no fixed shape -- it may hold figures, a press release, or
# neither -- so this adds whatever it happens to tag and the period windows do
# the rest, exactly as they do for every other form.
_FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "20-F/A",
          "40-F", "40-F/A", "6-K", "6-K/A")


def _days(v: dict) -> int | None:
    try:
        return (date.fromisoformat(v["end"]) - date.fromisoformat(v["start"])).days
    except (KeyError, TypeError, ValueError):
        return None


def series_from_rows(rows: list[dict]) -> tuple[dict[str, float], dict[str, float]]:
    """(quarterly by end, annual by end) from one concept's filed rows. Pure."""
    quarters: dict[str, float] = {}
    years: dict[str, tuple[str, float]] = {}
    cumulative: dict[str, list[tuple[str, float]]] = {}     # start -> [(end, val)]
    for v in rows:
        if v.get("form") not in _FORMS or not isinstance(v.get("val"), (int, float)):
            continue
        d = _days(v)
        if d is None:
            continue
        if 80 <= d <= 100:
            quarters[v["end"]] = float(v["val"])
        elif 350 <= d <= 380:
            years[v["end"]] = (v["start"], float(v["val"]))
        if 80 <= d <= 380:
            cumulative.setdefault(v["start"], []).append((v["end"], float(v["val"])))
    for start, pts in cumulative.items():
        pts = sorted(set(pts))
        for (e0, v0), (e1, v1) in zip(pts, pts[1:]):
            gap = (date.fromisoformat(e1) - date.fromisoformat(e0)).days
            if 80 <= gap <= 100 and e1 not in quarters:
                quarters[e1] = v1 - v0
    for end, (start, total) in years.items():
        if end in quarters:
            continue
        inside = [q for q in quarters if start < q < end]
        if len(inside) == 3:
            quarters[end] = total - sum(quarters[q] for q in inside)
    return quarters, {e: v for e, (_s, v) in years.items()}


def _facts(symbol: str) -> dict | None:
    """The company's tagged facts and which taxonomy they are in.

    `us-gaap` where the registrant files under it — including plenty of
    foreign issuers, Alibaba and VinFast among them — and `ifrs-full` where it
    does not. A filer has one or the other, never a useful mix, so the larger
    set wins and the answer says which so the concepts can be matched to it.
    """
    sym = symbol.upper()
    hit = _cache.get(sym)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]
    out: dict | None = None
    cik10 = edgar.cik_for(sym)
    if cik10:
        try:
            facts = json.loads(edgar._get(edgar._FACTS_URL.format(cik10=cik10), timeout=30.0)).get("facts") or {}
            gaap, ifrs = facts.get("us-gaap") or {}, facts.get("ifrs-full") or {}
            out = {"tags": gaap, "taxonomy": "us-gaap"} if len(gaap) >= len(ifrs) \
                else {"tags": ifrs, "taxonomy": "ifrs-full"}
        except Exception as exc:
            log.warning("EDGAR company facts failed for %s: %s", sym, exc)
    if len(_cache) > 512:
        _cache.clear()
    _cache[sym] = (time.monotonic(), out)
    return out


def _currency(tags: dict, concepts: list[str]) -> str:
    """The currency a filer actually reports in, read off its own facts.

    THE REPORTING CURRENCY, NOT USD — and the choice is settled by counting
    rows rather than by preferring one. A USD column in a foreign filing is a
    convenience translation at one date's rate; the primary statement is the
    company's own currency, and it is also the one with the series in it.
    Measured on the four filers this was built against:

        TSMC   TWD 26 rows  USD 9      SAP    EUR 27 rows  USD 1
        Alibaba CNY 47 rows USD 16     VinFast VND 11 rows USD 4

    SAP settles it: preferring USD would draw a one-point chart. Counting also
    covers the filers with no USD at all — Novo Nordisk files only DKK and
    Inventiva only EUR, where assuming dollars would print kroner behind a
    dollar sign. A domestic filer has USD alone and picks it either way.

    This is not IFRS-specific: Alibaba and VinFast file US-GAAP in renminbi and
    dong, so the same counting runs for both taxonomies.
    """
    counts: dict[str, int] = {}
    for c in concepts:
        for unit, rows in ((tags.get(c) or {}).get("units") or {}).items():
            counts[unit.split("/")[0]] = counts.get(unit.split("/")[0], 0) + len(rows or [])
    return max(counts, key=lambda u: counts[u]) if counts else "USD"


def fundamentals_series(symbol: str, period: str = "quarterly", limit: int = 20) -> dict:
    """{symbol, period, metrics, series, source} — the chart's Metrics menu."""
    sym = symbol.upper()
    found = _facts(sym) or {}
    tags_by_concept: dict = found.get("tags") or {}
    taxonomy = found.get("taxonomy") or "us-gaap"
    ifrs = taxonomy == "ifrs-full"
    # The currency is read from the filer's OWN revenue facts, not assumed:
    # Novo Nordisk files only DKK and Inventiva only EUR, and a dollar sign
    # over either would be a plain misstatement of what the company earned.
    concepts_for = (lambda mid, spec: IFRS_TAGS.get(mid, [])) if ifrs else (lambda mid, spec: spec["tags"])
    currency = _currency(tags_by_concept, concepts_for("revenue", METRICS["revenue"]))
    metrics: list[dict] = []
    series: dict[str, list[dict]] = {}
    for mid, spec in METRICS.items():
        q_all: dict[str, float] = {}
        y_all: dict[str, float] = {}
        # A per-share figure is filed under "<currency>/shares", everything
        # else under the bare currency.
        unit = f"{currency}/shares" if spec.get("units", "").endswith("/shares") else currency
        for tag in reversed(concepts_for(mid, spec)):
            rows = ((tags_by_concept.get(tag) or {}).get("units") or {}).get(unit) or []
            q, y = series_from_rows(rows)
            q_all.update(q)
            y_all.update(y)
        picked = q_all if period == "quarterly" else y_all
        if not picked:
            continue
        sign = -1.0 if spec.get("negate") else 1.0
        pts = [{"t": end, "v": round(sign * v, 4)} for end, v in sorted(picked.items())][-limit:]
        metrics.append({"id": mid, "label": spec["label"], "group": spec["group"], "unit": spec["unit"]})
        series[mid] = pts
    if "ocf" in series and "capex" in series:
        capex = {p["t"]: p["v"] for p in series["capex"]}
        fcf = [{"t": p["t"], "v": round(p["v"] + capex[p["t"]], 4)} for p in series["ocf"] if p["t"] in capex]
        if fcf:
            metrics.append({"id": "fcf", "label": "Free Cash Flow", "group": "Cash flow", "unit": "currency"})
            series["fcf"] = fcf
    return {"symbol": sym, "period": period, "metrics": metrics, "series": series,
            "source": "sec-edgar", "taxonomy": taxonomy, "currency": currency}
