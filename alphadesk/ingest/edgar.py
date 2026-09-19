"""SEC EDGAR — free, no API key, no vendor. The document layer under
desk/filings.py.

Every endpoint here is a plain SEC-hosted JSON/HTML file, verified live
against real filings before this was written (see commit history — Apple's
CIK, its actual 10-Q shape, the full-text search param names). Two facts
that are easy to get wrong and will silently 403/empty-result you if you do:

  1. SEC requires a descriptive User-Agent with contact info on every request
     (`SEC_USER_AGENT`, see `_user_agent()`) — generic or missing gets
     throttled or blocked. There is no safe default; each deployment sets it.
  2. Modern filings are inline XBRL: financial data tags are woven into the
     human-readable HTML, not a separate file. A naive tag-strip regex
     produces garbage near the document's XBRL-heavy front matter; this uses
     BeautifulSoup's get_text() instead, which handles it cleanly.
"""

import logging
from datetime import datetime, timezone
import os
import re
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("alphadesk.edgar")

def _user_agent() -> str:
    """SEC requires a descriptive User-Agent with real contact info on every
    request, and throttles or blocks generic ones.

    This MUST be configured per deployment. It used to be one maintainer's
    address hardcoded — which meant every fork would have hammered EDGAR under
    his name and could have got him rate-limited for someone else's traffic.
    """
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if ua:
        return ua
    if not _user_agent._warned:                      # type: ignore[attr-defined]
        log.warning(
            "SEC_USER_AGENT is not set. SEC asks for a descriptive User-Agent with "
            "contact info (e.g. 'AlphaDesk (you@example.com)') and throttles requests "
            "without one — filings may fail or be slow until you set it.")
        _user_agent._warned = True                   # type: ignore[attr-defined]
    return "AlphaDesk (contact not configured; set SEC_USER_AGENT)"


_user_agent._warned = False                          # type: ignore[attr-defined]
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{doc}"

# SEC allows 10 requests a second PER IP ADDRESS and blocks an address that
# goes over for about ten minutes. Every reader's EDGAR traffic and the
# background loops leave from the server's address, so this is a
# process-wide pace, not a per-caller one.
#
# THE PACE IS RESERVED UNDER A LOCK (2026-09-14). The old check-the-timer-
# then-sleep let concurrent callers — 40 request threads, two loops — all
# read the same last-request time and send together, bursting past the
# limit exactly when several readers opened pages at once. Now each caller
# takes the next free send slot under the lock and sleeps outside it, so
# sends are spaced by _MIN_INTERVAL_S however many threads ask.
_MIN_INTERVAL_S = 0.15
_pace_lock = threading.Lock()
_next_slot = 0.0

# A BLOCK IS HONOURED, NOT RETRIED INTO. When SEC answers "Request Rate
# Threshold Exceeded" (HTTP 403, or 429), every EDGAR call fails fast for
# _BLOCK_COOLDOWN_S instead of reaching SEC — ten minutes, SEC's own block
# length. Nothing is sent during the pause, so it cannot prolong SEC's block;
# a rate-limited answer after it restarts the pause. Callers already degrade
# on an exception (no filings, no release times), which is what a reader sees
# for those minutes either way.
_BLOCK_COOLDOWN_S = 600.0
_blocked_until = 0.0
_RATE_LIMIT_MARKERS = ("request rate threshold exceeded", "rate threshold", "too many requests")


class EdgarRateLimited(Exception):
    """SEC is refusing this address for going over its request rate; no
    request is sent until the cooldown ends."""


def rate_limit_status() -> dict:
    """Whether EDGAR calls are paused by a rate-limit block, and until when —
    for the System page and logs."""
    left = _blocked_until - time.monotonic()
    return {"blocked": left > 0, "seconds_left": round(max(0.0, left)), "min_interval_s": _MIN_INTERVAL_S}


def _is_rate_limited(code: int, body: bytes) -> bool:
    if code == 429:
        return True
    if code != 403:
        return False
    text = body[:4000].decode("utf-8", "replace").lower()
    return any(m in text for m in _RATE_LIMIT_MARKERS)


def _reserve_slot() -> float:
    """The next send time for this caller, reserved under the lock."""
    global _next_slot
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + _MIN_INTERVAL_S
        return slot

_ticker_cik_cache: dict[str, str] | None = None


def _get(url: str, timeout: float = 15.0) -> bytes:
    """One EDGAR request, paced process-wide and refused outright while a
    rate-limit block is in force. Raises EdgarRateLimited during a block."""
    global _blocked_until
    if time.monotonic() < _blocked_until:
        raise EdgarRateLimited(f"SEC EDGAR paused for {round(_blocked_until - time.monotonic())}s after a rate-limit block")
    wait = _reserve_slot() - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    if time.monotonic() < _blocked_until:          # a block landed while this caller waited its turn
        raise EdgarRateLimited("SEC EDGAR paused after a rate-limit block")
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            pass
        if _is_rate_limited(exc.code, body):
            first = time.monotonic() >= _blocked_until
            _blocked_until = time.monotonic() + _BLOCK_COOLDOWN_S
            if first:
                log.warning("SEC EDGAR rate-limited this address (HTTP %s); pausing EDGAR calls for %ds",
                            exc.code, int(_BLOCK_COOLDOWN_S))
            raise EdgarRateLimited(f"SEC EDGAR rate limit (HTTP {exc.code})") from exc
        raise


def _ticker_cik_map() -> dict[str, str]:
    """ticker -> zero-padded 10-digit CIK. One ~1MB file, cached for the
    process lifetime — SEC updates it a few times a day at most."""
    global _ticker_cik_cache
    if _ticker_cik_cache is not None:
        return _ticker_cik_cache
    import json
    try:
        data = json.loads(_get(_TICKER_MAP_URL))
        _ticker_cik_cache = {
            v["ticker"].upper(): f"{int(v['cik_str']):010d}" for v in data.values()
        }
        _ticker_title_cache.update({v["ticker"].upper(): v.get("title") for v in data.values() if v.get("title")})
    except Exception as exc:
        log.warning("EDGAR ticker map fetch failed: %s", exc)
        _ticker_cik_cache = {}
    return _ticker_cik_cache


def sec_ticker(symbol: str) -> str:
    """A share-class ticker in the SEC list's spelling. The SEC writes the
    class after a hyphen ("BRK-B"); Alpaca, FMP and Finnhub write a dot
    ("BRK.B") and some feeds a slash, so a Berkshire page opened from a
    vendor's list had no filings, annual report or facts (2026-09-19). Pure."""
    return re.sub(r"[./](?=[A-Z0-9]{1,2}$)", "-", (symbol or "").upper())


def cik_for(symbol: str) -> str | None:
    return _ticker_cik_map().get(sec_ticker(symbol))


_ticker_title_cache: dict[str, str] = {}


def company_title(symbol: str) -> str | None:
    """The registrant's name from the same ticker file ("Apple Inc.")."""
    _ticker_cik_map()
    return _ticker_title_cache.get(sec_ticker(symbol))


_INDEX_HEADER = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{accession}-index-headers.html"
_ACCEPTANCE = re.compile(r"ACCEPTANCE-DATETIME>\s*(\d{14})")


def index_accepted_at(header_text: str) -> str | None:
    """A filing's acceptance instant from its index header, ISO with the New
    York offset. The header's ACCEPTANCE-DATETIME is New York local time and
    is consistent, unlike the submissions record (below). Pure."""
    m = _ACCEPTANCE.search(header_text or "")
    if not m:
        return None
    try:
        from zoneinfo import ZoneInfo
        local = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("America/New_York"))
        return local.isoformat()
    except ValueError:
        return None


def accepted_at_from_index(cik: str, accession: str) -> str | None:
    """The authoritative acceptance instant of one filing (one request)."""
    url = _INDEX_HEADER.format(cik=int(cik), nodash=accession.replace("-", ""), accession=accession)
    return index_accepted_at(_get(url).decode("utf-8", "replace"))


def _accepted_at(raw: str | None, file_date: str | None = None) -> str | None:
    """EDGAR's acceptanceDateTime as an instant in New York time.

    THE SAME-DAY ENTRY IS NEW YORK TIME WEARING A UTC SUFFIX. Measured on
    four filings (2026-09-14 and 2026-09-15): Hub Group's 8-K read
    "06:02:45.000Z" the morning its index header said 06:02:45 ET; Forgent
    (06:40:38), Innventure (09:01:20) and Sculptor (16:36:37) all matched
    their index headers digit for digit on the day they were filed. Older
    entries are true UTC — the same Hub Group filings from August and June
    convert to the index header exactly.

    So a filing dated TODAY keeps its digits and is stamped New York; an
    older one is read as UTC and converted. Without the rule an after-close
    release filed at 16:30 read as 12:30 and was labelled "during the day"
    (the earnings calendar's EDGAR-only rows and foreign-filer sessions both
    read this clock). Release clocks for the results table come from the
    index header regardless — exact, one request, already paid for there."""
    if not raw:
        return None
    try:
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        if file_date and file_date[:10] == datetime.now(ny).date().isoformat():
            # Same day: the digits are already market time.
            return instant.replace(tzinfo=ny, microsecond=0).isoformat()
        return instant.astimezone(ny).replace(microsecond=0).isoformat()
    except (ValueError, TypeError):
        return None


# The forms the filings Q&A can quote from: narrative documents whose text
# a verbatim citation can be checked against. Amendments carry the same
# prose as the original, so they read too (Apple's 8-K/A of 2026-09-01 was
# the first one missed, 2026-09-11).
READABLE_FORMS: frozenset[str] = frozenset({
    "10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A",
    "20-F", "20-F/A", "6-K", "6-K/A", "DEF 14A",
})
# Listed for completeness but never picked for the Q&A: ownership forms are
# XML tables (Form 3/4/5 insider statements, Form 144 sale notices, 13D/13G
# holder notices) with nothing to quote. Their trades reach the Insider
# trades tile through ingest/insider.py instead.
LISTED_ONLY_FORMS: frozenset[str] = frozenset({
    "3", "3/A", "4", "4/A", "5", "5/A", "144", "144/A",
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",
})
DEFAULT_FORMS: tuple[str, ...] = tuple(sorted(READABLE_FORMS | LISTED_ONLY_FORMS))


def is_readable(form: str | None) -> bool:
    """Whether the filings Q&A can answer against this form's text."""
    return (form or "") in READABLE_FORMS


_FOREIGN_FORMS = ("20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A")
_DOMESTIC_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")
_foreign_cache: dict[str, tuple[float, bool, float]] = {}
_FOREIGN_TTL_S = 86_400
_UNKNOWN_TTL_S = 3_600


def classify_filer(forms: list[str]) -> bool | None:
    """True for a foreign private issuer (reports on 20-F/40-F and 6-K, never
    a 10-K or 10-Q), False for a domestic filer, None when the record says
    neither. Pure."""
    fs = set(forms)
    if fs & set(_DOMESTIC_FORMS):
        return False
    if fs & set(_FOREIGN_FORMS):
        return True
    return None


def is_foreign_filer(symbol: str) -> bool:
    """Whether a company files as a foreign private issuer — it furnishes
    results on a 6-K, which carries no item codes, so EDGAR cannot confirm
    its release the way an 8-K Item 2.02 does. One submissions request per
    company, held a day; a failed or empty lookup answers False uncached."""
    sym = symbol.upper()
    hit = _foreign_cache.get(sym)
    if hit and time.time() - hit[0] < hit[2]:
        return hit[1]
    rows = recent_filings(sym, forms=_FOREIGN_FORMS + _DOMESTIC_FORMS, limit=80)
    verdict = classify_filer([r["form"] for r in rows])
    if len(_foreign_cache) > 20_000:
        _foreign_cache.clear()
    # An empty record (no CIK, a fetch that failed, an EDGAR pause) is held an
    # hour rather than a day, so it is asked again soon but not on every load.
    _foreign_cache[sym] = (time.time(), bool(verdict), _FOREIGN_TTL_S if verdict is not None else _UNKNOWN_TTL_S)
    return bool(verdict)


def recent_filings(symbol: str, forms: tuple[str, ...] | None = None,
                   limit: int = 40) -> list[dict]:
    """This symbol's most recent filings of the given forms, newest first.
    Each: {accession, symbol, cik, form, filing_date, report_date,
    primary_doc, url, readable}. `forms=None` lists everything in
    DEFAULT_FORMS — the narrative documents plus the ownership forms, so the
    list matches what EDGAR's own page shows rather than a curated subset.
    Empty list (never raises) if the symbol has no CIK or the fetch fails —
    the caller degrades to 'no filings found', not a 500."""
    if forms is None:
        forms = DEFAULT_FORMS
    cik10 = cik_for(symbol)
    if not cik10:
        return []
    return filings_for_cik(cik10, symbol, forms, limit)


def filings_for_cik(cik10: str, symbol: str, forms: tuple[str, ...],
                    limit: int = 40) -> list[dict]:
    """recent_filings for a registrant named by CIK rather than ticker —
    a predecessor whose ticker has moved to its successor (below)."""
    import json
    try:
        data = json.loads(_get(_SUBMISSIONS_URL.format(cik10=cik10)))
    except Exception as exc:
        log.warning("EDGAR submissions fetch failed for %s: %s", symbol, exc)
        return []
    recent = (data.get("filings") or {}).get("recent") or {}
    n = len(recent.get("form") or [])
    cik_int = str(int(cik10))   # archive URLs use the CIK unpadded
    out = []
    for i in range(n):
        form = recent["form"][i]
        if form not in forms:
            continue
        accession = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i]
        out.append({
            "accession": accession,
            "symbol": symbol.upper(),
            "cik": cik10,
            "form": form,
            "filing_date": recent["filingDate"][i],
            "report_date": recent.get("reportDate", [None] * n)[i],
            # The 8-K item codes ("2.02,9.01"): 2.02 is Results of Operations,
            # which is how a results release is told apart from any other 8-K.
            "items": (recent.get("items") or [""] * n)[i] or "",
            # When EDGAR accepted it — minutes after the press release for
            # an earnings 8-K, which is how "the report is out" is known
            # long before any calendar backfills a number.
            "accepted_at": _accepted_at((recent.get("acceptanceDateTime") or [None] * n)[i],
                                        (recent.get("filingDate") or [None] * n)[i]),
            "readable": is_readable(form),
            "primary_doc": doc,
            "url": _ARCHIVE_URL.format(
                cik=cik_int, accession_nodash=accession.replace("-", ""), doc=doc),
        })
        if len(out) >= limit:
            break
    return out


_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
# Revenue as companies tag it, newest standard first; a filer moves between
# these over the years (Apple: SalesRevenueNet to 2018, Revenues for a
# year, RevenueFromContractWithCustomer since), so all three are read.
_REVENUE_TAGS = ("RevenueFromContractWithCustomerIncludingAssessedTax", "RevenueFromContractWithCustomerExcludingAssessedTax",
                 "Revenues", "SalesRevenueNet")
_facts_cache: dict[str, tuple[float, dict[str, float]]] = {}
_FACTS_TTL_S = 24 * 3600


def quarterly_revenue(symbol: str) -> dict[str, float]:
    """Revenue per fiscal quarter, as filed, keyed by the quarter's end
    date (ISO) — from the SEC's company-facts feed, free and no key.
    The 10-Q rows carry three-month durations directly; the fourth quarter
    is never filed on its own, so it is the 10-K's fiscal-year figure
    minus the three quarters that closed inside that year, and only when
    all three are on hand. Empty (never raises) when the symbol has no
    CIK, no revenue tag, or the fetch fails. Cached a day."""
    sym = symbol.upper()
    hit = _facts_cache.get(sym)
    if hit and time.monotonic() - hit[0] < _FACTS_TTL_S:
        return hit[1]
    out: dict[str, float] = {}
    cik10 = cik_for(sym)
    if cik10:
        import json
        from datetime import date
        try:
            gaap = (json.loads(_get(_FACTS_URL.format(cik10=cik10), timeout=30.0))
                    .get("facts") or {}).get("us-gaap") or {}
        except Exception as exc:
            log.warning("EDGAR company facts fetch failed for %s: %s", sym, exc)
            gaap = {}

        def _days(v) -> int | None:
            try:
                return (date.fromisoformat(v["end"]) - date.fromisoformat(v["start"])).days
            except (KeyError, TypeError, ValueError):
                return None

        quarters: dict[str, float] = {}
        years: dict[str, tuple[str, float]] = {}     # end -> (start, value)
        for tag in reversed(_REVENUE_TAGS):           # newest tag wins on overlap
            for v in ((gaap.get(tag) or {}).get("units") or {}).get("USD") or []:
                if v.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
                    continue
                d = _days(v)
                if d is None or not isinstance(v.get("val"), (int, float)):
                    continue
                if 80 <= d <= 100:
                    quarters[v["end"]] = float(v["val"])
                elif 350 <= d <= 380:
                    years[v["end"]] = (v["start"], float(v["val"]))
        for end, (start, total) in years.items():
            if end in quarters:
                continue
            inside = [q for q in quarters if start < q < end]
            if len(inside) == 3:
                quarters[end] = total - sum(quarters[q] for q in inside)
        out = dict(sorted(quarters.items()))
    if len(_facts_cache) > 512:
        _facts_cache.clear()
    _facts_cache[sym] = (time.monotonic(), out)
    return out


def fetch_filing_text(url: str, max_chars: int = 60_000) -> str | None:
    """Fetch one filing document and extract clean prose via BeautifulSoup
    (naive tag-stripping mangles inline-XBRL documents — see module
    docstring). Truncated to max_chars; a 10-K can run 200k+ chars and the
    caller (desk/filings.py) chunks/summarizes rather than feeding it whole
    to an LLM in one call."""
    try:
        raw = _get(url, timeout=30.0)
    except Exception as exc:
        log.warning("EDGAR document fetch failed (%s): %s", url, exc)
        return None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        # An inline-XBRL document opens with a hidden block of every tagged
        # fact; it is never displayed and put ~110,000 characters ahead of
        # TSMC's 20-F body (2026-09-19), pushing late sections past a cap.
        for tag in soup.find_all(re.compile(r"^ix:header$", re.I)):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
    except Exception as exc:
        log.warning("EDGAR text extraction failed (%s): %s", url, exc)
        return None
    return text[:max_chars]


# ── A ticker that moved to a successor registrant ────────────────────────────
# A redomiciliation or holding-company reorganization under Rule 12g-3 files
# a NEW registrant, which takes the ticker; the company's annual reports stay
# under the old one. XOM's ticker maps to ExxonMobil Holdings Corp (CIK
# 2115436, from 2026-07-01) with no 10-K yet, so its Profile was empty. The
# successor's 8-K12B names the predecessor in its text — "Exxon Mobil
# Corporation, a New Jersey corporation and the predecessor registrant" —
# and neither the filing header nor formerNames does, so the name is read
# from the text and resolved by EDGAR's full-text search.
_SUCCESSION_FORMS = ("8-K12B", "8-K12G3", "8-K12B/A", "8-K12G3/A")
_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_PREDECESSOR = re.compile(
    r"([A-Z][A-Za-z0-9.&'\- ]{1,100}?(?:,\s*(?:Inc|Ltd|L\.?P|LLC|Co|plc|N\.V|S\.A)\.?)?)"
    r",\s+an?\s+[A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,3}\s+"
    r"(?i:corporation|company|limited\s+liability\s+company|limited\s+partnership|public\s+limited\s+company|statutory\s+trust)"
    r"(?:\s*\([^)]{0,80}\))?,?\s+"
    r"(?i:(?:and\s+|as\s+)?(?:the\s+)?predecessor\s+(?:registrant|issuer|company))")
_NAME_WORDS = {"CORPORATION": "CORP", "INCORPORATED": "INC", "COMPANY": "CO", "LIMITED": "LTD"}
_SUCCESSOR_TTL_S = 86_400
_successor_cache: dict[str, tuple[float, dict | None]] = {}


def predecessor_name(text: str) -> str | None:
    """The predecessor registrant's name from a succession 8-K's text, or
    None. Pure."""
    m = _PREDECESSOR.search(re.sub(r"\s+", " ", text or ""))
    return m.group(1).strip() if m else None


def _norm_name(name: str) -> str:
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    words = [_NAME_WORDS.get(w, w) for w in words]
    return " ".join(words[1:] if words[:1] == ["THE"] else words)


def pick_predecessor(hits: list[dict], name: str, symbol: str, own_cik: str) -> dict | None:
    """The search hit that is the predecessor: another CIK whose EDGAR name
    is the same name ("EXXON MOBIL CORP" for "Exxon Mobil Corporation").
    Failing a name match, one still listed under the same ticker. Pure."""
    want, sym, own = _norm_name(name), symbol.upper(), int(own_cik or 0)
    by_ticker = None
    for h in hits:
        for dn in (h.get("_source") or {}).get("display_names") or []:
            m = re.match(r"\s*(.+?)\s+(?:\(([^)]*)\)\s+)?\(CIK (\d+)\)", dn)
            if not m or int(m.group(3)) == own:
                continue
            found = {"cik": f"{int(m.group(3)):010d}", "name": m.group(1).strip()}
            if _norm_name(found["name"]) == want:
                return found
            tickers = {t.strip().upper() for t in (m.group(2) or "").split(",")}
            if sym in tickers and by_ticker is None:
                by_ticker = found
    return by_ticker


def predecessor_of(symbol: str) -> dict | None:
    """{cik, name} of the registrant this symbol's current one succeeded,
    or None. Three requests the first time (the 8-K12B list, its text, one
    search), held a day either way; a failed fetch is not held."""
    import json
    from urllib.parse import urlencode
    sym = symbol.upper()
    hit = _successor_cache.get(sym)
    if hit and time.time() - hit[0] < _SUCCESSOR_TTL_S:
        return hit[1]
    rows = recent_filings(sym, forms=_SUCCESSION_FORMS, limit=1)
    found = None
    if rows:
        text = fetch_filing_text(rows[0]["url"], max_chars=40_000)
        if text is None:
            return None
        name = predecessor_name(text)
        if name:
            q = urlencode({"q": f'"{name}"', "forms": "10-K,20-F,40-F"})
            try:
                data = json.loads(_get(f"{_SEARCH_URL}?{q}"))
            except Exception as exc:
                log.warning("EDGAR predecessor search failed for %s: %s", sym, exc)
                return None
            found = pick_predecessor((data.get("hits") or {}).get("hits") or [], name, sym, rows[0]["cik"])
    if len(_successor_cache) > 5_000:
        _successor_cache.clear()
    _successor_cache[sym] = (time.time(), found)
    return found
