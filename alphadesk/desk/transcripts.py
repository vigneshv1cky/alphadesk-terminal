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
from alphadesk.providers.base import ProviderError

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


def list_transcripts(symbol: str) -> dict:
    prov = get_transcripts()
    try:
        rows = prov.list_transcripts(symbol)
    except ProviderError as exc:
        log.info("transcripts list unavailable for %s via %s: %s", symbol, prov.name, exc)
        rows = []
        return {"symbol": symbol.upper(), "provider": prov.name, "kind": prov.kind,
                "transcripts": rows, "error": str(exc)}
    return {"symbol": symbol.upper(), "provider": prov.name, "kind": prov.kind, "transcripts": rows}


def get_transcript(symbol: str, id: str) -> dict | None:
    """The document with its text, from the ledger cache when it has been
    read before. The provider name rides in the cache key: the same id
    means different documents on different sources. The cache row is a
    JSON envelope (meta + text) in the filing text cache — a transcript is
    never a row in the filings table, so the Filings panel never lists it."""
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

