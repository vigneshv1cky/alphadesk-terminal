"""The SEC's structured company facts — XBRL, as filed, keyless.

`data.sec.gov/api/xbrl/companyfacts/CIK##########.json` carries every
tagged number a registrant has ever filed. This takes the handful a
profile wants — revenue, net income, diluted EPS, assets, equity, cash,
long-term debt — as the LATEST FULL-YEAR value from a 10-K, each with the
period end and the accession of the filing it came from, plus the most
recent shares-outstanding count. Companies tag revenue under different
concepts, so a short fallback list is tried and the newest wins.

Same User-Agent rule as the rest of EDGAR. Cached a day per CIK.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from alphadesk.ingest import edgar

log = logging.getLogger(__name__)

_TTL_S = 86_400
_cache: dict[str, tuple[float, dict | None]] = {}
_lock = threading.Lock()
_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

# label → candidate concepts, newest full-year value across them wins.
CONCEPTS: dict[str, list[str]] = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "RevenuesNetOfInterestExpense"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "assets": ["Assets"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
}


def latest_annual(gaap: dict, concepts: list[str]) -> dict | None:
    """The newest 10-K full-year (fp=FY) value among the concepts."""
    best: dict | None = None
    for c in concepts:
        node = gaap.get(c)
        if not node:
            continue
        for unit, rows in (node.get("units") or {}).items():
            for r in rows:
                if r.get("form") != "10-K" or r.get("fp") != "FY" or r.get("val") is None:
                    continue
                if best is None or r["end"] > best["end"]:
                    best = {"val": r["val"], "end": r["end"], "fy": r.get("fy"),
                            "accn": r.get("accn"), "unit": unit, "concept": c}
    return best


def facts(cik10: str) -> dict | None:
    with _lock:
        hit = _cache.get(cik10)
        if hit and time.time() - hit[0] < _TTL_S:
            return hit[1]
    out: dict | None = None
    try:
        data = json.loads(edgar._get(_URL.format(cik10=cik10), timeout=30.0))
        gaap = (data.get("facts") or {}).get("us-gaap") or {}
        dei = (data.get("facts") or {}).get("dei") or {}
        items = {label: latest_annual(gaap, cs) for label, cs in CONCEPTS.items()}
        items = {k: v for k, v in items.items() if v}
        shares = None
        sh = dei.get("EntityCommonStockSharesOutstanding")
        if sh:
            rows = [r for u in (sh.get("units") or {}).values() for r in u if r.get("val") is not None]
            if rows:
                r = max(rows, key=lambda x: x["end"])
                shares = {"val": r["val"], "end": r["end"], "accn": r.get("accn")}
        if items or shares:
            # The fiscal year most items share — the latest 10-K.
            ends = sorted({v["end"] for v in items.values()}, reverse=True)
            out = {
                "as_of": ends[0] if ends else None,
                "items": items,
                "shares_outstanding": shares,
                "source_url": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",
            }
    except Exception as exc:
        log.debug("company facts failed for %s: %s", cik10, exc)
    with _lock:
        _cache[cik10] = (time.time(), out)
    return out
