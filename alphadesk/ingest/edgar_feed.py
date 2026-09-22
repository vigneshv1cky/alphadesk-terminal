"""THE MARKET'S FILINGS AS THEY LAND (2026-09-22) — EDGAR's own feed of what
has just been filed, market-wide, newest first.

Everything else here reads filings for ONE company, which answers "what has
this company filed" and never "what was just filed". A material event, a
stake, a tender offer and a priced offering are all catalysts with their own
clock, and the clock is the one fact this feed carries that a filing list
does not: EDGAR stamps each entry with its ACCEPTANCE TIME in New York, to
the second.

Keyless, like every other EDGAR surface — this is public government data,
not a vendor's, so the cache below is shared by every reader rather than
kept per reader (invariant 8's one carve-out, alongside the Treasury tile).

WHAT THE FORM STRINGS ACTUALLY ARE, measured 2026-09-22, because guessing
them wastes a request each time:

  * The `type` filter is a PREFIX MATCH, not an exact one. `type=4` returns
    424B2, which is not Form 4 — so a short string is a trap, and every
    group below is a prefix chosen to catch what it means and nothing else.
  * A stake is filed as "SCHEDULE 13D", NOT "SC 13D". Asking for "SC 13D"
    returns zero entries with no error, which reads exactly like a quiet day
    and is not one. `type=SC` catches the schedules AND the tender offers,
    which are catalysts too, in one request.
  * Asking with no type at all is one request for everything, but a page of
    100 was 60 structured-note prospectuses and three 8-Ks — the noise
    crowds the catalysts out, so the groups are fetched separately.
  * Repeated calls in quick succession draw 503s and timeouts. Each group is
    one request, they are paced by edgar._get, and the result is CACHED, so
    a board polling this does not become a queue of them.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import quote

from alphadesk.ingest import edgar

log = logging.getLogger("alphadesk.edgar_feed")

#: The catalyst groups, as the prefixes EDGAR actually answers to. The label
#: is what the group means, for a reader or an agent that has to choose one.
GROUPS: dict[str, dict] = {
    "events": {"type": "8-K", "label": "Material events (8-K)"},
    "stakes": {"type": "SC", "label": "Stakes and tender offers (Schedule 13D/G, SC TO, SC 14D9)"},
    "offerings": {"type": "424B", "label": "Priced offerings (424B)"},
    "registrations": {"type": "S-1", "label": "New registrations (S-1)"},
    "shelf": {"type": "S-3", "label": "Shelf registrations (S-3)"},
}

#: How long a group's page is kept. EDGAR publishes continuously and the feed
#: is the same for everyone, so this is a shared cache of public data. Three
#: minutes keeps a polling board to one request per group per three minutes.
KEEP_S = 180.0
#: Entries a group is asked for. Forty is one page and covers a busy hour of
#: 8-Ks; the caller pages no further, because a feed of what JUST landed
#: stops being that once it reaches back a day.
PAGE = 40
#: What `recent()` reads when no group is named. NOT everything, measured:
#: 424B2 structured-note prospectuses are about 60% of EDGAR's whole firehose
#: (a page of 100 held 60 of them and three 8-Ks), they arrive several a
#: minute from a handful of bank issuers, and they would bury every real
#: catalyst under themselves. Material events and stakes are the two groups
#: that are catalysts by construction; the offering groups are there to be
#: ASKED for, which is when they are worth reading.
DEFAULT_GROUPS = ("events", "stakes")

_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()
_cik_tickers: dict[str, list[str]] | None = None


def _tickers_by_cik() -> dict[str, list[str]]:
    """CIK -> every ticker the SEC lists against it. The ticker file maps the
    other way and one registrant can carry several share classes, so the
    inverse is built once and kept for the process, as the forward map is."""
    global _cik_tickers
    if _cik_tickers is not None:
        return _cik_tickers
    out: dict[str, list[str]] = {}
    for ticker, cik in edgar._ticker_cik_map().items():
        out.setdefault(cik, []).append(ticker)
    for tickers in out.values():
        tickers.sort()
    _cik_tickers = out
    return out


def parse_entries(xml: str) -> list[dict]:
    """EDGAR's atom entries as records. Pure.

    A title reads "FORM - COMPANY NAME (0001234567) (Filer)", and the ROLE at
    the end matters: a tender offer and a 13D are listed against the SUBJECT
    company as well as the filer, and it is the subject whose stock moves.
    An entry that names neither is still a filing and is kept, said plainly,
    rather than dropped for having an unfamiliar shape."""
    rows: list[dict] = []
    for chunk in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        title = re.search(r"<title>(.*?)</title>", chunk, re.S)
        updated = re.search(r"<updated>(.*?)</updated>", chunk, re.S)
        link = re.search(r'<link[^>]*href="(.*?)"', chunk)
        if not title or not updated:
            continue
        text = re.sub(r"\s+", " ", title.group(1)).strip()
        head = re.match(r"^(.*?)\s+-\s+(.*)$", text)
        if not head:
            continue
        form, rest = head.group(1).strip(), head.group(2).strip()
        cik = re.search(r"\((\d{7,10})\)", rest)
        role = re.search(r"\(([A-Za-z ]+)\)\s*$", rest)
        name = rest
        for cut in (cik, role):
            if cut:
                name = name.replace(cut.group(0), " ")
        url = link.group(1) if link else None
        # ".../0000929638-26-003584-index.htm" — the accession is what makes
        # one filing one row when it is listed under filer and subject both.
        accession = None
        if url:
            m = re.search(r"/(\d{10}-\d{2}-\d{6})-index", url)
            accession = m.group(1) if m else None
        rows.append({
            "form": form,
            "company": re.sub(r"\s{2,}", " ", name).strip(" -"),
            "cik": f"{int(cik.group(1)):010d}" if cik else None,
            "role": (role.group(1).strip().lower() if role else None),
            # EDGAR's own acceptance stamp, New York time, to the second.
            "filed_at": updated.group(1).strip(),
            "accession": accession,
            "url": url,
        })
    return rows


def _group(name: str) -> tuple[list[dict], float | None, str | None]:
    """One group's page: its rows, WHEN they were read, and why they could
    not be (2026-09-22).

    EDGAR answers a burst of requests with 503s and timeouts, so a group
    failing is ordinary rather than exceptional — and on a feed of what just
    happened, a group that could not be read must never be reported as a
    group with nothing in it. The last good page is handed back while EDGAR
    is unavailable, stamped with the time it was actually read, and the
    reason travels with it."""
    spec = GROUPS[name]
    with _lock:
        hit = _cache.get(name)
        if hit and time.time() - hit[0] < KEEP_S:
            return hit[1], hit[0], None
    url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
           f"&type={quote(spec['type'])}&company=&dateb=&owner=include"
           f"&count={PAGE}&output=atom")
    try:
        rows = parse_entries(edgar._get(url, timeout=30).decode("utf-8", "replace"))
    except Exception as exc:                      # a rate-limit block included
        log.info("edgar feed %s: %s", name, exc)
        with _lock:
            hit = _cache.get(name)
        return (hit[1] if hit else []), (hit[0] if hit else None), str(exc)[:200]
    for r in rows:
        r["group"] = name
    with _lock:
        _cache[name] = (time.time(), rows)
    return rows, time.time(), None


def tag_symbols(rows: list[dict]) -> list[dict]:
    """Each filing's registrant matched to the ticker(s) the SEC lists for
    it. Its own step rather than part of the fetch, so a row is tagged
    wherever it came from — a fresh page, a cached one, or a test."""
    by_cik = _tickers_by_cik()
    for r in rows:
        r["symbols"] = by_cik.get(r.get("cik") or "", [])
    return rows


def recent(groups: list[str] | None = None, limit: int = 50,
           symbol: str | None = None, listed_only: bool = True) -> dict:
    """What has just been filed, newest first.

    `groups` picks from GROUPS; the default is DEFAULT_GROUPS. `symbol` keeps
    only filings by a registrant the SEC lists that ticker against — which
    is exact, not a name match, and silent rather than approximate when the
    SEC lists no ticker for a filer (a fund, a trust, a foreign parent).

    `listed_only` keeps the filings whose registrant HAS a ticker. Measured
    2026-09-22: the 8-K feed's top is securitisation trusts and Federal Home
    Loan Banks, which file constantly and trade nowhere, so a catalyst feed
    without this reads as though nothing happened to any company. The count
    dropped is REPORTED rather than quietly applied — a filer the SEC lists
    no ticker for can still be a real company, so this is a convenience, not
    a judgement about what matters."""
    from datetime import datetime, timezone
    wanted = [g for g in (groups or DEFAULT_GROUPS) if g in GROUPS]
    if not wanted:
        wanted = list(DEFAULT_GROUPS)
    seen: dict[str, dict] = {}
    read_at: dict[str, str | None] = {}
    unavailable: dict[str, str] = {}
    for name in wanted:
        rows, at, why = _group(name)
        read_at[name] = (datetime.fromtimestamp(at, tz=timezone.utc).isoformat(timespec="seconds")
                         if at else None)
        if why:
            unavailable[name] = why
        for row in rows:
            # One filing is one row even when EDGAR lists it twice, under the
            # filer and the subject. The SUBJECT is the company whose stock
            # moves, so it wins the duplicate.
            key = row["accession"] or f"{row['form']}|{row['company']}|{row['filed_at']}"
            if key not in seen or row.get("role") == "subject":
                seen[key] = row
    rows = tag_symbols(sorted(seen.values(), key=lambda r: r["filed_at"], reverse=True))
    if symbol:
        want = edgar.sec_ticker(symbol).upper()
        rows = [r for r in rows if want in r["symbols"]]
    hidden = 0
    if listed_only and not symbol:
        listed = [r for r in rows if r["symbols"]]
        hidden, rows = len(rows) - len(listed), listed
    return {
        "filings": rows[:max(1, min(int(limit), 200))],
        # Filings whose registrant the SEC lists no ticker for — counted, so
        # a shorter list is never mistaken for a quieter market.
        "unlisted_hidden": hidden,
        "groups": {g: GROUPS[g]["label"] for g in wanted},
        # When each group was actually read, and which could not be — an
        # empty group and an unreadable one must never look alike here.
        "read_at": read_at,
        "unavailable": unavailable,
        # What this feed reaches back to, so "nothing since" is not read as
        # "nothing happened": each group is one page of the most recent.
        "oldest": rows[-1]["filed_at"] if rows else None,
        "count": len(rows),
    }


def reset_cache() -> None:
    with _lock:
        _cache.clear()


__all__ = ["DEFAULT_GROUPS", "GROUPS", "parse_entries", "recent", "reset_cache", "tag_symbols"]
