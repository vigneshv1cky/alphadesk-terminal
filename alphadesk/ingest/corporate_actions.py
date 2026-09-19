"""Dividends and splits for one symbol, with the dates filled in.

The reader's price source answers first (the consolidated tape's own record
on the builtin: every ex-date and amount, every split). Yahoo carries no
declaration, record or payment date, so when a dividend row is missing
them and a keyed source that has them is on hand — Polygon, Alpha Vantage
or Finnhub, in that order, by the operator's environment keys — that source
is asked once and its dates are copied onto the matching ex-date. Nothing
is invented: a date either came from a source or stays blank, and the
response names every source that contributed.

A helper that fails (no entitlement, a throttle, a bad day) contributes
nothing and never fails the response.
"""

import logging

from alphadesk.providers import get_prices
from alphadesk.providers.base import ProviderError

log = logging.getLogger("alphadesk.corporate_actions")

_FILL_FIELDS = ("declaration_date", "record_date", "payment_date", "currency", "amount", "adjusted_amount")


def _needs_fill(dividends: list[dict]) -> bool:
    return any(not r.get("payment_date") or not r.get("record_date") for r in dividends)


def split_factor_after(ex_date: str, splits: list[dict]) -> float:
    """How many of today's shares one share held on `ex_date` became: the
    product of every split executed AFTER that date (Apple, 1987-05-11:
    2 × 2 × 7 × 4 = 112)."""
    factor = 1.0
    for sp in splits:
        try:
            frm, to = float(sp.get("from") or 0), float(sp.get("to") or 0)
        except (TypeError, ValueError):
            continue
        if frm > 0 and to > 0 and (sp.get("date") or "") > ex_date:
            factor *= to / frm
    return factor


def reconcile_amounts(dividends: list[dict], splits: list[dict]) -> None:
    """Every row carries both figures: `amount` as DECLARED (what a holder
    was paid per share that day) and `adjusted_amount` per today's share
    (restated through every later split). A source gives one or the other
    — Yahoo the adjusted, Polygon and Alpha Vantage the declared, Finnhub
    both — and the split chain derives the missing one. Nothing is
    invented: with no split record the two are the same number, which is
    exactly true for a company that never split."""
    for r in dividends:
        amt, adj = r.get("amount"), r.get("adjusted_amount")
        if amt is not None and adj is not None:
            continue
        f = split_factor_after(r.get("ex_date") or "", splits)
        # A declared dividend is stated to the fraction of a cent; the
        # adjusted one carries the extra digits a 112× chain needs. Yahoo's
        # adjusted figure is itself rounded, so the product is rounded back
        # (0.000536 × 112 = 0.060032 is the $0.06 Apple declared in 1987).
        if amt is None and adj is not None:
            r["amount"] = round(adj * f, 4)
        elif adj is None and amt is not None:
            r["adjusted_amount"] = round(amt / f, 6)


def fill_from(got: dict | None, out: dict) -> bool:
    """Copy the missing dates from one vendor's record onto matching
    ex-dates. True when it contributed anything. Splits are taken from it
    only when the primary had none. Pure."""
    if not got:
        return False
    by_ex = {r["ex_date"]: r for r in got.get("dividends") or [] if r.get("ex_date")}
    touched = False
    for row in out["dividends"]:
        src = by_ex.get(row["ex_date"])
        if not src:
            continue
        for f in _FILL_FIELDS:
            if not row.get(f) and src.get(f):
                row[f] = src[f]
                touched = True
    if not out["splits"] and got.get("splits"):
        out["splits"] = list(got["splits"])
        touched = True
    return touched


def corporate_actions(symbol: str) -> dict:
    """{symbol, dividends, splits, sources}. The first of the user's vendors
    that has a record is the primary; the others that carry corporate
    actions fill dates it lacks. Raises NeedsKey when none is connected."""
    from alphadesk.providers.base import EntitlementError, NeedsKey
    sym = symbol.upper()
    router = get_prices()
    base = router.ask("corporate_actions", sym)
    primary = router.answered_by
    out = {
        "symbol": sym,
        "dividends": [dict(r) for r in base.get("dividends") or []],
        "splits": [dict(r) for r in base.get("splits") or []],
        "sources": [primary] if primary else [],
    }
    for r in out["dividends"]:
        r.setdefault("adjusted_amount", None)
    if out["dividends"] and _needs_fill(out["dividends"]):
        for name in router._order("corporate_actions", "corporate_actions"):
            if name == primary:
                continue
            try:
                got = router.vendors[name].corporate_actions(sym)
            except (EntitlementError, ProviderError, NeedsKey) as exc:
                log.info("%s corporate actions unavailable for %s: %s", name, sym, exc)
                continue
            if fill_from(got, out):
                out["sources"].append(name)
            if not _needs_fill(out["dividends"]):
                break
    reconcile_amounts(out["dividends"], out["splits"])
    return out


def reset_cache() -> None:
    """Nothing is cached here any more: the per-user vendor memo holds it."""
