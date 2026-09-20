"""Provider contracts.

These are `Protocol`s, not base classes, on purpose: a provider is anything
with the right shape. A third-party package doesn't import an AlphaDesk class
or inherit from it — it writes a plain object and registers it. That keeps the
dependency arrow pointing one way and means a provider can be tested with no
AlphaDesk imports at all.

Every method here is allowed to fail by raising `ProviderError`. Callers treat
that as "this source had nothing for me" and degrade — they never let a
provider failure take down a page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


class ProviderError(Exception):
    """A provider could not fulfil a request.

    The one exception type every provider raises. Callers catch this and drop
    the item; they must never have to know which vendor SDK is underneath or
    which of its twelve exception types leaked out.
    """


class NeedsKey(ProviderError):
    """No vendor the user connected answers this surface (2026-09-13: all
    market data comes from the user's own keys). Carries the surface id and
    the vendors of the user's that refused it on plan, so the route can
    answer with the prompt a panel renders — which vendors would fill it,
    free or paid — instead of an error string. The web layer maps it to
    HTTP 428 with `{"detail": {"needs_key": prompt}}`."""

    def __init__(self, surface: str, refused: list[str] | None = None, signed_in: bool = True,
                 connected: list[str] | None = None) -> None:
        self.surface = surface
        self.refused = list(refused or [])
        self.signed_in = signed_in
        # The reader's OWN vendors, so the prompt can leave out a key they
        # already hold (2026-09-20). None when the raiser does not know.
        self.connected = list(connected) if connected is not None else None
        try:
            from alphadesk.providers.catalogue import SURFACES
            label = SURFACES[surface].label if surface in SURFACES else surface
        except Exception:                              # pragma: no cover
            label = surface
        super().__init__(f"{label} needs a key — connect one on the Account page")

    def prompt(self) -> dict:
        from alphadesk.providers.catalogue import prompt
        return prompt(self.surface, refused=self.refused, signed_in=self.signed_in,
                      connected=self.connected)


class EntitlementError(ProviderError):
    """The key works but its PLAN does not cover this request — a 401/402/403
    from the vendor, or a "premium" refusal in the body. A ProviderError, so
    every existing catch that drops an item still drops it; distinct, so the
    chart can say "your plan does not include this" instead of "no bars" and
    the endpoint can try a coarser bar the plan does serve."""



@dataclass(slots=True)
class Article:
    """One news item, normalized across feeds.

    `symbols` is the load-bearing field: the screener groups the whole window
    by ticker, so a feed that cannot tag an article with the symbols it is
    about cannot back this app. If a provider only does per-symbol queries, it
    should fill this in itself from the query it made.
    """

    id: str
    title: str
    url: str
    published_at: str          # ISO 8601
    symbols: list[str]
    summary: str = ""
    source: str = ""           # publisher name, not the provider name
    # Best-effort extras the reader renders when a feed carries them. A feed
    # without them still backs the app — they are presentation, not identity.
    image_url: str = ""
    author: str = ""
    # The full article text, PLAIN TEXT, when the feed licenses and delivers
    # it (Alpaca's Benzinga content does; Polygon's feed does not carry a
    # body at all). Providers strip the publisher's HTML before setting this —
    # the field is rendered verbatim in the reader, so nothing executable and
    # no markup may survive into it. Empty means "the feed carries summaries";
    # the reader then shows the summary and links out.
    body: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class NewsProvider(Protocol):
    """A source of ticker-tagged news."""

    name: str

    # What this feed DELIVERS, from: "summaries", "full_bodies", "images",
    # "bylines". The UI never branches on the provider name — each article
    # says what it carries — but the declaration is read for FRAMING: the
    # reader's closing line and the settings surface state what the
    # configured key unlocks, so a thinner reader is explained where the key
    # is chosen rather than discovered as a mystery. Declare only what the
    # feed actually ships; an optimistic declaration is a broken promise on
    # the settings screen.
    capabilities: tuple[str, ...]

    def fetch(self, since: datetime, limit: int = 200) -> list[Article]:
        """Articles published at or after `since`, NEWEST FIRST.

        Newest-first matters: callers apply a hard cap, so the only correct
        thing to sacrifice under that cap is the oldest news. Return an empty
        list rather than raising when the feed simply has nothing.
        """
        ...


@runtime_checkable
@runtime_checkable
class TranscriptProvider(Protocol):
    """What a company said about a quarter, as a document: the earnings
    call transcript from a vendor that records calls, or — the free,
    keyless default — the results press release the company itself files
    as Exhibit 99.1 to its results 8-K on EDGAR. `kind` says which, so the
    UI can label a release as a release and never call it a transcript.
    """

    name: str
    kind: str          # "call" (a recorded call) | "release" (the filed press release)

    def list_transcripts(self, symbol: str) -> list[dict]:
        """Every document on record for the symbol, newest first:
        [{id, date, title, period_end}], `period_end` the ISO end of the
        quarter it covers when the source knows it, else None. Empty when
        the source has nothing; never raises for an unknown symbol."""
        ...

    def transcript(self, symbol: str, id: str) -> dict | None:
        """One document: {id, symbol, date, title, period_end, url, text},
        text as plain prose (a call as "Speaker: words" paragraphs). None
        when the id is unknown or the fetch fails."""
        ...


class PriceProvider(Protocol):
    """Quotes, bars and company data.

    The widest of the three interfaces, because it backs the chart, the
    earnings page and the research answers. Every method may return None to
    mean "not available from this source" — the UI already renders absence
    honestly (see the chart's data-quality gate), so a partial provider is
    usable rather than broken.
    """

    name: str

    def context(self, symbol: str) -> dict | None:
        """Last price, change, volume, ATR%, liquidity flags."""
        ...

    def chart_series(self, symbol: str, days: int = 2,
                     range_key: str | None = None,
                     interval: str | None = None,
                     before: datetime | None = None,
                     need: int | None = None) -> dict | None:
        """OHLC plus indicator series AND the coverage statistics that say
        whether those indicators can be trusted. A provider that cannot report
        coverage should report it as unreliable rather than omit it.

        `range_key` is one of 1D/5D/1M/3M/6M/YTD/1Y/5Y/MAX and selects the
        SERIES, not merely its length — a provider is expected to switch from
        intraday to daily bars past the reach of its minute feed rather than
        return a sparse intraday series stretched over a year.

        `interval` is the requested bar size (1m/2m/5m/15m/30m/1h/4h/1d/1wk/1mo)
        and is a PREFERENCE, not a demand: a provider whose feed cannot cover
        the range at that resolution should serve a coarser one and say which
        it served, rather than refusing or silently pretending. None means the
        provider picks.

        `before` asks for a HISTORY PAGE: the bars strictly before that
        instant, one range-span deep, at the interval the first page served.
        The reader panning left past the oldest bar asks for it; an empty
        page (or None) is the end of the history. A provider that cannot
        page may ignore it and return None."""
        ...

    def chart_intervals(self) -> dict[str, dict]:
        """The bar intervals this provider serves and how far back each
        reaches: {id: {n, unit, max_days, label}} in ingest.prices'
        CHART_INTERVALS shape. The toolbar offers exactly this; the
        range/interval policy caps with it. A provider with second bars
        declares them; one without does not pretend."""
        ...

    def fundamentals(self, symbol: str) -> dict | None: ...
    def institutional_ownership(self, symbol: str) -> dict | None: ...
    def earnings_context(self, symbol: str) -> dict | None: ...

    def earnings_insights(self, symbol: str) -> dict | None:
        """Analyst consensus for the four estimate periods — current quarter,
        next quarter, current year, next year: {symbol, periods: [{period,
        label, eps, revenue}]}, where eps and revenue are each {analysts, avg,
        low, high} or None. Report only the periods the source actually
        covers — an absent period beats a row of nulls — and None when it
        covers none. These are FORECASTS, the one place this terminal shows
        one; label them as consensus, never as the company's own numbers."""
        ...

    def earnings_history(self, symbol: str) -> dict | None:
        """The full report record, newest first, the next scheduled report
        on top: {symbol, reports: [{date, upcoming, eps_estimate, eps_actual,
        surprise_pct, revenue, revenue_estimate}]}. Revenue is the quarter
        the report covered, in raw dollars; a source that carries only EPS
        leaves revenue None. The upcoming row carries estimates only. None
        when the source has no record."""
        ...

    def corporate_actions(self, symbol: str) -> dict | None:
        """Cash dividends and stock splits on record for one symbol:
        {dividends: [{ex_date, amount, currency, declaration_date,
        record_date, payment_date}], splits: [{date, from, to}]}, newest
        first, dates ISO. A source that knows only the ex-date and amount
        leaves the other dates None — the route fills them from a keyed
        source that carries them (ingest/corporate_actions.py) rather than
        any provider guessing. None when the source has nothing."""
        ...

    def category_movers(self, category: str, top: int = 20) -> dict | None:
        """A movers category on this provider's own feed — "stocks",
        "crypto", "etfs", "mutual_funds", "options", "indices", "futures",
        "bonds" or "currencies": {tabs: [{id, label, rows: [{symbol, display,
        name, price, change_pct, volume}]}]}. None for a category the feed
        does not carry — the free path (ingest/movers.py) then answers it
        — so a keyed feed replaces what it can and nothing else. Rows
        carry the day's figures; the twenty-session statistics are added
        by the route from the same source it uses for everyone."""
        ...

    def economic_calendar(self, start: str, end: str) -> list[dict] | None:
        """Scheduled economic releases between two ISO dates, inclusive:
        [{time, country, event, impact, actual, estimate, previous, unit}],
        `time` an ISO datetime in UTC (or a bare date when the source gives
        none), `impact` "low" | "medium" | "high" | None, the three figures
        floats or None. None for a feed that does not carry a calendar —
        the route then says which key would, rather than showing an empty
        week as if nothing were scheduled."""
        ...

    def macro(self) -> dict | None: ...
    def sector_change_pct(self, sector: str | None) -> float | None: ...

    def quote(self, symbol: str) -> dict | None:
        """The equity-overview readout — price, bid/ask, ranges, valuation
        multiples, analyst targets. None if the source cannot price it."""
        ...

    def movers(self, top: int = 20) -> dict:
        """{most_active, gainers, losers}. Implementations should filter out
        instruments that are arithmetically large movers but informationally
        empty (sub-dollar tickers, warrants, near-zero turnover)."""
        ...

    def market_tape(self) -> list[dict]:
        """The index/commodity/crypto strip: [{symbol, label, price, change_pct}].
        Omit a symbol you cannot price rather than reporting it as zero — a tape
        showing 0.00 reads as a crashed market, not a missing quote."""
        ...

    def index_board(self) -> list[dict]:
        """The cross-asset panel: same shape as market_tape() over a wider
        list. Same rule about omitting what you cannot price."""
        ...

    def option_expirations(self, symbol: str) -> list[str]:
        """Upcoming expiries, soonest first. An empty list means the symbol has
        no listed options — a real answer, not a failure."""
        ...

    def option_chain(self, symbol: str, expiry: str) -> dict:
        """{symbol, expiry, calls, puts}, each row {strike, bid, ask, last, mid,
        open_interest}. Order by STRIKE ascending on both sides: a chain is a
        price ladder and any other order destroys its only structure."""
        ...

    def crypto_movers(self, top: int = 20) -> dict:
        """{all, most_active, gainers, losers} for crypto, each
        [{symbol, name, price, change_pct, volume, spark}]. Measure change over
        a rolling 24 hours: a 24/7 market has no close, so a previous-close
        figure would disagree with every venue the reader can check."""
        ...
