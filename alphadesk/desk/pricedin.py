"""The figures behind "is the move already priced in" (2026-10-03).

Priced in is a judgement about expectations that no feed contains. What can be
measured is the price's own history around the same kind of event: how this
stock has typically moved after reports, how far it had already run into them,
and how far it has moved since the event in question. Those are laid beside
today's move with analyst targets as the one external reference. NO VERDICT.
"""

from __future__ import annotations

from datetime import date
from statistics import median


def _closes(daily: list[dict]) -> list[tuple[str, float]]:
    return [(str(b["t"])[:10], b["c"]) for b in daily if b.get("c")]


def _pct(new, old):
    return round(100 * (new / old - 1), 2) if new and old else None


def _before(closes, day: str):
    prior = [i for i, (d, _) in enumerate(closes) if d < day]
    return prior[-1] if prior else None


def report_reactions(reports: list[dict], daily: list[dict], today: str, limit: int = 8, run_sessions: int = 10) -> list[dict]:
    """For each past report: the move from the close before the report date to
    the close after it (two sessions, so it covers a report before the open or
    after the close alike), the move on the report date alone, and the run in
    the `run_sessions` sessions leading into it. `reports` carry `date`."""
    closes = _closes(daily)
    out = []
    for r in sorted(reports, key=lambda x: str(x.get("date")), reverse=True):
        day = str(r.get("date") or "")[:10]
        if not day or day >= today or r.get("upcoming"):
            continue
        i = _before(closes, day)
        if i is None:
            continue
        base = closes[i][1]
        on_day = next((c for d, c in closes if d == day), None)
        after = next((c for d, c in closes if d > day), None)
        if after is None:
            continue
        out.append({"date": day,
                    "eps_surprise_pct": r.get("surprise_pct"),
                    "reaction_two_session_pct": _pct(after, base),
                    "report_day_pct": _pct(on_day, base) if on_day else None,
                    "run_into_report_pct": _pct(base, closes[i - run_sessions][1]) if i - run_sessions >= 0 else None})
        if len(out) >= limit:
            break
    return out


def priced_in_view(symbol: str, reports: list[dict], daily: list[dict], today: str,
                   since: str = "", targets: dict | None = None, week52_position=None,
                   run_sessions: int = 10) -> dict:
    closes = _closes(daily)
    last_day, last = (closes[-1] if closes else (None, None))
    past = report_reactions(reports, daily, today, run_sessions=run_sessions)
    abs_moves = [abs(p["reaction_two_session_pct"]) for p in past if p["reaction_two_session_pct"] is not None]
    runs = [p["run_into_report_pct"] for p in past if p["run_into_report_pct"] is not None]
    upcoming = sorted((r for r in reports if r.get("upcoming") or str(r.get("date") or "")[:10] >= today),
                      key=lambda r: str(r.get("date")))
    nxt = next(iter(upcoming), None)
    now_run = _pct(last, closes[-1 - run_sessions][1]) if len(closes) > run_sessions else None
    out = {
        "symbol": symbol, "as_of": last_day, "last_close": last,
        "past_reports": past,
        "typical_report_move_pct": round(median(abs_moves), 2) if abs_moves else None,
        "typical_run_into_report_pct": round(median(runs), 2) if runs else None,
        "next_report": ({"date": str(nxt.get("date"))[:10],
                         "days_away": (date.fromisoformat(str(nxt["date"])[:10]) - date.fromisoformat(today)).days}
                        if nxt else None),
        f"run_last_{run_sessions}_sessions_pct": now_run,
    }
    if since and closes:
        i = _before(closes, since[:10])
        out["since"] = since[:10]
        out["move_since_pct"] = _pct(last, closes[i][1]) if i is not None else None
        if out["move_since_pct"] is not None and out["typical_report_move_pct"]:
            out["move_since_in_typical_report_moves"] = round(abs(out["move_since_pct"]) / out["typical_report_move_pct"], 1)
    t = targets or {}
    if t.get("mean") and last:
        out["analyst_targets"] = {"low": t.get("low"), "mean": t.get("mean"), "high": t.get("high"),
                                  "mean_vs_last_pct": _pct(t["mean"], last)}
    if week52_position is not None:
        out["week52_position_pct"] = week52_position
    out["what_this_cannot_tell"] = (
        "Priced in is about expectations, which no feed holds. These are the stock's own reactions to past "
        "reports, its run into them, and its move since the event, set beside analyst targets; a past "
        "reaction is not a forecast and the report's date and timing are the vendor's.")
    return out
