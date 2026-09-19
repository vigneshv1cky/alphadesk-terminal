"""When US statistical agencies actually publish (2026-09-15).

The vendor's economic calendar is right about nearly every US release and
wrong about a few, always by the same hour: measured 2026-09-14 against the
official schedules, 53 of 57 US times matched, and retail sales and the
Employment Cost Index were listed at 09:30 New York time. Measured again a
day later, both were still an hour late — the error is systematic, not a
one-off, and the reader sees a time that is simply not when the number
comes out.

THE AGENCIES PUBLISH ON A FIXED CLOCK. The Bureau of Labor Statistics, the
Census Bureau and the Bureau of Economic Analysis release at 08:30 ET; the
Conference Board, the Institute for Supply Management and the University of
Michigan at 10:00; the Federal Reserve's rate decision at 14:00. Those times
are the agencies' own, published in their release schedules — this is not an
estimate, and nothing here invents a time for a release the vendor did not
list.

The rule is deliberately narrow:

  * US rows only, matched on a DISTINCTIVE phrase in the release's name;
  * the date the vendor gives is never changed, only the clock;
  * a row already on the agency's time is left exactly as it was, so the
    table is invisible except where the vendor disagrees;
  * a corrected row says so (`time_source: "agency"`), and the panel can
    tell the reader which clock it is reading.
"""

from __future__ import annotations

import re

#: (pattern, hour, minute, agency). Order matters: the first match wins, so
#: a more specific phrase comes before a looser one.
SCHEDULE: tuple[tuple[str, int, int, str], ...] = (
    # 08:30 ET — BLS, Census and BEA principal indicators.
    (r"\bnon[- ]?farm payrolls?\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bunemployment rate\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\baverage hourly earnings\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bparticipation rate\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\b(core )?inflation rate\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bcpi\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bproducer price(s)? index\b|\bppi\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bemployment cost\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bimport prices?\b|\bexport prices?\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bproductivity\b|\bunit labou?r costs?\b", 8, 30, "Bureau of Labor Statistics"),
    (r"\bretail sales\b", 8, 30, "Census Bureau"),
    (r"\bdurable goods\b", 8, 30, "Census Bureau"),
    (r"\bhousing starts\b|\bbuilding permits\b", 8, 30, "Census Bureau"),
    (r"\bbalance of trade\b|\btrade balance\b", 8, 30, "Census Bureau"),
    (r"\bwholesale inventories\b|\bretail inventories\b", 8, 30, "Census Bureau"),
    (r"\bgdp (growth|price|sales)\b", 8, 30, "Bureau of Economic Analysis"),
    (r"\bpersonal (income|spending)\b", 8, 30, "Bureau of Economic Analysis"),
    (r"\bpce price index\b|\bcore pce\b", 8, 30, "Bureau of Economic Analysis"),
    (r"\b(initial|continuing) jobless claims\b", 8, 30, "Department of Labor"),
    (r"\bphiladelphia fed\b|\bphilly fed\b", 8, 30, "Federal Reserve Bank of Philadelphia"),
    (r"\bempire state\b", 8, 30, "Federal Reserve Bank of New York"),
    # 10:00 ET — the survey houses and the rest of Census.
    (r"\bism (manufacturing|services|non[- ]?manufacturing)\b", 10, 0, "Institute for Supply Management"),
    (r"\bconsumer confidence\b", 10, 0, "Conference Board"),
    (r"\bmichigan\b", 10, 0, "University of Michigan"),
    (r"\bjolts\b|\bjob openings\b", 10, 0, "Bureau of Labor Statistics"),
    (r"\bnew home sales\b|\bexisting home sales\b|\bpending home sales\b", 10, 0, "Census Bureau / NAR"),
    (r"\bconstruction spending\b|\bfactory orders\b|\bbusiness inventories\b", 10, 0, "Census Bureau"),
    # The Fed's own clock.
    (r"\bfed interest rate decision\b|\bfomc (statement|rate)\b", 14, 0, "Federal Reserve"),
)

_COMPILED = tuple((re.compile(p, re.I), h, m, who) for p, h, m, who in SCHEDULE)


def agency_time(event: str) -> tuple[int, int, str] | None:
    """(hour, minute, agency) in New York time for a release this table
    knows, else None. Pure."""
    for pattern, hour, minute, who in _COMPILED:
        if pattern.search(event or ""):
            return hour, minute, who
    return None


def correct_times(rows: list[dict]) -> int:
    """Put US rows on their agency's clock where the vendor disagrees, in
    place. Returns how many were moved; the date is never changed."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    moved = 0
    for r in rows:
        if (r.get("country") or "").upper() not in ("US", "USA"):
            continue
        hit = agency_time(r.get("event") or "")
        stamp = r.get("time") or ""
        if not hit or len(stamp) < 16:
            continue
        hour, minute, who = hit
        try:
            at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(ny)
        except ValueError:
            continue
        if (at.hour, at.minute) == (hour, minute):
            continue
        fixed = at.replace(hour=hour, minute=minute, second=0, microsecond=0)
        r["time"] = fixed.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
        r["vendor_time"] = stamp
        r["time_source"] = "agency"
        r["time_agency"] = who
        moved += 1
    return moved
