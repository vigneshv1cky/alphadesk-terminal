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
        # PAGED, like the 8-K sweep. This asked for ONE page and EDGAR's
        # full-text search answers ten by default, so on 2026-09-21 the sweep
        # saw 10 of the 46 filings the phrase actually returned — ZJK
        # Industrial's results 6-K among the 36 it never looked at. Every
        # measurement of this sweep's coverage before 2026-09-28 was of a
        # fifth of its input.
        for page in range(_MAX_PAGES):
            try:
                got = _search_text(day, phrase, "6-K", page * _PAGE)
            except Exception as exc:
                log.warning("EDGAR 6-K search failed for %s (%s) page %d: %s", day, phrase, page, exc)
                break
            hits = (got.get("hits") or {}).get("hits") or []
            for row in foreign_candidates(hits):
                key = (row["symbol"], row["accession"])
                if row["is_exhibit"] or key not in found:
                    found[key] = row
            if len(hits) < _PAGE:
                break
    # The day's sweep runs every quarter of an hour; a filing already read is
    # not read again, so the cost is one search plus the exhibits that are
    # new since the last pass.
    known = {(r["symbol"], r["accession"]) for r in store.releases_between(day, day)}
    # SKIP FIRST, CAP SECOND (2026-09-28). The cap used to slice the candidate
    # list BEFORE the known filter, so every pass examined the same head and a
    # filing past the cap was not delayed but PERMANENTLY invisible — ZJK
    # Industrial's results 6-K sat in the search results all along, kept by
    # foreign_candidates, and was never once read. Same shape as the movers
    # fault in #91, where a cap on a sorted list meant nothing past the letter
    # T was ever asked about. Skipping what is already done first means each
    # pass makes progress through the backlog instead of re-doing its head.
    todo = [r for r in found.values()
            if r.get("document") and r.get("file_date")
            and (r["symbol"], r["accession"]) not in known]
    seen = store.exhibit_checked(sorted({r["accession"] for r in todo}), "6-K")
    todo = [r for r in todo if r["accession"] not in seen]
    stamped = 0
    for row in todo[:_SIX_K_MAX_READS]:
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/"
               f"{row['accession'].replace('-', '')}/{row['document']}")
        try:
            text = edgar.fetch_filing_text(url, max_chars=6_000) or ""
        except Exception as exc:
            log.debug("6-K exhibit text failed for %s %s: %s", row["symbol"], row["accession"], exc)
            continue
        hit = is_results_release(text)
        # A FILING MAY CARRY SEVERAL EXHIBITS, AND THE FIRST NEED NOT BE THE
        # ANNOUNCEMENT (2026-09-28). ZJK Industrial furnished three: 99.1 the
        # unaudited financial statements, 99.2 the operating review, and 99.3
        # the press release headed "Reports Financial Results for First Half
        # of Fiscal Year 2026". This read 99.1, correctly judged it not an
        # announcement, and dropped a real results release. The rest are
        # opened only when the first one fails, so a filing whose exhibit is
        # the announcement still costs exactly one fetch.
        if not hit:
            hit = _results_in_other_exhibits(row["cik"], row["accession"], row["document"])
        # Remember the verdict either way, so a 6-K that is not a results
        # release is never fetched a second time.
        store.mark_exhibit_checked(row["accession"], hit, "6-K")
        if not hit:
            continue
        released = dateline_day(text) or row["file_date"][:10]
        store.upsert_release(row["symbol"], row["accession"], row["cik"], row["file_date"],
                             None, row["company"], released, form="6-K")
        stamped += 1
    return stamped


def _results_in_other_exhibits(cik: str, accession: str, skip: str,
                               limit: int = 3) -> bool:
    """Does any OTHER exhibit of this filing announce results? Opened only
    after the first exhibit has failed, and capped: a filing with a dozen
    attachments must not become a dozen fetches."""
    import re
    adsh = (accession or "").replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh}/"
    try:
        idx = edgar._get(base).decode("utf-8", "ignore")
    except Exception as exc:
        log.debug("exhibit index unreadable for %s: %s", accession, exc)
        return False
    docs = [d for d in sorted(set(re.findall(r'href="[^"]*/([^/"]+\.htm)"', idx)))
            if re.search(r"ex-?_?99", d, re.I) and d != skip]
    for d in docs[:limit]:
        try:
            text = edgar.fetch_filing_text(base + d, max_chars=6_000) or ""
        except Exception:
            continue
        if is_results_release(text):
            return True
    return False

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
    # AND THE TWO WAYS A COMPANY REPORTS WITHOUT SAYING SO (2026-09-28).
    # Neither is obliged to announce itself: Item 2.02 is required only when
    # results go out by some other means first, so a filer that simply
    # publishes its 10-K owes no 8-K, and an 8-K whose substance is in an
    # exhibit need tag nothing but 9.01. Both were invisible, and both are
    # disproportionately the small companies no vendor lists either.
    # Each is wrapped on its own: neither may cost the day's 8-K sweep.
    try:
        periodic = refresh_periodic_day(day)
    except Exception as exc:
        log.warning("10-K/10-Q sweep failed for %s: %s", day, exc)
        periodic = 0
    try:
        exhibits = refresh_exhibit_day(day)
    except Exception as exc:
        log.warning("8-K exhibit sweep failed for %s: %s", day, exc)
        exhibits = 0
    return len(rows) + foreign + periodic + exhibits


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


# ── RESULTS PUBLISHED IN A PERIODIC REPORT (2026-09-28) ─────────────────────
# MEASURED, after the results feed came up a third short. Of 67 companies the
# calendar showed as having reported in one week, 23 had a vendor's actual and
# NO filing this sweep had found. Checking EDGAR directly for eight of them
# showed the sweep, not the vendors, was wrong — every one had filed:
#
#   Franklin Wireless  10-K 09-28     Espey Mfg      10-K 09-23
#   Amesite            10-K 09-23     Legacy Housing 10-K 09-24
#   Shineco            10-Q 09-24     ZJK Industrial  6-K 09-21
#   AnaptysBio          8-K 09-21 — filed, but carrying NO Item 2.02
#
# A COMPANY NEED NOT ANNOUNCE ON AN 8-K. Item 2.02 is required only when
# results are released by some other means first; a filer that simply
# publishes its 10-K or 10-Q has furnished them and owes no 8-K at all. The
# sweep looked only for Item 2.02, so every such company was invisible — and
# they are disproportionately the small filers no vendor lists either.
#
# ONLY WHERE THERE IS NO 8-K IN THE SURROUNDING QUARTER. A large company
# announces on an 8-K and files the 10-Q days later; counting both would put
# a second row on the calendar for one set of results. Requiring the company
# to have no Item 2.02 anywhere in ±PERIODIC_QUARTER_DAYS keeps this to the
# filers that never use them, which is the measured gap.
_PERIODIC_FORMS = ("10-K", "10-Q")
PERIODIC_QUARTER_DAYS = 45


def parse_periodic_hits(hits: list[dict]) -> list[dict]:
    """Search hits → one row per (ticker, filing). Unlike parse_hits there is
    no item number to test: a 10-K or 10-Q IS the results, so the form's
    presence is the whole signal. Pure."""
    out: dict[tuple[str, str], dict] = {}
    for h in hits:
        src = h.get("_source") or {}
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
                    out[(t, adsh)] = {"symbol": t, "accession": adsh, "cik": cik,
                                      "file_date": fd, "event_date": fd, "company": company,
                                      "form": (src.get("root_forms") or [None])[0] or src.get("file_type")}
    return list(out.values())


def _search_form(day: str, form: str, offset: int) -> dict:
    """Every filing of one form on one day. No phrase: the form filter alone
    is the query, the same shape the 8-K sweep uses."""
    q = urlencode({"forms": form, "dateRange": "custom", "startdt": day, "enddt": day, "from": offset})
    return json.loads(edgar._get(f"{_SEARCH}?{q}", timeout=30.0))


def refresh_periodic_day(day: str) -> int:
    """Store the day's 10-K and 10-Q filings as results releases, but only
    for companies with no Item 2.02 8-K in the surrounding quarter."""
    d = date.fromisoformat(day)
    lo = (d - timedelta(days=PERIODIC_QUARTER_DAYS)).isoformat()
    hi = (d + timedelta(days=PERIODIC_QUARTER_DAYS)).isoformat()
    # One read of what is already known, rather than a query per company.
    announced = {sym for sym, fs in releases_by_symbol(lo, hi).items()
                 if any((f.get("form") or "8-K") == "8-K" for f in fs)}
    stored = 0
    for form in _PERIODIC_FORMS:
        rows: list[dict] = []
        for page in range(_MAX_PAGES):
            try:
                got = _search_form(day, form, page * _PAGE)
            except Exception as exc:
                log.warning("EDGAR %s search failed for %s page %d: %s", form, day, page, exc)
                break
            hits = (got.get("hits") or {}).get("hits") or []
            rows.extend(parse_periodic_hits(hits))
            if len(hits) < _PAGE:
                break
        for r in rows:
            if r["symbol"] in announced:
                continue                      # it announced on an 8-K; one event, one row
            store.upsert_release(r["symbol"], r["accession"], r["cik"], r["file_date"],
                                 None, r["company"], r["event_date"], form=form)
            stored += 1
    return stored


# ── RESULTS THAT ONLY THE EXHIBIT KNOWS ABOUT (2026-09-28) ──────────────────
# Two filings the sweep missed turned out to have the same shape: the cover
# page and the item tags say nothing, and the results are in exhibit 99.1.
#
#   AnaptysBio  8-K 09-21, items "9.01" ALONE — no Item 2.02 — and the
#               exhibit reads "Anaptys Announces Second Quarter and
#               Transitional Fiscal Year 2026 Financial Results".
#   ZJK         6-K 09-21, which has no items at all and which the two
#               phrases the 6-K sweep searches for did not return.
#
# Item 2.02 is required only when results go out by some other means first,
# and a foreign issuer has no items to tag, so NEITHER filing was obliged to
# announce itself. `is_results_release()` already answers correctly for both
# — it was simply never given the text.
#
# THE COST IS CONTROLLED IN THREE WAYS, because reading exhibits is a fetch
# each and this runs every fifteen minutes:
#   * only items that could plausibly carry results (7.01 Reg FD, 8.01 Other
#     Events, or 9.01 alone). A 5.02 officer departure or a 1.01 agreement
#     never does, and those are most of the 110 a day that carry 9.01.
#   * only companies with NO release already stored for the quarter — the
#     large filers that announced on their own 8-K are already known, and
#     they are who most of the remainder are.
#   * a hard cap per day, so a heavy filing day cannot run away with the loop.
_EXHIBIT_ITEMS = {"9.01", "7.01", "8.01"}
EXHIBIT_READ_CAP = 40


def exhibit_candidates(hits: list[dict]) -> list[dict]:
    """8-K hits that might carry results in an exhibit: they attach one
    (9.01) and their other items are ones that could plausibly announce
    results, and none is Item 2.02, which the main sweep already has. Pure."""
    out: list[dict] = []
    for h in hits:
        src = h.get("_source") or {}
        items = set(src.get("items") or [])
        if not items or "2.02" in items or "9.01" not in items:
            continue
        if items - _EXHIBIT_ITEMS:
            continue
        out.append(h)
    return out


def _read_exhibit(cik: str, accession: str) -> str | None:
    """The filing's exhibit 99.x as text — where a press release lives."""
    import re
    adsh = (accession or "").replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh}/"
    try:
        idx = edgar._get(base).decode("utf-8", "ignore")
    except Exception as exc:
        log.debug("exhibit index unreadable for %s: %s", accession, exc)
        return None
    docs = [d for d in sorted(set(re.findall(r'href="[^"]*/([^/"]+\.htm)"', idx)))
            if re.search(r"ex-?_?99", d, re.I)]
    if not docs:
        return None
    return edgar.fetch_filing_text(base + docs[0], max_chars=20_000)


def refresh_exhibit_day(day: str, forms: tuple[str, ...] = ("8-K",)) -> int:
    """Store results releases whose only evidence is the exhibit."""
    d = date.fromisoformat(day)
    lo = (d - timedelta(days=PERIODIC_QUARTER_DAYS)).isoformat()
    hi = (d + timedelta(days=PERIODIC_QUARTER_DAYS)).isoformat()
    known = set(releases_by_symbol(lo, hi))
    stored = reads = 0
    for form in forms:
        hits: list[dict] = []
        for page in range(_MAX_PAGES):
            try:
                got = _search(day, page * _PAGE) if form == "8-K" else _search_form(day, form, page * _PAGE)
            except Exception as exc:
                log.warning("EDGAR %s sweep failed for %s page %d: %s", form, day, page, exc)
                break
            got_hits = (got.get("hits") or {}).get("hits") or []
            hits.extend(got_hits)
            if len(got_hits) < _PAGE:
                break
        # 8-Ks only: a 6-K reaches the same place through refresh_foreign_day,
        # whose phrase search already finds them — the cap there was hiding
        # them, not the search. Sweeping all ninety 6-Ks a day to re-find what
        # one fixed slice already returns is work for nothing.
        cands = exhibit_candidates(hits)
        rows = parse_periodic_hits(cands)
        # ONE READ PER FILING, EVER. A day carries about ninety 6-Ks and this
        # loop runs every fifteen minutes; without this the same ninety
        # exhibits would be fetched for ever. The cap below then bounds only
        # the FIRST pass over a day, not the steady state.
        seen = store.exhibit_checked(sorted({r["accession"] for r in rows}), "8-K")
        for r in rows:
            if r["symbol"] in known or r["accession"] in seen:
                continue
            if reads >= EXHIBIT_READ_CAP:
                break
            reads += 1
            seen.add(r["accession"])
            text = _read_exhibit(r["cik"], r["accession"])
            hit = bool(text) and is_results_release(text)
            store.mark_exhibit_checked(r["accession"], hit, "8-K")
            if not hit:
                continue
            store.upsert_release(r["symbol"], r["accession"], r["cik"], r["file_date"],
                                 None, r["company"], r["event_date"], form=form)
            known.add(r["symbol"])
            stored += 1
    return stored
