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

_cache: dict[str, tuple[float, dict | None]] = {}
_TTL_S = 6 * 3600
_FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")


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
    sym = symbol.upper()
    hit = _cache.get(sym)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]
    out: dict | None = None
    cik10 = edgar.cik_for(sym)
    if cik10:
        try:
            out = (json.loads(edgar._get(edgar._FACTS_URL.format(cik10=cik10), timeout=30.0)).get("facts") or {}).get("us-gaap") or {}
        except Exception as exc:
            log.warning("EDGAR company facts failed for %s: %s", sym, exc)
    if len(_cache) > 512:
        _cache.clear()
    _cache[sym] = (time.monotonic(), out)
    return out


def fundamentals_series(symbol: str, period: str = "quarterly", limit: int = 20) -> dict:
    """{symbol, period, metrics, series, source} — the chart's Metrics menu."""
    sym = symbol.upper()
    gaap = _facts(sym) or {}
    metrics: list[dict] = []
    series: dict[str, list[dict]] = {}
    for mid, spec in METRICS.items():
        q_all: dict[str, float] = {}
        y_all: dict[str, float] = {}
        for tag in reversed(spec["tags"]):
            rows = ((gaap.get(tag) or {}).get("units") or {}).get(spec.get("units", "USD")) or []
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
    return {"symbol": sym, "period": period, "metrics": metrics, "series": series, "source": "sec-edgar"}
