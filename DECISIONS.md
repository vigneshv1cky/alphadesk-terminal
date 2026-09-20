# Decisions

Why AlphaDesk is built the way it is, and what was tried and deliberately
undone. Read this before proposing a change in behaviour: much of what looks
missing was built, measured and removed.

None of this is fixed forever. It is a record of what has already been
weighed, so a proposal can start from new evidence rather than from scratch.

## What AlphaDesk is

A **consumption terminal**: it fetches, checks and presents market
information. It does not trade, hold positions, route orders or score
decisions. It is an **integration platform**: readers bring their own vendor
keys, and the news feed, market data, transcripts and dashboard tiles are all
swappable plugins.

## The rules that are the product

Breaking one of these is a bug even if the tests pass.

1. **Nothing is paraphrased.** Every panel and every agent tool returns what
   a vendor or the SEC actually said — a filing in pages, a statement series,
   a story's own text — never a summary of it. The reader's own AI agent does
   the reading. If a figure cannot be shown with its source, it is not shown.

2. **Indicators hide themselves when the data cannot support them.** Bar
   coverage and the median gap between bars are measured; below the floors,
   RSI and MACD are hidden rather than drawn. One thinly traded stock had 92
   bars across five sessions with 42-minute gaps against another's 1,570 at
   one-minute spacing — and both charts looked equally convincing. Do not
   "fix" this by drawing anyway: a misleading chart is worse than no chart,
   because it recruits the reader's judgment.

3. **A price series is one tape, never stitched.** One exchange's feed is
   about 2% of volume; mixing it with the consolidated tape once drew a
   closing auction as a 2,000-fold spike. The single exception is the
   overnight session, which has one venue, so unioning it adds no second
   scale.

4. **The only model here reads, it never writes.** A self-hosted embedding
   model, on CPU, in the same process: it matches news by meaning and tells
   a fund built on one company from a sector basket sharing its name. It
   runs on an idle worker, never inside a request — measured at 6.6 seconds
   for fourteen names, inline that is what starved the web server once. No
   generative model writes, summarises or scores anything.

5. **Nothing is ranked by us.** The screener window is a plain alphabetical
   read: sorting a column is the reader choosing, a default order is the app
   deciding. Alphabetical is also stable, so rows do not reshuffle under the
   cursor while polling. Agent tools may order today's facts by a measured
   number that is shown on the row (percent change, volume, story count,
   market capitalisation, release time) — never by a score or a weighting.
   Search results are newest first even when meaning decided what is
   relevant.

6. **An idle terminal spends nothing.** No background summarising, no
   unattended labelling. The background loops fetch: the SEC releases, each
   reader's own news feed, one daily forecast capture. Everything else is
   fetched on request, on the asking reader's keys.

7. **Untrusted text stays untrusted.** Headlines, article bodies, filings and
   transcripts can carry text aimed at whoever reads them. Nothing here acts
   on them, and the agent tools that hand them over say so, so the reader's
   agent treats them as data. Any future surface that feeds this text to
   something that acts must re-establish that fence.

8. **The platform is not an aggregator.** There is no shared news feed.
   Aggregation is the reader's own act on their own credentials: keying
   several feeds merges their window and nobody else's.

9. **The agent surface is read-only, one reader at a time.** The agent tools
   have no write surface by construction, and every call runs as exactly the
   reader whose credential it carries.

10. **Vendor data belongs to the reader whose key fetched it.** The server
   holds no vendor keys. Providers take keys explicitly; a missing key is an
   error, never an environment lookup. Every cache holding vendor data is
   keyed by the reader — a shared cache serving the next reader is
   redistribution. Keyless sources are public government data only (SEC
   EDGAR, the US Treasury). A panel no connected vendor carries answers HTTP
   428 naming the vendors and plans that would fill it, never an empty 200:
   an empty panel reads as "no data exists".

11. **Vendor data is kept only as long as a feature reads it**, and removing
    a key deletes what that key fetched.

## Tried and removed

- **Screener ranking**: computed scores plus an automatic digest of the top
  few. Ordering a list is a judgment; the reader makes it.
- **Scraped and undocumented sources**, including an unofficial finance API
  and a public crypto feed, removed entirely rather than kept behind a
  setting. The reason is legal exposure, not cost.
- **A hosted AI agent runtime.** Running an agent process per reader was
  built and dropped: readers' own agents already have browsing, memory and a
  subscription, and each process measured 300–420 MB resident. Readers
  connect their own agent over MCP instead.
- **The language model itself.** It labelled news, wrote an earnings box and
  extracted guidance — on a key most readers never added. All of it went,
  with its provider seam, caches and token meter. AlphaDesk runs no
  generative model: it hands whole documents to the reader's agent.
- **An AI-written news search.** Search is one rule, in code, mirrored in the
  frontend: whole words in order, with plurals and a short alias list.
- **A component library** (shadcn/ui and its dependencies): the bundle fell
  from 326 kB to 245 kB when it went. The primitives are hand-rolled, and
  reintroducing a library will be reverted.
- **A charting library**, replaced by SVG rendered from our own scales. The
  reason was control, not appearance. Candles are batched into four paths, so
  the node count does not grow with the number of bars.
- **Persisted chart drawings.** Drawings live on the chart page for one
  visit; people draw something, forget it, and find it weeks later.

## Design rules worth knowing before a pull request

- **Match the existing design system.** Buttons come from one helper, menus
  from shared classes, sizes from six type roles, spacing from a 4-pixel
  grid, colours from tokens. Do not introduce a new size or a one-off style.
- **Check every visual change at 375 pixels wide and at 1440.**
- **Widgets and providers register themselves.** Add a tile or a data source
  on its seam; do not edit the dashboard or the ingest layer to special-case
  it.
- **Background work never competes with requests.** Anything using CPU in the
  background runs on one thread, at low priority, while no request is being
  served. A 2-vCPU container reports more cores than it has: sizing threads
  from the reported count once starved the web server on the live service.
- **Every dependency must be permissively licensed** (MIT, ISC, BSD, Apache
  2.0). No copyleft dependency may be added; it would rule out the commercial
  licence that funds the project.
- **Comments explain why**, especially where the obvious approach was tried
  and rejected. Much of this codebase is the second attempt at something, and
  the note saying so is what stops it being undone.

## Proposing something on this list

Open an issue saying what you would change, what evidence you have, and what
you measured. A decision here was made on evidence and can be changed by
evidence.
