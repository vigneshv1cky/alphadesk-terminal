"""AlphaDesk configuration.

Everything here is read from the environment with a working default, so a
fresh checkout runs without a .env. The server holds no vendor keys
(2026-09-13): every market figure, headline and model answer comes from a
key the user connects on the Account page, sealed under
ALPHADESK_VAULT_KEY. SEC_USER_AGENT has no sensible default and must be
supplied (the SEC requires real contact info — see ingest/edgar.py).

Historical note: this file used to carry ~150 lines of trading parameters
(entry gates, ATR stops, trailing exits, paper-trading sizing, session entry
buffers). Every one of them was orphaned when the execution and measurement
layers were removed on 2026-08-18, and they were deleted on 2026-08-19. Git
history has them if that direction ever returns; a live config file listing
knobs nothing reads is worse than no record at all.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("alphadesk.config")


def _ensure_ca_bundle() -> None:
    """Make HTTPS work on a Python with no trusted root certificates (the
    python.org build on macOS ships none until its "Install Certificates"
    script is run, so every EDGAR and vendor call failed with CERTIFICATE_
    VERIFY_FAILED on a fresh clone, 2026-10-03). When nothing is configured and
    the interpreter's own default bundle is missing, use certifi's."""
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return
    import ssl
    paths = ssl.get_default_verify_paths()
    if paths.cafile and os.path.exists(paths.cafile):
        return
    if paths.capath and os.path.isdir(paths.capath) and os.listdir(paths.capath):
        return
    try:
        import certifi
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


_ensure_ca_bundle()

#: The app's own settings, whose values a reader may have commented.
_OUR_PREFIXES = ("ALPHADESK_", "DASHBOARD_", "NEWS_", "CHART_", "RSI_", "SEC_USER_AGENT",
                 "FORECAST_", "SCREENER_", "FILING_", "RESEARCH_", "OWNERSHIP_", "MCP_")


def _strip_inline_comments() -> None:
    """Take the trailing comment off every AlphaDesk setting, once, at import.

    Docker's --env-file keeps everything after the "=", so a template line
    like `ALPHADESK_AUTH=off  # development` arrives as the whole string.
    Numeric settings then raised on import; worse, string settings SILENTLY
    took another meaning — sign-in stayed on because the value was not
    exactly "off" (2026-09-19, found by running the README's own Docker
    command against the shipped template). Only values with whitespace
    before the "#" are touched, so a key containing a "#" is untouched.
    """
    for name, raw in list(os.environ.items()):
        if not name.startswith(_OUR_PREFIXES) or "#" not in raw:
            continue
        cut = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        if cut and cut != raw:
            os.environ[name] = cut


_strip_inline_comments()


def env_value(name: str, default: str = "") -> str:
    """A setting's value with a trailing comment stripped.

    Docker's --env-file does NOT strip inline comments the way python-dotenv
    does, so `CHART_MIN_COVERAGE=0.5  # note` reaches the process as the whole
    string and every numeric setting raised on import — the container exited
    on the README's own command (2026-09-19). Written once here so a reader's
    comment is never a crash.
    """
    raw = os.environ.get(name, default)
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip() if isinstance(raw, str) else raw

ET = ZoneInfo("America/New_York")
DATA_DIR = Path(env_value("ALPHADESK_DATA", "~/.alphadesk")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
# The settings `alphadesk init` writes live beside the data, so they are found
# wherever the server is started from (a pip install has no repo-root .env).
# Anything already in the environment, or in a .env found above, wins.
load_dotenv(DATA_DIR / ".env")

# ── Liquidity ────────────────────────────────────────────────────────────────
# 20-day average dollar volume below which a name is flagged thin. Surfaced as
# evidence on the Earnings page and in price context — never as a filter that
# removes a row, since "too thin to trade" is the reader's call to make.
LOW_LIQUIDITY_DOLLAR_VOL = 10_000_000

# ── Chart reference lines ────────────────────────────────────────────────────
# Drawn on the RSI panel so a reader can see where conventional oversold /
# overbought sit. They are DISPLAY thresholds only: nothing in this codebase
# acts on a crossing. The automated engine that did was deleted on 2026-08-16
# after measuring -0.072% mean alpha over 503 backtested trades.
RSI_CROSS_OVERSOLD = float(env_value("RSI_CROSS_OVERSOLD", "30"))
RSI_CROSS_OVERBOUGHT = float(env_value("RSI_CROSS_OVERBOUGHT", "70"))

# ── Chart data quality (human decision support) ──────────────────────────────
# Alpaca's free IEX feed carries only a few percent of consolidated volume, so
# an illiquid name has no print in most minutes. A "1-minute" RSI/MACD drawn on
# that series is really an N-sample indicator over an unknown time span —
# measured: ENTA had 92 bars across 5 sessions with a 42-min p90 gap, against
# AAPL's 1570 bars at a 1.0-min median. The rendered chart looks identical
# either way, which is the danger: a misleading chart actively recruits a
# reader's judgment. Below either floor the UI must hide the indicators rather
# than silently drawing them.
CHART_MIN_COVERAGE = float(env_value("CHART_MIN_COVERAGE", "0.5"))        # share of a 390-bar session
CHART_MAX_MEDIAN_GAP_MIN = float(env_value("CHART_MAX_MEDIAN_GAP_MIN", "2.0"))

# ── News ingest (main.py's _news_loop, ingest/news.py) ───────────────────────
# Fetch and persist ONLY: the loop narrates nothing and labels nothing
# (2026-09-17, the in-app model removed), so an idle terminal spends nothing.
# FIVE, not twenty (2026-09-17, measured): the poll was the whole of our
# staleness. Sampled against Yahoo's headline feed across ten large caps,
# our newest story per ticker was a median of 76 minutes old against their
# 34, while the window as a whole was only as old as the cycle position.
# Benzinga now arrives over the held socket in seconds (ingest/stream.py);
# this interval is what the feeds WITHOUT a stream — FMP, Polygon — cost in
# freshness, and four cycles an hour is still nothing against their limits.
NEWS_REFRESH_MINUTES = float(env_value("NEWS_REFRESH_MINUTES", "5"))
# TWO DAYS (2026-09-17, the owner's call — it was 36 hours). This is both the
# window a reader opens on and how far back a feed is asked on a cold start,
# so "yesterday and the day before" is there without pressing Load older.
# The news page does not fetch it in one request: 500 stories spanned 5.6
# hours on three feeds, so a day is around 2,000 of them, and the page fills
# the tail in background pages instead (ui/src/pages/NewsPage.tsx).
# THREE DAYS (2026-09-18, the owner's call — "always as a minimum"), up from
# two: a Monday morning then still reaches Friday.
NEWS_LOOKBACK_HOURS = float(env_value("NEWS_LOOKBACK_HOURS", "72"))

# ── How long vendor data is KEPT (2026-09-18, "store less") ────────────────
# Each reader's vendor data is kept only as long as a feature reads it; the
# rest is deleted every hour (store.prune_vendor_data). Public data (SEC
# EDGAR filings and releases) is not vendor data and is not pruned here.
# A story is kept while it is inside the news window plus a margin for
# paging and search; one fetched for an OLDER page (published before that)
# lives a day after it was fetched — paging back asks the reader's feed.
#
# KEEPING MORE ON A PERSONAL SERVER (2026-10-03). ALPHADESK_KEEP_DATA makes the
# retention below a longer one for the records a reader may want to look back
# on: `forever`, or a number of days. It only ever lengthens a default (a
# smaller number changes nothing), and it leaves the derived caches alone —
# release habits, press checks and the dollar-volume pool are recomputed
# anyway. A vendor's own terms about storing its data still apply to you; this
# setting does not change them.
_KEEP_RAW = env_value("ALPHADESK_KEEP_DATA", "").strip().lower()
FOREVER_DAYS = 36500.0            # a hundred years: "forever" without a special case anywhere
if _KEEP_RAW in ("forever", "always", "indefinitely"):
    KEEP_DATA_DAYS: float | None = FOREVER_DAYS
else:
    try:
        KEEP_DATA_DAYS = min(float(_KEEP_RAW), FOREVER_DAYS) if _KEEP_RAW else None
        if KEEP_DATA_DAYS is not None and not (KEEP_DATA_DAYS > 0):     # nan, zero, negative
            raise ValueError(_KEEP_RAW)
    except ValueError:
        log.warning("ALPHADESK_KEEP_DATA=%r is not 'forever' or a number of days: ignored", _KEEP_RAW)
        KEEP_DATA_DAYS = None


def keep_days(default_days: float) -> float:
    """A record's retention in days: its default, or the longer keep-data setting."""
    return max(default_days, KEEP_DATA_DAYS) if KEEP_DATA_DAYS else default_days


NEWS_KEEP_DAYS = keep_days(float(env_value("NEWS_KEEP_DAYS", "7")))
NEWS_OLDER_PAGE_KEEP_HOURS = keep_days(1.0) * 24
# REACHING FURTHER WHEN THE STORE HAS LESS (2026-10-03). With a longer
# keep-data setting the feed is also asked for more than the default: a key
# save refills NEWS_BACKFILL_DAYS back (the retention window by default, never
# more than a year, and 30 days when keeping more), "Load older" looks 30 days
# before the oldest story instead of 7, and a symbol's own ask looks a year back.
NEWS_BACKFILL_DAYS = min(365.0, float(env_value("NEWS_BACKFILL_DAYS", "") or
                                      (min(NEWS_KEEP_DAYS, 30.0) if KEEP_DATA_DAYS else NEWS_KEEP_DAYS)))
NEWS_OLDER_PAGE_DAYS = 30 if KEEP_DATA_DAYS else 7
SYMBOL_NEWS_LOOKBACK_DAYS = 365 if KEEP_DATA_DAYS else 30
# A story's FULL TEXT only while it is inside the news window; after that
# the row keeps its headline and summary, and opening it asks the reader's
# feed for the text again.
NEWS_BODY_KEEP_HOURS = keep_days(NEWS_LOOKBACK_HOURS / 24) * 24
# A company's own "will report on" announcement moves a calendar row within
# 14 days of its date; a month past the report date it has no use.
ANNOUNCEMENT_KEEP_DAYS = keep_days(30)
# The forecast log is scored against EDGAR at 1/3/7 days ahead and read back
# up to 30 days; 120 days covers any reasonable re-check.
FORECAST_KEEP_DAYS = keep_days(120)
# Release-habit (3 days) and press-release (6 hours) results are re-derived
# past their freshness; the dollar-volume pool is rebuilt daily.
HABIT_KEEP_DAYS = 3
PRESS_CHECK_KEEP_HOURS = 24
POOL_KEEP_DAYS = 7
# The kept copies of vendor answers (providers/registry.py): a vendor that is down
# is answered from here however old the copy is, so a copy is kept this long.
VENDOR_CACHE_KEEP_DAYS = keep_days(14)
# Scraped pages, held once for everyone (2026-09-25, #71). A calendar day is
# useful while the earnings window still reaches it; halts and posts are
# about right now and are worthless the next day. Kept only as long as a
# feature reads them, like every other vendor table.
SCRAPED_KEEP_DAYS = keep_days(float(env_value("SCRAPED_KEEP_DAYS", "21")))
SCRAPED_LIVE_KEEP_HOURS = keep_days(float(env_value("SCRAPED_LIVE_KEEP_HOURS", "24")) / 24) * 24
# Per-user feeds (phase 3). A reader's own key is polled only while they have
# been seen within the activity window, and each cycle is capped, so a
# sleeping reader's vendor quota is not spent. Both caps are visible here,
# not buried in the loop.
NEWS_USER_LIMIT = int(env_value("NEWS_USER_LIMIT", "100"))
NEWS_USER_ACTIVE_HOURS = float(env_value("NEWS_USER_ACTIVE_HOURS", "48"))
# The earnings forecast log's daily capture covers readers seen within a week:
# a reader away for a few days still keeps a continuous record, and one
# calendar request per vendor a day is the whole cost.
FORECAST_USER_ACTIVE_HOURS = float(env_value("FORECAST_USER_ACTIVE_HOURS", "168"))
FORECAST_CAPTURE_HOUR_ET = int(env_value("FORECAST_CAPTURE_HOUR_ET", "7"))
SCREENER_HORIZON_DAYS = int(env_value("SCREENER_HORIZON_DAYS", "5"))  # upcoming-earnings window
# One ask covers the WHOLE window (every symbol at once), so its input is
# bounded by these two rather than by a top-N cut of the symbol list. The cap
# drops the OLDEST articles first — same policy as ingest/news.py's scan cap.
SCREENER_ASK_MAX_ARTICLES = int(env_value("SCREENER_ASK_MAX_ARTICLES", "120"))
# Per-call input budget, well above LLM_MAX_INPUT_CHARS (24k, sized for one
# symbol's batch of headlines) for the same reason FILING_MAX_CHARS is: this
# call is deliberately wide. A global bump would raise every other call's cost.
SCREENER_ASK_MAX_CHARS = int(env_value("SCREENER_ASK_MAX_CHARS", "40000"))

# ── Filings workspace (ingest/edgar.py, desk/filings.py) ─────────────────────
# A 10-K's meaningful narrative (Business, Risk Factors, MD&A) commonly runs
# 50-100k characters — the news path's LLM_MAX_INPUT_CHARS (24k, sized for a
# batch of short headlines) would truncate before reaching most of it. This is
# a per-call override (ai/llm.chat_json's max_input_chars), not a change to the
# global default, so it doesn't raise the cost of every other call site.
FILING_MAX_CHARS = int(env_value("FILING_MAX_CHARS", "60000"))

# ── Research agent (desk/research.py) ────────────────────────────────────────
# Q&A over one symbol's pre-fetched fundamentals/ownership/insider/earnings/
# macro/sector data — same "server fetches, one chat_json call summarizes-and-
# cites" shape as desk/filings.py, not a tool-calling loop. All 6 sections are
# wrapped as untrusted <data:*> blocks (ai/llm.wrap_data), so this needs a much
# larger input budget than the news path — mirrors FILING_MAX_CHARS's reasoning.
RESEARCH_MAX_CHARS = int(env_value("RESEARCH_MAX_CHARS", "30000"))
# Unlike symbol_digests/filing_qa_cache, the underlying data (a live quote,
# recent insider filings) can go stale between identical asks even though the
# question text hasn't changed — so this cache needs an actual TTL, not just
# a hash key.
RESEARCH_CACHE_TTL_HOURS = float(env_value("RESEARCH_CACHE_TTL_HOURS", "4"))
# 13F is quarterly, Form 4 is event-driven — both move far slower than a live
# quote, hence the much longer TTL than prices.py's other in-memory caches.
OWNERSHIP_TTL_S = int(env_value("OWNERSHIP_TTL_S", str(6 * 3600)))


# ── Market sessions ──────────────────────────────────────────────────────────

def now_et() -> datetime:
    return datetime.now(ET)


def session(dt: datetime | None = None) -> str:
    dt = (dt or now_et()).astimezone(ET)
    if dt.weekday() >= 5:
        return "CLOSED"
    minutes = dt.hour * 60 + dt.minute
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "PRE"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "OPEN"
    if 16 * 60 <= minutes < 20 * 60:
        return "AFTER"
    return "CLOSED"


def session_label(dt: datetime | None = None) -> str:
    """What to call the moment, for a panel that has to say which session a
    figure belongs to (2026-09-22). `session()` answers what the market is
    doing and calls every quiet hour CLOSED alike; this one tells the
    overnight session from the weekend, because a price struck at two in the
    morning is a real print and a price struck on a Saturday is Friday's."""
    dt = (dt or now_et()).astimezone(ET)
    minutes = dt.hour * 60 + dt.minute
    day = dt.weekday()
    # The overnight venue runs Sunday evening to Friday evening.
    if day == 5 or (day == 6 and minutes < 20 * 60) or (day == 4 and minutes >= 20 * 60):
        return "Weekend"
    if day <= 4:
        if 4 * 60 <= minutes < 9 * 60 + 30:
            return "Pre-market"
        if 9 * 60 + 30 <= minutes < 16 * 60:
            return "Open"
        if 16 * 60 <= minutes < 20 * 60:
            return "After hours"
    return "Overnight"


# ── Symbols ─────────────────────────────────────────────────────────────────
#
# The symbol list search draws from is the SEC's own ticker file with each
# registrant's exchange (company_tickers_exchange.json) — public government
# data, keyless (2026-09-13: it replaced the Alpaca asset list read with the
# server's key). Cached a week on disk. Crypto pairs a user can chart are
# listed alongside so a search for a coin finds it.

_NAMES_CACHE = DATA_DIR / "symbol_meta_sec.json"
_NAMES_MAX_AGE_S = 7 * 24 * 3600
_names: dict[str, dict] | None = None
_names_fetch_tried = False
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_COINS = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "XRP", "DOGE": "Dogecoin", "ADA": "Cardano",
          "AVAX": "Avalanche", "LINK": "Chainlink", "DOT": "Polkadot", "LTC": "Litecoin", "BCH": "Bitcoin Cash",
          "UNI": "Uniswap", "AAVE": "Aave", "SHIB": "Shiba Inu", "XLM": "Stellar", "XTZ": "Tezos", "FIL": "Filecoin",
          "PEPE": "Pepe", "ARB": "Arbitrum", "HYPE": "Hyperliquid", "SUI": "Sui", "TRX": "TRON", "TON": "Toncoin",
          # Every coin Alpaca trades against the dollar (2026-10-04: the crypto
          # movers listed these but searching their names found nothing), and
          # the other large ones a reader types.
          "USDT": "Tether", "USDC": "USD Coin", "USDG": "Global Dollar", "PAXG": "PAX Gold", "ONDO": "Ondo",
          "SKY": "Sky", "POL": "Polygon", "RENDER": "Render", "CRV": "Curve DAO", "TRUMP": "Official Trump",
          "LDO": "Lido DAO", "BONK": "Bonk", "GRT": "The Graph", "WIF": "dogwifhat", "BAT": "Basic Attention Token",
          "SUSHI": "SushiSwap", "YFI": "yearn.finance", "BNB": "BNB", "NEAR": "NEAR Protocol", "ATOM": "Cosmos",
          "ETC": "Ethereum Classic", "XMR": "Monero", "ALGO": "Algorand", "APT": "Aptos", "INJ": "Injective",
          "MKR": "Maker", "COMP": "Compound", "SNX": "Synthetix", "ENA": "Ethena", "WLD": "Worldcoin"}


def _with_coins(names: dict) -> dict:
    """`names` with every listed coin pair present. Done on load as well as on
    fetch, so a symbol list cached before a coin was added still finds it."""
    for base, name in _COINS.items():
        names.setdefault(f"{base}-USD", {"name": name, "exchange": "Crypto", "class": "crypto"})
    return names


def _fetch_sec_names() -> dict[str, dict]:
    """ticker -> {name, exchange, class} from the SEC's ticker-exchange file."""
    from alphadesk.ingest import edgar
    data = json.loads(edgar._get(_SEC_TICKERS_URL, timeout=30.0))
    fields = data.get("fields") or []
    idx = {f: i for i, f in enumerate(fields)}
    out: dict[str, dict] = {}
    for row in data.get("data") or []:
        try:
            sym = str(row[idx["ticker"]]).upper()
            out.setdefault(sym, {"name": str(row[idx["name"]]).strip(), "exchange": row[idx["exchange"]] or None,
                                 "class": "us_equity"})
        except (KeyError, IndexError, TypeError):
            continue
    return _with_coins(out)


_QUOTE_NAMES = {"USD": "US Dollar", "USDC": "USD Coin", "USDT": "Tether", "BTC": "Bitcoin"}


def register_coin_pairs(pairs) -> int:
    """Make every crypto pair the connected Alpaca account can trade findable
    ("BAT/USDC" becomes BAT-USDC, "Basic Attention Token / USD Coin"), beyond
    the fixed coin list and the dollar pairs (2026-10-04, the owner: "all
    coins, crypto assets available to trade in alpaca" visible). In memory
    only; the account's own list is re-read daily. Returns how many were new."""
    _load_names()
    if _names is None:
        return 0
    pairs = [p for p in (pairs or ()) if "/" in str(p)]
    if pairs:
        # With the account's list in hand the search shows only what it can
        # trade (2026-10-04: NEAR-USD was offered, then charted nothing — the
        # fixed coin list had coins Alpaca does not carry).
        keep = {str(p).upper().replace("/", "-") for p in pairs}
        for sym in [k for k, v in _names.items() if v.get("class") == "crypto" and k not in keep]:
            del _names[sym]
    added = 0
    for pair in pairs:
        base, _, quote = str(pair).upper().partition("/")
        if not base or not quote:
            continue
        sym = f"{base}-{quote}"
        if sym in _names:
            continue
        coin = _COINS.get(base) or base
        name = coin if quote == "USD" else f"{coin} / {_QUOTE_NAMES.get(quote, quote)}"
        _names[sym] = {"name": name, "exchange": "Crypto", "class": "crypto"}
        added += 1
    return added


def _sec_key(symbol: str) -> str:
    """The SEC list writes a share class as "BRK-B"; vendors write "BRK.B"."""
    from alphadesk.ingest.edgar import sec_ticker
    return sec_ticker(symbol)


def in_universe(symbol: str) -> bool:
    """Whether a symbol is on the SEC's ticker list or a listed coin pair."""
    _load_names()
    return _sec_key(symbol) in (_names or {})


_CLASS_LABEL = {"us_equity": "Equity", "crypto": "Cryptocurrency",
                "us_option": "Option", "crypto_perp": "Crypto perpetual"}


def _row(sym: str, meta: dict) -> dict:
    return {"symbol": sym, "name": meta.get("name") or None,
            "exchange": meta.get("exchange") or None,
            "asset_class": _CLASS_LABEL.get(meta.get("class", ""), meta.get("class") or None)}


_WORD_RE = __import__("re").compile(r"[^A-Z0-9.]+")

# Name markers for instruments that merely REFERENCE a company rather than
# being it. "tesla" should offer TSLA before a 2x inverse ETN with Tesla in its
# title, and the asset class cannot tell them apart — Alpaca files all of these
# as us_equity, so the name is the only signal available.
_DERIVATIVE_MARKERS = (
    " ETF", " ETN", "ETNS", "LEVERAGED", "INVERSE", " 2X", " 3X", "-1X",
    "BULL", "BEAR", "INDEX-LINKED", "TRUST SERIES", "COVERED CALL",
)

# A POOLED VEHICLE named after a company is not that company (2026-09-17):
# searching "robinhood" answered RVI, Robinhood Ventures Fund I, ahead of
# HOOD itself, because both names begin with the word and the shorter ticker
# won the tie. Demoted the same way a derivative is — unless the reader asked
# for the vehicle, which is what the query carrying the marker word means:
# "northern trust" still finds Northern Trust first.
_VEHICLE_MARKERS = (" FUND", " TRUST", " PORTFOLIO", " CAPITAL TRUST")


#: Names the market uses that appear in NO registered name, so neither the
#: ticker nor the SEC's wording can reach them. DELIBERATELY TINY and not a
#: general alias dictionary: the generic mechanism is the initials tier in
#: _rank, which finds TSMC in "Taiwan Semiconductor Manufacturing Co" by
#: itself. This holds only the cases initials cannot — a company renamed
#: since the market learned it, or a contraction nobody files under
#: (2026-09-18, the reader searched TSMC and got nothing).
_ALIASES: dict[str, tuple[str, ...]] = {
    "GOOGLE": ("GOOGL", "GOOG"),      # files as Alphabet
    "FACEBOOK": ("META",),            # renamed 2021
    "BOFA": ("BAC",),                 # files as Bank of America Corp
    # Companies searched by a name they no longer file under (2026-10-04: "microstrategy" found nothing).
    "MICROSTRATEGY": ("MSTR",),       # now Strategy Inc
    "SQUARE": ("XYZ",),               # Block, Inc.
    "BLOCK": ("XYZ",),
    "MARATHON DIGITAL": ("MARA",),    # now MARA Holdings
    "MARATHON": ("MARA",),
    "RIOT BLOCKCHAIN": ("RIOT",),     # now Riot Platforms
    "VIACOM": ("PSKY",), "PARAMOUNT": ("PSKY",), "CBS": ("PSKY",),   # Paramount Skydance; PARA is now another company
    "WEIGHT WATCHERS": ("WW",),
    "ZOOM VIDEO": ("ZM",), "ZOOM": ("ZM",),
    "JP MORGAN": ("JPM",), "CHASE": ("JPM",),
    "HEWLETT PACKARD": ("HPQ", "HPE"),
    "TSMC": ("TSM",),
    "RIPPLE": ("XRP-USD",), "MATIC": ("POL-USD",), "POLYGON": ("POL-USD",),   # what the market calls them
    "DOGE": ("DOGE-USD",), "TETHER": ("USDT-USD",), "YEARN": ("YFI-USD",), "SUSHISWAP": ("SUSHI-USD",),
    "TRUMP COIN": ("TRUMP-USD",), "BINANCE COIN": ("BNB-USD",),
}


#: Names that mark a shell company built to buy another ("Bitcoin
#: Infrastructure Acquisition Corp"). Demoted like a derivative: nobody types
#: "bitcoin" to find a blank cheque.
_SHELL_MARKERS = (" ACQUISITION CORP", " ACQUISITION CO", " ACQUISITION HOLDINGS", " ACQUISITION LTD",
                  " ACQUISITION INC", " ACQUISITION PLC")

#: The coins named by their usual words, and the editorial basket whose stocks
#: move with them. Typing one of these finds the coin first, then the stocks
#: that follow it (2026-10-04: "bitcoin" answered a shell company and Bitcoin
#: Cash before Bitcoin itself).
_COIN_BASKETS = {"BITCOIN": "bitcoin", "ETHEREUM": "bitcoin", "ETHER": "bitcoin"}


def _is_warrant_unit_or_right(sym: str) -> bool:
    """A five-letter symbol whose fifth letter marks a warrant (W), unit (U),
    right (R) or preferred (P, Q): "BIXIW", "BIXIU". Rarely what a search
    for the company means."""
    return len(sym) == 5 and sym.isalpha() and sym[-1] in "WURPQ"


def _initials(name_norm: str) -> str:
    """The first letter of each word: "TAIWAN SEMICONDUCTOR MANUFACTURING CO
    LTD" becomes TSMCL, which is how TSMC is reachable at all. Pure."""
    return "".join(w[0] for w in name_norm.split() if w)


def _norm(text: str) -> str:
    """Uppercase, punctuation to spaces, whitespace collapsed.

    This is what makes "coca cola" find Coca-Cola. The old search asked whether
    the raw query was a substring of the raw name, so a hyphen in the company
    and a space in the query missed each other completely and KO was simply
    unreachable by name.
    """
    return " ".join(_WORD_RE.sub(" ", (text or "").upper()).split())


def _starts_word(haystack: str, token: str) -> bool:
    """Does `token` begin a word in `haystack`? Both are already normalised, so
    words are simply space-separated."""
    return haystack.startswith(token) or (" " + token) in haystack


def _rank(sym: str, name: str, q: str, q_norm: str, tokens: list[str]) -> int | None:
    """Lower is better; None means no match.

    Tiers rather than a similarity score, because the tiers are the intent: an
    exact ticker is never not what was meant, a ticker prefix is the next most
    likely, and only then does the company name matter.
    """
    name_norm = _norm(name)
    padded = f" {name_norm} "
    penalty = 50 if any(m in padded for m in _DERIVATIVE_MARKERS) else 0
    if not penalty:
        q_padded = f" {q_norm} "
        penalty = 50 if any(m in padded and m not in q_padded for m in _VEHICLE_MARKERS) else 0
    if not penalty and (_is_warrant_unit_or_right(sym) or any(m in padded for m in _SHELL_MARKERS)):
        penalty = 50

    if sym == q:
        return 0
    # A coin typed by its ticker: "bat" is BAT-USD, not the four stocks whose
    # symbols merely start with BAT (2026-10-04). Just behind an exact stock.
    # The pairs against a stablecoin follow their dollar twin: BAT-USDC right
    # behind BAT-USD, still ahead of the longer-named stocks.
    for rank_, quote in ((1, "-USD"), (2, "-USDC"), (3, "-USDT"), (4, "-BTC")):
        if sym.endswith(quote) and sym[:-len(quote)] == q:
            return rank_
    if sym.startswith(q):
        return 100 + len(sym)
    # A name that IS the query: "bitcoin" is Bitcoin, ahead of the companies
    # whose names merely begin with the word and win on a shorter ticker.
    if name_norm and name_norm == q_norm:
        return 150 + len(sym)
    if name_norm.startswith(q_norm):
        return 200 + penalty + len(sym)
    # The ticker CONTAINS the query. Typing "fd" should reach CLFD and BZFD,
    # not just the forty-one symbols that happen to begin FD — a substring of a
    # ticker is a ticker hunt, and there was no tier for it at all.
    #
    # Below name-prefix on purpose. Two letters match an enormous number of
    # symbols somewhere in the middle, and for a query like "co" the company
    # whose NAME starts with it (Coca-Cola, Costco) is far likelier to be the
    # one meant than an arbitrary ticker with CO buried in it.
    if len(q) >= 2 and q in sym:
        return 250 + len(sym)
    if not name_norm:
        return None
    # Every token present AT A WORD START, in any order — "global venture"
    # finds Venture Global. Word-anchored rather than anywhere-in-the-string
    # because a bare substring makes short queries meaningless: "f" appears
    # inside CLEARFIELD, and matching that returns half the market rather than
    # a search.
    if tokens and all(_starts_word(name_norm, t) for t in tokens):
        return 300 + penalty + len(sym)
    # Loosest tier, and two characters minimum for the same reason.
    if len(q_norm) >= 2 and q_norm in name_norm:
        return 400 + penalty + len(sym)
    # THE INITIALS, four characters and up: TSMC reaches Taiwan Semiconductor
    # Manufacturing Co, whose name and ticker (TSM) contain no "TSMC" at all.
    # Four is the floor because initials are only discriminating when they are
    # long — "TSMC" matched 2 of 10,449 listings, "BAC" matched 32 and "GE" 30,
    # so a shorter query would answer a ticker hunt with noise. Last tier, so
    # it never outranks a name or a ticker that genuinely matched.
    if len(q_norm) >= 4 and _initials(name_norm).startswith(q_norm.replace(" ", "")):
        return 500 + penalty + len(sym)
    return None


def search_symbols(query: str, limit: int = 12) -> list[dict]:
    """Ticker/name search over the SEC's ticker list.

    In-memory over ~13k entries, so no index and no round trip to a vendor is
    warranted — a linear scan of that is microseconds and the list only changes
    on the weekly universe refresh.

    Ranked in tiers: exact ticker, ticker prefix, name prefix, all query tokens
    present, then a loose substring. Within a tier a derivative is demoted and
    the shorter ticker wins, which favours the primary listing over the ETFs
    named after it — "jpmorgan" used to answer JIG, a JPMorgan ETF, ahead of
    JPM itself, because both merely contained the word and the tie fell to
    dictionary order.

    Ties break on the symbol, so the same query always returns the same list.
    """
    q = (query or "").strip().upper()
    if not q:
        return []
    _load_names()
    q_norm = _norm(q)
    tokens = [t for t in q_norm.split() if t]

    # An alias is explicit intent, so it leads — and still falls through to
    # the ranking below, which fills the rest of the list.
    lead = [s for s in _ALIASES.get(q_norm, ()) if s in (_names or {})]

    scored: list[tuple[int, str, str]] = []
    for sym, meta in (_names or {}).items():
        name = (meta or {}).get("name", "") or ""
        r = _rank(sym, name, q, q_norm, tokens)
        if r is not None:
            # Within a tier an exchange listing outranks an over-the-counter
            # one: "apple" means AAPL before an OTC shell with Apple in its name.
            otc = 1 if str((meta or {}).get("exchange") or "").upper() == "OTC" else 0
            scored.append((r * 2 + otc, sym, name))
    scored.sort(key=lambda t: (t[0], t[1]))
    # A coin's name: the coin first (the exact-name tier above), then the
    # editorial basket of the stocks that move with it, then the rest.
    follow: list[str] = []
    basket = _COIN_BASKETS.get(q_norm)
    if basket:
        theme = next((t for t in THEMES if t.get("id") == basket), None)
        follow = [s for s in (theme or {}).get("symbols", []) if s in (_names or {})]
    top = [sym for r, sym, _n in scored if r < 400 and sym not in lead]       # exact name or a ticker match
    rest = [sym for r, sym, _n in scored if r >= 400 and sym not in lead]
    ordered = lead + top + [s for s in follow if s not in lead and s not in top] + [s for s in rest if s not in follow]
    return [_row(sym, (_names or {}).get(sym) or {}) for sym in ordered[:limit]]


def _read_names_file() -> dict:
    try:
        if time.time() - _NAMES_CACHE.stat().st_mtime > _NAMES_MAX_AGE_S:
            return {}
        raw = json.loads(_NAMES_CACHE.read_text())
        return raw if all(isinstance(v, dict) for v in raw.values()) else {}
    except Exception:
        return {}


def _load_names() -> None:
    """The symbol list, from the week-old cache or fetched once per process
    from the SEC (so a failed fetch does not retry on every keystroke)."""
    global _names, _names_fetch_tried
    if _names is not None:
        return
    _names = _read_names_file()
    if _names:
        _with_coins(_names)
    if _names or _names_fetch_tried:
        return
    _names_fetch_tried = True
    try:
        _names = _fetch_sec_names()
        _NAMES_CACHE.write_text(json.dumps(_names))
        log.info("Symbol list fetched from the SEC: %d symbols", len(_names))
    except Exception as exc:
        log.warning("symbol list unavailable, search will be empty: %s", exc)
        _names = None


def symbol_meta(symbol: str) -> dict | None:
    """Everything cached about one symbol — name, exchange, asset class."""
    _load_names()
    meta = (_names or {}).get(_sec_key(symbol))
    return _row(symbol.upper(), meta) if meta else None


def company_name(symbol: str) -> str | None:
    """Display name for a symbol, from the SEC's ticker list.

    Returns None rather than the ticker when unknown — the caller decides
    whether a blank cell or a repeated ticker reads better, and repeating it
    would just be noise beside the symbol column.
    """
    # Populated on the next universe refresh; until then every row simply has
    # no name, which renders as an empty cell.
    _load_names()
    return ((_names or {}).get(_sec_key(symbol)) or {}).get("name") or None


# Curated baskets. A theme is a NAME and a list of symbols — nothing is scored,
# ranked or picked here, and the order is the order you write. That keeps it on
# the right side of the 2026-08-18 screener-ranking deletion: choosing what
# belongs in "AI & Tech" is an editorial act, and it is done once, in config,
# where a reader can see it and change it — not computed per-request and
# presented as a finding.
#
# Override wholesale with THEMES_JSON, which must be a JSON list of
# {"id", "label", "symbols"}. Left as a literal rather than a packed string
# because a nested list in a comma-separated env var is unreadable.
_DEFAULT_THEMES = [
    # EVERY TICKER HAS ONE HOME (2026-09-18, the owner's call: "make each
    # basket as unique as possible"). A name sits in the basket whose news
    # moves it most, so no two baskets share a member and a basket reads as
    # its own story — NVIDIA had been in five, Google in five. A test pins
    # it. Groups are keyed to the NEWS that moves them, across industries;
    # the Sectors page is the one that groups by industry. Big Tech antitrust
    # folded into the Magnificent Seven (the same seven names); the oil basket
    # split into Oil & gas and Fuel costs (airlines, the other side of it).
    # Every ticker was checked against the SEC list that day; the funds
    # (GLD, SLV, UUP, IBIT, ETHA) are listed there too. Membership is
    # editorial: nothing is scored or ranked.
    {"id": "mag-7", "label": "Magnificent Seven",
     "why": "These companies move up or down based on their own earnings, AI news, antitrust rulings and the index flows their size draws.",
     "symbols": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]},
    {"id": "semis", "label": "Semiconductors",
     "why": "These companies move up or down based on chip demand, the chip leaders' earnings and memory prices.",
     "symbols": ["AMD", "AVGO", "MU", "TSM", "QCOM", "TXN", "ADI", "INTC", "ARM"]},
    {"id": "export-controls", "label": "Chip export controls",
     "why": "These companies move up or down based on US rules on selling chipmaking equipment to China.",
     "symbols": ["ASML", "LRCX", "AMAT", "KLAC"]},
    {"id": "ai-capex", "label": "AI spending",
     "why": "These companies move up or down based on AI data-center budgets: the servers, networking and rented AI capacity those budgets buy.",
     "symbols": ["ORCL", "DELL", "ANET", "VRT", "SMCI", "CRWV", "NBIS"]},
    {"id": "ai-tech", "label": "AI software",
     "why": "These companies move up or down based on AI adoption news: new models, enterprise deals and automation.",
     "symbols": ["PLTR", "NOW", "AI", "SOUN", "PATH"]},
    {"id": "ai-power", "label": "AI power demand",
     "why": "These companies move up or down based on data-center electricity demand: power producers, grid equipment and nuclear developers.",
     "symbols": ["VST", "CEG", "TLN", "NRG", "GEV", "BE", "OKLO", "SMR"]},
    {"id": "financials", "label": "Financial Services",
     "why": "These companies move up or down based on interest rates, the yield curve and bank earnings.",
     "symbols": ["JPM", "BAC", "WFC", "GS", "MS", "C", "SCHW", "BLK"]},
    {"id": "rates", "label": "Fed & interest rates",
     "why": "These companies move up or down based on Fed decisions and Treasury yields: homebuilders, mortgage lenders and yield stocks.",
     "symbols": ["DHI", "LEN", "TOL", "RKT", "O", "AMT", "NEE"]},
    {"id": "consumer-credit", "label": "Consumer credit",
     "why": "These companies move up or down based on credit-card delinquencies, loan losses and lending rules.",
     "symbols": ["COF", "SYF", "AXP", "AFRM", "SOFI"]},
    {"id": "energy", "label": "Oil & gas",
     "why": "These companies move up or down based on crude oil and natural gas prices.",
     "symbols": ["XOM", "CVX", "COP", "OXY", "EOG", "SLB", "HAL", "PSX", "MPC"]},
    {"id": "fuel-costs", "label": "Fuel costs",
     "why": "These companies move up or down based on the oil price in reverse: when fuel gets dearer these airlines' costs rise.",
     "symbols": ["DAL", "UAL", "AAL", "LUV", "ALK", "JBLU"]},
    {"id": "bitcoin", "label": "Bitcoin price",
     "why": "These move up or down based on the price of bitcoin: miners, companies holding bitcoin, and the spot bitcoin and ether funds.",
     "symbols": ["MSTR", "MARA", "RIOT", "CLSK", "IREN", "CIFR", "WULF", "HUT", "BMNR", "IBIT", "ETHA"]},
    {"id": "crypto-rules", "label": "Crypto rules & stablecoins",
     "why": "These companies move up or down based on crypto regulation and stablecoin news.",
     "symbols": ["COIN", "HOOD", "CRCL", "GLXY", "XYZ", "PYPL"]},
    {"id": "tariffs", "label": "Tariffs & China trade",
     "why": "These companies move up or down based on tariffs and US–China trade news: makers who source in Asia and China's own giants.",
     "symbols": ["NKE", "DECK", "MAT", "HAS", "CAT", "BABA", "PDD", "JD"]},
    {"id": "health-policy", "label": "Healthcare policy",
     "why": "These companies move up or down based on Medicare rates and drug-pricing rules.",
     "symbols": ["UNH", "CVS", "CI", "HUM", "ELV", "CNC", "MRK", "BMY", "ABBV"]},
    {"id": "obesity", "label": "Obesity drug news",
     "why": "These companies move up or down based on weight-loss drug news: trial results, pricing and insurance coverage.",
     "symbols": ["LLY", "NVO", "VKTX", "AMGN", "HIMS"]},
    {"id": "vaccines", "label": "Vaccines & outbreaks",
     "why": "These companies move up or down based on outbreak headlines, vaccine approvals and public-health guidance.",
     "symbols": ["MRNA", "PFE", "BNTX", "NVAX"]},
    {"id": "geopolitics", "label": "Conflict & defense budgets",
     "why": "These companies move up or down based on wars, conflicts and defense budgets.",
     "symbols": ["LMT", "RTX", "NOC", "GD", "LHX", "KTOS", "AVAV"]},
    {"id": "safe-haven", "label": "Safe havens",
     "why": "These move up or down based on fear in the market: gold, silver and the dollar draw money when investors get scared.",
     "symbols": ["GLD", "SLV", "UUP", "NEM", "AEM", "B"]},
    {"id": "consumer", "label": "Consumer spending",
     "why": "These companies move up or down based on consumer spending data: retail sales, jobs and sentiment.",
     "symbols": ["WMT", "COST", "TGT", "DG", "DLTR", "MCD", "SBUX", "CMG"]},
    {"id": "travel", "label": "Travel demand",
     "why": "These companies move up or down based on travel demand: bookings, hotel and cruise data, and disruptions.",
     "symbols": ["BKNG", "EXPE", "ABNB", "MAR", "HLT", "RCL", "CCL", "NCLH"]},
    {"id": "quantum", "label": "Quantum computing",
     "why": "These companies move up or down based on quantum computing breakthroughs and research headlines.",
     "symbols": ["IONQ", "RGTI", "QBTS", "QUBT", "IBM"]},
    {"id": "space", "label": "Space",
     "why": "These companies move up or down based on rocket launches, space contracts and funding news.",
     "symbols": ["RKLB", "ASTS", "LUNR", "PL", "SPCX"]},
    {"id": "ev-policy", "label": "EV credits & auto tariffs",
     "why": "These companies move up or down based on EV tax credits, emissions rules and auto tariffs.",
     "symbols": ["RIVN", "LCID", "GM", "F", "NIO", "XPEV", "LI"]},
    {"id": "weather", "label": "Storms & disasters",
     "why": "These companies move up or down based on hurricanes, wildfires and storms: insurers, home repair and backup power.",
     "symbols": ["ALL", "TRV", "PGR", "CB", "HD", "LOW", "GNRC"]},
    {"id": "farm", "label": "Crops & fertilizer",
     "why": "These companies move up or down based on crop reports, farm weather and fertilizer prices.",
     "symbols": ["DE", "ADM", "BG", "CTVA", "MOS", "NTR", "CF"]},
    {"id": "freight", "label": "Shipping & freight rates",
     "why": "These companies move up or down based on freight rates, port disruptions and shipping-lane news.",
     "symbols": ["ZIM", "MATX", "DAC", "FDX", "UPS"]},
    {"id": "entertainment", "label": "Box office & live events",
     "why": "These companies move up or down based on box-office weekends, streaming numbers and concert tours.",
     "symbols": ["NFLX", "DIS", "WBD", "IMAX", "CNK", "LYV"]},
    {"id": "betting", "label": "Sports betting & casinos",
     "why": "These companies move up or down based on sports-betting legalization, betting volumes and Las Vegas and Macau numbers.",
     "symbols": ["DKNG", "FLUT", "MGM", "CZR", "PENN"]},
    {"id": "cannabis", "label": "Cannabis rules",
     "why": "These companies move up or down based on cannabis rescheduling, legalization and banking-access news.",
     "symbols": ["TLRY", "CGC", "CRON"]},
    {"id": "breaches", "label": "Cyberattacks",
     "why": "These companies move up or down based on major cyberattacks and data breaches in the news.",
     "symbols": ["CRWD", "PANW", "ZS", "OKTA", "S", "FTNT"]},
    {"id": "lithium", "label": "Lithium & battery metals",
     "why": "These companies move up or down based on lithium prices, EV demand and mine news.",
     "symbols": ["ALB", "SQM", "LAC"]},
    {"id": "copper", "label": "Copper & China stimulus",
     "why": "These companies move up or down based on copper prices, China stimulus and construction data.",
     "symbols": ["FCX", "SCCO", "TECK", "BHP", "RIO"]},
    {"id": "ad-spend", "label": "Ad spending",
     "why": "These companies move up or down based on advertising budgets: ad-market data and each other's earnings.",
     "symbols": ["SNAP", "PINS", "RDDT", "TTD", "APP"]},
    {"id": "luxury", "label": "Luxury & premium brands",
     "why": "These companies move up or down based on high-end spending: Chinese shoppers, tourism and luxury demand.",
     "symbols": ["EL", "TPR", "RL", "CPRI", "LULU"]},
    {"id": "elections", "label": "Election outcomes",
     "why": "These companies move up or down based on election results: private prisons and residential solar swing with who wins.",
     "symbols": ["GEO", "CXW", "FSLR", "ENPH"]},
]


def _load_themes() -> list[dict]:
    raw = os.environ.get("THEMES_JSON")
    if not raw:
        return _DEFAULT_THEMES
    try:
        import json
        parsed = json.loads(raw)
        out = []
        for t in parsed:
            tid, label = str(t["id"]).strip(), str(t["label"]).strip()
            syms = [str(x).strip().upper() for x in t["symbols"] if str(x).strip()]
            if tid and label and syms:
                entry = {"id": tid, "label": label, "symbols": syms}
                if t.get("why"):
                    entry["why"] = str(t["why"]).strip()
                out.append(entry)
        # A malformed override must not silently empty the nav.
        return out or _DEFAULT_THEMES
    except Exception:
        return _DEFAULT_THEMES


THEMES = _load_themes()


CRYPTO_UNIVERSE = [
    s.strip() for s in os.environ.get(
        "CRYPTO_UNIVERSE", "BTC/USD:Bitcoin,ETH/USD:Ethereum,SOL/USD:Solana,"
                           "XRP/USD:XRP,DOGE/USD:Dogecoin,ADA/USD:Cardano,"
                           "AVAX/USD:Avalanche,LINK/USD:Chainlink,DOT/USD:Polkadot,"
                           "LTC/USD:Litecoin,BCH/USD:Bitcoin Cash,UNI/USD:Uniswap,"
                           "AAVE/USD:Aave,SHIB/USD:Shiba Inu,PEPE/USD:Pepe,"
                           "ARB/USD:Arbitrum,POL/USD:Polygon,FIL/USD:Filecoin,"
                           "RENDER/USD:Render,ONDO/USD:Ondo"
    ).split(",") if s.strip()
]
