# Writing a provider

AlphaDesk talks to the outside world through three seams: the **LLM**, the
**news feed**, and **market data**. Each is a `Protocol` in
`alphadesk/providers/base.py`. A provider is any object with the right shape —
you do not subclass anything, and a provider package need not import AlphaDesk
at all except to register itself.

## The contracts

```python
class LLMProvider(Protocol):
    name: str
    def chat_json(self, system: str, user: str, *,
                  max_tokens: int = 2048, timeout_s: float = 60.0) -> ChatResult: ...

class NewsProvider(Protocol):
    name: str
    capabilities: tuple[str, ...]   # from: summaries, full_bodies, images, bylines
    def fetch(self, since: datetime, limit: int = 200) -> list[Article]: ...

class PriceProvider(Protocol):
    name: str
    # Company and market data
    def context(self, symbol) -> dict | None: ...
    def chart_series(self, symbol, days=2, range_key=None, interval=None) -> dict | None: ...
    def fundamentals(self, symbol) -> dict | None: ...
    def institutional_ownership(self, symbol) -> dict | None: ...
    def earnings_context(self, symbol) -> dict | None: ...
    def earnings_insights(self, symbol) -> dict | None: ...
    def macro(self) -> dict | None: ...
    def sector_change_pct(self, sector) -> float | None: ...
    # Quote, board and movers surfaces
    def quote(self, symbol) -> dict | None: ...
    def movers(self, top=20) -> dict: ...
    def market_tape(self) -> list[dict]: ...
    def index_board(self) -> list[dict]: ...
    def crypto_movers(self, top=20) -> dict: ...
    def category_movers(self, category, top=20) -> dict | None: ...   # optional
    def economic_calendar(self, start, end) -> list[dict] | None: ...  # optional
    # Options
    def option_expirations(self, symbol) -> list[str]: ...
    def option_chain(self, symbol, expiry) -> dict: ...
```

Raise `ProviderError` for anything that goes wrong.

`PriceProvider` is the widest of the three and every method is load-bearing
for some page — a provider missing one breaks that surface, not the app. Two
that are easy to get wrong:

- **`chart_series`** must return the coverage statistics alongside the bars, not
  just the bars. `range_key` selects the SERIES rather than merely its length
  (switch to daily bars past your minute feed's reach), and `interval` is a
  preference: serve a coarser one and report which you served rather than
  refusing. See `alphadesk/providers/base.py` for the full docstrings — that
  file is the contract, this page is the tour.
- **`category_movers` is the movers seam** (2026-09-13). The Markets board
  draws nine categories — stocks, crypto, ETFs, mutual funds, options,
  indices, futures, bonds, currencies — and asks the selected provider for
  each one first. Answer `{tabs: [{id, label, rows: [{symbol, display, name,
  price, change_pct, volume}]}]}` for a category your feed carries whole
  and `None` for the rest: the free path (Yahoo's screeners, CoinGecko, the
  option chains) then serves those, so a keyed feed replaces what it can
  and never blanks a tile. Twenty-session volatility and average dollar
  volume are added by the route afterwards from one source for everyone,
  and the reader's floors apply on top. The shipped Polygon provider
  answers stocks (the full US snapshot, so active, gainers and losers come
  from one request with no market-cap cap) and currencies (the forex
  snapshot mapped onto the same pairs the free tile lists); Finnhub and
  Alpha Vantage decline every category.
- **`economic_calendar` is a keyed surface** (2026-09-13). Scheduled
  releases with consensus, previous and actual for an ISO date window:
  `[{time, country, event, impact, actual, estimate, previous, unit}]`.
  There is no free structured source, so the builtin answers `None` and the
  Earnings page's panel names the key that would fill it. Finnhub
  implements it (`/calendar/economic`, a premium-plan endpoint; a free key's
  403 is reported as a plan refusal, not an empty week). The operator's
  `FINNHUB_API_KEY` serves it even when the selected price provider is the
  builtin, the way the earnings calendar and peers use that key.
- **Report thin data honestly.** A provider that cannot measure coverage should
  report its indicators as unreliable rather than omit the field. The UI hides
  RSI/MACD on that signal, and drawing them anyway is the one failure this
  project treats as a bug.
 Callers catch it, drop the
item and log why — a provider failure degrades one feature, it never takes down
a page.

## A minimal news provider

```python
from datetime import datetime
from alphadesk.providers import Article, ProviderError, register

class MyNews:
    name = "mynews"

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        try:
            rows = my_client.headlines(after=since, count=limit)
        except Exception as exc:
            raise ProviderError(f"mynews failed: {exc}") from exc
        return [
            Article(
                id=str(r["id"]),
                title=r["headline"],
                url=r["link"],
                published_at=r["ts"],          # ISO 8601
                symbols=r["tickers"],          # REQUIRED — see below
                summary=r.get("teaser", ""),
                source=r.get("publisher", ""),
            )
            for r in rows
        ]

register("news", MyNews.name, MyNews)
```

Register the **factory**, not an instance: construction may read config or open
a client, and that should not happen for providers nobody selected.

### Two things a news provider must get right

**`symbols` is not optional.** The screener groups the entire window by ticker.
A feed that cannot say which symbols an article is about cannot back this app.

**Return newest first.** Callers apply a hard cap, so the only correct thing to
drop under that cap is the oldest news.

This is also why a per-symbol-only feed is a poor fit: covering
the window would take one request per symbol per poll, and you could only ever
find news for symbols you already track — which removes discovery, the point of
the window.

## Getting your provider loaded

Three ways, in increasing order of decoupling:

**1. Local module** — set `ALPHADESK_PLUGINS` to a comma-separated list of
import paths. Importing is enough, since the module registers itself.

```ini
ALPHADESK_PLUGINS=myplugins.news,myplugins.llm
```

**2. Entry point** — a published package is discovered automatically once
installed, with no config:

```toml
[project.entry-points."alphadesk.providers"]
mynews = "mypackage.providers:register_all"
```

**3. Fork** — add it to `alphadesk/providers/` and register it in `builtin.py`.

Built-ins load first, so registering an existing name deliberately **replaces**
it: `register("news", "polygon", MyBetterPolygon)` overrides the shipped one
without patching this repo.

## Selecting one

There is no server-side selection (2026-09-13): the server holds no vendor
keys. A reader selects a provider by connecting its key on the Account page,
and the provider is built per reader from that key. For market data a reader
may connect several vendors; `providers/catalogue.py` lists, per panel, the
vendors that carry it and on which plan, and the router asks the reader's
connected vendors in that order. A method that returns `None` means "not
carried" and the next vendor is asked; an entitlement error is noted; when
none answers, the request fails with HTTP 428 and a prompt naming the vendors
that would.

A new market-data vendor therefore needs an implementation registered under
`prices` and an entry in the catalogue for each panel it can serve.

## Shipped providers

| Kind | Name | Notes |
|---|---|---|
| llm | `openai-compatible` | DeepSeek, OpenAI, Groq, OpenRouter and other hosted presets — base URL and model come with the reader's key |
| llm | `anthropic` | Messages API; JSON is forced by prefilling the assistant turn |
| llm | `gemini` | Google's Generative Language API |
| news | `polygon`, `alpaca`, `finnhub`, `benzinga`, `tiingo`, `alphavantage`, `marketaux`, `fmp` | ticker-tagged feeds; a reader keying several has their window merged |
| prices | `alpaca` | SIP bars (15 minutes behind on the free plan), overnight session, quotes, streams, movers, crypto, option chains |
| prices | `finnhub` | key statistics, analysts, peers, earnings history and calendar, profile; more on paid plans |
| prices | `polygon` | bars, quotes, dividends and splits; currencies and option movers on paid plans |
| prices | `alphavantage` | overview-based statistics, estimates, earnings calendar |
| prices | `fmp` | statistics, peers, grades, ETF holdings, corporate actions, economic calendar |
| prices | `coingecko` | crypto movers and coin profiles |

## Testing yours

`isinstance` works against these Protocols, so the cheapest possible test is:

```python
from alphadesk.providers import base
def test_shape():
    assert isinstance(MyNews(), base.NewsProvider)
```

See `tests/test_providers.py` for how the built-ins are covered.

## News is capability-driven, not vendor-driven

The intended shape for a bring-your-own-keys deployment, already wired:

**The article is the contract.** `Article` carries `summary`, and best-effort
`image_url`, `author` and `body`. The UI never branches on the provider name —
each story renders exactly what it carries, and an absent field is an absent
element, never an empty box. `body` is the full article text, PLAIN, and it is
sanitized at ingestion (`providers/news._strip_html`), not in the browser:
nothing executable and no markup survives into the stored record, so it is
safe wherever it is later rendered — the web reader, the MCP tools, an
agent's context.

**The provider declares what its feed delivers** via `capabilities`, drawn
from `summaries`, `full_bodies`, `images`, `bylines`. The declaration is
never used for rendering (the per-article rule covers that); it is read for
FRAMING: the reader's closing line ("read the full story at the source"
versus a plain attribution) and the settings surface, which states what a
key unlocks so the difference between feeds is learned where the key is
chosen. Declare only what the feed actually ships.

Shipped declarations, both verified against live payloads:

- `polygon` — `summaries, images, bylines`. The payload has no body field at
  any tier; the full text stays with the publisher.
- `alpaca` — `summaries, full_bodies, images, bylines`. Benzinga articles
  arrive with full HTML content, stripped to plain text at ingestion.

A new news provider is therefore a backend-only event: map the feed onto
`Article`, declare capabilities honestly, register — the reader, the tiles
and the settings surface need no changes. Keys are entered on the Account page
and sealed in the vault; see [hosted-mode.md](hosted-mode.md).
