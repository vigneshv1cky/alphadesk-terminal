"""Ask a question of one SEC filing, answered ONLY from that filing's own
text, every claim backed by a verbatim quote.

Attribution here is stronger than the news screener's: the screener cites by
article INDEX and resolves that index back to a URL we already control (the
model's own idea of a URL is never trusted). A filing is one document, not a
numbered list, so there's no index to cite — instead the model is required to
quote verbatim, and every quote is checked as an actual substring of the
cached filing text before it's returned. A quote that doesn't verify is
dropped, not shown. The model can claim anything; only quotes that actually
appear in the SEC document survive.
"""

import logging

from alphadesk.config import FILING_MAX_CHARS
from alphadesk.ingest import edgar
from alphadesk.ledger import store

log = logging.getLogger("alphadesk.filings")

_QA_SYSTEM = (
    "You answer questions about ONE SEC filing using ONLY the filing text "
    "provided. If the filing doesn't address the question, say so plainly — "
    "never guess or use outside knowledge.\n"
    "Every factual claim must be backed by a VERBATIM quote from the text — "
    "copy the exact wording, do not paraphrase into the quote field.\n"
    "Return ONLY JSON: {\"answer\": \"...\", "
    "\"quotes\": [\"verbatim snippet from the filing\", ...]}"
)


#: How much of a filing, exhibits included, is read and KEPT (2026-10-06). The
#: agent's reader asks for up to this much; the in-app question answering
#: takes the first FILING_MAX_CHARS of the same stored text.
FULL_MAX_CHARS = 400_000


def _maybe_cut(text: str) -> bool:
    """A copy saved under the old 60,000-character cap may stop short of the
    document's end; one that is clearly shorter or longer than the cap is whole."""
    return FILING_MAX_CHARS * 0.98 <= len(text) <= FILING_MAX_CHARS


def get_full_text(accession: str, url: str | None = None) -> str | None:
    """A filing's whole text, exhibits included, from the store when it is
    there and from EDGAR (then stored for good) when it is not.

    THE SAVED COPY IS READ FIRST (2026-10-06, the owner: "I told you to save
    most data possible"). The agent's reader fetched every filing from EDGAR
    afresh — a paced queue — and kept it only in memory, so a restart or a busy
    hour fetched it again; the saved copy was used only when EDGAR failed, and
    was capped at 60,000 characters. A filing never changes once accepted, so
    the whole of it is saved the first time it is read."""
    cached = store.get_filing_text(accession)
    if cached is not None and not _maybe_cut(cached):
        return cached
    if not url:
        meta = store.get_filing_meta(accession)
        url = meta["url"] if meta else None
    if not url:
        return cached
    text = edgar.fetch_filing_with_exhibits(url, max_chars=FULL_MAX_CHARS)
    if text:
        store.save_filing_text(accession, text)
        return text
    return cached                                  # EDGAR unreachable: what is saved, possibly cut


def get_text(accession: str, url: str | None = None) -> str | None:
    """The first FILING_MAX_CHARS of a filing, for question answering — taken
    from the same saved whole text."""
    text = get_full_text(accession, url)
    return text[:FILING_MAX_CHARS] if text else text


def list_filings(symbol: str, refresh: bool = True) -> list[dict]:
    """A symbol's recent filings — the narrative forms the Q&A can read
    (10-K, 10-Q, 8-K and their amendments, 20-F, 6-K, the proxy) and the
    ownership forms it cannot (3, 4, 5, 144, 13D/13G), each row carrying
    `readable`. Refreshes from EDGAR on every call by default (cheap — one
    submissions JSON fetch) and persists into the filings table either way,
    so a later accession lookup (get_filing_meta) works even for a filing
    never re-listed since."""
    if refresh:
        fresh = edgar.recent_filings(symbol)
        if fresh:
            store.save_filings(fresh)
    rows = store.get_filings(symbol, limit=60)
    for r in rows:
        r["readable"] = edgar.is_readable(r.get("form"))
    return rows
