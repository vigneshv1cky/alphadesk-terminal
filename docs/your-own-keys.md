# Why AlphaDesk uses your own data keys

Most market terminals sell you the data. AlphaDesk does not have any. You
connect the providers you already pay for, and every request runs on your
account with that provider.

This page explains what that buys you, what it costs you, and where it is
the wrong choice.

## What it buys you

**No markup.** A terminal that bundles data has to charge for it, and has to
charge more than it pays. AlphaDesk never touches the bill, so there is
nothing to mark up. You pay the vendor their price, and nothing for the
software.

**Your entitlements, not an average.** What you see is what your plan
allows. Pay for the consolidated tape and you read the consolidated tape.
Pay for a premium calendar and you get its fields. Nobody is throttling you
because a shared key is being spread across thousands of strangers — there
is no shared key.

**A working terminal before you pay anyone.** SEC EDGAR and the US Treasury
are public government data and need no key at all, which covers filings and
their full text, XBRL financial statements, Form 4 insider trades, company
profiles and the yield curve. That is a real product on a fresh install.

**No lock-in.** Connect several vendors and each panel asks yours in the
order that suits it, taking the first that carries the figure. Add one,
remove one, change plan — the board does not change shape. Removing a key
deletes what it fetched.

**Separation by construction.** Keys are sealed with AES-256-GCM under a key
you hold. Every cache that holds vendor data is keyed by the reader, so one
reader's entitlement can never answer another's request, and your data is
never pooled into a feed served to other people.

## What it costs you

**Setup.** You need accounts with the vendors you want, and you paste keys
on the Account page. A free Alpaca key covers a great deal; several vendors
have free tiers.

**Your own bill.** If you want premium data, you pay for premium data.
AlphaDesk cannot make a cheap plan behave like an expensive one.

**Coverage depends on your vendors.** A panel none of your connected vendors
carries will say so plainly, and name the vendors and plans that would fill
it, rather than showing an empty box.

## Where it is the wrong choice

If you want one invoice, a support line and somebody else's licence covering
your data, a commercial terminal is a better fit. Bring-your-own-key trades
that convenience for control, cost and privacy.

## What each vendor can fill

| Vendor | What it carries |
|---|---|
| **Alpaca** (free key works) | Charts on the consolidated tape, quotes, live stock and crypto streams, movers, market ETFs, option chains with implied volatility, split calendar |
| **Financial Modeling Prep** | Key statistics, peers, grades, price targets, ETF holdings, dividends and splits, earnings and economic calendars, press releases |
| **Finnhub** | Key statistics, comparison, peers, analyst ratings, earnings history and calendar, company profiles; more on paid plans |
| **Polygon** | Charts, quotes, dividends and splits, news; currencies and option movers on paid plans |
| **Alpha Vantage** | Key statistics, analyst ratings, estimates, earnings calendar, company profiles, ETF holdings |
| **CoinGecko** | The crypto list and coin profiles, worldwide prices and turnover |
| **News feeds** (Polygon, Finnhub, Alpaca, Marketaux, Tiingo and more) | Your news window, merged across whichever you key |
| **SEC EDGAR, US Treasury** | **No key.** Filings and their text, financial statements, insider trades, yield curve |

## A note on vendor terms

Your agreement with each vendor governs the data it returns. Plans differ —
some are personal-use only, some restrict showing data to other people, some
restrict storage. Read your plan before running an instance that other
people use. Each vendor's terms are linked in
[data-sources.md](data-sources.md).

## How it works underneath

Every request resolves the signed-in reader first, then that reader's
connected vendors. A provider is a small object that takes a key explicitly
— there is no environment fallback, and the server holds no keys of its own.
A method that returns nothing means "this vendor does not carry it", and the
next vendor is asked. When none does, the panel answers with a prompt naming
the vendors and plans that would.

See [providers.md](providers.md) to add a vendor of your own.
