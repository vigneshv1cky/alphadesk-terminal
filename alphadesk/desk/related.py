"""What a company's own words tie it to (2026-10-03).

A vendor's peer list follows a company's old industry code: SVRN, which now
holds a NEAR Protocol token treasury, still came back as a list of dry-bulk
shippers, and no search found the token. The company says what it is in its
press releases and filings, so those words are read for the crypto assets and
the other listed companies they name. A mention is a mention: this says what
the text names, not that the price follows it.
"""

from __future__ import annotations

import re

#: Coins by the names a filing uses, to their tickers.
COINS = {
    "bitcoin": "BTC", "ethereum": "ETH", "ether": "ETH", "solana": "SOL", "near protocol": "NEAR",
    "xrp": "XRP", "ripple": "XRP", "dogecoin": "DOGE", "cardano": "ADA", "avalanche": "AVAX",
    "polkadot": "DOT", "chainlink": "LINK", "litecoin": "LTC", "tron": "TRX", "sui": "SUI",
    "toncoin": "TON", "hyperliquid": "HYPE", "binance coin": "BNB", "bnb": "BNB", "stellar": "XLM",
    "polygon": "POL", "aptos": "APT", "cosmos": "ATOM", "uniswap": "UNI", "aave": "AAVE",
    "zcash": "ZEC", "monero": "XMR", "shiba inu": "SHIB", "pepe": "PEPE", "hedera": "HBAR",
}
_COIN_NAME = re.compile(r"\b(" + "|".join(sorted((re.escape(k) for k in COINS), key=len, reverse=True)) + r")\b", re.I)
# "NEAR tokens", "SOL treasury": an upper-case ticker followed by a crypto word.
_TICKER_TOKEN = re.compile(r"\b([A-Z]{2,10})\s+(?:Protocol\b|tokens?\b|coins?\b|treasury\b)")
_LISTED = re.compile(r"\((?:NASDAQ|NYSE(?: American| Arca)?|CBOE|OTC[A-Z]*|TSX|LSE)\s*:\s*([A-Z][A-Z.\-]{0,5})\)")
_NOT_COINS = {"THE", "OUR", "ITS", "AND", "FOR", "USD", "SEC", "LLC", "INC", "CEO", "CFO", "NAV", "ETF", "IPO", "AI", "US", "USA"}


def _snippet(text: str, start: int, end: int, width: int = 90) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - width):end + width]).strip()


def extract_related(sources: list[dict], own_symbol: str, own_names: list[str] | None = None) -> dict:
    """Crypto assets and other listed companies named in `sources`, each
    {source, text}. A crypto asset appears with its mention count, the first
    source and a snippet; a company with its ticker. The reader's own ticker
    and names are left out."""
    own = {own_symbol.upper(), *(n.upper() for n in own_names or [])}
    crypto: dict[str, dict] = {}
    companies: dict[str, dict] = {}

    def add_coin(ticker, name, src, text, a, b):
        row = crypto.setdefault(ticker, {"asset": ticker, "name": name, "mentions": 0,
                                         "first_source": src, "snippet": _snippet(text, a, b)})
        row["mentions"] += 1
        if len(name) > len(row["name"]):
            row["name"] = name

    for s in sources:
        text, src = s.get("text") or "", s.get("source")
        for m in _COIN_NAME.finditer(text):
            name = m.group(1)
            if name.lower() == "sui" and not re.search(r"\bSUI\b", m.group(0)):
                continue                                     # the word "sui" in "sui generis"
            add_coin(COINS[name.lower()], name.title() if name.islower() else name, src, text, m.start(), m.end())
        for m in _TICKER_TOKEN.finditer(text):
            t = m.group(1)
            if t in _NOT_COINS or t in own:
                continue
            add_coin(t, t, src, text, m.start(), m.end())
        # Other listed companies are read from FILINGS only: a news summary that
        # names tickers is usually a movers list ("Here Are 20 Stocks Moving"),
        # which ties the company to nothing.
        for m in (_LISTED.finditer(text) if not str(src).startswith("story:") else ()):
            t = m.group(1)
            if t.upper() in own:
                continue
            row = companies.setdefault(t, {"ticker": t, "mentions": 0, "first_source": src, "snippet": _snippet(text, m.start(), m.end())})
            row["mentions"] += 1
    # A bare ticker found only by the generic pattern must repeat to count:
    # "ABC treasury" once in a long document is as likely a heading as an asset.
    keep = [c for c in crypto.values() if c["mentions"] >= 2 or c["asset"] in COINS.values()]
    return {"crypto": sorted(keep, key=lambda c: -c["mentions"]),
            "companies": sorted(companies.values(), key=lambda c: -c["mentions"])}
