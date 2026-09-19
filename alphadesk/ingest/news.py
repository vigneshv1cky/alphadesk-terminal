"""News ingestion — poll the configured provider, enrich, persist.

Recovered and adapted from the v1 multi-agent system (removed 11263ae,
2026-08-07): same Polygon fetch and the same enrichment_cache-backed
amortization, with the LLM call swapped from the old committee's call_role()
(claude_sdk/kimi/deepseek, multi-role) to this repo's single-purpose
ai/llm.py client. The enrichment prompt (category/sentiment/relations) is
unchanged — it was already tuned and working.
"""

import functools
import inspect
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from alphadesk.ledger import store

log = logging.getLogger("alphadesk.news")

_BATCH = 30               # articles per enrichment call — fewer calls, less overhead
_seen_ids: set[str] = set()
_SEEN_CAP = 100_000       # bound memory in a 24/7 process; clearing only risks
                          # re-fetching an old article, absorbed by enrichment_cache

_ENRICH_SYSTEM = (
    "You are a financial news enrichment engine. For each numbered article you "
    "receive, produce a substance category, sentiment, and any explicit "
    "inter-company relations stated in the text.\n"
    "category — what KIND of information this is:\n"
    "  BUSINESS_EVENT: something happened at the company — earnings/guidance, "
    "M&A, contracts, products, leadership, legal/regulatory action against it\n"
    "  SUPPLY_DEMAND: supply-chain, production, capacity, shortages, pricing "
    "power, demand signals, orders, inventory\n"
    "  MACRO_POLICY: rates, regulation, tariffs, geopolitics affecting sectors\n"
    "  PRICE_COMMENTARY: the article mainly narrates stock-price action "
    "('X soared/plunged/hit a high', 'why X stock moved', weekly recaps)\n"
    "  OPINION: listicles, 'top N stocks to buy', 'should you buy X', "
    "evergreen takes with no new information\n"
    "sentiment: -1.0 (very negative) to 1.0 (very positive) — the OVERALL tone. "
    "label: negative|neutral|positive.\n"
    "ticker_sentiment: when the article names MULTIPLE companies and the news is "
    "NOT symmetric across them, give the per-company sentiment (e.g. 'X sues Y' is "
    "negative for Y but neutral/positive for X). List ONLY tickers whose sentiment "
    "differs from the overall — any ticker you omit inherits the article sentiment. "
    "Skip this entirely for single-company or uniformly-toned articles.\n"
    "relations: ONLY relations explicitly stated or strongly implied by the "
    "article text itself (e.g. 'X supplies chips to Y', 'X competes with Y').\n"
    "Return ONLY JSON: {\"items\": [{\"i\": <1-based index>, \"category\": ..., "
    "\"sentiment\": ..., \"label\": ..., "
    "\"ticker_sentiment\": [{\"t\": \"TICK\", \"sentiment\": ..., \"label\": ...}], "
    "\"relations\": [{\"a\": \"TICK\", \"rel\": \"...\", \"b\": \"TICK\"}]}]}"
)


@functools.lru_cache(maxsize=32)
def _user_news_provider(user_id: str, created_at: str, provider_name: str, sealed: str):
    """One reader's feed instance from their sealed vault config — the same
    LRU-on-created_at pattern as the per-user LLM path: replacing the key
    builds a fresh instance, the old one ages out."""
    from alphadesk.ledger import vault
    from alphadesk.providers import registry
    cfg = vault.decrypt(sealed)
    return registry.build(
        "news", provider_name,
        api_key=cfg.get("api_key") or None,
        api_secret=cfg.get("api_secret") or None,
    )


# One fetched batch per (reader, feed), remembered briefly. The normal
# cadence (NEWS_REFRESH_MINUTES, 20 min) always misses this memo — it exists
# so a hot loop, an extra scheduler or a misconfigured refresh cannot ride a
# reader's key once per minute. Within the window the provider is NOT
# called; the previous batch replays instead, which is idempotent (persist
# dedups, enrichment is cached) and defers genuinely new articles by at most
# the TTL. Read at call time so tests can shrink it.
NEWS_USER_FETCH_TTL_S = float(os.environ.get("NEWS_USER_FETCH_TTL_S", "300"))
_USER_FETCH_MEMO_MAX = 256
_user_fetch_memo: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_user_fetch_lock = threading.Lock()


def _memoized_user_fetch(user_id: str, provider_name: str, provider,
                         since: datetime, limit: int) -> tuple[list[dict], bool]:
    """fetch_articles for one reader's feed, behind the TTL memo.
    Returns (articles, fetched_live) — the caller stamps last_used only for
    a call that actually reached the provider."""
    key = (user_id, provider_name)
    now = time.monotonic()
    with _user_fetch_lock:
        hit = _user_fetch_memo.get(key)
        if hit and now - hit[0] < NEWS_USER_FETCH_TTL_S:
            return hit[1], False
    batch = fetch_articles(since, limit, provider=provider, owner=user_id)
    with _user_fetch_lock:
        if len(_user_fetch_memo) >= _USER_FETCH_MEMO_MAX:
            live = {k: v for k, v in _user_fetch_memo.items()
                    if now - v[0] < NEWS_USER_FETCH_TTL_S}
            _user_fetch_memo.clear()
            _user_fetch_memo.update(live if len(live) < _USER_FETCH_MEMO_MAX else {})
        _user_fetch_memo[key] = (now, batch)
    return batch, True


def news_owner(user_id: str | None) -> str:
    """Whose window a reader sees: their own, always (2026-09-13 — the
    server's shared feed is gone). An anonymous caller owns nothing and
    sees an empty window. The single place that decision is made."""
    return user_id or "\x00anonymous"


def _merge_feeds(batches: list[list[dict]]) -> list[dict]:
    """Concatenate several feeds' articles, dropping the SAME STORY told
    twice: provider ids never collide, but two feeds carrying one press
    release do — the URL (query stripped) is the cheap cross-feed identity.
    Only a READER'S OWN keyed feeds ever merge (the shared feed is a single
    provider by stance); first feed wins, so provider order is a
    preference, not just a set."""
    kept: dict[str, dict] = {}
    merged: list[dict] = []
    for batch in batches:
        for a in batch:
            u = store.article_url_key(a.get("url"))
            if u and u in kept:
                # The same story from a second feed: one article, both feeds.
                first = kept[u]
                first["feeds"] = sorted(set(first.get("feeds") or []) | set(a.get("feeds") or []))
                continue
            a = {**a, "feeds": sorted(set(a.get("feeds") or []))}
            if u:
                kept[u] = a
            merged.append(a)
    return merged


def fetch_articles(since: datetime, limit: int = 200, provider=None,
                   owner: str = "") -> list[dict]:
    """Ticker-tagged articles since `since`, NEWEST first, from `provider`
    — one of the reader's own feeds; no provider, no articles.

    Returns the dict shape the rest of the pipeline stores. A provider failure
    is logged and yields an empty list: a dead feed must leave the terminal
    showing the articles it already has, never an error page.
    """
    from alphadesk.providers import ProviderError
    if provider is None:
        return []                                  # no server feed: a user's own key fetches
    try:
        articles = provider.fetch(since, limit=limit)
    except ProviderError as exc:
        log.warning("news provider unavailable: %s", exc)
        return []
    except Exception as exc:                      # a broken plugin is not fatal
        log.error("news provider raised unexpectedly: %s", exc)
        return []

    out: list[dict] = []
    for a in articles:
        # Dedupe across polls, PER OWNER — the same story may legitimately
        # land once in the shared feed and once in a reader's own. The window
        # overlaps by design, so without this every cycle would re-scan the
        # same articles (enrichment_cache absorbs the LLM cost either way).
        seen_key = f"{owner}:{a.id}"
        if not a.id or seen_key in _seen_ids:
            continue
        if len(_seen_ids) >= _SEEN_CAP:
            _seen_ids.clear()
        _seen_ids.add(seen_key)
        out.append({
            "id": a.id, "title": a.title, "summary": a.summary,
            "source": a.source, "url": a.url,
            "published_at": a.published_at, "tickers": a.symbols,
            "image_url": a.image_url, "author": a.author, "body": a.body,
        })
    return out


def poll_user(user_id: str, since: datetime, limit: int | None = None) -> int:
    """One reader's feed cycle: their vaulted news key fetches and their rows
    are owned by them. Nothing is labelled or summarised — no model runs here
    or anywhere else (2026-09-17). Capped harder than the shared feed
    (NEWS_USER_LIMIT): this runs unattended for every active keyed reader.

    Any failure is that reader's alone — logged, zero returned, the loop
    moves on to the next reader."""
    from alphadesk.config import NEWS_USER_LIMIT
    rows = store.get_user_keys(user_id, "news")
    if not rows:
        return 0
    batches: list[list[dict]] = []
    served: list[str] = []
    for row in rows:
        try:
            provider = _user_news_provider(user_id, row["created_at"], row["provider"], row["config"])
        except Exception as exc:
            log.warning("user %s %s news key cannot build its provider: %s",
                        user_id[:8], row["provider"], exc)
            continue
        batch, live = _memoized_user_fetch(user_id, row["provider"], provider,
                                           since, limit or NEWS_USER_LIMIT)
        batch = [{**a, "feeds": [row["provider"]]} for a in batch]
        if batch and live:
            served.append(row["provider"])
        batches.append(batch)
    articles = _merge_feeds(batches)
    if not articles:
        return 0
    store.save_articles(articles, owner=user_id)
    try:
        from alphadesk.ingest import earnings_announcements
        earnings_announcements.record_from_articles(user_id, articles)
    except Exception as exc:                          # the window never waits on the calendar
        log.debug("announcement parse failed for %s: %s", user_id[:8], exc)
    for name in served:
        store.touch_user_key_provider(user_id, "news", name)
    return len(articles)


# ── real-time delivery (2026-09-15) ───────────────────────────────────────

# How many streamed stories each reader has received this process. The tab's
# live connection watches its reader's count and tells the page to reread the
# list when it moves; the page never parses a story off the socket.
_stream_seq: dict[str, int] = {}
_stream_seq_lock = threading.Lock()


STREAM_TEXT_RETRY_S = 120.0


def _refill_text(user_id: str, article_id: str) -> None:
    try:
        story = full_story(user_id, article_id)
    except Exception as exc:
        log.debug("text refill for %s: %s", article_id, exc)
        return
    if story and story.get("body"):
        with _stream_seq_lock:
            _stream_seq[user_id] = _stream_seq.get(user_id, 0) + 1


def stream_seq(owner: str) -> int:
    with _stream_seq_lock:
        return _stream_seq.get(owner, 0)


def ingest_streamed(user_id: str, article) -> bool:
    """One story from the reader's real-time feed (an Article): stored as
    theirs, parsed for earnings announcements, and counted so their open tabs
    reread the list.

    The connection is held for every active reader now, tab or no tab
    (ingest/stream.py), so this is the ordinary path for an Alpaca key rather
    than the lucky one. The poll (NEWS_REFRESH_MINUTES, five) stays the
    backstop for what the socket missed while it was down, and for the feeds
    with no stream at all; a story both deliver is one row (save_articles
    dedupes by id and URL). False when the story carried nothing to store."""
    rows = fetch_articles_from([article], owner=user_id)
    if not rows:
        return False
    rows = [{**r, "feeds": ["alpaca"]} for r in rows]
    store.save_articles(rows, owner=user_id)
    if not rows[0].get("body"):
        # A story can stream before Benzinga attaches its text (one did at
        # 18:56 UTC on 2026-09-15, and the feed had no text for it minutes
        # later either): asked for again once, a little later.
        timer = threading.Timer(STREAM_TEXT_RETRY_S, _refill_text, args=(user_id, rows[0]["id"]))
        timer.daemon = True
        timer.start()
    with _stream_seq_lock:
        _stream_seq[user_id] = _stream_seq.get(user_id, 0) + 1
    try:
        from alphadesk.ingest import earnings_announcements
        earnings_announcements.record_from_articles(user_id, rows)
    except Exception as exc:                          # the window never waits on the calendar
        log.debug("announcement parse failed for %s: %s", user_id[:8], exc)
    return True


def fetch_articles_from(articles, owner: str) -> list[dict]:
    """Articles already in hand (a stream's) in the stored dict shape, with
    the same per-owner dedupe the poll uses."""
    out: list[dict] = []
    for a in articles:
        seen_key = f"{owner}:{a.id}"
        if not a.id or seen_key in _seen_ids:
            continue
        if len(_seen_ids) >= _SEEN_CAP:
            _seen_ids.clear()
        _seen_ids.add(seen_key)
        out.append({
            "id": a.id, "title": a.title, "summary": a.summary,
            "source": a.source, "url": a.url,
            "published_at": a.published_at, "tickers": a.symbols,
            "image_url": a.image_url, "author": a.author, "body": a.body,
        })
    return out


# ── older stories (2026-09-15) ─────────────────────────────────────────────

# How far back one page of older news may reach at the vendor.
OLDER_PAGE_DAYS = 7


def older_articles(user_id: str, before: str, limit: int = 100, query: str = "") -> list[dict]:
    """A page of the reader's stories published before `before` (ISO), newest
    first; with `query`, only those whose headline, summary or tickers
    contain it. From what is stored first; when the store runs short of a
    page (and no query narrows it), the reader's feeds that can page backwards
    (Alpaca) are asked for the week before `before`, the answer stored as
    theirs, and the page read again."""
    owner = news_owner(user_id)
    rows = store.articles_before(owner, before, limit, query)
    if len(rows) >= limit or query:
        return rows
    try:
        until = datetime.fromisoformat(before.replace("Z", "+00:00"))
    except ValueError:
        return rows
    since = until - timedelta(days=OLDER_PAGE_DAYS)
    batches = []
    for row in store.get_user_keys(user_id, "news"):
        try:
            provider = _user_news_provider(user_id, row["created_at"], row["provider"], row["config"])
        except Exception:
            continue
        if "until" not in inspect.signature(provider.fetch).parameters:
            continue                                   # this feed cannot page backwards
        try:
            got = provider.fetch(since, limit=limit, until=until)
        except Exception as exc:
            log.info("older news from %s: %s", row["provider"], exc)
            continue
        batches.append([{**d, "feeds": [row["provider"]]} for d in fetch_articles_from(got, owner="older:" + user_id)])
    merged = _merge_feeds(batches)
    if merged:
        store.save_articles(merged, owner=owner)
        rows = store.articles_before(owner, before, limit, query)
    return rows


def full_story(user_id: str, article_id: str) -> Optional[dict]:
    """The reader's stored story with its text. A story stored without it
    (before the feed was asked for text, 2026-09-15) is fetched again from
    the reader's Alpaca news key once, and the text stored; other feeds do
    not deliver text, so their stories come back as stored. None when the
    reader has no such story."""
    owner = news_owner(user_id)
    story = store.article(owner, article_id)
    if story is None or story.get("body") or "alpaca" not in (story.get("feeds") or []):
        return story
    row = next((r for r in store.get_user_keys(user_id, "news") if r["provider"] == "alpaca"), None)
    if row is None or not story.get("tickers") or not story.get("published_at"):
        return story
    try:
        provider = _user_news_provider(user_id, row["created_at"], row["provider"], row["config"])
        from alphadesk.providers.news import alpaca_story_body
        again = alpaca_story_body(provider.key, provider.secret, article_id, story["tickers"][0], story["published_at"])
    except Exception as exc:
        log.info("full story %s: %s", article_id, exc)
        return story
    if again is None or not again.body:
        return story
    store.save_articles([{"id": article_id, "title": story["title"], "url": story["url"],
                          "published_at": story["published_at"], "tickers": story["tickers"],
                          "body": again.body, "feeds": ["alpaca"]}], owner=owner)
    return {**story, "body": again.body}
