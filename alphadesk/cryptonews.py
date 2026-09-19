"""A coin's news: all crypto, and what moves it (2026-09-19, the owner: "for
any crypto show all crypto, coin news dont target it towards a particular
coin, and also include any news that might influence it").

A coin's panel used to be the stories a publisher tagged with that exact
coin. Crypto does not move one coin at a time — bitcoin's price, the crypto
stocks, regulation and the Fed move all of it — so every coin reads the same
list: a story is in when it is

  coin          tagged with ANY coin, in any feed's spelling (BTCUSD,
                X:BTCUSD, BTC-USD);
  crypto stock  tagged with a company whose share price moves on crypto —
                the curated "bitcoin" basket (miners, bitcoin holders, the
                spot funds) and the pure crypto companies of "crypto-rules"
                (Coinbase, Circle, Galaxy). Robinhood, Block and PayPal are
                broad fintech: their stories come in when they name crypto;
  crypto        naming crypto in its headline or summary;
  rates         a HEADLINE naming what moves every risk asset crypto trades
                with: the Fed, a rate decision, CPI/PCE, the jobs report.
                Measured on the first run (2026-09-19): matched on summaries
                and on "inflation"/"yields" it was 103 of 232 stories,
                dividend and real-estate pieces among them.

The first reason that applies is the one given. A fixed rule, not a model or
a score: which story matters is the reader's call (invariant 3), and the
list stays newest first.
"""

from __future__ import annotations

import re

_COIN_TAG = re.compile(r"^(?:X:|CRYPTO:)?[A-Z0-9]{2,10}[-/]?(?:USD|USDT|USDC)$")
_CRYPTO_WORDS = re.compile(
    r"\b(?:crypto(?:currenc(?:y|ies))?|bitcoin|btc|ether(?:eum)?|eth|stablecoins?|blockchain|altcoins?|"
    r"digital[- ]assets?|tokeni[sz](?:ed|ation)|defi|memecoins?|solana|xrp|dogecoin)\b", re.IGNORECASE)
_RATES_WORDS = re.compile(
    r"\b(?:federal reserve|fomc|powell|(?:fed|rate) (?:cut|hike)s?|cpi|pce|jobs report|nonfarm payrolls?)\b",
    re.IGNORECASE)
_BASKET = "bitcoin"
_PURE_CRYPTO = frozenset({"COIN", "CRCL", "GLXY"})


def crypto_stocks() -> frozenset[str]:
    """The curated baskets' members whose price moves on crypto."""
    from alphadesk import config
    return frozenset(s.upper() for t in config._DEFAULT_THEMES if t.get("id") == _BASKET
                     for s in t.get("symbols") or []) | _PURE_CRYPTO


def why(article: dict, stocks: frozenset[str]) -> str | None:
    """Why a story belongs on a coin's panel, or None. Pure."""
    tags = [str(t).upper() for t in article.get("tickers") or []]
    if any(_COIN_TAG.match(t) for t in tags):
        return "coin"
    if any(t in stocks for t in tags):
        return "crypto stock"
    text = f"{article.get('title') or ''} {article.get('summary') or ''}"
    if _CRYPTO_WORDS.search(text):
        return "crypto"
    if _RATES_WORDS.search(article.get("title") or ""):
        return "rates"
    return None


def select(articles: list[dict], limit: int) -> list[dict]:
    """The stories a coin's panel shows, newest first as given, each marked
    with why it is there."""
    stocks = crypto_stocks()
    out = []
    for a in articles:
        reason = why(a, stocks)
        if reason:
            a["why"] = reason
            out.append(a)
            if len(out) >= limit:
                break
    return out
