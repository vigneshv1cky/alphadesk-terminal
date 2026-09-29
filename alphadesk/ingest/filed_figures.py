"""WHAT THE COMPANY ACTUALLY FILED, against the same quarter a year earlier
(2026-09-28, the owner: "know whats in the report and whether its a positive
or negative catalyst").

THE SECOND HALF OF THAT IS ANSWERED WITHOUT A VERDICT, deliberately. Nothing
here scores a report or labels it positive. It states each figure the company
filed, the same figure a year earlier, and the direction between them — all
three with a source. The reader draws the conclusion, which is the same call
that removed screener ranking on 2026-08-18 ("ordering a list is a judgment;
the reader makes it") and which invariant 1 requires. The other half of the
answer is already on the row beside it: the price reaction, which is a
measurement of what the market concluded rather than an opinion of ours.

KEYLESS. Every figure is the company's own XBRL from SEC EDGAR, so a reader
with no vendor at all still gets this.

THE STALENESS GUARD IS THE WHOLE DIFFICULTY, and it was measured rather than
assumed (2026-09-28, thirteen companies that had just reported). XBRL facts
arrive with the 10-Q or 10-K, which can be filed WEEKS AFTER the 8-K that
announced the results. Eight of the thirteen had the quarter on file at a lag
of 87-90 days -- exactly one quarter. Two did not: EON Resources' newest
filed quarter ended 2025-12-31, 271 days before the report, and Incannex's
was 452 days back. Printing those beside a fresh report would say the company
posted figures it has not filed, which is the quieter kind of lie this
codebase keeps catching. So the period end is ALWAYS NAMED and a quarter too
old to belong to the report is marked rather than dressed up.

AND THE PERIOD IS NAMED EVEN WHEN IT IS FRESH, because an Item 2.02 8-K is
not always a new quarter: Gray Media's filing that day RAISED GUIDANCE and
reported no period at all, while its newest filed quarter was an ordinary 90
days old and would have passed any freshness test. "The quarter just
reported" is a claim this module cannot make; "the newest quarter on file,
ended 30 June" is one it can.

THREE OF THE THIRTEEN HAD NO REVENUE TAG AT ALL -- VinFast, Inventiva and
NioCorp. A foreign private issuer reports under IFRS and tags its filings
differently, so the US-GAAP concepts here find nothing. That is a coverage
gap, stated as one: an empty answer says the SEC holds no US-GAAP figures for
this filer, never that the company reported nothing.
"""
from __future__ import annotations

import logging
from datetime import date

log = logging.getLogger(__name__)

# A quarter belongs to the report when it ended within this many days of it.
# MEASURED: the eight companies whose quarter was on file sat at 87-90 days;
# the two that were not sat at 271 and 452. Nothing lands between, so the
# threshold is nowhere near a real boundary -- which is what makes it safe.
COVERS_REPORT_DAYS = 120

# An annual filer reports once a year, so its newest filed period is up to a
# year and a reporting lag old before the next one lands. Judging it by the
# quarterly window would call every 20-F filer's figures missing.
ANNUAL_COVERS_REPORT_DAYS = 460

# The year-ago quarter is matched by date, not by counting back four rows: a
# company that skipped a filing, or restated one, would shift the count and
# silently compare the wrong pair. A 52/53-week fiscal calendar moves the end
# date by a few days a year, so the match is the nearest end within this many
# days of one year earlier.
YEAR_AGO_TOLERANCE_DAYS = 45

# Filed figures only, in the order a reader reads them. Margins are derived
# below -- arithmetic on two filed figures is not a judgment, but it is not a
# filed figure either, so it is marked as derived.
ORDER = ["revenue", "gross_profit", "operating_income", "net_income",
         "diluted_eps", "ocf", "fcf", "capex"]


def _nearest(ends: list[str], target: date, tolerance: int) -> str | None:
    """The period end closest to `target`, within tolerance. None otherwise."""
    best, best_gap = None, None
    for e in ends:
        try:
            gap = abs((date.fromisoformat(e) - target).days)
        except ValueError:
            continue
        if gap <= tolerance and (best_gap is None or gap < best_gap):
            best, best_gap = e, gap
    return best


def _change(now: float | None, prior: float | None) -> float | None:
    """Percent change, or None where the sign makes it meaningless.

    A SWING THROUGH ZERO HAS NO PERCENTAGE. A company that lost $2.4M and now
    earns $3.8M did not improve by some percent of a negative base -- the
    arithmetic returns -258% and reads as a collapse. The figures themselves
    are shown either way and say it plainly; this returns None and the panel
    prints the direction in words instead.
    """
    if now is None or prior is None or prior == 0:
        return None
    if prior < 0 or now < 0:
        return None
    return round((now - prior) / abs(prior) * 100, 2)


def _direction(now: float | None, prior: float | None) -> str | None:
    """Up, down or flat — which survives a swing through zero when a
    percentage cannot."""
    if now is None or prior is None:
        return None
    if now > prior:
        return "up"
    return "down" if now < prior else "flat"


def filed_quarter(symbol: str, on: str | None = None) -> dict:
    """The newest quarter this company has FILED with the SEC, every figure
    beside the same quarter a year earlier.

    `on` is the report date being looked at, and decides only whether the
    filed quarter is recent enough to belong to that report. It never selects
    a different quarter: the newest on file is the newest on file.
    """
    from alphadesk.ingest.edgar_financials import fundamentals_series

    sym = (symbol or "").upper()
    out: dict = {"symbol": sym, "source": "sec-edgar", "period_end": None,
                 "prior_end": None, "metrics": [], "covers_report": None,
                 "lag_days": None, "note": None, "period": "quarterly",
                 # THE CURRENCY TRAVELS WITH THE FIGURES OR THEY ARE A LIE.
                 # Novo Nordisk files kroner, Alibaba renminbi, VinFast dong;
                 # a panel that assumes dollars misstates every one of them.
                 "currency": "USD"}
    if not sym:
        return out
    # A FOREIGN PRIVATE ISSUER FILES NO QUARTERS (2026-09-28, found on WEBUY
    # Global). It reports annually on a 20-F, and its interim 6-K carries
    # half-years that are neither a quarter nor a year. Asking only for
    # quarters left the panel empty for a company whose full annual figures
    # the SEC holds in US-GAAP. So the annual series answers where there is no
    # quarterly one, and the period is named in the payload rather than left
    # for the reader to assume -- "year ended" and "quarter ended" are not
    # interchangeable and the panel must not print one for the other.
    grain = "quarterly"
    try:
        data = fundamentals_series(sym, "quarterly", limit=24)
        if not (data.get("series") or {}):
            annual = fundamentals_series(sym, "annual", limit=12)
            if (annual.get("series") or {}):
                data, grain = annual, "annual"
    except Exception as exc:
        log.debug("filed figures: no XBRL for %s (%s)", sym, exc)
        out["note"] = "SEC EDGAR could not be read for this company just now."
        return out

    out["period"] = grain
    out["currency"] = data.get("currency") or "USD"
    series: dict[str, list[dict]] = data.get("series") or {}
    labels = {m["id"]: m.get("label") or m["id"] for m in (data.get("metrics") or [])}
    units = {m["id"]: m.get("unit") or "currency" for m in (data.get("metrics") or [])}

    ends = sorted({p["t"] for pts in series.values() for p in pts if p.get("t")})
    if not ends:
        # NAME WHAT IS OBSERVED, NOT A CAUSE WE CANNOT SEE (2026-09-28, caught
        # on Exascale Labs). The first wording blamed IFRS, which is right for
        # VinFast and Inventiva and simply false for a newly listed US company
        # that has filed no quarterly report yet -- both arrive here as an
        # empty US-GAAP fact set and nothing in it distinguishes them. Stating
        # the likely reasons without picking one is the honest form; asserting
        # the wrong one is the made-up fact this codebase keeps refusing.
        # Both grains were tried before this fires, so the filer really does
        # tag nothing in US-GAAP. That is now a narrow statement rather than
        # the catch-all it was: a 20-F filer reporting in US-GAAP is answered
        # above, and what reaches here is a genuine IFRS filer (Inventiva,
        # TSMC, Novo Nordisk) or a company that has filed nothing yet.
        out["note"] = ("SEC EDGAR holds no US-GAAP figures for this filer, annual "
                       "or quarterly. A company reporting under IFRS tags its "
                       "filings differently, and a newly listed one may have filed "
                       "no report yet.")
        return out

    period = ends[-1]
    out["period_end"] = period
    prior = _nearest(ends[:-1], date.fromisoformat(period).replace(
        year=date.fromisoformat(period).year - 1), YEAR_AGO_TOLERANCE_DAYS)
    out["prior_end"] = prior

    if on:
        try:
            lag = (date.fromisoformat(on) - date.fromisoformat(period)).days
            out["lag_days"] = lag
            # AN ANNUAL FILER'S NEWEST PERIOD IS A YEAR OLD BY DESIGN, so the
            # quarterly window would mark every 20-F filer stale and say its
            # figures were missing when they are simply annual.
            window = COVERS_REPORT_DAYS if grain == "quarterly" else ANNUAL_COVERS_REPORT_DAYS
            out["covers_report"] = lag <= window
            if lag > window:
                out["note"] = (
                    "The period behind this report is not filed yet. "
                    "These are the newest figures on record, which are older.")
        except ValueError:
            pass

    at = {mid: {p["t"]: p["v"] for p in pts} for mid, pts in series.items()}
    for mid in ORDER:
        if mid not in at:
            continue
        now = at[mid].get(period)
        was = at[mid].get(prior) if prior else None
        if now is None and was is None:
            continue
        out["metrics"].append({
            "id": mid, "label": labels.get(mid, mid), "unit": units.get(mid, "currency"),
            "value": now, "prior": was, "change_pct": _change(now, was),
            "direction": _direction(now, was), "filed": True,
        })

    # Margins, marked derived: arithmetic on two filed figures, not a filed
    # figure. Only where the revenue they divide by is positive in both
    # periods, because a margin off a negative or absent base says nothing.
    rev_now, rev_was = at.get("revenue", {}).get(period), (
        at.get("revenue", {}).get(prior) if prior else None)
    for mid, label in (("operating_income", "Operating margin"), ("net_income", "Net margin")):
        if mid not in at or not rev_now or rev_now <= 0:
            continue
        now = at[mid].get(period)
        if now is None:
            continue
        was_pct = None
        if rev_was and rev_was > 0 and at[mid].get(prior) is not None:
            was_pct = round(at[mid][prior] / rev_was * 100, 2)
        now_pct = round(now / rev_now * 100, 2)
        out["metrics"].append({
            "id": f"{mid}_margin", "label": label, "unit": "percent",
            "value": now_pct, "prior": was_pct,
            # A margin is already a percentage, so the change between two of
            # them is stated in PERCENTAGE POINTS, never as a percent of a
            # percent -- which is how a move from 2% to 4% becomes "+100%".
            "change_pct": None,
            "change_pp": (round(now_pct - was_pct, 2) if was_pct is not None else None),
            "direction": _direction(now_pct, was_pct), "filed": False,
        })
    return out
