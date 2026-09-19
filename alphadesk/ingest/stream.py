"""Real-time trades, pushed rather than polled.

ONE upstream connection, fanned out. Alpaca's free tier allows a single
concurrent market-data websocket per account, so this holds it for the whole
process and every reader shares it — a per-request connection would work for
exactly one reader and then start failing for the rest.

Subscriptions are REFERENCE COUNTED against the symbols people are actually
looking at. A terminal showing NVDA subscribes to NVDA; close the tab and the
last reader releases it and the upstream subscription goes with it. Nothing
here sweeps a universe or holds symbols nobody has open, which is the same
lazy-and-per-symbol rule the rest of ingest/prices.py follows.

WHICH FEED (2026-09-13). A key on a paid Alpaca plan streams the SIP feed —
every US exchange, real time; the provider's plan probe decides. A free key
streams IEX, and the caveat below is about that feed.

WHAT THIS DOES NOT PROMISE. On IEX, which carries a few percent of
consolidated volume: measured over 26 seconds mid-session, NVDA pushed 23
trades, AAPL 11, and ENTA pushed nothing at all. A silent symbol here means
"this feed saw no print", NOT "the stock did not trade" and certainly not
"the market is closed" — the same distinction _coverage_stats draws for the
chart. Anything rendering these ticks has to say when it last heard one
rather than let an old price sit there looking current.
"""

import asyncio
import logging
import random
import threading
import time
from typing import Any, Optional

log = logging.getLogger("alphadesk.stream")

# After a failed start, how long before the next subscriber may try again.
FAILED_RETRY_S = 60.0

# A tick older than this is stale rather than live. Not a reconnect trigger —
# a quiet symbol on IEX is normal — just how long a price may be presented as
# current before the UI should say when it actually arrived.
TICK_STALE_AFTER_S = 30.0

# RECONNECT BACKOFF (2026-09-06). alpaca-py's run loop retries a failed
# connection with no delay at all: `_run_forever` catches the auth error,
# sleeps zero, and calls `_start_ws` again — observed as dozens of
# "connection limit exceeded" tracebacks per second, then HTTP 429, whenever
# another process (an orphaned dev server, a restart racing its predecessor)
# held the account's single slot. The schedule below is what the SDK lacks:
# doubling from 2s, capped at 60s, with ±25% jitter so two restarts do not
# retry in lockstep. It resets the moment an attempt succeeds.
BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 60.0


def backoff_delay(failures: int, jitter: bool = True) -> float:
    """Seconds to wait before the next attempt after `failures` consecutive
    failures. Zero before the first failure; 2, 4, 8, … capped at 60."""
    if failures <= 0:
        return 0.0
    delay = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** (failures - 1)))
    if jitter:
        delay *= 0.75 + random.random() * 0.5
    return delay


class _QuietRetries(logging.Filter):
    """Drops the SDK's per-attempt tracebacks while a reconnect is backing
    off. One warning when the connection is first lost and one line when it
    is back say everything a log needs; the SDK's `log.exception` on every
    attempt said it hundreds of times."""

    def __init__(self) -> None:
        super().__init__()
        self.suppressing = False

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.suppressing:
            return True
        msg = record.getMessage()
        return not ("error during websocket communication" in msg
                    or "restarting connection" in msg
                    or "starting" in msg and "websocket connection" in msg
                    or "connecting to wss://" in msg)


_stream_cls: dict[str, Any] = {}


def _stream_class(kind: str = "stock") -> Any:
    """The SDK stream with a backoff on reconnect. Built lazily because the
    SDK import is lazy: an instance nobody streams from never imports it."""
    if kind in _stream_cls:
        return _stream_cls[kind]
    from alpaca.data.live import CryptoDataStream, StockDataStream
    if kind == "news":
        from alpaca.data.live.news import NewsDataStream
        base = NewsDataStream
    else:
        base = CryptoDataStream if kind == "crypto" else StockDataStream

    class _BackoffStream(base):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.failures = 0
            self._quiet = _QuietRetries()
            logging.getLogger("alpaca.data.live.websocket").addFilter(self._quiet)

        async def _start_ws(self) -> None:
            # Every reconnect the SDK's loop makes passes through here, so
            # this is the one place a delay throttles all of them: the auth
            # rejection path and the websocket-error path alike.
            delay = backoff_delay(self.failures)
            if delay:
                log.debug("market stream retry %d in %.1fs", self.failures + 1, delay)
                await asyncio.sleep(delay)
            try:
                await super()._start_ws()
            except Exception as exc:
                self.failures += 1
                if self.failures == 1:
                    log.warning("market stream connection failed, backing off: %s", exc)
                    self._quiet.suppressing = True
                raise
            if self.failures:
                log.info("market stream reconnected after %d failed attempts", self.failures)
            self.failures = 0
            self._quiet.suppressing = False

    _stream_cls[kind] = _BackoffStream
    return _BackoffStream


class _MarketStream:
    """One Alpaca account's upstream connection (2026-09-13: the USER's key,
    never the server's).

    Built lazily on the first subscriber, so an account nobody is watching
    never opens a socket. Alpaca allows one market-data connection per
    account, so readers sharing a key share this one connection.
    """

    def __init__(self, key: str | None = None, secret: str | None = None, kind: str = "stock",
                 feed: str = "iex") -> None:
        self._key, self._secret, self._kind = key, secret, kind
        self.feed = feed if kind == "stock" else kind
        # A news connection: the readers each streamed story is stored for,
        # counted like symbols so two tabs of one reader share it.
        self._owners: dict[str, int] = {}
        self._lock = threading.Lock()
        self._stream: Any = None
        self._thread: Optional[threading.Thread] = None
        self._refs: dict[str, int] = {}
        self._last: dict[str, dict] = {}
        # When the last start attempt failed. Not a permanent verdict: a
        # transient constructor failure held the process off streaming for
        # its whole life. After FAILED_RETRY_S the next subscriber tries again.
        self._failed_at: float | None = None

    # ── upstream ────────────────────────────────────────────────────────────

    def _ensure_running(self) -> bool:
        """Start the connection if it is not up. Returns False when streaming
        is unavailable (no keys, SDK missing, a previous hard failure), which
        callers treat as "no live data" and fall back to polling rather than
        as an error worth surfacing."""
        if self._failed_at is not None and time.time() - self._failed_at < FAILED_RETRY_S:
            return False
        if self._stream is not None:
            return True
        try:
            cls = _stream_class(self._kind)
        except Exception as exc:                      # pragma: no cover
            log.info("streaming unavailable (no SDK): %s", exc)
            self._failed_at = time.time()
            return False
        key, secret = self._key, self._secret
        if not key or not secret:
            self._failed_at = time.time()
            return False
        try:
            if self._kind == "stock":
                from alpaca.data.enums import DataFeed
                self._stream = cls(key, secret, feed=DataFeed.SIP if self.feed == "sip" else DataFeed.IEX)
            else:
                self._stream = cls(key, secret)
            # Everything still held is re-subscribed on the replacement
            # stream — the readers did not go away with the socket.
            for sym in list(self._refs):
                try:
                    self._subscribe(sym)
                except Exception as exc:                  # pragma: no cover
                    log.debug("re-subscribe failed for %s: %s", sym, exc)
            self._thread = threading.Thread(
                target=self._run, name="alphadesk-stream", daemon=True)
            self._thread.start()
            self._failed_at = None
            return True
        except Exception as exc:
            log.warning("could not start market stream: %s", exc)
            self._failed_at = time.time()
            self._stream = None
            return False

    def _run(self) -> None:
        try:
            self._stream.run()
        except Exception as exc:
            # Includes a normal stop(). Losing the socket must not take the
            # process with it: the REST path still answers every panel, so a
            # dead stream degrades to the polling behaviour rather than an
            # outage.
            log.info("market stream ended: %s", exc)
        finally:
            # The reference table SURVIVES the socket: it says who is
            # watching what, and that does not change because upstream
            # dropped. Clearing it let a reader's later release pop another
            # reader's symbol off the replacement stream. The next
            # subscriber (or the next tick request) brings the stream back
            # and re-subscribes everything still held.
            with self._lock:
                self._stream = None
                self._thread = None

    def _subscribe(self, sym: str) -> None:
        if self._kind == "news":
            self._stream.subscribe_news(self._on_news, sym)
            return
        self._stream.subscribe_trades(self._on_trade, sym)
        if self._kind == "crypto":
            # Crypto prints are sparse on this feed; the quote midpoint is
            # what moves between them.
            self._stream.subscribe_quotes(self._on_quote, sym)

    def _unsubscribe(self, stream: Any, sym: str) -> None:
        if self._kind == "news":
            stream.unsubscribe_news(sym)
            return
        stream.unsubscribe_trades(sym)
        if self._kind == "crypto":
            stream.unsubscribe_quotes(sym)

    async def _on_quote(self, q: Any) -> None:
        try:
            bid, ask = float(q.bid_price), float(q.ask_price)
            if bid > 0 and ask > 0:
                self._last[str(q.symbol).upper()] = {
                    "symbol": str(q.symbol).upper(), "price": round((bid + ask) / 2, 8), "size": 0,
                    "at": str(getattr(q, "timestamp", "")), "received": time.time(), "mid": True}
        except Exception:
            pass

    async def _on_news(self, n: Any) -> None:
        """A story from the real-time feed: stored for every reader watching
        on this account, off the socket's loop (a database write and a model
        call must not stall the next message)."""
        from alphadesk.providers.news import alpaca_article
        try:
            article = alpaca_article(n)
        except Exception:
            return
        with self._lock:
            owners = [o for o, n_refs in self._owners.items() if n_refs > 0]
        if article is None or not owners:
            return
        self._last["*"] = {"symbol": "*", "at": str(getattr(n, "created_at", "")), "received": time.time()}
        threading.Thread(target=_deliver_news, args=(owners, article), name="alphadesk-news-deliver", daemon=True).start()

    def add_owner(self, owner: str) -> None:
        with self._lock:
            self._owners[owner] = self._owners.get(owner, 0) + 1

    def drop_owner(self, owner: str) -> None:
        with self._lock:
            n = self._owners.get(owner, 0)
            if n <= 1:
                self._owners.pop(owner, None)
            else:
                self._owners[owner] = n - 1

    async def _on_trade(self, t: Any) -> None:
        try:
            self._last[str(t.symbol).upper()] = {
                "symbol": str(t.symbol).upper(),
                "price": float(t.price),
                "size": int(getattr(t, "size", 0) or 0),
                "at": str(getattr(t, "timestamp", "")),
                "received": time.time(),
            }
        except Exception:                             # a malformed tick is not fatal
            pass

    # ── subscription ────────────────────────────────────────────────────────

    def acquire(self, symbol: str) -> bool:
        """Take a reference on `symbol`, subscribing upstream if it is the
        first. Safe to call repeatedly."""
        sym = symbol.upper()
        with self._lock:
            if not self._ensure_running():
                return False
            n = self._refs.get(sym, 0)
            self._refs[sym] = n + 1
            if n:
                return True
        try:
            self._subscribe(sym)
            return True
        except Exception as exc:
            log.warning("subscribe failed for %s: %s", sym, exc)
            with self._lock:
                self._refs[sym] = max(0, self._refs.get(sym, 1) - 1)
            return False

    def ensure_live(self) -> bool:
        """Bring the socket back up if it dropped, re-subscribing everything
        still held. Takes NO reference — it is for a caller that already holds
        one and only wants the connection kept alive (the news keeper below).
        Without it a holder would have to acquire again to trigger a restart,
        and each acquire is another reference that is never released."""
        with self._lock:
            return self._ensure_running()

    def release(self, symbol: str) -> None:
        """Drop a reference; unsubscribe upstream when the last reader goes."""
        sym = symbol.upper()
        with self._lock:
            n = self._refs.get(sym, 0)
            if n <= 1:
                self._refs.pop(sym, None)
            else:
                self._refs[sym] = n - 1
                return
            stream = self._stream
        if stream is None:
            return
        try:
            self._unsubscribe(stream, sym)
        except Exception as exc:
            log.debug("unsubscribe failed for %s: %s", sym, exc)
        self._last.pop(sym, None)

    def shutdown(self) -> None:
        """Close the upstream socket for process exit.

        The run thread is a daemon, so exit never BLOCKS on this stream — the
        call exists to send a proper websocket close instead of letting the
        OS drop the TCP connection. That matters here specifically: the
        account gets ONE concurrent market-data connection, and a dropped
        socket holds the slot until the server times it out, which is what
        left every restart's new process retrying "connection limit exceeded"
        against its own predecessor's ghost.
        """
        with self._lock:
            s, t = self._stream, self._thread
        if s is None:
            return
        try:
            s.stop()                     # thread-safe; the SDK caps it at 5s
        except Exception as exc:
            log.debug("stream stop during shutdown: %s", exc)
        if t is not None:
            t.join(timeout=5)

    # ── reading ─────────────────────────────────────────────────────────────

    def latest(self, symbol: str) -> Optional[dict]:
        """The most recent trade seen for `symbol`, or None if this feed has
        not printed one since we subscribed. None is a real answer — see the
        module docstring — not a failure to report."""
        tick = self._last.get(symbol.upper())
        if not tick:
            return None
        out = dict(tick)
        out["age_s"] = round(time.time() - tick["received"], 2)
        out["stale"] = out["age_s"] > TICK_STALE_AFTER_S
        return out

    def status(self) -> dict:
        with self._lock:
            return {
                "connected": self._stream is not None,
                "feed": self.feed,
                "available": not (self._failed_at is not None and time.time() - self._failed_at < FAILED_RETRY_S),
                # Counts, not just names: "NVDA is subscribed" and "NVDA is
                # subscribed eleven times because nothing is releasing" look
                # identical without them.
                "symbols": dict(sorted(self._refs.items())),
            }


_streams: dict[str, _MarketStream] = {}
_streams_lock = threading.Lock()


def for_key(key: str, secret: str, kind: str = "stock", feed: str = "iex") -> _MarketStream:
    """The connection for one Alpaca account, created on first use. Keyed
    by a digest of the key, so the plaintext is not a dict key and readers
    sharing an account share its one connection. A plan change (IEX to SIP)
    closes the old connection first: the account holds one at a time."""
    import hashlib
    digest = hashlib.sha256(f"{kind}:{key}:{secret}".encode()).hexdigest()[:24]
    with _streams_lock:
        s = _streams.get(digest)
        if s is not None and kind == "stock" and s.feed != feed:
            old, s = s, None
            threading.Thread(target=old.shutdown, name="alphadesk-stream-swap", daemon=True).start()
        if s is None:
            s = _MarketStream(key, secret, kind, feed)
            _streams[digest] = s
        return s


def for_current_user(kind: str = "stock") -> Optional[_MarketStream]:
    """The signed-in user's own Alpaca connection, or None when they have
    not connected an Alpaca key — the caller then says the panel is not
    live, never falls back to anyone else's feed."""
    from alphadesk.providers import get_prices
    vendor = get_prices().vendors.get("alpaca")
    inner = getattr(vendor, "_inner", vendor)
    key, secret = getattr(inner, "api_key", ""), getattr(inner, "api_secret", "")
    if not key or not secret:
        return None
    feed = "iex"
    if kind == "stock":
        try:
            feed = inner.stock_feed()
        except Exception as exc:                          # the probe failing leaves the free feed
            log.debug("stream plan probe: %s", exc)
    return for_key(key, secret, kind, feed)


def _deliver_news(owners: list[str], article: Any) -> None:
    from alphadesk.ingest import news
    for owner in owners:
        try:
            news.ingest_streamed(owner, article)
        except Exception as exc:                        # one reader's failure is theirs alone
            log.warning("streamed story for %s not stored: %s", owner[:8], exc)


#: News feeds that deliver over a held real-time connection; every other feed
#: arrives on the poll. The Account page states this per feed (2026-09-18) so
#: a reader sees why one feed's stories land in seconds and another's in
#: minutes — read from here, so the page cannot claim a stream that is not.
STREAMING_NEWS = frozenset({"alpaca"})


def news_for_user(uid: str) -> Optional[_MarketStream]:
    """The real-time news connection for ONE reader's own Alpaca news key, or
    None when their news keys include no Alpaca key — the other feeds have no
    real-time stream and stay on the poll."""
    from alphadesk.ingest import news
    from alphadesk.ledger import store
    for row in store.get_user_keys(uid, "news"):
        if row["provider"] not in STREAMING_NEWS:
            continue
        try:
            provider = news._user_news_provider(uid, row["created_at"], row["provider"], row["config"])
        except Exception as exc:
            log.debug("news stream key: %s", exc)
            return None
        key, secret = getattr(provider, "key", ""), getattr(provider, "secret", "")
        if key and secret:
            return for_key(key, secret, "news")
    return None


def news_for_current_user() -> tuple[Optional[_MarketStream], Optional[str]]:
    """The same for the signed-in reader, with their id: what an open tab
    subscribes to."""
    from alphadesk.identity import request_user
    uid = request_user()
    if not uid:
        return None, None
    return news_for_user(uid), uid


#: Readers whose news connection this process holds open with no tab,
#: and the connection each hold was taken on (a key change makes a new one).
_news_holds: dict[str, _MarketStream] = {}
_news_holds_lock = threading.Lock()


def hold_news_for(user_ids: list[str]) -> tuple[int, int]:
    """Keep a live news connection open for each reader listed, with no
    browser tab (2026-09-17).

    MEASURED: with the connection held only while a tab subscribed, a reader
    away from the terminal saw stories no sooner than the next poll — up to
    NEWS_REFRESH_MINUTES late, where Benzinga delivers them over the socket
    in seconds. Sampled against Yahoo's headline feed across ten large caps
    at 20:10 UTC on 2026-09-17, our newest story per ticker was a median of
    76 minutes old against their 34; almost all of that gap was the poll.

    A hold is one owner reference (the story is stored as that reader's) plus
    one subscription to the whole feed, and it is idempotent: calling this
    every cycle re-uses the hold, revives a socket that dropped, and releases
    the readers who have since gone inactive. Invariant 8 permits it — this
    is each reader's own news feed on each reader's own key, stored under
    them and shared with nobody.

    Returns (held now, released this call).
    """
    wanted = set(user_ids)
    dropped = 0
    with _news_holds_lock:
        for uid in list(_news_holds):
            if uid in wanted:
                continue
            market = _news_holds.pop(uid)
            dropped += 1
            try:
                market.drop_owner(uid)
                market.release("*")
            except Exception as exc:                      # pragma: no cover
                log.debug("releasing the news hold for %s: %s", uid[:8], exc)
        for uid in wanted:
            held = _news_holds.get(uid)
            if held is not None:
                held.ensure_live()                        # a dropped socket comes back
                continue
            market = news_for_user(uid)
            if market is None:
                continue                                  # no Alpaca key: the poll is their feed
            market.add_owner(uid)
            if not market.acquire("*"):
                market.drop_owner(uid)                    # streaming unavailable; poll covers it
                continue
            _news_holds[uid] = market
        return len(_news_holds), dropped


def shutdown_all() -> None:
    with _streams_lock:
        items = list(_streams.values())
    for s in items:
        s.shutdown()


def status_all() -> dict:
    with _streams_lock:
        items = list(_streams.values())
    return {"accounts": len(items), "connected": sum(1 for s in items if s.status()["connected"]),
            "symbols": sum(len(s.status()["symbols"]) for s in items)}


# ── one browser connection for every live surface ─────────────────────────


# How long an upstream subscription outlives the connection that held it
# (2026-09-15). A tab reopens its one live connection whenever the set of
# symbols it watches changes, so the new connection subscribes a moment after
# the old one lets go; without a grace period that is an unsubscribe and a
# resubscribe upstream per click, and the last price forgotten in between.
RELEASE_GRACE_S = 5.0

# What one connection may carry. Quotes are the panels' rows (movers,
# watchlist, market ETFs) unioned; trades are the charts and quote blocks on
# screen; coins are the tape and crypto movers.
LIVE_TRADES_MAX = 12
LIVE_QUOTES_MAX = 120
LIVE_COINS_MAX = 40


class LiveMux:
    """Every live surface of one browser tab on ONE Server-Sent Events
    connection (2026-09-15).

    A tab used to open a connection per chart symbol, one per quotes panel
    and one for crypto. Over HTTP/1.1 — a local server — a browser keeps six
    connections to an origin, and the Markets board held five or six open
    streams, so a chart request could wait indefinitely for a free one. Now
    the tab holds one, and three channels share it:

    - trades: every new print for a charted symbol (the chart's live edge),
      each frame one tick, as `event: trade`;
    - quotes: the latest price per row symbol, deduped on price and pushed at
      most every `panel_push_s` per symbol, as `event: quotes`;
    - coins: the same for crypto, at `coin_push_s`, as `event: crypto`.

    Pure bookkeeping over the reader's market streams: `open` takes the
    references and says what is live, `frames` is called on a clock and
    returns the frames to send, `close` hands every reference to `release`
    (which the endpoint delays by RELEASE_GRACE_S)."""

    def __init__(self, stock: Optional["_MarketStream"], crypto: Optional["_MarketStream"],
                 trades: list[str], quotes: list[str], coins: list[str],
                 *, panel_push_s: float, coin_push_s: float, pair_of,
                 news: Optional["_MarketStream"] = None, news_owner: Optional[str] = None,
                 news_seq=None) -> None:
        self._stock, self._crypto, self._pair_of = stock, crypto, pair_of
        # The news channel: this reader's real-time feed, and how to read the
        # count of stories stored for them (ingest/news.py stream_seq).
        self._news, self._news_owner, self._news_seq = news, news_owner, news_seq
        self._news_live = False
        self._news_at: Optional[int] = None
        self._want_trades = trades[:LIVE_TRADES_MAX]
        self._want_quotes = quotes[:LIVE_QUOTES_MAX]
        self.skipped_quotes = quotes[LIVE_QUOTES_MAX:]
        self._want_coins = [c for c in coins if pair_of(c)][:LIVE_COINS_MAX]
        self._panel_push_s, self._coin_push_s = panel_push_s, coin_push_s
        # (market, upstream symbol) per reference taken, for close().
        self._held: list[tuple["_MarketStream", str]] = []
        self._trades: list[tuple[str, "_MarketStream", str]] = []
        self._quotes: list[str] = []
        self._coins: list[tuple[str, str]] = []
        self._trade_at: dict[str, Any] = {}
        self._price: dict[tuple[str, str], float] = {}
        self._sent: dict[tuple[str, str], float] = {}

    def _take(self, market: Optional["_MarketStream"], upstream: str) -> bool:
        if market is None or not market.acquire(upstream):
            return False
        self._held.append((market, upstream))
        return True

    def open(self) -> dict:
        """Take the references; the hello frame's body."""
        live_trades: dict[str, bool] = {}
        for sym in self._want_trades:
            pair = self._pair_of(sym)
            market, upstream = (self._crypto, pair) if pair else (self._stock, sym)
            ok = self._take(market, upstream)
            live_trades[sym] = ok
            if ok:
                self._trades.append((sym, market, upstream))
        self._quotes = [s for s in self._want_quotes if self._take(self._stock, s)]
        self._coins = [(c, self._pair_of(c)) for c in self._want_coins if self._take(self._crypto, self._pair_of(c))]
        if self._news is not None and self._news_owner:
            self._news.add_owner(self._news_owner)
            self._news_live = self._take(self._news, "*")
            if self._news_seq:
                self._news_at = self._news_seq(self._news_owner)
        return {
            "news": self._news_live,
            "trades": live_trades,
            "quotes": {"symbols": self._quotes, "skipped": self.skipped_quotes, "live": bool(self._quotes)},
            "crypto": {"products": [c for c, _ in self._coins], "live": bool(self._coins)},
            "feed": self._stock.feed if self._stock else None,
        }

    def _moved(self, channel: str, key: str, tick: Optional[dict], now: float, every: float,
               skip_stale: bool = True) -> bool:
        # Coins are left their last quote midpoint however old: the tape
        # shows a price, and crypto trades around the clock.
        if not tick or (skip_stale and tick.get("stale")) or tick.get("price") == self._price.get((channel, key)):
            return False
        if now - self._sent.get((channel, key), float("-inf")) < every:
            return False
        self._price[(channel, key)], self._sent[(channel, key)] = tick["price"], now
        return True

    def frames(self, now: float) -> list[str]:
        """The frames to send this turn: one per new trade, one quotes frame
        and one crypto frame when anything moved."""
        import json as _json
        out: list[str] = []
        for sym, market, upstream in self._trades:
            tick = market.latest(upstream)
            if tick and tick.get("at") != self._trade_at.get(sym):
                self._trade_at[sym] = tick.get("at")
                out.append(f"event: trade\ndata: {_json.dumps({**tick, 'symbol': sym})}\n\n")
        moved = [t for s in self._quotes
                 if self._moved("q", s, t := self._stock.latest(s), now, self._panel_push_s)]
        if moved:
            out.append(f"event: quotes\ndata: {_json.dumps({'ticks': moved})}\n\n")
        if self._news_live and self._news_seq:
            seq = self._news_seq(self._news_owner)
            if seq != self._news_at:
                self._news_at = seq
                out.append(f"event: news\ndata: {_json.dumps({'seq': seq})}\n\n")
        coins = [{**t, "symbol": c, "product": c} for c, pair in self._coins
                 if self._moved("c", c, t := self._crypto.latest(pair), now, self._coin_push_s, skip_stale=False)]
        if coins:
            out.append(f"event: crypto\ndata: {_json.dumps({'ticks': coins})}\n\n")
        return out

    def close(self, release) -> None:
        """Hand every reference taken to `release(market, upstream)`."""
        held, self._held = self._held, []
        for market, upstream in held:
            release(market, upstream)
        if self._news is not None and self._news_owner:
            self._news.drop_owner(self._news_owner)
