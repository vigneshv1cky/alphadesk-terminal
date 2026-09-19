"""Market-wide corporate calendars — dividends, stock splits, IPOs — for a
window, from the user's vendor that carries them (2026-09-14: Financial
Modeling Prep, on its Premium plan and up). Each raises NeedsKey without
one, so the panel names the plan that would fill it.

Dividends are kept to SEC filers (the same ticker file the earnings
calendar uses) and ordered within each ex-date by the user's own daily
dollar volume, most traded first: a day holds
a hundred-odd names and alphabetical buries the ones a reader trades.
Splits keep US-style symbols (no exchange suffix) — a reverse split of an
OTC name is exactly the kind a reader wants to see coming — and are
checked against a second vendor when the reader has one (FMP listed splits
that never happened; see corroborate_splits). IPOs are listed
as the vendor has them, by date.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger("alphadesk.corporate_calendars")

MAX_SPAN_DAYS = 31
LOW_LIQUIDITY_DOLLAR_VOL = 10_000_000


def _window(start: Optional[str], end: Optional[str]) -> tuple[str, str]:
    today = date.today()
    s = date.fromisoformat(start) if start else today - timedelta(days=today.weekday())
    e = date.fromisoformat(end) if end else s + timedelta(days=6)
    if e < s:
        s, e = e, s
    if (e - s).days > MAX_SPAN_DAYS:
        e = s + timedelta(days=MAX_SPAN_DAYS)
    return s.isoformat(), e.isoformat()


def _liquidity(router, symbols: list[str]) -> dict[str, float]:
    """Average daily dollar volume over twenty sessions, from the user's
    chart vendor; empty when none answers (the column then shows a dash)."""
    from alphadesk.ingest.movers import stats_from_bars
    bars = router.get("daily_history", sorted(set(symbols)), 21) or {}
    out: dict[str, float] = {}
    for sym, b in bars.items():
        if b:
            liq = stats_from_bars([x["close"] for x in b], [x["volume"] for x in b]).get("liquidity")
            if liq is not None:
                out[sym] = liq
    return out


def dividends(start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """{start, end, rows, source}: each ex-dividend in the window, SEC filers
    only, named from EDGAR, largest company first within a day (the owner's
    call, 2026-09-14, as on the earnings calendar); a company with no market
    value on the reader's vendors follows, most traded first."""
    from alphadesk.ingest import edgar
    from alphadesk.providers import get_prices
    s, e = _window(start, end)
    router = get_prices()
    rows = [dict(r) for r in router.ask("dividend_calendar", s, e)]
    source = router.answered_by
    listed = edgar._ticker_cik_map()
    if listed:
        rows = [r for r in rows if r["symbol"] in listed]
    rows = [r for r in rows if s <= r["ex_date"] <= e]
    liq = _liquidity(router, [r["symbol"] for r in rows]) if rows else {}
    caps = (router.get("market_caps", sorted({r["symbol"] for r in rows})) or {}) if rows else {}
    for r in rows:
        r["company_name"] = edgar.company_title(r["symbol"])
        r["liquidity"] = liq.get(r["symbol"])
        r["low_liquidity"] = None if r["liquidity"] is None else r["liquidity"] < LOW_LIQUIDITY_DOLLAR_VOL
        r["market_cap"] = caps.get(r["symbol"].upper())
    rows.sort(key=lambda r: (r["ex_date"], r["market_cap"] is None, -(r["market_cap"] or 0), -(r["liquidity"] or 0), r["symbol"]))
    return {"start": s, "end": e, "rows": rows, "source": source}


# Two vendors' listings of one split: the same ratio within this many days.
SPLIT_MATCH_DAYS = 3
# The vendor whose date stands when two agree on a split a day or two apart:
# Alpaca processes its customers' positions on it (SBTU, 2026-09-14: FMP the
# 25th, Alpaca the 24th, and the price moved on the 24th).
SPLIT_DATE_FIRST = ("alpaca",)


def split_rows(router, start: str, end: str) -> tuple[list[dict], list[str]]:
    """Every connected split vendor's rows for [start, end], corroborated,
    and the vendors that answered. NeedsKey when none carries the surface."""
    from alphadesk.providers.base import EntitlementError, NeedsKey, ProviderError
    order = router._order("split_calendar", "split_calendar")
    if not order:
        raise NeedsKey("split_calendar", [], signed_in=router.uid is not None)
    got: list[tuple[str, list[dict]]] = []
    refused: list[str] = []
    for name in order:
        try:
            rows = router.vendors[name].split_calendar(start, end)
        except EntitlementError:
            refused.append(name)
            continue
        except (ProviderError, NeedsKey) as exc:
            log.warning("%s split calendar failed: %s", name, exc)
            continue
        if rows is not None:
            got.append((name, rows))
    if not got:
        raise NeedsKey("split_calendar", refused, signed_in=router.uid is not None)
    return corroborate_splits(got), [n for n, _ in got]


def corroborate_splits(per_vendor: list[tuple[str, list[dict]]]) -> list[dict]:
    """One row per split, with `sources` (the vendors listing it) and
    `corroborated`: True when two vendors list the same ratio within
    SPLIT_MATCH_DAYS, False when only one of several answering vendors does,
    None when only one vendor answered and nothing could be checked.

    Measured 2026-09-14, three months of US listings: FMP and Alpaca agreed
    on 138 splits; of the ones only FMP listed, the price confirmed five and
    showed no move at all on six (ASTN, DAMD, STSM, VMRK, RUSHA/RUSHB), and a
    split Alpaca alone listed was real. A single vendor's split is a claim,
    not an event. Pure."""
    def same_ratio(a: dict, b: dict) -> bool:
        return bool(a.get("to") and a.get("from") and b.get("to") and b.get("from")) \
            and abs(a["to"] / a["from"] - b["to"] / b["from"]) < 1e-6

    several = len(per_vendor) > 1
    out: list[dict] = []
    for name, rows in per_vendor:
        for r in rows:
            sym = str(r["symbol"]).upper()
            day = date.fromisoformat(str(r["date"])[:10])
            hit = next((o for o in out if o["symbol"] == sym and name not in o["sources"] and same_ratio(o, r)
                        and abs((date.fromisoformat(o["date"]) - day).days) <= SPLIT_MATCH_DAYS), None)
            if hit is None:
                out.append({**r, "symbol": sym, "date": day.isoformat(), "sources": [name],
                            "corroborated": False if several else None})
                continue
            hit["sources"].append(name)
            hit["corroborated"] = True
            if day.isoformat() != hit["date"]:
                hit.setdefault("vendor_dates", {hit["sources"][0]: hit["date"]})[name] = day.isoformat()
                if name in SPLIT_DATE_FIRST:
                    hit["date"] = day.isoformat()
    # A vendor listing one split twice a day apart (FMP's SBTU, the 24th and
    # the 25th): the copy the other vendor did not match is the same split.
    confirmed = [o for o in out if o["corroborated"]]
    return [o for o in out if o["corroborated"] is not False or not any(
        c["symbol"] == o["symbol"] and o["sources"][0] in c["sources"] and same_ratio(c, o)
        and abs((date.fromisoformat(c["date"]) - date.fromisoformat(o["date"])).days) <= SPLIT_MATCH_DAYS for c in confirmed)]


def splits(start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """{start, end, rows, source, vendors}: each split in the window with its
    ratio, whether it is a reverse split, and whether a second vendor lists
    it. The page hides a split only one of two vendors lists unless asked."""
    from alphadesk.ingest import edgar
    from alphadesk.providers import get_prices
    s, e = _window(start, end)
    router = get_prices()
    # Asked a few days wider than the week, so a split two vendors date either
    # side of its edge is still matched (UZX: FMP the 18th, Alpaca the 21st).
    pad = timedelta(days=SPLIT_MATCH_DAYS)
    got, vendors = split_rows(router, (date.fromisoformat(s) - pad).isoformat(), (date.fromisoformat(e) + pad).isoformat())
    rows = [dict(r) for r in got if "." not in r["symbol"]]
    for r in rows:
        r["company_name"] = edgar.company_title(r["symbol"])
        r["reverse"] = bool(r.get("from") and r.get("to") and r["to"] < r["from"])
    rows = sorted((r for r in rows if s <= r["date"] <= e), key=lambda r: (r["date"], r["symbol"]))
    return {"start": s, "end": e, "rows": rows, "source": ",".join(vendors), "vendors": vendors}


# What an IPO calendar row is (2026-09-14): FMP's list mixes company IPOs
# with ETF launches and the separately listed units, rights and warrants of
# blank-check companies — 112 of 162 rows over six weeks — which bury the
# offerings a reader looks for. Read from the name FMP gives.
_BLANK_CHECK = re.compile(r"\bacquisition(?:\b|\d)|\bmerger\s+corp|\bblank check\b"
                          r"|\b(?:holdings|corp|corporation|capital|partners)\.?,?\s+[ivx]{1,4}\b", re.I)
_FUND = re.compile(r"\bETFs?\b|\bETNs?\b|\bfund\b|\btrust\b|\b(?:bull|bear)\s+\d+(?:\.\d+)?x\b", re.I)
_DEBT_OR_PREFERRED = re.compile(r"\bpreferred\b|\bnotes?\s+due\b|\bsenior notes\b|\bdebentures?\b|\d\.\d+%", re.I)
_PIECE = re.compile(r"\bwarrants?\b|\brights?\b|\bunits?\b", re.I)


def ipo_kind(company: str | None) -> str:
    """"company", "blank_check" (a SPAC and its units, rights, warrants —
    serial names like Cartesian Growth Corp. IV count), "fund" (ETFs, funds,
    leveraged daily shares) or "other_security" (another company's
    warrants, rights, preferred stock or listed notes). Pure."""
    name = company or ""
    if _BLANK_CHECK.search(name):
        return "blank_check"
    if _DEBT_OR_PREFERRED.search(name) or (_PIECE.search(name) and not _FUND.search(name)):
        return "other_security"
    if _FUND.search(name):
        return "fund"
    return "company"


# A symbol already trading this long before its listing date was an uplisting
# or a rename, not a new listing.
ALREADY_TRADING_DAYS = 7


def _bar_aliases(r: dict) -> list[str]:
    """The symbol as FMP writes it, and as the chart vendor may: NYSE units
    and warrants carry a suffix FMP folds in (PNAQU is Alpaca's PNAQ.U)."""
    sym = str(r.get("symbol") or "").upper()
    if not sym:
        return []
    out = [sym]
    # Only NYSE spells them apart; a Nasdaq unit asked as "X.U" is a refused
    # symbol, and each refusal costs the batch a retry.
    if str(r.get("exchange") or "").upper().startswith("NYSE") and len(sym) >= 4:
        if sym.endswith("U"):
            out.append(sym[:-1] + "-U")
        elif sym.endswith("W"):
            out.append(sym[:-1] + "-WS")
    return out


def mark_listings(rows: list[dict], bars: dict[str, list[dict]], today: str) -> None:
    """For each row whose date has passed, whether the symbol actually traded:
    `listing` is "listed" with `first_trade` (its first session in the bars),
    "already_trading" (it traded well before the date: an uplisting or a
    rename), or "no_trades"; None for a date still ahead. FMP rarely updates
    its own status — measured 2026-09-14, 119 of 134 past rows still read
    "Expected" though the symbol had started trading. Pure."""
    for r in rows:
        r["listing"] = r["first_trade"] = None
        if r["date"] >= today or not r.get("symbol"):
            continue
        firsts = []
        for alias in _bar_aliases(r):
            b = bars.get(alias) or []
            if b:
                t = b[0]["ts"]
                firsts.append(t.date().isoformat() if hasattr(t, "date") else str(t)[:10])
        if not firsts:
            r["listing"] = "no_trades"
            continue
        first = min(firsts)
        if first < (date.fromisoformat(r["date"]) - timedelta(days=ALREADY_TRADING_DAYS)).isoformat():
            r["listing"] = "already_trading"
        else:
            r["listing"], r["first_trade"] = "listed", first


def ipos(start: Optional[str] = None, end: Optional[str] = None) -> dict:
    """{start, end, rows, source, checked}: expected and priced IPOs in the
    window, with the deal size at the middle of the price range when both are
    known, what kind of listing each is, and — once its date has passed —
    whether it traded, from the reader's chart vendor. `checked` is False
    when no chart vendor answered, so no row carries a listing verdict."""
    from alphadesk.config import now_et
    from alphadesk.providers import get_prices
    s, e = _window(start, end)
    router = get_prices()
    rows = [dict(r) for r in router.ask("ipo_calendar", s, e)]
    source = router.answered_by
    for r in rows:
        lo, hi, sh = r.get("price_low"), r.get("price_high"), r.get("shares")
        r["deal_size"] = round(sh * (lo + hi) / 2) if sh and lo is not None and hi is not None else None
        r["kind"] = ipo_kind(r.get("company"))
    rows = sorted((r for r in rows if s <= r["date"] <= e), key=lambda r: (r["date"], r.get("company") or ""))
    today = now_et().date().isoformat()
    past = [r for r in rows if r["date"] < today and r.get("symbol")]
    bars = None
    if past:
        # Enough sessions to reach a week before the earliest listing date.
        since = date.fromisoformat(min(r["date"] for r in past)) - timedelta(days=ALREADY_TRADING_DAYS + 7)
        sessions = min(400, (date.fromisoformat(today) - since).days)
        try:
            bars = router.get("daily_history", sorted({a for r in past for a in _bar_aliases(r)}), sessions)
        except Exception as exc:
            log.debug("listing check unavailable: %s", exc)
    if bars is None:          # nothing past to check, or no chart vendor answered
        for r in rows:
            r["listing"] = r["first_trade"] = None
    else:
        mark_listings(rows, bars, today)
    return {"start": s, "end": e, "rows": rows, "source": source, "checked": bars is not None or not past}
