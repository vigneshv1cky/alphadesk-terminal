"""WHAT THE GOVERNMENT JUST DID (2026-09-22) — agency actions, the Federal
Reserve's own announcements, and Treasury auction results, in one shape.

Keyless: all three are public US government data, like EDGAR and the
Treasury yield curve, so the cache here is shared by every reader rather
than kept per reader.

THE THREE SOURCES, AND WHY THESE THREE:

  * THE FEDERAL REGISTER is the general one, and it is what makes this
    tractable. Every federal agency's rules, proposed rules and notices are
    published there under a documented API covering 473 agencies — so the
    Surface Transportation Board, the FDA, FERC, the EPA and the SEC are one
    query each rather than one scraper each. Without it, "regulators" is an
    unbounded list of one-off pages.
  * THE FEDERAL RESERVE publishes its own feed, and it carries the thing the
    Federal Register does not: an FOMC statement, at the minute it lands.
  * TREASURY AUCTIONS come from TreasuryDirect's own service, with the rate
    each auction struck.

TIME IS NOT THE SAME ON ALL THREE, and a catalyst is a claim about time, so
every row says which kind of stamp it carries. The Federal Register is a
DAILY publication: its stamp is a date, and a ruling is often announced
before it is published there. The Fed's and Treasury's rows carry a real
moment. `at_precision` is "day" or "second" and a caller that treats the
first as the second is wrong about when something happened.

WHAT IS DELIBERATELY NOT HERE: openFDA. Its drug endpoint cannot express
"approved this month" — the date filter matches an APPLICATION, not the
submission inside it, so a query for September 2026 returns applications
whose approval was in 1993 (measured 2026-09-22, 106 results, top rows
approved 2010, 2014 and 1993, and nearly all generics). FDA *rules* do
arrive through the Federal Register above; FDA *approvals* would need the
bulk dataset downloaded and filtered, which is a different job.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

log = logging.getLogger("alphadesk.gov_feed")

USER_AGENT = "AlphaDesk/1.0 (market research terminal)"
#: Public services with no plan metering us, so the pace is set for their
#: sake rather than ours, and one gate is shared across all three.
_MIN_GAP_S = 0.4
_gate = threading.Lock()
_last_at = 0.0
#: These publish on human schedules — daily, or a few times a day — so a
#: board polling them does not need a fresh read every time.
KEEP_S = 300.0
_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()

SOURCES = {
    "agencies": "Federal agency rules, proposed rules and notices (Federal Register)",
    "fed": "Federal Reserve announcements, including FOMC statements",
    "treasury": "Treasury auction results",
}


class GovUnavailable(RuntimeError):
    """This source could not be read. Never an empty result — a quiet day and
    an unreachable service must not look alike."""


def _fetch(url: str, timeout: float = 25.0) -> str:
    global _last_at
    with _gate:
        wait = _last_at + _MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_at = time.monotonic()
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, */*"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        raise GovUnavailable(f"refused ({exc.code})") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise GovUnavailable(f"unreachable: {exc}") from exc


def _event(source: str, kind: str, title: str, at: str, precision: str,
           url: str | None = None, **extra) -> dict:
    """One government action in the shape all three share. `at_precision`
    travels with every row because the sources do not agree on it."""
    return {"source": source, "kind": kind, "title": title, "at": at,
            "at_precision": precision, "url": url, **extra}


# ── the Federal Register ──────────────────────────────────────────────────

#: Agencies whose actions move listed companies, as the Federal Register's
#: own slugs. Not a complete list and not meant to be — it is the shortlist a
#: caller gets when it names none, and any of the service's 473 slugs may be
#: passed instead.
#:
#: THE FAA IS DELIBERATELY ABSENT (measured 2026-09-22): it filed 47 of the
#: 92 rules and proposed rules these agencies produced in a fortnight, nearly
#: all airworthiness directives naming one aircraft model, and it would have
#: been more than half of every answer. Ask for
#: "federal-aviation-administration" by name when that is what you want.
MARKET_AGENCIES = (
    "securities-and-exchange-commission",
    "federal-trade-commission",
    "food-and-drug-administration",
    "federal-communications-commission",
    "federal-energy-regulatory-commission",
    "surface-transportation-board",
    "environmental-protection-agency",
    "national-highway-traffic-safety-administration",
    "commodity-futures-trading-commission",
)

#: A notice is the bulk of the Federal Register and mostly routine; a rule
#: and a proposed rule are the ones that change what a company may do.
DOCUMENT_TYPES = ("RULE", "PRORULE", "NOTICE", "PRESDOCU")


def federal_register(agencies: list[str] | None = None, days: int = 7,
                     limit: int = 40, types: list[str] | None = None) -> list[dict]:
    """Agency actions published in the last `days`, newest first.

    The stamp is a PUBLICATION DATE, not a moment: the Federal Register comes
    out once a day, so a decision is frequently announced before it appears
    here. Every row says so."""
    picked = [a for a in (agencies or MARKET_AGENCIES) if re.fullmatch(r"[a-z0-9-]{2,80}", a or "")]
    kinds = [t for t in (types or ("RULE", "PRORULE")) if t in DOCUMENT_TYPES]
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))).date().isoformat()
    parts = [
        "per_page=" + str(max(1, min(limit, 100))),
        "order=newest",
        "conditions[publication_date][gte]=" + since,
        "fields[]=title", "fields[]=publication_date", "fields[]=type",
        "fields[]=agencies", "fields[]=html_url", "fields[]=abstract",
        "fields[]=document_number",
    ]
    parts += [f"conditions[agencies][]={quote(a)}" for a in picked]
    parts += [f"conditions[type][]={quote(k)}" for k in kinds]
    body = _fetch("https://www.federalregister.gov/api/v1/documents.json?" + "&".join(parts))
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise GovUnavailable(f"unreadable answer: {exc}") from exc
    out = []
    for r in data.get("results") or []:
        day = str(r.get("publication_date") or "")[:10]
        if not day or not r.get("title"):
            continue
        out.append(_event(
            "agencies", (r.get("type") or "Document"), str(r.get("title")).strip(),
            day, "day", r.get("html_url"),
            agencies=[a.get("name") for a in (r.get("agencies") or []) if a.get("name")],
            # The Register's own summary, verbatim and not ours.
            abstract=(r.get("abstract") or None),
            document_number=r.get("document_number"),
        ))
    return out


# ── the Federal Reserve ───────────────────────────────────────────────────

def fed_press(limit: int = 25) -> list[dict]:
    """The Board's own announcements, newest first — FOMC statements,
    enforcement actions, policy notices. These carry a real time."""
    body = _fetch("https://www.federalreserve.gov/feeds/press_all.xml")
    out = []
    for chunk in re.findall(r"<item>(.*?)</item>", body, re.S):
        def field(tag: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", chunk, re.S)
            text = (m.group(1) if m else "").strip()
            # The feed wraps several fields in CDATA, titles included.
            inner = re.match(r"^<!\[CDATA\[(.*?)\]\]>$", text, re.S)
            return (inner.group(1) if inner else text).strip()
        title, when = field("title"), field("pubDate")
        if not title or not when:
            continue
        at = _rfc822(when)
        if not at:
            continue
        out.append(_event("fed", "Press release", title, at, "second", field("link") or None))
    out.sort(key=lambda r: r["at"], reverse=True)
    return out[:max(1, min(limit, 100))]


def _rfc822(text: str) -> str | None:
    """"Fri, 18 Sep 2026 15:00:00 GMT" as an ISO instant. Pure."""
    from email.utils import parsedate_to_datetime
    try:
        at = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


# ── Treasury auctions ─────────────────────────────────────────────────────

def treasury_auctions(days: int = 7, limit: int = 25) -> list[dict]:
    """Auctions settled in the last `days`, newest first, with the rate each
    one struck. A bill that clears well above expectations is a rates
    catalyst, and the figure is the government's own."""
    body = _fetch("https://www.treasurydirect.gov/TA_WS/securities/auctioned"
                  f"?format=json&days={max(1, min(days, 90))}")
    try:
        rows = json.loads(body)
    except ValueError as exc:
        raise GovUnavailable(f"unreadable answer: {exc}") from exc
    out = []
    for r in rows if isinstance(rows, list) else []:
        day = str(r.get("auctionDate") or "")[:10]
        kind, term = r.get("securityType"), r.get("securityTerm")
        if not day or not kind:
            continue
        rate = r.get("highInvestmentRate") or r.get("highYield") or r.get("highDiscountRate")
        title = f"{term} {kind}".strip()
        out.append(_event("treasury", "Auction", title, day, "day",
                          None, cusip=r.get("cusip"),
                          # The government's own figure, as a number where it
                          # gave one and absent where the auction has not
                          # settled — never zero, which would read as a rate.
                          rate=_num(rate),
                          offering_amount=_num(r.get("offeringAmount")),
                          bid_to_cover=_num(r.get("bidToCoverRatio")),
                          issue_date=str(r.get("issueDate") or "")[:10] or None))
    out.sort(key=lambda r: r["at"], reverse=True)
    return out[:max(1, min(limit, 100))]


def _num(v) -> float | None:
    try:
        x = float(str(v).strip())
        return x if x == x else None
    except (TypeError, ValueError):
        return None


# ── together ──────────────────────────────────────────────────────────────

_READERS = {
    "agencies": lambda **kw: federal_register(agencies=kw.get("agencies"), days=kw.get("days", 7),
                                              limit=kw.get("limit", 40), types=kw.get("types")),
    "fed": lambda **kw: fed_press(limit=kw.get("limit", 25)),
    "treasury": lambda **kw: treasury_auctions(days=kw.get("days", 7), limit=kw.get("limit", 25)),
}


def recent(sources: list[str] | None = None, days: int = 7, limit: int = 50,
           agencies: list[str] | None = None, types: list[str] | None = None) -> dict:
    """Government action from the sources named, newest first.

    A source that could not be read is named in `unavailable` and never
    reported as a source with nothing in it."""
    wanted = [s for s in (sources or list(SOURCES)) if s in SOURCES]
    if not wanted:
        wanted = list(SOURCES)
    events: list[dict] = []
    read_at: dict[str, str | None] = {}
    unavailable: dict[str, str] = {}
    for name in wanted:
        key = f"{name}|{days}|{','.join(agencies or [])}|{','.join(types or [])}"
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < KEEP_S:
            events += hit[1]
            read_at[name] = _stamp(hit[0])
            continue
        try:
            rows = _READERS[name](days=days, limit=limit, agencies=agencies, types=types)
        except GovUnavailable as exc:
            log.info("gov feed %s: %s", name, exc)
            unavailable[name] = str(exc)
            read_at[name] = _stamp(hit[0]) if hit else None
            if hit:
                events += hit[1]
            continue
        with _lock:
            if len(_cache) > 256:
                _cache.clear()
            _cache[key] = (time.time(), rows)
        events += rows
        read_at[name] = _stamp(time.time())
    # A day-stamped row sorts against a second-stamped one on its date alone,
    # which is the most that can honestly be said about their order.
    events.sort(key=lambda r: r["at"], reverse=True)
    return {"events": events[:max(1, min(int(limit), 200))],
            "sources": {s: SOURCES[s] for s in wanted},
            "read_at": read_at, "unavailable": unavailable,
            "count": len(events)}


def _stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


def reset_cache() -> None:
    with _lock:
        _cache.clear()


__all__ = ["DOCUMENT_TYPES", "GovUnavailable", "MARKET_AGENCIES", "SOURCES",
           "fed_press", "federal_register", "recent", "reset_cache", "treasury_auctions"]
