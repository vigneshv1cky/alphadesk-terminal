# Contributing

AlphaDesk is open source under the GNU AGPL-3.0 and also offered under a
commercial licence (see the Licence section of the README). This guide is
for people working in the repository.

**Contributor licence agreement.** Because the project is dual-licensed,
every contribution must come with a signed
[contributor licence agreement](CLA.md) that lets the copyright holder offer
it under both licences. You keep the copyright in your work. Sign once, on
your first pull request, by posting the sentence in section 7 of the
agreement as a comment; an automatic check records it and marks the pull
request. A pull request without a signature cannot be merged. Before changing behaviour, read **[DECISIONS.md](DECISIONS.md)** and
open an issue: much of what might look missing was built, measured and
removed on purpose. Found a vulnerability? **[SECURITY.md](SECURITY.md)** —
never a public issue.

## Setup

```bash
pip install -r requirements.txt
cp alphadesk/deploy/env.example .env      # set ALPHADESK_VAULT_KEY and SEC_USER_AGENT
python -m pytest -q                       # should be green before you start
cd alphadesk/ui && pnpm install
```

For local work without sign-in, set `ALPHADESK_AUTH=off` in `.env`, add your
own vendor keys there, and seal them into the local account:

```bash
python -m alphadesk.main keys import-env
```

The first start downloads the search-by-meaning model (about 1.2 GB) into the
Hugging Face cache; set `ALPHADESK_SEMANTIC_SEARCH=off` to skip it.

## Running it

```bash
python -m alphadesk.main dashboard       # API + built SPA on :8000
cd alphadesk/ui && pnpm dev              # frontend with hot reload, proxies /api
```

The terminal works with partial configuration. A panel that none of the
reader's connected vendors carries answers HTTP 428 and names the vendors
and plans that would fill it; without a news key the news window names the
feeds that would. That degradation is a feature — keep it when adding
things. Never answer a missing vendor with an empty 200: an empty panel
reads as "no data exists".

## Checks

Continuous integration runs these on every pull request; run them locally
first:

```bash
python -m pytest -q
python -m ruff check alphadesk
cd alphadesk/ui && pnpm test && pnpm build   # pnpm build runs tsc -b, then vite build
```

**`npx tsc --noEmit` checks nothing in this repo.** The root `tsconfig.json`
is `files: []` with project references, so it exits 0 on code that cannot
compile. Use `tsc -b` (what `pnpm build` runs).

Run the full test suite, not just the file you changed: a test that
disturbs shared state can make an unrelated test fail one run in three.

## Adding a data source

Write a **provider**, don't edit `ingest/`. See
[docs/providers.md](docs/providers.md). A provider is a plain object matching
a `Protocol`, registered by name, built per reader from that reader's key —
no subclassing. Then:

- List the surfaces it carries in `providers/catalogue.py`, in the order the
  router should ask vendors.
- Document the source, how it is collected and its terms in
  [docs/data-sources.md](docs/data-sources.md).
- Never add a keyless path to a commercial vendor or an unofficial endpoint,
  and never read a vendor key from the server's environment.
- Key every cache that holds vendor data by the reader.

## Adding a dashboard tile

Write a component that fetches its own data and call `registerWidget` — see
`ui/src/widgets/`. Don't edit `DashboardPage`; it renders whatever is
registered, and that's deliberate.

Use the shared query hooks in `lib/queries.ts`. Two tiles asking for the same
endpoint share one request and one cache entry; a hand-rolled `setInterval`
would re-fetch it separately.

## House rules

**Nothing is paraphrased.** Every panel and agent tool shows what a vendor or
EDGAR actually said, with its source. No model writes, summarises or scores
anything here; the only model is the self-hosted embedding model used to
find related news.

**Don't fix the data-quality gate by drawing anyway.** When bar coverage is
too sparse, indicators are hidden on purpose. A misleading chart is worse
than no chart because it recruits the reader's judgment.

**Don't rank.** Sorting a column is the reader choosing; ordering by default
is the app deciding for them. Search results are newest first even when a
model decided what is related.

**Follow the design system.** There is no component library, and
reintroducing one will be reverted. Buttons come from `btnCls()`, menus from
`menuPanelCls` / `menuItemCls`, sizes from the six type roles and the 4-pixel
spacing grid, colours from the tokens in `index.css`. Override classes
through `cn()`, never by string concatenation. Check every visual change at
375 pixels (phone) and 1440 (desktop).

**Background work never competes with requests.** Anything that uses CPU in
the background runs on one thread, at low priority, while no request is being
served — a container reports more cores than it has. Ship it switched off,
then switch it on in production and watch.

## Style

Python targets 3.11+ with type hints on public functions. TypeScript is
strict.

Comments explain **why**, especially where the obvious approach was tried and
rejected — much of this codebase is the second attempt at something, and the
note saying so is what stops it being undone. Don't add comments that restate
the code.

Every dependency must be under a permissive licence (MIT, BSD, Apache 2.0).
No copyleft dependency may be added: it would rule out the commercial
licence.

## Commits and pull requests

One logical change per commit. The message says what changed and *why*,
including what you measured if the change is a judgment call. If you remove
something, say what you verified still works.
