"""The terminal's HTTP surface — JSON API + the built SPA. Auth is OFF by
default and opt-in for hosted deployments (see app/auth.py).

AlphaDesk is a consumption product: every endpoint here READS. Nothing books,
holds, closes or scores a position. The trading endpoints (/api/picks/*,
/api/live, /api/performance, /api/sessions, /api/timelines, /api/stats,
/api/sources, /api/quant/stats) were removed with the execution layer on
2026-08-18.
"""

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from alphadesk.app.auth import router as auth_router
from alphadesk.ledger import store
from alphadesk.providers.base import NeedsKey

log = logging.getLogger("alphadesk.dashboard")

_STATIC = Path(__file__).parent / "static"

# THE AGENT'S TOOLS (2026-09-17): the MCP tools, mounted inside the app so a
# tool call runs as the reader its token names (app/agent_tools.py). Their
# session manager has to live as long as the app does.
from contextlib import asynccontextmanager  # noqa: E402 — kept beside the mount it serves

from alphadesk.app import agent_tools  # noqa: E402

_agent_tools_app, _agent_tools_lifetime = agent_tools.build()


@asynccontextmanager
async def _lifespan(_app):
    async with _agent_tools_lifetime():
        yield


app = FastAPI(title="AlphaDesk", lifespan=_lifespan)
app.include_router(auth_router)
from alphadesk.app.admin import router as admin_router  # noqa: E402
app.include_router(admin_router)
# Mounted before every other route, so the SPA's catch-all can never answer
# a tool call with the page shell.
app.mount(agent_tools.MOUNT, _agent_tools_app)
# The OAuth sign-in connectors use (Claude.ai, ChatGPT): the authorization
# server and resource metadata at the root, as the specs place them, and the
# consent page (app/agent_oauth.py). Also before the SPA's catch-all.
from alphadesk.app import agent_oauth  # noqa: E402

app.router.routes.extend(agent_oauth.oauth_routes())
app.include_router(agent_oauth.router)


@app.exception_handler(NeedsKey)
async def _needs_key(request: Request, exc: NeedsKey):
    """No vendor the user connected serves this surface. 428 (Precondition
    Required) with the prompt a panel renders: which vendors would fill it,
    free or paid, and which of the user's own refused it on plan."""
    return JSONResponse({"detail": {"needs_key": exc.prompt()}}, status_code=428)


# COMPRESSION (2026-09-16). Every response left here uncompressed: the
# screener window was 1,084KB on the wire, a one-day minute chart 516KB,
# and the left rail pulled both on every page. JSON of this shape gives up
# roughly nine tenths of itself to gzip, so this one line is worth more
# than any payload trimming — and Cloud Run does not do it for us.
#
# The live stream is EXEMPT. Server-sent events are a long-lived response
# whose whole point is that each event arrives when it happens; a compressor
# that buffers would hold events back until its window filled, which reads
# as a dead feed. The exclusion is by media type, so any future streaming
# route is covered by the same rule.
class _GZipUnlessStreaming(GZipMiddleware):
    async def __call__(self, scope, receive, send):
        # The agent's tool server streams its replies too (MCP over HTTP).
        if scope["type"] == "http" and scope.get("path", "").startswith(("/api/stream", "/api/agent/tools")):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


app.add_middleware(_GZipUnlessStreaming, minimum_size=1_024)


@app.middleware("http")
async def _note_for_prewarm(request: Request, call_next):
    """An owner's successful read of market data is noted so the server can
    keep that panel warm (alphadesk/prewarm.py). The replays themselves carry
    a header and are never noted again."""
    response = await call_next(request)
    if (request.method == "GET" and response.status_code == 200
            and request.url.path.startswith("/api/") and not request.headers.get("x-alphadesk-prewarm")):
        from alphadesk import billing, prewarm
        from alphadesk.app import auth
        claims = auth.current_user(request)
        uid = (claims or {}).get("uid") or (None if auth.auth_required() else _local_uid())
        if uid and (not auth.auth_required() or billing.is_owner((claims or {}).get("email"))):
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            prewarm.note(uid, path)
    return response


@app.middleware("http")
async def _count_in_flight(request: Request, call_next):
    """Counts the requests being served, so the embedding worker only runs
    while the server is idle (alphadesk/semantic.py). The live streams are
    open for minutes and do not count."""
    from alphadesk import semantic
    if request.url.path.startswith("/api/stream"):
        return await call_next(request)
    semantic.request_started()
    try:
        return await call_next(request)
    finally:
        semantic.request_finished()


@app.middleware("http")
async def _login_gate(request: Request, call_next):
    """Hosted mode's one door. With ALPHADESK_AUTH unset this is a straight
    pass-through and the instance behaves exactly as it always has; with it
    set to `required`, every data route demands a signed session. Static
    files and SPA routes stay open — the shell is public code, and a deep
    link has to be able to load the page that shows the login screen."""
    from alphadesk.app import auth
    claims = auth.current_user(request)
    if auth.auth_required() and auth.is_gated(request.url.path) and claims is None:
        return Response('{"detail": "sign in required"}', status_code=401,
                        media_type="application/json")
    # Stamp the signed-in reader onto the request's context so the AI layer
    # can bill (and, with a vaulted key, RUN) their asks as theirs. The
    # contextvar rides into the threadpool a sync endpoint executes on;
    # background ingest loops never pass through here, so they stay the
    # operator's spend by construction.
    from alphadesk import identity as ai_llm
    uid = (claims or {}).get("uid")
    if not uid and not auth.auth_required():
        # An open instance acts as its one local account, so keys and every
        # keyed surface work there as for a signed-in user.
        uid = _local_uid()
    if uid:
        _touch_seen(uid)
    # The access gate (alphadesk/billing.py): off unless ALPHADESK_BILLING_
    # ENFORCE is set. On, an account past its trial with no subscription gets
    # 402 on data routes — never on its own plan, keys or agent access — and
    # the app shows the subscribe screen. Only signed-in accounts on a gated
    # instance; an open instance's local account is never stopped.
    if claims and claims.get("uid") and auth.auth_required() and auth.is_gated(request.url.path):
        from alphadesk import billing
        if not billing.exempt(request.url.path) and billing.blocked_user(claims["uid"]):
            return Response('{"detail": {"subscribe": "your free trial has ended"}}', status_code=402,
                            media_type="application/json")
    token = ai_llm.set_request_user(uid)
    try:
        return await call_next(request)
    finally:
        ai_llm.reset_request_user(token)


_local_uid_value: str | None = None


def _local_uid() -> str:
    global _local_uid_value
    if _local_uid_value is None:
        _local_uid_value = store.ensure_local_user()
    return _local_uid_value


# Throttle for the last-seen stamp: one write per user per five minutes, not
# one per request — the activity gate for per-user news polling only needs
# hour-scale truth.
_seen_stamped: dict[str, float] = {}


def _touch_seen(uid: str) -> None:
    import time
    now = time.monotonic()
    if now - _seen_stamped.get(uid, -1e9) < 300:
        return
    _seen_stamped[uid] = now
    try:
        store.touch_user_seen(uid)
    except Exception:
        pass    # a missed stamp only delays a feed poll; never fail the request


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Liveness for the GCP uptime check: 200 while the ingest loop is
    cycling, 503 if it has been silent >30 min (hung loop / dead scheduler).
    First 30 min after boot count as healthy (startup grace)."""
    from alphadesk.app import scheduler
    age = scheduler.heartbeat_age_s()
    if age < 1800 or age == float("inf") and _process_age_s() < 1800:
        return {"ok": True}
    if age == float("inf"):
        return Response("scheduler never ticked", status_code=503)
    return Response(f"ingest silent {int(age)}s", status_code=503)


_BOOT_MONO = __import__("time").monotonic()


def _process_age_s() -> float:
    import time
    return time.monotonic() - _BOOT_MONO


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@app.get("/api/filings/{symbol}")
def api_filings_list(symbol: str):
    """A symbol's recent 10-K/10-Q/8-K filings, straight from EDGAR (cheap —
    one JSON fetch, cached into the filings table). Never 500s on an unknown
    symbol or an EDGAR hiccup — returns an empty list, which the UI renders
    as 'no filings found', not an error."""
    from alphadesk.desk import filings
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return {"symbol": sym, "filings": filings.list_filings(sym)}


@app.get("/api/screener")
def api_screener():
    """Everything in the current window, UNRANKED and alphabetical — symbols
    with fresh news or a report inside SCREENER_HORIZON_DAYS, each with its
    raw headlines. Pure database read: no LLM call, no score, no top-N. The
    order of this list is not a recommendation (see desk/screener.py)."""
    from alphadesk.desk import screener
    return {"symbols": screener.inventory()}


_rail_counts: dict[str, tuple[float, tuple[int, int | None]]] = {}
RAIL_KEEP_S = 30
#: ONE REBUILD AT A TIME, PER READER (2026-09-21, after the service went
#: down). The counts were cached, but the cache is only written when the
#: rebuild FINISHES — so while one was in flight every other rail request
#: also missed and started its own. Adding three symbols in quick succession
#: was enough: each add asked the rail, each rebuilt the earnings week, none
#: returned, each held one of the forty request workers until Cloud Run
#: killed it at five minutes, and with those gone the service could not
#: serve a static file. A lock per reader means the first caller does the
#: work and the rest wait for its answer.
_rail_locks: dict[str, threading.Lock] = {}
_rail_locks_guard = threading.Lock()
#: How long a request waits for someone else's rebuild before answering with
#: what it already has. A badge is not worth a request worker.
RAIL_WAIT_S = 2.0
#: How long the rebuild itself may hold the REQUEST. Past this the request
#: returns without the number and the work carries on in the background,
#: filling the cache for the next caller — what must not happen is a vendor
#: call with no end holding a worker until the platform kills it.
RAIL_BUILD_S = 3.0
#: Two at most, and never request workers: a rebuild that never returns can
#: strand one of these without touching the ones serving pages.
_rail_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rail-counts")


def _rail_lock(owner: str) -> threading.Lock:
    with _rail_locks_guard:
        if len(_rail_locks) > 1_000:
            _rail_locks.clear()
        return _rail_locks.setdefault(owner, threading.Lock())


def _rail_numbers(owner: str, uid: str | None) -> tuple[int, int | None]:
    """The two counts, computed and cached. Runs on `_rail_pool`, never on
    the request's own thread.

    THE READER IS STAMPED ON THIS THREAD FIRST. Identity lives in a context
    variable and a bare pool thread does NOT inherit it — deliberately, so
    background work cannot borrow a reader's keys by accident. Everything
    below reads it: the screener's window is per reader, and so is the
    earnings week. Without the stamp this raised on its first line, which
    turned the whole rail into a 500 once the work moved off the request
    thread (2026-09-21). background_fill does the same thing for the same
    reason.

    NOTHING HERE MAY FAIL THE REQUEST. These are two badges beside the
    navigation; a vendor having a bad afternoon must cost the reader a
    number, not the page."""
    from alphadesk.identity import reset_request_user, set_request_user
    token = set_request_user(uid) if uid else None
    try:
        from alphadesk.desk import screener
        from alphadesk.ingest import earnings_calendar
        try:
            rows = screener.inventory()
            with_news = sum(1 for r in rows if (r.get("article_count") or 0) > 0)
        except Exception as exc:
            log.warning("rail: the news count could not be built (%s)", exc)
            with_news = (_rail_counts.get(owner) or (0, (0, None)))[1][0]
        try:
            week = earnings_calendar.week()
            calls = sum(d.get("count") or 0 for d in week.get("days") or [])
        except NeedsKey:
            calls = None
        except Exception as exc:
            log.warning("rail: the earnings count could not be built (%s)", exc)
            calls = None
        if len(_rail_counts) > 1_000:
            _rail_counts.clear()
        _rail_counts[owner] = (time.time(), (with_news, calls))
        return with_news, calls
    finally:
        if token is not None:
            reset_request_user(token)


@app.get("/api/rail")
def api_rail(symbols: str = ""):
    """THE LEFT RAIL'S THREE NUMBERS, and nothing else (2026-09-16).

    The rail shows how many symbols have news, how many companies report
    this week, and whether anything new has arrived about the board. It used
    to get them by loading three whole datasets — the screener window, the
    earnings week and the news list — on EVERY page, which measured 1.15MB
    and a 2.5-second vendor-bound call for three integers. On the News, AI,
    Profile and Options pages that was most of what the page fetched.

    The stories come back as identity only — id, tickers, time — because the
    rail compares them against a mark the browser keeps; what it never needed
    was the headlines, summaries and bodies attached to them.
    """
    from alphadesk.desk import screener
    from alphadesk.identity import request_user
    from alphadesk.ingest.news import news_owner
    board = [s.strip().upper() for s in symbols.split(",") if s.strip()][:40]
    wanted = set(board)
    uid = request_user()
    owner = news_owner(uid)
    # THE COUNTS ARE HELD HALF A MINUTE PER READER. Counting symbols with news
    # builds the whole screener window, about 800ms, and the rail asks on
    # every navigation — twice on a first render, once before the board's
    # symbols resolve and once after. The numbers are badges; half a minute
    # old is exact enough.
    def fresh(h) -> bool:
        return bool(h) and time.time() - h[0] < RAIL_KEEP_S

    held = _rail_counts.get(owner)
    if fresh(held):
        with_news, calls = held[1]
    else:
        lock = _rail_lock(owner)
        mine = lock.acquire(timeout=RAIL_WAIT_S)
        held = _rail_counts.get(owner)
        if fresh(held):
            # Someone else's rebuild landed while this request waited.
            if mine:
                lock.release()
            with_news, calls = held[1]
        elif mine:
            job = _rail_pool.submit(_rail_numbers, owner, uid)
            # Released when the WORK finishes, not when this request gives up
            # on it — otherwise the next caller starts a second rebuild of
            # the same thing, which is the pile-up this exists to prevent.
            job.add_done_callback(lambda _f: lock.release())
            try:
                with_news, calls = job.result(timeout=RAIL_BUILD_S)
            except FuturesTimeout:
                with_news, calls = held[1] if held else (0, None)
            except Exception as exc:                    # badges, not the page
                log.warning("rail: counts unavailable (%s)", exc)
                with_news, calls = held[1] if held else (0, None)
        else:
            # Someone else is rebuilding and it is taking a while. The last
            # numbers, stale, beat holding a worker for a pair of badges.
            with_news, calls = held[1] if held else (0, None)
    stories = []
    if wanted:
        for a in store.recent_articles(screener._since_iso(), limit=300, owner=owner):
            tickers = [t.upper() for t in (a.get("tickers") or [])]
            if wanted.isdisjoint(tickers):
                continue
            stories.append({"article_id": a["article_id"], "tickers": tickers,
                            "published_at": a.get("published_at")})
    return {"news_symbols": with_news, "earnings_calls": calls, "stories": stories}


@app.get("/api/news/related")
def api_news_related(q: str = "", limit: int = 60):
    """Stories in the reader's window related in MEANING to `q`, each marked
    why="related" — what the News page's filter box adds under its word
    matches (alphadesk/semantic.py, 2026-09-19). Empty until the model has
    loaded, or when semantic search is off. No article text in the list."""
    from alphadesk import semantic
    from alphadesk.desk.screener import _since_iso
    from alphadesk.identity import request_user
    from alphadesk.ingest.news import news_owner
    uid = request_user()
    if not uid or not store.get_user_keys(uid, "news"):
        raise NeedsKey("news", [], signed_in=bool(uid))
    rows = semantic.related_articles(news_owner(uid), (q or "")[:200], since=_since_iso(),
                                     limit=max(1, min(int(limit), semantic.MAX_RELATED)))
    for a in rows:
        a["has_body"] = bool(a.pop("body", None))
    return {"articles": rows, "ready": semantic.ready()}


@app.get("/api/news")
def api_news(limit: int = 300, before: str | None = None, q: str | None = None, symbol: str | None = None):
    """The window's news as a READING LIST: one row per article, newest first,
    with the story's full ticker list and the provider's summary text.
    The per-symbol fan-out stays on /api/screener, where a context window
    needs it; a reader needs each story once.

    Pure database read — no model call, no upstream fetch.
    """
    from alphadesk.desk.screener import _since_iso

    from alphadesk.identity import request_user
    from alphadesk.ingest.news import news_owner

    limit = max(1, min(int(limit), 500))
    uid = request_user()
    if not uid or not store.get_user_keys(uid, "news"):
        # No server feed (2026-09-13): news is the user's own feed key.
        raise NeedsKey("news", [], signed_in=bool(uid))
    sym = "".join(c for c in (symbol or "").upper() if c.isalnum() or c in ".-")[:14]
    from alphadesk.providers.alpaca import coin_pair
    if sym and not q and coin_pair(sym):
        # A COIN reads all crypto and what moves it, not its own tag
        # (alphadesk/cryptonews.py, 2026-09-19). The window, or with
        # `before` a page of older stories, filtered by that one rule.
        from alphadesk import cryptonews
        if before:
            pool = store.articles_before(news_owner(uid), before, limit=500)
        else:
            pool = store.recent_articles(_since_iso(), limit=8000, owner=news_owner(uid))
        articles = cryptonews.select(pool, min(limit, 300))
    elif sym and not q:
        # ONE symbol's stories (2026-09-18). The symbol panel used to filter
        # the shared window, which is the newest 500 stories across every
        # feed — a few hours — so a quiet name like XLK showed three of its
        # two days. Without `before` it is the whole window (NEWS_LOOKBACK_
        # HOURS); with it, the page of that symbol's older stories.
        rows = store.articles_for_symbol(news_owner(uid), sym, before, min(limit, 300))
        if not before:
            edge = _since_iso()
            rows = [a for a in rows if (a.get("published_at") or "") >= edge]
        articles = rows
    elif before or q:
        # A page of OLDER stories (`before`: published before this instant),
        # or a search of everything stored (`q`). Older pages reach back to
        # the reader's feed when the store runs short (ingest/news.py).
        from alphadesk.ingest.news import older_articles
        edge = before or "9999-12-31T00:00:00+00:00"
        size = min(limit, 100)
        articles = older_articles(uid, edge, limit=size, query=(q or "")[:80])
        if q:
            # And the stories related in MEANING, marked "related", merged
            # newest first (alphadesk/semantic.py, 2026-09-19).
            from alphadesk import semantic
            rel = semantic.related_articles(news_owner(uid), q[:200], before=edge,
                                            exclude={a["article_id"] for a in articles})
            articles = semantic.merge(articles, rel, size + len(rel))
    else:
        articles = store.recent_articles(_since_iso(), limit=limit, owner=news_owner(uid))
    for a in articles:
        # The list carries no article text (2026-09-15): with Benzinga's full
        # stories stored, 300 of them ran to ~1.5MB on a poll every minute.
        # The reader fetches a story's text when it opens (/story).
        a["has_body"] = bool(a.pop("body", None))
    return {"articles": articles}


@app.get("/api/news/terms")
def api_news_terms(q: str = ""):
    """The companies a news search names exactly — tickers and the short name
    a headline uses (alphadesk/newsquery.expand) — so the News page's filter
    box widens the same way "Search all" does: "robinhood" also keeps stories
    tagged HOOD, "HOOD" also keeps headlines naming Robinhood. A config read,
    no vendor call."""
    from alphadesk.newsquery import expand
    return expand(q[:80])


@app.get("/api/news/{article_id}/story")
def api_news_story(article_id: str):
    """One of the reader's stories with its full text where their feed
    delivers it — fetched once from the feed for a story stored before the
    text was asked for (ingest/news.py full_story). 404 for a story that is
    not theirs."""
    from alphadesk.identity import request_user
    from alphadesk.ingest.news import full_story
    uid = request_user()
    if not uid:
        raise NeedsKey("news", [], signed_in=False)
    story = full_story(uid, article_id[:120])
    if story is None:
        raise HTTPException(404, "no such story")
    return story


def _clean_screen(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    panels = [str(p)[:40] for p in raw.get("panels", [])
              if isinstance(p, str) and p.strip()][:12]
    symbols = ["".join(c for c in str(s).upper() if c.isalnum() or c in ".-^=")[:14]
               for s in raw.get("symbols", []) if str(s).strip()][:16]
    out = {
        "page": str(raw.get("page", ""))[:40],
        "panels": panels,
        "symbols": [s for s in symbols if s],
        "active": "".join(c for c in str(raw.get("active", "")).upper()
                          if c.isalnum() or c in ".-^=")[:14],
    }
    return out if (out["panels"] or out["symbols"]) else None


class BoardIn(BaseModel):
    symbols: list[str] = []
    active: str = ""


def _board_symbol(raw: str) -> str:
    return "".join(c for c in (raw or "").upper() if c.isalnum() or c in ".-^=/")[:14]


@app.put("/api/board")
def api_board_put(body: BoardIn, request: Request):
    """The reader's symbol strip, mirrored from the browser so their own
    agent can read it (the my_board MCP tool)."""
    uid = _key_user(request)
    seen: list[str] = []
    for raw in body.symbols[:50]:
        sym = _board_symbol(raw)
        if sym and sym not in seen:
            seen.append(sym)
    active = _board_symbol(body.active)
    store.save_board(uid, seen, active if active in seen else (seen[0] if seen else ""))
    return {"ok": True}


@app.get("/api/board")
def api_board_get(request: Request):
    return store.get_board(_key_user(request)) or {"symbols": [], "active": "", "updated_at": None}


class AccessTokenIn(BaseModel):
    name: str = ""


def _tools_url(request: Request) -> str:
    """The address a reader's agent connects to."""
    from alphadesk.app import agent_tools
    base = os.environ.get("ALPHADESK_BASE_URL", "").strip().rstrip("/") \
        or f"{request.url.scheme}://{request.url.netloc}"
    return f"{base}{agent_tools.MOUNT}/mcp"


@app.get("/api/agent/access-tokens")
def api_agent_access_tokens(request: Request):
    """The reader's live agent tokens (never the tokens themselves) and the
    address their agent connects to."""
    return {"url": _tools_url(request),
            "tokens": store.list_agent_access_tokens(_key_user(request))}


@app.post("/api/agent/access-tokens")
def api_agent_access_token_issue(body: AccessTokenIn, request: Request):
    """Issue a token. The response is the ONLY time the token is shown."""
    from alphadesk.app import agent_access
    try:
        row, secret = agent_access.issue(_key_user(request), body.name)
    except agent_access.TokenLimit as exc:
        raise HTTPException(422, str(exc)) from exc
    # no-store: a token must not linger in any cache between here and the page.
    return JSONResponse({**row, "token": secret, "url": _tools_url(request)},
                        headers={"Cache-Control": "no-store"})


@app.delete("/api/agent/access-tokens/{token_id}")
def api_agent_access_token_revoke(token_id: str, request: Request):
    if not store.revoke_agent_access_token(_key_user(request), token_id):
        raise HTTPException(404, "no such token")
    return {"ok": True}


@app.get("/api/agent/connections")
def api_agent_connections(request: Request):
    """Apps the reader let in through the OAuth sign-in."""
    return {"connections": store.list_oauth_grants(_key_user(request))}


@app.delete("/api/agent/connections/{grant_id}")
def api_agent_connection_revoke(grant_id: str, request: Request):
    if not store.revoke_oauth_grant(grant_id, _key_user(request)):
        raise HTTPException(404, "no such connection")
    return {"ok": True}


# PLAN REFUSALS (2026-09-10). A key's plan is invisible until a request hits
# its wall; when one does, the refused interval is remembered for that reader
# and provider for an hour, the menu marks it, and the same wall is not hit
# on every poll. Keyed by (reader, provider) → {interval: expiry}.
_REFUSAL_TTL_S = 3600
_refusals: dict[tuple[str, str], dict[str, float]] = {}


def _chart_reader() -> str:
    from alphadesk.providers.registry import _request_uid
    return _request_uid() or "anon"


def _refused(reader: str, provider: str) -> set[str]:
    import time as _time
    now = _time.monotonic()
    box = _refusals.get((reader, provider)) or {}
    live = {k: v for k, v in box.items() if v > now}
    if live != box:
        _refusals[(reader, provider)] = live
    return set(live)


def _refuse(reader: str, provider: str, interval: str) -> None:
    import time as _time
    if len(_refusals) > 4096:
        _refusals.clear()
    _refusals.setdefault((reader, provider), {})[interval] = _time.monotonic() + _REFUSAL_TTL_S


def _chart_intervals_of(provider) -> dict[str, dict]:
    """The provider's catalogue, or the builtin table for one that predates
    the declaration (a plugin registered before 2026-09-10)."""
    from alphadesk.ingest.prices import CHART_INTERVALS
    fn = getattr(provider, "chart_intervals", None)
    try:
        table = fn() if callable(fn) else None
    except Exception:
        table = None
    return table or CHART_INTERVALS


@app.get("/api/chart/capabilities")
def api_chart_capabilities():
    """What the reader's ACTIVE price provider can chart: every interval it
    serves, fine to coarse, with how far back each reaches. The toolbar
    builds its interval menu from this and nothing else — a key that
    carries second bars is offered them; one that does not is not."""
    from alphadesk.ingest.prices import interval_seconds
    from alphadesk.providers import get_prices
    provider = get_prices().vendor_for("chart", "chart_series")
    table = _chart_intervals_of(provider)
    return {
        "provider": provider.name,
        "intervals": [
            {"id": k, "label": v["label"], "unit": v["unit"], "n": v["n"], "max_days": v["max_days"]}
            for k, v in sorted(table.items(), key=lambda kv: interval_seconds(kv[1]))
        ],
        # Intervals this reader's plan has refused in the last hour.
        "refused": sorted(_refused(_chart_reader(), provider.name)),
    }


@app.get("/api/chart/{symbol}")
def api_chart(symbol: str, days: int = 2, range: str | None = None,
              interval: str | None = None, before: str | None = None,
              source: str | None = None, need: int | None = None):
    """OHLC + RSI-9 + MACD(12,26,9) series for the human decision chart.

    Always returns the data-quality block (coverage / median_gap_min /
    indicators_reliable). The UI must render that: on the free IEX feed an
    illiquid name's "1-minute" chart can be a handful of prints stretched
    across days, and it draws identically to a real one.
    """
    from alphadesk.providers import get_prices
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    # `range` (1D/5D/1M/3M/6M/YTD/1Y/5Y/MAX) picks the SERIES, not just its
    # length: 1D and 5D come off the minute feed, everything longer off daily
    # bars, because the minute feed reaches about 30 days. `days` stays for
    # callers that predate ranges.
    from alphadesk.ingest.prices import CHART_RANGES
    if range and range.upper() not in CHART_RANGES:
        raise HTTPException(400, f"range must be one of {', '.join(CHART_RANGES)}")
    # One vendor serves a chart and every page of its history: the first
    # connected vendor that charts, never a mix.
    provider = get_prices().vendor_for("chart", "chart_series")
    table = _chart_intervals_of(provider)
    if interval and interval.lower() not in table:
        raise HTTPException(400, f"interval must be one of {', '.join(table)} on {provider.name}")
    # A too-fine interval for the span is downgraded rather than refused, and
    # the response reports what was actually served — see resolve_interval.
    from alphadesk.ingest.prices import resolve_interval
    reader = _chart_reader()
    wanted = resolve_interval(range or "1D", interval, table)
    label = lambda k: table.get(k, {}).get("label", k)  # noqa: E731
    # `before` asks for a HISTORY PAGE — the bars before that instant, one
    # range-span deep. The reader panning left past the oldest bar asks for
    # it; an empty page is the end of the history, answered as 404.
    cursor = None
    if before:
        from datetime import datetime, timezone
        try:
            cursor = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "before must be an ISO-8601 instant")
        if cursor.tzinfo is None:
            cursor = cursor.replace(tzinfo=timezone.utc)
    # The cursor is passed only when there is one, so a plugin provider
    # written to the older signature still serves its first page; one that
    # cannot take the keyword at all simply has no history to page.
    from alphadesk.ingest.prices import (PAGE_MAX_BARS, PAGE_MIN_BARS, SourceUnavailable,
                                         history_ceiling_note, history_floor)
    # HOW FAR LEFT THIS BAR SIZE GOES. Scrolling back does not go on for
    # ever: each bar size has a reach, and at its end the chart says so
    # instead of trawling a thinner and thinner trickle of intraday bars
    # from years ago. Further back is a coarser bar, which is what a longer
    # range serves.
    if cursor is not None:
        from alphadesk.config import now_et
        floor = history_floor(wanted, now_et())
        if floor is not None and cursor <= floor:
            raise HTTPException(404, history_ceiling_note(wanted))
    page = {"before": cursor} if cursor is not None else {}
    # `need` is how much BLANK the chart has to its left, in bars: zoomed
    # out, one range-span page fills a sliver of it and the reader watches
    # the line creep in page by page. Asking for the whole gap lets the
    # vendor window widen until one page covers it.
    if cursor is not None and need:
        page["need"] = max(PAGE_MIN_BARS, min(int(need), PAGE_MAX_BARS))
    # `source` is accepted from older clients and ignored: a vendor serves
    # one tape by nature.
    try:
        return _chart_or_fallback(provider, sym, days, range, interval, page, reader, wanted, table, label)
    except SourceUnavailable as exc:
        # The source FAILED — a rate limit, a timeout — which is not "no
        # bars": 503 with a Retry-After, so the client keeps the series it
        # has and asks again, instead of reading a blip as the end of history.
        raise HTTPException(503, f"{provider.name}: {exc}", headers={"Retry-After": "15"})


def _chart_or_fallback(provider, sym, days, range, interval, page, reader, wanted, table, label):
    from alphadesk.ingest.prices import interval_seconds
    from alphadesk.providers.base import EntitlementError
    try:
        # A bar the plan refused within the hour is not asked for again on
        # every poll: the refusal is remembered, so go straight to the
        # coarser bar rather than paying the refused call and the fallback
        # twice a minute for as long as the pin lasts.
        if interval and wanted in _refused(reader, provider.name):
            raise EntitlementError(f"{label(wanted)} bars were refused by the plan earlier this hour")
        try:
            series = provider.chart_series(sym, days=days, range_key=range, interval=interval, **page)
        except TypeError as exc:
            # A provider written before the page depth was asked for still
            # pages: drop the depth and take its own window.
            if "need" in str(exc) and "need" in page:
                series = provider.chart_series(sym, days=days, range_key=range, interval=interval,
                                               **{k: v for k, v in page.items() if k != "need"})
            elif not page or ("before" not in str(exc) and "source" not in str(exc)):
                raise
            else:
                raise HTTPException(404, f"{provider.name} does not page history")
        note = None
    except EntitlementError as first:
        # The plan's wall. Remember it, then try the coarser bars the plan
        # may serve — a reader on the free tier still gets a chart, and the
        # response says which bar it is and why.
        _refuse(reader, provider.name, wanted)
        refused = _refused(reader, provider.name)
        series, note = None, None
        coarser = [k for k in sorted(table, key=lambda k: interval_seconds(table[k]))
                   if interval_seconds(table[k]) > interval_seconds(table[wanted]) and k not in refused]
        for alt in coarser:
            try:
                series = provider.chart_series(sym, days=days, range_key=range, interval=alt, **page)
            except EntitlementError:
                _refuse(reader, provider.name, alt)
                continue
            if series:
                note = (f"Your {provider.name} plan does not include {label(wanted)} bars"
                        f" ({first}); showing {label(series.get('interval', alt))}.")
                break
        if not series:
            raise HTTPException(402, f"Your {provider.name} plan does not include {label(wanted)} bars: {first}")
    if not series:
        if page.get("before") is not None:
            # A page with nothing before it: the end of the feed's history
            # at this interval, named so the chart can say so at the edge.
            from alphadesk.ingest.prices import history_reach_note
            raise HTTPException(404, history_reach_note(wanted))
        raise HTTPException(404, f"no bars for {sym}")
    if note:
        series["plan_note"] = note
        series["interval_requested"] = (interval or "").lower() or None
    return series


# HOW OFTEN A LIVE SURFACE MAY REPAINT. Two numbers, and the split is the
# point: a flash lasts 420ms, so anything pushed faster than about a second
# leaves the tint permanently on and stops reading as a change at all — which
# is exactly what the first version of the crypto ticker did.
#
# A single number can take a faster cadence than a table. The strip shows one
# price per instrument and nothing moves position; a panel re-ranks twenty rows,
# and a table reordering every two seconds is unreadable however live it is.
_TICKER_PUSH_S = float(os.environ.get("CRYPTO_MIN_PUSH_S", "2.0"))
_PANEL_PUSH_S = float(os.environ.get("PANEL_PUSH_S", "5.0"))

# Kept as the old name so a deployment's existing env still applies.
_CRYPTO_MIN_PUSH_S = _TICKER_PUSH_S


def stream_symbols(raw: str, cap: int = 10_000, extra: str = "") -> tuple[list[str], list[str]]:
    """Parse a comma list into (taken, skipped): cleaned, de-duplicated, in
    the order given, with everything past `cap` in the second list. `extra`
    admits more punctuation ("/" for a coin pair)."""
    wanted: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        sym = "".join(c for c in part.upper() if c.isalnum() or c in ".-^=" + extra)[:14]
        if sym and sym not in seen:
            seen.add(sym)
            wanted.append(sym)
    return wanted[:cap], wanted[cap:]


@app.get("/api/stream")
async def api_stream(request: Request, trades: str = "", quotes: str = "", crypto: str = "", news: int = 0):
    """Every live surface of one browser tab on ONE Server-Sent Events
    connection (2026-09-15): `trades` for the charted symbols (a frame per
    print), `quotes` for panel rows and `crypto` for coins (latest prices,
    deduped and paced). See LiveMux in ingest/stream.py.

    It replaced a connection per chart symbol, one per quotes panel and one
    for crypto: over HTTP/1.1 a browser keeps six connections to an origin,
    the Markets board held five or six streams, and a chart request could
    wait indefinitely for a free one.

    The tab reopens this connection with the new lists when what it watches
    changes. Subscription changes are not sent on a side request, because on
    Cloud Run that request can land on another instance than the stream. The
    references are released RELEASE_GRACE_S after disconnect, so the reopened
    connection finds the upstream subscriptions and their last prices still
    there.

    The feeds: a paid Alpaca plan streams SIP, every US exchange; a free key
    streams IEX, a few percent of volume, where a quiet row means this feed
    saw no print, not that the stock did not trade. Outside market hours it
    subscribes and sits silent. The upstream connections are the reader's own
    (Alpaca allows one per account); without an Alpaca key the hello says
    nothing is live and nothing else is sent.

    Async on purpose: every other endpoint is a sync def on the 40-worker
    threadpool, and a long-lived one of those would park a worker per viewer.
    """
    import asyncio
    import time as _time

    from alphadesk.ingest import stream as streams
    from alphadesk.providers.alpaca import coin_pair

    def clean(raw: str, extra: str = "") -> list[str]:
        return stream_symbols(raw, extra=extra)[0]

    stock = streams.for_current_user("stock") if (trades or quotes) else None
    coins = streams.for_current_user("crypto") if (crypto or trades) else None
    # The news channel (2026-09-15): the reader's Alpaca news key streams
    # stories as they publish; each is stored as theirs and the tab is told to
    # reread its list. Other feeds have no real-time stream and stay polled.
    news_stream, news_owner = streams.news_for_current_user() if news else (None, None)
    from alphadesk.ingest.news import stream_seq
    mux = streams.LiveMux(stock, coins, clean(trades, "/"), clean(quotes), clean(crypto, "/"),
                          panel_push_s=_PANEL_PUSH_S, coin_push_s=_CRYPTO_MIN_PUSH_S, pair_of=coin_pair,
                          news=news_stream, news_owner=news_owner, news_seq=stream_seq)

    def release_later(market, upstream):
        asyncio.get_running_loop().call_later(streams.RELEASE_GRACE_S, market.release, upstream)

    async def events():
        hello = mux.open()
        try:
            yield f"event: hello\ndata: {json.dumps(hello)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                sent = mux.frames(_time.monotonic())
                for frame in sent:
                    yield frame
                if not sent:
                    # A comment line keeps proxies from timing the connection
                    # out while every symbol is genuinely quiet.
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)
        finally:
            mux.close(release_later)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        # nginx and friends buffer text/event-stream by default, which turns a
        # live feed into a batch delivered whenever the buffer fills.
        "X-Accel-Buffering": "no",
    })


# The quote block's figures beyond price — size, multiples, dividend, the
# analysts' target — come from whichever connected vendor carries key
# statistics; a field no vendor carries stays absent, never guessed.
_QUOTE_STAT_FIELDS = {
    "market_cap": "market_cap", "enterprise_value": "enterprise_value", "pe_forward": "forward_pe",
    "pe_trailing": "trailing_pe", "peg": "peg", "price_to_sales": "price_to_sales", "price_to_book": "price_to_book",
    "beta": "beta", "eps_ttm": "trailing_eps", "dividend_yield": "dividend_yield", "dividend_rate": "dividend_rate",
    "ex_dividend_date": "ex_dividend_date", "earnings_date": "earnings_date", "fiscal_year_end": "fiscal_year_end",
    "week52_low": "week52_low", "week52_high": "week52_high", "avg_volume": "avg_volume",
}


def _with_key_stats(router, sym: str, q: dict) -> dict:
    stats = router.get("key_stats", sym) or {}
    for ours, theirs in _QUOTE_STAT_FIELDS.items():
        if q.get(ours) is None and stats.get(theirs) is not None:
            q[ours] = stats[theirs]
    if stats and not q.get("name") and stats.get("name"):
        q["name"] = stats["name"]
    if not q.get("fiscal_year_end"):
        # The registrant's fiscal year end from SEC EDGAR (keyless): what
        # turns a June quarter into "Q3 FY26" on the earnings panels.
        try:
            from datetime import date
            from alphadesk.ingest.company import _edgar_facts
            fye = (_edgar_facts(sym) or {}).get("fiscal_year_end")          # "09-26"
            if fye:
                q["fiscal_year_end"] = f"{date.today().year - 1}-{fye}"
        except Exception:
            pass
    return q


@app.get("/api/quote/{symbol}")
def api_quote(symbol: str):
    """The equity-overview block for one symbol."""
    from alphadesk.providers import get_prices
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    router = get_prices()
    q = router.ask("quote", sym)
    return _with_key_stats(router, sym, dict(q))


@app.get("/api/search")
def api_search(q: str = "", limit: int = 50):
    """Ticker/name search, so a symbol can be picked rather than typed exactly.

    Served from the SEC's ticker list (keyless public data, cached a week)
    plus the coin pairs a user can chart. The empty query offers the user's
    own most-active list when their vendors carry one.
    """
    from alphadesk.config import search_symbols, symbol_meta
    # 100, not 50. A two-letter query legitimately matches dozens — "fd" has 41
    # symbols starting with it before a single one that merely contains it, so
    # a short cap made the substring matches unreachable rather than merely
    # low. The popover scrolls; the reader decides where to stop looking.
    n = max(1, min(limit, 100))
    if q.strip():
        return {"results": search_symbols(q, limit=n), "trending": False}

    # Empty query: offer what is actually moving rather than a hardcoded list —
    # and the SAME list the Markets tile shows, which is the point of calling
    # it trending.
    #
    # The raw screener ranks by SHARE COUNT, so sub-dollar stocks own it:
    # Advasa at 11.5 cents and Cheetah Net at 5.9 cents outranked NVIDIA on
    # volume while trading $31M and $15M against its $19bn (measured
    # 2026-09-16). The category list applies the reader's price, turnover and
    # liquidity floors; the search had been reading past them.
    try:
        from alphadesk.ingest import movers as movers_ingest
        tabs = (movers_ingest.category_movers("stocks", top=n) or {}).get("tabs") or []
        active = next((t["rows"] for t in tabs if t.get("id") == "most_active"), [])
    except Exception:
        active = []
    out = []
    for row in active[:n]:
        meta = symbol_meta(row["symbol"]) or {"symbol": row["symbol"], "name": row.get("name"),
                                              "exchange": None, "asset_class": None}
        out.append(meta)
    return {"results": out, "trending": True}


@app.get("/api/company/{symbol}")
def api_company(symbol: str):
    """The company behind a symbol: EDGAR's registrant facts, the latest
    10-K's Business and Properties sections verbatim, and the profile feed's
    summary, headcount and officers. See ingest/company."""
    from alphadesk.ingest.company import profile
    # Wider than the equity cleaner: the cross-asset board's symbols carry
    # ^ (indices), = (futures, FX) and - (crypto pairs).
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    out = profile(sym)
    if not out:
        # A COIN is not a missing company: nothing in EDGAR or a company
        # feed knows it, and the coin record needs a vendor that carries
        # coins. Saying which one fills the panel beats "no company record"
        # (2026-09-15).
        from alphadesk.providers import get_prices
        from alphadesk.providers.alpaca import coin_pair
        from alphadesk.ingest.company import _crypto_key
        # The key prompt only when there IS no CoinGecko key; with one, a
        # coin CoinGecko does not know is simply not found.
        if coin_pair(sym) and not _crypto_key():
            raise NeedsKey("coin_profile", signed_in=get_prices().uid is not None)
        raise HTTPException(404, f"no {'coin' if coin_pair(sym) else 'company'} record for {sym}")
    return out


@app.get("/api/events/{symbol}")
def api_events(symbol: str, days: int = 400):
    """Dated events for the chart — earnings releases (EDGAR 8-K Item 2.02,
    each with its accession), dividends and splits. See ingest/events."""
    from alphadesk.ingest.events import events
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return events(sym, days=max(30, min(days, 3650)))


@app.get("/api/fundamentals/{symbol}")
def api_fundamentals(symbol: str, period: str = "quarterly"):
    """Financial-statement series for plotting against price.

    Only metrics upstream actually reports for this company are returned, so
    the chart's Metrics menu offers nothing that would draw an empty line.
    """
    from alphadesk.ingest.edgar_financials import fundamentals_series
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    if period not in ("quarterly", "annual"):
        raise HTTPException(400, "period must be quarterly or annual")
    return fundamentals_series(sym, period)


@app.get("/api/movers")
def api_movers(top: int = 20):
    """Most active / gainers / losers, filtered for tradeability."""
    from alphadesk.providers import get_prices
    return get_prices().ask("movers", top=max(1, min(top, 50)))


@app.get("/api/social/posts")
def api_social_posts(limit: int = 20):
    """Recent social posts — 428 until the reader switches the social source
    on. Unverified user-generated text (2026-09-22)."""
    from alphadesk.providers import get_prices
    return {"posts": get_prices().ask("social_posts", limit=max(1, min(limit, 100)),
                                      surface="social") or []}


@app.get("/api/social/trending")
def api_social_trending(limit: int = 30):
    """The symbols being talked about, in the vendor's own rank order.
    Attention, not news."""
    from alphadesk.providers import get_prices
    return {"symbols": get_prices().ask("social_trending", limit=max(1, min(limit, 100)),
                                        surface="social") or []}


@app.get("/api/gov/feed")
def api_gov_feed(sources: str = "", days: int = 7, limit: int = 50,
                 agencies: str = "", types: str = ""):
    """What the government just did: agency rules and proposed rules from the
    Federal Register, the Fed's own announcements, and Treasury auction
    results (2026-09-22). Keyless public government data."""
    from alphadesk.ingest import gov_feed
    pick = lambda text: [x.strip() for x in text.split(",") if x.strip()]   # noqa: E731
    return gov_feed.recent(sources=pick(sources) or None, days=max(1, min(days, 90)),
                           limit=max(1, min(limit, 200)),
                           agencies=pick(agencies) or None, types=pick(types) or None)


@app.get("/api/filings/feed")
def api_filing_feed(groups: str = "", limit: int = 50, symbol: str = "",
                    listed_only: bool = True):
    """WHAT HAS JUST BEEN FILED, market-wide, newest first (2026-09-22).

    Keyless — EDGAR is public government data. Every other filings surface
    here reads ONE company; this one answers "what was just filed", with the
    SEC's own acceptance time on each row."""
    from alphadesk.ingest import edgar_feed
    picked = [g.strip() for g in groups.split(",") if g.strip()]
    return edgar_feed.recent(groups=picked or None, limit=max(1, min(limit, 200)),
                             symbol=symbol.strip().upper() or None,
                             listed_only=listed_only)


@app.get("/api/halts")
def api_trading_halts(limit: int = 100):
    """Today's trading halts and resumptions (2026-09-22).

    A catalyst with its own clock: the exchange stopped the stock at a stated
    time for a stated reason and said when it would resume. No keyed vendor in
    the catalogue carries it, so this answers 428 until a source that does is
    switched on."""
    from alphadesk.providers import get_prices
    return {"halts": get_prices().ask("trading_halts", limit=max(1, min(limit, 500)),
                                      surface="trading_halts")}


@app.get("/api/sectors")
def api_sectors():
    """The Sectors page: the eleven S&P sector funds and a set of industry
    funds with trailing returns, 52-week range, today's dollars traded and
    return relative to SPY, in one request (ingest/sectors.py). 428 when no
    connected vendor carries daily bars."""
    from alphadesk.ingest import sectors
    return sectors.sectors()


@app.get("/api/sectors/breadth")
def api_sectors_breadth():
    """Per sector: how many of its US-listed companies over $2B are up and
    down today, and its ten largest with today's move (ingest/sectors.py).
    428 when no connected vendor lists companies by sector."""
    from alphadesk.ingest import sectors
    return sectors.breadth()


@app.get("/api/movers/{category}")
def api_category_movers(category: str, top: int = 20,
                        min_price: float | None = Query(None, ge=0),
                        min_turnover: float | None = Query(None, ge=0),
                        min_liquidity: float | None = Query(None, ge=0),
                        min_volatility: float | None = Query(None, ge=0)):
    """Movers by category — stocks, crypto, etfs, mutual_funds, options,
    indices, futures, bonds, currencies — one shape for one tile
    (ingest/movers.py). The floors are the reader's when given, the
    category's defaults otherwise. 404 for a category that does not exist."""
    from alphadesk.ingest import movers
    try:
        return movers.category_movers(category, top=max(1, min(top, 50)),
                                      min_price=min_price, min_turnover=min_turnover,
                                      min_liquidity=min_liquidity, min_volatility=min_volatility)
    except KeyError:
        raise HTTPException(404, f"no such category: {category}")


@app.get("/api/tape")
def api_tape():
    """The market strip pinned across the top of the terminal. Cached upstream
    for a minute — this is glanceable context, not a quote feed."""
    from alphadesk.providers import get_prices
    return {"tape": get_prices().ask("market_tape")}


# Four, measured: nine concurrent per-symbol quotes made the upstream hand back
# 404s at random, and one at a time took 8.9s for eight symbols.
_QUOTES_CONCURRENCY = int(os.environ.get("QUOTES_CONCURRENCY", "4"))


@app.get("/api/quotes")
def api_quotes(symbols: str = "", fill: str = ""):
    """Quotes for a BASKET, in one request.

    A theme page asking for nine symbols used to fire nine per-symbol requests
    at once. Every endpoint here is a sync def on a 40-worker threadpool, so
    that is nine threads hitting the upstream simultaneously — and it throttled,
    returning 404 for two or three of them at random. The rows that lost the
    race rendered as dashes, which reads as "this company has no price" rather
    than "we asked too fast".

    BOUNDED, not serial and not unbounded. Nine at once throttles; one at a
    time is nine times a single quote's latency, which measured 8.9s cold for
    eight symbols and is a page that looks broken while it loads. Four workers
    is the middle: fast enough to paint, slow enough that the upstream does not
    start refusing. The per-symbol cache underneath makes a warm basket
    effectively free (measured 0.002s), and this fills that same cache, so
    opening one of these names on Analysis afterwards is already answered.

    A symbol that genuinely has no quote comes back null rather than dropping
    out: the caller asked for a specific list and needs to know which member
    failed, not receive a shorter list.

    `fill` asks for the fields a quote vendor may not carry, and costs a
    request each for the whole basket, so a caller opts in rather than every
    tile paying (2026-09-16): `range` computes the 52-week high and low from
    the reader's own daily bars (Alpaca's quote carries no range at all, so
    the column was empty), `cap` reads market capitalisation from the
    vendor that lists it for many companies at once, `avgvol` averages the
    last twenty daily volumes (coins' twenty days), and `pe` reads each
    company's trailing P/E from its key statistics (2026-09-19: the heatmap's
    Market cap, Avg vol and P/E tabs had been empty for every symbol since
    the Yahoo quote that carried them went, #71).
    """
    from alphadesk.providers import get_prices
    wanted, seen = [], set()
    for raw in symbols.split(","):
        sym = "".join(c for c in raw.upper() if c.isalnum() or c in ".-^=")[:14]
        if sym and sym not in seen:
            seen.add(sym)
            wanted.append(sym)
    if not wanted:
        return {"quotes": {}}
    if len(wanted) > 50:
        raise HTTPException(400, "too many symbols (max 50)")
    router = get_prices()
    # A vendor with a batch call answers the whole basket in one request;
    # symbols it has no price for are asked of the user's next vendors one
    # at a time. The router is resolved here, on the request, because the
    # worker threads below do not inherit the request's identity.
    got: dict = {}
    try:
        got = dict(router.ask("quotes", wanted))
    except NeedsKey:
        got = {}
    missing = [s for s in wanted if not got.get(s)]

    def one(sym: str):
        try:
            return sym, router.get("quote", sym)
        except Exception:
            return sym, None      # one bad symbol must not empty the basket

    if missing:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=_QUOTES_CONCURRENCY) as pool:
            got.update(dict(pool.map(one, missing)))
        if not any(got.values()):
            router.ask("quote", wanted[0])      # nothing at all: say which key would fill it
    wants = {w.strip().lower() for w in fill.split(",") if w.strip()}
    if wants:
        _fill_quote_gaps(router, got, wants)
    # Rebuilt in the ORDER ASKED, so the caller can render straight down its
    # own list without re-sorting a map whose iteration order it did not choose.
    return {"quotes": {sym: got.get(sym) for sym in wanted}}


#: A year of sessions, for the 52-week range.
_YEAR_SESSIONS = 253


def _fill_quote_gaps(router, quotes: dict, wants: set[str]) -> None:
    """Fill the fields the quote vendor left empty, in one request each for
    the whole basket. Only the symbols actually missing a field are asked
    for, and a vendor that cannot answer leaves them as they were."""
    from alphadesk.ingest.prices import week52_from_bars
    if "range" in wants:
        need = [s for s, q in quotes.items()
                if q and (q.get("week52_high") is None or q.get("week52_low") is None)]
        if need:
            try:
                bars = router.get("daily_history", need, _YEAR_SESSIONS) or {}
            except Exception:                      # no bar vendor: the column stays empty
                bars = {}
            for sym, rows in bars.items():
                lo, hi = week52_from_bars(rows or [])
                q = quotes.get(sym)
                if q and lo is not None and hi is not None:
                    q.setdefault("week52_low", None)
                    q.setdefault("week52_high", None)
                    if q["week52_low"] is None:
                        q["week52_low"] = lo
                    if q["week52_high"] is None:
                        q["week52_high"] = hi
    if "cap" in wants:
        need = [s for s, q in quotes.items() if q and q.get("market_cap") is None]
        if need:
            try:
                caps = router.get("market_caps", need) or {}
            except Exception:
                caps = {}
            for sym, cap in caps.items():
                q = quotes.get(sym)
                if q and cap:
                    q["market_cap"] = cap
    if "avgvol" in wants:
        from alphadesk.providers.alpaca import coin_pair
        need = [s for s, q in quotes.items() if q and q.get("avg_volume") is None]
        coins = [s for s in need if coin_pair(s)]
        stocks = [s for s in need if not coin_pair(s)]
        bars: dict = {}
        for method, syms in (("daily_history", stocks), ("crypto_daily_history", coins)):
            if syms:
                try:
                    bars.update(router.get(method, syms, 21) or {})
                except Exception:                  # no bar vendor: the tab stays empty
                    pass
        for sym, rows in bars.items():
            vols = [r.get("volume") for r in (rows or [])[-20:] if r.get("volume") is not None]
            q = quotes.get(sym)
            if q and vols:
                q["avg_volume"] = sum(vols) / len(vols)
    if "pe" in wants:
        # A coin has no earnings; only companies (and whatever a vendor
        # reports for a fund) are asked, four at a time, each a cached
        # key-statistics call.
        from concurrent.futures import ThreadPoolExecutor
        from alphadesk.providers.alpaca import coin_pair
        need = [s for s, q in quotes.items() if q and q.get("pe_trailing") is None and not coin_pair(s)]

        def pe(sym: str):
            try:
                ks = router.get("key_stats", sym) or {}
            except Exception:
                return sym, None
            v = ks.get("trailing_pe") if ks.get("trailing_pe") is not None else ks.get("pe")
            return sym, v
        if need:
            with ThreadPoolExecutor(max_workers=_QUOTES_CONCURRENCY) as pool:
                for sym, v in pool.map(pe, need):
                    if v is not None and quotes.get(sym):
                        quotes[sym]["pe_trailing"] = v


def _clean_symbol(raw: str) -> str:
    return "".join(c for c in raw.upper() if c.isalnum() or c in ".-^=")[:14]


@app.get("/api/options/{symbol}")
def api_option_expirations(symbol: str):
    """Upcoming expiries for one underlying."""
    from alphadesk.providers import get_prices
    sym = _clean_symbol(symbol)
    if not sym:
        raise HTTPException(400, "bad symbol")
    vendor = get_prices().vendor_for("options", "option_expirations")
    return {"symbol": sym, "expirations": vendor.option_expirations(sym) or [], "vendor": vendor.name}


@app.get("/api/options/{symbol}/chain")
def api_option_chain(symbol: str, expiry: str = ""):
    """One expiry's chain. `expiry` is required — a chain without one is every
    strike of every expiry at once, which is thousands of rows and answers no
    question anyone asked."""
    from alphadesk.providers import get_prices
    sym = _clean_symbol(symbol)
    exp = "".join(c for c in expiry if c.isdigit() or c == "-")[:10]
    if not sym:
        raise HTTPException(400, "bad symbol")
    if len(exp) != 10:
        raise HTTPException(400, "expiry must be YYYY-MM-DD")
    # The chain comes from the same vendor the expiries did.
    return get_prices().vendor_for("options", "option_chain").option_chain(sym, exp) or {"symbol": sym, "expiry": exp, "calls": [], "puts": []}


@app.get("/api/options-flow")
def api_option_flow(symbols: str = "", min_premium: float = 25_000.0):
    """The day's big orders on the most active contracts of up to eight
    underlyings (the board's chips), newest first (ingest/options_flow.py).
    Poll it: each call reads the trades since the last, and an order seen
    within seconds of its quote gets its side (at the ask, the bid or
    between); earlier orders keep an unknown side."""
    from alphadesk.ingest import options_flow
    from alphadesk.providers import get_prices
    syms = [s for s in (_clean_symbol(x) for x in symbols.split(",")) if s]
    if not syms:
        raise HTTPException(400, "symbols required")
    router = get_prices()
    vendor = router.vendor_for("options", "option_trades")
    return options_flow.flow(vendor, router.owner, syms, max(0.0, min(min_premium, 10_000_000.0)))


@app.get("/api/insider/{symbol}")
def api_insider(symbol: str):
    """Recent SEC Form 4 SHARE trades for one symbol, newest first — parsed
    from EDGAR directly (ingest/insider.py; derivative rows excluded there).
    Cached upstream; an empty list is the honest answer for a name with no
    recent activity or a source hiccup."""
    from alphadesk.ingest import insider
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return {"symbol": sym, "trades": insider.get_insider_trades(sym) or []}


@app.get("/api/ownership/{symbol}")
def api_ownership(symbol: str):
    """The largest institutional holders of one symbol, from the user's own
    vendor that carries ownership (ingest/ownership.py); the key prompt
    when none does."""
    from alphadesk.ingest import ownership
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return ownership.top_holders(sym)


@app.get("/api/institutional/{symbol}")
def api_institutional(symbol: str, limit: int = Query(25, ge=1, le=100)):
    """Institutional ownership of one symbol from the user's own vendor that
    carries it (ingest/ownership.py): the filers with their shares and
    changes, and any summary the vendor reports. A figure the vendor does
    not report is absent, never estimated."""
    from alphadesk.ingest import ownership
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return ownership.institutional_holdings(sym, limit)


@app.get("/api/analysts/{symbol}")
def api_analysts(symbol: str):
    """The sell side on one symbol (ingest/analysts.py): the target range
    with the current price, the rating distribution by month, the recent
    upgrades and downgrades with each firm's target move, and the
    short-interest report. Null when the record carries none of it."""
    from alphadesk.ingest import analysts
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return analysts.analyst_view(sym)


@app.get("/api/economic")
def api_economic(start: str = Query("", max_length=10), end: str = Query("", max_length=10)):
    """Scheduled economic releases for a window (ingest/economic.py), from
    the reader's or operator's keyed price provider. Without a source the
    rows are empty and `note` names the key that would fill them."""
    from alphadesk.ingest import economic
    try:
        return economic.calendar(start or None, end or None)
    except ValueError:
        raise HTTPException(400, "start and end are ISO dates")


@app.get("/api/calendars/{kind}")
def api_corporate_calendar(kind: str, start: str = Query("", max_length=10), end: str = Query("", max_length=10)):
    """Market-wide dividends, stock splits or IPOs for a window
    (ingest/corporate_calendars.py), from the reader's vendor that carries
    them; 428 with the key prompt when none does."""
    from alphadesk.ingest import corporate_calendars as cc
    build = {"dividends": cc.dividends, "splits": cc.splits, "ipos": cc.ipos}.get(kind)
    if build is None:
        raise HTTPException(404, "calendar must be dividends, splits or ipos")
    try:
        return build(start or None, end or None)
    except ValueError:
        raise HTTPException(400, "start and end are ISO dates")


@app.get("/api/stats/{symbol}")
def api_key_stats(symbol: str):
    """The summary block for one symbol (ingest/keystats.py): price ranges
    and averages, size and float, multiples, EPS, dividend, holders, the
    next dates. Null for a symbol the record does not know."""
    from alphadesk.ingest import keystats
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return keystats.key_stats(sym)


@app.get("/api/fund/{symbol}")
def api_fund(symbol: str):
    """What an ETF or mutual fund holds (ingest/funds.py): category,
    family, expense ratio, net assets, the asset-class split, sector
    weights and the largest positions. Null for anything that is not a
    fund, so a page can decide whether to show the fund panels."""
    from alphadesk.ingest import funds
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return funds.fund_profile(sym)


@app.get("/api/funds/related/{symbol}")
def api_related_funds(symbol: str):
    """The funds built ON one company (ingest/related_funds.py): the
    leveraged and inverse single-stock products, the option-income and
    buffered ones, each priced. NOT the funds that hold the stock — no
    vendor a reader here can reach carries per-stock exposure."""
    from alphadesk.ingest import related_funds
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return related_funds.related_funds(sym)


@app.get("/api/compare/metrics")
def api_compare_metrics(symbols: str = Query("", max_length=200)):
    """Comparison analysis: valuation, profitability, growth, balance-sheet
    and trading figures for each symbol asked, from the company record
    (ingest/compare.py). `missing` names the ones with no record."""
    from alphadesk.ingest import compare
    wanted = ["".join(c for c in s.upper() if c.isalnum() or c in ".-^=")[:14] for s in symbols.split(",")]
    wanted = [w for w in wanted if w]
    if not wanted:
        raise HTTPException(400, "symbols is required")
    return compare.compare(wanted)


@app.get("/api/peers/{symbol}")
def api_peers(symbol: str):
    """A company's peers from Finnhub's free endpoint when its key is set;
    an empty list with a null source otherwise — never a sector guess."""
    from alphadesk.ingest import compare
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return compare.peers(sym)


@app.get("/api/corporate-actions/{symbol}")
def api_corporate_actions(symbol: str):
    """Dividends and splits on record for one symbol, newest first, with
    the declaration/record/payment dates filled from a keyed source when
    the reader's price source carries only the ex-date (ingest/
    corporate_actions.py). Empty lists when nothing is known — a symbol
    that has never paid is a fact, not an error."""
    from alphadesk.ingest import corporate_actions
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return corporate_actions.corporate_actions(sym)


@app.get("/api/themes")
def api_themes():
    """The curated baskets and the reader's own (2026-09-18, marked `mine`),
    with their members. Pure read — no prices, no ordering, no scoring. The
    page prices the members through /api/quotes, one batched request."""
    from alphadesk.config import THEMES
    from alphadesk.identity import request_user
    uid = request_user()
    return {"themes": [*THEMES, *(store.list_user_baskets(uid) if uid else [])]}


@app.get("/api/indices")
def api_indices():
    """The cross-asset board: indices, rates, commodities, FX. Wider than
    /api/tape on purpose — see INDEX_BOARD in config."""
    from alphadesk.providers import get_prices
    return {"indices": get_prices().ask("index_board")}


@app.get("/api/crypto")
def api_crypto(top: int = 20):
    """{all, most_active, gainers, losers} for crypto, on a rolling 24h."""
    from alphadesk.providers import get_prices
    return get_prices().ask("crypto_movers", top=max(1, min(top, 50)))


@app.get("/api/widgets/external")
def api_external_widgets():
    """The declarative external tiles this deployment is configured with.

    Empty list when ALPHADESK_WIDGET_BACKENDS is unset — the common case, and
    the frontend renders nothing for it. See alphadesk/extwidgets.py for the
    contract and docs/widgets.md for how to write a backend."""
    from alphadesk import extwidgets
    return {"widgets": extwidgets.list_widgets()}


@app.get("/api/widgets/external/data")
def api_external_widget_data(uid: str, symbol: str | None = None):
    """One external tile's data, fetched through the server so the browser
    never talks to the widget backend directly (no CORS surface, and the
    cleaning in extwidgets.py always runs). Only uids a current descriptor
    claims are reachable — this is not a proxy."""
    from alphadesk import extwidgets
    try:
        return extwidgets.fetch_data(uid, symbol)
    except LookupError:
        raise HTTPException(404, f"no external widget {uid!r}")
    except Exception as exc:
        # The backend is down or served junk: one tile degrades, with the
        # reason, and the rest of the board is untouched.
        raise HTTPException(502, f"widget backend failed: {exc}")


class KeyIn(BaseModel):
    provider: str
    api_key: str
    api_secret: str | None = None   # news seam only: Alpaca auths with a pair
    base_url: str | None = None
    model: str | None = None


def _key_user(request: Request) -> str:
    """The signed-in reader a /api/keys call acts for. The vault is
    meaningless without an account, so an anonymous call is refused even on
    an instance that runs with auth off."""
    from alphadesk.app import auth
    claims = auth.current_user(request)
    if (claims is None or not claims.get("uid")) and not auth.auth_required():
        return _local_uid()
    if claims is None or not claims.get("uid"):
        raise HTTPException(401, "sign in to manage keys")
    return claims["uid"]


@app.get("/api/keys")
def api_keys_list(request: Request):
    """The reader's stored keys — hints only, never the keys. `vault` says
    whether the instance can store keys at all, so the UI states the truth
    ('the operator has not enabled the vault') instead of failing a save."""
    from alphadesk.ledger import vault
    user_id = _key_user(request)
    keys = store.list_user_keys(user_id)
    # What each news feed actually delivered in the last day — a connected
    # feed that brings nothing into the window says so on the Account page.
    if any(k["seam"] == "news" for k in keys):
        from datetime import datetime, timedelta, timezone
        counts = store.feed_counts(user_id, (datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
        from alphadesk.ingest.stream import STREAMING_NEWS
        for k in keys:
            if k["seam"] == "news":
                k["stories_24h"] = counts.get(k["provider"], 0)
                # How its stories arrive: over a held socket in seconds, or on
                # the poll. The page says so per feed (2026-09-18).
                k["delivery"] = "stream" if k["provider"] in STREAMING_NEWS else "poll"
    from alphadesk.config import NEWS_REFRESH_MINUTES
    return {"vault": vault.enabled(), "keys": keys, "news_poll_minutes": NEWS_REFRESH_MINUTES}


@app.get("/api/data/vendors")
def api_data_vendors(request: Request):
    """The market-data vendors a user can connect, what each one's key
    covers, and which surfaces each serves at which plan tier — the Account
    page's list and the source of every panel's key prompt. Carries no key
    material; `connected` is the user's own vendor names."""
    from dataclasses import asdict
    from alphadesk.providers import catalogue, registry
    uid = registry._request_uid()
    connected = sorted({r["provider"] for r in store.get_user_keys(uid, "prices")}) if uid else []
    serves: dict[str, list[dict]] = {}
    for s in catalogue.SURFACES.values():
        for name, tier in s.vendors:
            serves.setdefault(name, []).append({"surface": s.id, "label": s.label, "tier": tier})
    # What the connected Alpaca key's plan delivers — real-time or delayed —
    # so the Account page can say it rather than leave the reader to notice.
    plans: dict[str, dict] = {}
    if "alpaca" in connected:
        try:
            vendor = registry.get_prices().vendors.get("alpaca")
            plans["alpaca"] = getattr(vendor, "_inner", vendor).plan()
        except Exception:                         # the list still renders without it
            pass
    return {"connected": connected,
            "vendors": [{**asdict(v), "serves": serves.get(v.name, []), "plan": plans.get(v.name)}
                        for v in catalogue.VENDORS.values()]}


@app.put("/api/sources/{name}")
def api_source_enable(name: str, request: Request):
    """Switch on a SCRAPED source (2026-09-22). There is no key to paste, so
    the Account page offers a button and this stores the same kind of row a
    key does with an empty credential — which is what makes switching one off
    identical to removing a key, purge and all.

    It is stored on the prices seam like any market-data vendor, so the
    router picks it up on the reader's next request; the catalogue lists it
    against no surface, so every vendor they keyed is still asked first."""
    from alphadesk.ledger import vault
    from alphadesk.providers import registry
    from alphadesk.providers.scraped import SCRAPED_SOURCES
    user_id = _key_user(request)
    if name not in SCRAPED_SOURCES:
        raise HTTPException(404, f"{name!r} is not a scraped source")
    if not vault.enabled():
        raise HTTPException(503, "the key vault is not enabled on this instance"
                                 " (ALPHADESK_VAULT_KEY is not set)")
    store.set_user_key(user_id, "prices", name,
                       vault.encrypt({"api_key": "", "api_secret": "", "base_url": "", "model": ""}),
                       "")
    registry.forget_user_keys(user_id)
    return {"ok": True, "seam": "prices", "provider": name, "official": False}


@app.put("/api/keys/{seam}")
def api_keys_set(seam: str, body: KeyIn, request: Request):
    """Store (or replace) the reader's key for one seam. The plaintext exists
    for the duration of this handler — sealed before the store sees it, and
    only the hint ever comes back."""
    from alphadesk.ledger import vault
    from alphadesk.providers import registry
    user_id = _key_user(request)
    if seam == "crypto":
        seam = "prices"      # CoinGecko is a market-data vendor since 2026-09-13
    if seam not in ("news", "prices", "transcripts"):
        raise HTTPException(422, "seam must be 'news', 'prices' or 'transcripts'")
    if not vault.enabled():
        raise HTTPException(503, "the key vault is not enabled on this instance"
                                 " (ALPHADESK_VAULT_KEY is not set)")
    kind: registry.Kind = seam  # the seam names ARE the registry kinds
    if body.provider not in registry.available(kind)[kind]:
        raise HTTPException(422, f"{body.provider!r} is not a registered {kind} provider")
    api_key = body.api_key.strip()
    if len(api_key) < 8:
        raise HTTPException(422, "that doesn't look like an API key")
    if seam == "prices":
        # Refuse now, not on every chart later: a prices provider that cannot
        # take per-user config must
        # bounce at the door with a message, not serve hard errors per call.
        from alphadesk.providers.base import ProviderError
        try:
            registry.build("prices", body.provider, api_key=api_key,
                           api_secret=(body.api_secret or "").strip() or None)
        except ProviderError as exc:
            raise HTTPException(422, str(exc)) from exc
    sealed = vault.encrypt({"api_key": api_key,
                            "api_secret": (body.api_secret or "").strip(),
                            "base_url": (body.base_url or "").strip(),
                            "model": (body.model or "").strip()})
    store.set_user_key(user_id, seam, body.provider, sealed, api_key[-4:])
    registry.forget_user_keys(user_id)
    # A replaced key must serve the very next ask: the per-user LRU keys on
    # created_at, which the upsert refreshed, so no explicit invalidation.
    return {"ok": True, "seam": seam, "provider": body.provider, "key_hint": api_key[-4:]}


@app.delete("/api/keys/{seam}/{provider}")
def api_keys_delete_provider(seam: str, provider: str, request: Request):
    """Drop ONE feed's key. News keys accumulate per provider, so removal
    must address one without taking the others."""
    from alphadesk.providers import registry
    user_id = _key_user(request)
    if seam == "crypto":
        seam = "prices"
    if not store.delete_user_key(user_id, seam, provider):
        raise HTTPException(404, "no key stored for that provider")
    registry.forget_user_keys(user_id)
    _purge_after_key_removal(user_id, seam, provider)
    return {"ok": True}


@app.delete("/api/keys/{seam}")
def api_keys_delete(seam: str, request: Request):
    from alphadesk.providers import registry
    user_id = _key_user(request)
    if not store.delete_user_key(user_id, seam):
        raise HTTPException(404, "no key stored for that seam")
    registry.forget_user_keys(user_id)
    _purge_after_key_removal(user_id, seam, None)
    return {"ok": True}


def _purge_after_key_removal(user_id: str, seam: str, provider: str | None) -> None:
    """A removed key's data goes with it (store.purge_vendor_data): vendors
    require deletion when the customer's access ends, and removing the key is
    where AlphaDesk sees that."""
    import logging

    from alphadesk.ingest.news import news_owner
    log = logging.getLogger(__name__)
    owner = news_owner(user_id) if seam == "news" else user_id
    try:
        gone = store.purge_vendor_data(owner, seam, provider)
        if any(gone.values()):
            log.info("key removed: purged %s for reader %s", gone, user_id[:8])
    except Exception as exc:  # noqa: BLE001 — the key is already gone; a failed purge is retried by the hourly prune
        log.warning("purge after key removal failed: %s", exc)


class ViewIn(BaseModel):
    name: str
    layout: str = ""
    position: int = 0


#: A layout's page key: the layout hook's own, including a view's
#: "view:<id>" form.
_LAYOUT_PAGE = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,63}$")
_VIEW_ID = re.compile(r"^[a-z0-9-]{4,40}$")


class LayoutIn(BaseModel):
    tiles: str = ""


@app.get("/api/layouts")
def api_layouts_get(request: Request):
    """Every board this reader has arranged, as {page key: tiles} — what a
    browser that has never seen them seeds itself from (2026-09-21). The
    strip's symbols follow the account through /api/board; this is the rest
    of the board."""
    return {"layouts": store.user_layouts(_key_user(request))}


@app.put("/api/layouts/{page}")
def api_layouts_set(page: str, body: LayoutIn, request: Request):
    """Keep one page's layout. An EMPTY string forgets it rather than storing
    it: empty means "the page's default", and pinning that would freeze the
    board as the defaults stood on the day it was saved, so a tile added to
    the product later would never appear on it."""
    if not _LAYOUT_PAGE.match(page):
        raise HTTPException(422, "bad page key")
    store.set_user_layout(_key_user(request), page, body.tiles.strip()[:2000])
    return {"ok": True}


@app.get("/api/views")
def api_views_list(request: Request):
    """The signed-in reader's saved views — name plus the board's `id:span`
    layout string, the same form ?tiles= carries. The browser keeps a working
    copy; this is the durable one that follows the account."""
    return {"views": store.list_user_views(_key_user(request))}


@app.put("/api/views/{view_id}")
def api_views_set(view_id: str, body: ViewIn, request: Request):
    user_id = _key_user(request)
    if not _VIEW_ID.match(view_id):
        raise HTTPException(422, "bad view id")
    name = body.name.strip()[:60]
    if not name:
        raise HTTPException(422, "a view needs a name")
    if len(body.layout) > 2000:
        raise HTTPException(422, "layout too large")
    store.upsert_user_view(user_id, view_id, name, body.layout, body.position)
    return {"ok": True}


class BasketIn(BaseModel):
    label: str
    why: str = ""
    symbols: list[str] | str


#: A reader's basket ids are prefixed, so one can never shadow a curated one.
_BASKET_ID = re.compile(r"^my-[a-z0-9-]{2,40}$")
#: The alphabet the rest of the app accepts for a symbol, plus "/" for a pair.
_BASKET_SYMBOL = re.compile(r"^[A-Z0-9.^=/\-]{1,14}$")
_BASKETS_MAX, _BASKET_SYMBOLS_MAX = 50, 40


def basket_symbols(raw: list[str] | str) -> list[str]:
    """Tickers as typed — a list, or one string split on commas and spaces —
    upper-cased, each once, in the order given, anything that is not a symbol
    dropped. Nothing is looked up: a crypto pair or a fund the SEC list does
    not carry is still a fine member."""
    parts = raw.replace(",", " ").split() if isinstance(raw, str) else [str(x) for x in raw]
    out: list[str] = []
    for p in parts:
        s = p.strip().upper().lstrip("$")
        if s and _BASKET_SYMBOL.match(s) and s not in out:
            out.append(s)
    return out


@app.put("/api/baskets/{basket_id}")
def api_basket_set(basket_id: str, body: BasketIn, request: Request):
    """Create or replace one of the reader's own baskets (2026-09-18)."""
    user_id = _key_user(request)
    if not _BASKET_ID.match(basket_id):
        raise HTTPException(422, "bad basket id")
    label = body.label.strip()[:60]
    if not label:
        raise HTTPException(422, "a basket needs a name")
    symbols = basket_symbols(body.symbols)
    if not symbols:
        raise HTTPException(422, "a basket needs at least one ticker")
    if len(symbols) > _BASKET_SYMBOLS_MAX:
        raise HTTPException(422, f"a basket holds at most {_BASKET_SYMBOLS_MAX} tickers")
    mine = store.list_user_baskets(user_id)
    if len(mine) >= _BASKETS_MAX and all(b["id"] != basket_id for b in mine):
        raise HTTPException(422, f"at most {_BASKETS_MAX} baskets")
    store.upsert_user_basket(user_id, basket_id, label, body.why.strip()[:300], symbols)
    return {"ok": True, "id": basket_id, "symbols": symbols}


@app.delete("/api/baskets/{basket_id}")
def api_basket_delete(basket_id: str, request: Request):
    if not store.delete_user_basket(_key_user(request), basket_id):
        raise HTTPException(404, "no such basket")
    return {"ok": True}


@app.delete("/api/views/{view_id}")
def api_views_delete(view_id: str, request: Request):
    if not store.delete_user_view(_key_user(request), view_id):
        raise HTTPException(404, "no such view")
    return {"ok": True}


# prefs, and prefs:1..3 for the workspace's other grid cells; the grid itself,
# the saved layouts and the indicator templates; drawings per symbol.
# Drawings are NOT a key (2026-09-18): they live for one visit to /chart and
# are never saved, so a line drawn and forgotten does not come back.
_CHART_KEY = re.compile(r"^(prefs(:[1-3])?|layout|layouts|templates)$")


class ChartStateIn(BaseModel):
    state: dict | list


@app.get("/api/chart/state/{key}")
def api_chart_state_get(key: str, request: Request):
    """The reader's chart state — 'prefs' (the reading setup), the
    workspace's cells, layouts and templates. Null when nothing is saved."""
    user_id = _key_user(request)
    if not _CHART_KEY.match(key):
        raise HTTPException(422, "bad chart-state key")
    raw = store.get_chart_state(user_id, key)
    try:
        return {"key": key, "state": json.loads(raw) if raw else None}
    except (TypeError, ValueError):
        return {"key": key, "state": None}


@app.put("/api/chart/state/{key}")
def api_chart_state_set(key: str, body: ChartStateIn, request: Request):
    user_id = _key_user(request)
    if not _CHART_KEY.match(key):
        raise HTTPException(422, "bad chart-state key")
    raw = json.dumps(body.state)
    if len(raw) > 100_000:
        raise HTTPException(422, "chart state too large")
    store.set_chart_state(user_id, key, raw)
    return {"ok": True}


@app.delete("/api/chart/state/{key}")
def api_chart_state_delete(key: str, request: Request):
    if not store.delete_chart_state(_key_user(request), key):
        raise HTTPException(404, "nothing saved under that key")
    return {"ok": True}


def _reader_news_health() -> dict:
    from alphadesk.identity import request_user
    from alphadesk.ingest.news import news_owner
    return store.news_health(news_owner(request_user()))


@app.get("/api/system")
def api_system():
    """What the reader's screens need to know about the terminal: the market
    session, how fresh THEIR news is, and which news feeds can be connected.

    Reader-scoped since 2026-09-18 (the owner's call before going live). It
    used to carry the operator's view too — server uptime, EDGAR's rate-limit
    pause, the plugin seams, and a count of every reader's live price
    connections and watched symbols — which every signed-in reader could read
    and the System health page printed. That page is gone; none of that is
    a reader's business."""
    from alphadesk.config import session as market_session
    from alphadesk.providers import available
    return {
        "market": market_session(),
        # The reader's own feed: there is no shared feed to report on.
        "news": _reader_news_health(),
        # The feeds a reader can connect, for the Account page's list.
        "providers": {"available": available()},
    }


@app.get("/api/earnings")
def api_earnings():
    """Be-ready view: who reports next (with the time to RUN the desk to catch the
    drift) and who just reported."""
    from datetime import timedelta

    from alphadesk.config import now_et
    from alphadesk.ingest.earnings import reported_public, run_at

    # Time-aware split: a report is "just reported" once it's PUBLIC (BMO/DAY at the
    # 9:30 open, AMC at the 16:00 close of its report day) — not when Nasdaq happens
    # to backfill the actual EPS. So a name reporting today flips after 9:30 today.
    now = now_et()
    upcoming, reported = [], []
    from alphadesk.ingest import earnings_calendar
    window = earnings_calendar.rows_between((now.date() - timedelta(days=4)).isoformat(),
                                            (now.date() + timedelta(days=14)).isoformat())
    # A symbol whose report is OUT — an actual EPS on any row in the window —
    # is never "reporting soon" on a sibling row: a stale projected date
    # next to a filled one read as a report still to come (2026-09-11).
    out_already = {e["symbol"] for e in window
                   if e.get("eps_actual") is not None or e.get("released_at") or e.get("released_on")}
    today = now.date().isoformat()
    # The be-ready horizon is one week: a projected date two weeks out on a
    # calendar that guesses from last year is not something to be ready for.
    horizon = (now.date() + timedelta(days=7)).isoformat()
    for e in window:
        pub = reported_public(e["report_date"])
        e["public_at"] = pub.isoformat() if pub else None   # when the report becomes tradeable (BMO/DAY 4:00, AMC 16:00 ET)
        released = e.get("eps_actual") is not None or bool(e.get("released_at") or e.get("released_on"))
        if released or (pub is not None and now >= pub):
            # Released is released, whatever date the calendar put on it.
            reported.append(e)
        elif e["symbol"] in out_already and e["report_date"] >= today:
            continue                                     # a stale sibling of a report already out
        elif e["report_date"] > horizon:
            continue                                     # too far out to be "soon"
        else:
            e["run_at"] = run_at(e["report_date"], e.get("session"))
            upcoming.append(e)
    # newest report first, then group by report-day in the UI (biggest names first)
    # reverse=True → newest report day first AND biggest market cap first within a
    # day (a plain cap here, NOT -cap: reverse already flips it to descending).
    reported.sort(key=lambda e: (e["report_date"], e.get("market_cap") or 0.0), reverse=True)

    # Collapse dual-class listings of the same company (identical report date +
    # market cap to the dollar, e.g. GOOG/GOOGL) to one row. Two different firms
    # never share a 13-digit cap exactly, so this only merges share classes.
    def _dedupe_dual(rows: list[dict]) -> list[dict]:
        seen: set = set()
        out = []
        for e in rows:
            mc = e.get("market_cap")
            if mc:
                key = (e["report_date"], mc)
                if key in seen:
                    continue
                seen.add(key)
            out.append(e)
        return out

    # Sort so the UI can group by run-day (earliest to run first) with the biggest
    # names surfaced first inside each day — never truncated by earlier small-caps.
    upcoming.sort(key=lambda e: (e["run_at"] or "9999", -(e.get("market_cap") or 0.0)))
    upcoming = _dedupe_dual(upcoming)
    reported = _dedupe_dual(reported)
    # Post-report drift is NOT reported here. It came from earnings_reactions,
    # a table the retired trading engine wrote to grade its own reaction gate —
    # nothing populates it any more, so serving it would mean serving stale
    # numbers from a dead system. The calendar answers "who reports when"; what
    # a name did afterwards belongs on its chart.

    # Same liquidity bar the live trading pipeline actually gates entries on
    # (20-day avg $ volume, not market cap — a thin float can hide behind a
    # decent-looking company size), pre-computed off the earnings loop
    # (earnings.arm_liquidity) and already present on each row from
    # earnings_window() above. A live batch fetch for the whole window here
    # instead took over two minutes and made the page itself unusable — this
    # keeps that cost entirely off the request path.
    for e in upcoming + reported:
        v = e.get("low_liquidity")
        e["low_liquidity"] = bool(v) if v is not None else None

    return {"upcoming": upcoming, "reported": reported}


@app.get("/api/earnings/find")
def api_earnings_find(symbol: str):
    """One company's reports in the reader's calendar vendors, four months
    either side of today, and the date the calendar should jump to — the
    week view's symbol filter. 428 without a calendar vendor."""
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-")[:12]
    if not sym:
        raise HTTPException(400, "bad symbol")
    from alphadesk.ingest import earnings_calendar
    return earnings_calendar.find(sym)


@app.get("/api/earnings/accuracy")
def api_earnings_accuracy(request: Request, days: int = Query(30, ge=1, le=120)):
    """How right the reader's calendar vendors were a day, three days and a
    week ahead of each release in the last `days`, scored against EDGAR
    (ingest/calendar_accuracy.py). Empty until their calendar has been
    captured for a while."""
    from alphadesk.ingest import calendar_accuracy
    from alphadesk.providers import registry
    uid = registry._request_uid()
    if not uid:
        raise HTTPException(401, "sign in to see your calendar's accuracy")
    return calendar_accuracy.report(uid, days)


@app.get("/api/earnings/week")
def api_earnings_week(start: str | None = None):
    """One calendar week, day by day — the shape the Earnings page renders.

    `start` is any YYYY-MM-DD inside the wanted week; the week is normalised to
    the Sunday that contains it, so the caller can just pass "today" or step by
    seven days without doing calendar arithmetic itself. Omitted means this
    week.

    Every day is returned, including weekends and days with nothing on them —
    the strip across the top shows seven cells whatever the market did, and a
    missing day would silently shift the ones after it.
    """
    from datetime import date, timedelta

    from alphadesk.config import now_et

    try:
        anchor = date.fromisoformat(start) if start else now_et().date()
    except ValueError:
        raise HTTPException(400, "start must be YYYY-MM-DD") from None
    # Sunday-first, matching how the calendar is read: isoweekday() is Mon=1..Sun=7.
    sunday = anchor - timedelta(days=anchor.isoweekday() % 7)

    from alphadesk.ingest import earnings_calendar
    return earnings_calendar.week(sunday.isoformat())


@app.get("/api/earnings/context/{symbol}")
def api_earnings_context(symbol: str):
    """The company's reported record: the last four quarters' estimate/actual/
    surprise (report_history), the quarterly revenue and net-income trend, and
    the consensus for the next quarter. Everything here is a code-fetched fact
    — the EPS chart and the revenue bars draw straight from it."""
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    from alphadesk.ingest import earnings_record
    return earnings_record.context(sym)


@app.get("/api/transcripts/{symbol}")
def api_transcripts_list(symbol: str):
    """The earnings documents on record for one symbol from the selected
    transcript source: the company's filed results releases by default
    (`kind: release`), recorded calls when the reader keys a vendor
    (`kind: call`). Empty when the source has nothing."""
    from alphadesk.desk import transcripts
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    return transcripts.list_transcripts(sym)


@app.get("/api/transcripts/{symbol}/{id}")
def api_transcript(symbol: str, id: str):
    """One earnings document with its full text."""
    from alphadesk.desk import transcripts
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym or not id.strip():
        raise HTTPException(400, "bad symbol or id")
    doc = transcripts.get_transcript(sym, id.strip()[:64])
    if doc is None:
        raise HTTPException(404, "that document is not available from the transcript source")
    return doc


@app.get("/api/earnings/history/{symbol}")
def api_earnings_history(symbol: str):
    """Every report on record for one symbol — estimate, actual, surprise,
    the quarter's revenue — with the next scheduled report on top carrying
    its consensus estimates. Empty when the source has no record."""
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    from alphadesk.ingest import earnings_record
    return earnings_record.history(sym)


@app.get("/api/earnings/insights/{symbol}")
def api_earnings_consensus(symbol: str):
    """Analyst consensus across the four estimate periods — the insights
    panel. `periods` is empty when the provider covers none of them; the UI
    says so rather than drawing an empty grid."""
    from alphadesk.providers import get_prices
    sym = "".join(c for c in symbol.upper() if c.isalnum() or c in ".-^=")[:14]
    if not sym:
        raise HTTPException(400, "bad symbol")
    router = get_prices()
    return {**router.ask("earnings_insights", sym), "vendor": router.answered_by}


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    # CACHE POLICY (2026-09-11). The shell carried no Cache-Control, so the
    # browser kept it on the Last-Modified heuristic — for hours — and after
    # a deploy kept loading the OLD chunks it named (or failed to load the
    # ones that were gone: "Failed to fetch dynamically imported module").
    # The shell must be revalidated on every load (its ETag makes that a
    # 304 when nothing changed); the hashed assets under /assets are
    # immutable by name and may be cached for a year.
    if path:
        candidate = (_STATIC / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(_STATIC.resolve()):
            immutable = path.startswith("assets/")
            return FileResponse(candidate, headers={
                "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
    index = _STATIC / "index.html"
    if not index.is_file():
        return Response(
            "UI bundle missing — run `pnpm build` in alphadesk/ui", status_code=503
        )
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
