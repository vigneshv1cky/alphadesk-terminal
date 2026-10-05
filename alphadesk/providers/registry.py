"""Provider registration, discovery and selection.

Three ways a provider gets in, in increasing order of decoupling:

  1. **Built in** — the implementations shipped in this package.
  2. **`ALPHADESK_PLUGINS`** — a comma-separated list of module paths that get
     imported at startup. Importing is enough; the module registers itself.
     This is the escape hatch for a local one-file provider.
  3. **Entry points** — a package declaring `[project.entry-points."alphadesk.providers"]`
     is discovered automatically once installed. This is how a real
     third-party provider ships, with no config at all.

Which one RUNS is the signed-in user's choice (2026-09-13): each vendor is
built from that user's vaulted key with `build`, and the server selects
nothing from its environment. Market data goes through `get_prices`, the
router over a user's connected vendors; the transcript seam falls back to
SEC EDGAR's filed releases, the one keyless source.
"""

from __future__ import annotations

import functools
import importlib
import logging
import os
import threading
import time
from typing import Any, Callable, Literal

from alphadesk.providers.base import EntitlementError, NeedsKey, ProviderError

log = logging.getLogger("alphadesk.providers")

Kind = Literal["news", "prices", "transcripts"]

# kind -> name -> zero-arg factory. Factories, not instances: constructing a
# provider may read config or open a client, and that should not happen at
# import time for providers nobody selected.
_REGISTRY: dict[str, dict[str, Callable[[], Any]]] = {"news": {}, "prices": {}, "transcripts": {}}
_ENTRY_POINT_GROUP = "alphadesk.providers"
_loaded = False


def register(kind: Kind, name: str, factory: Callable[[], Any]) -> None:
    """Register a provider factory under `name`.

    Re-registering an existing name replaces it, which is what lets a fork or
    a local plugin override a built-in without patching this file.
    """
    if kind not in _REGISTRY:
        raise ValueError(f"unknown provider kind {kind!r}; expected one of {list(_REGISTRY)}")
    if name in _REGISTRY[kind]:
        log.info("provider %s/%s replaced", kind, name)
    _REGISTRY[kind][name] = factory


def _load_once() -> None:
    """Import built-ins, then env-listed modules, then installed entry points."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    from alphadesk.providers import builtin  # noqa: F401  (registers on import)

    for mod in (m.strip() for m in os.environ.get("ALPHADESK_PLUGINS", "").split(",")):
        if not mod:
            continue
        try:
            importlib.import_module(mod)
            log.info("loaded plugin module %s", mod)
        except Exception as exc:                      # a bad plugin must not kill boot
            log.error("plugin %s failed to import: %s", mod, exc)

    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group=_ENTRY_POINT_GROUP):
            try:
                ep.load()
                log.info("loaded provider entry point %s", ep.name)
            except Exception as exc:
                log.error("entry point %s failed: %s", ep.name, exc)
    except Exception as exc:                          # pragma: no cover
        log.debug("entry point discovery unavailable: %s", exc)


def available(kind: Kind | None = None) -> dict[str, list[str]]:
    """What's registered. Surfaced at /api/system so the terminal can show
    which providers a deployment actually has."""
    _load_once()
    kinds = [kind] if kind else list(_REGISTRY)
    return {k: sorted(_REGISTRY[k]) for k in kinds}


def build(kind: Kind, name: str, **config: Any) -> Any:
    """Construct a provider from EXPLICIT config instead of the environment —
    the key vault's path: each signed-in reader's key builds their own
    instance. The registered factory must accept the config as keyword
    arguments (the built-in LLM providers take api_key/base_url/model); one
    that doesn't is reported as such rather than as a crash."""
    _load_once()
    impls = _REGISTRY[kind]
    if name not in impls:
        raise ProviderError(
            f"{name!r} is not a registered {kind} provider. Available: "
            f"{sorted(impls) or '(none)'}.")
    try:
        return impls[name](**config)
    except TypeError as exc:
        raise ProviderError(
            f"{kind} provider {name!r} does not accept per-user config: {exc}") from exc


# The signed-in reader's market-data key rows, cached briefly: charts and
# quotes poll every few seconds, and a ledger read per price call would be
# most of the request. 30s staleness on add/replace/delete is the same trade
# the session cache makes; the key routes clear a user's entry on write.
_PRICES_ROW_TTL_S = 30.0
_prices_rows: dict[str, tuple[float, list[dict]]] = {}


def _request_uid() -> str | None:
    """The identity the middleware stamped for this request, if any. Lazy
    import."""
    try:
        from alphadesk.identity import request_user
        return request_user()
    except Exception:                                  # pragma: no cover
        return None


def _user_prices_rows(uid: str) -> list[dict]:
    """Every market-data vendor the user connected (one row per vendor)."""
    now = time.monotonic()
    hit = _prices_rows.get(uid)
    if hit and now - hit[0] < _PRICES_ROW_TTL_S:
        return hit[1]
    from alphadesk.ledger import store
    rows = store.get_user_keys(uid, "prices")
    if len(_prices_rows) > 4096:
        _prices_rows.clear()
    _prices_rows[uid] = (now, rows)
    return rows


def forget_user_keys(uid: str) -> None:
    """Drop the memoised key rows for one user — the key routes call this on
    every write so an added vendor serves the very next request."""
    _prices_rows.pop(uid, None)


# Per-method TTLs for a user's own price sources, mirroring the old module
# path's module caches: without them every chart poll would ride the
# user's key straight into their vendor's rate limit. The old builtin
# provider is NOT wrapped — ingest/prices.py already caches internally.
_METHOD_TTL_S: dict[str, float] = {
    "chart_series": 30.0, "quote": 60.0, "context": 60.0, "movers": 60.0,
    "market_tape": 30.0, "index_board": 30.0, "fundamentals": 3600.0,
    "institutional_ownership": 3600.0, "earnings_context": 3600.0,
    "earnings_insights": 3600.0, "macro": 600.0, "sector_change_pct": 300.0,
    "option_expirations": 900.0, "option_chain": 900.0, "crypto_movers": 60.0,
    "category_movers": 30.0, "quotes": 20.0, "key_stats": 600.0, "compare_metrics": 3600.0,
    "peers": 86400.0, "analyst_ratings": 3600.0, "price_targets": 3600.0, "rating_changes": 3600.0,
    "short_interest": 3600.0, "fund_holdings": 21600.0, "corporate_actions": 21600.0,
    "earnings_history": 3600.0, "earnings_calendar": 900.0, "economic_calendar": 1800.0,
    "press_releases": 21600.0, "dividend_calendar": 1800.0, "split_calendar": 3600.0, "ipo_calendar": 1800.0, "market_caps": 3600.0,
    "company_profile": 86400.0, "option_movers": 120.0, "crypto_bars": 30.0, "daily_history": 900.0, "crypto_daily_history": 900.0, "fx_daily_history": 3600.0,
}
# KEPT ANSWERS (2026-10-03). The memo above forgets at every restart and re-asks
# the vendor every few minutes for answers that change daily. The methods below
# have a copy kept in the store: read back while younger than the number given
# (so a restart is warm and a quiet panel does not spend the reader's rate
# limit), and used however old it is when the vendor itself fails. Live
# answers — quotes, movers, the tape, option chains — are NOT kept: a stale
# price is worse than none.
_KEEP_FRESH_S: dict[str, float] = {
    "fundamentals": 21600.0, "key_stats": 3600.0, "company_profile": 604800.0, "peers": 604800.0,
    "analyst_ratings": 21600.0, "price_targets": 21600.0, "rating_changes": 21600.0,
    "short_interest": 21600.0, "fund_holdings": 43200.0, "corporate_actions": 43200.0,
    "earnings_history": 21600.0, "institutional_ownership": 21600.0, "compare_metrics": 21600.0,
    "earnings_context": 21600.0, "earnings_insights": 21600.0, "press_releases": 43200.0,
    "split_calendar": 7200.0, "dividend_calendar": 7200.0, "ipo_calendar": 7200.0, "market_caps": 7200.0,
    "macro": 3600.0, "earnings_calendar": 3600.0, "economic_calendar": 7200.0,
    "daily_history": 3600.0, "crypto_daily_history": 3600.0, "fx_daily_history": 10800.0,
}
_HISTORY_RANGES = {"1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"}
_DAILY_OR_LONGER = {"1d", "1wk", "1mo"}
_KEEP_STALE_S = 14 * 86400.0


def _keep_fresh_s(method: str, kwargs: dict) -> float | None:
    """How long a kept copy of this call counts as current, or None when it is
    not kept. A chart is kept only when it is history: a page before an instant
    never changes (a day), a daily-or-longer series changes once a day (an hour);
    the intraday tail is live and is not kept."""
    if method == "chart_series":
        if kwargs.get("before") is not None:
            return 86400.0
        if kwargs.get("interval") in _DAILY_OR_LONGER or kwargs.get("range_key") in _HISTORY_RANGES:
            return 3600.0
        return None
    return _KEEP_FRESH_S.get(method)


def _arg_key(method: str, args: tuple, kwargs: dict) -> str:
    import hashlib
    import json
    raw = json.dumps([method, args, sorted(kwargs.items())], default=str, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


#: How long an answer that says it is still filling in is held: the rest of
#: it lands within seconds, so it must not be held for the method's TTL.
_FILLING_TTL_S = 2.0
_CACHE_MAX_ENTRIES = 512
_CACHE_SWEEP_AT = 24
_REFUSAL_TTL_S = 3600.0


class _CachedPrices:
    """A TTL memo around one reader's price provider.

    One instance per keyed provider (built below under the LRU, so the cache
    ages out with the instance). Results — None included — are held for the
    method's TTL: a None from a partial provider is an answer, and re-asking
    every poll would spend the reader's rate limit relearning it. Exceptions
    are never cached; an unopenable key stays a loud, per-call error.
    Attributes outside the TTL table (name, api_key) pass straight through.
    """

    def __init__(self, inner: Any, owner: str = "", vendor: str = "") -> None:
        self._inner = inner
        self._memo: dict[tuple, tuple[float, float, Any]] = {}
        self._memo_lock = threading.Lock()
        self._owner, self._vendor = owner, vendor            # whose kept answers these are, and from whom
        self._flight: dict[tuple, threading.Lock] = {}       # one vendor call per identical request at a time

    # -- kept answers -------------------------------------------------------
    def _kept_get(self, attr: str, args: tuple, kwargs: dict) -> tuple[Any, float] | None:
        """(the kept answer, its age in seconds), or None."""
        if not (self._owner and self._vendor) or _keep_fresh_s(attr, kwargs) is None:
            return None
        try:
            import json
            from datetime import datetime, timezone

            from alphadesk.ledger import store
            got = store.vendor_cache_get(self._owner, self._vendor, attr, _arg_key(attr, args, kwargs))
            if got is None:
                return None
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(got[1])).total_seconds()
            return json.loads(got[0]), age
        except Exception as exc:                          # a kept copy is a convenience, never an error
            log.debug("kept answer for %s unreadable: %s", attr, exc)
            return None

    def _kept_put(self, attr: str, args: tuple, kwargs: dict, val: Any) -> None:
        if val is None or not (self._owner and self._vendor) or _keep_fresh_s(attr, kwargs) is None:
            return
        try:
            import json

            from alphadesk.ledger import store
            payload = json.dumps(val)
            if json.loads(payload) != val:                # tuples, sets, objects: not kept, rather than altered
                return
            store.vendor_cache_put(self._owner, self._vendor, attr, _arg_key(attr, args, kwargs), payload)
        except Exception as exc:
            log.debug("answer for %s not kept: %s", attr, exc)

    def __getattr__(self, attr: str) -> Any:
        target = getattr(self._inner, attr)
        ttl = _METHOD_TTL_S.get(attr)
        if ttl is None or not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            def _h(v: Any) -> Any:
                return tuple(_h(x) for x in v) if isinstance(v, (list, tuple)) else v
            key = (attr, _h(args), tuple(sorted((k, _h(v)) for k, v in kwargs.items())))
            now = time.monotonic()
            with self._memo_lock:
                hit = self._memo.get(key)
                if hit and now - hit[0] < hit[1]:
                    if isinstance(hit[2], EntitlementError):
                        raise hit[2]
                    return hit[2]
                if len(self._flight) > 1024:
                    self._flight.clear()
                flight = self._flight.setdefault(key, threading.Lock())
            # One vendor call per identical request at a time: a page and a
            # prewarm replay asking together shared nothing before, and both
            # rode the reader's rate limit (2026-10-03).
            with flight:
                with self._memo_lock:
                    hit = self._memo.get(key)
                    if hit and time.monotonic() - hit[0] < hit[1]:
                        if isinstance(hit[2], EntitlementError):
                            raise hit[2]
                        return hit[2]
                kept = self._kept_get(attr, args, kwargs)
                fresh_for = _keep_fresh_s(attr, kwargs)
                if kept is not None and fresh_for is not None and kept[1] < fresh_for:
                    with self._memo_lock:
                        self._memo[key] = (time.monotonic(), ttl, kept[0])
                    return kept[0]
                return self._ask_vendor(attr, target, args, kwargs, key, ttl, kept)

        return call

    def _ask_vendor(self, attr: str, target: Any, args: tuple, kwargs: dict, key: tuple,
                    ttl: float, kept: tuple[Any, float] | None) -> Any:
        now = time.monotonic()
        try:
            val = target(*args, **kwargs)
        except EntitlementError as exc:
            # A plan refusal does not change minute to minute: held for
            # an hour, so a polling panel does not spend the user's rate
            # limit being refused again.
            with self._memo_lock:
                self._memo[key] = (now, _REFUSAL_TTL_S, exc)
            raise
        except Exception as exc:
            # A vendor that is down answers from the kept copy, however old —
            # for history and profiles an old answer beats an empty panel.
            # Held briefly so a failing vendor is not asked on every poll.
            if kept is not None and kept[1] < _KEEP_STALE_S:
                log.warning("%s failed %s (%s): serving the copy kept %d min ago",
                            self._vendor, attr, exc, int(kept[1] / 60))
                with self._memo_lock:
                    self._memo[key] = (time.monotonic(), min(ttl, 60.0), kept[0])
                return kept[0]
            raise
        # AN ANSWER THAT IS STILL COMING IS NOT AN ANSWER (2026-09-24,
        # #67). A dict marked `filling` was already held briefly. A
        # provider that DEFERS its first read needs the same treatment
        # for None: the scraped calendars answer None while a background
        # fill runs, and the full hold meant the fill's answer, stored
        # seconds later, went unread until the memo expired — the source
        # looked permanently empty on a page that had already fetched it.
        #
        # ONLY FOR PROVIDERS THAT SAY SO (`DEFERS_FIRST_READ`), never for
        # None in general: None normally means "I do not carry this",
        # which is static, and several providers only discover it AFTER
        # an HTTP call. Shortening the hold for all of them would turn
        # every not-found lookup on a polling panel into a fresh vendor
        # request every couple of seconds, spending the reader's rate
        # limit to re-learn the same nothing.
        deferring = val is None and getattr(self._inner, "DEFERS_FIRST_READ", False)
        filling = deferring or (isinstance(val, dict) and val.get("filling"))
        hold = min(ttl, _FILLING_TTL_S) if filling else ttl
        with self._memo_lock:
            # What has EXPIRED goes on every insert once the memo has grown, not only
            # when it is full: an expired answer is never read again, but a 3-month
            # minute chart is ~48,000 bars, and up to 512 of them were kept until the
            # memo filled (2026-10-05: the server sat at 72-83% of 4 GiB and stalled).
            if len(self._memo) > _CACHE_SWEEP_AT or len(self._memo) >= _CACHE_MAX_ENTRIES:
                live = {k: v for k, v in self._memo.items() if now - v[0] < v[1]}
                self._memo = live if len(live) < _CACHE_MAX_ENTRIES else {}
            self._memo[key] = (now, hold, val)
        if not filling:
            self._kept_put(attr, args, kwargs, val)
        return val


@functools.lru_cache(maxsize=32)
def _user_prices_provider(user_id: str, created_at: str, provider_name: str, sealed: str):
    """One reader's price source from their sealed vault config — the LRU-on-
    created_at pattern the news seam uses: replacing the key builds a
    fresh instance, the old one ages out. Wrapped in the per-user TTL memo,
    so a polling board asks the reader's provider once per window, not once
    per poll."""
    from alphadesk.ledger import vault
    cfg = vault.decrypt(sealed)
    provider = build("prices", provider_name,
                     api_key=cfg.get("api_key") or None,
                     api_secret=cfg.get("api_secret") or None)
    # Which reader this instance serves, for what it persists under their
    # name (a derived result kept per reader, invariant 8). Its background
    # threads have no request identity to read it from.
    try:
        provider.reader_id = user_id
    except AttributeError:                        # a plugin that forbids it
        pass
    return _CachedPrices(provider, owner=user_id, vendor=provider_name)


_STAMP_EVERY_S = 300.0
_stamped: dict[tuple[str, str], float] = {}


def _stamp_used(uid: str | None, vendor: str) -> None:
    """The Account page's "last used" for a market-data key: stamped when
    the vendor actually answers, at most every five minutes per key, so a
    polling board is not a database write per poll."""
    if not uid:
        return
    now = time.monotonic()
    key = (uid, vendor)
    if now - _stamped.get(key, -_STAMP_EVERY_S) < _STAMP_EVERY_S:
        return
    _stamped[key] = now
    try:
        from alphadesk.ledger import store
        store.touch_user_key_provider(uid, "prices", vendor)
    except Exception as exc:                                  # a stamp never fails a panel
        log.debug("could not stamp %s key use: %s", vendor, exc)


class DataRouter:
    """One user's market data: every vendor they connected, asked in the
    catalogue's order for each surface (providers/catalogue.py).

    There is no operator source behind it (2026-09-13). A vendor that answers
    None does not carry the surface and the next is asked; one whose plan
    refuses the call is noted and skipped; when none answers, `ask` raises
    NeedsKey carrying the prompt a panel renders. `get` is the same walk
    returning None instead, for composite callers that assemble several
    surfaces and show what they have.

    The router's `name` is "user"; `answered_by` names the vendor that served
    the most recent call on this router, for a panel's source line."""

    name = "user"

    def __init__(self, uid: str | None, vendors: dict[str, Any]) -> None:
        self.uid = uid
        self.vendors = vendors
        self.answered_by: str | None = None

    @property
    def connected(self) -> list[str]:
        return sorted(self.vendors)

    @property
    def owner(self) -> str:
        """The cache scope for anything this router's answers fill: data
        from a user's key is theirs alone."""
        return self.uid or "anonymous"

    def _order(self, surface: str, method: str) -> list[str]:
        from alphadesk.providers.catalogue import SURFACES, VENDORS
        s = SURFACES.get(surface)
        listed = [n for n, _ in s.vendors] if s else []
        # Catalogue order first; a connected vendor the catalogue does not
        # list for the surface (a plugin) is asked after, if it has the method.
        rest = [n for n in sorted(self.vendors) if n not in listed]
        # A SCRAPED SOURCE IS ALWAYS LAST (2026-09-23, the owner's rule: never
        # scrape what a keyed vendor carries; scrape only where none does).
        # It held before this only because no scraped source is listed on a
        # surface AND their names happened to sort after the vendors they
        # compete with — luck, not a guarantee, and a plugin named after
        # "nasdaq" would have taken a calendar from a paid vendor. Now the
        # walk cannot reach one until every keyed vendor has declined.
        def scraped(name: str) -> bool:
            v = VENDORS.get(name)
            return v is not None and not v.official
        order = [n for n in listed + rest
                 if n in self.vendors and callable(getattr(self.vendors[n], method, None))]
        # Stable, so the catalogue's order survives among the keyed vendors
        # and only the scraped ones move — to the end.
        return sorted(order, key=scraped)

    def ask(self, method: str, *args: Any, surface: str | None = None, **kwargs: Any) -> Any:
        from alphadesk.providers.catalogue import METHOD_SURFACE
        surf = surface or METHOD_SURFACE.get(method, method)
        refused: list[str] = []
        # WHY EACH VENDOR DECLINED, carried on the NeedsKey (2026-09-23). A
        # vendor that was ASKED and could not answer is not the same thing as
        # one the reader never connected, and until now both ended in the same
        # 428 — so a source that was switched ON but unreachable told the
        # reader to switch it on. That is the "connect a key" prompt lying
        # about the state of the world, and it is how the social source went
        # unnoticed: it was on, the site refused the server, and the panel
        # said nothing at all. Same lesson as the empty tabs in #57 — a failed
        # read is not an absence.
        failed: dict[str, str] = {}
        for name in self._order(surf, method):
            try:
                value = getattr(self.vendors[name], method)(*args, **kwargs)
            except NeedsKey:
                raise
            except EntitlementError as exc:
                log.info("%s refused %s on plan: %s", name, method, exc)
                refused.append(name)
                continue
            except ProviderError as exc:
                log.warning("%s failed %s: %s", name, method, exc)
                failed[name] = str(exc)
                continue
            if value is None:
                continue
            self.answered_by = name
            _stamp_used(self.uid, name)
            return value
        raise NeedsKey(surf, refused, signed_in=self.uid is not None, connected=list(self.vendors),
                       failed=failed)

    def ask_others(self, method: str, *args: Any, skip: str | None = None,
                   surface: str | None = None, **kwargs: Any):
        """Each OTHER connected vendor's answer to `method`, in catalogue
        order, skipping `skip` and any vendor that refuses or fails — for a
        panel that fills one missing part of an answer from a second vendor
        (fund holdings, 2026-09-18). Yields (vendor name, value)."""
        from alphadesk.providers.catalogue import METHOD_SURFACE
        surf = surface or METHOD_SURFACE.get(method, method)
        for name in self._order(surf, method):
            if name == skip:
                continue
            try:
                value = getattr(self.vendors[name], method)(*args, **kwargs)
            except (EntitlementError, ProviderError):
                continue
            if value is not None:
                yield name, value

    def vendor_for(self, surface: str, method: str) -> Any:
        """The one vendor that serves a surface whose calls must not be mixed
        across vendors — a chart's pages, an option chain's expiries: the
        first connected vendor in catalogue order that has the method. It
        does not call anything; NeedsKey when none is connected."""
        order = self._order(surface, method)
        if not order:
            raise NeedsKey(surface, [], signed_in=self.uid is not None)
        return self.vendors[order[0]]

    def get(self, method: str, *args: Any, surface: str | None = None, **kwargs: Any) -> Any:
        try:
            return self.ask(method, *args, surface=surface, **kwargs)
        except NeedsKey:
            return None

    def __getattr__(self, attr: str) -> Any:
        # Contract-shaped access (router.quote(sym)) for callers written
        # against a single provider: the walk, answering None when no
        # connected vendor carries it.
        if attr.startswith("_"):
            raise AttributeError(attr)
        return lambda *args, **kwargs: self.get(attr, *args, **kwargs)


#: Vendors this version no longer carries. A key still saved for one (until the
#: ledger's start-up drops it) is passed over rather than failing every price
#: call; any OTHER unopenable key stays a hard error, below.
REMOVED_VENDORS = frozenset({"coingecko"})


def get_prices() -> DataRouter:
    """The market-data router for THIS call: the signed-in user's connected
    vendors, nothing else. Anonymous calls, background loops and the MCP
    server carry no identity and get an empty router — every surface on it
    answers NeedsKey.

    An unopenable stored key is a HARD ERROR, never a silent skip — the user
    chose that vendor; serving a different one behind their back is the one
    thing this seam must not do."""
    uid = _request_uid()
    if not uid:
        return DataRouter(None, {})
    vendors: dict[str, Any] = {}
    for row in _user_prices_rows(uid):
        if row["provider"] in REMOVED_VENDORS:
            continue
        vendors[row["provider"]] = _user_prices_provider(uid, row["created_at"], row["provider"], row["config"])
    return DataRouter(uid, vendors)


get_data = get_prices


@functools.lru_cache(maxsize=1)
def _operator_transcripts():
    # The keyless default is the company's own filed press release on SEC
    # EDGAR — public government data, the one source that needs no key. A
    # call transcript needs a vendor that records calls, keyed by the user.
    return build("transcripts", "edgar")


@functools.lru_cache(maxsize=32)
def _user_transcripts_provider(user_id: str, created_at: str, provider_name: str, sealed: str):
    from alphadesk.ledger import vault
    cfg = vault.decrypt(sealed)
    return build("transcripts", provider_name, api_key=cfg.get("api_key") or None)


def get_transcripts():
    """The transcript source for THIS call — the reader's keyed vendor when
    they stored one, the operator's selection otherwise. Not memoised per
    user: a transcript is read a few times an hour, not polled, so the
    ledger read per call is nothing. The prices seam's rule holds: an
    unopenable stored key is a hard error, never a silent fall-through."""
    uid = _request_uid()
    if uid:
        from alphadesk.ledger import store
        row = store.get_user_key(uid, "transcripts")
        if row is not None:
            store.touch_user_key_provider(uid, "transcripts", row["provider"])
            return _user_transcripts_provider(uid, row["created_at"], row["provider"], row["config"])
    return _operator_transcripts()


def reset_cache() -> None:
    """Forget the selected providers. For tests and for re-reading config."""
    _user_prices_provider.cache_clear()
    _prices_rows.clear()
    _operator_transcripts.cache_clear()
    _user_transcripts_provider.cache_clear()
