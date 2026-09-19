"""What a news search matches — one rule for the app's filter box
(ui/src/lib/newsMatch.ts, the same rule in TypeScript), "Search all" and the
agent's news_search (ledger/store.py). No model: words, word forms and the
SEC ticker list.

The rule, and why each part is there:

* WHOLE WORDS, in order (2026-09-18). A search word matches a whole word of
  the headline, summary, source or ticker tags; several words are a phrase.
  "ARM" used to return an ARMS sale and Senator ARMSTRONG because a word
  could stop part-way. Only the LAST word may still stop part-way, once it
  is five characters or more: "robin" finds Robinhood.
* WORD FORMS (2026-09-18). A plural matches its singular and back —
  "tariff" finds "tariffs", "rate cut" finds "rate cuts", "company" finds
  "companies" — by a small fixed suffix rule, the same on both sides.
* A TICKER TYPED IN CAPITALS IS EXACT. "ARM" is compared as typed, never
  through the word-form rule, or "arms" would come back; "arm" in lower case
  is the word and does take its forms.
* COMPANY NAMES (2026-09-18). A query that is a company's ticker, its name
  or a known alias also finds the stories tagged with that ticker, and a
  ticker also finds headlines naming the company: "robinhood" finds stories
  tagged HOOD, "HOOD" finds "Robinhood Rallies". Resolved off the SEC list
  the symbol picker uses, and only when the match is exact — the ticker
  itself, or the query as the name's leading words — so "fed" resolves to
  nothing rather than to FedEx.
"""

from __future__ import annotations

import re

#: How long the last query word must be before it may match as a prefix.
PREFIX_MIN = 5

#: Words the plural rule must leave alone.
_KEEP = frozenset({"news", "series", "species", "always", "perhaps", "whereas"})

#: A query token typed as a ticker: capitals and digits, one to five.
_TICKER_TYPED = re.compile(r"^[A-Z][A-Z0-9]{0,4}$")

#: Leading words too common to stand for a company on their own; a name that
#: starts with one is matched whole ("bank of america"), never by that word.
_GENERIC = frozenset({
    "american", "bank", "first", "united", "general", "national", "global",
    "international", "new", "the", "capital", "digital", "energy", "one", "us",
    "china", "royal", "western", "southern", "northern", "eastern", "pacific",
    "atlantic", "federal", "standard", "advanced", "applied", "great", "home",
    "health", "financial", "gold", "silver", "blue", "green", "north", "south",
})
_NAME_TAIL = re.compile(
    r"(,|/| INC\b| CORP\b| CORPORATION\b| PLC\b| LTD\b| LIMITED\b| CO\b| COMPANY\b"
    r"| GROUP\b| HOLDINGS\b| HOLDING\b| N\.?V\.?\b| S\.?A\.?\b| AG\b| SE\b| TRUST\b| ETF\b| CLASS\b).*$")


def stem(word: str) -> str:
    """A plural's singular, by suffix — "tariffs" → "tariff", "companies" →
    "company", "crashes" → "crash". Short words and a few fixed ones are left
    as they are; the rule only has to agree with itself on both sides."""
    if len(word) <= 3 or word in _KEEP:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    """`text` as lower-case words, split on anything that is not a letter or a
    digit."""
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


def query_terms(query: str) -> list[tuple[str, bool]]:
    """The query's words, each marked LITERAL when it was typed as a ticker."""
    raw = [w for w in re.split(r"[^A-Za-z0-9]+", query or "") if w]
    return [(w.lower(), bool(_TICKER_TYPED.match(w))) for w in raw]


def _phrase_in(terms: list[tuple[str, bool]], hay: list[str]) -> bool:
    if not terms:
        return True
    stems = [stem(w) for w in hay]
    last = len(terms) - 1
    for i in range(len(hay) - last):
        ok = True
        for k, (term, literal) in enumerate(terms):
            got, got_stem = hay[i + k], stems[i + k]
            if literal:
                ok = got == term
            else:
                want = stem(term)
                ok = got_stem == want or got == term or (
                    k == last and len(term) >= PREFIX_MIN and got.startswith(term))
            if not ok:
                break
        if ok:
            return True
    return False


def matches(query: str, *fields: str | None, tickers: tuple[str, ...] = (),
            names: tuple[str, ...] = (), tags: tuple[str, ...] | list[str] = ()) -> bool:
    """Does a story match `query`? `fields` are its texts, HEADLINE FIRST;
    `tags` its ticker tags; `tickers` and `names` the query's company
    expansion (see expand).

    A query typed as a ticker that names a company is about THAT company: it
    matches the company's tag, its name in the headline, and the ticker as a
    word in the headline — not the word anywhere in a summary, where "HOOD"
    had matched "under the hood" (2026-09-18)."""
    terms = query_terms(query)
    if not terms:
        return True
    as_ticker = bool(tickers) and all(lit for _, lit in terms)
    texts = [fields[0]] if as_ticker and fields else list(fields)
    if any(_phrase_in(terms, words(f)) for f in texts if f):
        return True
    if tickers and any(t in tickers for t in tags):
        return True
    headline = fields[0] if fields else None
    for name in names:
        # A company's name is matched exactly, word for word: "Arm", never "arms".
        name_terms = [(w, True) for w in words(name)]
        if headline and _phrase_in(name_terms, words(headline)):
            return True
    return False


def short_name(name: str) -> str | None:
    """How a headline calls a company: its SEC name without the legal tail,
    and only its first word when that word is distinctive — "Robinhood" for
    Robinhood Markets, Inc., "NVIDIA" for NVIDIA CORP, but "Bank Of America"
    whole."""
    base = _NAME_TAIL.sub("", (name or "").upper()).strip(" .,-")
    parts = base.split()
    if not parts:
        return None
    if parts[0].lower() not in _GENERIC and len(parts[0]) >= 3:
        return parts[0].lower()
    return " ".join(parts).lower() if len(parts) > 1 else None


def expand(query: str) -> dict:
    """The companies a query names EXACTLY: its ticker, or the query as the
    leading words of a company's name, or a known alias. Returns their
    tickers and short names ({"tickers": [...], "names": [...]}); empty when
    the query names no company. Only queries of up to four words are tried."""
    from alphadesk.config import _ALIASES, search_symbols
    q = " ".join((query or "").split())
    if not q or len(q.split()) > 4:
        return {"tickers": [], "names": []}
    key = re.sub(r"[^A-Z0-9 ]", " ", q.upper())
    key = " ".join(key.split())
    tickers: list[str] = []
    tickers.extend(_ALIASES.get(key.replace(" ", ""), ()))
    hits = search_symbols(q, 5)
    for h in hits[:1]:
        sym = (h.get("symbol") or "").upper()
        name_key = " ".join(re.sub(r"[^A-Z0-9 ]", " ", (h.get("name") or "").upper()).split())
        if sym == key.replace(" ", "") or name_key == key or name_key.startswith(key + " "):
            if sym not in tickers:
                tickers.append(sym)
    names: list[str] = []
    for sym in tickers:
        hit = next((h for h in hits if (h.get("symbol") or "").upper() == sym), None)
        n = short_name(hit.get("name") if hit else "") if hit else None
        if n is None:
            from alphadesk.config import company_name
            n = short_name(company_name(sym) or "")
        if n and n not in names:
            names.append(n)
    return {"tickers": tickers, "names": names}
