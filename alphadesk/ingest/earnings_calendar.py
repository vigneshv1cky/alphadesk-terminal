"""The earnings calendar for ONE user, built at request time from their own
calendar vendors (2026-09-13 — the shared calendar gathered from Nasdaq's
undocumented route is gone).

  1. Every connected vendor that carries an earnings calendar is asked for
     the window; the first to answer is the primary and the rest are
     unioned in (a company one vendor lists that another lacks is added; the
     same report on two dates within a few days is one report whose date
     moved).
  2. Companies are kept when they file with the SEC (EDGAR's ticker file),
     and named from it.
  3. Each report is joined to its results 8-K from the keyless EDGAR release
     table: `released_at` is EDGAR's acceptance instant. A results 8-K filed
     in the window by a company no vendor listed is a report too, added
     from EDGAR alone when it is a quarter's release (not a mid-quarter
     update or a deal closing).
  4. Volatility and liquidity come from the user's own daily bars — twenty
     sessions, one request for the whole window — and order each day, most
     traded first.

Nothing is stored per user: each vendor's answer is held in the user's own
vendor memo, and the EDGAR half is shared public data.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from alphadesk.providers.base import EntitlementError, NeedsKey, ProviderError

log = logging.getLogger("alphadesk.earnings_calendar")

LOW_LIQUIDITY_DOLLAR_VOL = 10_000_000


def _vendor_rows(router, start: str, end: str) -> list[tuple[str, list[dict]]]:
    got: list[tuple[str, list[dict]]] = []
    refused: list[str] = []
    order = router._order("earnings_calendar", "earnings_calendar")
    if not order:
        raise NeedsKey("earnings_calendar", [], signed_in=router.uid is not None)
    for name in order:
        try:
            rows = router.vendors[name].earnings_calendar(start, end)
        except EntitlementError:
            refused.append(name)
            continue
        except (ProviderError, NeedsKey) as exc:
            log.warning("%s earnings calendar failed: %s", name, exc)
            continue
        if rows is not None:
            got.append((name, rows))
    if not got:
        raise NeedsKey("earnings_calendar", refused, signed_in=router.uid is not None)
    return got


def combine(per_vendor: list[tuple[str, list[dict]]]) -> list[dict]:
    """The vendors' rows as one list: the first vendor's rows as primary,
    the others unioned in, moved reports collapsed. Pure."""
    from alphadesk.ingest.earnings import collapse_moved, union_calendars
    primary_name, primary = per_vendor[0]
    prim = [{**r, "sources": primary_name} for r in primary]
    others = [{**r, "source": name} for name, rows in per_vendor[1:] for r in rows]
    rows = union_calendars(prim, others) if others else [{**r, "sources": primary_name} for r in primary]
    kept, _dropped = collapse_moved(rows)
    return kept


# How far a vendor's date may sit from the results 8-K it stands for. A
# vendor date is usually a projection that runs EARLY — measured 2026-09-13:
# Finnhub listed Macy's on 09-01 and National Beverage on 09-03, filed 09-10
# and 09-11 — so a filing up to two weeks later is the same report. A filing
# more than a week earlier than the vendor's date is left alone: that is a
# company that pre-announced, or last quarter.
LATER_FILING_DAYS = 14
EARLIER_FILING_DAYS = 7
#: How far before a STILL-UPCOMING vendor date an earlier results 8-K may
#: still be that report. Beyond it the two are treated as different events
#: until an actual arrives (2026-09-15: Hub Group's 8-K of the 14th carried
#: preliminary figures for two restated quarters while its scheduled report
#: sat on the 17th; joining them moved the scheduled row onto the 14th,
#: marked it released with no actual, and emptied the 17th).
EARLY_RELEASE_DAYS = 1
MOVE_WINDOW_DAYS = LATER_FILING_DAYS




def _today_et() -> str:
    from alphadesk.config import now_et
    return now_et().date().isoformat()


def _actual_vendors(r: dict) -> list[str]:
    vendors = r.get("actual_vendors")
    return vendors if vendors is not None else [s for s in str(r.get("sources") or "").split(",") if s]


def _single_vendor_actual(r: dict) -> bool:
    """An actual only one vendor carries, with no results 8-K joined."""
    return (r.get("eps_actual") is not None and not r.get("released_on") and not r.get("released_at")
            and len(set(_actual_vendors(r))) < 2)


def _looks_like_placeholder(r: dict) -> bool:
    """One vendor's actual that is exactly its estimate: FMP filled NioCorp's
    actual with its estimate before any report (2026-09-14), and ZenaTech's
    the same day, to five decimals."""
    est = r.get("eps_estimate")
    return _single_vendor_actual(r) and est is not None and abs(r["eps_actual"] - est) < 1e-9


# Filings that show a company reported: a results 8-K, its periodic report
# (smaller companies release with the 10-K or 10-Q itself — American Battery
# Technology, 2026-09-14), or a foreign issuer's 6-K / annual report.
EVIDENCE_FORMS = ("8-K", "10-Q", "10-K", "10-Q/A", "10-K/A", "6-K", "6-K/A", "20-F", "40-F")
FOREIGN_ACTUAL_AFTER_DAYS = 1


def _evidence_lookup(symbol: str, report_date: str, today: str) -> bool:
    """Whether EDGAR shows the company reported: a filing of EVIDENCE_FORMS on
    the report date or the day after, or — for a foreign private issuer, whose
    6-K may come days later — the report date is FOREIGN_ACTUAL_AFTER_DAYS
    past. One submissions request; a failed lookup answers False."""
    from alphadesk.ingest import edgar
    try:
        filings = edgar.recent_filings(symbol, forms=EVIDENCE_FORMS, limit=40)
    except Exception as exc:                    # an EDGAR pause leaves the placeholder held, never breaks the calendar
        log.debug("filing evidence lookup failed for %s: %s", symbol, exc)
        return False
    day = date.fromisoformat(report_date[:10])
    near = {day.isoformat(), (day + timedelta(days=1)).isoformat()}
    if any((f.get("filing_date") or "")[:10] in near and (f.get("filing_date") or "")[:10] <= today for f in filings):
        return True
    return (edgar.classify_filer([f["form"] for f in filings]) is True
            and today >= (day + timedelta(days=FOREIGN_ACTUAL_AFTER_DAYS)).isoformat())


def actual_evidence(rows: list[dict], today: str, lookup=None, workers: int = 6) -> dict[str, bool]:
    """The filing-evidence answer for every row whose single-vendor actual
    looks like a placeholder, looked up `workers` at a time and paced by
    EDGAR's throttle. Only those rows are asked about: a week holds two or
    three."""
    from concurrent.futures import ThreadPoolExecutor
    lookup = lookup or _evidence_lookup
    wanted = sorted({(r["symbol"], r["report_date"][:10]) for r in rows if _looks_like_placeholder(r)})
    if not wanted:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        answers = list(pool.map(lambda w: lookup(w[0], w[1], today), wanted))
    return {sym: ok for (sym, _), ok in zip(wanted, answers)}


def settle_actuals(rows: list[dict], has_evidence=lambda symbol: False) -> None:
    """Which actuals count. Two vendors, or a results 8-K on EDGAR, settle it.
    One vendor's actual counts too, as the consumer calendars show it
    (2026-09-14, the owner's call: Yahoo shows American Battery Technology's
    -200% from one source), marked `actual_basis` "single_vendor" — unless
    it is exactly the vendor's estimate and `has_evidence` finds no filing
    to back it. That one is a placeholder: not shown as an actual, the report
    left pending, and kept as `placeholder_actual` for the page to explain.
    Runs after the EDGAR join."""
    for r in rows:
        if not _single_vendor_actual(r):
            continue
        vendors = _actual_vendors(r)
        source = vendors[0] if vendors else None
        if not _looks_like_placeholder(r) or has_evidence(r["symbol"]):
            r["actual_basis"] = "single_vendor"
            r["actual_source"] = source
            continue
        r["placeholder_actual"] = r["eps_actual"]
        r["placeholder_source"] = source
        r["eps_actual"] = None
        r["surprise_pct"] = None


def release_day(f: dict) -> str:
    """The day a results 8-K says the results came out: its date of report,
    or the filing day when that is not read yet."""
    return (f.get("event_date") or f["file_date"])[:10]


def release_clock(f: dict) -> str | None:
    """EDGAR's acceptance instant stands for the release time only when the
    8-K was filed the day it reports; a filing days later (allowed up to four
    business days) carries the filing's time, not the release's."""
    return f.get("accepted_at") if f["file_date"][:10] == release_day(f) else None


def join_releases(rows: list[dict], releases: dict[str, list[dict]], today: str | None = None) -> None:
    """Each report joined to the company's results 8-K whose RELEASE DAY is
    nearest the vendor's date — up to a week before it or two weeks after.
    The release day is the 8-K's date of report, not the day it was filed
    (2026-09-14: Optical Cable released on the 9th, as both vendors said, and
    filed on the 11th; moving to the filing day put it on the wrong day with
    the filing's 4:15 PM as its clock). A vendor date that disagrees with the
    release day moves to it, and the row says so (Finnhub listed Kroger on
    2026-09-09; its release was on the 11th).

    A RELEASE WELL BEFORE A DATE STILL TO COME is left alone while no actual
    has arrived: a company can put out preliminary or restated figures days
    before the quarter it is scheduled to report (Hub Group, 2026-09-15).
    The row keeps the vendor's date and remembers the earlier release, so the
    reader sees both the coming report and the 8-K that already landed. Once
    an actual arrives, or the scheduled day passes, the join goes ahead as
    before — an early reporter is still the same report. Pure."""
    for r in rows:
        day = date.fromisoformat(r["report_date"][:10])
        lo = (day - timedelta(days=EARLIER_FILING_DAYS)).isoformat()
        hi = (day + timedelta(days=LATER_FILING_DAYS)).isoformat()
        cands = sorted((x for x in releases.get(r["symbol"], []) if lo <= release_day(x) <= hi),
                       key=lambda x: (abs((date.fromisoformat(release_day(x)) - day).days),
                                      x.get("accepted_at") is None, release_day(x)))
        if not cands:
            continue
        hit = cands[0]
        released = release_day(hit)
        upcoming = today is not None and r["report_date"][:10] > today
        early = (date.fromisoformat(released) - day).days < -EARLY_RELEASE_DAYS
        if upcoming and early and r.get("eps_actual") is None:
            r["earlier_release_on"] = released
            continue
        # A FOREIGN ISSUER'S DATELINE IS ITS OWN CALENDAR (2026-09-16). ZTO
        # announced its second quarter on the evening of August 18 in New
        # York, where its shares trade, and datelined the release Shanghai,
        # August 19 — the same moment, one date each side of midnight. The
        # 6-K therefore confirms a vendor's date that is within a day of it
        # rather than moving the report onto the other day; further apart
        # than that and the filing still wins, as for any other company.
        abroad = (hit.get("form") or "").upper() == "6-K"
        nearby = abs((date.fromisoformat(released) - day).days) <= 1
        if released != day.isoformat() and not (abroad and nearby):
            r["vendor_date"] = r["report_date"]
            r["report_date"] = released
            r["date_from_edgar"] = True
        # The clock only when the filing's instant is the release's; a later
        # filing, or one whose instant is not read yet, is out with no time.
        # A 6-K filed the morning after an evening announcement abroad is not
        # the release's instant either, so a foreign filing kept beside its
        # vendor date carries no clock and cannot correct the session.
        r["released_at"] = None if (abroad and nearby) else release_clock(hit)
        r["released_on"] = released
        corrected = session_after_release(r.get("session"), bool(r.get("confirmed")), r["released_at"])
        if corrected != r.get("session"):
            if r.get("session"):
                r["vendor_session"] = r["session"]
            r["session"] = corrected
        r["filed_on"] = hit["file_date"][:10]
        r["filed_at"] = hit.get("accepted_at")
        r["release_accession"] = hit["accession"]


def merge_same_release(rows: list[dict]) -> list[dict]:
    """One row per results 8-K. Two vendors can date one report five days
    apart — too far for the union to call them the same — and the join then
    moves both onto the release (RFIL, 2026-09-14: Finnhub the 9th, FMP the
    14th). The row whose date needed no move is kept; the other lends it
    what it lacks and its source. Pure."""
    kept: dict[tuple[str, str], dict] = {}
    out: list[dict] = []
    for r in sorted(rows, key=lambda r: bool(r.get("date_from_edgar"))):
        acc = r.get("release_accession")
        key = (r["symbol"], acc) if acc else None
        if key is None or key not in kept:
            if key:
                kept[key] = r
            out.append(r)
            continue
        k = kept[key]
        for field in ("eps_estimate", "eps_actual", "surprise_pct", "estimate_count", "market_cap", "company_name"):
            if k.get(field) is None and r.get(field) is not None:
                k[field] = r[field]
        if k.get("session") not in ("BMO", "AMC") and r.get("session") in ("BMO", "AMC"):
            k["session"] = r["session"]
        k["confirmed"] = bool(k.get("confirmed")) or bool(r.get("confirmed"))
        if r.get("vendor_date") and not k.get("vendor_date"):
            k["vendor_date"] = r["vendor_date"]
        k["sources"] = ",".join(sorted(set(filter(None, f"{k.get('sources') or ''},{r.get('sources') or ''}".split(",")))))
    order = {id(r): i for i, r in enumerate(rows)}
    return sorted(out, key=lambda r: order[id(r)])


#: Where a session sits in the trading day. A row with no session at all
#: sorts with the middle of the day, which is where an unknown report is as
#: likely to land as anywhere.
_SESSION_ORDER = {"BMO": 0, "DAY": 1, "AMC": 2}


def session_after_release(vendor_session: str | None, vendor_confirmed: bool, accepted_at: str | None) -> str | None:
    """The session of a released report. EDGAR's acceptance instant is an
    UPPER BOUND on the release, not the release itself: a company files the
    8-K after its press release, sometimes hours after (America's Car-Mart,
    2026-09-09: before the open by Finnhub, 8-K at 2:53 PM). So a vendor's
    confirmed session stands when it is no later than the filing's; the
    filing's session replaces it when the vendor claims a LATER one (said
    after the close, filed at 6:59 AM) or named none. Pure."""
    clock = _session_from_clock(accepted_at)
    if clock is None:
        return vendor_session
    if vendor_confirmed and vendor_session in _SESSION_ORDER and _SESSION_ORDER[vendor_session] <= _SESSION_ORDER[clock]:
        return vendor_session
    return clock


def _session_from_clock(accepted_at: str | None) -> str | None:
    """BMO before 09:30 ET, AMC from 16:00, DAY between; None without a clock."""
    if not accepted_at:
        return None
    from datetime import datetime
    from alphadesk.config import ET
    t = datetime.fromisoformat(accepted_at).astimezone(ET)
    hm = t.hour * 60 + t.minute
    return "BMO" if hm < 9 * 60 + 30 else "AMC" if hm >= 16 * 60 else "DAY"


# A results 8-K is a QUARTER's release only when the company's previous one
# (or its previous 10-Q) is at least this far back. Item 2.02 also covers
# mid-quarter updates and deal closings — measured 2026-09-13: Group 1
# Automotive filed one 40 days after its July results, Plains All American a
# month after its 10-Q, PWCM five in three months, CYCN inside a merger
# closing. A vendor-listed row needs no such check; the vendor corroborates it.
MIN_QUARTER_GAP_DAYS = 50
_periodic_cache: dict[tuple[str, str], bool] = {}


def is_quarter_release(filed_on: str, earlier: list[dict]) -> bool:
    """Whether a results 8-K filed on `filed_on` is a quarter's release, given
    the company's filings (8-K with items, 10-Q). Filings within a week of it
    are the same event (the 10-Q beside the release). No earlier filing — a
    new registrant — passes. Pure."""
    day = date.fromisoformat(filed_on)
    cutoff = (day - timedelta(days=EARLIER_FILING_DAYS)).isoformat()
    prior = [f["filing_date"] for f in earlier
             if f["filing_date"] < cutoff and (f["form"].startswith("10-Q") or "2.02" in (f.get("items") or ""))]
    if not prior:
        return True
    return (day - date.fromisoformat(max(prior))).days >= MIN_QUARTER_GAP_DAYS


def quarter_release(symbol: str, filed_on: str) -> bool:
    """`is_quarter_release` over EDGAR's filing list, cached per filing — a
    filed release does not change. A failed fetch is not cached."""
    key = (symbol, filed_on)
    if key in _periodic_cache:
        return _periodic_cache[key]
    from alphadesk.ingest import edgar
    filings = edgar.recent_filings(symbol, forms=("8-K", "8-K/A", "10-Q", "10-Q/A"), limit=60)
    ok = is_quarter_release(filed_on, filings)
    if filings:
        _periodic_cache[key] = ok
    return ok


def edgar_only_rows(rows: list[dict], releases: dict[str, list[dict]], start: str, end: str,
                    listed: dict[str, str]) -> list[dict]:
    """Reports no vendor listed, from results 8-Ks filed in [start, end]
    (measured 2026-09-13: Apnimed, Barnes & Noble Education, Braveheart Bio
    and Reformation filed that week and Finnhub listed none of them).

    One row per company: a CIK filing under several tickers (ORCL and its
    preferred ORCL-PD) takes the common one, and a company that already has
    a row within a week of the filing is not added twice. Pure."""
    cik_of = lambda sym: listed.get(sym)                       # noqa: E731
    have: dict[str, list[date]] = {}
    for r in rows:
        cik = cik_of(r["symbol"]) or r["symbol"]
        have.setdefault(cik, []).append(date.fromisoformat((r.get("released_on") or r["report_date"])[:10]))
    by_cik: dict[str, list[dict]] = {}
    for sym, filings in releases.items():
        if sym not in listed:
            continue
        for f in filings:
            if start <= release_day(f) <= end:
                by_cik.setdefault(f.get("cik") or listed[sym], []).append({**f, "symbol": sym})
    out: list[dict] = []
    for cik, filings in by_cik.items():
        filings.sort(key=lambda f: (release_day(f), f.get("accepted_at") is None, "-" in f["symbol"], len(f["symbol"]), f["symbol"]))
        taken: list[date] = list(have.get(cik, []))
        for f in filings:
            day = date.fromisoformat(release_day(f))
            if any(abs((day - d).days) <= EARLIER_FILING_DAYS for d in taken):
                continue
            taken.append(day)
            out.append({
                "symbol": f["symbol"], "report_date": release_day(f),
                "session": _session_from_clock(release_clock(f)),
                "confirmed": True, "eps_estimate": None, "eps_actual": None,
                "company_name": None, "sources": "edgar", "edgar_only": True,
                "released_at": release_clock(f), "released_on": release_day(f),
                "filed_on": f["file_date"][:10], "filed_at": f.get("accepted_at"),
                "release_accession": f["accession"],
            })
    return out


FORECAST_AHEAD_DAYS = 28
_captured: dict[tuple, bool] = {}


def forecast_rows(rows: list[dict], today: str) -> list[dict]:
    """A vendor's upcoming reports worth recording: dated today through four
    weeks ahead, one per company — the confirmed row, else the earliest —
    as the calendar would show it. Pure."""
    hi = (date.fromisoformat(today) + timedelta(days=FORECAST_AHEAD_DAYS)).isoformat()
    best: dict[str, dict] = {}
    for r in rows:
        d = (r.get("report_date") or "")[:10]
        if not d or not (today <= d <= hi):
            continue
        cur = best.get(r["symbol"])
        if cur is None or (bool(r.get("confirmed")), -date.fromisoformat(d).toordinal()) > \
                (bool(cur.get("confirmed")), -date.fromisoformat(cur["report_date"][:10]).toordinal()):
            best[r["symbol"]] = r
    return list(best.values())


def _capture_forecasts(router, per_vendor: list[tuple[str, list[dict]]], combined: list[dict],
                       span: tuple[str, str]) -> None:
    """Record what the reader's vendors — and their merged calendar — say
    about upcoming reports: at most once an hour per vendor and window, so a
    board refreshing every five minutes keeps the day's latest word without
    rewriting it each time. Captured when the reader's own calendar is built,
    on their keys, under their account; nothing runs in the background for
    it. A failure never costs the calendar."""
    if not router.uid:
        return
    try:
        from alphadesk.config import now_et
        from alphadesk.ledger import store
        now = now_et()
        today = now.date().isoformat()
        for name, rows in [*per_vendor, ("calendar", combined)]:
            key = (router.uid, name, today, now.hour, span)
            if _captured.get(key):
                continue
            picked = forecast_rows(rows, today)
            if picked:
                store.save_forecasts(router.uid, name, today, picked)
            _captured[key] = True
        if len(_captured) > 5000:
            _captured.clear()
    except Exception as exc:
        log.warning("earnings forecast capture failed: %s", exc)


def capture_daily(uid: str) -> dict[str, int]:
    """The forecast log's daily capture for one reader (2026-09-14): their
    calendar vendors asked once for today through four weeks ahead, each
    vendor's answer and the merged calendar recorded under that reader. Runs
    from the background loop under the reader's own identity, on their keys —
    the one keyed market-data call made without a request, so the log does
    not depend on the reader opening the calendar that day. Returns rows
    recorded per vendor; empty when the reader has no calendar vendor."""
    from alphadesk import identity as ai_llm
    from alphadesk.config import now_et
    from alphadesk.ledger import store
    from alphadesk.providers import get_prices
    token = ai_llm.set_request_user(uid)
    try:
        router = get_prices()
        today = now_et().date()
        hi = (today + timedelta(days=FORECAST_AHEAD_DAYS)).isoformat()
        try:
            per_vendor = _vendor_rows(router, today.isoformat(), hi)
        except NeedsKey:
            return {}
        counts: dict[str, int] = {}
        for name, rows in [*per_vendor, ("calendar", combine(per_vendor))]:
            counts[name] = store.save_forecasts(uid, name, today.isoformat(), forecast_rows(rows, today.isoformat()))
        # Warm this week's calendar in the same process: the SEC lookups behind
        # predicted sessions and foreign-filer actuals are cached a day, so the
        # reader's first open of the Earnings page does not pay for them.
        try:
            sunday = today - timedelta(days=today.isoweekday() % 7)
            rows_between(sunday.isoformat(), (sunday + timedelta(days=6)).isoformat(), stats=False)
        except Exception as exc:
            log.debug("calendar warm-up failed for %s: %s", uid[:8], exc)
        return counts
    finally:
        ai_llm.reset_request_user(token)


# ── Parity with the consumer calendars (2026-09-14) ─────────────────────────
# Measured against Yahoo's AlphaSpace calendar for Sep 14–18: its 47 reports
# were a clean list; ours had 85 more, mostly OTC foreign ordinaries, warrants
# and preferred series of companies already listed.

_OTC_EXCHANGES = {"OTC", ""}


def listing_kind(symbol: str, cik_of: dict[str, str], tickers_of_cik: dict[str, list[str]], exchange: str | None) -> str:
    """"primary" for a company's main exchange listing; "secondary" for its
    other tickers (warrants, preferreds, a second share class — OCCI's OCCIM,
    NEWT's NEWTG, LEN's LEN-B); "otc" for an over-the-counter listing. One
    primary per company: the shortest ticker without a dash, then alphabetical.
    Pure."""
    sym = symbol.upper()
    if str(exchange or "").upper() in _OTC_EXCHANGES:
        return "otc"
    cik = cik_of.get(sym)
    siblings = [t for t in tickers_of_cik.get(cik, []) if t != sym] if cik else []
    if siblings:
        primary = min([sym, *siblings], key=lambda t: ("-" in t, len(t), t))
        if primary != sym:
            return "secondary"
    return "primary"


SPLIT_ADJUST_DAYS = 30


def adjust_for_splits(rows: list[dict], splits: list[dict]) -> None:
    """A vendor estimate quoted on the pre-split share count, rescaled when
    the company split within SPLIT_ADJUST_DAYS before its report (or on the
    day). Measured 2026-09-14: Ocean Power's 1-for-30 reverse split took
    effect that morning, and both FMP (−0.03) and Finnhub (−0.0306) still
    quoted the old count, while the consumer calendar showed −0.90. A split
    of `to` new shares for every `from` old ones divides per-share figures by
    to/from. The original is kept. Pure."""
    by_sym: dict[str, list[dict]] = {}
    for sp in splits:
        if sp.get("from") and sp.get("to"):
            by_sym.setdefault(str(sp["symbol"]).upper(), []).append(sp)
    for r in rows:
        est = r.get("eps_estimate")
        if est is None or r.get("eps_actual") is not None:
            continue
        day = date.fromisoformat(r["report_date"][:10])
        for sp in by_sym.get(r["symbol"], []):
            eff = date.fromisoformat(str(sp["date"])[:10])
            if day - timedelta(days=SPLIT_ADJUST_DAYS) <= eff <= day:
                factor = sp["from"] / sp["to"]
                r["eps_estimate_unadjusted"] = est
                r["eps_estimate"] = round(est * factor, 4)
                r["split_note"] = f"{sp['to']:g}-for-{sp['from']:g} split on {eff.isoformat()}"
                break


def timing_from_history(release_sessions: list[str]) -> str | None:
    """The session a company will most likely report in, from the sessions of
    its recent quarterly results 8-Ks filed the day of release (newest
    first, up to four). A filing time is an upper bound on the release: an
    8-K accepted before the open means a pre-market release, one accepted
    after 16:00 an after-close release unless the company filed late in the
    day. A habit is three of the last four, or both of two when that is all
    the history there is (Forgent: two releases, both before the open). Pure."""
    recent = [s for s in release_sessions[:4] if s in ("BMO", "AMC", "DAY")]
    for s in ("BMO", "AMC"):
        if len(recent) >= 3 and recent.count(s) >= 3:
            return s
        if len(recent) == 2 and recent.count(s) == 2:
            return s
    return None


_habit_cache: dict[str, tuple[float, str | None, int]] = {}
_HABIT_TTL_S = 86_400


def foreign_release_sessions(filings: list[dict], report_dates: list[str]) -> list[str]:
    """Sessions of a foreign filer's past releases: for each past report date
    a vendor recorded (newest first), the earliest 6-K the company filed that
    day. A foreign private issuer furnishes its results on a 6-K the day it
    releases them, but a 6-K carries no item codes, so the vendor's date is
    what says which one it was. Pure."""
    by_day: dict[str, list[str]] = {}
    for f in filings:
        if f.get("form") in ("6-K", "6-K/A") and f.get("accepted_at"):
            by_day.setdefault(f["filing_date"][:10], []).append(f["accepted_at"])
    out = []
    for d in report_dates:
        clocks = sorted(by_day.get(d[:10], []))
        if clocks:
            out.append(_session_from_clock(clocks[0]))
    return out


def _release_habit(symbol: str, past_report_dates=None) -> tuple[str | None, int]:
    """(predicted session, how many past releases it rests on) from EDGAR:
    the company's quarterly results 8-Ks, or — for a foreign filer — its 6-Ks
    on the report dates `past_report_dates(symbol)` returns. One submissions
    request per company (plus one vendor record for a foreign filer), cached
    a day in memory. Raises when EDGAR or the vendor cannot be asked."""
    import time as _time
    from alphadesk.ingest import edgar
    sym = symbol.upper()
    hit = _habit_cache.get(sym)
    if hit and _time.time() - hit[0] < _HABIT_TTL_S:
        return hit[1], hit[2]
    # A failed lookup raises, so the caller can tell "no history" (stored)
    # from "could not ask" (asked again next time).
    filings = edgar.recent_filings(sym, forms=("8-K", "6-K", "6-K/A", "10-Q", "10-K", "20-F", "40-F"), limit=120)
    today = _today_et()
    if edgar.classify_filer([f["form"] for f in filings]) and past_report_dates is not None:
        dates = [d for d in past_report_dates(sym) if d < today][:4]
        sessions = foreign_release_sessions(filings, dates)
        predicted = timing_from_history(sessions)
        _habit_cache[sym] = (_time.time(), predicted, min(len(sessions), 4))
        return predicted, min(len(sessions), 4)
    sessions = []
    last_kept: date | None = None
    for f in (x for x in filings if x.get("form") == "8-K"):      # newest first
        # Settled history only: a same-day entry in the submissions record can
        # carry a mislabelled clock (see edgar._accepted_at).
        if "2.02" not in (f.get("items") or "") or not f.get("accepted_at") or f["filing_date"] >= today:
            continue
        if (f.get("report_date") or f["filing_date"])[:10] != f["filing_date"][:10]:
            continue
        # One release per quarter: an Item 2.02 within MIN_QUARTER_GAP_DAYS of
        # the next newer one kept is a preannouncement or an update, whose
        # timing says nothing about the quarter's release (Kestra, Dec 2025).
        filed = date.fromisoformat(f["filing_date"][:10])
        if last_kept is not None and (last_kept - filed).days < MIN_QUARTER_GAP_DAYS:
            continue
        last_kept = filed
        sessions.append(_session_from_clock(f["accepted_at"]))
    predicted = timing_from_history(sessions)
    if len(_habit_cache) > 20_000:
        _habit_cache.clear()
    _habit_cache[sym] = (_time.time(), predicted, min(len(sessions), 4))
    return predicted, min(len(sessions), 4)


def _needs_prediction(r: dict, today: str) -> bool:
    """An upcoming primary listing, not released, with no confirmed
    before/after-market session."""
    return (r["report_date"][:10] >= today and not r.get("released_on") and r.get("eps_actual") is None
            and not (r.get("confirmed") and r.get("session") in ("BMO", "AMC"))
            and r.get("listing", "primary") == "primary")


def predict_sessions(rows: list[dict], habit, today: str | None = None) -> None:
    """For an upcoming report (today or later) with no confirmed before/after-
    market session and no release yet, the company's usual session from its
    SEC history, marked as a prediction. A vendor's confirmed session always
    wins; a passed date is not predicted."""
    today = today or _today_et()
    for r in rows:
        if not _needs_prediction(r, today):
            continue
        predicted, basis = habit(r["symbol"])
        if predicted:
            r["session_predicted"] = predicted
            r["session_basis"] = basis


# A company's release habit changes a quarter at a time; kept this long in the
# database so a fresh server does not ask EDGAR again for every upcoming
# report (measured 2026-09-14: 47 lookups, 15 of a cold build's 25 seconds).
HABIT_KEEP_DAYS = 3
HABIT_WORKERS = 6


# A week in earnings season needs hundreds of lookups (316 for Oct 19–23),
# most of a minute at EDGAR's pace: past this many, the page returns with the
# stored habits and the rest are filled in the background.
HABIT_BLOCK_LIMIT = 24
BACKGROUND_WORKERS = 2


def release_habits_for(router, rows: list[dict], past_report_dates,
                       pending: dict | None = None) -> dict[str, tuple[str | None, int]]:
    """The usual session of every company `predict_sessions` would ask about:
    the reader's stored habits computed within HABIT_KEEP_DAYS, the rest
    looked up HABIT_WORKERS at a time (EDGAR's throttle still paces them) and
    stored under the reader — the foreign-filer habit rests on their vendor's
    report dates. A lookup that fails is left out, not stored. When more than
    HABIT_BLOCK_LIMIT are missing, they are looked up in the background
    instead and counted in `pending["timing"]`."""
    from alphadesk.config import now_et
    from alphadesk.ingest import background_fill
    from alphadesk.ledger import store
    today = _today_et()
    wanted = sorted({r["symbol"].upper() for r in rows if _needs_prediction(r, today)})
    if not wanted:
        return {}
    got: dict[str, tuple[str | None, int]] = {}
    if router.uid:
        since = (now_et() - timedelta(days=HABIT_KEEP_DAYS)).isoformat()
        try:
            got = store.release_habits(router.uid, wanted, since)
        except Exception as exc:
            log.debug("stored release habits unavailable: %s", exc)
    missing = [s for s in wanted if s not in got
               and not (router.uid and background_fill.recently_failed("timing", router.uid, s))]
    if router.uid and len(missing) > HABIT_BLOCK_LIMIT:
        # Stored a batch at a time, so a page asking again sees the week fill
        # in; fewer workers, so a reader's own page requests still get EDGAR's
        # turn between them.
        background_fill.submit("timing", router.uid, missing, lambda syms: [
            _lookup_habits(router, syms[i:i + HABIT_BLOCK_LIMIT], past_report_dates, workers=BACKGROUND_WORKERS)
            for i in range(0, len(syms), HABIT_BLOCK_LIMIT)])
        if pending is not None:
            pending["timing"] = len(missing)
        return got
    return {**got, **_lookup_habits(router, missing, past_report_dates)}


def _lookup_habits(router, symbols: list[str], past_report_dates,
                   workers: int = HABIT_WORKERS) -> dict[str, tuple[str | None, int]]:
    """Look up and store the habits of `symbols`, `workers` at a time."""
    from concurrent.futures import ThreadPoolExecutor

    from alphadesk.identity import reset_request_user, set_request_user
    from alphadesk.config import now_et
    from alphadesk.ingest import background_fill
    from alphadesk.ledger import store
    if not symbols:
        return {}

    def one(sym: str):
        token = set_request_user(router.uid)
        try:
            return sym, _release_habit(sym, past_report_dates)
        except Exception as exc:
            log.debug("release habit failed for %s: %s", sym, exc)
            return sym, None
        finally:
            reset_request_user(token)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, symbols))
    fresh = {sym: h for sym, h in results if h is not None}
    if router.uid:
        background_fill.note_failed("timing", router.uid, [sym for sym, h in results if h is None])
        if fresh:
            try:
                store.save_release_habits(router.uid, fresh, now_et().isoformat())
            except Exception as exc:
                log.debug("release habits not stored: %s", exc)
    return fresh


def store_announcements(router, start: str, end: str) -> list[dict]:
    """The reader's stored announcements for reports in [start, end]."""
    if not router.uid:
        return []
    from alphadesk.ledger import store
    try:
        return store.announcements_between(router.uid, start, end)
    except Exception as exc:
        log.debug("announcements unavailable: %s", exc)
        return []


def _mark_listings(rows: list[dict], listed: dict[str, str]) -> None:
    from alphadesk.config import symbol_meta
    tickers_of_cik: dict[str, list[str]] = {}
    for t, c in (listed or {}).items():
        tickers_of_cik.setdefault(c, []).append(t)
    for r in rows:
        meta = symbol_meta(r["symbol"]) or {}
        r["listing"] = listing_kind(r["symbol"], listed or {}, tickers_of_cik, meta.get("exchange"))


def rows_between(start: str, end: str, *, stats: bool = True, pending: dict | None = None) -> list[dict]:
    """Every report the user's vendors list in [start, end]. Raises NeedsKey
    when no connected vendor carries an earnings calendar. Lookups too many to
    wait for are filled in the background and counted in `pending`."""
    from alphadesk.ingest import edgar, edgar_releases
    from alphadesk.ingest.movers import stats_from_bars
    from alphadesk.providers import get_prices
    router = get_prices()
    # The vendors are asked for a wider span than the window: a report a
    # vendor dates two weeks early still lands here once its 8-K is joined.
    fetch_lo = (date.fromisoformat(start) - timedelta(days=LATER_FILING_DAYS)).isoformat()
    fetch_hi = (date.fromisoformat(end) + timedelta(days=EARLIER_FILING_DAYS)).isoformat()
    per_vendor = _vendor_rows(router, fetch_lo, fetch_hi)
    rows = combine(per_vendor)
    _capture_forecasts(router, per_vendor, rows, (fetch_lo, fetch_hi))
    listed = edgar._ticker_cik_map()
    if listed:
        rows = [r for r in rows if r["symbol"] in listed]
    for r in rows:
        r["company_name"] = r.get("company_name") or edgar.company_title(r["symbol"])
        est, act = r.get("eps_estimate"), r.get("eps_actual")
        if r.get("surprise_pct") is None and act is not None and est not in (None, 0):
            r["surprise_pct"] = round((act - est) / abs(est) * 100, 2)
        r.setdefault("surprise_pct", None)
        r.setdefault("market_cap", None)
        r.setdefault("estimate_count", None)
        r.setdefault("actual_at", None)
        r.setdefault("released_at", None)
        r["confirmed"] = bool(r.get("confirmed")) or act is not None
    # The company's own word on when it reports, before the EDGAR join: a
    # stored announcement from the reader's feeds, or — for the window's
    # upcoming rows no vendor has timed — each company's recent press releases.
    from alphadesk.ingest import earnings_announcements as ea
    anns = store_announcements(router, fetch_lo, fetch_hi)
    open_rows = [r for r in rows if start <= r["report_date"][:10] <= end and r["report_date"][:10] >= _today_et()
                 and r.get("eps_actual") is None and not (r.get("confirmed") and r.get("session") in ("BMO", "AMC"))
                 and r["symbol"] not in {a["symbol"] for a in anns}]
    if open_rows:
        anns += ea.for_symbols(router, sorted({r["symbol"] for r in open_rows}), router.uid,
                               pending=pending, block_limit=ea.BLOCK_LIMIT)
    ea.apply_announcements(rows, anns)
    lo = (date.fromisoformat(fetch_lo) - timedelta(days=EARLIER_FILING_DAYS)).isoformat()
    hi = (date.fromisoformat(fetch_hi) + timedelta(days=LATER_FILING_DAYS)).isoformat()
    releases = edgar_releases.releases_by_symbol(lo, hi)
    join_releases(rows, releases, today=_today_et())
    rows = merge_same_release(rows)
    # A report moved onto its filing day may now sit outside the window.
    rows = [r for r in rows if start <= r["report_date"][:10] <= end]
    # Settled on the window's rows only: the foreign-filer check is an EDGAR
    # request per company, and the fetch span is five weeks wide.
    evidence = actual_evidence(rows, _today_et())
    settle_actuals(rows, lambda sym: evidence.get(sym, False))
    if listed:
        for r in edgar_only_rows(rows, releases, start, end, listed):
            if not quarter_release(r["symbol"], r["report_date"]):
                continue
            r["company_name"] = edgar.company_title(r["symbol"])
            r["surprise_pct"] = r["market_cap"] = r["estimate_count"] = r["actual_at"] = None
            rows.append(r)
    if listed:
        for r in ea.announced_rows(rows, anns, start, end, listed):
            r["company_name"] = edgar.company_title(r["symbol"])
            for k in ("surprise_pct", "market_cap", "estimate_count", "actual_at", "released_at"):
                r[k] = None
            rows.append(r)
    for r in rows:
        r.setdefault("released_on", None)
        if r["released_at"] or r["released_on"]:
            r["confirmed"] = True
    _mark_listings(rows, listed)
    try:
        from alphadesk.ingest.corporate_calendars import split_rows
        got, _vendors = split_rows(router, (date.fromisoformat(start) - timedelta(days=SPLIT_ADJUST_DAYS)).isoformat(), end)
        # A split one of two vendors lists alone rescales nothing: FMP listed
        # six that never took effect (2026-09-14). With one vendor there is
        # nothing to check it against, and its splits stand.
        splits = [sp for sp in got if sp.get("corroborated") is not False]
    except Exception as exc:
        log.debug("split calendar unavailable for estimates: %s", exc)
        splits = []
    adjust_for_splits(rows, splits)

    def past_report_dates(sym: str) -> list[str]:
        """The company's past report dates with an actual, newest first, from
        the reader's calendar vendors' own record of it."""
        got = router.get("earnings_history", sym) or {}
        return sorted({r["date"][:10] for r in got.get("reports", []) if r.get("eps_actual") is not None}, reverse=True)
    habits = release_habits_for(router, rows, past_report_dates, pending)
    predict_sessions(rows, habit=lambda s: habits.get(s.upper(), (None, 0)))
    if stats and rows:
        # Company size orders each day, largest first (2026-09-14, the owner's
        # call): the reports a reader weighs first are the biggest companies'.
        caps = router.get("market_caps", sorted({r["symbol"] for r in rows})) or {}
        for r in rows:
            r["market_cap"] = r.get("market_cap") or caps.get(r["symbol"].upper())
        bars = router.get("daily_history", sorted({r["symbol"] for r in rows}), 21) or {}
        for r in rows:
            b = bars.get(r["symbol"]) or []
            st = stats_from_bars([x["close"] for x in b], [x["volume"] for x in b]) if b else {"volatility": None, "liquidity": None}
            r["volatility"], r["liquidity"] = st["volatility"], st["liquidity"]
            r["low_liquidity"] = (st["liquidity"] < LOW_LIQUIDITY_DOLLAR_VOL) if st["liquidity"] is not None else None
    else:
        for r in rows:
            r.setdefault("volatility", None)
            r.setdefault("liquidity", None)
            r.setdefault("low_liquidity", None)
    # Largest company first within a day; a company with no market value on
    # the reader's vendors follows, most traded first.
    rows.sort(key=lambda r: (r["report_date"], r.get("market_cap") is None, -(r.get("market_cap") or 0),
                             -(r.get("liquidity") or 0), r["symbol"]))
    return rows


#: A built week, kept briefly per reader. THE WEEK WAS REBUILT ON EVERY
#: REQUEST (2026-09-16): 2.5 seconds of vendor calls and joins, paid by the
#: Earnings page, by its neighbouring-week prefetch, and — because the left
#: rail counts this week's reports — by every other page in the terminal,
#: on every navigation. The inputs are vendor calendars and filings that
#: move in minutes at best, so a minute of memory costs nothing and takes
#: the cost off all of them. Keyed by reader, like every other cache here,
#: because the rows rest on that reader's vendors.
_week_cache: dict[tuple[str, str], tuple[float, dict]] = {}
WEEK_KEEP_S = 60


def _week_cached(owner: str, sunday: str) -> Optional[dict]:
    import time as _time
    hit = _week_cache.get((owner, sunday))
    return hit[1] if hit and _time.time() - hit[0] < WEEK_KEEP_S else None


def _week_store(owner: str, sunday: str, built: dict) -> None:
    import time as _time
    if len(_week_cache) > 400:
        _week_cache.clear()
    _week_cache[(owner, sunday)] = (_time.time(), built)


def week(start: Optional[str] = None) -> dict:
    """One Sunday-to-Saturday week, day by day — the Earnings page's shape.
    Held for a minute per reader; see the note above the cache."""
    from alphadesk.config import now_et
    anchor = date.fromisoformat(start) if start else now_et().date()
    sunday = anchor - timedelta(days=anchor.isoweekday() % 7)
    saturday = sunday + timedelta(days=6)
    from alphadesk.providers import get_prices
    owner = get_prices().owner
    ready = _week_cached(owner, sunday.isoformat())
    if ready is not None:
        return ready
    pending: dict[str, int] = {}
    rows = rows_between(sunday.isoformat(), saturday.isoformat(), pending=pending)
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r["report_date"][:10], []).append(r)
    days = []
    for i in range(7):
        d = sunday + timedelta(days=i)
        key = d.isoformat()
        days.append({"date": key, "weekday": d.strftime("%a"), "count": len(by_day.get(key, [])), "rows": by_day.get(key, [])})
    built = {"start": sunday.isoformat(), "end": saturday.isoformat(), "today": now_et().date().isoformat(),
             "days": days, "pending": pending}
    # A week still waiting on background lookups is NOT kept: it is asked
    # again every few seconds precisely so those fill in.
    if not any(pending.values()):
        _week_store(owner, sunday.isoformat(), built)
    return built


def upcoming(days: int = 7) -> list[dict]:
    """Reports from today through `days` ahead, for the screener and agent
    tools. Empty (never raises) when the user has no calendar vendor — the
    screener still has its headlines."""
    from alphadesk.config import now_et
    today = now_et().date()
    try:
        return rows_between(today.isoformat(), (today + timedelta(days=days)).isoformat(), stats=False)
    except NeedsKey:
        return []


def recently_reported(days: int = 3) -> list[dict]:
    from alphadesk.config import now_et
    today = now_et().date()
    try:
        rows = rows_between((today - timedelta(days=days)).isoformat(), today.isoformat(), stats=False)
    except NeedsKey:
        return []
    return [r for r in rows if r.get("eps_actual") is not None or r.get("released_at")]


FIND_BACK_DAYS = 120
FIND_AHEAD_DAYS = 120


def _vendor_rows_for(router, symbol: str, start: str, end: str) -> list[tuple[str, list[dict]]]:
    """One company's rows from every calendar vendor, asked for that symbol
    alone (a vendor that ignores the filter is filtered here)."""
    got: list[tuple[str, list[dict]]] = []
    refused: list[str] = []
    order = router._order("earnings_calendar", "earnings_calendar")
    if not order:
        raise NeedsKey("earnings_calendar", [], signed_in=router.uid is not None)
    for name in order:
        try:
            rows = router.vendors[name].earnings_calendar(start, end, symbol=symbol)
        except EntitlementError:
            refused.append(name)
            continue
        except (ProviderError, NeedsKey) as exc:
            log.warning("%s earnings calendar for %s failed: %s", name, symbol, exc)
            continue
        if rows is not None:
            got.append((name, [r for r in rows if r.get("symbol") == symbol and r.get("report_date")]))
    if not got:
        raise NeedsKey("earnings_calendar", refused, signed_in=router.uid is not None)
    return got


def pick_report(reports: list[dict], today: str) -> dict | None:
    """The report the finder jumps to: the one nearest today, the upcoming
    one on a tie. Pure."""
    if not reports:
        return None
    t = date.fromisoformat(today)
    return min(reports, key=lambda r: (abs((date.fromisoformat(r["report_date"][:10]) - t).days),
                                      r["report_date"] < today))


def find(symbol: str, today: Optional[str] = None) -> dict:
    """Every report one company has in the user's calendar vendors from four
    months back to four months ahead, dated the way the week view dates it
    (moved onto its results 8-K, or added from EDGAR alone), and the one the
    calendar should open on. A symbol that is not an SEC filer has none — the
    week view does not list it either."""
    from alphadesk.config import now_et
    from alphadesk.ingest import edgar, edgar_releases
    from alphadesk.providers import get_prices
    sym = symbol.upper()
    today = today or now_et().date().isoformat()
    t = date.fromisoformat(today)
    lo = (t - timedelta(days=FIND_BACK_DAYS)).isoformat()
    hi = (t + timedelta(days=FIND_AHEAD_DAYS)).isoformat()
    router = get_prices()
    per_vendor = _vendor_rows_for(router, sym, lo, hi)
    listed = edgar._ticker_cik_map()
    name = edgar.company_title(sym)
    if listed and sym not in listed:
        return {"symbol": sym, "company_name": name, "listed": False, "reports": [], "pick": None,
                "start": lo, "end": hi}
    rows = combine(per_vendor) if any(r for _, r in per_vendor) else []
    # Dated like the week view: the company's own announcement first.
    from alphadesk.ingest import earnings_announcements as ea
    anns = [a for a in store_announcements(router, lo, hi) if a["symbol"] == sym]
    if not anns and any(r["report_date"][:10] >= today and r.get("eps_actual") is None
                        and not (r.get("confirmed") and r.get("session") in ("BMO", "AMC")) for r in rows):
        anns = ea.for_symbols(router, [sym], router.uid)
    ea.apply_announcements(rows, anns)
    releases = {k: v for k, v in edgar_releases.releases_by_symbol(
        (t - timedelta(days=FIND_BACK_DAYS + LATER_FILING_DAYS)).isoformat(),
        (t + timedelta(days=FIND_AHEAD_DAYS + LATER_FILING_DAYS)).isoformat()).items() if k == sym}
    join_releases(rows, releases, today=today)
    rows = merge_same_release(rows)
    evidence = actual_evidence(rows, today)
    settle_actuals(rows, lambda sym: evidence.get(sym, False))
    rows = [r for r in rows if lo <= r["report_date"][:10] <= hi]
    if listed:
        rows += [r for r in edgar_only_rows(rows, releases, lo, hi, listed) if quarter_release(sym, r["report_date"])]
        rows += ea.announced_rows(rows, anns, max(lo, today), hi, listed)
    reports = sorted(({"report_date": r["report_date"][:10], "session": r.get("session"),
                       "confirmed": bool(r.get("confirmed")) or bool(r.get("released_at") or r.get("released_on")),
                       "eps_estimate": r.get("eps_estimate"), "eps_actual": r.get("eps_actual"),
                       "placeholder_actual": r.get("placeholder_actual"), "placeholder_source": r.get("placeholder_source"),
                       "actual_basis": r.get("actual_basis"), "actual_source": r.get("actual_source"),
                       "released_at": r.get("released_at"), "released_on": r.get("released_on"),
                       "vendor_date": r.get("vendor_date"), "edgar_only": bool(r.get("edgar_only")),
                       "date_from_edgar": bool(r.get("date_from_edgar")), "announcement": r.get("announcement")}
                      for r in rows), key=lambda r: r["report_date"])
    chosen = pick_report(reports, today)
    return {"symbol": sym, "company_name": name, "listed": True, "reports": reports,
            "pick": chosen["report_date"] if chosen else None, "start": lo, "end": hi}


def report_row(symbol: str, report_date: str) -> dict | None:
    try:
        for r in rows_between(report_date, report_date, stats=False):
            if r["symbol"] == symbol.upper():
                return r
    except NeedsKey:
        return None
    return None
