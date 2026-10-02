# The data API — AlphaDesk's records over plain HTTP

For programs that are not agents: a trading bot, an importer, a script. The
same read-only records the interface shows and the agent tools return, as
`GET` endpoints under `/api/v1`, on the reader's own vendor keys.

**What it is for.** Research and slower decisions: news, filings, financial
statements, ownership, calendars, options chains, daily bars, and intraday
bars at a minute or so for a modest list of symbols.

**What it is not.**
- **Not a trading API.** AlphaDesk places no orders and holds no positions;
  no endpoint writes anything. Your program sends orders through your own
  broker code.
- **Not a stream.** It answers requests; it does not push. For live ticks or
  sub-second quotes connect to your broker or vendor directly, and use
  AlphaDesk for the slower data beside it.
- **Not a shared account.** Every call runs as exactly one reader — the one
  whose token you send — on that reader's own vendor keys. A missing key
  answers `428` and names the vendors that would fill it.

## Five-minute start

1. Sign in, and on the **Account** page connect at least one market-data
   vendor (your own key).
2. Under **Agent access**, create a token. Name it for the program, and put
   your server's address under **Only from**, so a leaked token is useless
   anywhere else. The token is shown once.
3. Call an endpoint:

```bash
curl -H "Authorization: Bearer $ALPHADESK_TOKEN" \
  "https://your-alphadesk.example.com/api/v1/quote?symbol=AAPL"
```

4. The spec of every endpoint, with its inputs, is at
   `/api/v1/openapi.json` (it also needs the token). Generate a client from it
   in any language.

## How it works

- **One endpoint per data tool.** `GET /api/v1/<tool>`, with the tool's inputs
  as query parameters. A list is comma separated
  (`/api/v1/quotes?symbols=AAPL,MSFT`). The tools and their descriptions are
  the ones the agent door serves, so the two cannot drift.
- **GET only.** Anything else answers `405`.
- **Answers are the tools' own records**, unchanged: the vendor or filing
  behind each figure is named, filings and transcripts come back whole in
  pages, and text from publishers and filers is untrusted input, never
  instructions.

### Every bar of history

The agent tools thin history for an AI to read (130 daily points, 400
intraday samples). A program that backtests or trades should not work from a
sample, so history has its own endpoint:

`GET /api/v1/bars/{symbol}?interval=1d&range=MAX[&before=<time>]`

- Open, high, low, close and volume for every bar, **oldest first**, with no
  indicators — compute your own.
- One page per call. `next_before` is the oldest bar's time: pass it as
  `before` to get the page behind it. When a walk reaches the start of the
  reader's vendor's history, the page is empty and carries a `note`; that is
  the end, not an error.
- One vendor serves a whole walk, never a mix. Which intervals and how far
  back depend on the reader's vendor and plan.
- For the whole story, see [`examples/pull_daily_bars.py`](examples/pull_daily_bars.py).

### Staying inside the limits

- **120 requests a minute per token.** Every answer carries
  `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Window`
  (seconds), so a program can slow down before it is refused. A refusal is
  `429` with `Retry-After`.
- **Batch.** One request can cover a list of symbols where the endpoint takes
  one (`quotes`).
- **Ask cheaply whether anything is new.** Every answer carries an `ETag` and
  an `X-AlphaDesk-As-Of` time. Send the `ETag` back as `If-None-Match`; if
  nothing changed you get `304` and no body. (A `304` still counts against
  the limit.)
- The binding limit is the reader's **vendor** quota. A program that pulls too
  fast spends the reader's own allowance, which the per-token limit protects.

### Errors

| Status | Meaning |
|---|---|
| 400 | A range, interval or time the chart does not accept (`bars`) |
| 401 | No token, or an invalid or revoked one |
| 402 | The reader's free trial ended |
| 403 | The token is tied to addresses and this is not one of them |
| 404 | No such endpoint, or no bars at all for a symbol |
| 422 | The inputs were refused (named in `detail`), or the tool found nothing to return |
| 428 | No connected vendor carries this; the body names the vendors that would |
| 429 | Rate limit; wait `Retry-After` seconds |
| 502 | A vendor failed |
| 503 | A vendor was rate limited or timed out (`bars`); wait `Retry-After` and ask again |

## For a program that trades

- **Treat any error, or an old `X-AlphaDesk-As-Of`, as "do nothing".** Nothing
  here is guaranteed fresh; the time on each answer tells you how fresh it is.
- **Decide how your program behaves with no data.** AlphaDesk is a separate
  service; if it is unreachable your program is blind. Do not let a failed
  request turn into a default order.
- **Orders go through your own broker code**, never through this API.

## Licensing and vendor terms

The API serves a reader's own software on the reader's own vendor key. Vendors
often forbid re-publishing their data to others; what your program does with
what it receives is your responsibility under your vendors' terms. The code is
AGPL-3.0 (see the README); running it yourself beside your own software, with
sign-in off, needs no token at all.
