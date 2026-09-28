"""Earnings transcripts: the list, the document, and the one ask over it.

The document comes from the selected transcript provider (the company's
filed press release by default, a recorded call when the reader keys a
vendor). Its text is cached in the ledger under "tx:<provider>:<id>" —
the same cache the filings Q&A uses, because a filed release IS a filing
exhibit and a call transcript never changes once published.

GUIDANCE EXTRACTION is the one AI feature here, and it runs only when the
reader presses the button (invariant 4). The model reads the document and
returns figures as {metric, period, value, quote}; every row is kept ONLY
if its quote is a verbatim substring of the document and the value appears
inside that quote — the filings Q&A's rule, applied per figure. What does
not verify is dropped, never caveated (invariant 1). Cached per document.
"""

import hashlib
import json
import logging
import re

from alphadesk.ledger import store
from alphadesk.providers import get_transcripts
from alphadesk.providers.base import EntitlementError, ProviderError

log = logging.getLogger("alphadesk.transcripts")

_GUIDANCE_SYSTEM = (
    "You extract MANAGEMENT GUIDANCE from ONE earnings document (a results "
    "press release or a call transcript) using ONLY the text provided. "
    "Guidance is a forward-looking figure or range management gives for a "
    "coming period: revenue, margins, expenses, EPS, tax rate, capex, unit "
    "or growth outlooks. Reported results for the past quarter are NOT "
    "guidance — leave them out. If the document gives no guidance, return "
    "an empty list.\n"
    "For each figure return: metric (short name), period (the period it "
    "applies to, as the document states it), value (the figure or range, "
    "with units, as stated), and quote — a VERBATIM sentence or clause from "
    "the text that contains the value. Copy the exact wording; do not "
    "paraphrase into the quote field.\n"
    "Return ONLY JSON: {\"items\": [{\"metric\": \"...\", \"period\": \"...\", "
    "\"value\": \"...\", \"quote\": \"...\"}, ...]}"
)
_GUIDANCE_QHASH = hashlib.sha1(b"guidance-v1").hexdigest()[:16]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def text_key(provider: str, id: str) -> str:
    return f"tx:{provider}:{id}"


# A CALL TRANSCRIPT IS OFTEN ALREADY IN THE READER'S NEWS FEED (2026-09-28,
# the owner: "the calls come from news providers right?"). Benzinga publishes
# full earnings-call transcripts as ordinary stories, tagged with the one
# ticker and carrying their whole text, so a reader with an Alpaca key already
# holds them and needs no transcript vendor at all.
#
# MEASURED before building on it, because the coverage is the whole question:
# in one 500-story window there were four, every one full-text and tagged with
# exactly one ticker — and of 39 companies that reported that week, three were
# covered. That is thin, and it is stated as thin. It is still three panels
# that said "no transcript source keyed" over a document the reader owned.
#
# The headline is the only index there is, so the match is deliberately narrow:
# a story is a transcript when its title says so in one of the forms these
# publishers actually use. "Earnings call" alone is not enough — a preview or a
# report ABOUT a call is not the call.
_CALL_TITLE = re.compile(
    r"\b(full\s+)?transcript\b.*\bearnings\b|\bearnings\b.*\b(full\s+)?transcript\b"
    r"|\bearnings\s+(conference\s+)?call\s+transcript\b|^transcript:",
    re.I)

NEWS_PROVIDER = "news"


def _from_news(symbol: str) -> list[dict]:
    """Call transcripts sitting in the reader's own news window, newest first.

    Empty for a reader with no news feed, or none for this company — which is
    the common case and is why this supplements a vendor rather than replacing
    one.
    """
    from alphadesk.identity import request_user
    uid = request_user()
    if not uid:
        return []
    try:
        rows = store.articles_for_symbol(uid, symbol.upper(), limit=60) or []
    except Exception as exc:
        log.debug("news transcripts unavailable for %s: %s", symbol, exc)
        return []
    out = []
    for a in rows:
        title = a.get("title") or ""
        if not _CALL_TITLE.search(title):
            continue
        out.append({
            "id": str(a.get("article_id") or a.get("id") or ""),
            "title": title,
            "date": (a.get("published_at") or "")[:10],
            "url": a.get("url") or None,
            "source": a.get("source") or None,
        })
    return [r for r in out if r["id"]]


def list_transcripts(symbol: str) -> dict:
    prov = get_transcripts()
    try:
        rows = prov.list_transcripts(symbol)
    except ProviderError as exc:
        log.info("transcripts list unavailable for %s via %s: %s", symbol, prov.name, exc)
        # SAY WHAT HAPPENED, NOT THE STATUS LINE (2026-09-28, the reader, on a
        # panel reading "HTTP 402"). A vendor's status code is not a sentence,
        # and 402 in particular means something a reader can act on: the key
        # works and the PLAN does not reach this. Recorded call transcripts sit
        # on FMP's Ultimate tier, which is why a Premium key lands here.
        from alphadesk.providers.catalogue import VENDORS
        v = VENDORS.get(prov.name)
        name = v.label if v else prov.name
        if isinstance(exc, EntitlementError):
            why = (f"{name} refused this: recorded call transcripts are not on your plan "
                   f"with them. SEC results releases are free — clear your transcript "
                   f"vendor on the Account page to read those instead.")
        else:
            why = f"{name} could not be reached for this symbol just now ({exc})."
        # A REFUSED VENDOR IS NOT AN ABSENCE OF TRANSCRIPTS. The reader's own
        # news feed may hold the call, and saying "your plan refuses this" over
        # a document they already have is the same fault as a key prompt for a
        # source already connected.
        from_news = _from_news(symbol)
        if from_news:
            return {"symbol": symbol.upper(), "provider": NEWS_PROVIDER, "kind": "call",
                    "transcripts": from_news, "note": why}
        return {"symbol": symbol.upper(), "provider": prov.name, "kind": prov.kind,
                "transcripts": [], "error": why}
    # THE CALL AND THE RELEASE ARE DIFFERENT DOCUMENTS, so a call found in the
    # news feed JOINS the list rather than replacing it or waiting for it to be
    # empty. The default source is EDGAR, which always has releases, so a
    # "only when there is nothing" fallback would never once have fired — and
    # the reader would keep being told no call was available while its whole
    # text sat in their own news window.
    merged = _merge(rows, _from_news(symbol), prov.name)
    return {"symbol": symbol.upper(), "provider": prov.name, "kind": prov.kind,
            "transcripts": merged}


def _merge(vendor_rows: list[dict], news_rows: list[dict], vendor: str) -> list[dict]:
    """Both sets, newest first, each row saying where it came from.

    `from` is on EVERY row, vendor rows included: a picker that marks only the
    borrowed ones implies the rest are something else by omission, and the
    panel needs to know which reader to send an id back to.
    """
    out = [{**r, "from": r.get("from") or vendor} for r in (vendor_rows or [])]
    seen = {str(r.get("id")) for r in out}
    for r in news_rows or []:
        if str(r.get("id")) not in seen:
            out.append({**r, "from": NEWS_PROVIDER, "kind": "call"})
    out.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return out


def get_transcript(symbol: str, id: str) -> dict | None:
    """The document with its text, from the ledger cache when it has been
    read before. The provider name rides in the cache key: the same id
    means different documents on different sources. The cache row is a
    JSON envelope (meta + text) in the filing text cache — a transcript is
    never a row in the filings table, so the Filings panel never lists it."""
    # A NEWS-SOURCED TRANSCRIPT IS READ FROM THE NEWS STORE, not from the
    # transcript vendor — the id is an article id and means nothing to them.
    from_news = next((r for r in _from_news(symbol) if r["id"] == id), None)
    if from_news is not None:
        from alphadesk.identity import request_user
        from alphadesk.ingest.news import full_story
        uid = request_user()
        story = full_story(uid, id) if uid else None
        text = (story or {}).get("body") or (story or {}).get("text") or ""
        if text:
            return {"id": id, "symbol": symbol.upper(), "provider": NEWS_PROVIDER,
                    "kind": "call", "date": from_news["date"], "period_end": None,
                    "title": from_news["title"], "url": from_news["url"], "text": text}
        return None

    prov = get_transcripts()
    key = text_key(prov.name, id)
    cached = store.get_filing_text(key)
    if cached is not None:
        try:
            env = json.loads(cached)
            if isinstance(env, dict) and env.get("text"):
                return {**env, "id": id, "symbol": symbol.upper(), "provider": prov.name, "kind": prov.kind}
        except ValueError:
            pass
    doc = prov.transcript(symbol, id)
    if not doc or not doc.get("text"):
        return None
    env = {"date": doc.get("date"), "period_end": doc.get("period_end"),
           "title": doc.get("title"), "url": doc.get("url"), "text": doc["text"]}
    store.save_filing_text(key, json.dumps(env))
    return {**env, "id": id, "symbol": symbol.upper(), "provider": prov.name, "kind": prov.kind}


def verify_guidance(items: list, text: str) -> tuple[list[dict], int]:
    """Keep a figure only when its quote is a verbatim substring of the
    document (whitespace-normalised, 15+ chars) AND the value appears in
    that quote. Returns (kept, dropped)."""
    norm_text = _norm(text)
    kept, dropped = [], 0
    for it in items or []:
        if not isinstance(it, dict):
            dropped += 1
            continue
        quote = _norm(str(it.get("quote") or ""))
        value = _norm(str(it.get("value") or ""))
        metric = str(it.get("metric") or "").strip()
        if not (metric and value and len(quote) >= 15 and quote in norm_text):
            dropped += 1
            continue
        # The value must sit inside the quote: "$28 billion, plus or minus
        # 2%" verifies when its digits do, so the check is on the numbers
        # (a model may write "28B" for "$28 billion").
        nums = re.findall(r"\d+(?:\.\d+)?", value)
        if nums and not all(n in quote for n in nums):
            dropped += 1
            continue
        kept.append({"metric": metric, "period": str(it.get("period") or "").strip(),
                     "value": str(it.get("value")).strip(), "quote": str(it.get("quote")).strip()})
    return kept, dropped

