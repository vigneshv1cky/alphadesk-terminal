"""THE COMPANY'S OWN SHARE COUNT, ASKED OF THE SEC (2026-09-26, #83).

WHY NOT THE VENDOR'S. A reverse split restates every historical per-share
figure, and vendors are least reliable about share counts on exactly the
companies that have just done one — WHLR's float came back as 2,420 shares
against 89 million traded that day, which made turnover read 36,800x. Any
measure that divides by a share count is worthless there, and that is the
population it would be used on.

The SEC's `EntityCommonStockSharesOutstanding` is the number the company
itself put on the cover of its own filing. Keyless public data, so one row
serves every reader (invariant 8 allows exactly this, as it does for EDGAR
and the Treasury curve).

ONE CONCEPT, NOT THE WHOLE FACTS FILE. secfacts.facts() already exposes this
number, but it downloads a company's ENTIRE XBRL history to get it — fine
for one profile page, hopeless for a window of two hundred symbols. This
asks for the single concept instead.

RATE LIMIT. Every call goes through edgar._get, which reserves a send slot
every 0.15s process-wide, so a cold window of 200 symbols would be 30
seconds. Callers must therefore fill what is already stored, ask for a
handful more, and leave the rest to a background thread — see
screener.inventory().
"""

import json
import logging

from alphadesk.ingest import edgar
from alphadesk.ledger import store

log = logging.getLogger("alphadesk.secshares")

_URL = ("https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}"
        "/dei/EntityCommonStockSharesOutstanding.json")


def read(symbol: str) -> dict | None:
    """Ask the SEC for one company's share count and store it.

    Returns {shares, as_of, accession} or None. A company the SEC has no
    number for is STORED AS NOTHING rather than left absent, so a polling
    panel does not ask again every minute about a company that will never
    have one.
    """
    cik = edgar.cik_for(symbol)
    if not cik:
        store.save_sec_shares(symbol, None, None, None)
        return None
    try:
        data = json.loads(edgar._get(_URL.format(cik10=cik), timeout=20.0))
    except Exception as exc:
        # NOT stored: a refused or rate-limited read is not an answer, and
        # writing it as "no number" would hide the company for a week.
        log.debug("sec share count failed for %s: %s", symbol, exc)
        return None
    rows = [r for unit in (data.get("units") or {}).values() for r in unit
            if r.get("val") is not None and r.get("end")]
    if not rows:
        store.save_sec_shares(symbol, None, None, None, None)
        return None
    # CHOSEN BY WHEN IT WAS FILED, NOT BY THE DATE ON THE COVER. The cover
    # date is the company's own text and it can simply be wrong: American
    # Airlines' latest reads 2027-07-17 on a filing made 2026-07-23, and the
    # SEC's own frame label carries the mistake forward as CY2027Q2I. A
    # figure dated in the future would pass any freshness test ever written,
    # so the clock has to be the one nobody types.
    best = max(rows, key=lambda r: (r.get("filed") or "", r["end"]))
    out = {"shares": float(best["val"]), "as_of": best["end"],
           "filed_at": best.get("filed"), "accession": best.get("accn")}
    store.save_sec_shares(symbol, out["shares"], out["as_of"], out["filed_at"], out["accession"])
    return out


def stored(symbols: list[str]) -> dict[str, dict]:
    """What is already held, without asking the SEC anything."""
    return store.get_sec_shares(symbols)
