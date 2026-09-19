# Data sources

Every upstream AlphaDesk touches, what it is used for, how it is collected, and
whose key it runs on.

Nothing here is legal advice. Where a source's terms matter, the link is the
authority, not this table.

## The rule (2026-09-13)

**The server holds no market-data or news keys.** Every price, headline and
estimate is fetched on a key the signed-in reader connected on
the Account page, under that reader's own agreement with the vendor, and is
served to that reader only. Caches that hold vendor data are keyed by the
reader (and by the vendors they connected), so one reader's entitlement never
answers another's request.

The only sources read without a key are **public government data**: SEC EDGAR
and the US Treasury's yield curve.

Removed on the same date, and not to be reintroduced even as an opt-in:

- **Yahoo Finance via `yfinance`** — an unofficial scrape of the endpoints
  behind Yahoo's own site. It backed charts, quotes, fundamentals, ownership,
  movers and corporate actions.
- **Nasdaq's `api.nasdaq.com` calendar and holdings routes** — undocumented
  endpoints behind Nasdaq's public pages.
- **Keyless CoinGecko and the Coinbase public feed** — crypto now runs on the
  reader's Alpaca or CoinGecko key.
- **The operator's Alpaca stream, shared Polygon news feed and default model
  key** — every reader brings their own.

## Keyless: public government data

| Source | Used for | Collection | Terms |
|---|---|---|---|
| **SEC EDGAR** | filings and their text, Form 4 insider trades, XBRL financial statements (fundamentals, revenue history), the earnings calendar's release instants (8-K Item 2.02 full-text search), the symbol list (`company_tickers_exchange.json`), company names | official public JSON/HTML endpoints | [SEC access policy](https://www.sec.gov/os/webmaster-faq#developers) |
| **US Treasury** | the Treasury yields movers tile (daily par yield curve, change in basis points) | official public CSV | [Treasury data](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics) |

## On the reader's key

Each panel asks the reader's connected vendors in a fixed order and takes the
first that carries the figure. A vendor that refuses on the reader's plan is
noted, and a panel no connected vendor carries answers HTTP 428 with a prompt
naming the vendors (and plans) that would.

| Vendor | What it can serve | Terms |
|---|---|---|
| **Alpaca** (key + secret) | charts (consolidated SIP bars 15 minutes behind on the free plan, Blue Ocean overnight session), quotes, live stock and crypto streams, stock movers, market ETFs, crypto, option chains with implied volatility | [Alpaca terms](https://alpaca.markets/terms) |
| **Finnhub** | key statistics, comparison, peers, analyst ratings, earnings history and calendar, company profile; price targets, rating changes, short interest, fund holdings, institutional ownership, estimates on paid plans | [Finnhub terms](https://finnhub.io/terms-of-service) |
| **Polygon** | charts, quotes, dividends and splits, news; currencies and option movers on paid plans | [Polygon terms](https://polygon.io/terms) |
| **Alpha Vantage** | key statistics, analyst ratings and mean target, estimates, earnings calendar, company profile, ETF holdings and sector weights | [Alpha Vantage terms](https://www.alphavantage.co/terms_of_service/) |
| **Financial Modeling Prep** | key statistics, peers, grades, targets, ETF holdings, dividends and splits, earnings, economic calendar | [FMP terms](https://site.financialmodelingprep.com/terms-of-service) |
| **CoinGecko** (demo or paid key) | the crypto list (worldwide prices, volume, market caps, names — cut to coins the reader can trade when an Alpaca key is also connected), coin profiles; verified against a live Demo key 2026-09-19 | [CoinGecko terms](https://www.coingecko.com/en/terms) |
| **News feeds** (Polygon, Finnhub, Alpaca, Marketaux, Tiingo, …) | the reader's news window, merged across the feeds they keyed | each provider's terms |

Data fetched on your key is governed by your agreement with that vendor.
Plans differ in what they allow — personal or commercial use, display to
other people, storage and attribution — so read your plan's terms (linked
above) before using AlphaDesk in a hosted or shared setting. This is not
legal advice.

## SEC EDGAR — free, but with a rule

SEC filing data is US-government public domain. Two conditions apply:

- **A descriptive User-Agent with real contact info is required** on every
  request. AlphaDesk reads `SEC_USER_AGENT`, which you MUST set; the default is
  a placeholder that identifies nobody. Requests without one get throttled or
  blocked.
- SEC asks for **no more than 10 requests/second**. `ingest/edgar.py` self-limits
  well under that.

One detail that bit twice: a submission record's `acceptanceDateTime` is
true UTC for older filings but labels a SAME-DAY filing's New York time as
UTC (measured 2026-09-14). Release clocks are therefore read from the
filing's own index header (ACCEPTANCE-DATETIME, New York time); the
submissions field is used only for filing lists.

## Licence: resolved (2026-08-18)

AlphaDesk previously depended on `openbb-core` / `openbb-sec`, which are
**AGPL-3.0-only**. AGPL §13 extends to software users interact with over a
network — exactly what this is. Both are removed; they existed for one
feature, SEC Form 4 insider trades, which `ingest/insider.py` reads straight
from EDGAR instead.

## Dependency licences

Checked from installed package metadata:

| Package | Licence |
|---|---|
| alpaca-py | Apache-2.0 |
| polygon-api-client | MIT |
| beautifulsoup4 | MIT |
| pandas | BSD-3-Clause |
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| python-dotenv | BSD-3-Clause |
| cryptography | Apache-2.0 / BSD |
| mcp | MIT |
| pg8000 | BSD-3-Clause |
| sentence-transformers | Apache-2.0 |
| transformers | Apache-2.0 |
| torch (CPU build) | BSD-3-Clause |

No AGPL or other copyleft dependency remains, and none may be added.

**The embedding model** used for search by meaning, **Qwen3-Embedding-0.6B**
(Alibaba), is Apache-2.0. It is self-hosted in the server process and baked
into the image: no news text is sent to a third party, and there is no model
key.

## What AlphaDesk stores

In its database (`ALPHADESK_DATA/ledger.db` locally, Postgres on Cloud SQL
in production). **Vendor data is kept only as long as a feature reads it**,
pruned hourly; removing a key deletes what that key fetched, and deleting an
account deletes every row keyed to it.

| Data | Whose | Kept |
|---|---|---|
| Vendor keys, sealed with AES-256-GCM under `ALPHADESK_VAULT_KEY` | the reader | until removed |
| News stories (headline, summary, url, source, symbols) | the reader | 7 days after publication |
| Full article text (feeds licensed to deliver it) | the reader | 72 hours |
| Headline meaning vectors, for search by meaning | the reader | with their story |
| Company announcements of report dates | the reader | 30 days past the report |
| The earnings forecast log | the reader | 120 days |
| Release-session habits, press-release checks | the reader | 3 days / 24 hours |
| An owner's recent read requests, for prewarming (never the answers) | the owner | 24 hours unused |
| SEC filing metadata, filing text, annual-report sections, 8-K/6-K results releases | public | kept |

Quotes, bars and other vendor figures are otherwise held only in short-lived
in-memory caches keyed by reader. There is no analytics, advertising or
tracking data.
