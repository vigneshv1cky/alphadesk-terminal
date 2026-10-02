# A read-only REST data API for bots and trading agents

Status: design, agreed 2026-10-02. Nothing is built yet.

## Purpose

Let programs that live on other servers (trading bots, execution software,
agent runtimes) read what AlphaDesk shows its reader, on the reader's own
vendor keys, without ever holding those keys.

AlphaDesk stays what `DECISIONS.md` says it is: a consumption terminal. It
places no orders, holds no positions and gains no write surface. The builder's
own code does all execution, through the builder's own broker.

## Decisions taken, and why

| Decision | Why |
|---|---|
| No trading in AlphaDesk, and no sibling trading service | Rules 1, 5 and 9 in `DECISIONS.md`; `tests/test_mcp.py` fails on any tool that mutates state. The consent page promises "read-only tools". |
| A plain REST API in addition to MCP | Today the only programmatic door is MCP. A bot written as ordinary code has to speak MCP just to read a quote. The ordinary `/api/*` endpoints accept only the browser's session cookie. |
| Generate the endpoints from the tool list | One source of truth. A tool added later appears in both doors with no extra work, and the surfaces cannot drift. |
| Reuse the existing gate | `app/agent_tools.py` already verifies the token, applies the billing gate and the rate limit, and sets the request's reader. Reusing it keeps one place to secure. |
| Pasted token first, OAuth later | A 24/7 unattended bot suits a revocable, non-expiring token. OAuth's one-hour access token depends on a refresh token replaced on every use; a crash between receiving and saving it logs the bot out until the reader approves again. OAuth is built for outside apps acting for many readers. |
| Full-resolution history gets its own endpoints | The agent tools thin daily history to 130 points and intraday bars to 400 samples. A program that backtests or trades must not silently work from a sample. |

## Scope

In scope: GET endpoints over the existing data tools; full-resolution bars;
a published machine-readable spec; per-token address allowlist; developer
documentation and a client library.

Out of scope: orders, positions, accounts, streaming or push of any kind,
and any change to what a reader's keys may reach. For live ticks or
sub-second quotes the builder should connect to the broker or vendor
directly and use AlphaDesk for the slower data beside it.

The first target is slow data: news, filings, fundamentals, calendars, daily
bars, and intraday bars at a minute or so for a modest symbol list.

## Architecture

```
 builder's server                           AlphaDesk (Cloud Run)
 ┌──────────────┐   GET + bearer token     ┌──────────────────────────────┐
 │ bot / agent  │ ───────────────────────► │ token gate (existing)        │
 │ own broker   │                          │  - verify token, billing,    │
 │ code         │ ◄─────────────────────── │    rate limit, allowlist     │
 └──────────────┘   JSON, as-of, source    │  - run as that reader        │
                                           │ REST layer (new, generated)  │
                                           │ tool functions (existing)    │
                                           │ per-reader data router       │──► reader's vendors,
                                           └──────────────────────────────┘    SEC EDGAR, Treasury
```

The REST layer mounts beside the agent tools under a single versioned
prefix. It does not call the web panels' own endpoints.

## Surface

- One GET endpoint per data tool, named from the tool, with the tool's inputs
  as query parameters. List-valued inputs are comma separated.
- Any method other than GET is refused. There is no endpoint that changes
  anything.
- A machine-readable spec of every endpoint is published at a fixed address.
  Inputs are described firmly; outputs are described by example at first.
  Typed response schemas are added for the endpoints builders actually use.
- A missing vendor key answers HTTP 428 naming the vendors that would fill
  the gap, never an empty 200 (rule 10).
- Text from publishers and filers keeps the warning that it is untrusted
  input (rule 7).

## Full-resolution history

- Daily and intraday bars are returned unthinned, oldest first, one record per
  bar with open, high, low, close and volume.
- They page by time. A response says whether more exists and carries the
  cursor for the next page, so a program can walk back as far as the reader's
  vendor carries.
- Each response names the vendor and the session boundaries. A series is one
  tape and is never stitched across feeds (rule 3).
- RSI and MACD are not returned. The program computes its own; the rule that
  indicators hide when coverage is thin stays with the chart (rule 2).

## Staying inside the limits

- The existing limit of 120 requests a minute per token stands.
- Batch reads are the main lever: quotes take a list, and other endpoints
  accept comma-separated symbols where it makes sense.
- Every response carries remaining-quota and reset headers. A refusal is HTTP
  429 with a retry-after time.
- Every response carries an as-of timestamp and a validator, so a program can
  ask whether anything is new and receive a cheap empty answer.
- The binding limit is the reader's vendor quota. A program that pulls too
  fast spends the reader's own allowance, which is what the per-token cap
  protects.

## Authentication

- Credential: the reader-created token (`adk_...`) from the Account page under
  Agent access. Stored only as a hash, shown once, revocable at once, at most
  ten live per reader.
- The bot gets its own token with a clear label, so it can be revoked without
  disturbing other agents.
- New: an optional allowlist of source addresses per token. A request from an
  address outside it is refused before any data is read.
- OAuth 2.1 with PKCE (already built for MCP connectors) covers apps that act
  for many readers. It is designed but not extended to REST until someone
  needs it. The consent page must then say the app can read market data and
  cannot place orders or change anything.

## Errors

| Status | Meaning |
|---|---|
| 401 | No token, or an invalid or revoked one |
| 402 | The reader's free trial ended |
| 428 | No connected vendor carries this surface; names the vendors |
| 429 | Rate limit; carries a retry-after time |
| 502/503 | A vendor failed; names the vendor so "no news" is distinguishable from "news feed down" |

Guidance for bots: treat any error, or an old as-of timestamp, as "do
nothing".

## Tests

1. Read-only proof: a test walks every endpoint, asserts each is GET only, and
   fails if a write route ever appears. It extends the check that guards the
   agent tools.
2. Coverage: every data tool has a matching endpoint, and adding a tool
   without one fails.
3. Reader isolation: two readers with different keys never see each other's
   data, and removing a key removes what it fetched.
4. Bars: count and order match the vendor's, with no thinning; paging by time
   loses and duplicates nothing.
5. The 401, 402, 428 and 429 paths each have a test.
6. Allowlist: a request from outside a token's allowlist is refused.
7. Untrusted-text warnings survive into the REST responses.

## Packaging for builders

1. A one-page quickstart: create an account, connect a vendor key, make a
   token, pull a quote and a year of daily bars in minutes.
2. A thin Python client (TypeScript later) that wraps the REST API, handles the
   token, backs off on rate limits and returns typed records.
3. Honest safety guidance: check the as-of time; it is polling, not
   streaming; orders go through the builder's own broker code.
4. A self-hosting guide for people who want independence or higher limits,
   with the AGPL explained in plain words. A copy beside the builder's own
   software needs no sign-in and no OAuth.
5. Provenance in every response is the headline feature.

## Risks and open questions

- Every end user needs their own vendor keys; the server holds none and never
  shares one reader's data with another. A builder cannot run an app for many
  people on one shared account. The onboarding flow must make connecting keys
  easy.
- Capacity: outside apps spend the server's capacity. Cloud Run needs
  monitoring and, if usage grows, a warm instance and limits that survive
  more than one instance (the limiter is kept in memory per instance).
- Vendor terms often forbid re-publishing data. The API serves a reader's own
  software on their own key; the reader remains responsible for what their
  program does with it, and the documentation must say so.
- The response schemas for the endpoints builders use first are not yet
  declared. Which endpoints those are decides what is typed first.
- The contributor licence check currently marks commits authored as the AI
  assistant as unsigned. Commits for this work should be authored as the
  owner with the assistant as co-author.
