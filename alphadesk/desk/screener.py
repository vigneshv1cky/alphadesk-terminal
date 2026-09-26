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
import re
from datetime import date as date_type
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


# How far back a split still counts as recent enough to mark.
SPLIT_LOOKBACK_DAYS = 180
# EDGAR reserves a send slot every 0.15s process-wide, so a cold window of
# 200 symbols would be 30 seconds on the request thread. Ask for a handful,
# leave the rest to a background thread under the reader who asked.
_SEC_LOOKUPS_PER_REQUEST = 12
# And no more than this handed to the background per request, so one poll of
# a 900-symbol window cannot hold the shared fill pool for two minutes while
# the earnings week waits behind it. The window polls, so it drains.
_SEC_QUEUED_PER_REQUEST = 150
# Past this a cover figure is not a description of today. A company that
# dilutes heavily — which is most of the population this measure is for —
# can multiply its share count between two filings.
SHARES_MAX_AGE_DAYS = 120

# A US-listed equity, which is the only thing that HAS an SEC share count or
# a bar from an equity vendor. The window is built from news tickers, so it
# also carries coin pairs (DOGEUSD), Toronto listings (TSX:BB) and the slash
# spelling of a share class (BRK/A). ONE symbol a vendor calls invalid fails
# the WHOLE batch — "invalid symbol: TSX:BB" blanked all 911 — so they are
# dropped before the request rather than after the failure.
_EQUITY = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z]{1,2})?$")


def inventory(fill: tuple[str, ...] = ()) -> list[dict]:
    """Everything in the window, UNRANKED and alphabetical. Each entry:
    {symbol, report_date, session, article_count,
     headlines: [{title, url, source, published_at}]}

    Pure database read with no `fill` — fast and free however many symbols
    are in play, which is what lets the window poll.

    TWO MEASURES ON REQUEST (2026-09-26, #83), the same shape as the
    heatmap's (#285): a caller asks only for what it will show.

      "split"     days_since_split, and the ratio, from CORROBORATED splits
                  only — a split one vendor lists alone is the kind that
                  never happens.
      "turnover"  the session's volume divided by the company's OWN share
                  count from its SEC cover page, never the vendor's. On the
                  population where this measure is used at all — companies
                  fresh from a reverse split — the vendor number is wrong by
                  orders of magnitude: WHLR came back as 2,420 shares
                  against 89 million traded, and the SEC says 1,931,568.

    NEITHER IS A SCORE AND NOTHING IS SORTED BY THEM. They are columns; the
    reader sets a threshold and sorts, which is the reader choosing. The
    measurement that prompted them found no edge in the thing they describe
    — 77 corroborated reverse splits over 90 days had a median of -20.9% at
    twenty sessions and only one name carried the positive average — so they
    are offered as facts and explicitly not as a signal.
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
    if fill:
        _attach(out, tuple(fill))
    return out


def _recent_splits() -> dict[str, dict]:
    """Each symbol's most recent CORROBORATED split, by ticker."""
    from datetime import date
    from alphadesk.ingest import corporate_calendars
    today = date.today()
    cal = corporate_calendars.splits((today - timedelta(days=SPLIT_LOOKBACK_DAYS)).isoformat(),
                                     today.isoformat())
    best: dict[str, dict] = {}
    for r in cal.get("rows") or []:
        # `hidden` marks a split only one of two vendors lists. Those are the
        # ones that never took effect — FMP listed six — so they must never
        # move a share count or mark a row.
        if r.get("hidden"):
            continue
        sym = (r.get("symbol") or "").upper()
        if sym and (sym not in best or r["date"] > best[sym]["date"]):
            best[sym] = r
    return best


def _attach(rows: list[dict], fill: tuple[str, ...]) -> None:
    """Add the asked-for measures in place. Never raises: a measure that
    cannot be filled is ABSENT, and an absent figure reads as unknown. A
    zero or a guess would read as a fact."""
    from alphadesk.ingest import background_fill, secshares
    from alphadesk.providers import get_prices

    symbols = [r["symbol"] for r in rows if _EQUITY.match(r["symbol"])]
    splits = _recent_splits() if ("split" in fill or "turnover" in fill) else {}

    if "split" in fill:
        today = now_et().date()
        for r in rows:
            sp = splits.get(r["symbol"])
            if not sp:
                continue
            try:
                age = (today - date_type.fromisoformat(sp["date"])).days
            except (TypeError, ValueError):
                continue
            r["days_since_split"] = age
            r["split_date"] = sp["date"]
            r["split_ratio"] = f'{sp.get("from")}-for-{sp.get("to")}'
            r["split_reverse"] = bool(sp.get("reverse"))

    if "turnover" not in fill:
        return

    router = get_prices()
    try:
        bars = router.get("daily_history", symbols, 2) or {}
    except Exception as exc:                        # a missing key is not an error here
        log.debug("turnover: no bars (%s)", exc)
        bars = {}

    wanted = set(symbols)
    held = secshares.stored(symbols)
    missing = [s for s in symbols if s not in held]
    for sym in missing[:_SEC_LOOKUPS_PER_REQUEST]:
        got = secshares.read(sym)
        if got:
            held[sym] = got
    rest = missing[_SEC_LOOKUPS_PER_REQUEST:]
    owner = _owner()
    if rest and owner:
        todo = [s for s in rest if not background_fill.recently_failed("secshares", owner, s)]
        todo = todo[:_SEC_QUEUED_PER_REQUEST]
        if todo:
            background_fill.submit("secshares", owner, todo,
                                   lambda syms: [secshares.read(s) for s in syms])

    pending = set(rest)
    for r in rows:
        if r["symbol"] not in wanted:
            continue
        r["turnover_pending"] = r["symbol"] in pending
        rec = held.get(r["symbol"])
        shares = (rec or {}).get("shares")
        bar = (bars.get(r["symbol"]) or [])
        volume = bar[-1].get("volume") if bar else None
        if not shares or not volume:
            continue
        if shares <= 0:
            continue
        # The COUNT is a fact and is always shown, dated. The RATIO is not,
        # and is withheld whenever the count cannot describe today.
        as_of = (rec or {}).get("as_of")
        r["shares_outstanding"] = shares
        r["shares_as_of"] = as_of
        r["shares_filed_at"] = (rec or {}).get("filed_at")
        why = _stale_count(r["symbol"], (rec or {}).get("filed_at") or as_of, splits)
        if why:
            r["turnover_withheld"] = why
            continue
        r["turnover"] = volume / shares


def _stale_count(symbol: str, as_of: str | None, splits: dict[str, dict]) -> str | None:
    """Why this share count cannot be divided into today's volume, or None.

    `as_of` is the FILING date where there is one, because a cover date can
    be wrong and a wrong one is dated in the FUTURE, which would sail past
    any freshness test (see secshares.read).

    RESCALING BY THE SPLIT WAS TRIED AND REMOVED THE SAME HOUR (2026-09-26).
    It looks right — we hold a corroborated ratio, and the earnings estimates
    are rescaled exactly that way — and on this population it is wrong,
    because it assumes the only thing that changed was the split. CTNT's SEC
    cover said 36,177,712 shares in March and it did 200-for-1 in April, so
    the rescale produced 180,889 — against 515,748,469 shares traded in a
    day, a turnover of 2,851x. The company had diluted massively in between;
    that is WHY it trades at three cents. INLF was the same, from a count
    nine months old.
    A wrong figure here is worse than none, because this is the one measure
    a reader would act on — the same reason keystats.py withholds a P/E that
    divides a current price by a restated per-share figure.
    """
    if not as_of:
        return "the share count is undated"
    sp = splits.get(symbol)
    if sp and sp["date"] > as_of:
        return f"the share count predates the {sp['date']} split"
    try:
        age = (now_et().date() - date_type.fromisoformat(as_of)).days
    except (TypeError, ValueError):
        return "the share count is undated"
    if age < 0:
        return "the share count is dated in the future"
    if age > SHARES_MAX_AGE_DAYS:
        return f"the share count is {age} days old"
    return None


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

