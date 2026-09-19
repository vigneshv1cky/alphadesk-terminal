"""Today's market, in one compact reply for a reader's agent (2026-09-17).

A reader asks their own agent "what's trending today, what news is trending,
what should I look at" — and the agent needs the day's facts in ONE call,
small enough for a connector (Claude.ai, ChatGPT) to take whole. This
composes what the terminal already has, on the reader's own keys:

  * the market tape (indexes, rates, commodities, crypto)
  * top movers: gainers, losers and most active
  * sector funds' moves today
  * news activity: the symbols with the most stories today, each with its
    newest headline and link, and the newest stories overall
  * earnings reporting today (primary listings)
  * today's US economic releases

ORDERING (the owner's call, 2026-09-17). Lists here ARE sorted, and only by
a measured number shown beside each row — % change, volume, story count,
market cap, release time. No score, no weighting, no pick: which of these
deserve attention is the reader's (or their agent's) judgment. The
terminal's own screener window stays alphabetical (invariant 3).

Each section fails on its own: a vendor the reader has not connected, or one
that errors, leaves that section out and names why under `unavailable`, and
the rest still answers.
"""

from __future__ import annotations

import contextvars
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime

log = logging.getLogger("alphadesk.today")

#: How many rows each list carries by default.
TOP = 10
#: Earnings and economic rows carried at most.
MAX_EARNINGS = 25
MAX_ECONOMIC = 20


def _pick(row: dict, keys: tuple[str, ...]) -> dict:
    return {k: row.get(k) for k in keys if row.get(k) is not None}


def _tape() -> list[dict]:
    from alphadesk.providers import get_prices
    return [_pick(r, ("symbol", "label", "price", "change_pct")) for r in get_prices().market_tape() or []]


def _movers(top: int) -> dict:
    from alphadesk.providers import get_prices
    got = get_prices().ask("movers", top=top) or {}
    keys = ("symbol", "name", "price", "change_pct", "volume")
    return {tab: [_pick(r, keys) for r in (got.get(tab) or [])[:top]]
            for tab in ("gainers", "losers", "most_active")}


def _sectors() -> list[dict]:
    from alphadesk.ingest import sectors
    got = sectors.sectors() or {}
    rows = [_pick(r, ("symbol", "label", "change_pct")) for r in got.get("sectors") or []]
    return sorted(rows, key=lambda r: r.get("change_pct") if r.get("change_pct") is not None else float("-inf"),
                  reverse=True)


def _news(top: int, since_iso: str) -> dict:
    from alphadesk.identity import request_user
    from alphadesk.ingest.news import news_owner
    from alphadesk.ledger import store
    from alphadesk.providers.base import NeedsKey

    uid = request_user()
    if not uid or not store.get_user_keys(uid, "news"):
        raise NeedsKey("news", [], signed_in=bool(uid))
    articles = store.recent_articles(since_iso, limit=2000, owner=news_owner(uid))
    counts: Counter[str] = Counter()
    newest: dict[str, dict] = {}
    for a in articles:                       # newest first
        for t in a["tickers"]:
            counts[t] += 1
            newest.setdefault(t, a)

    def brief(a: dict) -> dict:
        return {"title": a["title"], "url": a.get("url") or "", "source": a.get("source") or "",
                "published_at": a.get("published_at")}

    # Most stories first; ties alphabetical, so the order is stable.
    busiest = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return {
        "stories_today": len(articles),
        "most_covered": [{"symbol": s, "stories": n, "newest": brief(newest[s])} for s, n in busiest],
        "latest": [{**brief(a), "tickers": a["tickers"]} for a in articles[:top]],
    }


def _earnings(today: str) -> list[dict]:
    from alphadesk.ingest import earnings_calendar
    rows = earnings_calendar.rows_between(today, today)
    rows = [r for r in rows if r.get("listing", "primary") == "primary"]
    rows.sort(key=lambda r: (-(r.get("market_cap") or 0), r["symbol"]))
    keys = ("symbol", "company_name", "session", "eps_estimate", "eps_actual", "revenue_estimate",
            "revenue_actual", "market_cap")
    return [_pick(r, keys) for r in rows[:MAX_EARNINGS]]


def _economic(today: str) -> list[dict]:
    from alphadesk.ingest import economic
    got = economic.calendar(today, today) or {}
    rows = [r for r in got.get("rows") or [] if (r.get("country") or "").upper() in ("US", "USA")]
    rows.sort(key=lambda r: r.get("time") or "")
    keys = ("time", "event", "impact", "actual", "estimate", "previous", "unit")
    return [_pick(r, keys) for r in rows[:MAX_ECONOMIC]]


def market_today(top: int = TOP) -> dict:
    """Today's market facts for the calling reader. See the module docstring."""
    from alphadesk.config import ET, now_et
    from alphadesk.providers.base import NeedsKey

    top = max(1, min(int(top), 25))
    now = now_et()
    today = now.date().isoformat()
    since = datetime.combine(now.date(), dtime.min, tzinfo=ET).isoformat()
    sections = {
        "tape": _tape,
        "movers": lambda: _movers(top),
        "sectors": _sectors,
        "news": lambda: _news(top, since),
        "earnings_today": lambda: _earnings(today),
        "economic_today": lambda: _economic(today),
    }
    out: dict = {"as_of": now.isoformat(timespec="seconds"), "date": today}
    unavailable: dict[str, str] = {}
    # In parallel, each in a COPY of this request's context — the reader's
    # identity rides a context variable, and a bare thread would run as nobody.
    with ThreadPoolExecutor(max_workers=len(sections)) as pool:
        futures = {name: pool.submit(contextvars.copy_context().run, fn) for name, fn in sections.items()}
        for name, fut in futures.items():
            try:
                out[name] = fut.result(timeout=60)
            except NeedsKey as exc:
                unavailable[name] = str(exc)
            except Exception as exc:  # noqa: BLE001 — one section never sinks the rest
                log.warning("market_today %s failed: %s", name, exc)
                unavailable[name] = "could not be loaded right now"
    out["unavailable"] = unavailable
    return out
