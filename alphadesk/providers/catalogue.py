"""Which vendor serves which surface — the one table the data router, the
"add a key" prompts and the Account page all read (2026-09-13).

AlphaDesk carries no market data of its own. Every figure on a market-data
panel comes from a vendor the signed-in user keyed on the Account page; the
only keyless sources are public US government data (SEC EDGAR, the US
Treasury), which are free to redistribute. So for each surface the platform
needs two facts: which vendors can answer it, in the order they are asked,
and whether a vendor's free plan covers it or only a paid one. A panel with
no connected vendor shows that list instead of data.

`tier` is what the vendor's own plan page says as of 2026-09-13, and it is
guidance for the prompt, not enforcement: a call a plan refuses surfaces as
a plan refusal at request time whatever this table says.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vendor:
    name: str
    label: str
    signup: str
    needs_secret: bool = False
    note: str = ""
    kind: str = "data"          # data | news | model — which Account section it belongs to


VENDORS: dict[str, Vendor] = {
    v.name: v for v in (
        Vendor("alpaca", "Alpaca", "https://app.alpaca.markets/signup", needs_secret=True,
               note="Free key: live US stock prices from one exchange (IEX), charts 15 minutes behind, movers, options, crypto. "
                    "Algo Trader Plus: real-time prices, charts and options from every exchange."),
        Vendor("finnhub", "Finnhub", "https://finnhub.io/register",
               note="Free key: quotes, company profile, key metrics, earnings calendar and record, peers, analyst ratings."),
        Vendor("polygon", "Polygon", "https://polygon.io/dashboard/signup",
               note="Free key: end-of-day bars, dividends and splits, financials. Paid: real-time snapshots and movers."),
        Vendor("alphavantage", "Alpha Vantage", "https://www.alphavantage.co/support/#api-key",
               note="Free key (25 calls a day): company overview, earnings, calendar, dividends and splits, daily bars."),
        Vendor("fmp", "Financial Modeling Prep", "https://site.financialmodelingprep.com/register",
               note="Paid plans: analyst targets and rating changes, estimates, fund holdings, institutional ownership, "
                    "earnings and economic calendars."),
        Vendor("coingecko", "CoinGecko", "https://www.coingecko.com/en/developers/dashboard",
               note="Free demo key: crypto markets by market cap, coin profiles."),
    )
}

# News vendors are keyed in their own Account section; they are listed here
# so a prompt can name them with a signup link. (The model vendors went with
# the model, 2026-09-17; removed from this list 2026-09-18.)
PROMPT_VENDORS: dict[str, Vendor] = {
    v.name: v for v in (
        # Finnhub's general feed carries almost no tickers, and the window keeps
        # only tagged stories (measured 2026-09-13: 0 of 100), so it is listed last.
        Vendor("news:finnhub", "Finnhub", "https://finnhub.io/register", kind="news",
               note="Free key: general market news, rarely tagged with companies, so few stories reach the window."),
        Vendor("news:fmp", "Financial Modeling Prep", "https://site.financialmodelingprep.com/register", kind="news",
               note="Starter plan and up: stock news across many publishers, each story tagged with its company."),
        Vendor("news:marketaux", "Marketaux", "https://www.marketaux.com/register", kind="news", note="Free key."),
        Vendor("news:polygon", "Polygon", "https://polygon.io/dashboard/signup", kind="news", note="Free key: ticker news."),
        Vendor("news:alpaca", "Alpaca", "https://app.alpaca.markets/signup", kind="news", needs_secret=True, note="Free key: Benzinga headlines."),
        Vendor("news:tiingo", "Tiingo", "https://www.tiingo.com/account/api/token", kind="news"),
    )
}

FREE, PAID = "free", "paid"


@dataclass(frozen=True)
class Surface:
    id: str
    label: str
    vendors: tuple[tuple[str, str], ...]     # (vendor name, tier), in asking order


SURFACES: dict[str, Surface] = {
    s.id: s for s in (
        Surface("chart", "Price chart", (("alpaca", FREE), ("polygon", FREE), ("alphavantage", FREE), ("finnhub", PAID))),
        Surface("quote", "Quote", (("alpaca", FREE), ("finnhub", FREE), ("polygon", PAID), ("alphavantage", FREE))),
        Surface("stream", "Live prices", (("alpaca", FREE),)),
        Surface("stock_movers", "Stock movers", (("alpaca", FREE), ("polygon", PAID))),
        Surface("etf_movers", "ETF movers", (("alpaca", FREE), ("polygon", PAID))),
        Surface("index_board", "Market tape", (("alpaca", FREE), ("polygon", PAID))),
        Surface("crypto", "Crypto", (("coingecko", FREE), ("alpaca", FREE))),
        # FMP first: its quotes answer on Premium (2026-09-15, 12 pairs in
        # 0.09s); Polygon's forex snapshot has not been run on a paid key.
        Surface("currencies", "Currencies", (("fmp", PAID), ("polygon", PAID))),
        Surface("options", "Options", (("alpaca", FREE),)),
        # FMP first where its record is the fuller one (measured 2026-09-14 on
        # a Premium key against the free vendors it overlaps): a vendor a
        # reader PAID for answers before a free one that carries less. A
        # plan that refuses a call still falls through to the next vendor.
        Surface("key_stats", "Key statistics", (("fmp", PAID), ("finnhub", FREE), ("alphavantage", FREE))),
        Surface("compare", "Comparison metrics", (("finnhub", FREE), ("alphavantage", FREE), ("fmp", PAID))),
        Surface("peers", "Peers", (("fmp", PAID), ("finnhub", FREE))),
        # FMP first: it carries 24 monthly snapshots where Finnhub's free
        # plan carries four, so a reader paying for it gets the history
        # (the owner's call, 2026-09-15). The two map house ratings onto
        # the five buckets differently, so the counts change with the
        # vendor — the panel names whichever answered.
        Surface("analyst_ratings", "Analyst ratings", (("fmp", PAID), ("finnhub", FREE), ("alphavantage", FREE))),
        Surface("price_targets", "Price targets", (("fmp", PAID), ("finnhub", PAID), ("alphavantage", FREE))),
        Surface("rating_changes", "Rating changes", (("fmp", PAID), ("finnhub", PAID))),
        # FMP has no short-interest record at all — its stable API answers
        # 404 (measured 2026-09-15) — so naming it sent readers to a plan
        # that could never fill the panel.
        Surface("short_interest", "Short interest", (("finnhub", PAID),)),
        # Alpha Vantage's ETF_PROFILE (2026-09-18): holdings and sector weights
        # on an ETF, where FMP keeps the holdings list on Ultimate and Finnhub
        # on a paid plan. Asked last: FMP's profile and descriptions answer
        # first, and funds.py fills a refused holdings list from here.
        Surface("fund_holdings", "Fund holdings", (("fmp", PAID), ("finnhub", PAID), ("alphavantage", FREE))),
        Surface("institutional", "Institutional ownership", (("finnhub", PAID),)),
        # FMP: 92 Apple dividends with declaration, record and payment dates; Polygon free: 57.
        Surface("corporate_actions", "Dividends and splits", (("fmp", PAID), ("polygon", FREE), ("alphavantage", FREE), ("finnhub", PAID))),
        # FMP: 165 Apple reports with revenue; Finnhub free: the last 4.
        Surface("earnings_history", "Earnings history", (("fmp", PAID), ("alphavantage", FREE), ("finnhub", FREE))),
        Surface("earnings_estimates", "Earnings estimates", (("alphavantage", FREE), ("fmp", PAID), ("finnhub", PAID))),
        # FMP first: its DATES were right for 63 of 65 quarterly reports against
        # EDGAR's release days (Sep 1–11, 2026), Finnhub's for 59. The first
        # vendor's date stands; Finnhub still supplies the time — it named
        # before/after the market for 58 and was right on 57 — because the
        # union takes a confirmed session from any vendor when the first has none.
        Surface("earnings_calendar", "Earnings calendar", (("fmp", PAID), ("finnhub", FREE), ("alphavantage", FREE))),
        Surface("economic_calendar", "Economic calendar", (("finnhub", PAID), ("fmp", PAID))),
        # FMP's "corporate calendars" (Premium and up), measured 2026-09-14.
        Surface("press_releases", "Company press releases", (("fmp", PAID),)),
        Surface("dividend_calendar", "Dividend calendar", (("fmp", PAID),)),
        Surface("split_calendar", "Stock split calendar", (("fmp", PAID), ("alpaca", FREE))),
        Surface("market_caps", "Market capitalisation, many companies at once", (("fmp", PAID),)),
        Surface("etf_list", "Which listed symbols are funds", (("fmp", PAID),)),
        Surface("sector_weights", "S&P 500 sector weights", (("fmp", PAID),)),
        Surface("sector_companies", "Companies by sector", (("fmp", PAID),)),
        Surface("sp500", "S&P 500 members", (("fmp", PAID),)),
        Surface("day_changes", "Today's change for many stocks at once", (("alpaca", FREE),)),
        Surface("ipo_calendar", "IPO calendar", (("fmp", PAID),)),
        Surface("company_profile", "Company profile", (("fmp", PAID), ("alphavantage", FREE), ("finnhub", FREE), ("coingecko", FREE))),
        # A COIN's record comes from a coin vendor alone: naming the company
        # feeds would send a reader to a key that cannot answer (2026-09-15).
        Surface("coin_profile", "Coin profile", (("coingecko", FREE),)),
        # Alpaca first: the reader's chain snapshots over the most traded
        # option markets (OPRA on a paid plan, the indicative feed otherwise).
        Surface("option_movers", "Option movers", (("alpaca", FREE), ("polygon", PAID))),
        Surface("news", "News", (("news:alpaca", FREE), ("news:polygon", FREE), ("news:fmp", PAID), ("news:marketaux", FREE),
                                  ("news:tiingo", PAID), ("news:finnhub", FREE))),
    )
}

# The contract method each router call maps to its surface. Methods absent
# here are not routed (a vendor's own attribute like `name`).
METHOD_SURFACE: dict[str, str] = {
    "chart_series": "chart", "chart_intervals": "chart", "daily_history": "chart",
    "quote": "quote", "quotes": "quote", "context": "quote",
    "movers": "stock_movers", "market_tape": "index_board", "index_board": "index_board",
    "crypto_movers": "crypto", "crypto_bars": "crypto", "crypto_daily_history": "crypto", "crypto_symbols": "crypto", "fx_daily_history": "currencies",
    "option_expirations": "options", "option_chain": "options", "option_active_contracts": "options",
    "option_trades": "options", "option_latest_quotes": "options", "option_movers": "option_movers",
    "fundamentals": "key_stats", "key_stats": "key_stats", "compare_metrics": "compare",
    "peers": "peers", "analyst_ratings": "analyst_ratings", "price_targets": "price_targets",
    "rating_changes": "rating_changes", "short_interest": "short_interest",
    "fund_holdings": "fund_holdings", "institutional_ownership": "institutional",
    "corporate_actions": "corporate_actions",
    "earnings_history": "earnings_history", "earnings_context": "earnings_history",
    "earnings_insights": "earnings_estimates",
    "earnings_calendar": "earnings_calendar", "economic_calendar": "economic_calendar",
    "company_profile": "company_profile",
    "press_releases": "press_releases", "dividend_calendar": "dividend_calendar", "split_calendar": "split_calendar", "ipo_calendar": "ipo_calendar", "market_caps": "market_caps",
    "etf_symbols": "etf_list", "fund_names": "etf_list", "sector_weights": "sector_weights", "sector_companies": "sector_companies",
    "sp500_constituents": "sp500",
    "day_changes": "day_changes",
}

# Category movers route to their own surface.
MOVER_SURFACE: dict[str, str] = {
    "stocks": "stock_movers", "etfs": "etf_movers", "indices": "index_board", "crypto": "crypto",
    "currencies": "currencies", "options": "option_movers", "bonds": "",   # bonds: US Treasury, keyless
}


def _vendor(name: str) -> Vendor | None:
    return VENDORS.get(name) or PROMPT_VENDORS.get(name)


def prompt(surface_id: str, *, refused: list[str] | None = None, signed_in: bool = True) -> dict:
    """The body a panel renders when no connected vendor answered: what the
    surface is, which vendors would, each with its tier and signup link, and
    which of the user's own vendors refused it on plan. JSON-safe."""
    s = SURFACES.get(surface_id)
    if s is None:
        return {"surface": surface_id, "label": surface_id, "vendors": [], "refused": refused or [], "signed_in": signed_in}
    return {
        "surface": s.id, "label": s.label, "signed_in": signed_in,
        "refused": [VENDORS[r].label if r in VENDORS else r for r in (refused or [])],
        "vendors": [{"name": n.split(":")[-1], "label": _vendor(n).label, "tier": tier, "signup": _vendor(n).signup,
                     "needs_secret": _vendor(n).needs_secret}
                    for n, tier in s.vendors if _vendor(n) is not None],
    }
