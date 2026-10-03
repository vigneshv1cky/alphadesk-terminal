"""Symbols with something scheduled or just filed that could move them
(2026-10-03) — a list of CANDIDATES with the evidence for each, not a
prediction. Nothing here says a stock WILL move: it gathers the dated reasons
one might, so a reader can weigh them, and says which names have already moved.
"""

from __future__ import annotations

from datetime import date

from alphadesk.desk import sessions

#: What each kind of evidence adds to a symbol's `evidence_weight`. The weights
#: only order the list; they are not a probability.
WEIGHTS = {"earnings_soon": 3, "earnings_in_horizon": 2, "halt_today": 3,
           "material_8k": 2, "stake_filing": 2, "offering_filing": 2, "on_board": 1}
_STAKE = ("SCHEDULE 13D", "SC 13D", "SCHEDULE 13G", "SC 13G", "SC TO")
_OFFERING = ("424B", "S-1", "S-3", "F-1", "F-3")


def _day(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _reaction_sessions(row: dict) -> list[date]:
    """The session(s) a report could move: before the open moves its own day,
    after the close the next trading day, and where the vendor gives no timing
    either could."""
    d = _day(row.get("report_date"))
    if d is None:
        return []
    timing = str(row.get("time") or row.get("hour") or row.get("report_time") or "").lower()
    same = sessions.on_or_next_session(d)
    after = sessions.next_session(d)
    if any(k in timing for k in ("bmo", "before", "pre")):
        return [same]
    if any(k in timing for k in ("amc", "after", "post")):
        return [after]
    return sorted({same, after})


def rank(earnings: list[dict], filings: list[dict], halts: list[dict], movers: list[dict],
         board: list[str], target_sessions: list[date]) -> list[dict]:
    """Candidates for the given target session(s), strongest evidence first.
    Inputs are the rows the matching tools return: calendar rows {symbol,
    report_date, time}, filing-feed rows {symbols, form, items, filed_at},
    halts {symbol, today, resumed, reason_code}, mover rows {symbol,
    change_pct}. `target_sessions` are the trading days being asked about."""
    by: dict[str, dict] = {}

    def add(sym, kind, when, detail):
        sym = str(sym or "").strip().upper()
        if not sym:
            return
        row = by.setdefault(sym, {"symbol": sym, "evidence_weight": 0, "evidence": []})
        if any(e["kind"] == kind and e["when"] == when for e in row["evidence"]):
            return
        row["evidence"].append({"kind": kind, "when": when, "detail": detail})
        row["evidence_weight"] += WEIGHTS[kind]

    targets = set(target_sessions)
    first = target_sessions[0] if target_sessions else None
    for r in earnings or []:
        hit = [d for d in _reaction_sessions(r) if d in targets]
        if not hit:
            continue
        timing = str(r.get("time") or r.get("hour") or r.get("report_time") or "").strip()
        add(r.get("symbol"), "earnings_soon" if first in hit else "earnings_in_horizon", str(r.get("report_date"))[:10],
            f"reports {str(r.get('report_date'))[:10]}" + (f" ({timing})" if timing else " (timing not stated)")
            + f", can move {', '.join(d.isoformat() for d in hit)}"
            + (f", EPS estimate {r['eps_estimate']}" if r.get("eps_estimate") is not None else ""))
    for f in filings or []:
        form = str(f.get("form") or "")
        kind = ("stake_filing" if form.startswith(_STAKE) else "offering_filing" if form.startswith(_OFFERING)
                else "material_8k" if form.startswith("8-K") else None)
        if kind is None:
            continue
        items = ", ".join(str(i.get("item") or i.get("code") or "") for i in (f.get("items") or []) if isinstance(i, dict)) \
            or ", ".join(str(i) for i in (f.get("items") or []) if not isinstance(i, dict))
        for sym in f.get("symbols") or []:
            add(sym, kind, str(f.get("filed_at") or "")[:16], f"{form} {items}".strip() + (f" ({f.get('role')})" if f.get("role") else ""))
    for h in halts or []:
        if h.get("today"):
            add(h.get("symbol"), "halt_today", str(h.get("halted_at") or "")[:16],
                f"halt code {h.get('reason_code') or '?'}" + ("" if h.get("resumed") else ", not yet resumed"))
    for sym in board or []:
        if str(sym).upper() in by:
            add(sym, "on_board", "", "on your board")
    moved = {str(m.get("symbol") or "").upper(): m.get("change_pct") for m in movers or []}
    out = []
    for sym, row in by.items():
        row["on_board"] = sym in {str(b).upper() for b in board or []}
        row["already_moved_pct"] = moved.get(sym)
        out.append(row)
    out.sort(key=lambda r: (-r["evidence_weight"], r["symbol"]))
    return out
