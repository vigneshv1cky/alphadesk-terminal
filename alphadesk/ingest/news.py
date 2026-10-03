"""News ingestion — poll each reader's own feeds, merge, persist.

No model touches a story: nothing is labelled, scored or summarised. A feed
that fails is logged and remembered (feed_problem) so the Account page can say
why, and the window keeps what it already has.
"""

import functools
import inspect
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from alphadesk.config import NEWS_OLDER_PAGE_DAYS as OLDER_PAGE_DAYS
from alphadesk.config import SYMBOL_NEWS_LOOKBACK_DAYS as SYMBOL_LOOKBACK_DAYS
from alphadesk.ledger import store

log = logging.getLogger("alphadesk.news")

_BATCH = 30               # articles per enrichment call — fewer calls, less overhead
_seen_ids: set[str] = set()
_SEEN_CAP = 100_000       # bound memory in a 24/7 process; clearing only risks
                          # re-fetching an old article, absorbed by enrichment_cache

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


# WHAT EACH FEED LAST SAID (2026-10-03). A rejected key made the poll fail
# quietly every five minutes for half a day while the news window read "no
# news" — nothing on the page said why. The last failure per reader and feed is
# kept so the Account page can say it, and cleared by the next good answer.
_feed_errors: dict[tuple[str, str], str] = {}


_REFUSAL = re.compile(r"\b(401|403)\b|unauthori[sz]ed|not authori[sz]ed|authorization required|forbidden"
                      r"|unknown api key|invalid api key|invalid key|api key (is )?(missing|invalid)", re.I)


def _refused(text: str) -> bool:
    """Whether a vendor's error text is a REFUSAL of the credentials. The
    status code does not survive the providers' re-wrap of the vendor's
    exception, so the wording is read too (Alpaca answers "request is not
    authorized", Polygon "Unknown API Key", a gateway "401 Authorization
    Required"). Matched without regard to case, and a number only as a word."""
    return bool(_REFUSAL.search(text or ""))


def has_feed_problem(user_id: str) -> bool:
    """Whether any of this reader's feeds failed its last ask."""
    return any(owner == user_id for owner, _ in list(_feed_errors))


def feed_problem(user_id: str, provider_name: str) -> str | None:
    """Why this feed last failed, in words, or None when its last ask worked."""
    msg = _feed_errors.get((user_id, provider_name))
    if not msg:
        return None
    if _refused(msg):
        return "the vendor rejected this key — replace it with a current key and secret"
    return msg.strip().splitlines()[0][:160]


def check_news_key(provider_name: str, api_key: str, api_secret: str | None) -> str | None:
    """Try a freshly typed news key once and say if the vendor REFUSES it
    (401 or 403). Any other trouble — a timeout, an outage, a vendor with no
    cheap test — never blocks a save: only a refusal is certain."""
    from alphadesk.providers import ProviderError, registry
    if os.environ.get("ALPHADESK_SKIP_KEY_CHECK", "").strip() == "1":
        return None                                   # offline, or a test: save without trying
    try:
        provider = registry.build("news", provider_name, api_key=api_key, api_secret=api_secret or None)
        provider.fetch(datetime.now(timezone.utc) - timedelta(hours=6), limit=1)
    except ProviderError as exc:
        if _refused(str(exc)):
            return f"{provider_name} rejected that key and secret — check them and try again"
    except Exception as exc:                          # noqa: BLE001 — never block a save on our own trouble
        log.debug("news key check for %s: %s", provider_name, exc)
    return None


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
    name = getattr(provider, "name", "")
    try:
        articles = provider.fetch(since, limit=limit)
        _feed_errors.pop((owner, name), None)
    except ProviderError as exc:
        log.warning("news provider unavailable: %s", exc)
        _feed_errors[(owner, name)] = str(exc)
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

# How far back one page of older news may reach at the vendor (30 days when
# a longer keep-data setting is on; config.py): OLDER_PAGE_DAYS, imported above.


def _article_dicts(got, feed: str) -> list[dict]:
    """A feed's answer in the stored shape, WITHOUT the process-wide seen-id
    set the poll uses: that set exists so a poll does not re-scan its own
    window, and on a page, a backfill or a symbol's ask it hid stories that had
    since been pruned from the store, so the page stayed short until a
    restart (2026-10-03)."""
    return [{"id": a.id, "title": a.title, "summary": a.summary, "source": a.source,
             "url": a.url, "published_at": a.published_at, "tickers": a.symbols,
             "image_url": a.image_url, "author": a.author, "body": a.body,
             "feeds": [feed]} for a in got if a.id]


def older_articles(user_id: str, before: str, limit: int = 100, query: str = "") -> list[dict]:
    """A page of the reader's stories published before `before` (ISO), newest
    first; with `query`, only those whose headline, summary or tickers
    contain it. From what is stored first; when the store runs short of a
    page (and no query narrows it), the reader's feeds that can page backwards
    (Alpaca) are asked for the week before `before`, the answer stored as
    theirs, and the page read again."""
    owner = news_owner(user_id)
    rows = store.articles_before(owner, before, limit, query, body=False)
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
        batches.append(_article_dicts(got, row["provider"]))
    merged = _merge_feeds(batches)
    if merged:
        store.save_articles(merged, owner=owner)
        rows = store.articles_before(owner, before, limit, query, body=False)
    return rows


# A symbol's own ask at the vendor, remembered so a panel that refreshes every
# minute does not repeat it. Keyed by reader, symbol and page edge.
SYMBOL_ASK_TTL_S = 600.0
# A symbol's own ask looks SYMBOL_LOOKBACK_DAYS back (config.py, imported above).
_symbol_asked: dict[tuple, float] = {}
_symbol_asked_lock = threading.Lock()


def symbol_articles(user_id: str, symbol: str, before: str | None, limit: int) -> list[dict]:
    """One symbol's stories for its panel, newest first (2026-10-02). From
    what is stored first; when the store runs short of `limit`, the reader's
    feeds that can read one symbol (Alpaca) are asked for that symbol alone,
    the answer stored as theirs, and the page read again. The feed-wide poll
    only ever holds the newest slice of everything, so a quiet name such as
    SVRN could be empty here however far back the reader paged. An ask is
    made once per ten minutes per symbol and page edge; any failure leaves
    the stored page as it was."""
    owner = news_owner(user_id)
    rows = store.articles_for_symbol(owner, symbol, before, limit, body=False)
    if len(rows) >= limit:
        return rows
    key = (user_id, symbol, before or "")
    now = time.monotonic()
    with _symbol_asked_lock:
        if now - _symbol_asked.get(key, -1e9) < SYMBOL_ASK_TTL_S:
            return rows
        _symbol_asked[key] = now
        if len(_symbol_asked) > 2000:
            _symbol_asked.clear()
    try:
        until = datetime.fromisoformat(before.replace("Z", "+00:00")) if before else None
    except ValueError:
        return rows
    since = (until or datetime.now(timezone.utc)) - timedelta(days=SYMBOL_LOOKBACK_DAYS)
    keys = store.get_user_keys(user_id, "news")
    batches = []
    for row in keys:
        try:
            provider = _user_news_provider(user_id, row["created_at"], row["provider"], row["config"])
        except Exception:
            continue
        params = inspect.signature(provider.fetch).parameters
        if "symbols" not in params or "until" not in params:
            continue                                   # this feed cannot read one symbol
        try:
            got = provider.fetch(since, limit=limit, until=until, symbols=[symbol])
        except Exception as exc:
            log.info("%s news from %s: %s", symbol, row["provider"], exc)
            continue
        batches.append(_article_dicts(got, row["provider"]))
    merged = _merge_feeds(batches)
    if merged:
        store.save_articles(merged, owner=owner)
        rows = store.articles_for_symbol(owner, symbol, before, limit, body=False)
    return rows


# One ask returns at most this many stories; a day is walked in up to this many.
BACKFILL_PAGE = 400
BACKFILL_PAGES_PER_DAY = 8


def backfill_user(user_id: str, provider_name: str, days: float | None = None) -> int:
    """Refill the retention window for one feed after its key is saved
    (2026-10-02). The poll only ever asks for the newest stories, so a
    reader whose stored stories were lost, or who has just connected a feed,
    saw a thin window until they paged back by hand. This walks the window a
    day at a time (a single ask is capped well below a week of an all-symbol
    feed) and stores the answer as that feed's. A feed that cannot page
    backwards is skipped. Any failure is logged and ends the backfill; the
    poll carries on regardless. Returns the stories stored."""
    from alphadesk.config import NEWS_BACKFILL_DAYS
    days = NEWS_BACKFILL_DAYS if days is None else days
    row = next((r for r in store.get_user_keys(user_id, "news") if r["provider"] == provider_name), None)
    if row is None:
        return 0
    try:
        provider = _user_news_provider(user_id, row["created_at"], row["provider"], row["config"])
    except Exception as exc:
        log.info("backfill %s for %s: %s", provider_name, user_id[:8], exc)
        return 0
    if "until" not in inspect.signature(provider.fetch).parameters:
        return 0
    now = datetime.now(timezone.utc)
    stored = 0
    for day in range(max(1, math.ceil(days))):
        day_until = now - timedelta(days=day)
        since = max(day_until - timedelta(days=1), now - timedelta(days=days))
        cursor = day_until
        # A day of an all-symbol feed is far more than one ask returns (the
        # newest BACKFILL_PAGE stories), so walk the day backwards: each ask
        # ends where the last one's oldest story began, until the day is
        # covered, the feed has no more, or a page makes no progress.
        for _page in range(BACKFILL_PAGES_PER_DAY):
            try:
                got = provider.fetch(since, limit=BACKFILL_PAGE, until=cursor)
            except Exception as exc:
                log.info("backfill %s for %s: %s", provider_name, user_id[:8], exc)
                return stored
            batch = _merge_feeds([_article_dicts(got, provider_name)])
            if batch:
                store.save_articles(batch, owner=news_owner(user_id))
                stored += len(batch)
            if len(got) < BACKFILL_PAGE:
                break
            try:
                oldest = min(datetime.fromisoformat(a.published_at.replace("Z", "+00:00")) for a in got if a.published_at)
            except ValueError:
                break
            if oldest >= cursor or oldest <= since:
                break
            cursor = oldest
    return stored


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
