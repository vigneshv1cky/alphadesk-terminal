"""The funds built ON one company (2026-09-15).

A reader looking at NVIDIA wants to know what else trades off it: the 2x
long, the inverse, the option-income fund, the buffered one. Twenty-three
US-listed funds carry NVIDIA's name, twenty-six Tesla's, sixteen
MicroStrategy's, two CrowdStrike's.

WHAT THIS IS NOT: the funds that HOLD the stock. Per-stock fund exposure is
on no vendor a reader here can reach — FMP's exposure endpoint is retired
(403 "legacy"), its replacement does not exist (404) and its holdings lists
are an Ultimate dataset. So this answers "what is built on this company",
never "who owns it", and the panel says as much rather than implying a
complete picture.

A COMPANY NAMED AFTER ITS INDUSTRY BREAKS THE WORD MATCH (2026-09-20). The
distinctive word is the company's own coinage for NVIDIA or Tesla, but Space
Exploration Technologies gives "space", and twelve space-sector ETFs joined
SPCX's panel beside its real 2x longs and shorts. So a name-only match is
kept only when the fund declares what it does to a single stock, or when the
classifier (fundclass.py, on the idle worker) says the name reads as a
single-stock product. Sector look-alikes are dropped, not shown in a second
group — the panel answers one question.

THE MATCH IS ON THE NAME, and a fund name is the issuer's own words, so the
rules are conservative:

  * the ticker must appear as a WHOLE WORD ("2X Long NVDA Daily"), never as
    a fragment, or every fund with those letters inside a word joins in;
  * the company's name counts too ("Leverage Shares - 2x NVIDIA"), but only
    when it is distinctive — MicroStrategy renamed itself Strategy, and
    "Strategy" matches 232 funds that have nothing to do with it;
  * US listings only. Foreign lines (Leverage Shares' London 2x NVIDIA, a
    Toronto one) carry a suffix and cannot be priced or charted on the
    reader's keys, so listing them would show a name and no figures.

The KIND is read from the same name — leveraged, inverse, income, buffered,
paired — because nothing in the listing says what a fund does.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("alphadesk.related_funds")

#: Kept per company. Tesla's twenty-six is the widest seen; the cap is a
#: guard against a name that matches too freely, not a ranking.
MAX_FUNDS = 40

#: Priced in one basket (/api/quotes caps at 50).
MAX_PRICED = 40

#: A company word this common is not evidence: "Strategy" is MicroStrategy's
#: new name and 232 funds use it as a noun.
_COMMON_WORDS = {
    "strategy", "growth", "income", "value", "global", "alpha", "core", "select", "capital",
    "technology", "energy", "materials", "health", "digital", "quality", "target", "premium",
    "innovation", "future", "american", "united", "national", "international", "first", "next",
}

#: A name carrying one of these is a FUND's name, not a company's. Read as
#: a company it hands back the issuer's brand — CRWC is "Corgi CRWD 2x Daily
#: ETF", whose first word matched every Corgi fund there is (2026-09-15).
_FUND_WORDS = ("etf", "fund", "trust", "shares", "daily", "index", "portfolio")

#: Words that end a company's legal name rather than naming it.
_SUFFIXES = {"inc", "inc.", "incorporated", "corp", "corp.", "corporation", "co", "co.", "company",
             "plc", "ltd", "ltd.", "limited", "holdings", "holding", "group", "sa", "nv", "ag",
             "class", "a", "b", "c", "common", "stock", "the"}


def company_word(name: str | None) -> str | None:
    """The distinctive word in a company's name, or None when it has none.

    "NVIDIA Corporation" gives nvidia; "Tesla, Inc." tesla; "Strategy Inc"
    nothing, because the only word left is one 232 unrelated funds use; a
    fund's own name nothing, because its first word is its issuer."""
    low = str(name or "").lower()
    if any(re.search(rf"(?<![a-z]){w}(?![a-z])", low) for w in _FUND_WORDS):
        return None
    words = [w for w in re.sub(r"[^A-Za-z0-9 ]", " ", str(name or "")).lower().split()
             if w not in _SUFFIXES]
    if not words:
        return None
    first = words[0]
    return first if len(first) >= 4 and first not in _COMMON_WORDS else None


def _leverage(name: str) -> float | None:
    """The multiple a fund's name states, negative when it is short."""
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*[xX]\b", name)
    if not m:
        return None
    mult = float(m.group(1))
    short = re.search(r"\b(short|bear|inverse)\b", name, re.I) or mult < 0
    return -abs(mult) if short else abs(mult)


def fund_kind(name: str) -> str:
    """What the fund does, read from its name.

    leveraged / inverse: a stated multiple, long or short. income: the
    option-writing funds (YieldMax, YieldBOOST, "Option Income"). buffered:
    the defined-outcome ones. paired: two companies in one fund. other:
    named for the company with nothing else declared."""
    low = name.lower()
    mult = _leverage(name)
    if mult is not None:
        return "inverse" if mult < 0 else "leveraged"
    if re.search(r"\b(short|bear|inverse)\b", low):
        return "inverse"
    if re.search(r"buffer|defined outcome|defined income|target income|target 25", low):
        return "buffered"
    if re.search(r"income|yield|covered call|option|distribution|premium|weeklypay|weekly pay", low):
        return "income"
    # Two full positions, joined by an ampersand or the WORD "and"
    # (2026-09-20): "Leverage Shares 100% TSLA AND 100% SPCX Daily ETF" read
    # as "other" because only the ampersand was looked for.
    if re.search(r"100%.*(?:&|\band\b).*100%", low):
        return "paired"
    return "other"


#: The order the panel groups them in: what the fund does to the stock
#: first, what it pays second.
KIND_ORDER = ("leveraged", "inverse", "income", "buffered", "paired", "other")


def is_us_listing(symbol: str) -> bool:
    """A plain US ticker. A dot or a longer code is a foreign line (NVD2.L,
    NVHE.TO), which the reader's keys cannot price."""
    return bool(re.fullmatch(r"[A-Z]{1,5}", symbol or ""))


def keep_fund(matched: str, kind: str, verdict: str | None) -> bool:
    """Whether a matched fund belongs in "funds built on this company". Pure.

    A TICKER in the name is proof — no other company's fund carries it. A
    name-only match needs either the classifier's verdict or, until one
    exists, a name that declares what it does to a single stock: leveraged,
    inverse, income, buffered, paired. A plain "other" name-only match is a
    sector fund that happens to share a word (ARK Space & Defense)."""
    if matched == "ticker":
        return True
    if verdict == "single":
        return True
    if verdict == "sector":
        return False
    return kind != "other"


def candidate_rows(names: dict[str, str], symbol: str, company: str | None) -> list[dict]:
    """Every US-listed fund whose NAME carries this company, before any
    judgement about what the fund is. Pure."""
    sym = (symbol or "").upper()
    if not sym:
        return []
    word = company_word(company)
    ticker = re.compile(rf"(?<![A-Za-z0-9]){re.escape(sym)}(?![A-Za-z0-9])")
    rows = []
    for fund, name in names.items():
        if fund == sym or not name or not is_us_listing(fund):
            continue
        by_ticker = bool(ticker.search(name))
        by_word = bool(word and re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", name, re.I))
        if not (by_ticker or by_word):
            continue
        rows.append({"symbol": fund, "name": name, "kind": fund_kind(name),
                     "leverage": _leverage(name), "matched": "ticker" if by_ticker else "name"})
    return rows


def single_stock_funds(names: dict[str, str], symbol: str, company: str | None,
                       limit: int = MAX_FUNDS, verdicts: dict[str, str] | None = None) -> list[dict]:
    """Every US-listed fund BUILT ON this company, grouped by what it does.
    Pure: `names` is the vendor's whole fund listing, symbol to name, and
    `verdicts` what the classifier has decided about a name so far."""
    said = verdicts or {}
    out = [r for r in candidate_rows(names, symbol, company)
           if keep_fund(str(r["matched"]), str(r["kind"]), said.get(str(r["name"])))]
    # Grouped by what the fund does, and inside a group by the size of the
    # bet: 3x before 2x, -3x before -1x. Alphabetical where neither states
    # a multiple, so the list does not reshuffle between reads.
    out.sort(key=lambda r: (KIND_ORDER.index(str(r["kind"])), -abs(float(r["leverage"] or 0)), str(r["symbol"])))
    return out[:limit]


def related_funds(symbol: str) -> dict:
    """{symbol, company, funds, is_fund, source}. The funds built on one
    company, priced. Raises NeedsKey when no connected vendor lists funds.

    A FUND asked about itself answers an empty list and says so: nothing is
    built on a fund, and what it holds is the holdings panel's question."""
    from alphadesk.providers import get_prices
    router = get_prices()
    sym = symbol.upper()
    names = router.ask("fund_names") or {}
    source = router.answered_by
    quote = router.get("quote", sym) or {}
    if sym in names:
        return {"symbol": sym, "company": names.get(sym) or quote.get("name"),
                "funds": [], "is_fund": True, "source": source}
    # What the classifier already knows, then the rest of this company's
    # look-alikes queued for the idle worker. A ticker match needs no model:
    # it is recorded as a known single-stock name, and those are exactly what
    # the classifier learns from (fundclass.py).
    from alphadesk import fundclass
    from alphadesk.ledger import store
    candidates = candidate_rows(names, sym, quote.get("name"))
    known = store.fund_verdicts([str(c["name"]) for c in candidates]) if candidates else {}
    # A fund read against its own documents outranks both tests below it.
    known.update({str(c["name"]): fundclass.VERIFIED[str(c["name"])]
                  for c in candidates if str(c["name"]) in fundclass.VERIFIED})
    rows = single_stock_funds(names, sym, quote.get("name"), verdicts=known)
    try:
        store.queue_fund_names([str(c["name"]) for c in candidates if c["matched"] == "ticker"],
                               verdict="single", model="ticker")
        unjudged = {str(c["name"]): str(c["symbol"]) for c in candidates
                    if c["matched"] == "name" and c["name"] not in known}
        store.queue_fund_names(list(unjudged))
        # Ask the vendors what each one IS, in the background under this
        # reader: a name states the structure, not the subject (fundclass).
        if unjudged and getattr(router, "uid", None):
            from alphadesk.ingest import background_fill
            background_fill.submit(
                "fundrecord", router.uid, list(unjudged.values()),
                lambda syms: fundclass.read_records(
                    {n: s for n, s in unjudged.items() if s.upper() in {x.upper() for x in syms}}))
    except Exception as exc:                          # a queue that fails never costs a panel
        log.debug("related funds: could not queue names (%s)", exc)
    priced = {}
    if rows:
        try:
            priced = dict(router.ask("quotes", [r["symbol"] for r in rows[:MAX_PRICED]]) or {})
        except Exception as exc:                      # a basket that fails leaves the names
            log.debug("related funds: no prices for %s (%s)", sym, exc)
    # HOW MUCH OF IT TRADES, not how big it is (2026-09-17, the owner's
    # call, replacing capitalisation). These are trading vehicles: what
    # decides whether a line is usable is whether anyone is on the other
    # side of the order. NVDX and NVDU are within a tenth of each other in
    # size, $528m against $483m, and traded $68m against $19m the same
    # session. The session's share count rides the quote the prices already
    # came from, so it costs no extra vendor call.
    for r in rows:
        q = priced.get(r["symbol"]) or {}
        r["price"], r["change_pct"] = q.get("price"), q.get("change_pct")
        r["volume"] = q.get("volume")
    return {"symbol": sym, "company": quote.get("name"), "funds": rows, "is_fund": False, "source": source}
