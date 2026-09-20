# Is AlphaDesk what you are looking for?

Plain answers to the questions people ask before installing it, including the
ones where the answer is no.

## Is this an open-source trading terminal?

**No.** AlphaDesk does not trade, route orders, hold positions or connect to
a broker for execution. It is a **research** terminal: it fetches, checks and
presents market information, and hands the records to you or to your own AI
agent.

If you want to place orders from a terminal, look elsewhere. Earlier versions
of this project did trade, and that was removed on purpose.

## Is this an open-source alternative to a professional market terminal?

For **reading**, largely yes, if you bring your own data. On one board you
get quotes and intraday charts with indicators, news, SEC filings and their
text, XBRL financial statements, insider trades, earnings and corporate
calendars, options chains with implied volatility, crypto, sector and market
movers, and the US Treasury yield curve.

What you do not get: execution, chat with other traders, analyst-desk
research, proprietary consensus estimates, real-time depth-of-book across
every venue, or a support contract. Data quality is whatever your vendor
plan gives you.

## How does it compare to OpenBB?

They overlap and are not the same shape.

| | AlphaDesk | OpenBB |
|---|---|---|
| What it is | A terminal you open: a dense board of panels, plus MCP tools | A Python library and platform you build on |
| AI inside | None. Your own agent reads the records over MCP | Has had AI features and an assistant |
| Data | Your own vendor keys, fetched per reader | Your own keys, many providers |
| Licence | AGPL-3.0 plus a commercial licence | AGPL-3.0 |
| Best for | Reading markets daily, and giving your agent grounded tools | Building your own analytics in Python |

If you want to write Python against a unified data layer, OpenBB is the
better fit. If you want a screen to read, and tools your agent can call,
this is.

## Do I need to pay for market data?

For much of it, no.

- **No key at all:** SEC filings and their full text, XBRL financial
  statements, Form 4 insider trades, company profiles, and the US Treasury
  yield curve. These are public government data.
- **Your own key:** quotes, charts, news, earnings and corporate calendars,
  options chains, crypto, movers. A free Alpaca key covers a great deal.
  Vendors supported include Alpaca, Financial Modeling Prep, Finnhub,
  Polygon, Alpha Vantage, CoinGecko, Tiingo and Marketaux.

AlphaDesk never resells data. Each request runs on your account with that
vendor, under your agreement with them. Check your plan's terms before
running a shared instance for other people.

## What are the MCP tools, and why would I want them?

AlphaDesk exposes 37 read-only tools over the Model Context Protocol, so
Claude, ChatGPT, Codex, Cursor or opencode can read the same records the
screen shows — with your subscription doing the reasoning.

They are written for an agent that cannot see a screen. `market_today`
answers "what is moving" in one call. `price_chart` returns a thinned series
where each point carries its own indicators, because an agent needs the
trajectory rather than a snapshot. `news_search` searches the window by word.
`find_symbol` resolves a name to a ticker off the SEC list, so the agent
checks instead of guessing. `filing_text` and `transcript_text` hand over
whole documents rather than summaries.

Every call runs as the reader whose credential it carries, on that reader's
own vendor keys. There is no write surface.

## Does it use AI to analyse the market?

No, and that is deliberate. No panel is written by a model; every figure is
shown with its source. The only model in the system is a small embedding
model, self-hosted on CPU. It does two jobs: it matches news stories by
meaning, and it tells a fund built on one company from a sector basket that
merely shares its name — it writes nothing, and scores nothing for you. No
text leaves the server, and one setting turns it off.

The reasoning is meant to happen in your own agent, where you can see exactly
what it was given.

## Can I self-host it?

Yes, and that is the main way it is meant to run:

    pip install alphadesk
    python -m alphadesk.main dashboard

Docker works too, and the image bakes the embedding model in. SQLite by
default, Postgres when given a connection string. Two required settings: a
vault key that seals stored vendor keys, and an SEC user-agent string with
contact details. See the README.

## What does it cost?

The software is free under the AGPL-3.0. You pay only for whatever vendor
plans you already use. A commercial licence is available for uses the AGPL
does not suit, and a hosted instance exists, free during early access.

## Is it related to the AlphaDesk order management system?

No. AlphaDesk (this project) is an open-source research terminal. There is an
unrelated commercial order and execution management system of the same name
used by professional asset managers. Where it matters, this project is
written as **AlphaDesk Terminal**.
