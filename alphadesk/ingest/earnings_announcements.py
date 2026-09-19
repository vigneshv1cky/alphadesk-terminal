"""Companies' own announcements of when they will report (2026-09-14).

A company tells the market days or weeks ahead: "Lennar … will release its
third quarter 2026 earnings after the market closes on September 16, 2026."
Those press releases reach the reader through their own feeds (FMP's press
releases, Benzinga through Alpaca). Read from them, the date and the session
are the COMPANY's word — firmer than a vendor's projection — and every one
carries the release it came from, so the calendar can show its source.

`parse_announcement` is pure. It accepts an announcement only when the text
ties a future report of results to a date; a report of results that already
happened ("reported", "announced … results for") is not one.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
_MON_ABBR = {k[:3]: v for k, v in _MONTHS.items()} | {"sept": 9}

_DATE = re.compile(
    r"\b(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?"
    r"(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?",
    re.I)

# A future release of results: the verb looks forward.
# A release of results (preferred: its date is the report date) versus a
# conference call (its date can be the morning AFTER an after-close release —
# Lennar released on Sep 16 and broadcast its call on the 17th).
_RELEASE_VERBS = r"(report|release|announce|publish|issue|be\s+released|be\s+issued|be\s+reported)"
_CALL_VERBS = r"(host|hold|broadcast|discuss|webcast)"
_FORWARD_RELEASE = re.compile(
    r"\b(will|to|plans? to|expects? to|intends? to|scheduled to|is scheduled|are scheduled)\s+(?:\w+\s+){0,3}?" + _RELEASE_VERBS, re.I)
_FORWARD_CALL = re.compile(
    r"\b(will|to|plans? to|expects? to|intends? to|scheduled to|is scheduled|are scheduled)\s+(?:\w+\s+){0,3}?" + _CALL_VERBS, re.I)
# FINANCIAL results, not any results. A bare "results" put Rezolute's
# earnings date on a clinical-trial release — "remains on track to report
# topline results before the end of 2026" — seven days before the date its
# calendar vendor listed (2026-09-15). A results announcement always names
# the period or the kind of results; a trial update does not.
_RESULTS = re.compile(
    r"\b(earnings|financial\s+results|operating\s+results|financial\s+and\s+operating\s+results"
    r"|fiscal|quarter(?:ly)?|half[-\s]year|full[-\s]year|year[-\s]end|annual\s+results"
    r"|q[1-4]\b|first\s+quarter|second\s+quarter|third\s+quarter|fourth\s+quarter)\b", re.I)
_PAST = re.compile(r"\b(reported|announced|released)\s+(?:its\s+|their\s+)?(?:\w+\s+){0,4}(results|earnings)\s+for\b", re.I)

_MKT = r"(?:the\s+)?(?:u\.?s\.?\s+|financial\s+|stock\s+|equity\s+)*markets?"
_BMO = re.compile(r"before\s+" + _MKT + r"\s+opens?\b|before\s+(?:the\s+)?(?:market|opening)\s+(?:open|bell)"
                  r"|before\s+(?:the\s+)?opening\s+of\s+(?:the\s+)?(?:u\.?s\.?\s+)?(?:trading|markets?)|before\s+trading\s+(?:opens|begins)"
                  r"|prior\s+to\s+(?:the\s+)?opening\s+of\s+(?:trading|the\s+markets?)"
                  r"|prior\s+to\s+" + _MKT + r"\s+open|pre-?market|before\s+(?:the\s+)?open\b", re.I)
_AMC = re.compile(r"after\s+" + _MKT + r"\s+(?:close|closes|closed)\b|after\s+(?:the\s+)?(?:market\s+)?close\b"
                  r"|after\s+(?:the\s+)?close\s+of\s+(?:the\s+)?(?:trading|markets?)"
                  r"|after\s+(?:the\s+)?(?:closing\s+)?bell|following\s+the\s+(?:market\s+)?close|post-?market", re.I)
_CALL_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?\s*(?:\(?\s*(?:u\.?s\.?\s+)?(eastern|et|edt|est)\b)", re.I)


def _resolve_date(month: str, day: str, year: str | None, published: date) -> date | None:
    m = _MONTHS.get(month.lower()) or _MON_ABBR.get(month.lower().rstrip("."))
    if not m:
        return None
    try:
        d = date(int(year), m, int(day)) if year else date(published.year, m, int(day))
    except ValueError:
        return None
    if not year and d < published - timedelta(days=2):
        try:
            d = date(published.year + 1, m, int(day))
        except ValueError:
            return None
    return d


#: A wire dateline, up to and including the service's marker.
_DATELINE = re.compile(
    r"[A-Z][A-Za-z.\- ]{1,40},\s*(?:[A-Z][A-Za-z.]{1,14},\s*)?"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\s*"
    r"[/(][^)/]{0,40}(?:NEWSWIRE|NEWS WIRE|PRNEWSWIRE|BUSINESS WIRE|GLOBE NEWSWIRE|ACCESSWIRE|ACCESS NEWSWIRE)"
    r"[^)/]{0,40}[)/]\s*(?:--|—|-)?", re.I)

_ABBREV = re.compile(r"\b(inc|corp|co|ltd|plc|llc|n\.v|s\.a|u\.s|no|jr|sr|st|dr|mr|ms)\.$", re.I)


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", re.sub(r"\s+", " ", text or "")) if p.strip()]
    out: list[str] = []
    for p in parts:
        # "High Tide Inc. (Nasdaq: HITI) … will release" is one sentence.
        if out and _ABBREV.search(out[-1]):
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


def _quote(sentence: str, at: int) -> str:
    """The sentence as the reader sees it: from shortly before the verb, so a
    company's self-description does not crowd out the date."""
    if len(sentence) <= 220:
        return sentence
    start = max(0, at - 60)
    start = sentence.find(" ", start) + 1 if start else 0
    clip = sentence[start:start + 240]
    return ("…" if start else "") + clip + ("…" if start + 240 < len(sentence) else "")


def parse_announcement(title: str, text: str, published_at: str) -> dict | None:
    """{report_date, session, basis, sentence} when the release announces a
    future report of results on a date; None otherwise. `session` is BMO or
    AMC when the text says so (or a conference call before 9:30 / from 16:00
    implies it), else None. Pure."""
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00").replace(" ", "T")).date()
    except ValueError:
        return None
    # The wire's dateline opens the body ("REDWOOD CITY, Calif., Sept. 09,
    # 2026 (GLOBE NEWSWIRE) -- ") and carries the PUBLICATION day. Sentence
    # splitting can leave it trailing the previous sentence, where it reads
    # as the date a forward-looking verb was pointing at, so it is cut
    # before anything is parsed (2026-09-15).
    text = _DATELINE.sub(" ", text or "")
    sentences = [title or "", *_sentences(text)[:10]]
    blob = " ".join(sentences)

    def dated(sentence: str, after: int = 0) -> date | None:
        """The first date AFTER the forward verb — a wire dateline ("MIAMI,
        Sept. 2, 2026 /PRNewswire/ --") opens the same sentence and is the
        publication day, not the report day."""
        if not _RESULTS.search(sentence) or _PAST.search(sentence):
            return None
        for m in _DATE.finditer(sentence, after):
            d = _resolve_date(m.group(1), m.group(2), m.group(3), published)
            if d is not None and published - timedelta(days=1) <= d <= published + timedelta(days=75):
                return d
        return None

    def title_says(sentence: str, verbs: str) -> bool:
        return sentence is sentences[0] and bool(re.search(r"\bto\s+" + verbs + r"\b", sentence, re.I))

    chosen, kind = None, None
    # First pass: a sentence releasing results on a date. Second: a call on a date.
    for pattern, verbs, label in ((_FORWARD_RELEASE, _RELEASE_VERBS, "release"), (_FORWARD_CALL, _CALL_VERBS, "call")):
        for sentence in sentences:
            verb = pattern.search(sentence)
            if not (verb or title_says(sentence, verbs)):
                continue
            d = dated(sentence, verb.start() if verb else 0)
            if d is not None:
                chosen, kind = (d, _quote(sentence, verb.start() if verb else 0)), label
                break
        if chosen:
            break
    if not chosen:
        return None
    d, sentence = chosen
    session, basis = None, None
    if _BMO.search(blob) and not _AMC.search(blob):
        session, basis = "BMO", "stated"
    elif _AMC.search(blob) and not _BMO.search(blob):
        session, basis = "AMC", "stated"
    elif kind == "release":
        # Only a call on the release's own day says when the release came out.
        call = _CALL_TIME.search(blob)
        if call:
            hour = int(call.group(1)) % 12 + (12 if call.group(3).lower() == "p" else 0)
            minutes = hour * 60 + int(call.group(2) or 0)
            if minutes < 9 * 60 + 30:
                session, basis = "BMO", "call time"
            elif minutes >= 16 * 60:
                session, basis = "AMC", "call time"
    if kind == "call":
        # A call date is the report date only for a same-day call; an after-
        # close release with a next-morning call is common, so without a
        # stated session the date is not trusted as the report date.
        if session is None:
            return None
    return {"report_date": d.isoformat(), "session": session, "basis": basis, "kind": kind, "sentence": sentence[:300]}


# The wires companies issue their own releases on. A reporter's article is
# not the company's word: "Prediction: Micron's Sept. 30 earnings" named a
# date and tagged SanDisk too (2026-09-14).
_WIRES = re.compile(r"(^|\.)(globenewswire\.com|prnewswire\.com|prnewswire\.co\.uk|newswire\.ca|businesswire\.com"
                    r"|newsfilecorp\.com|accessnewswire\.com|accesswire\.com)$", re.I)


def is_press_release(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        return bool(_WIRES.search(urlparse(url).hostname or ""))
    except ValueError:
        return False


def from_articles(articles: list[dict]) -> list[dict]:
    """Announcements in a batch of stored-shape articles (title, summary or
    body, published_at, url, tickers, source), one per ticker, from press
    releases on the wires only. Pure."""
    out = []
    for a in articles:
        tickers = a.get("tickers") or []
        if not tickers or not a.get("url") or not a.get("published_at") or not is_press_release(a["url"]):
            continue
        parsed = parse_announcement(a.get("title") or "", a.get("body") or a.get("summary") or "", a["published_at"])
        if not parsed:
            continue
        for t in tickers[:3]:
            out.append({**parsed, "symbol": str(t).upper(), "url": a["url"], "published_at": a["published_at"],
                        "source": a.get("source")})
    return out


def record_from_articles(owner: str, articles: list[dict]) -> int:
    """Parse and store announcements from a reader's newly saved articles."""
    from alphadesk.ledger import store
    return store.save_announcements(owner, from_articles(articles))


MATCH_DAYS = 14


#: Words that end a company's legal name rather than naming it.
_NAME_TAIL = {"inc", "incorporated", "corp", "corporation", "co", "company", "companies", "plc",
              "ltd", "limited", "holdings", "holding", "group", "sa", "nv", "ag", "the", "de",
              "lp", "llc", "trust", "partners", "international"}


def names_company(text: str, symbol: str, company: str | None) -> bool:
    """Whether a press release is about THIS company.

    The vendor's own filter cannot be trusted: asked for Eastern Company's
    releases it answered with Playboy's, DexCom's and Parker's, every row
    tagged EML (measured 2026-09-15), and eleven of Eastern's twelve stored
    announcements belonged to other companies. Dave Inc's calendar row came
    from a Dave & Buster's release the same way.

    A wire release names its company in the ticker line — "The Eastern
    Company (NASDAQ: EML)" — so the TICKER IN CAPITALS as a whole word is the
    evidence. Failing that, the company's name as a phrase of two words or
    more, which "Dave" alone is not and "Eastern Bankshares" does not match
    for "Eastern Company". Pure."""
    body = text or ""
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(symbol.upper())}(?![A-Za-z0-9])", body):
        return True
    words = [w for w in re.sub(r"[^A-Za-z0-9 ]", " ", str(company or "")).lower().split()
             if w not in _NAME_TAIL]
    if len(words) < 2:
        return False
    return " ".join(words[:2]) in " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", body).lower().split())


def is_results_announcement(sentence: str | None) -> bool:
    """Whether a stored announcement's own sentence names financial results.

    Rows recorded before the parser was tightened can still say a clinical
    trial's "topline results" moved an earnings date (Rezolute, 2026-09-15),
    and a stored row outlives the fix. Checking the sentence on the way out
    heals them without a migration; a row with no sentence is left alone."""
    return not sentence or bool(_RESULTS.search(sentence))


def apply_announcements(rows: list[dict], announcements: list[dict]) -> None:
    """A company's newest announcement sets the date of its nearest row within
    MATCH_DAYS, and that row's session when the release states one — the
    company's word over a vendor's projection. The vendor's date is kept as
    `vendor_date`; the release that said so as `announcement`. One
    announcement settles one report: an older one within MATCH_DAYS of it is
    the same report, superseded, and a company's second vendor row is left
    alone rather than moved onto the same day (51Talk, 2026-09-14).

    A report already out keeps its date. EDGAR's clock wins when there is
    one; without it, an announcement for that same day still says whether it
    came before the open or after the close (CoinShares, one vendor's actual
    and no 8-K). Pure."""
    by_sym: dict[str, list[dict]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"].upper(), []).append(r)
    taken: set[int] = set()
    settled: dict[str, list[date]] = {}
    for a in sorted(announcements, key=lambda a: a["published_at"], reverse=True):
        if not is_results_announcement(a.get("sentence")):
            continue
        sym = a["symbol"].upper()
        ann = date.fromisoformat(a["report_date"][:10])
        if any(abs((ann - d).days) <= MATCH_DAYS for d in settled.get(sym, [])):
            continue
        near = [(abs((ann - date.fromisoformat(r["report_date"][:10])).days), i, r)
                for i, r in enumerate(by_sym.get(sym, [])) if id(r) not in taken]
        near = [n for n in near if n[0] <= MATCH_DAYS]
        if not near:
            continue
        _, _, r = min(near, key=lambda n: (n[0], n[1]))
        settled.setdefault(sym, []).append(ann)
        taken.add(id(r))
        stated = a.get("session") in ("BMO", "AMC")
        if r.get("released_on") or r.get("released_at") or r.get("eps_actual") is not None:
            if r.get("released_at") or ann.isoformat() != r["report_date"][:10] or not stated \
                    or r.get("session") in ("BMO", "AMC"):
                continue
        elif ann.isoformat() != r["report_date"][:10]:
            r.setdefault("vendor_date", r["report_date"])
            r["report_date"] = ann.isoformat()
        r["confirmed"] = True
        if stated:
            if r.get("session") and r["session"] != a["session"]:
                r.setdefault("vendor_session", r["session"])
            r["session"] = a["session"]
        r["announcement"] = {"url": a["url"], "published_at": a["published_at"], "source": a.get("source"),
                             "basis": a.get("basis"), "sentence": a.get("sentence")}


def announced_rows(rows: list[dict], announcements: list[dict], start: str, end: str, listed: dict[str, str]) -> list[dict]:
    """Reports no vendor listed, from announcements dated in [start, end] for
    SEC-listed companies (Trip.com, 2026-09-14). One per company. Pure."""
    have = {r["symbol"].upper() for r in rows}
    have_cik = {listed.get(s) for s in have if listed.get(s)}
    out: dict[str, dict] = {}
    for a in sorted(announcements, key=lambda a: a["published_at"], reverse=True):
        if not is_results_announcement(a.get("sentence")):
            continue
        sym = a["symbol"].upper()
        if sym in have or sym in out or sym not in listed or listed[sym] in have_cik:
            continue
        if not (start <= a["report_date"][:10] <= end):
            continue
        out[sym] = {"symbol": sym, "report_date": a["report_date"][:10], "session": a.get("session") or "DAY",
                    "confirmed": True, "eps_estimate": None, "eps_actual": None, "sources": "announcement",
                    "announcement": {"url": a["url"], "published_at": a["published_at"], "source": a.get("source"),
                                     "basis": a.get("basis"), "sentence": a.get("sentence")}}
        have_cik.add(listed[sym])
    return list(out.values())


# A company's press releases, once read for a reader, are not asked for again
# this long — the router's memo lives in one process, and a fresh server
# otherwise re-reads every upcoming company's releases (4s of a cold build).
CHECK_KEEP_HOURS = 6
# Past this many companies to read, the reads run in the background and the
# page counts them in `pending["announcements"]`.
BLOCK_LIMIT = 40


def for_symbols(router, symbols: list[str], owner: str | None, *,
                pending: dict | None = None, block_limit: int | None = None) -> list[dict]:
    """Announcements from each company's own recent press releases, on the
    reader's key, stored under the reader so the next build reads them from
    the table. Companies read within CHECK_KEEP_HOURS are skipped; companies
    whose releases cannot be fetched are skipped and asked again next time.
    Eight at a time: a week holds a hundred upcoming reports, one request each."""
    from concurrent.futures import ThreadPoolExecutor

    from alphadesk.identity import reset_request_user, set_request_user
    from alphadesk.config import now_et
    from alphadesk.ledger import store

    from alphadesk.ingest import background_fill
    # A reader with no press-release vendor has nothing to read.
    if not router._order("press_releases", "press_releases"):
        return []
    if owner and symbols:
        since = (now_et() - timedelta(hours=CHECK_KEEP_HOURS)).isoformat()
        try:
            done = store.press_releases_checked_since(owner, symbols, since)
            symbols = [s for s in symbols if s.upper() not in done
                       and not background_fill.recently_failed("announcements", owner, s)]
        except Exception:
            pass
    if owner and block_limit is not None and len(symbols) > block_limit:
        background_fill.submit("announcements", owner, symbols, lambda syms: for_symbols(router, syms, owner))
        if pending is not None:
            pending["announcements"] = len(symbols)
        return []

    def one(sym: str) -> tuple[str, bool, list[dict]]:
        # Pool threads do not inherit the request context; re-stamp the reader.
        token = set_request_user(owner)
        try:
            releases = router.get("press_releases", sym)
        except Exception:
            return sym, False, []
        finally:
            reset_request_user(token)
        from alphadesk.ingest import edgar
        company = edgar.company_title(sym)
        out = []
        for rel in releases or []:
            if not (rel.get("url") and rel.get("published_at")):
                continue
            title, text = rel.get("title") or "", rel.get("text") or ""
            # The vendor tags every row it returns with the symbol asked for,
            # whatever company the release is actually about (2026-09-15).
            if not names_company(f"{title} {text}", sym, company):
                continue
            parsed = parse_announcement(title, text, rel["published_at"])
            if parsed:
                out.append({**parsed, "symbol": sym.upper(), "url": rel["url"], "published_at": rel["published_at"],
                            "source": rel.get("source")})
        return sym, releases is not None, out

    if not symbols:
        return []
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, symbols))
    found = [a for _, _, batch in results for a in batch]
    if owner:
        try:
            # A re-check REPLACES what this company had: a row parsed by an
            # older, looser reader outlives the fix otherwise, and every
            # company is re-read within CHECK_KEEP_HOURS.
            store.replace_announcements(owner, [sym for sym, ok, _ in results if ok], found)
            store.mark_press_releases_checked(owner, [sym for sym, ok, _ in results if ok], now_et().isoformat())
            background_fill.note_failed("announcements", owner, [sym for sym, ok, _ in results if not ok])
        except Exception as exc:
            import logging
            logging.getLogger("alphadesk.earnings_announcements").debug("announcements not stored: %s", exc)
    return found
