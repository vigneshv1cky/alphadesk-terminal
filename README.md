# AlphaDesk — dense, fast market-research terminal & MCP integration platform

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Commercial licence available](https://img.shields.io/badge/Commercial-licence_available-black.svg)](#licence)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)
![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)
![MCP tools: 37](https://img.shields.io/badge/MCP_tools-37_read--only-6E56CF.svg)

**A dense, fast market-research terminal and integration platform.** Readers
connect their own market-data and news providers; AlphaDesk is the workspace
that connects, checks and presents what those providers — and the public
record at SEC EDGAR and the US Treasury — actually say. Questions are asked
in the reader's **own AI agent** (Claude, ChatGPT, Codex, Cursor, opencode),
which reads the same records through **37 read-only agent tools** (MCP).

AlphaDesk **reads**: quotes and charts, news, SEC filings, financial
statements, ownership and insider activity, earnings and corporate
calendars, options, crypto. It **does not** trade, route orders, hold
positions, score ideas or write summaries.

Two ways to use it — the [managed cloud](#option-a--managed-cloud) or
[your own server](#option-b--self-hosted-agpl-30). The code is open source
under the **GNU AGPL-3.0**, with a **commercial licence** for anyone who
cannot meet its terms. See [Licence](#licence).

---

## Contents

1. [What AlphaDesk is — and is not](#what-alphadesk-is--and-is-not)
2. [Two ways to run it](#two-ways-to-run-it)
3. [Design principles](#design-principles)
4. [Features](#features)
5. [Data sources](#data-sources)
6. [Search](#search)
7. [Agent access (MCP)](#agent-access-mcp)
8. [Accounts, security and privacy](#accounts-security-and-privacy)
9. [Architecture](#architecture)
10. [Repository layout](#repository-layout)
11. [Development](#development)
12. [Configuration reference](#configuration-reference)
13. [Production deployment and operations](#production-deployment-and-operations)
14. [Testing and quality](#testing-and-quality)
15. [Known limitations](#known-limitations)
16. [History](#history)
17. [Licence](#licence)

---

## What AlphaDesk is — and is not

| AlphaDesk is | AlphaDesk is not |
|---|---|
| A **consumption terminal**: it fetches, checks and presents market information | A trading system — there is no order routing, position state or broker integration |
| An **integration platform**: every vendor figure runs on the reader's own key | An aggregator — the server holds no vendor keys and never shares one reader's data with another |
| A **presenter of records**: filings, statements, stories and prices, shown whole with their source | A summariser — no model writes, paraphrases or scores anything here |
| **Pluggable**: news feeds, market data, transcripts and dashboard tiles are swappable providers | A black box — every list is chronological, alphabetical or ordered by the figure it shows |

It is offered **free** at present (payments are designed but switched off;
see [Accounts](#accounts-security-and-privacy)).

---

## Two ways to run it

| | Option A — Managed cloud | Option B — Self-hosted |
|---|---|---|
| Price | **Free during early access.** Planned: $19 a month or $190 a year, announced before it starts | Free |
| Licence | Commercial terms of service — no AGPL obligations for you | GNU AGPL-3.0 |
| You run | Nothing: sign in with GitHub | One container or one Python process, and a database |
| Search by meaning | Included (the embedding model runs on our servers) | Runs on your CPU (~1.2 GB model, 2 vCPU / 4 GiB recommended) or switched off |
| Vendor keys | Your own, connected on the Account page | Your own, in `.env` or the Account page |
| Updates | Continuous | `git pull` and restart |

### Option A — Managed cloud

1. Open the [hosted terminal](https://alphadesk-764298799571.us-east4.run.app)
   and sign in with GitHub — the account is created on first sign-in. (Google
   sign-in admits invited accounts only until Google approves the app.)
2. On the **Account** page, connect the market-data and news providers you
   already use (Alpaca, FMP, Finnhub, Polygon, CoinGecko, Tiingo, …). SEC
   EDGAR and the US Treasury need no key.
3. **It is free during early access** — there is no plan to choose and no
   card to enter. Paid plans ($19 a month or $190 a year, each after a
   14-day trial) will be announced to account holders before they start;
   nobody is charged without subscribing.
4. Optional: connect your own agent from the Account page — a token for
   Claude Code, Codex, Cursor or opencode, or add the server URL as a
   connector in Claude.ai or ChatGPT.

### Option B — Self-hosted (AGPL-3.0)

**You need** a SEC User-Agent with real contact details (SEC blocks
requests without one), Python 3.11+ or Docker, and — for anything beyond
EDGAR and Treasury data — your own vendor keys.

**1. Configure.** Copy the template and fill in the two required values:

```bash
cp alphadesk/deploy/env.example .env
```

| Setting in `.env` | Required | What to put |
|---|---|---|
| `ALPHADESK_VAULT_KEY` | yes | 32 random bytes, base64 — seals stored vendor keys; keep a copy, losing it makes them unreadable |
| `SEC_USER_AGENT` | yes | `AlphaDesk (you@example.com)` — a name and a real email |
| `ALPHADESK_AUTH` | for one person | `off`: a single local account with no sign-in |
| `ALPHADESK_DATABASE_URL` | no | a `postgres://` URL; unset, SQLite in `ALPHADESK_DATA` (`~/.alphadesk`) |
| `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `FMP_API_KEY`, `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `ALPHAVANTAGE_API_KEY`, `COINGECKO_API_KEY` | no | your own keys; sealed into the local account with `python -m alphadesk.main keys import-env` (or connect them on the Account page instead) |
| `ALPHADESK_SEMANTIC_SEARCH` | no | `off` skips the ~1.2 GB embedding model; search then matches words only |
| `GOOGLE_CLIENT_ID` / `GITHUB_CLIENT_ID` (+ secrets), `ALPHADESK_BASE_URL` | for several people | single sign-on for a shared instance |

Generate the vault key with:

```bash
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

**2a. Run with Python.**

```bash
pip install -r requirements.txt
python -m alphadesk.main keys import-env
python -m alphadesk.main dashboard
```

The terminal is at http://127.0.0.1:8000. The first start downloads the
embedding model into the Hugging Face cache.

**2b. Or run with Docker.** The image bakes the embedding model in, so a
container downloads nothing at start:

```bash
docker build -t alphadesk .
```

```bash
docker run -d --name alphadesk -p 8000:8000 --env-file .env -e ALPHADESK_DATA=/data -v alphadesk-data:/data alphadesk
```

With `ALPHADESK_AUTH` left on and no sign-on provider configured, create a
password account inside the container:

```bash
docker exec -it alphadesk python -m alphadesk.main user add you@example.com
```

**3. Keep it private or publish your changes.** Under the AGPL, if you let
other people use a modified copy over a network, you must offer them the
source of your version. Using it yourself, unmodified, or keeping your
changes to yourself on your own machine carries no such obligation. Billing
stays off (`ALPHADESK_BILLING_ENFORCE` is off by default), so every account
on your instance has full access.

---

## Design principles

These are the product. Much of what might look missing was built,
measured and removed on purpose; before proposing to bring something back,
open an issue.

1. **Nothing is paraphrased.** Every panel and agent tool returns what a
   vendor or EDGAR actually said — a filing in pages, a statement series, a
   story's own text. If a figure cannot be shown with its source, it is not
   shown.
2. **Indicators hide when the data cannot support them.** Bar coverage and
   gap size are measured per series; below the floor RSI and MACD are hidden
   rather than drawn over sparse prints that would render identically to a
   liquid name's chart.
3. **Nothing is ranked for you.** The screener window is alphabetical;
   calendars and agent tools order only by the figure on each row. Search
   results are newest first — a model may decide what is *related*, never
   what comes first.
4. **An idle terminal spends nothing.** Background loops fetch only public
   data and each reader's own news; everything else is fetched on request,
   on the requesting reader's keys.
5. **Untrusted text stays untrusted.** Headlines, articles, filings and
   transcripts are data. Nothing here acts on them, and the agent tools that
   return them say so.
6. **Not an aggregator.** Merging several news feeds is the reader's act, on
   their own credentials, for their own window.
7. **The agent surface is read-only and per reader.** Every agent call runs
   as exactly the reader whose token or grant it carries.
8. **Vendor data is the reader's.** No vendor key on the server; no keyless
   route to a commercial vendor or unofficial endpoint; every vendor cache
   keyed by reader; vendor data kept only as long as a feature reads it.

---

## Features

### Pages

| Page | What it shows |
|---|---|
| **Landing** (`/`) | Product overview with blurred screenshots; sign-in and sign-up |
| **Markets** | A composable board: chart, equity overview, funds built on the stock, stock/ETF/crypto/currency/option movers, Treasury yields, heatmap, news |
| **Chart** | Full workspace: candles, line, area, step and other styles; 1-minute to multi-year intervals; indicators and templates; drawing tools (desktop, per visit); multi-chart layouts; overnight, pre-market, after-hours and weekend session shading |
| **Analysis** | One name end to end: chart, filings, price performance, key statistics, earnings history and consensus, analysts, rating changes, financials as filed, splits, dividends, institutional and insider ownership, news. Funds add holdings and breakdown; coins get their CoinGecko record instead of stock-only panels |
| **Profile** | Who a company is: EDGAR registrant facts, the latest 10-K/20-F business and properties sections verbatim, locations, officers; a coin's CoinGecko record |
| **News** | Each reader's merged feeds, three days deep, newest first; filter by words, source or board; search by words and by meaning; an in-page reader with full text where the feed carries it |
| **Earnings** | The week's reporters, dated by the company's own release and joined to its SEC results filing; sessions predicted from history; estimates, actuals, surprise, market cap, volatility, liquidity |
| **Calendars** | Economic releases, dividends, corroborated splits and IPOs |
| **Options** | Chains with implied volatility, calls green and puts red; options flow seen live |
| **Sectors** | Sector funds by weight and dollars traded, with breadth |
| **Baskets** | 36 curated baskets grouped by the *news* that moves them (rates, oil, tariffs, chip export rules, bitcoin, …), plus the reader's own |
| **Portfolio / custom views** | The reader's saved boards |
| **Account** | Coverage matrix of connected vendors and feeds, agent access (tokens and connected apps), sign-in methods and sessions |
| **Admin** | Owners only: accounts, last seen, sign-in methods, sign-out-everywhere, disable, delete |
| **Terms, Privacy, Disclaimer** | Public drafts pending legal review |

### Across the terminal

- **The symbol strip** scopes every page; picking a row adds and selects the
  symbol without moving the page.
- **Composable boards**: show, hide, reorder, size and place tiles; the
  layout lives in the URL, so a link restores the exact board.
- **Live data** where the reader's plan streams it (Alpaca stock, crypto and
  news sockets), polling elsewhere; a 428 prompt names the vendors and plans
  that would fill any panel the reader's keys cannot.
- **Phones**: every page is laid out for a 375-pixel screen as well as a
  desktop.
- **Light and dark themes**, a hand-rolled design system on a 4-pixel grid
  with six type roles, and full keyboard focus handling in every overlay.

---

## Data sources

### Market data — the reader's own keys

| Vendor | Carries (plan-dependent) |
|---|---|
| **Alpaca** | Consolidated (SIP) and IEX bars, overnight (Blue Ocean) session, quotes, movers, crypto, option chains with IV, options flow, corporate actions |
| **Financial Modeling Prep** | Calendars (earnings, economic, dividends, splits, IPOs), key statistics, profiles, analysts, market caps, currencies, press releases, fund data |
| **Polygon (Massive)** | Bars, quotes, movers, currencies, options |
| **Finnhub** | Company metrics, profiles, earnings calendar and sessions |
| **Alpha Vantage** | Company overview, bars |
| **CoinGecko** | Worldwide crypto prices, volume, market caps and coin records |

For each panel the reader's connected vendors are asked in a fixed,
documented order; the first that carries the figure answers. Charts and
option chains are pinned to **one** vendor, never stitched across tapes.

### News — the reader's own feeds

Alpaca (Benzinga), Polygon, Finnhub, Benzinga, Tiingo, Alpha Vantage,
Marketaux and FMP. Several feeds merge into one window per reader,
de-duplicated by URL. Alpaca's news streams live; the rest poll every five
minutes.

### Public data — no key

- **SEC EDGAR**: filings and their text, XBRL financial statements, Form 4
  insider trades, 8-K Item 2.02 and 6-K results releases (release day read
  from the filing itself), ticker and company lists.
- **US Treasury**: the daily par yield curve.

Every source, how it is collected and its terms are listed in
**[docs/data-sources.md](docs/data-sources.md)**. Vendor terms are separate
from the code licence; see [Known limitations](#known-limitations).

---

## Search

News search works two ways at once, everywhere a reader searches — the News
filter box, "Search all" and the agent's `news_search` tool:

- **By words** — one rule shared by the server and the browser: whole words
  in order, plurals matched to singulars, a capitalised ticker matched
  exactly, and a query that names a company also finds stories tagged with
  it ("robinhood" finds stories tagged HOOD).
- **By meaning** — stories whose headline is close in meaning to the query
  are added and marked **related**, so "AI data center spending" finds
  "Equinix plans $5B–$7B annual data center buildout" without a shared
  phrase. This uses **Qwen3-Embedding-0.6B** (Apache 2.0), **self-hosted
  inside the server**: no text leaves AlphaDesk and there is no model key.
  Headlines are embedded once as they arrive; the threshold (cosine 0.50)
  was calibrated so that only on-topic stories are added. Results remain
  newest first.

  The embedding work never competes with the site: the model runs on a
  single CPU thread, the background worker runs at the lowest operating
  system priority, and it embeds only while no request is being served.
  Searches take about a third of a second.

A **coin's** news panel reads all crypto and what moves it — any coin's
stories, crypto stocks, stories naming crypto, and Fed and rates headlines —
each marked with the reason it is there.

---

## Agent access (MCP)

AlphaDesk exposes the same records the interface shows as **37 read-only
tools** over the [Model Context Protocol](https://modelcontextprotocol.io),
at `/api/agent/tools/mcp`. Every call runs **as the reader**, on their keys,
rate-limited to 120 requests a minute per token.

**Connecting**

- **Claude.ai, ChatGPT** — add a custom connector with the server address and
  sign in when asked (OAuth 2.1 with PKCE; one live grant per registered app).
- **Claude Code, Codex, Cursor, opencode** — create a token on the Account
  page under Agent access (shown once, stored hashed, revocable at once); the
  page gives each client's exact setup.

**Tools**

| For | Tools |
|---|---|
| Today | `market_today`, `market_tape`, `movers`, `sector_performance`, `sector_breadth` |
| The reader's names | `my_board`, `quotes`, `screener_window`, `baskets`, `find_symbol` |
| One company | `quote`, `key_stats`, `company_profile`, `fund_profile`, `analyst_view`, `financial_statements`, `earnings_history`, `ownership`, `insider_activity`, `peers`, `compare_metrics` |
| Prices | `price_history`, `price_chart` |
| News | `symbol_news`, `news_search`, `news_story` |
| Filings and calls | `list_filings`, `filing_text`, `transcripts`, `transcript_text` |
| Calendars | `earnings_calendar`, `recently_reported`, `economic_calendar`, `corporate_calendar` |
| Options | `option_expirations`, `option_chain`, `options_flow` |

The tools are written for an agent that cannot see the screen: `find_symbol`
resolves a name to a ticker from the SEC list rather than letting an agent
guess; `price_chart` returns a thinned series carrying each point's RSI and
MACD; `filing_text` and `transcript_text` return whole documents in pages;
`news_search` marks each story as a word or meaning match. Tools that return
publisher or filer text say that it is untrusted input.

---

## Accounts, security and privacy

- **Sign-in**: single sign-on is the only door and is also sign-up — Google
  and GitHub are live, Microsoft is a configuration slot. The email address
  is the account key across providers; each sign-in's method is recorded.
- **Sessions**: HMAC-signed cookie, 14-day lifetime, sign-out everywhere.
- **Vendor keys**: sealed per reader with AES-256-GCM under a master key held
  outside the database; never logged, never shown after entry.
- **Agent credentials**: tokens and OAuth codes stored as SHA-256 hashes;
  OAuth clients sealed; consent page signed, same-site and unframeable.
- **Owners** (configured by email) reach the Admin page; everyone else is a
  reader. **Access is free**: a trial is recorded but the access gate is off
  and no payment processor is configured.
- **Retention — vendor data is kept only as long as a feature reads it**:
  stories 7 days, full article text 72 hours, meaning vectors with their
  stories, company announcements 30 days past the report, the forecast log
  120 days, release habits 3 days, press-release checks 24 hours. Removing a
  key deletes what that key fetched.
- **Deletion**: a reader can delete their account, confirmed by typing its
  email; every row keyed to it is removed in one transaction. The table
  list is checked against the schema by the test suite.
- **No analytics, advertising or tracking.**

The full account, session, key-vault and agent-credential design is in
**[docs/hosted-mode.md](docs/hosted-mode.md)**.

---

## Architecture

```
                       ┌──────────────────────────────────────────────┐
  Browser (React SPA) ─┤  FastAPI · one process · one port            │
  Reader's agent (MCP) ┤                                              │
                       │  /api/*  ── panels, composed per request     │
                       │  /api/agent/tools/mcp ── 37 read-only tools  │
                       │  OAuth 2.1 at the root (/authorize, /token…) │
                       │                                              │
                       │  Per-reader DataRouter ──► reader's vendors  │──► Alpaca · FMP · Polygon
                       │    (ordered per panel; 428 when none carry)  │    Finnhub · Alpha Vantage
                       │                                              │    CoinGecko
                       │  Background:                                 │
                       │    news poll (5 min) + held news sockets     │──► each reader's feeds
                       │    EDGAR results sweep (15 min, weekdays)    │──► SEC EDGAR
                       │    daily earnings forecast capture           │──► Treasury
                       │    embedding worker (search by meaning)      │
                       └──────────────┬───────────────────────────────┘
                                      │
                         Postgres (Cloud SQL) in production
                         SQLite (WAL) in development
```

**Backend** — Python 3.11+. FastAPI with synchronous handlers on a
40-worker thread pool and explicit socket deadlines for every upstream.
Providers are structural Protocols (`NewsProvider`, `PriceProvider`,
`TranscriptProvider`), built per reader from their sealed keys and
discoverable through entry points. The request's reader identity travels in
a context variable; background threads deliberately do not inherit it. The
store speaks SQLite locally and Postgres through the pure-Python `pg8000`
driver in production. The embedding model runs in process on CPU via
sentence-transformers and PyTorch's CPU build.

**Frontend** — TypeScript, React 19 and Vite, built to static files the
Python process serves. Tailwind CSS v4 carries the design tokens (14-pixel
root, 4-pixel spacing grid, six type roles, light and dark). TanStack Query
shares one query per endpoint. There is **no component library and no chart
library**: primitives are hand-rolled, and the chart is AlphaDesk's own SVG
renderer, with candles batched into four paths so the node count is
constant in bar count.

---

## Repository layout

```
alphadesk/
  main.py            entry point: web server + background loops, and the CLI
  app/               FastAPI app, auth, admin, agent access (tokens, OAuth, MCP mount)
  providers/         the plugin seams, vendor implementations, catalogue, per-reader router
  ingest/            EDGAR, news polling, calendars, movers, prices and indicator math
  desk/              screener window, filings, transcripts, market-today
  ledger/            store (SQLite / Postgres), database adapter, key vault
  mcp_server.py      the agent tools
  semantic.py        search by meaning (self-hosted embedding model)
  cryptonews.py      a coin's news selection
  newsquery.py       the word-search rule
  billing.py         owners, trial, the (off) access gate and payment seam
  config.py          settings, retention, curated baskets
  ui/                React 19 + Vite frontend (built into app/static)
  deploy/            deployment guide and the configuration template
docs/                data sources, providers, widgets, hosted mode
scripts/deploy.sh    build on Cloud Build and roll the Cloud Run service
tests/               pytest suite
```

---

## Development

### Prerequisites

- Python **3.11+**, Node with **pnpm**
- A **SEC User-Agent** string with real contact details (SEC requires one)
- Your own vendor keys for anything beyond EDGAR and Treasury
- About 1.5 GB of disk for the embedding model, downloaded on first use (or
  set `ALPHADESK_SEMANTIC_SEARCH=off`)

### Set up and run

```bash
pip install -r requirements.txt
cp alphadesk/deploy/env.example .env        # then edit: vault key, SEC user agent
python -m alphadesk.main dashboard          # API + built SPA on http://127.0.0.1:8000
```

Generate a vault key (32 random bytes, base64):

```bash
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

For local work without sign-in, set `ALPHADESK_AUTH=off` (one local
account), put your own vendor keys in `.env`, and seal them into that
account:

```bash
python -m alphadesk.main keys import-env
```

Frontend with hot reload (proxies `/api` to the running server):

```bash
cd alphadesk/ui && pnpm install && pnpm dev
```

### Command line

| Command | Purpose |
|---|---|
| `python -m alphadesk.main dashboard` | The web server and background loops |
| `python -m alphadesk.main keys import-env` | Development: seal `.env` vendor keys into the local account |
| `python -m alphadesk.main earnings` | Stamp today's EDGAR results releases and list the last three days |
| `python -m alphadesk.main backfill --hours 72` | Backfill EDGAR results releases |
| `python -m alphadesk.main calendar-accuracy --days 30` | Score calendar vendors against EDGAR release days |
| `python -m alphadesk.main mcp [--http]` | The agent tools standalone (EDGAR only — no reader identity) |
| `python -m alphadesk.main user …` | Manage password accounts for instances without SSO |

### Extending

- **Providers**: implement a Protocol and register it through a local module
  (`ALPHADESK_PLUGINS`) or the `alphadesk.providers` entry point —
  **[docs/providers.md](docs/providers.md)**.
- **Dashboard tiles**: register a widget in `ui/src/widgets/`, or serve tiles
  from an external JSON backend (`ALPHADESK_WIDGET_BACKENDS`) —
  **[docs/widgets.md](docs/widgets.md)**.
- Conventions and checks: **[CONTRIBUTING.md](CONTRIBUTING.md)**. Several
  obvious improvements were tried and deliberately undone; open an issue
  before changing behaviour.

---

## Configuration reference

Environment variables (also read from `.env`). Only the first two are
required.

| Variable | Purpose |
|---|---|
| `ALPHADESK_VAULT_KEY` | **Required.** 32 bytes, base64: seals every reader's keys. Losing it makes them unreadable |
| `SEC_USER_AGENT` | **Required.** Descriptive User-Agent with contact details, as SEC asks |
| `ALPHADESK_DATABASE_URL` | Postgres connection string; unset uses SQLite in `ALPHADESK_DATA` |
| `ALPHADESK_DATA` | Data directory for SQLite (default `~/.alphadesk`) |
| `ALPHADESK_AUTH` | `off` for a single local account without sign-in |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google sign-in (likewise `GITHUB_…`, `MICROSOFT_…`) |
| `ALPHADESK_BASE_URL` | Public URL; OAuth redirects and the agent host allowlist depend on it |
| `ALPHADESK_SECRET` | Session signing secret |
| `ALPHADESK_COOKIE_SECURE` | Secure cookies (on behind HTTPS) |
| `ALPHADESK_OWNER_EMAILS` | Owner accounts (Admin page, never gated) |
| `ALPHADESK_TRIAL_DAYS` / `ALPHADESK_BILLING_ENFORCE` / `ALPHADESK_BILLING_PROVIDER` | Trial length, access gate (`on` for the managed service; off by default), payment processor (`stripe` when a Stripe key is set) |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Managed service only: Stripe checkout and signed webhooks at `/api/billing/webhook`. Unset, checkout answers 503 and nothing is charged |
| `STRIPE_PRICE_ID_MONTHLY` / `STRIPE_PRICE_ID_YEARLY` | The two plans' Stripe price IDs ($19 a month, $190 a year) |
| `ALPHADESK_SEMANTIC_SEARCH` | `off` disables search by meaning |
| `ALPHADESK_EMBED_MODEL` / `ALPHADESK_SEMANTIC_THRESHOLD` | Embedding model (default Qwen/Qwen3-Embedding-0.6B) and similarity cutoff (0.50) |
| `ALPHADESK_PLUGINS` / `ALPHADESK_WIDGET_BACKENDS` | Provider plugins; external tile backends |
| `NEWS_REFRESH_MINUTES` / `NEWS_LOOKBACK_HOURS` / `NEWS_KEEP_DAYS` | News poll interval (5), window (72 h), retention (7 days) |
| `CHART_MIN_COVERAGE` / `CHART_MAX_MEDIAN_GAP_MIN` | The indicator coverage gate |
| `DASHBOARD_HOST` / `DASHBOARD_PORT` | Web server bind (Cloud Run injects `PORT`) |
| `MCP_HOST` / `MCP_PORT` | Standalone agent server bind (default port 8010) |

The full annotated template is `alphadesk/deploy/env.example`; every
setting's default lives in `alphadesk/config.py`.

---

## Production deployment and operations

The reference service runs on **Google Cloud Run** (`alphadesk`, us-east4)
with **Cloud SQL for Postgres**.

| Setting | Value | Why |
|---|---|---|
| Size | 2 vCPU, 4 GiB | The embedding model and the web server share the instance |
| Instances | exactly 1 (min = max = 1) | One writer for the background loops and live sockets |
| CPU | always allocated, startup boost | Background loops run between requests |
| Image | Python 3.12 slim, PyTorch CPU build, model baked in (~1.2 GB) | Nothing is downloaded at start; model loads in seconds |

**Deploying** — continuous integration runs the tests, lint and build on
every pull request; deploying stays a maintainer's step. After a merge to
`main`:

```bash
scripts/deploy.sh
```

The script refuses unless the checkout is a clean `main` matching the
remote, builds the image on Cloud Build, rolls the service with the new
image only (environment, database mount and scaling untouched), and checks
that the live page serves the new build. The frontend bundle is committed
under `alphadesk/app/static`, so the image needs no Node build step.

**Operations**

- Logs: Cloud Logging for the `alphadesk` service; the ingest loops,
  pruning and the embedding worker log their progress there.
- Always-on is required as built; approximate cost at this size is
  $110–120 a month for the service (plus Cloud SQL). The lever for cost is a
  smaller embedding model, not scaling to zero.
- Graceful shutdown is bounded: a revision stops within seconds.
- **Kill switch for search by meaning.** If the service ever slows or
  refuses requests, turn it off without a rebuild — search falls back to
  words alone:

  ```bash
  gcloud run services update alphadesk --region us-east4 --update-env-vars ALPHADESK_SEMANTIC_SEARCH=off
  ```

  Always use `--update-env-vars` (adds or changes one variable), never
  `--set-env-vars` (replaces every variable). The worker's start-up log line
  reports the cores the machine claims and the thread the model uses
  (expected: one).
- **Background work is shipped switched off, then enabled and watched.** A
  2-vCPU container reports more cores than it has, so behaviour on a
  many-core laptop does not predict production: sizing threads from the
  reported core count once starved the web server of a live instance.

---

## Testing and quality

| Check | Command | Scope |
|---|---|---|
| Backend tests | `python -m pytest -q` | ~720 tests: providers, calendars, EDGAR parsing, news rules, search, agent tools, auth, accounts, retention |
| Frontend tests | `cd alphadesk/ui && pnpm test` | Pure logic under `src/lib/__tests__` (chart scales, sessions, news matching, layouts) |
| Type-check and build | `cd alphadesk/ui && pnpm build` | `tsc -b` (project references — `tsc --noEmit` checks nothing here) then Vite |
| Lint | `python -m ruff check alphadesk` | Python |

---

## Known limitations

- **Vendor terms.** Market data is fetched on your own key, under your own
  agreement with each vendor, and those terms govern how you may use it.
  Plans differ — some are personal, some restrict display to others or
  storage — so check your plan before using AlphaDesk in a hosted or shared
  setting. Each vendor's terms are linked in
  [docs/data-sources.md](docs/data-sources.md).
- **Untested paths.** Some paid-plan surfaces (Alpha Vantage, Finnhub
  premium, Polygon paid) were built from documentation and have not been
  exercised against a live key.
- **Search by meaning** reads headlines only (summaries would cost several
  CPU-hours a day per reader), and a new deployment embeds the stored
  backlog before older stories can match by meaning.
- **Legal pages** are drafts awaiting counsel.

---

## History

Earlier versions of this repository traded. Two autonomous engines were
built, measured against the S&P 500 and deleted in August 2026 (**−0.072%**
mean alpha over 503 backtested trades; **−1.123%** over 44 live exits); the
manual booking and grading layer followed when the product became a
consumption terminal. Screener ranking, operator-held data and unofficial
sources, the in-app agent and the in-app language model were each removed
in turn, each for a measured or stated reason. The one
model that remains is the self-hosted embedding model used for search.

---

## Licence

AlphaDesk is **dual-licensed**. Copyright © 2026 Vignesh Murugan.

**Open source — GNU AGPL-3.0** ([LICENSE](LICENSE)). You may use, study,
modify and redistribute AlphaDesk. The AGPL is a strong copyleft licence with
one clause beyond the GPL: if you run a **modified** copy and let others use
it **over a network**, you must offer those users the complete source of
your version under the same licence. Distributing copies, modified or not,
likewise carries the source with it. Running it for yourself imposes
nothing.

**Commercial licence.** For organisations that want to embed AlphaDesk in a
proprietary product, run a modified hosted service without publishing their
changes, or need an enterprise exception, a commercial licence is available
— contact **muruganvignesh0810@gmail.com**. The **managed cloud** is offered under its
own terms of service; subscribers take on no AGPL obligations.

**Contributions** are accepted under a [contributor licence agreement](CLA.md),
so the project can continue to offer both licences; contributors keep the
copyright in their work.

**Dependencies** are all under permissive licences (MIT, ISC, BSD, Apache
2.0), and no copyleft dependency may be added — it would prevent the
commercial licence. The web interface ships its third-party notices at
`/third-party-notices.txt`, written by every build from the packages the
bundle actually contains (the fonts are under the SIL Open Font License). The embedding model, Qwen3-Embedding-0.6B, is Apache 2.0.

**Data is not code.** The code licence grants nothing over market data. Each
vendor's terms govern the data fetched on your key; see
[docs/data-sources.md](docs/data-sources.md).
