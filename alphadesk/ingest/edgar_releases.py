"""Results releases as filed on SEC EDGAR, for every company, keyless
(2026-09-13).

A company's earnings release is an 8-K carrying Item 2.02. Most are
accepted by EDGAR within minutes of the press release; the rule allows up to
four business days, and some companies use them (Optical Cable released on
2026-09-09 and filed on the 11th at 4:15 PM). So each row keeps the RELEASE
day beside the filing day, and only a same-day filing's acceptance instant
stands for the release time.

The release day is NOT the 8-K's "date of report": that is the earliest
event anywhere in the filing (measured 2026-09-14 — Casey's reported a
2026-09-02 shareholder vote in the same 8-K as its 09-08 results; Signet
and IBEX an earlier agreement; Designer Brands' date of report was the day
BEFORE its release). The Item 2.02 text itself says "On September 9, 2026,
… issued a press release", and that sentence is read — only for filings
whose date of report is earlier than their filing day, since a same-day
filing cannot have an earlier release. EDGAR's full-text search lists every 8-K filed on a day
with its item numbers and tickers, so one keyless job can stamp every
release without knowing any calendar: the day's 8-Ks are paged through,
those with Item 2.02 are kept, and each filer's submissions record gives
the acceptance instant to the second. The result lives in one shared table
of public data; each user's calendar joins it to the reports their own
vendors list.

A FOREIGN PRIVATE ISSUER FILES NO 8-K AT ALL (2026-09-16). Its results go
out on a 6-K, which carries no item numbers, so those filings are found by
searching the day's 6-K text for the wording a results release uses and
reading each candidate's exhibit to be sure. Until this existed the sweep
was blind to every 20-F filer: ZTO Express announced its second quarter on
2026-08-19 and nothing here could confirm it, correct a vendor's date for
it, or list the company when no vendor carried it at all.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, timedelta
from urllib.parse import urlencode

from alphadesk.ingest import edgar
from alphadesk.ledger import store

log = logging.getLogger("alphadesk.edgar_releases")

_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_PAGE = 100
_MAX_PAGES = 12
_TICKERS = re.compile(r"\(([A-Z0-9.\-, ]+)\)\s*\(CIK (\d+)\)")
# "Item 2.02 … On September 9, 2026, Optical Cable Corporation issued a press release"
_PRESS_DATE = re.compile(r"Item\s*2\.02.{0,400}?\bOn\s+([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4})", re.I | re.S)
_RESULTS_ONLY = {"2.02", "9.01"}


def press_release_date(text: str) -> str | None:
    """The date the Item 2.02 section says the results were released, as
    YYYY-MM-DD, or None when the sentence is not there. Pure."""
    from datetime import datetime
    for m in _PRESS_DATE.finditer(re.sub(r"\s+", " ", text or "")):
        raw = m.group(1).replace(".", "").replace(" ,", ",")
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d,%Y", "%b %d,%Y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def resolve_release_day(file_date: str, report_date: str | None, items: str | list | None, text: str | None) -> str:
    """The release day of a results 8-K. Same-day (or no date of report):
    the filing day. Otherwise the Item 2.02 sentence's date when it lies
    between the date of report and the filing day; failing that, the date of
    report for a filing that carries only results, else the filing day. Pure."""
    fd = file_date[:10]
    rd = (report_date or "")[:10]
    if not rd or rd >= fd:
        return fd
    said = press_release_date(text or "")
    if said and rd <= said <= fd:
        return said
    its = {i.strip() for i in (items if isinstance(items, list) else str(items or "").split(",")) if i.strip()}
    return rd if its and its <= _RESULTS_ONLY else fd


def parse_hits(hits: list[dict]) -> list[dict]:
    """Search hits → one row per (ticker, filing) for filings carrying Item
    2.02: {symbol, accession, cik, file_date, event_date, company}. The
    search's `period_ending` is the 8-K's date of report. A filing appears
    once per document in the search, so accessions are deduped. Pure."""
    out: dict[tuple[str, str], dict] = {}
    for h in hits:
        src = h.get("_source") or {}
        if "2.02" not in (src.get("items") or []):
            continue
        adsh = src.get("adsh") or str(h.get("_id") or "").split(":")[0]
        for name in src.get("display_names") or []:
            m = _TICKERS.search(name)
            if not m:
                continue
            company = name[: m.start()].strip()
            cik = f"{int(m.group(2)):010d}"
            for t in m.group(1).split(","):
                t = t.strip().upper()
                if t and (t, adsh) not in out:
                    fd = src.get("file_date")
                    rd = (src.get("period_ending") or "")[:10] or None
                    out[(t, adsh)] = {"symbol": t, "accession": adsh, "cik": cik, "file_date": fd,
                                      # Settled here only when it cannot be earlier than the filing;
                                      # otherwise read from the filing's text when times are filled.
                                      "event_date": fd if fd and (not rd or rd >= fd) else None,
                                      "company": company}
    return list(out.values())


def _search(day: str, offset: int) -> dict:
    q = urlencode({"forms": "8-K", "dateRange": "custom", "startdt": day, "enddt": day, "from": offset})
    return json.loads(edgar._get(f"{_SEARCH}?{q}", timeout=30.0))


# FOREIGN PRIVATE ISSUERS (2026-09-16). A company filing 20-F never files an
# 8-K, so nothing above ever sees it: ZTO Express announced its second
# quarter on a 6-K and the sweep could neither stamp it, correct a vendor's
# date for it, nor create a row when no vendor listed it. A 6-K has no item
# numbers to filter on — it is a covering page over whatever the company
# published abroad, from a results announcement to a share-buyback return —
# so the filings are found by SEARCHING THE TEXT for the wording a results
# release uses, and each candidate's own exhibit is then read to be sure.
#
# Measured on 2026-08-19: "financial results" returned 51 filings for the
# day and "interim results" 6, where the whole day's 8-K sweep is a few
# hundred. The two phrases overlap and are deduped by accession.
_SIX_K_PHRASES = ("financial results", "interim results")
_SIX_K_MAX_READS = 80

# The headline of a results release, as foreign issuers write it: "ZTO
# Reports Second Quarter 2026 Unaudited Financial Results", "Top Wealth
# Group Holding Limited Announces Financial Results", "Interim Results
# Announcement for the Six Months Ended June 30, 2026".
_RESULTS_HEADLINE = re.compile(
    r"\b(reports?|reported|announces?|announced|announcement of|publishes|publication of)\b[^.\n]{0,90}"
    r"\b(unaudited |interim |annual |quarterly |half[- ]year |full[- ]year )*(financial )?results\b"
    r"|\b(interim|annual|quarterly|unaudited)\s+results\s+announcement\b"
    r"|\b(unaudited|audited)\s+(interim\s+|annual\s+)?financial results\b", re.I)
# A period word, so a filing that merely mentions results in passing — a
# prospectus, a rights issue, a change of auditor — is not taken for one.
_RESULTS_PERIOD = re.compile(
    r"\b(first|second|third|fourth)\s+quarter\b|\bq[1-4]\b|\bhalf[- ]year\b|\bsix months ended\b"
    r"|\bthree months ended\b|\bnine months ended\b|\btwelve months ended\b|\bfull[- ]year\b"
    r"|\bfiscal year\b|\byear ended\b", re.I)
# "SHANGHAI, August 19, 2026 /PRNewswire/ - ZTO Express (Cayman) Inc. …"
_DATELINE = re.compile(r"\b([A-Z][A-Za-z.\-' ]{2,28}),\s*([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4})\s*[/(—–-]")


def is_results_release(text: str) -> bool:
    """Whether a 6-K exhibit is the company announcing results for a period,
    rather than any other thing a foreign issuer files abroad. Pure."""
    head = re.sub(r"\s+", " ", text or "")[:3_000]
    return bool(_RESULTS_HEADLINE.search(head) and _RESULTS_PERIOD.search(head))


def dateline_day(text: str) -> str | None:
    """The date on a press release's own dateline, as YYYY-MM-DD, or None.

    It is the RELEASE day as the company wrote it, and for an issuer abroad
    that is its own calendar: ZTO's second-quarter release is datelined
    Shanghai, August 19, when the same moment was the evening of August 18 in
    New York, where its shares trade. So this is a day either side of the day
    a US calendar would name, which is why a vendor's date within a day of it
    is left where it is. Pure."""
    from datetime import datetime
    m = _DATELINE.search(re.sub(r"\s+", " ", text or "")[:1_500])
    if not m:
        return None
    raw = m.group(2).replace(".", "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _search_text(day: str, phrase: str, forms: str, offset: int = 0) -> dict:
    q = urlencode({"q": f'"{phrase}"', "forms": forms, "dateRange": "custom",
                   "startdt": day, "enddt": day, "from": offset})
    return json.loads(edgar._get(f"{_SEARCH}?{q}", timeout=30.0))


def foreign_candidates(hits: list[dict]) -> list[dict]:
    """Search hits → one row per (ticker, filing), deduped, keeping the
    EXHIBIT document of each — the covering 6-K says nothing, the exhibit is
    the announcement. Pure."""
    out: dict[tuple[str, str], dict] = {}
    for h in hits:
        src = h.get("_source") or {}
        doc = str(h.get("_id") or "")
        adsh = src.get("adsh") or doc.split(":")[0]
        file_type = (src.get("file_type") or "").upper()
        for name in src.get("display_names") or []:
            m = _TICKERS.search(name)
            if not m:
                continue
            company = name[: m.start()].strip()
            cik = f"{int(m.group(2)):010d}"
            for t in m.group(1).split(","):
                t = t.strip().upper()
                if not t:
                    continue
                row = out.get((t, adsh))
                # The exhibit wins over the covering page when both matched.
                if row is not None and not file_type.startswith("EX-"):
                    continue
                out[(t, adsh)] = {"symbol": t, "accession": adsh, "cik": cik,
                                  "file_date": src.get("file_date"), "company": company,
                                  "document": doc.split(":", 1)[1] if ":" in doc else None,
                                  "is_exhibit": file_type.startswith("EX-")}
    return list(out.values())


def refresh_foreign_day(day: str) -> int:
    """Stamp every results 6-K filed on `day`. Returns how many rows."""
    found: dict[tuple[str, str], dict] = {}
    for phrase in _SIX_K_PHRASES:
        try:
            got = _search_text(day, phrase, "6-K")
        except Exception as exc:
            log.warning("EDGAR 6-K search failed for %s (%s): %s", day, phrase, exc)
            continue
        for row in foreign_candidates((got.get("hits") or {}).get("hits") or []):
            key = (row["symbol"], row["accession"])
            if row["is_exhibit"] or key not in found:
                found[key] = row
    # The day's sweep runs every quarter of an hour; a filing already read is
    # not read again, so the cost is one search plus the exhibits that are
    # new since the last pass.
    known = {(r["symbol"], r["accession"]) for r in store.releases_between(day, day)}
    stamped = 0
    for row in list(found.values())[:_SIX_K_MAX_READS]:
        if not row.get("document") or not row.get("file_date"):
            continue
        if (row["symbol"], row["accession"]) in known:
            continue
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/"
               f"{row['accession'].replace('-', '')}/{row['document']}")
        try:
            text = edgar.fetch_filing_text(url, max_chars=6_000) or ""
        except Exception as exc:
            log.debug("6-K exhibit text failed for %s %s: %s", row["symbol"], row["accession"], exc)
            continue
        if not is_results_release(text):
            continue
        released = dateline_day(text) or row["file_date"][:10]
        store.upsert_release(row["symbol"], row["accession"], row["cik"], row["file_date"],
                             None, row["company"], released, form="6-K")
        stamped += 1
    return stamped


def refresh_day(day: str) -> int:
    """Stamp every results 8-K filed on `day`. Returns how many rows."""
    rows: list[dict] = []
    for page in range(_MAX_PAGES):
        try:
            got = _search(day, page * _PAGE)
        except Exception as exc:
            log.warning("EDGAR search failed for %s page %d: %s", day, page, exc)
            break
        hits = (got.get("hits") or {}).get("hits") or []
        rows.extend(parse_hits(hits))
        if len(hits) < _PAGE:
            break
    for r in rows:
        store.upsert_release(r["symbol"], r["accession"], r["cik"], r["file_date"], None, r["company"],
                             r.get("event_date"), form="8-K")
    fill_times(day)
    # A foreign private issuer files no 8-K at all; its announcement is on a
    # 6-K and is found by its wording instead of by an item number.
    try:
        foreign = refresh_foreign_day(day)
    except Exception as exc:
        log.warning("6-K sweep failed for %s: %s", day, exc)
        foreign = 0
    return len(rows) + foreign


def fill_times(since: str) -> int:
    """The acceptance instant and the release day for releases that lack
    either: the instant from each filer's submissions record (one request per
    filer), the release day from it too when the date of report is the filing
    day, else from the 8-K's Item 2.02 text (one more request per such filing,
    its text cached)."""
    filled = 0
    by_symbol: dict[tuple[str, str], list[dict]] = {}
    for r in store.releases_missing_time(since):
        by_symbol.setdefault((r["symbol"], (r.get("form") or "8-K").upper()), []).append(r)
    for (sym, form), rows in by_symbol.items():
        try:
            filings = {f["accession"]: f for f in edgar.recent_filings(sym, forms=(form,), limit=20)}
        except Exception as exc:
            log.debug("submissions failed for %s: %s", sym, exc)
            continue
        for r in rows:
            f = filings.get(r["accession"])
            if not f:
                continue
            text = None
            rd = (f.get("report_date") or "")[:10]
            if form == "6-K":
                # The release day of a 6-K was read from the announcement's
                # own dateline when it was stamped; the submissions record
                # has no item numbers and no better date to offer. Only the
                # clock is wanted here.
                clock = None
                try:
                    clock = edgar.accepted_at_from_index(r.get("cik") or f["cik"], r["accession"])
                except Exception as exc:
                    log.debug("index header failed for %s %s: %s", sym, r["accession"], exc)
                store.set_release_clock(sym, r["accession"], clock or f.get("accepted_at"),
                                        "index" if clock else None)
                filled += 1
                continue
            if rd and rd < r["file_date"]:
                try:
                    from alphadesk.desk import filings as filing_text
                    text = filing_text.get_text(f["accession"], f["url"])
                except Exception as exc:
                    log.debug("8-K text failed for %s %s: %s", sym, f["accession"], exc)
            day = resolve_release_day(r["file_date"], rd or None, f.get("items"), text)
            # The clock from the filing's own index header: the submissions
            # record mislabels a same-day filing's New York time as UTC.
            clock, source = None, None
            try:
                clock = edgar.accepted_at_from_index(r.get("cik") or f["cik"], r["accession"])
                source = "index" if clock else None
            except Exception as exc:
                log.debug("index header failed for %s %s: %s", sym, r["accession"], exc)
            if clock is None:
                clock = f.get("accepted_at")
            store.set_release_clock(sym, r["accession"], clock, source)
            store.upsert_release(sym, r["accession"], r["cik"], r["file_date"], None, None, day)
            filled += 1
    return filled


def backfill(days: int = 7) -> int:
    n = 0
    d = date.today()
    for i in range(days):
        day = d - timedelta(days=i)
        if day.weekday() < 5:
            n += refresh_day(day.isoformat())
            time.sleep(0.2)
    return n


def releases_by_symbol(start: str, end: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in store.releases_between(start, end):
        out.setdefault(r["symbol"], []).append(r)
    return out
