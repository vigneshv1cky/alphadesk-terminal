"""One symbol's price, news and filings lined up on the same dates (2026-10-03).

An agent asked "why did this stock move" used to make a call per source and
match the dates itself. This does the matching, once, as plain arithmetic: the
days the price moved at least a threshold, with the stories published and the
filings accepted in the window that led into each, and for every filing the
size of the move on the first session that could react to it.

NO VERDICT. Nothing here says a story or a filing CAUSED a move: the window
is the evidence, and a move with nothing attached is reported as having
nothing attached, which is itself the finding.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
CLOSE = time(16, 0)


def _ny(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.astimezone(NY) if at.tzinfo else at.replace(tzinfo=NY)


def _session_close(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), CLOSE, tzinfo=NY)


def daily_moves(bars: list[dict]) -> list[dict]:
    """[{date, close, change_pct, volume, volume_vs_median}] for every session
    after the first. `bars` are daily {t, c, v}, oldest first."""
    rows = [b for b in bars if b.get("c")]
    vols = sorted(v for v in (b.get("v") for b in rows) if v)
    median = vols[len(vols) // 2] if vols else None
    out = []
    for prev, cur in zip(rows, rows[1:]):
        out.append({
            "date": str(cur["t"])[:10], "close": cur["c"],
            "change_pct": round(100 * (cur["c"] / prev["c"] - 1), 2),
            "volume": cur.get("v"),
            "volume_vs_median": round(cur["v"] / median, 1) if cur.get("v") and median else None,
            "previous_date": str(prev["t"])[:10],
        })
    return out


def _filing_time(f: dict) -> datetime | None:
    at = _ny(f.get("accepted_at"))
    if at is not None:
        return at
    day = f.get("filing_date")
    return datetime.combine(date.fromisoformat(day), time(12, 0), tzinfo=NY) if day else None


def join_moves(bars: list[dict], articles: list[dict], filings: list[dict],
               min_move_pct: float = 10.0, since: str | None = None) -> dict:
    """The matched view. `articles` carry published_at, title, kind, tickers;
    `filings` carry filing_date, accepted_at, form, accession."""
    moves = daily_moves(bars)
    if since:
        moves = [m for m in moves if m["date"] >= since]
    big = [m for m in moves if abs(m["change_pct"]) >= min_move_pct]

    def window(m):
        return _session_close(m["previous_date"]), _session_close(m["date"])

    def stories_in(lo, hi):
        out = []
        for a in articles:
            at = _ny(a.get("published_at"))
            if at is not None and lo <= at <= hi:
                out.append({"published_at": a.get("published_at"), "title": a.get("title"),
                            "kind": a.get("kind"), "source": a.get("source"),
                            "named_tickers": len(a.get("tickers") or [])})
        return sorted(out, key=lambda s: s["published_at"] or "")

    def filings_in(lo, hi):
        out = []
        for f in filings:
            at = _filing_time(f)
            if at is not None and lo <= at <= hi:
                out.append({"form": f.get("form"), "filed": f.get("filing_date"),
                            "accession": f.get("accession"), "readable": bool(f.get("readable"))})
        return out

    days = []
    for m in big:
        lo, hi = window(m)
        stories, filed = stories_in(lo, hi), filings_in(lo, hi)
        days.append({**{k: m[k] for k in ("date", "close", "change_pct", "volume", "volume_vs_median")},
                     "window": {"from": lo.isoformat(), "to": hi.isoformat()},
                     "stories": stories, "filings": filed,
                     "nothing_attached": not stories and not filed})

    # Each filing in the span against the first session able to react to it:
    # accepted after the 4pm close reacts the NEXT session.
    dates = [m["date"] for m in moves]
    reactions = []
    for f in filings:
        at = _filing_time(f)
        if at is None or not dates or not (_session_close(dates[0]) - timedelta(days=1) <= at):
            continue
        day = at.date().isoformat()
        after_close = at.timetz().replace(tzinfo=None) >= CLOSE
        pick = next((m for m in moves if m["date"] > day or (m["date"] == day and not after_close)), None)
        if pick is None:
            continue
        reactions.append({"form": f.get("form"), "filed": f.get("filing_date"), "accession": f.get("accession"),
                          "reaction_session": pick["date"], "change_pct": pick["change_pct"],
                          "volume_vs_median": pick["volume_vs_median"]})
    return {
        "threshold_pct": min_move_pct,
        "sessions": len(moves),
        "big_move_days": days,
        "big_moves_with_nothing_attached": sum(1 for d in days if d["nothing_attached"]),
        "filing_reactions": reactions,
    }
