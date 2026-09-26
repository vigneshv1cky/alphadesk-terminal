"""The screener — an INVENTORY of what's in play, plus an AI you ask.

Two deliberate properties, and the second is why the first exists:

  1. **Nothing is ranked.** `inventory()` returns every symbol with fresh news
     or a report inside `SCREENER_HORIZON_DAYS`, in alphabetical order. There
     is no score, no top-N, no "these 15 matter most". An earlier build ranked
     by earnings proximity + news volume and auto-narrated the top of that
     list; ordering a list IS a judgment, and this terminal's whole premise is
     that the judgment is the operator's.
  2. **The AI speaks only when asked.** `ask()` runs ONE chat_json() call over
     the WHOLE window — every article and every upcoming report at once — and
     answers the question actually posed. Nothing is generated in the
     background, so a page load costs zero tokens and the model never
     pre-decides what was interesting.

No claim renders without a source, same discipline as the rest of the repo
(the attribution rule). Everything the model is shown is a NUMBERED
item drawn from our own tables — an article or a calendar row — and it cites
by that index. `_resolve_citations` maps the index back to the stored record;
the model's own idea of a URL or a date is never trusted, only its index into
a list we control.
"""

import hashlib
import logging
from datetime import timedelta, timezone

from alphadesk.config import (
    NEWS_LOOKBACK_HOURS,
    SCREENER_HORIZON_DAYS,
    now_et,
)
from alphadesk.ledger import store

log = logging.getLogger("alphadesk.screener")

# symbol_digests is (symbol, input_hash) -> answer + citations, which is
# exactly this cache's shape. A market-wide ask has no one symbol, so it is
# stored under a sentinel that can never collide with a real ticker (store
# uppercases symbols; no ticker contains '*').
_ASK_CACHE_SYMBOL = "*SCREENER-ASK*"

_ASK_SYSTEM = (
    "You are a financial research assistant reading a trader's whole watch "
    "window at once: recent news articles and upcoming earnings dates across "
    "many symbols. Answer the question actually asked, using ONLY the "
    "numbered items provided — never guess or use outside knowledge.\n"
    "Be concrete (symbols, numbers, dates). If the items can't answer the "
    "question, say so plainly rather than padding. Do not rank or recommend "
    "trades unless the question explicitly asks you to.\n"
    "Every factual claim MUST cite the item number it came from.\n"
    "Return ONLY JSON: {\"answer\": \"...\", "
    "\"citations\": [{\"item\": <1-based int>, \"claim\": \"short phrase\"}]}"
)


def _since_iso() -> str:
    return (now_et().astimezone(timezone.utc)
            - timedelta(hours=NEWS_LOOKBACK_HOURS)).isoformat()


def _owner() -> str:
    """Whose window this call builds: a reader with their own news key sees
    the articles their key fetched; everyone else shares the operator's feed.
    Rides the same request context the per-user LLM path uses, so the agent's
    tools and the API endpoints inherit it without threading a parameter."""
    from alphadesk.identity import request_user
    from alphadesk.ingest.news import news_owner
    return news_owner(request_user())


def inventory() -> list[dict]:
    """Everything in the window, UNRANKED and alphabetical. Each entry:
    {symbol, report_date, session, article_count,
     headlines: [{title, url, source, published_at}]}

    Pure database read — no LLM call, so this is fast and free however many
    symbols are in play.
    """
    from alphadesk.ingest import earnings_calendar
    upcoming = earnings_calendar.upcoming(days=SCREENER_HORIZON_DAYS)
    by_symbol = {r["symbol"].upper(): r for r in upcoming}
    news_by_symbol = store.recent_articles_by_ticker(_since_iso(), owner=_owner())

    out = []
    # Alphabetical, not by any measure of interest: the order of this list is
    # not a recommendation. Stable across polls, too — a re-sort under the
    # cursor every 60s would itself read as "this one moved up".
    for sym in sorted(set(by_symbol) | set(news_by_symbol)):
        earn = by_symbol.get(sym) or {}
        arts = news_by_symbol.get(sym, [])
        out.append({
            "symbol": sym,
            "report_date": earn.get("report_date"),
            "session": earn.get("session"),
            "article_count": len(arts),
            "headlines": [{"title": a["title"], "url": a.get("url", ""),
                           "source": a.get("source", ""),
                           "published_at": a.get("published_at")}
                          for a in arts[:5]],
        })
    return out


def _input_hash(question: str, items: list[dict]) -> str:
    ids = [it["article_id"] if it["kind"] == "article"
           else f"E:{it['symbol']}:{it.get('report_date')}" for it in items]
    payload = question.strip().lower() + "|" + ",".join(sorted(ids))
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def _resolve_citations(citations: list[dict], items: list[dict]) -> list[dict]:
    """Turn {item, claim} into the real record behind it. An index outside
    the list we handed the model is dropped, not shown."""
    out = []
    for c in citations:
        n = c.get("item")
        claim = c.get("claim") or ""
        if not isinstance(n, int):
            continue
        i = n - 1
        if i < 0 or i >= len(items):
            continue
        it = items[i]
        if it["kind"] == "earnings":
            out.append({"kind": "earnings", "claim": claim, "symbol": it["symbol"],
                        "title": f"{it['symbol']} reports {it.get('report_date') or '?'}",
                        "url": "", "source": "earnings calendar"})
        else:
            out.append({"kind": "article", "claim": claim, "symbol": it["symbol"],
                        "title": it["title"], "url": it.get("url", ""),
                        "source": it.get("source", "")})
    return out

