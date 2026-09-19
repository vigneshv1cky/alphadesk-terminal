"""A coin's profile from CoinGecko — the public API, with the reader's own
key when they have added one on the Account page ("crypto" seam).

Two calls: /search resolves a ticker to a coin id by market-cap rank
("btc" → "bitcoin", not one of the eleven other BTC-symbol tokens), then
/coins/{id} carries the description, categories, links, supply and launch.
Keyless calls share CoinGecko's public rate limit; a demo or pro key rides
on the request header and raises it for that reader. Public data either
way, so the result is cached an hour per coin for everyone.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_TTL_S = 3600
_cache: dict[str, tuple[float, dict | None]] = {}
_lock = threading.Lock()
_BASE = "https://api.coingecko.com/api/v3"


def _get(path: str, api_key: str | None, timeout: float = 15.0) -> dict:
    if not api_key:
        # 2026-09-13: every CoinGecko call carries the user's own key.
        raise RuntimeError("no CoinGecko key")
    headers = {"Accept": "application/json", "User-Agent": "AlphaDesk/1.0 (research terminal)"}
    if api_key:
        headers["x-cg-demo-api-key"] = api_key
    req = urllib.request.Request(_BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def resolve_id(base: str, api_key: str | None = None) -> str | None:
    """The coin id for a ticker, highest market-cap rank first."""
    s = _get(f"/search?query={urllib.parse.quote_plus(base)}", api_key)
    coins = [c for c in (s.get("coins") or []) if (c.get("symbol") or "").upper() == base.upper()]
    if not coins:
        return None
    coins.sort(key=lambda c: (c.get("market_cap_rank") is None, c.get("market_cap_rank") or 10**9))
    return coins[0].get("id")


def _strip(html: str, cap: int = 1400) -> str:
    text = re.sub(r"<[^>]+>", "", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= cap else text[:cap].rsplit(" ", 1)[0] + "…"


def coin(symbol: str, api_key: str | None = None) -> dict | None:
    """Profile for "BTC-USD" / "BTC". None when CoinGecko does not know it."""
    base = symbol.upper().split("-")[0]
    # Keyed by the reader's key, not shared (invariant 8): one reader's
    # CoinGecko answer must not serve the next reader.
    import hashlib
    ck = f"{hashlib.sha256((api_key or '').encode()).hexdigest()[:16]}:{base}"
    with _lock:
        hit = _cache.get(ck)
        if hit and time.time() - hit[0] < _TTL_S:
            return hit[1]
    out: dict | None = None
    try:
        cid = resolve_id(base, api_key)
        if cid:
            c = _get(f"/coins/{cid}?localization=false&tickers=false&community_data=false"
                     "&developer_data=false&sparkline=false", api_key)
            links = c.get("links") or {}
            md = c.get("market_data") or {}
            out = {
                "id": cid,
                "name": c.get("name"),
                "symbol": (c.get("symbol") or base).upper(),
                "description": _strip(((c.get("description") or {}).get("en")) or ""),
                "categories": [x for x in (c.get("categories") or []) if x][:6],
                "homepage": next((u for u in (links.get("homepage") or []) if u), None),
                "whitepaper": links.get("whitepaper") or None,
                "explorers": [u for u in (links.get("blockchain_site") or []) if u][:3],
                "genesis_date": c.get("genesis_date"),
                "hashing_algorithm": c.get("hashing_algorithm"),
                "market_cap_rank": c.get("market_cap_rank"),
                "circulating_supply": md.get("circulating_supply"),
                "total_supply": md.get("total_supply"),
                "max_supply": md.get("max_supply"),
                "url": f"https://www.coingecko.com/en/coins/{cid}",
                # CoinGecko's paid plans require this exact credit wherever
                # their data is shown, linked to coingecko.com (2026-09-19).
                "attribution": "Powered by CoinGecko",
            }
    except Exception as exc:
        log.debug("coingecko failed for %s: %s", base, exc)
        # A rate-limited keyless call is not worth caching as "unknown".
        return None
    with _lock:
        _cache[ck] = (time.time(), out)
    return out
